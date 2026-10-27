"""The closed ``Operation`` set and the typed ``OperationBatch`` (contracts §2, §6).

Required semantic operations: ``InsertOccurrence | TrimOccurrence | MoveOccurrence |
SetConstantSpeed | RetimeOccurrence | AddTransition | SetAudioMix | AddTitle | ShiftTitle |
SetCaptions | BindSubjectEffect | RevertOperation``. Descriptor-bound: ``AddGeneratedSource |
AddLayer | AddAudioTrack | AddLink | BindEffect | SetParameter | SetKeyframes |
SetTransitionSettings | SetOutputProfile | UnbindEffect``. Lifecycle: ``RebindAsset |
RecompileWithNewCatalog`` (``ImportSnapshot`` and ``Migrate`` are ledger events, not batch
operations). Inverse-only removals (``RemoveOccurrence | RemoveTransition | RemoveTitle |
RemoveGeneratedSource | RemoveLayer | RemoveAudioTrack | RemoveAsset | UnsetParameter``)
exist because every operation must have an inverse; they are ordinary validated operations
(recorded as a contract refinement in docs/evidence/milestone-1.md).

Semantics live in :mod:`aidashvideo.project.apply`; this module is data and wire form.
"""

from __future__ import annotations

from dataclasses import dataclass

from aidashvideo.ledger.canonical import (
    as_int,
    as_list,
    as_object,
    as_str,
    field,
    require_keys,
)
from aidashvideo.ledger.domain import (
    BatchEnvelope,
    Provenance,
    ToolCall,
    UserWording,
    provenance_from_json,
)
from aidashvideo.ledger.errors import ContractError, is_int, is_str, widen
from aidashvideo.ledger.grants import LocalUser
from aidashvideo.ledger.ids import EventKind, EventSeq, ProjectId, ReplayKey, RevisionId, Sha256
from aidashvideo.store.identity import ProbeReceipt

from .document import (
    AnalysisRef,
    AssetRef,
    AudioMix,
    Caption,
    ClipOccurrence,
    EffectBinding,
    GeneratedSource,
    MaskRef,
    NoMask,
    ObjectRef,
    OccurrenceTarget,
    OutputProfile,
    Transition,
)
from .params import Animated, ParamAssignment, assignments_from_json
from .text import LiteralText
from .timing import Constant, Normal, SequenceFrame, SourceSpan, Speed, TimeMap, timing_from_json


def _id(value: object, what: str) -> str:
    text = as_str(value, what)
    if not text or len(text) > 128 or not text.isprintable():
        raise ContractError(f"{what}: invalid identifier {text!r}")
    return text


def _check_id(value: str, what: str) -> None:
    if not is_str(value) or not value or len(value) > 128 or not value.isprintable():
        raise ContractError(f"{what}: invalid identifier {value!r}")


# ----------------------------------------------------------------------------- containers


@dataclass(frozen=True, slots=True)
class LayerRef:
    layer_id: str

    def __post_init__(self) -> None:
        _check_id(self.layer_id, "LayerRef.layer_id")

    def to_json(self) -> dict[str, object]:
        return {"kind": "Layer", "layer_id": self.layer_id}


@dataclass(frozen=True, slots=True)
class TrackRef:
    track_id: str

    def __post_init__(self) -> None:
        _check_id(self.track_id, "TrackRef.track_id")

    def to_json(self) -> dict[str, object]:
        return {"kind": "Track", "track_id": self.track_id}


type ContainerRef = LayerRef | TrackRef


def container_from_json(raw: object) -> ContainerRef:
    data = as_object(raw, "container")
    kind = as_str(field(data, "kind", "container"), "container.kind")
    if kind == "Layer":
        require_keys(data, "container", ("kind", "layer_id"))
        return LayerRef(_id(data["layer_id"], "layer_id"))
    if kind == "Track":
        require_keys(data, "container", ("kind", "track_id"))
        return TrackRef(_id(data["track_id"], "track_id"))
    raise ContractError(f"container: unknown kind {kind!r}")


# ----------------------------------------------------------------------------- undo choices


@dataclass(frozen=True, slots=True)
class DropDependent:
    """Remove an effect or transition that would dangle after the revert."""

    ref: ObjectRef

    def to_json(self) -> dict[str, object]:
        return {"kind": "DropDependent", "ref": str(self.ref)}


@dataclass(frozen=True, slots=True)
class RebindTo:
    """Re-target an effect to the named occurrence after the revert."""

    effect_id: str
    occurrence_id: str

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "RebindTo",
            "effect_id": self.effect_id,
            "occurrence_id": self.occurrence_id,
        }


@dataclass(frozen=True, slots=True)
class ForceRestore:
    """Accept that a later change to this object is overwritten by the revert."""

    ref: ObjectRef

    def to_json(self) -> dict[str, object]:
        return {"kind": "ForceRestore", "ref": str(self.ref)}


type UndoChoice = DropDependent | RebindTo | ForceRestore


def choice_from_json(raw: object) -> UndoChoice:
    data = as_object(raw, "UndoChoice")
    kind = as_str(field(data, "kind", "UndoChoice"), "UndoChoice.kind")
    if kind == "DropDependent":
        require_keys(data, "DropDependent", ("kind", "ref"))
        return DropDependent(ObjectRef.parse(as_str(data["ref"], "ref")))
    if kind == "RebindTo":
        require_keys(data, "RebindTo", ("kind", "effect_id", "occurrence_id"))
        return RebindTo(
            _id(data["effect_id"], "effect_id"), _id(data["occurrence_id"], "occurrence_id")
        )
    if kind == "ForceRestore":
        require_keys(data, "ForceRestore", ("kind", "ref"))
        return ForceRestore(ObjectRef.parse(as_str(data["ref"], "ref")))
    raise ContractError(f"UndoChoice: unknown kind {kind!r}")


# ----------------------------------------------------------------------------- operations


@dataclass(frozen=True, slots=True)
class InsertOccurrence:
    container: ContainerRef
    occurrence: ClipOccurrence

    def to_json(self) -> dict[str, object]:
        return {
            "op": "InsertOccurrence",
            "container": self.container.to_json(),
            "occurrence": self.occurrence.to_json(),
        }


@dataclass(frozen=True, slots=True)
class RemoveOccurrence:
    container: ContainerRef
    occurrence_id: str

    def to_json(self) -> dict[str, object]:
        return {
            "op": "RemoveOccurrence",
            "container": self.container.to_json(),
            "occurrence_id": self.occurrence_id,
        }


@dataclass(frozen=True, slots=True)
class TrimOccurrence:
    """New source interval; the placement keeps its start and derives its length."""

    occurrence_id: str
    source: SourceSpan

    def to_json(self) -> dict[str, object]:
        return {
            "op": "TrimOccurrence",
            "occurrence_id": self.occurrence_id,
            "source": self.source.to_json(),
        }


@dataclass(frozen=True, slots=True)
class MoveOccurrence:
    occurrence_id: str
    start: SequenceFrame

    def to_json(self) -> dict[str, object]:
        return {
            "op": "MoveOccurrence",
            "occurrence_id": self.occurrence_id,
            "start": self.start.to_json(),
        }


@dataclass(frozen=True, slots=True)
class SetConstantSpeed:
    occurrence_id: str
    speed: Speed

    def to_json(self) -> dict[str, object]:
        return {
            "op": "SetConstantSpeed",
            "occurrence_id": self.occurrence_id,
            "speed": self.speed.to_json(),
        }


@dataclass(frozen=True, slots=True)
class RetimeOccurrence:
    occurrence_id: str
    map: TimeMap

    def to_json(self) -> dict[str, object]:
        return {
            "op": "RetimeOccurrence",
            "occurrence_id": self.occurrence_id,
            "map": self.map.to_json(),
        }


@dataclass(frozen=True, slots=True)
class AddTransition:
    layer_id: str
    transition: Transition

    def to_json(self) -> dict[str, object]:
        return {
            "op": "AddTransition",
            "layer_id": self.layer_id,
            "transition": self.transition.to_json(),
        }


@dataclass(frozen=True, slots=True)
class RemoveTransition:
    layer_id: str
    transition_id: str

    def to_json(self) -> dict[str, object]:
        return {
            "op": "RemoveTransition",
            "layer_id": self.layer_id,
            "transition_id": self.transition_id,
        }


@dataclass(frozen=True, slots=True)
class SetTransitionSettings:
    transition_id: str
    duration_frames: int
    params: tuple[ParamAssignment, ...]

    def __post_init__(self) -> None:
        if not is_int(self.duration_frames) or self.duration_frames < 1:
            raise ContractError("SetTransitionSettings.duration_frames must be >= 1")

    def to_json(self) -> dict[str, object]:
        return {
            "op": "SetTransitionSettings",
            "transition_id": self.transition_id,
            "duration_frames": self.duration_frames,
            "params": [p.to_json() for p in self.params],
        }


@dataclass(frozen=True, slots=True)
class SetAudioMix:
    track_id: str
    mix: AudioMix

    def to_json(self) -> dict[str, object]:
        return {"op": "SetAudioMix", "track_id": self.track_id, "mix": self.mix.to_json()}


@dataclass(frozen=True, slots=True)
class AddTitle:
    """Start and duration are raw frame counts so a negative start is a typed rejection
    (``NegativeStart``) rather than an unparseable batch."""

    title_id: str
    text: LiteralText
    start_frame: int
    duration_frames: int
    style: str

    def __post_init__(self) -> None:
        if not is_int(self.start_frame) or not is_int(self.duration_frames):
            raise ContractError("AddTitle frames must be integers")

    def to_json(self) -> dict[str, object]:
        return {
            "op": "AddTitle",
            "title_id": self.title_id,
            "text": self.text.to_json(),
            "start_frame": self.start_frame,
            "duration_frames": self.duration_frames,
            "style": self.style,
        }


@dataclass(frozen=True, slots=True)
class RemoveTitle:
    title_id: str

    def to_json(self) -> dict[str, object]:
        return {"op": "RemoveTitle", "title_id": self.title_id}


@dataclass(frozen=True, slots=True)
class ShiftTitle:
    title_id: str
    delta_frames: int

    def __post_init__(self) -> None:
        if not is_int(self.delta_frames) or self.delta_frames == 0:
            raise ContractError("ShiftTitle.delta_frames must be a non-zero integer")

    def to_json(self) -> dict[str, object]:
        return {"op": "ShiftTitle", "title_id": self.title_id, "delta_frames": self.delta_frames}


@dataclass(frozen=True, slots=True)
class SetCaptions:
    """Replace the caption set (each caption cites transcript evidence)."""

    captions: tuple[Caption, ...]

    def to_json(self) -> dict[str, object]:
        return {"op": "SetCaptions", "captions": [c.to_json() for c in self.captions]}


@dataclass(frozen=True, slots=True)
class SubjectRequest:
    """What the provider is asked for; its result is a separately admitted mask track."""

    concept: LiteralText
    requested: SourceSpan
    profile: str
    """The only mask profile id (``sam31-mlx-metal``); recorded, never assumed qualified."""

    def __post_init__(self) -> None:
        _check_id(self.profile, "SubjectRequest.profile")

    def to_json(self) -> dict[str, object]:
        return {
            "concept": self.concept.to_json(),
            "requested": self.requested.to_json(),
            "profile": self.profile,
        }

    @classmethod
    def from_json(cls, raw: object) -> SubjectRequest:
        data = as_object(raw, "SubjectRequest")
        require_keys(data, "SubjectRequest", ("concept", "requested", "profile"))
        return cls(
            LiteralText.from_json(data["concept"]),
            SourceSpan.from_json(data["requested"]),
            _id(data["profile"], "profile"),
        )


@dataclass(frozen=True, slots=True)
class ExistingTrack:
    """Bind to a mask track that is already an analysis ref (no new provider request)."""

    def to_json(self) -> dict[str, object]:
        return {"kind": "ExistingTrack"}


def subject_request_from_json(raw: object) -> SubjectRequest | ExistingTrack:
    data = as_object(raw, "request")
    if data.get("kind") == "ExistingTrack":
        require_keys(data, "ExistingTrack", ("kind",))
        return ExistingTrack()
    return SubjectRequest.from_json(raw)


@dataclass(frozen=True, slots=True)
class BindSubjectEffect:
    binding: EffectBinding
    request: SubjectRequest | ExistingTrack

    def __post_init__(self) -> None:
        if not isinstance(widen(self.binding.mask), MaskRef):
            raise ContractError("BindSubjectEffect needs a MaskRef binding")
        if not isinstance(widen(self.binding.target), OccurrenceTarget):
            raise ContractError("BindSubjectEffect targets one occurrence")

    def to_json(self) -> dict[str, object]:
        return {
            "op": "BindSubjectEffect",
            "binding": self.binding.to_json(),
            "request": self.request.to_json(),
        }


@dataclass(frozen=True, slots=True)
class BindEffect:
    binding: EffectBinding

    def __post_init__(self) -> None:
        if not isinstance(widen(self.binding.mask), NoMask):
            raise ContractError("BindEffect carries no mask; use BindSubjectEffect")

    def to_json(self) -> dict[str, object]:
        return {"op": "BindEffect", "binding": self.binding.to_json()}


@dataclass(frozen=True, slots=True)
class AddLink:
    """A processing link (service type ``link``) on one occurrence."""

    binding: EffectBinding

    def __post_init__(self) -> None:
        if not isinstance(widen(self.binding.mask), NoMask):
            raise ContractError("AddLink carries no mask")
        if not isinstance(widen(self.binding.target), OccurrenceTarget):
            raise ContractError("AddLink targets one occurrence")

    def to_json(self) -> dict[str, object]:
        return {"op": "AddLink", "binding": self.binding.to_json()}


@dataclass(frozen=True, slots=True)
class UnbindEffect:
    effect_id: str

    def to_json(self) -> dict[str, object]:
        return {"op": "UnbindEffect", "effect_id": self.effect_id}


@dataclass(frozen=True, slots=True)
class SetParameter:
    effect_id: str
    assignment: ParamAssignment

    def to_json(self) -> dict[str, object]:
        return {
            "op": "SetParameter",
            "effect_id": self.effect_id,
            "assignment": self.assignment.to_json(),
        }


@dataclass(frozen=True, slots=True)
class SetKeyframes:
    effect_id: str
    assignment: ParamAssignment

    def __post_init__(self) -> None:
        if not isinstance(widen(self.assignment.value), Animated):
            raise ContractError("SetKeyframes needs an Animated assignment")

    def to_json(self) -> dict[str, object]:
        return {
            "op": "SetKeyframes",
            "effect_id": self.effect_id,
            "assignment": self.assignment.to_json(),
        }


@dataclass(frozen=True, slots=True)
class UnsetParameter:
    effect_id: str
    param_id: str

    def to_json(self) -> dict[str, object]:
        return {"op": "UnsetParameter", "effect_id": self.effect_id, "param_id": self.param_id}


@dataclass(frozen=True, slots=True)
class AddGeneratedSource:
    source: GeneratedSource

    def to_json(self) -> dict[str, object]:
        return {"op": "AddGeneratedSource", "source": self.source.to_json()}


@dataclass(frozen=True, slots=True)
class RemoveGeneratedSource:
    source_id: str

    def to_json(self) -> dict[str, object]:
        return {"op": "RemoveGeneratedSource", "source_id": self.source_id}


@dataclass(frozen=True, slots=True)
class AddLayer:
    layer_id: str
    above: str
    """Insert above this layer id, or ``"top"``."""

    def to_json(self) -> dict[str, object]:
        return {"op": "AddLayer", "layer_id": self.layer_id, "above": self.above}


@dataclass(frozen=True, slots=True)
class RemoveLayer:
    layer_id: str

    def to_json(self) -> dict[str, object]:
        return {"op": "RemoveLayer", "layer_id": self.layer_id}


@dataclass(frozen=True, slots=True)
class AddAudioTrack:
    track_id: str
    mix: AudioMix

    def to_json(self) -> dict[str, object]:
        return {"op": "AddAudioTrack", "track_id": self.track_id, "mix": self.mix.to_json()}


@dataclass(frozen=True, slots=True)
class RemoveAudioTrack:
    track_id: str

    def to_json(self) -> dict[str, object]:
        return {"op": "RemoveAudioTrack", "track_id": self.track_id}


@dataclass(frozen=True, slots=True)
class SetOutputProfile:
    profile: OutputProfile

    def to_json(self) -> dict[str, object]:
        return {"op": "SetOutputProfile", "profile": self.profile.to_json()}


@dataclass(frozen=True, slots=True)
class RebindAsset:
    """Bind (``Absent`` precondition) or relink an asset to verified bytes with its receipt.
    Relinking to other bytes is a new identity: analysis bound to the old bytes no longer
    matches and must be unbound first (I1)."""

    asset: AssetRef
    probe: ProbeReceipt

    def __post_init__(self) -> None:
        if self.probe.receipt_id != self.asset.identity.probe_receipt_id:
            raise ContractError("RebindAsset: receipt does not match the asset identity")

    def to_json(self) -> dict[str, object]:
        return {"op": "RebindAsset", "asset": self.asset.to_json(), "probe": self.probe.to_json()}


@dataclass(frozen=True, slots=True)
class RemoveAsset:
    asset_id: str

    def to_json(self) -> dict[str, object]:
        return {"op": "RemoveAsset", "asset_id": self.asset_id}


@dataclass(frozen=True, slots=True)
class RecordAnalysis:
    """Admit analysis evidence (a transcript or mask track reference with its coverage and
    qualification) into the document. Producers (M3/M4) admit it through the ledger with
    ``ToolCall`` provenance; a worker never writes the document itself."""

    ref: AnalysisRef

    def to_json(self) -> dict[str, object]:
        return {"op": "RecordAnalysis", "ref": self.ref.to_json()}


@dataclass(frozen=True, slots=True)
class RemoveAnalysis:
    ref_id: str

    def to_json(self) -> dict[str, object]:
        return {"op": "RemoveAnalysis", "ref_id": self.ref_id}


@dataclass(frozen=True, slots=True)
class RecompileWithNewCatalog:
    """Explicit qualified choice after a catalog digest mismatch (V29)."""

    from_digest: Sha256
    to_digest: Sha256

    def to_json(self) -> dict[str, object]:
        return {
            "op": "RecompileWithNewCatalog",
            "from_digest": self.from_digest.hex,
            "to_digest": self.to_digest.hex,
        }


@dataclass(frozen=True, slots=True)
class RevertOperation:
    event_seq: EventSeq
    choices: tuple[UndoChoice, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "op": "RevertOperation",
            "event_seq": self.event_seq.value,
            "choices": [c.to_json() for c in self.choices],
        }


type Operation = (
    InsertOccurrence
    | RemoveOccurrence
    | TrimOccurrence
    | MoveOccurrence
    | SetConstantSpeed
    | RetimeOccurrence
    | AddTransition
    | RemoveTransition
    | SetTransitionSettings
    | SetAudioMix
    | AddTitle
    | RemoveTitle
    | ShiftTitle
    | SetCaptions
    | BindSubjectEffect
    | BindEffect
    | AddLink
    | UnbindEffect
    | SetParameter
    | SetKeyframes
    | UnsetParameter
    | AddGeneratedSource
    | RemoveGeneratedSource
    | AddLayer
    | RemoveLayer
    | AddAudioTrack
    | RemoveAudioTrack
    | SetOutputProfile
    | RebindAsset
    | RemoveAsset
    | RecordAnalysis
    | RemoveAnalysis
    | RecompileWithNewCatalog
    | RevertOperation
)

REQUIRED_OPERATIONS = (
    "InsertOccurrence",
    "TrimOccurrence",
    "MoveOccurrence",
    "SetConstantSpeed",
    "RetimeOccurrence",
    "AddTransition",
    "SetAudioMix",
    "AddTitle",
    "ShiftTitle",
    "SetCaptions",
    "BindSubjectEffect",
    "RevertOperation",
)
DESCRIPTOR_BOUND_OPERATIONS = (
    "AddGeneratedSource",
    "AddLayer",
    "AddAudioTrack",
    "AddLink",
    "BindEffect",
    "SetParameter",
    "SetKeyframes",
    "SetTransitionSettings",
    "SetOutputProfile",
    "UnbindEffect",
)
LIFECYCLE_OPERATIONS = ("RebindAsset", "RecompileWithNewCatalog", "RecordAnalysis")
INVERSE_ONLY_OPERATIONS = (
    "RemoveOccurrence",
    "RemoveTransition",
    "RemoveTitle",
    "RemoveGeneratedSource",
    "RemoveLayer",
    "RemoveAudioTrack",
    "RemoveAsset",
    "RemoveAnalysis",
    "UnsetParameter",
)
ALL_OPERATIONS = (
    REQUIRED_OPERATIONS
    + DESCRIPTOR_BOUND_OPERATIONS
    + LIFECYCLE_OPERATIONS
    + INVERSE_ONLY_OPERATIONS
)


def _speed_from_json(raw: object) -> Speed:
    value = timing_from_json(raw)
    if isinstance(value, TimeMap):
        raise ContractError("SetConstantSpeed needs Normal or Constant, not a TimeMap")
    assert isinstance(value, Normal | Constant)
    return value


def operation_from_json(raw: object) -> Operation:
    """Strict parse: unknown ``op`` names and stray keys are refused."""
    data = as_object(raw, "Operation")
    op = as_str(field(data, "op", "Operation"), "Operation.op")
    match op:
        case "InsertOccurrence":
            require_keys(data, op, ("op", "container", "occurrence"))
            return InsertOccurrence(
                container_from_json(data["container"]), ClipOccurrence.from_json(data["occurrence"])
            )
        case "RemoveOccurrence":
            require_keys(data, op, ("op", "container", "occurrence_id"))
            return RemoveOccurrence(
                container_from_json(data["container"]), _id(data["occurrence_id"], "occurrence_id")
            )
        case "TrimOccurrence":
            require_keys(data, op, ("op", "occurrence_id", "source"))
            return TrimOccurrence(
                _id(data["occurrence_id"], "occurrence_id"), SourceSpan.from_json(data["source"])
            )
        case "MoveOccurrence":
            require_keys(data, op, ("op", "occurrence_id", "start"))
            return MoveOccurrence(
                _id(data["occurrence_id"], "occurrence_id"), SequenceFrame.from_json(data["start"])
            )
        case "SetConstantSpeed":
            require_keys(data, op, ("op", "occurrence_id", "speed"))
            return SetConstantSpeed(
                _id(data["occurrence_id"], "occurrence_id"), _speed_from_json(data["speed"])
            )
        case "RetimeOccurrence":
            require_keys(data, op, ("op", "occurrence_id", "map"))
            value = timing_from_json(data["map"])
            if not isinstance(value, TimeMap):
                raise ContractError("RetimeOccurrence needs a TimeMap")
            return RetimeOccurrence(_id(data["occurrence_id"], "occurrence_id"), value)
        case "AddTransition":
            require_keys(data, op, ("op", "layer_id", "transition"))
            return AddTransition(
                _id(data["layer_id"], "layer_id"), Transition.from_json(data["transition"])
            )
        case "RemoveTransition":
            require_keys(data, op, ("op", "layer_id", "transition_id"))
            return RemoveTransition(
                _id(data["layer_id"], "layer_id"), _id(data["transition_id"], "transition_id")
            )
        case "SetTransitionSettings":
            require_keys(data, op, ("op", "transition_id", "duration_frames", "params"))
            return SetTransitionSettings(
                _id(data["transition_id"], "transition_id"),
                as_int(data["duration_frames"], "duration_frames"),
                assignments_from_json(data["params"], "params"),
            )
        case "SetAudioMix":
            require_keys(data, op, ("op", "track_id", "mix"))
            return SetAudioMix(_id(data["track_id"], "track_id"), AudioMix.from_json(data["mix"]))
        case "AddTitle":
            require_keys(
                data, op, ("op", "title_id", "text", "start_frame", "duration_frames", "style")
            )
            return AddTitle(
                _id(data["title_id"], "title_id"),
                LiteralText.from_json(data["text"]),
                as_int(data["start_frame"], "start_frame"),
                as_int(data["duration_frames"], "duration_frames"),
                _id(data["style"], "style"),
            )
        case "RemoveTitle":
            require_keys(data, op, ("op", "title_id"))
            return RemoveTitle(_id(data["title_id"], "title_id"))
        case "ShiftTitle":
            require_keys(data, op, ("op", "title_id", "delta_frames"))
            return ShiftTitle(
                _id(data["title_id"], "title_id"), as_int(data["delta_frames"], "delta_frames")
            )
        case "SetCaptions":
            require_keys(data, op, ("op", "captions"))
            return SetCaptions(
                tuple(Caption.from_json(c) for c in as_list(data["captions"], "captions"))
            )
        case "BindSubjectEffect":
            require_keys(data, op, ("op", "binding", "request"))
            return BindSubjectEffect(
                EffectBinding.from_json(data["binding"]), subject_request_from_json(data["request"])
            )
        case "BindEffect":
            require_keys(data, op, ("op", "binding"))
            return BindEffect(EffectBinding.from_json(data["binding"]))
        case "AddLink":
            require_keys(data, op, ("op", "binding"))
            return AddLink(EffectBinding.from_json(data["binding"]))
        case "UnbindEffect":
            require_keys(data, op, ("op", "effect_id"))
            return UnbindEffect(_id(data["effect_id"], "effect_id"))
        case "SetParameter":
            require_keys(data, op, ("op", "effect_id", "assignment"))
            return SetParameter(
                _id(data["effect_id"], "effect_id"), ParamAssignment.from_json(data["assignment"])
            )
        case "SetKeyframes":
            require_keys(data, op, ("op", "effect_id", "assignment"))
            return SetKeyframes(
                _id(data["effect_id"], "effect_id"), ParamAssignment.from_json(data["assignment"])
            )
        case "UnsetParameter":
            require_keys(data, op, ("op", "effect_id", "param_id"))
            return UnsetParameter(
                _id(data["effect_id"], "effect_id"), _id(data["param_id"], "param_id")
            )
        case "AddGeneratedSource":
            require_keys(data, op, ("op", "source"))
            return AddGeneratedSource(GeneratedSource.from_json(data["source"]))
        case "RemoveGeneratedSource":
            require_keys(data, op, ("op", "source_id"))
            return RemoveGeneratedSource(_id(data["source_id"], "source_id"))
        case "AddLayer":
            require_keys(data, op, ("op", "layer_id", "above"))
            return AddLayer(_id(data["layer_id"], "layer_id"), _id(data["above"], "above"))
        case "RemoveLayer":
            require_keys(data, op, ("op", "layer_id"))
            return RemoveLayer(_id(data["layer_id"], "layer_id"))
        case "AddAudioTrack":
            require_keys(data, op, ("op", "track_id", "mix"))
            return AddAudioTrack(_id(data["track_id"], "track_id"), AudioMix.from_json(data["mix"]))
        case "RemoveAudioTrack":
            require_keys(data, op, ("op", "track_id"))
            return RemoveAudioTrack(_id(data["track_id"], "track_id"))
        case "SetOutputProfile":
            require_keys(data, op, ("op", "profile"))
            return SetOutputProfile(OutputProfile.from_json(data["profile"]))
        case "RebindAsset":
            require_keys(data, op, ("op", "asset", "probe"))
            return RebindAsset(
                AssetRef.from_json(data["asset"]), ProbeReceipt.from_json(data["probe"])
            )
        case "RemoveAsset":
            require_keys(data, op, ("op", "asset_id"))
            return RemoveAsset(_id(data["asset_id"], "asset_id"))
        case "RecordAnalysis":
            require_keys(data, op, ("op", "ref"))
            return RecordAnalysis(AnalysisRef.from_json(data["ref"]))
        case "RemoveAnalysis":
            require_keys(data, op, ("op", "ref_id"))
            return RemoveAnalysis(_id(data["ref_id"], "ref_id"))
        case "RecompileWithNewCatalog":
            require_keys(data, op, ("op", "from_digest", "to_digest"))
            return RecompileWithNewCatalog(
                Sha256(as_str(data["from_digest"], "from_digest")),
                Sha256(as_str(data["to_digest"], "to_digest")),
            )
        case "RevertOperation":
            require_keys(data, op, ("op", "event_seq", "choices"))
            return RevertOperation(
                EventSeq(as_int(data["event_seq"], "event_seq")),
                tuple(choice_from_json(c) for c in as_list(data["choices"], "choices")),
            )
        case _:
            raise ContractError(f"Operation: unknown op {op!r}")


# ----------------------------------------------------------------------------- preconditions


@dataclass(frozen=True, slots=True)
class Exists:
    object_ref: ObjectRef
    version: str

    def __post_init__(self) -> None:
        if not is_str(self.version) or len(self.version) != 64:
            raise ContractError("Exists.version must be a 64-hex object version")

    def to_json(self) -> dict[str, object]:
        return {"kind": "Exists", "object_ref": str(self.object_ref), "version": self.version}


@dataclass(frozen=True, slots=True)
class Absent:
    object_ref: ObjectRef

    def to_json(self) -> dict[str, object]:
        return {"kind": "Absent", "object_ref": str(self.object_ref)}


type ObjectPrecondition = Exists | Absent


def precondition_from_json(raw: object) -> ObjectPrecondition:
    data = as_object(raw, "precondition")
    kind = as_str(field(data, "kind", "precondition"), "precondition.kind")
    if kind == "Exists":
        require_keys(data, "Exists", ("kind", "object_ref", "version"))
        return Exists(
            ObjectRef.parse(as_str(data["object_ref"], "object_ref")),
            as_str(data["version"], "version"),
        )
    if kind == "Absent":
        require_keys(data, "Absent", ("kind", "object_ref"))
        return Absent(ObjectRef.parse(as_str(data["object_ref"], "object_ref")))
    raise ContractError(f"precondition: unknown kind {kind!r}")


# ----------------------------------------------------------------------------- batch


@dataclass(frozen=True, slots=True)
class OperationBatch:
    """Typed batch; ``to_envelope`` produces the canonical wire form the ledger admits."""

    actor: LocalUser
    project_id: ProjectId
    base_revision: RevisionId
    replay_key: ReplayKey
    preconditions: tuple[ObjectPrecondition, ...]
    operations: tuple[Operation, ...]
    provenance: Provenance

    def __post_init__(self) -> None:
        if not self.operations:
            raise ContractError("OperationBatch needs at least one operation")

    @property
    def kind(self) -> EventKind:
        if all(isinstance(op, RevertOperation) for op in self.operations):
            return EventKind.UNDO
        if all(isinstance(op, RebindAsset | RemoveAsset) for op in self.operations):
            return EventKind.REBIND
        if all(isinstance(op, RecordAnalysis | RemoveAnalysis) for op in self.operations):
            return EventKind.EFFECT_FACT
        return EventKind.EDIT

    def to_envelope(self) -> BatchEnvelope:
        return BatchEnvelope.build(
            actor=self.actor,
            project_id=self.project_id,
            base_revision=self.base_revision,
            replay_key=self.replay_key,
            preconditions=[p.to_json() for p in self.preconditions],
            operations=[op.to_json() for op in self.operations],
            provenance=self.provenance,
            kind=self.kind,
        )

    @property
    def payload_sha256(self) -> Sha256:
        return self.to_envelope().payload_sha256

    @classmethod
    def from_envelope(cls, envelope: BatchEnvelope) -> OperationBatch:
        body = envelope.parse_body()
        return cls(
            envelope.actor,
            envelope.project_id,
            envelope.base_revision,
            envelope.replay_key,
            tuple(precondition_from_json(p) for p in body.preconditions),
            tuple(operation_from_json(op) for op in body.operations),
            body.provenance,
        )


def operations_from_json(raw: object) -> tuple[Operation, ...]:
    return tuple(operation_from_json(op) for op in as_list(raw, "operations"))


def operations_to_json(operations: tuple[Operation, ...]) -> list[object]:
    return [op.to_json() for op in operations]


__all__ = [
    "ALL_OPERATIONS",
    "DESCRIPTOR_BOUND_OPERATIONS",
    "INVERSE_ONLY_OPERATIONS",
    "LIFECYCLE_OPERATIONS",
    "REQUIRED_OPERATIONS",
    "Absent",
    "AddAudioTrack",
    "AddGeneratedSource",
    "AddLayer",
    "AddLink",
    "AddTitle",
    "AddTransition",
    "BindEffect",
    "BindSubjectEffect",
    "ContainerRef",
    "DropDependent",
    "ExistingTrack",
    "Exists",
    "ForceRestore",
    "InsertOccurrence",
    "LayerRef",
    "MoveOccurrence",
    "ObjectPrecondition",
    "Operation",
    "OperationBatch",
    "RebindAsset",
    "RebindTo",
    "RecompileWithNewCatalog",
    "RecordAnalysis",
    "RemoveAnalysis",
    "RemoveAsset",
    "RemoveAudioTrack",
    "RemoveGeneratedSource",
    "RemoveLayer",
    "RemoveOccurrence",
    "RemoveTitle",
    "RemoveTransition",
    "RetimeOccurrence",
    "RevertOperation",
    "SetAudioMix",
    "SetCaptions",
    "SetConstantSpeed",
    "SetKeyframes",
    "SetOutputProfile",
    "SetParameter",
    "SetTransitionSettings",
    "ShiftTitle",
    "SubjectRequest",
    "ToolCall",
    "TrackRef",
    "TrimOccurrence",
    "UnbindEffect",
    "UndoChoice",
    "UnsetParameter",
    "UserWording",
    "choice_from_json",
    "container_from_json",
    "operation_from_json",
    "operations_from_json",
    "operations_to_json",
    "precondition_from_json",
    "provenance_from_json",
]
