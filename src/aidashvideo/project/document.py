"""The project document: the portable, content-addressed payload of a revision
(contracts §2 "project domain"; wire id ``aidashvideo.project-document/1``).

Every type is a frozen dataclass with a validating constructor and a strict JSON parser
(exact key sets, exact rationals, closed kinds). Structural validation of the whole
document (:func:`validate_document`) runs before any admission; descriptor-bound checks
against the catalog happen per operation (:mod:`aidashvideo.project.apply`).

Refinements recorded for the frozen contract (see docs/evidence/milestone-1.md):

* ``probes`` keeps every referenced :class:`ProbeReceipt` inline so the portable file
  carries "source assets and probe/provenance" and handle checks need no store;
* ``generated`` holds descriptor-bound generated sources (``AddGeneratedSource``), which
  have no bytes and therefore no :class:`SourceIdentity`;
* MLT *links* are effect bindings whose service is of type ``link``.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from enum import StrEnum
from fractions import Fraction
from typing import cast

from aidashvideo.ledger.canonical import (
    as_int,
    as_list,
    as_object,
    as_str,
    canonical_bytes,
    canonical_sha256,
    field,
    rational_from_json,
    rational_to_json,
    require_keys,
)
from aidashvideo.ledger.errors import ContractError, is_int, is_str, widen
from aidashvideo.ledger.ids import Sha256
from aidashvideo.ledger.results import RejectCode, Rejected
from aidashvideo.store.identity import (
    AssetAvailability,
    AudioStream,
    Changed,
    Missing,
    Present,
    ProbeReceipt,
    Sdr709,
    SourceBinding,
    SourceIdentity,
    StreamProbe,
    VideoStream,
    availability_from_json,
)

from .geometry import Box, Point
from .params import ParamAssignment, assignments_from_json
from .text import LiteralText
from .timing import (
    InsufficientHandles,
    Placement,
    SequenceSpan,
    SourceSpan,
    Timing,
    timing_from_json,
    timing_to_json,
    transition_handles,
    validate_placement,
)

DOCUMENT_SCHEMA_ID = "aidashvideo.project-document/1"
DOCUMENT_SCHEMA_VERSION = 1


def _id(value: object, what: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128 or not value.isprintable():
        raise ContractError(f"{what}: invalid identifier {value!r}")
    return value


def _json_id(value: object, what: str) -> str:
    return _id(as_str(value, what), what)


# ----------------------------------------------------------------------------- profile


class Container(StrEnum):
    MP4_H264_AAC = "Mp4H264Aac"


class Layout(StrEnum):
    STEREO = "Stereo"


@dataclass(frozen=True, slots=True)
class Loudness:
    target_lufs: Fraction
    true_peak_dbtp: Fraction

    def __post_init__(self) -> None:
        if not isinstance(widen(self.target_lufs), Fraction) or not isinstance(
            widen(self.true_peak_dbtp), Fraction
        ):
            raise ContractError("Loudness values must be Fractions")
        if self.true_peak_dbtp > 0:
            raise ContractError("Loudness.true_peak_dbtp must be <= 0 dBTP")

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "Loudness",
            "target_lufs": rational_to_json(self.target_lufs),
            "true_peak_dbtp": rational_to_json(self.true_peak_dbtp),
        }


@dataclass(frozen=True, slots=True)
class Unconstrained:
    def to_json(self) -> dict[str, object]:
        return {"kind": "Unconstrained"}


type Delivery = Loudness | Unconstrained


@dataclass(frozen=True, slots=True)
class AudioProfile:
    sample_rate: int
    layout: Layout
    delivery: Delivery

    def __post_init__(self) -> None:
        if not is_int(self.sample_rate) or self.sample_rate < 8000:
            raise ContractError("AudioProfile.sample_rate must be >= 8000")

    @classmethod
    def default(cls) -> AudioProfile:
        return cls(48000, Layout.STEREO, Unconstrained())

    def to_json(self) -> dict[str, object]:
        return {
            "sample_rate": self.sample_rate,
            "layout": self.layout.value,
            "delivery": self.delivery.to_json(),
        }

    @classmethod
    def from_json(cls, raw: object) -> AudioProfile:
        data = as_object(raw, "AudioProfile")
        require_keys(data, "AudioProfile", ("sample_rate", "layout", "delivery"))
        delivery_raw = as_object(data["delivery"], "delivery")
        kind = as_str(field(delivery_raw, "kind", "delivery"), "delivery.kind")
        delivery: Delivery
        if kind == "Loudness":
            require_keys(delivery_raw, "Loudness", ("kind", "target_lufs", "true_peak_dbtp"))
            delivery = Loudness(
                rational_from_json(delivery_raw["target_lufs"], "target_lufs"),
                rational_from_json(delivery_raw["true_peak_dbtp"], "true_peak_dbtp"),
            )
        elif kind == "Unconstrained":
            require_keys(delivery_raw, "Unconstrained", ("kind",))
            delivery = Unconstrained()
        else:
            raise ContractError(f"delivery: unknown kind {kind!r}")
        try:
            layout = Layout(as_str(data["layout"], "layout"))
        except ValueError as exc:
            raise ContractError(f"AudioProfile.layout: {exc}") from exc
        return cls(as_int(data["sample_rate"], "sample_rate"), layout, delivery)


@dataclass(frozen=True, slots=True)
class OutputProfile:
    width: int
    height: int
    fps: Fraction
    color: Sdr709
    audio: AudioProfile
    container: Container

    def __post_init__(self) -> None:
        if not is_int(self.width) or not is_int(self.height) or self.width < 16 or self.height < 16:
            raise ContractError("OutputProfile dimensions must be integers >= 16")
        if self.width % 2 or self.height % 2:
            raise ContractError("OutputProfile dimensions must be even (yuv420p)")
        if not isinstance(widen(self.fps), Fraction) or self.fps <= 0:
            raise ContractError("OutputProfile.fps must be a positive rational")
        if not isinstance(widen(self.color), Sdr709):
            raise ContractError("OutputProfile.color must be Sdr709 (HDR delivery is a non-goal)")

    @classmethod
    def default(cls) -> OutputProfile:
        """SDR Rec.709 1920x1080 30/1 fps, 48 kHz stereo AAC in MP4 (docs/design/milestone-0)."""
        return cls(
            1920, 1080, Fraction(30), Sdr709(), AudioProfile.default(), Container.MP4_H264_AAC
        )

    def to_json(self) -> dict[str, object]:
        return {
            "width": self.width,
            "height": self.height,
            "fps": rational_to_json(self.fps),
            "color": self.color.to_json(),
            "audio": self.audio.to_json(),
            "container": self.container.value,
        }

    @classmethod
    def from_json(cls, raw: object) -> OutputProfile:
        data = as_object(raw, "OutputProfile")
        require_keys(
            data, "OutputProfile", ("width", "height", "fps", "color", "audio", "container")
        )
        color = as_object(data["color"], "color")
        require_keys(color, "color", ("kind",))
        if color["kind"] != "Sdr709":
            raise ContractError("OutputProfile.color must be Sdr709")
        try:
            container = Container(as_str(data["container"], "container"))
        except ValueError as exc:
            raise ContractError(f"OutputProfile.container: {exc}") from exc
        return cls(
            as_int(data["width"], "width"),
            as_int(data["height"], "height"),
            rational_from_json(data["fps"], "fps"),
            Sdr709(),
            AudioProfile.from_json(data["audio"]),
            container,
        )


# ----------------------------------------------------------------------------- refs


@dataclass(frozen=True, slots=True)
class ServiceRef:
    """A descriptor by ``(service_id, catalog_digest)``."""

    service_id: str
    catalog_digest: Sha256

    def __post_init__(self) -> None:
        _id(self.service_id, "ServiceRef.service_id")

    def to_json(self) -> dict[str, object]:
        return {"service_id": self.service_id, "catalog_digest": self.catalog_digest.hex}

    @classmethod
    def from_json(cls, raw: object) -> ServiceRef:
        data = as_object(raw, "ServiceRef")
        require_keys(data, "ServiceRef", ("service_id", "catalog_digest"))
        return cls(
            _json_id(data["service_id"], "service_id"),
            Sha256(as_str(data["catalog_digest"], "catalog_digest")),
        )


class ObjectKind(StrEnum):
    ASSET = "asset"
    GENERATED = "generated"
    LAYER = "layer"
    TRACK = "track"
    OCCURRENCE = "occurrence"
    TRANSITION = "transition"
    TITLE = "title"
    CAPTION = "caption"
    EFFECT = "effect"
    ANALYSIS = "analysis"
    PROFILE = "profile"
    CAPTIONS = "captions"


@dataclass(frozen=True, slots=True)
class ObjectRef:
    kind: ObjectKind
    id: str

    def __post_init__(self) -> None:
        _id(self.id, "ObjectRef.id")

    def __str__(self) -> str:
        return f"{self.kind.value}:{self.id}"

    @classmethod
    def parse(cls, text: str) -> ObjectRef:
        if ":" not in text:
            raise ContractError(f"ObjectRef: expected kind:id, got {text!r}")
        kind, _, ident = text.partition(":")
        try:
            return cls(ObjectKind(kind), ident)
        except ValueError as exc:
            raise ContractError(f"ObjectRef: {exc}") from exc


# ----------------------------------------------------------------------------- assets


@dataclass(frozen=True, slots=True)
class AssetRef:
    asset_id: str
    identity: SourceIdentity
    availability: AssetAvailability

    def __post_init__(self) -> None:
        _id(self.asset_id, "AssetRef.asset_id")
        expected = self.identity.sha256
        match self.availability:
            case Present(verified_hash, _, receipt):
                if verified_hash != expected:
                    raise ContractError(
                        f"asset {self.asset_id}: Present hash differs from identity"
                    )
                if receipt != self.identity.probe_receipt_id:
                    raise ContractError(
                        f"asset {self.asset_id}: Present receipt differs from identity"
                    )
            case Missing(expected_hash, relink):
                if expected_hash != expected or relink.expected_hash != expected:
                    raise ContractError(
                        f"asset {self.asset_id}: Missing hash differs from identity"
                    )
                if relink.asset_id != self.asset_id:
                    raise ContractError(f"asset {self.asset_id}: relink names another asset")
            case Changed(expected_hash, _):
                if expected_hash != expected:
                    raise ContractError(
                        f"asset {self.asset_id}: Changed hash differs from identity"
                    )

    def to_json(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "identity": self.identity.to_json(),
            "availability": self.availability.to_json(),
        }

    @classmethod
    def from_json(cls, raw: object) -> AssetRef:
        data = as_object(raw, "AssetRef")
        require_keys(data, "AssetRef", ("asset_id", "identity", "availability"))
        return cls(
            _json_id(data["asset_id"], "asset_id"),
            SourceIdentity.from_json(data["identity"]),
            availability_from_json(data["availability"]),
        )


@dataclass(frozen=True, slots=True)
class GeneratedSource:
    """A descriptor-bound producer (colour, noise, ...) with a declared duration and size."""

    source_id: str
    service: ServiceRef
    params: tuple[ParamAssignment, ...]
    duration: Fraction
    width: int
    height: int

    def __post_init__(self) -> None:
        _id(self.source_id, "GeneratedSource.source_id")
        if not isinstance(widen(self.duration), Fraction) or self.duration <= 0:
            raise ContractError("GeneratedSource.duration must be a positive rational")
        if not is_int(self.width) or not is_int(self.height) or self.width < 1 or self.height < 1:
            raise ContractError("GeneratedSource dimensions must be positive integers")

    def to_json(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "service": self.service.to_json(),
            "params": [p.to_json() for p in self.params],
            "duration": rational_to_json(self.duration),
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_json(cls, raw: object) -> GeneratedSource:
        data = as_object(raw, "GeneratedSource")
        require_keys(
            data,
            "GeneratedSource",
            ("source_id", "service", "params", "duration", "width", "height"),
        )
        return cls(
            _json_id(data["source_id"], "source_id"),
            ServiceRef.from_json(data["service"]),
            assignments_from_json(data["params"], "GeneratedSource.params"),
            rational_from_json(data["duration"], "duration"),
            as_int(data["width"], "width"),
            as_int(data["height"], "height"),
        )


# ----------------------------------------------------------------------------- sequence


@dataclass(frozen=True, slots=True)
class NoCrop:
    def to_json(self) -> dict[str, object]:
        return {"kind": "NoCrop"}


@dataclass(frozen=True, slots=True)
class Crop:
    box: Box

    def to_json(self) -> dict[str, object]:
        return {"kind": "Crop", "box": self.box.to_json()}


@dataclass(frozen=True, slots=True)
class ClipTransform:
    crop: NoCrop | Crop
    scale: Fraction
    position: Point

    def __post_init__(self) -> None:
        if not isinstance(widen(self.scale), Fraction) or self.scale <= 0:
            raise ContractError("ClipTransform.scale must be a positive rational")

    @classmethod
    def identity(cls) -> ClipTransform:
        return cls(NoCrop(), Fraction(1), Point(Fraction(0), Fraction(0)))

    def to_json(self) -> dict[str, object]:
        return {
            "crop": self.crop.to_json(),
            "scale": rational_to_json(self.scale),
            "position": self.position.to_json(),
        }

    @classmethod
    def from_json(cls, raw: object) -> ClipTransform:
        data = as_object(raw, "ClipTransform")
        require_keys(data, "ClipTransform", ("crop", "scale", "position"))
        crop_raw = as_object(data["crop"], "crop")
        kind = as_str(field(crop_raw, "kind", "crop"), "crop.kind")
        crop: NoCrop | Crop
        if kind == "NoCrop":
            require_keys(crop_raw, "NoCrop", ("kind",))
            crop = NoCrop()
        elif kind == "Crop":
            require_keys(crop_raw, "Crop", ("kind", "box"))
            crop = Crop(Box.from_json(crop_raw["box"]))
        else:
            raise ContractError(f"crop: unknown kind {kind!r}")
        return cls(
            crop, rational_from_json(data["scale"], "scale"), Point.from_json(data["position"])
        )


@dataclass(frozen=True, slots=True)
class ClipOccurrence:
    """One placement of a source interval; ids survive moves and cuts, and two occurrences
    of the same asset stay distinguishable."""

    occurrence_id: str
    asset_id: str
    stream_index: int
    source: SourceSpan
    place: SequenceSpan
    timing: Timing
    transform: ClipTransform

    def __post_init__(self) -> None:
        _id(self.occurrence_id, "ClipOccurrence.occurrence_id")
        _id(self.asset_id, "ClipOccurrence.asset_id")
        if not is_int(self.stream_index) or self.stream_index < 0:
            raise ContractError("ClipOccurrence.stream_index must be >= 0")
        Placement(self.source, self.place, self.timing)  # map length matches the placement

    @property
    def placement(self) -> Placement:
        return Placement(self.source, self.place, self.timing)

    def to_json(self) -> dict[str, object]:
        return {
            "occurrence_id": self.occurrence_id,
            "asset_id": self.asset_id,
            "stream_index": self.stream_index,
            "source": self.source.to_json(),
            "place": self.place.to_json(),
            "timing": timing_to_json(self.timing),
            "transform": self.transform.to_json(),
        }

    @classmethod
    def from_json(cls, raw: object) -> ClipOccurrence:
        data = as_object(raw, "ClipOccurrence")
        require_keys(
            data,
            "ClipOccurrence",
            ("occurrence_id", "asset_id", "stream_index", "source", "place", "timing", "transform"),
        )
        return cls(
            _json_id(data["occurrence_id"], "occurrence_id"),
            _json_id(data["asset_id"], "asset_id"),
            as_int(data["stream_index"], "stream_index"),
            SourceSpan.from_json(data["source"]),
            SequenceSpan.from_json(data["place"]),
            timing_from_json(data["timing"]),
            ClipTransform.from_json(data["transform"]),
        )


@dataclass(frozen=True, slots=True)
class Transition:
    transition_id: str
    left_occurrence: str
    right_occurrence: str
    kind: ServiceRef
    duration_frames: int
    params: tuple[ParamAssignment, ...]

    def __post_init__(self) -> None:
        _id(self.transition_id, "Transition.transition_id")
        _id(self.left_occurrence, "Transition.left_occurrence")
        _id(self.right_occurrence, "Transition.right_occurrence")
        if self.left_occurrence == self.right_occurrence:
            raise ContractError("Transition needs two different occurrences")
        if not is_int(self.duration_frames) or self.duration_frames < 1:
            raise ContractError("Transition.duration_frames must be >= 1")

    def to_json(self) -> dict[str, object]:
        return {
            "transition_id": self.transition_id,
            "left_occurrence": self.left_occurrence,
            "right_occurrence": self.right_occurrence,
            "kind": self.kind.to_json(),
            "duration_frames": self.duration_frames,
            "params": [p.to_json() for p in self.params],
        }

    @classmethod
    def from_json(cls, raw: object) -> Transition:
        data = as_object(raw, "Transition")
        require_keys(
            data,
            "Transition",
            (
                "transition_id",
                "left_occurrence",
                "right_occurrence",
                "kind",
                "duration_frames",
                "params",
            ),
        )
        return cls(
            _json_id(data["transition_id"], "transition_id"),
            _json_id(data["left_occurrence"], "left_occurrence"),
            _json_id(data["right_occurrence"], "right_occurrence"),
            ServiceRef.from_json(data["kind"]),
            as_int(data["duration_frames"], "duration_frames"),
            assignments_from_json(data["params"], "Transition.params"),
        )


@dataclass(frozen=True, slots=True)
class VideoLayer:
    layer_id: str
    occurrences: tuple[ClipOccurrence, ...]
    transitions: tuple[Transition, ...]

    def __post_init__(self) -> None:
        _id(self.layer_id, "VideoLayer.layer_id")

    def to_json(self) -> dict[str, object]:
        return {
            "layer_id": self.layer_id,
            "occurrences": [o.to_json() for o in self.occurrences],
            "transitions": [t.to_json() for t in self.transitions],
        }

    @classmethod
    def from_json(cls, raw: object) -> VideoLayer:
        data = as_object(raw, "VideoLayer")
        require_keys(data, "VideoLayer", ("layer_id", "occurrences", "transitions"))
        return cls(
            _json_id(data["layer_id"], "layer_id"),
            tuple(ClipOccurrence.from_json(o) for o in as_list(data["occurrences"], "occurrences")),
            tuple(Transition.from_json(t) for t in as_list(data["transitions"], "transitions")),
        )


@dataclass(frozen=True, slots=True)
class NoDucking:
    def to_json(self) -> dict[str, object]:
        return {"kind": "NoDucking"}


@dataclass(frozen=True, slots=True)
class DuckUnder:
    """Lower this track under speech on another track, justified by transcript evidence."""

    speech_track_id: str
    amount_db: Fraction
    evidence: str
    """A transcript id in ``analysis_refs``."""

    def __post_init__(self) -> None:
        _id(self.speech_track_id, "DuckUnder.speech_track_id")
        _id(self.evidence, "DuckUnder.evidence")
        if not isinstance(widen(self.amount_db), Fraction) or self.amount_db >= 0:
            raise ContractError("DuckUnder.amount_db must be a negative rational (dB)")

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "DuckUnder",
            "speech_track_id": self.speech_track_id,
            "amount_db": rational_to_json(self.amount_db),
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class AudioMix:
    gain_db: Fraction
    fade_in_frames: int
    fade_out_frames: int
    ducking: NoDucking | DuckUnder

    def __post_init__(self) -> None:
        if not isinstance(widen(self.gain_db), Fraction) or not -96 <= self.gain_db <= 24:
            raise ContractError("AudioMix.gain_db must be a rational within [-96, 24] dB")
        for name in ("fade_in_frames", "fade_out_frames"):
            if not is_int(getattr(self, name)) or getattr(self, name) < 0:
                raise ContractError(f"AudioMix.{name} must be a non-negative integer")

    @classmethod
    def default(cls) -> AudioMix:
        return cls(Fraction(0), 0, 0, NoDucking())

    def to_json(self) -> dict[str, object]:
        return {
            "gain_db": rational_to_json(self.gain_db),
            "fade_in_frames": self.fade_in_frames,
            "fade_out_frames": self.fade_out_frames,
            "ducking": self.ducking.to_json(),
        }

    @classmethod
    def from_json(cls, raw: object) -> AudioMix:
        data = as_object(raw, "AudioMix")
        require_keys(data, "AudioMix", ("gain_db", "fade_in_frames", "fade_out_frames", "ducking"))
        duck_raw = as_object(data["ducking"], "ducking")
        kind = as_str(field(duck_raw, "kind", "ducking"), "ducking.kind")
        ducking: NoDucking | DuckUnder
        if kind == "NoDucking":
            require_keys(duck_raw, "NoDucking", ("kind",))
            ducking = NoDucking()
        elif kind == "DuckUnder":
            require_keys(
                duck_raw, "DuckUnder", ("kind", "speech_track_id", "amount_db", "evidence")
            )
            ducking = DuckUnder(
                _json_id(duck_raw["speech_track_id"], "speech_track_id"),
                rational_from_json(duck_raw["amount_db"], "amount_db"),
                _json_id(duck_raw["evidence"], "evidence"),
            )
        else:
            raise ContractError(f"ducking: unknown kind {kind!r}")
        return cls(
            rational_from_json(data["gain_db"], "gain_db"),
            as_int(data["fade_in_frames"], "fade_in_frames"),
            as_int(data["fade_out_frames"], "fade_out_frames"),
            ducking,
        )


@dataclass(frozen=True, slots=True)
class AudioTrack:
    track_id: str
    occurrences: tuple[ClipOccurrence, ...]
    mix: AudioMix

    def __post_init__(self) -> None:
        _id(self.track_id, "AudioTrack.track_id")

    def to_json(self) -> dict[str, object]:
        return {
            "track_id": self.track_id,
            "occurrences": [o.to_json() for o in self.occurrences],
            "mix": self.mix.to_json(),
        }

    @classmethod
    def from_json(cls, raw: object) -> AudioTrack:
        data = as_object(raw, "AudioTrack")
        require_keys(data, "AudioTrack", ("track_id", "occurrences", "mix"))
        return cls(
            _json_id(data["track_id"], "track_id"),
            tuple(ClipOccurrence.from_json(o) for o in as_list(data["occurrences"], "occurrences")),
            AudioMix.from_json(data["mix"]),
        )


@dataclass(frozen=True, slots=True)
class Title:
    title_id: str
    text: LiteralText
    place: SequenceSpan
    style: str
    """``TitleStyleRef``: a style id (fonts are bound by identity in the runtime profile)."""

    def __post_init__(self) -> None:
        _id(self.title_id, "Title.title_id")
        _id(self.style, "Title.style")

    def to_json(self) -> dict[str, object]:
        return {
            "title_id": self.title_id,
            "text": self.text.to_json(),
            "place": self.place.to_json(),
            "style": self.style,
        }

    @classmethod
    def from_json(cls, raw: object) -> Title:
        data = as_object(raw, "Title")
        require_keys(data, "Title", ("title_id", "text", "place", "style"))
        return cls(
            _json_id(data["title_id"], "title_id"),
            LiteralText.from_json(data["text"]),
            SequenceSpan.from_json(data["place"]),
            _json_id(data["style"], "style"),
        )


@dataclass(frozen=True, slots=True)
class Caption:
    caption_id: str
    text: LiteralText
    place: SequenceSpan
    language: str
    style: str
    lines: tuple[LiteralText, ...]
    evidence: str
    """A transcript id in ``analysis_refs`` (``TranscriptRef``)."""

    requested: SourceSpan
    """The transcript segment interval the placement realizes (requested boundary)."""

    def __post_init__(self) -> None:
        _id(self.caption_id, "Caption.caption_id")
        _id(self.style, "Caption.style")
        _id(self.evidence, "Caption.evidence")
        if not is_str(self.language) or not 2 <= len(self.language) <= 16:
            raise ContractError("Caption.language must be a language tag")
        if not self.lines:
            raise ContractError("Caption needs at least one line")

    def to_json(self) -> dict[str, object]:
        return {
            "caption_id": self.caption_id,
            "text": self.text.to_json(),
            "place": self.place.to_json(),
            "language": self.language,
            "style": self.style,
            "lines": [line.to_json() for line in self.lines],
            "evidence": self.evidence,
            "requested": self.requested.to_json(),
        }

    @classmethod
    def from_json(cls, raw: object) -> Caption:
        data = as_object(raw, "Caption")
        require_keys(
            data,
            "Caption",
            ("caption_id", "text", "place", "language", "style", "lines", "evidence", "requested"),
        )
        return cls(
            _json_id(data["caption_id"], "caption_id"),
            LiteralText.from_json(data["text"]),
            SequenceSpan.from_json(data["place"]),
            as_str(data["language"], "language"),
            _json_id(data["style"], "style"),
            tuple(LiteralText.from_json(line) for line in as_list(data["lines"], "lines")),
            _json_id(data["evidence"], "evidence"),
            SourceSpan.from_json(data["requested"]),
        )


@dataclass(frozen=True, slots=True)
class Sequence:
    video_layers: tuple[VideoLayer, ...]
    audio_tracks: tuple[AudioTrack, ...]
    titles: tuple[Title, ...]
    captions: tuple[Caption, ...]

    @classmethod
    def empty(cls) -> Sequence:
        return cls((VideoLayer("V1", (), ()),), (AudioTrack("A1", (), AudioMix.default()),), (), ())

    def to_json(self) -> dict[str, object]:
        return {
            "video_layers": [v.to_json() for v in self.video_layers],
            "audio_tracks": [a.to_json() for a in self.audio_tracks],
            "titles": [t.to_json() for t in self.titles],
            "captions": [c.to_json() for c in self.captions],
        }

    @classmethod
    def from_json(cls, raw: object) -> Sequence:
        data = as_object(raw, "Sequence")
        require_keys(data, "Sequence", ("video_layers", "audio_tracks", "titles", "captions"))
        return cls(
            tuple(VideoLayer.from_json(v) for v in as_list(data["video_layers"], "video_layers")),
            tuple(AudioTrack.from_json(a) for a in as_list(data["audio_tracks"], "audio_tracks")),
            tuple(Title.from_json(t) for t in as_list(data["titles"], "titles")),
            tuple(Caption.from_json(c) for c in as_list(data["captions"], "captions")),
        )


# ----------------------------------------------------------------------------- effects


@dataclass(frozen=True, slots=True)
class OccurrenceTarget:
    occurrence_id: str

    def __post_init__(self) -> None:
        _id(self.occurrence_id, "OccurrenceTarget.occurrence_id")

    def to_json(self) -> dict[str, object]:
        return {"kind": "OccurrenceTarget", "occurrence_id": self.occurrence_id}


@dataclass(frozen=True, slots=True)
class LayerTarget:
    layer_id: str

    def __post_init__(self) -> None:
        _id(self.layer_id, "LayerTarget.layer_id")

    def to_json(self) -> dict[str, object]:
        return {"kind": "LayerTarget", "layer_id": self.layer_id}


type EffectTarget = OccurrenceTarget | LayerTarget


def target_from_json(raw: object) -> EffectTarget:
    data = as_object(raw, "EffectTarget")
    kind = as_str(field(data, "kind", "EffectTarget"), "EffectTarget.kind")
    if kind == "OccurrenceTarget":
        require_keys(data, "OccurrenceTarget", ("kind", "occurrence_id"))
        return OccurrenceTarget(_json_id(data["occurrence_id"], "occurrence_id"))
    if kind == "LayerTarget":
        require_keys(data, "LayerTarget", ("kind", "layer_id"))
        return LayerTarget(_json_id(data["layer_id"], "layer_id"))
    raise ContractError(f"EffectTarget: unknown kind {kind!r}")


@dataclass(frozen=True, slots=True)
class NoMask:
    def to_json(self) -> dict[str, object]:
        return {"kind": "NoMask"}


@dataclass(frozen=True, slots=True)
class MaskRef:
    track_version_id: str

    def __post_init__(self) -> None:
        _id(self.track_version_id, "MaskRef.track_version_id")

    def to_json(self) -> dict[str, object]:
        return {"kind": "MaskRef", "track_version_id": self.track_version_id}


@dataclass(frozen=True, slots=True)
class EffectBinding:
    effect_id: str
    target: EffectTarget
    service: ServiceRef
    params: tuple[ParamAssignment, ...]
    mask: NoMask | MaskRef

    def __post_init__(self) -> None:
        _id(self.effect_id, "EffectBinding.effect_id")
        ids = [p.param_id for p in self.params]
        if len(set(ids)) != len(ids):
            raise ContractError(f"effect {self.effect_id}: duplicate parameter ids")

    def to_json(self) -> dict[str, object]:
        return {
            "effect_id": self.effect_id,
            "target": self.target.to_json(),
            "service": self.service.to_json(),
            "params": [p.to_json() for p in self.params],
            "mask": self.mask.to_json(),
        }

    @classmethod
    def from_json(cls, raw: object) -> EffectBinding:
        data = as_object(raw, "EffectBinding")
        require_keys(data, "EffectBinding", ("effect_id", "target", "service", "params", "mask"))
        mask_raw = as_object(data["mask"], "mask")
        kind = as_str(field(mask_raw, "kind", "mask"), "mask.kind")
        mask: NoMask | MaskRef
        if kind == "NoMask":
            require_keys(mask_raw, "NoMask", ("kind",))
            mask = NoMask()
        elif kind == "MaskRef":
            require_keys(mask_raw, "MaskRef", ("kind", "track_version_id"))
            mask = MaskRef(_json_id(mask_raw["track_version_id"], "track_version_id"))
        else:
            raise ContractError(f"mask: unknown kind {kind!r}")
        return cls(
            _json_id(data["effect_id"], "effect_id"),
            target_from_json(data["target"]),
            ServiceRef.from_json(data["service"]),
            assignments_from_json(data["params"], "EffectBinding.params"),
            mask,
        )


# ----------------------------------------------------------------------------- analysis refs


@dataclass(frozen=True, slots=True)
class QualifiedEvidence:
    evidence: str

    def __post_init__(self) -> None:
        if not is_str(self.evidence) or not self.evidence:
            raise ContractError("QualifiedEvidence needs evidence")

    def to_json(self) -> dict[str, object]:
        return {"kind": "Qualified", "evidence": self.evidence}


@dataclass(frozen=True, slots=True)
class Unqualified:
    reason: str

    def __post_init__(self) -> None:
        if not is_str(self.reason) or not self.reason:
            raise ContractError("Unqualified needs a reason")

    def to_json(self) -> dict[str, object]:
        return {"kind": "Unqualified", "reason": self.reason}


type Qualification = QualifiedEvidence | Unqualified


def qualification_from_json(raw: object) -> Qualification:
    data = as_object(raw, "qualification")
    kind = as_str(field(data, "kind", "qualification"), "qualification.kind")
    if kind == "Qualified":
        require_keys(data, "Qualified", ("kind", "evidence"))
        return QualifiedEvidence(as_str(data["evidence"], "evidence"))
    if kind == "Unqualified":
        require_keys(data, "Unqualified", ("kind", "reason"))
        return Unqualified(as_str(data["reason"], "reason"))
    raise ContractError(f"qualification: unknown kind {kind!r}")


@dataclass(frozen=True, slots=True)
class Produced:
    """Coverage exists (``SegmentTimed`` transcript / ``Tracked`` mask) with its qualification."""

    qualification: Qualification

    def to_json(self) -> dict[str, object]:
        return {"kind": "Produced", "qualification": self.qualification.to_json()}


@dataclass(frozen=True, slots=True)
class PendingAnalysis:
    """Requested from a provider and not yet produced (never counts as coverage)."""

    requested: SourceSpan

    def to_json(self) -> dict[str, object]:
        return {"kind": "Pending", "requested": self.requested.to_json()}


@dataclass(frozen=True, slots=True)
class UnavailableAnalysis:
    reason: str
    required_action: str

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "Unavailable",
            "reason": self.reason,
            "required_action": self.required_action,
        }


type AnalysisState = Produced | PendingAnalysis | UnavailableAnalysis


def analysis_state_from_json(raw: object) -> AnalysisState:
    data = as_object(raw, "AnalysisState")
    kind = as_str(field(data, "kind", "AnalysisState"), "AnalysisState.kind")
    if kind == "Produced":
        require_keys(data, "Produced", ("kind", "qualification"))
        return Produced(qualification_from_json(data["qualification"]))
    if kind == "Pending":
        require_keys(data, "Pending", ("kind", "requested"))
        return PendingAnalysis(SourceSpan.from_json(data["requested"]))
    if kind == "Unavailable":
        require_keys(data, "Unavailable", ("kind", "reason", "required_action"))
        return UnavailableAnalysis(
            as_str(data["reason"], "reason"), as_str(data["required_action"], "required_action")
        )
    raise ContractError(f"AnalysisState: unknown kind {kind!r}")


class AnalysisKind(StrEnum):
    TRANSCRIPT = "Transcript"
    MASK_TRACK = "MaskTrack"


@dataclass(frozen=True, slots=True)
class NoArtifact:
    def to_json(self) -> dict[str, object]:
        return {"kind": "NoArtifact"}


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    """The sealed CAS artifact holding the evidence bytes (transcript JSON, mask track)."""

    sha256: Sha256

    def to_json(self) -> dict[str, object]:
        return {"kind": "Artifact", "sha256": self.sha256.hex}


def evidence_artifact_from_json(raw: object) -> NoArtifact | EvidenceArtifact:
    data = as_object(raw, "artifact")
    kind = as_str(field(data, "kind", "artifact"), "artifact.kind")
    if kind == "NoArtifact":
        require_keys(data, "NoArtifact", ("kind",))
        return NoArtifact()
    if kind == "Artifact":
        require_keys(data, "Artifact", ("kind", "sha256"))
        return EvidenceArtifact(Sha256(as_str(data["sha256"], "sha256")))
    raise ContractError(f"artifact: unknown kind {kind!r}")


@dataclass(frozen=True, slots=True)
class AnalysisRef:
    """``TranscriptRef`` or ``MaskRef`` evidence bound to content (never a path); coverage
    is a set of source spans and is empty unless ``state`` is ``Produced``; produced
    evidence names its sealed artifact, which the ledger requires to exist before admission."""

    kind: AnalysisKind
    ref_id: str
    binding: SourceBinding
    coverage: tuple[SourceSpan, ...]
    state: AnalysisState
    artifact: NoArtifact | EvidenceArtifact

    def __post_init__(self) -> None:
        _id(self.ref_id, "AnalysisRef.ref_id")
        if not isinstance(self.state, Produced) and self.coverage:
            raise ContractError(f"analysis {self.ref_id}: coverage requires a Produced state")
        if isinstance(self.state, Produced) and not self.coverage:
            raise ContractError(f"analysis {self.ref_id}: Produced needs non-empty coverage")
        if not isinstance(self.state, Produced) and isinstance(self.artifact, EvidenceArtifact):
            raise ContractError(f"analysis {self.ref_id}: only produced evidence has an artifact")

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "ref_id": self.ref_id,
            "binding": self.binding.to_json(),
            "coverage": [c.to_json() for c in self.coverage],
            "state": self.state.to_json(),
            "artifact": self.artifact.to_json(),
        }

    @classmethod
    def from_json(cls, raw: object) -> AnalysisRef:
        data = as_object(raw, "AnalysisRef")
        require_keys(
            data, "AnalysisRef", ("kind", "ref_id", "binding", "coverage", "state", "artifact")
        )
        try:
            kind = AnalysisKind(as_str(data["kind"], "kind"))
        except ValueError as exc:
            raise ContractError(f"AnalysisRef.kind: {exc}") from exc
        return cls(
            kind,
            _json_id(data["ref_id"], "ref_id"),
            SourceBinding.from_json(data["binding"]),
            tuple(SourceSpan.from_json(c) for c in as_list(data["coverage"], "coverage")),
            analysis_state_from_json(data["state"]),
            evidence_artifact_from_json(data["artifact"]),
        )


# ----------------------------------------------------------------------------- document


@dataclass(frozen=True, slots=True)
class ProjectDocument:
    profile: OutputProfile
    assets: tuple[AssetRef, ...]
    probes: tuple[ProbeReceipt, ...]
    generated: tuple[GeneratedSource, ...]
    sequence: Sequence
    effects: tuple[EffectBinding, ...]
    analysis_refs: tuple[AnalysisRef, ...]

    @classmethod
    def new(cls, profile: OutputProfile) -> ProjectDocument:
        return cls(profile, (), (), (), Sequence.empty(), (), ())

    def to_json(self) -> dict[str, object]:
        return {
            "$id": DOCUMENT_SCHEMA_ID,
            "schema_version": DOCUMENT_SCHEMA_VERSION,
            "profile": self.profile.to_json(),
            "assets": [a.to_json() for a in self.assets],
            "probes": [p.to_json() for p in self.probes],
            "generated": [g.to_json() for g in self.generated],
            "sequence": self.sequence.to_json(),
            "effects": [e.to_json() for e in self.effects],
            "analysis_refs": [a.to_json() for a in self.analysis_refs],
        }

    def to_bytes(self) -> bytes:
        return canonical_bytes(self.to_json())

    @classmethod
    def from_json(cls, raw: object) -> ProjectDocument:
        data = as_object(raw, "ProjectDocument")
        require_keys(
            data,
            "ProjectDocument",
            (
                "$id",
                "schema_version",
                "profile",
                "assets",
                "probes",
                "generated",
                "sequence",
                "effects",
                "analysis_refs",
            ),
        )
        if data["$id"] != DOCUMENT_SCHEMA_ID:
            raise ContractError(f"ProjectDocument: unsupported $id {data['$id']!r}")
        if as_int(data["schema_version"], "schema_version") != DOCUMENT_SCHEMA_VERSION:
            raise ContractError(
                f"ProjectDocument: schema_version {data['schema_version']!r} is not"
                f" {DOCUMENT_SCHEMA_VERSION}"
            )
        return cls(
            OutputProfile.from_json(data["profile"]),
            tuple(AssetRef.from_json(a) for a in as_list(data["assets"], "assets")),
            tuple(ProbeReceipt.from_json(p) for p in as_list(data["probes"], "probes")),
            tuple(GeneratedSource.from_json(g) for g in as_list(data["generated"], "generated")),
            Sequence.from_json(data["sequence"]),
            tuple(EffectBinding.from_json(e) for e in as_list(data["effects"], "effects")),
            tuple(
                AnalysisRef.from_json(a) for a in as_list(data["analysis_refs"], "analysis_refs")
            ),
        )

    # ------------------------------------------------------------------ lookups

    def asset(self, asset_id: str) -> AssetRef | None:
        for a in self.assets:
            if a.asset_id == asset_id:
                return a
        return None

    def probe(self, receipt_id: Sha256) -> ProbeReceipt | None:
        for p in self.probes:
            if p.receipt_id == receipt_id:
                return p
        return None

    def generated_source(self, source_id: str) -> GeneratedSource | None:
        for g in self.generated:
            if g.source_id == source_id:
                return g
        return None

    def layer(self, layer_id: str) -> VideoLayer | None:
        for layer in self.sequence.video_layers:
            if layer.layer_id == layer_id:
                return layer
        return None

    def track(self, track_id: str) -> AudioTrack | None:
        for track in self.sequence.audio_tracks:
            if track.track_id == track_id:
                return track
        return None

    def occurrence(
        self, occurrence_id: str
    ) -> tuple[ClipOccurrence, VideoLayer | AudioTrack] | None:
        for layer in self.sequence.video_layers:
            for occ in layer.occurrences:
                if occ.occurrence_id == occurrence_id:
                    return occ, layer
        for track in self.sequence.audio_tracks:
            for occ in track.occurrences:
                if occ.occurrence_id == occurrence_id:
                    return occ, track
        return None

    def all_occurrences(self) -> tuple[ClipOccurrence, ...]:
        out: list[ClipOccurrence] = []
        for layer in self.sequence.video_layers:
            out.extend(layer.occurrences)
        for track in self.sequence.audio_tracks:
            out.extend(track.occurrences)
        return tuple(out)

    def transition(self, transition_id: str) -> tuple[Transition, VideoLayer] | None:
        for layer in self.sequence.video_layers:
            for t in layer.transitions:
                if t.transition_id == transition_id:
                    return t, layer
        return None

    def title(self, title_id: str) -> Title | None:
        for t in self.sequence.titles:
            if t.title_id == title_id:
                return t
        return None

    def effect(self, effect_id: str) -> EffectBinding | None:
        for e in self.effects:
            if e.effect_id == effect_id:
                return e
        return None

    def analysis(self, ref_id: str) -> AnalysisRef | None:
        for a in self.analysis_refs:
            if a.ref_id == ref_id:
                return a
        return None

    def stream_of(self, occ: ClipOccurrence) -> StreamProbe | GeneratedSource | None:
        asset = self.asset(occ.asset_id)
        if asset is not None:
            receipt = self.probe(asset.identity.probe_receipt_id)
            return None if receipt is None else receipt.stream(occ.stream_index)
        return self.generated_source(occ.asset_id)

    def source_duration(self, occ: ClipOccurrence) -> Fraction | None:
        asset = self.asset(occ.asset_id)
        if asset is not None:
            receipt = self.probe(asset.identity.probe_receipt_id)
            return None if receipt is None else receipt.container_duration
        generated = self.generated_source(occ.asset_id)
        return None if generated is None else generated.duration

    def binding_of(self, occ: ClipOccurrence) -> SourceBinding | None:
        asset = self.asset(occ.asset_id)
        if asset is None:
            return None
        return SourceBinding(
            asset.identity.sha256, occ.stream_index, asset.identity.probe_receipt_id
        )

    def effects_on(self, occurrence_id: str) -> tuple[EffectBinding, ...]:
        return tuple(
            e
            for e in self.effects
            if isinstance(e.target, OccurrenceTarget) and e.target.occurrence_id == occurrence_id
        )

    def transitions_on(self, occurrence_id: str) -> tuple[Transition, ...]:
        out: list[Transition] = []
        for layer in self.sequence.video_layers:
            out.extend(
                t
                for t in layer.transitions
                if occurrence_id in (t.left_occurrence, t.right_occurrence)
            )
        return tuple(out)

    # ------------------------------------------------------------------ object graph

    def objects(self) -> dict[ObjectRef, object]:
        """Every addressable object (stable ids, never indices) with its value."""
        out: dict[ObjectRef, object] = {ObjectRef(ObjectKind.PROFILE, "output"): self.profile}
        for a in self.assets:
            out[ObjectRef(ObjectKind.ASSET, a.asset_id)] = a
        for g in self.generated:
            out[ObjectRef(ObjectKind.GENERATED, g.source_id)] = g
        for layer in self.sequence.video_layers:
            out[ObjectRef(ObjectKind.LAYER, layer.layer_id)] = replace(
                layer, occurrences=(), transitions=()
            )
            for occ in layer.occurrences:
                out[ObjectRef(ObjectKind.OCCURRENCE, occ.occurrence_id)] = occ
            for t in layer.transitions:
                out[ObjectRef(ObjectKind.TRANSITION, t.transition_id)] = t
        for track in self.sequence.audio_tracks:
            out[ObjectRef(ObjectKind.TRACK, track.track_id)] = replace(track, occurrences=())
            for occ in track.occurrences:
                out[ObjectRef(ObjectKind.OCCURRENCE, occ.occurrence_id)] = occ
        for t in self.sequence.titles:
            out[ObjectRef(ObjectKind.TITLE, t.title_id)] = t
        for c in self.sequence.captions:
            out[ObjectRef(ObjectKind.CAPTION, c.caption_id)] = c
        out[ObjectRef(ObjectKind.CAPTIONS, "all")] = self.sequence.captions
        for e in self.effects:
            out[ObjectRef(ObjectKind.EFFECT, e.effect_id)] = e
        for a in self.analysis_refs:
            out[ObjectRef(ObjectKind.ANALYSIS, a.ref_id)] = a
        return out

    def object_version(self, ref: ObjectRef) -> str | None:
        """Content version of one object (``sha256`` of its canonical JSON); ``None`` if absent."""
        value = self.objects().get(ref)
        if value is None:
            return None
        return object_version(value)


def object_version(value: object) -> str:
    return canonical_sha256(_object_json(value)).hex


def _object_json(value: object) -> object:
    if isinstance(value, tuple):
        return [_object_json(v) for v in cast(tuple[object, ...], value)]
    to_json = getattr(value, "to_json", None)
    if callable(to_json):
        result: object = to_json()
        return result
    raise ContractError(f"object {type(value).__name__} has no JSON form")


# ----------------------------------------------------------------------------- validation


@dataclass(frozen=True, slots=True)
class Problem:
    code: RejectCode
    detail: str
    objects: tuple[str, ...] = ()


def stream_duration(doc: ProjectDocument, occ: ClipOccurrence) -> Fraction | None:
    return doc.source_duration(occ)


def _check_occurrence(
    doc: ProjectDocument, occ: ClipOccurrence, video: bool, problems: list[Problem]
) -> None:
    ref = str(ObjectRef(ObjectKind.OCCURRENCE, occ.occurrence_id))
    asset = doc.asset(occ.asset_id)
    generated = doc.generated_source(occ.asset_id)
    if asset is None and generated is None:
        problems.append(
            Problem(RejectCode.UNKNOWN_OBJECT, f"{ref}: unknown asset {occ.asset_id!r}", (ref,))
        )
        return
    if asset is not None:
        receipt = doc.probe(asset.identity.probe_receipt_id)
        if receipt is None:
            problems.append(
                Problem(
                    RejectCode.VALIDATION,
                    f"{ref}: asset {occ.asset_id} has no inline probe receipt",
                    (ref,),
                )
            )
            return
        stream = receipt.stream(occ.stream_index)
        if stream is None:
            problems.append(
                Problem(
                    RejectCode.UNKNOWN_OBJECT,
                    f"{ref}: asset {occ.asset_id} has no stream {occ.stream_index}",
                    (ref,),
                )
            )
            return
        if video and not isinstance(stream, VideoStream):
            problems.append(
                Problem(
                    RejectCode.VALIDATION,
                    f"{ref}: stream {occ.stream_index} is not video on a video layer",
                    (ref,),
                )
            )
        if not video and not isinstance(stream, AudioStream):
            problems.append(
                Problem(
                    RejectCode.VALIDATION,
                    f"{ref}: stream {occ.stream_index} is not audio on an audio track",
                    (ref,),
                )
            )
        duration = receipt.container_duration
    else:
        assert generated is not None
        if not video:
            problems.append(
                Problem(RejectCode.VALIDATION, f"{ref}: generated sources are video only", (ref,))
            )
        if occ.stream_index != 0:
            problems.append(
                Problem(
                    RejectCode.UNKNOWN_OBJECT, f"{ref}: generated sources have one stream", (ref,)
                )
            )
        duration = generated.duration
    if occ.source.out.seconds > duration:
        problems.append(
            Problem(
                RejectCode.OUTSIDE_SOURCE,
                f"{ref}: source out {occ.source.out.seconds} s exceeds the {duration} s source",
                (ref,),
            )
        )
    placement_problem = validate_placement(occ.placement, doc.profile.fps)
    if placement_problem is not None:
        problems.append(
            Problem(RejectCode.OUTSIDE_PLACED_RANGE, f"{ref}: {placement_problem.detail}", (ref,))
        )


def _check_no_overlap(
    container: str, occurrences: tuple[ClipOccurrence, ...], problems: list[Problem]
) -> None:
    ordered = sorted(occurrences, key=lambda o: o.place.start.index)
    for a, b in itertools.pairwise(ordered):
        if a.place.overlaps(b.place):
            problems.append(
                Problem(
                    RejectCode.OVERLAP,
                    f"{container}: {a.occurrence_id} {a.place.to_json()} overlaps"
                    f" {b.occurrence_id} {b.place.to_json()}",
                    (f"occurrence:{a.occurrence_id}", f"occurrence:{b.occurrence_id}"),
                )
            )


def validate_document(doc: ProjectDocument) -> tuple[Problem, ...]:
    """Structural validation of the complete document; an empty tuple means valid."""
    problems: list[Problem] = []
    seen_ids: dict[str, str] = {}

    def unique(kind: str, ident: str) -> None:
        key = f"{kind}:{ident}"
        if key in seen_ids:
            problems.append(Problem(RejectCode.DUPLICATE_OBJECT, f"duplicate {key}", (key,)))
        seen_ids[key] = key

    receipts = {p.receipt_id for p in doc.probes}
    if len(receipts) != len(doc.probes):
        problems.append(Problem(RejectCode.DUPLICATE_OBJECT, "duplicate probe receipts"))
    source_ids: set[str] = set()
    for asset in doc.assets:
        unique("asset", asset.asset_id)
        source_ids.add(asset.asset_id)
        if asset.identity.probe_receipt_id not in receipts:
            problems.append(
                Problem(
                    RejectCode.VALIDATION,
                    f"asset {asset.asset_id}: probe receipt not inline",
                    (f"asset:{asset.asset_id}",),
                )
            )
    for generated in doc.generated:
        if generated.source_id in source_ids:
            problems.append(
                Problem(
                    RejectCode.DUPLICATE_OBJECT,
                    f"generated {generated.source_id} collides with an asset id",
                )
            )
        unique("generated", generated.source_id)
    for layer in doc.sequence.video_layers:
        unique("layer", layer.layer_id)
        for occ in layer.occurrences:
            unique("occurrence", occ.occurrence_id)
            _check_occurrence(doc, occ, True, problems)
        _check_no_overlap(f"layer {layer.layer_id}", layer.occurrences, problems)
        occ_ids = {o.occurrence_id for o in layer.occurrences}
        pairs: set[tuple[str, str]] = set()
        for t in layer.transitions:
            unique("transition", t.transition_id)
            ref = f"transition:{t.transition_id}"
            if t.left_occurrence not in occ_ids or t.right_occurrence not in occ_ids:
                problems.append(
                    Problem(
                        RejectCode.UNKNOWN_OBJECT,
                        f"{ref}: neighbours must be on layer {layer.layer_id}",
                        (ref,),
                    )
                )
                continue
            if (t.left_occurrence, t.right_occurrence) in pairs:
                problems.append(
                    Problem(
                        RejectCode.DUPLICATE_OBJECT,
                        f"{ref}: second transition between the same neighbours",
                        (ref,),
                    )
                )
            pairs.add((t.left_occurrence, t.right_occurrence))
            left = doc.occurrence(t.left_occurrence)
            right = doc.occurrence(t.right_occurrence)
            assert left is not None and right is not None
            left_duration = doc.source_duration(left[0])
            right_duration = doc.source_duration(right[0])
            if left_duration is None or right_duration is None:
                continue
            handles = transition_handles(
                left[0].placement,
                right[0].placement,
                t.duration_frames,
                doc.profile.fps,
                left_duration,
                right_duration,
            )
            if isinstance(handles, InsufficientHandles):
                problems.append(
                    Problem(RejectCode.INSUFFICIENT_HANDLES, f"{ref}: {handles.detail}", (ref,))
                )
    for track in doc.sequence.audio_tracks:
        unique("track", track.track_id)
        for occ in track.occurrences:
            unique("occurrence", occ.occurrence_id)
            _check_occurrence(doc, occ, False, problems)
        _check_no_overlap(f"track {track.track_id}", track.occurrences, problems)
        if isinstance(track.mix.ducking, DuckUnder):
            duck = track.mix.ducking
            if doc.track(duck.speech_track_id) is None:
                problems.append(
                    Problem(
                        RejectCode.UNKNOWN_OBJECT,
                        f"track {track.track_id}: ducks under unknown track {duck.speech_track_id}",
                        (f"track:{track.track_id}",),
                    )
                )
            evidence = doc.analysis(duck.evidence)
            if evidence is None or evidence.kind is not AnalysisKind.TRANSCRIPT:
                problems.append(
                    Problem(
                        RejectCode.UNKNOWN_OBJECT,
                        f"track {track.track_id}: ducking evidence {duck.evidence} is not a"
                        " transcript",
                        (f"track:{track.track_id}",),
                    )
                )
    for title in doc.sequence.titles:
        unique("title", title.title_id)
    for caption in doc.sequence.captions:
        unique("caption", caption.caption_id)
        evidence = doc.analysis(caption.evidence)
        if evidence is None or evidence.kind is not AnalysisKind.TRANSCRIPT:
            problems.append(
                Problem(
                    RejectCode.UNKNOWN_OBJECT,
                    f"caption {caption.caption_id}: evidence {caption.evidence} is not a"
                    " transcript",
                    (f"caption:{caption.caption_id}",),
                )
            )
    for analysis in doc.analysis_refs:
        unique("analysis", analysis.ref_id)
    for effect in doc.effects:
        unique("effect", effect.effect_id)
        ref = f"effect:{effect.effect_id}"
        target_occ: ClipOccurrence | None = None
        match effect.target:
            case OccurrenceTarget(occurrence_id):
                found = doc.occurrence(occurrence_id)
                if found is None:
                    problems.append(
                        Problem(
                            RejectCode.UNKNOWN_OBJECT,
                            f"{ref}: targets unknown occurrence {occurrence_id}",
                            (ref,),
                        )
                    )
                else:
                    target_occ = found[0]
            case LayerTarget(layer_id):
                if doc.layer(layer_id) is None:
                    problems.append(
                        Problem(
                            RejectCode.UNKNOWN_OBJECT,
                            f"{ref}: targets unknown layer {layer_id}",
                            (ref,),
                        )
                    )
        if isinstance(effect.mask, MaskRef):
            track_ref = doc.analysis(effect.mask.track_version_id)
            if track_ref is None or track_ref.kind is not AnalysisKind.MASK_TRACK:
                problems.append(
                    Problem(
                        RejectCode.UNKNOWN_OBJECT,
                        f"{ref}: mask {effect.mask.track_version_id} is not a mask track",
                        (ref,),
                    )
                )
            elif target_occ is not None:
                binding = doc.binding_of(target_occ)
                if binding is None or (binding.asset_sha256, binding.stream_index) != (
                    track_ref.binding.asset_sha256,
                    track_ref.binding.stream_index,
                ):
                    problems.append(
                        Problem(
                            RejectCode.VALIDATION,
                            f"{ref}: mask {effect.mask.track_version_id} is bound to other"
                            " source bytes than its target",
                            (ref,),
                        )
                    )
            elif isinstance(effect.target, LayerTarget):
                problems.append(
                    Problem(
                        RejectCode.VALIDATION,
                        f"{ref}: a subject mask needs an occurrence target",
                        (ref,),
                    )
                )
    return tuple(problems)


def rejection_for(problems: tuple[Problem, ...]) -> Rejected:
    first = problems[0]
    detail = first.detail if len(problems) == 1 else f"{first.detail} (+{len(problems) - 1} more)"
    objects: list[str] = []
    for p in problems:
        objects.extend(o for o in p.objects if o not in objects)
    return Rejected.make(first.code, detail, tuple(objects))
