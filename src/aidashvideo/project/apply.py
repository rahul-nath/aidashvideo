"""Operation semantics: ``apply_batch(doc, batch, catalog, history)`` (contracts §6).

Every operation is validated against the catalog descriptors and the complete resulting
document before anything is admitted; any failing operation rejects the whole batch with a
typed reason and no mutation. Each applied operation yields its inverse (stored in the
event) and the object refs it affected.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from aidashvideo.catalog.descriptors import (
    Callable,
    DescriptorCatalog,
    ServiceDescriptor,
    ServiceType,
    ServiceUnavailable,
)
from aidashvideo.ledger.canonical import canonical_sha256
from aidashvideo.ledger.domain import HistoryView, IntentRequest
from aidashvideo.ledger.ids import IntentId, IntentKind, Sha256
from aidashvideo.ledger.results import RejectCode, Rejected
from aidashvideo.store.identity import AssetAvailability, Present

from .document import (
    AnalysisKind,
    AnalysisRef,
    AudioTrack,
    Caption,
    ClipOccurrence,
    DuckUnder,
    EffectBinding,
    EvidenceArtifact,
    LayerTarget,
    MaskRef,
    NoArtifact,
    ObjectKind,
    ObjectRef,
    OccurrenceTarget,
    PendingAnalysis,
    Problem,
    Produced,
    ProjectDocument,
    Sequence,
    ServiceRef,
    Title,
    Transition,
    UnavailableAnalysis,
    VideoLayer,
    rejection_for,
    validate_document,
)
from .operations import (
    Absent,
    AddAudioTrack,
    AddGeneratedSource,
    AddLayer,
    AddLink,
    AddTitle,
    AddTransition,
    BindEffect,
    BindSubjectEffect,
    ExistingTrack,
    Exists,
    InsertOccurrence,
    LayerRef,
    MoveOccurrence,
    Operation,
    OperationBatch,
    RebindAsset,
    RecompileWithNewCatalog,
    RecordAnalysis,
    RemoveAnalysis,
    RemoveAsset,
    RemoveAudioTrack,
    RemoveGeneratedSource,
    RemoveLayer,
    RemoveOccurrence,
    RemoveTitle,
    RemoveTransition,
    RetimeOccurrence,
    RevertOperation,
    SetAudioMix,
    SetCaptions,
    SetConstantSpeed,
    SetKeyframes,
    SetOutputProfile,
    SetParameter,
    SetTransitionSettings,
    ShiftTitle,
    SubjectRequest,
    TrackRef,
    TrimOccurrence,
    UnbindEffect,
    UnsetParameter,
)
from .params import Animated, FrameOffset, ParamAssignment, validate_assignment
from .timing import (
    InsufficientHandles,
    OutsidePlacedRange,
    SequenceSpan,
    SourceSpan,
    TimeMap,
    Timing,
    coverage_missing,
    duration_frames,
    place_source_span,
    transition_handles,
)

MASK_INTENT_DEADLINE_S = 600


@dataclass(frozen=True, slots=True)
class Step:
    document: ProjectDocument
    inverse: Operation
    affected: tuple[ObjectRef, ...]
    intents: tuple[IntentRequest, ...] = ()


@dataclass(frozen=True, slots=True)
class BatchApplied:
    document: ProjectDocument
    applied: tuple[Operation, ...]
    inverse: tuple[Operation, ...]
    affected: tuple[str, ...]
    intents: tuple[IntentRequest, ...]
    artifacts: tuple[Sha256, ...]
    """Evidence artifacts newly referenced by the result; the ledger requires them sealed."""


# ----------------------------------------------------------------------------- helpers


def _ref(kind: ObjectKind, ident: str) -> ObjectRef:
    return ObjectRef(kind, ident)


def _reject(code: RejectCode, detail: str, *refs: ObjectRef) -> Rejected:
    return Rejected.make(code, detail, tuple(str(r) for r in refs))


def _service(
    catalog: DescriptorCatalog, ref: ServiceRef, expected: ServiceType, context: ObjectRef
) -> ServiceDescriptor | Rejected:
    if ref.catalog_digest != catalog.digest:
        return _reject(
            RejectCode.CATALOG_MISMATCH,
            f"{context}: service {ref.service_id} is bound to catalog {ref.catalog_digest.hex[:12]}"
            f" but the installed catalog is {catalog.digest.hex[:12]}; RecompileWithNewCatalog"
            " is an explicit choice",
            context,
        )
    found = catalog.service(ref.service_id)
    if isinstance(found, ServiceUnavailable):
        return _reject(
            RejectCode.UNKNOWN_DESCRIPTOR,
            f"{context}: service {ref.service_id!r} is Unavailable: {found.reason}"
            f" ({found.required_action})",
            context,
        )
    assert isinstance(found, Callable)
    if found.descriptor.service_type is not expected:
        return _reject(
            RejectCode.VALIDATION,
            f"{context}: service {ref.service_id} is a {found.descriptor.service_type.value},"
            f" not a {expected.value}",
            context,
        )
    return found.descriptor


def _validate_params(
    descriptor: ServiceDescriptor, binding_params: tuple[ParamAssignment, ...], context: ObjectRef
) -> Rejected | None:
    for assignment in binding_params:
        problem = validate_assignment(descriptor, assignment, str(context))
        if problem is not None:
            return problem
    return None


def _with_sequence(doc: ProjectDocument, sequence: Sequence) -> ProjectDocument:
    return replace(doc, sequence=sequence)


def _replace_layer(doc: ProjectDocument, layer: VideoLayer) -> ProjectDocument:
    layers = tuple(layer if v.layer_id == layer.layer_id else v for v in doc.sequence.video_layers)
    return _with_sequence(doc, replace(doc.sequence, video_layers=layers))


def _replace_track(doc: ProjectDocument, track: AudioTrack) -> ProjectDocument:
    tracks = tuple(track if t.track_id == track.track_id else t for t in doc.sequence.audio_tracks)
    return _with_sequence(doc, replace(doc.sequence, audio_tracks=tracks))


def _replace_occurrence(doc: ProjectDocument, occ: ClipOccurrence) -> ProjectDocument:
    found = doc.occurrence(occ.occurrence_id)
    assert found is not None
    _, container = found
    if isinstance(container, VideoLayer):
        occurrences = tuple(
            occ if o.occurrence_id == occ.occurrence_id else o for o in container.occurrences
        )
        return _replace_layer(doc, replace(container, occurrences=occurrences))
    occurrences = tuple(
        occ if o.occurrence_id == occ.occurrence_id else o for o in container.occurrences
    )
    return _replace_track(doc, replace(container, occurrences=occurrences))


def _occ(
    doc: ProjectDocument, occurrence_id: str
) -> tuple[ClipOccurrence, VideoLayer | AudioTrack] | Rejected:
    found = doc.occurrence(occurrence_id)
    if found is None:
        return _reject(
            RejectCode.UNKNOWN_OBJECT,
            f"unknown occurrence {occurrence_id!r}",
            _ref(ObjectKind.OCCURRENCE, occurrence_id),
        )
    return found


def _replace_effect(doc: ProjectDocument, effect: EffectBinding) -> ProjectDocument:
    return replace(
        doc, effects=tuple(effect if e.effect_id == effect.effect_id else e for e in doc.effects)
    )


# ----------------------------------------------------------------------------- occurrences


def _insert_occurrence(
    doc: ProjectDocument, op: InsertOccurrence, catalog: DescriptorCatalog
) -> Step | Rejected:
    occ = op.occurrence
    ref = _ref(ObjectKind.OCCURRENCE, occ.occurrence_id)
    if doc.occurrence(occ.occurrence_id) is not None:
        return _reject(
            RejectCode.DUPLICATE_OBJECT, f"occurrence {occ.occurrence_id!r} already exists", ref
        )
    timing_problem = _check_timing_support(occ, catalog, ref)
    if timing_problem is not None:
        return timing_problem
    match op.container:
        case LayerRef(layer_id):
            layer = doc.layer(layer_id)
            if layer is None:
                return _reject(
                    RejectCode.UNKNOWN_OBJECT,
                    f"unknown layer {layer_id!r}",
                    _ref(ObjectKind.LAYER, layer_id),
                )
            new_doc = _replace_layer(doc, replace(layer, occurrences=(*layer.occurrences, occ)))
        case TrackRef(track_id):
            track = doc.track(track_id)
            if track is None:
                return _reject(
                    RejectCode.UNKNOWN_OBJECT,
                    f"unknown track {track_id!r}",
                    _ref(ObjectKind.TRACK, track_id),
                )
            new_doc = _replace_track(doc, replace(track, occurrences=(*track.occurrences, occ)))
    return Step(new_doc, RemoveOccurrence(op.container, occ.occurrence_id), (ref,))


def _remove_occurrence(doc: ProjectDocument, op: RemoveOccurrence) -> Step | Rejected:
    found = _occ(doc, op.occurrence_id)
    if isinstance(found, Rejected):
        return found
    occ, container = found
    ref = _ref(ObjectKind.OCCURRENCE, occ.occurrence_id)
    dependents = [
        str(_ref(ObjectKind.EFFECT, e.effect_id)) for e in doc.effects_on(occ.occurrence_id)
    ]
    dependents += [
        str(_ref(ObjectKind.TRANSITION, t.transition_id))
        for t in doc.transitions_on(occ.occurrence_id)
    ]
    if dependents:
        return Rejected.make(
            RejectCode.DEPENDENTS_EXIST,
            f"occurrence {occ.occurrence_id} still has dependents {dependents}; unbind or"
            " remove them first",
            (str(ref), *dependents),
        )
    if isinstance(container, VideoLayer):
        if not isinstance(op.container, LayerRef) or op.container.layer_id != container.layer_id:
            return _reject(
                RejectCode.UNKNOWN_OBJECT,
                f"occurrence {occ.occurrence_id} is not in {op.container}",
                ref,
            )
        new_doc = _replace_layer(
            doc,
            replace(
                container,
                occurrences=tuple(
                    o for o in container.occurrences if o.occurrence_id != occ.occurrence_id
                ),
            ),
        )
    else:
        if not isinstance(op.container, TrackRef) or op.container.track_id != container.track_id:
            return _reject(
                RejectCode.UNKNOWN_OBJECT,
                f"occurrence {occ.occurrence_id} is not in {op.container}",
                ref,
            )
        new_doc = _replace_track(
            doc,
            replace(
                container,
                occurrences=tuple(
                    o for o in container.occurrences if o.occurrence_id != occ.occurrence_id
                ),
            ),
        )
    return Step(new_doc, InsertOccurrence(op.container, occ), (ref,))


def _check_timing_support(
    occ: ClipOccurrence, catalog: DescriptorCatalog, ref: ObjectRef
) -> Rejected | None:
    timing = occ.timing
    if isinstance(timing, TimeMap):
        if timing.mode.value not in catalog.retime.modes:
            return _reject(
                RejectCode.UNSUPPORTED_SPEED,
                f"{ref}: retime mode {timing.mode.value} is not declared by the catalog"
                f" ({list(catalog.retime.modes)})",
                ref,
            )
        if timing.interpolation.value not in catalog.retime.interpolations:
            return _reject(
                RejectCode.UNSUPPORTED_SPEED,
                f"{ref}: interpolation {timing.interpolation.value} is not declared by the catalog",
                ref,
            )
        return None
    ratio = timing.ratio
    if not catalog.retime.min_speed <= ratio <= catalog.retime.max_speed:
        return _reject(
            RejectCode.UNSUPPORTED_SPEED,
            f"{ref}: speed {ratio} is outside the catalog range"
            f" [{catalog.retime.min_speed}, {catalog.retime.max_speed}]",
            ref,
        )
    return None


def _retimed(
    doc: ProjectDocument, occ: ClipOccurrence, source: SourceSpan, timing: Timing
) -> ClipOccurrence:
    frames = duration_frames(source, timing, doc.profile.fps)
    start = occ.place.start.index
    return replace(
        occ, source=source, timing=timing, place=SequenceSpan.make(start, start + frames)
    )


def _trim(doc: ProjectDocument, op: TrimOccurrence) -> Step | Rejected:
    found = _occ(doc, op.occurrence_id)
    if isinstance(found, Rejected):
        return found
    occ, _ = found
    ref = _ref(ObjectKind.OCCURRENCE, occ.occurrence_id)
    new_occ = _retimed(doc, occ, op.source, occ.timing)
    return Step(
        _replace_occurrence(doc, new_occ), TrimOccurrence(occ.occurrence_id, occ.source), (ref,)
    )


def _move(doc: ProjectDocument, op: MoveOccurrence) -> Step | Rejected:
    found = _occ(doc, op.occurrence_id)
    if isinstance(found, Rejected):
        return found
    occ, _ = found
    ref = _ref(ObjectKind.OCCURRENCE, occ.occurrence_id)
    new_occ = replace(
        occ, place=SequenceSpan.make(op.start.index, op.start.index + occ.place.frames)
    )
    return Step(
        _replace_occurrence(doc, new_occ),
        MoveOccurrence(occ.occurrence_id, occ.place.start),
        (ref,),
    )


def _inverse_timing(occ: ClipOccurrence) -> Operation:
    if isinstance(occ.timing, TimeMap):
        return RetimeOccurrence(occ.occurrence_id, occ.timing)
    return SetConstantSpeed(occ.occurrence_id, occ.timing)


def _set_speed(
    doc: ProjectDocument, op: SetConstantSpeed, catalog: DescriptorCatalog
) -> Step | Rejected:
    found = _occ(doc, op.occurrence_id)
    if isinstance(found, Rejected):
        return found
    occ, _ = found
    ref = _ref(ObjectKind.OCCURRENCE, occ.occurrence_id)
    new_occ = _retimed(doc, occ, occ.source, op.speed)
    problem = _check_timing_support(new_occ, catalog, ref)
    if problem is not None:
        return problem
    return Step(_replace_occurrence(doc, new_occ), _inverse_timing(occ), (ref,))


def _retime(
    doc: ProjectDocument, op: RetimeOccurrence, catalog: DescriptorCatalog
) -> Step | Rejected:
    found = _occ(doc, op.occurrence_id)
    if isinstance(found, Rejected):
        return found
    occ, _ = found
    ref = _ref(ObjectKind.OCCURRENCE, occ.occurrence_id)
    new_occ = _retimed(doc, occ, occ.source, op.map)
    problem = _check_timing_support(new_occ, catalog, ref)
    if problem is not None:
        return problem
    return Step(_replace_occurrence(doc, new_occ), _inverse_timing(occ), (ref,))


# ----------------------------------------------------------------------------- transitions


def _check_transition(
    doc: ProjectDocument, layer: VideoLayer, transition: Transition, catalog: DescriptorCatalog
) -> Rejected | None:
    ref = _ref(ObjectKind.TRANSITION, transition.transition_id)
    descriptor = _service(catalog, transition.kind, ServiceType.TRANSITION, ref)
    if isinstance(descriptor, Rejected):
        return descriptor
    problem = _validate_params(descriptor, transition.params, ref)
    if problem is not None:
        return problem
    by_id = {o.occurrence_id: o for o in layer.occurrences}
    left = by_id.get(transition.left_occurrence)
    right = by_id.get(transition.right_occurrence)
    if left is None or right is None:
        return _reject(
            RejectCode.UNKNOWN_OBJECT,
            f"{ref}: both neighbours must be occurrences on layer {layer.layer_id}",
            ref,
        )
    left_duration = doc.source_duration(left)
    right_duration = doc.source_duration(right)
    if left_duration is None or right_duration is None:
        return _reject(RejectCode.UNKNOWN_OBJECT, f"{ref}: a neighbour has no source", ref)
    handles = transition_handles(
        left.placement,
        right.placement,
        transition.duration_frames,
        doc.profile.fps,
        left_duration,
        right_duration,
    )
    if isinstance(handles, InsufficientHandles):
        return _reject(RejectCode.INSUFFICIENT_HANDLES, f"{ref}: {handles.detail}", ref)
    return None


def _add_transition(
    doc: ProjectDocument, op: AddTransition, catalog: DescriptorCatalog
) -> Step | Rejected:
    ref = _ref(ObjectKind.TRANSITION, op.transition.transition_id)
    layer = doc.layer(op.layer_id)
    if layer is None:
        return _reject(
            RejectCode.UNKNOWN_OBJECT,
            f"unknown layer {op.layer_id!r}",
            _ref(ObjectKind.LAYER, op.layer_id),
        )
    if doc.transition(op.transition.transition_id) is not None:
        return _reject(
            RejectCode.DUPLICATE_OBJECT,
            f"transition {op.transition.transition_id!r} already exists",
            ref,
        )
    problem = _check_transition(doc, layer, op.transition, catalog)
    if problem is not None:
        return problem
    new_doc = _replace_layer(doc, replace(layer, transitions=(*layer.transitions, op.transition)))
    return Step(new_doc, RemoveTransition(op.layer_id, op.transition.transition_id), (ref,))


def _remove_transition(doc: ProjectDocument, op: RemoveTransition) -> Step | Rejected:
    ref = _ref(ObjectKind.TRANSITION, op.transition_id)
    found = doc.transition(op.transition_id)
    if found is None or found[1].layer_id != op.layer_id:
        return _reject(
            RejectCode.UNKNOWN_OBJECT,
            f"unknown transition {op.transition_id!r} on layer {op.layer_id}",
            ref,
        )
    transition, layer = found
    new_doc = _replace_layer(
        doc,
        replace(
            layer,
            transitions=tuple(t for t in layer.transitions if t.transition_id != op.transition_id),
        ),
    )
    return Step(new_doc, AddTransition(op.layer_id, transition), (ref,))


def _set_transition_settings(
    doc: ProjectDocument, op: SetTransitionSettings, catalog: DescriptorCatalog
) -> Step | Rejected:
    ref = _ref(ObjectKind.TRANSITION, op.transition_id)
    found = doc.transition(op.transition_id)
    if found is None:
        return _reject(RejectCode.UNKNOWN_OBJECT, f"unknown transition {op.transition_id!r}", ref)
    transition, layer = found
    updated = replace(transition, duration_frames=op.duration_frames, params=op.params)
    problem = _check_transition(doc, layer, updated, catalog)
    if problem is not None:
        return problem
    new_doc = _replace_layer(
        doc,
        replace(
            layer,
            transitions=tuple(
                updated if t.transition_id == op.transition_id else t for t in layer.transitions
            ),
        ),
    )
    return Step(
        new_doc,
        SetTransitionSettings(op.transition_id, transition.duration_frames, transition.params),
        (ref,),
    )


# ------------------------------------------------------------------ audio, titles, captions


def _set_audio_mix(doc: ProjectDocument, op: SetAudioMix) -> Step | Rejected:
    ref = _ref(ObjectKind.TRACK, op.track_id)
    track = doc.track(op.track_id)
    if track is None:
        return _reject(RejectCode.UNKNOWN_OBJECT, f"unknown track {op.track_id!r}", ref)
    return Step(
        _replace_track(doc, replace(track, mix=op.mix)), SetAudioMix(op.track_id, track.mix), (ref,)
    )


def _add_title(doc: ProjectDocument, op: AddTitle) -> Step | Rejected:
    ref = _ref(ObjectKind.TITLE, op.title_id)
    if doc.title(op.title_id) is not None:
        return _reject(RejectCode.DUPLICATE_OBJECT, f"title {op.title_id!r} already exists", ref)
    if op.start_frame < 0:
        return _reject(
            RejectCode.NEGATIVE_START,
            f"{ref}: start frame {op.start_frame} is before the sequence start",
            ref,
        )
    if op.duration_frames < 1:
        return _reject(RejectCode.VALIDATION, f"{ref}: duration must be at least one frame", ref)
    title = Title(
        op.title_id,
        op.text,
        SequenceSpan.make(op.start_frame, op.start_frame + op.duration_frames),
        op.style,
    )
    new_doc = _with_sequence(doc, replace(doc.sequence, titles=(*doc.sequence.titles, title)))
    return Step(new_doc, RemoveTitle(op.title_id), (ref,))


def _remove_title(doc: ProjectDocument, op: RemoveTitle) -> Step | Rejected:
    ref = _ref(ObjectKind.TITLE, op.title_id)
    title = doc.title(op.title_id)
    if title is None:
        return _reject(RejectCode.UNKNOWN_OBJECT, f"unknown title {op.title_id!r}", ref)
    new_doc = _with_sequence(
        doc,
        replace(
            doc.sequence, titles=tuple(t for t in doc.sequence.titles if t.title_id != op.title_id)
        ),
    )
    inverse = AddTitle(
        title.title_id, title.text, title.place.start.index, title.place.frames, title.style
    )
    return Step(new_doc, inverse, (ref,))


def _shift_title(doc: ProjectDocument, op: ShiftTitle) -> Step | Rejected:
    ref = _ref(ObjectKind.TITLE, op.title_id)
    title = doc.title(op.title_id)
    if title is None:
        return _reject(RejectCode.UNKNOWN_OBJECT, f"unknown title {op.title_id!r}", ref)
    shifted = title.place.shifted(op.delta_frames)
    if not isinstance(shifted, SequenceSpan):
        return _reject(
            RejectCode.NEGATIVE_START,
            f"{ref}: shifting by {op.delta_frames} frames would start at frame"
            f" {shifted.would_be_start}",
            ref,
        )
    new_title = replace(title, place=shifted)
    new_doc = _with_sequence(
        doc,
        replace(
            doc.sequence,
            titles=tuple(
                new_title if t.title_id == op.title_id else t for t in doc.sequence.titles
            ),
        ),
    )
    return Step(new_doc, ShiftTitle(op.title_id, -op.delta_frames), (ref,))


def _set_captions(doc: ProjectDocument, op: SetCaptions) -> Step | Rejected:
    ids = [c.caption_id for c in op.captions]
    if len(set(ids)) != len(ids):
        return _reject(
            RejectCode.DUPLICATE_OBJECT, "duplicate caption ids", _ref(ObjectKind.CAPTIONS, "all")
        )
    for caption in op.captions:
        problem = _check_caption(doc, caption)
        if problem is not None:
            return problem
    before = {c.caption_id: c for c in doc.sequence.captions}
    after = {c.caption_id: c for c in op.captions}
    changed = sorted(cid for cid in set(before) | set(after) if before.get(cid) != after.get(cid))
    affected = (
        _ref(ObjectKind.CAPTIONS, "all"),
        *(_ref(ObjectKind.CAPTION, cid) for cid in changed),
    )
    new_doc = _with_sequence(doc, replace(doc.sequence, captions=op.captions))
    return Step(new_doc, SetCaptions(doc.sequence.captions), affected)


def _check_caption(doc: ProjectDocument, caption: Caption) -> Rejected | None:
    """The caption's placement must be what the shared map realizes for its requested
    transcript interval through some occurrence of the evidence's source (one run of
    ``timing.place_source_span``); anything else is ``OutsidePlacedRange``, never clamped."""
    ref = _ref(ObjectKind.CAPTION, caption.caption_id)
    evidence = doc.analysis(caption.evidence)
    if evidence is None or evidence.kind is not AnalysisKind.TRANSCRIPT:
        return _reject(
            RejectCode.UNKNOWN_OBJECT,
            f"{ref}: evidence {caption.evidence!r} is not a transcript ref",
            ref,
        )
    if not any(span.covers(caption.requested) for span in evidence.coverage):
        return _reject(
            RejectCode.OUTSIDE_PLACED_RANGE,
            f"{ref}: requested {caption.requested.to_json()} is not inside the transcript's"
            " coverage",
            ref,
        )
    for occ in doc.all_occurrences():
        binding = doc.binding_of(occ)
        if binding is None or binding.asset_sha256 != evidence.binding.asset_sha256:
            continue
        placed = place_source_span(occ.placement, caption.requested, doc.profile.fps)
        if isinstance(placed, OutsidePlacedRange):
            continue
        if any(run.frames == caption.place for run in placed.runs):
            return None
    return _reject(
        RejectCode.OUTSIDE_PLACED_RANGE,
        f"{ref}: {caption.place.to_json()} is not what the map realizes for"
        f" {caption.requested.to_json()} through any occurrence of the evidence's source",
        ref,
    )


# ----------------------------------------------------------------------------- effects


def _bind_effect(
    doc: ProjectDocument, binding: EffectBinding, catalog: DescriptorCatalog, expected: ServiceType
) -> Rejected | None:
    ref = _ref(ObjectKind.EFFECT, binding.effect_id)
    if doc.effect(binding.effect_id) is not None:
        return _reject(
            RejectCode.DUPLICATE_OBJECT, f"effect {binding.effect_id!r} already exists", ref
        )
    descriptor = _service(catalog, binding.service, expected, ref)
    if isinstance(descriptor, Rejected):
        return descriptor
    problem = _validate_params(descriptor, binding.params, ref)
    if problem is not None:
        return problem
    match binding.target:
        case OccurrenceTarget(occurrence_id):
            if doc.occurrence(occurrence_id) is None:
                return _reject(
                    RejectCode.UNKNOWN_OBJECT, f"{ref}: unknown occurrence {occurrence_id!r}", ref
                )
        case LayerTarget(layer_id):
            if doc.layer(layer_id) is None:
                return _reject(RejectCode.UNKNOWN_OBJECT, f"{ref}: unknown layer {layer_id!r}", ref)
    return None


def _bind_plain(
    doc: ProjectDocument, binding: EffectBinding, catalog: DescriptorCatalog, expected: ServiceType
) -> Step | Rejected:
    problem = _bind_effect(doc, binding, catalog, expected)
    if problem is not None:
        return problem
    ref = _ref(ObjectKind.EFFECT, binding.effect_id)
    return Step(
        replace(doc, effects=(*doc.effects, binding)), UnbindEffect(binding.effect_id), (ref,)
    )


def _bind_subject(
    doc: ProjectDocument, op: BindSubjectEffect, catalog: DescriptorCatalog, intent_scope: str
) -> Step | Rejected:
    binding = op.binding
    ref = _ref(ObjectKind.EFFECT, binding.effect_id)
    problem = _bind_effect(doc, binding, catalog, ServiceType.FILTER)
    if problem is not None:
        return problem
    assert isinstance(binding.target, OccurrenceTarget) and isinstance(binding.mask, MaskRef)
    found = doc.occurrence(binding.target.occurrence_id)
    assert found is not None
    occ, container = found
    if not isinstance(container, VideoLayer):
        return _reject(
            RejectCode.VALIDATION, f"{ref}: subject effects apply to video occurrences", ref
        )
    source_binding = doc.binding_of(occ)
    if source_binding is None:
        return _reject(
            RejectCode.VALIDATION, f"{ref}: generated sources have no subject to track", ref
        )
    track_id = binding.mask.track_version_id
    analysis_ref = _ref(ObjectKind.ANALYSIS, track_id)
    existing = doc.analysis(track_id)
    intents: tuple[IntentRequest, ...] = ()
    affected: tuple[ObjectRef, ...] = (ref,)
    new_refs = doc.analysis_refs
    if existing is not None:
        if existing.kind is not AnalysisKind.MASK_TRACK:
            return _reject(RejectCode.VALIDATION, f"{ref}: {track_id} is not a mask track", ref)
        if (existing.binding.asset_sha256, existing.binding.stream_index) != (
            source_binding.asset_sha256,
            source_binding.stream_index,
        ):
            return _reject(
                RejectCode.VALIDATION,
                f"{ref}: mask track {track_id} is bound to other source bytes",
                ref,
                analysis_ref,
            )
    else:
        if isinstance(op.request, ExistingTrack):
            return _reject(
                RejectCode.UNKNOWN_OBJECT,
                f"{ref}: mask track {track_id!r} does not exist; a new binding needs a"
                " SubjectRequest",
                ref,
            )
        request: SubjectRequest = op.request
        if not request.requested.covers(occ.source):
            return _reject(
                RejectCode.VALIDATION,
                f"{ref}: requested coverage {request.requested.to_json()} does not cover the"
                f" occurrence source {occ.source.to_json()}",
                ref,
            )
        new_refs = (
            *doc.analysis_refs,
            AnalysisRef(
                AnalysisKind.MASK_TRACK,
                track_id,
                source_binding,
                (),
                PendingAnalysis(request.requested),
                NoArtifact(),
            ),
        )
        affected = (ref, analysis_ref)
        spec: dict[str, object] = {
            "kind": "Mask",
            "track_version_id": track_id,
            "binding": source_binding.to_json(),
            "requested": request.requested.to_json(),
            "concept": request.concept.to_json(),
            "profile": request.profile,
            "effect_id": binding.effect_id,
        }
        intent_id = IntentId(
            f"mask-{canonical_sha256({'track': track_id, 'scope': intent_scope}).hex[:32]}"
        )
        intents = (IntentRequest(intent_id, IntentKind.MASK, spec, MASK_INTENT_DEADLINE_S),)
    new_doc = replace(doc, effects=(*doc.effects, binding), analysis_refs=new_refs)
    return Step(new_doc, UnbindEffect(binding.effect_id), affected, intents)


def _unbind_effect(doc: ProjectDocument, op: UnbindEffect) -> Step | Rejected:
    ref = _ref(ObjectKind.EFFECT, op.effect_id)
    effect = doc.effect(op.effect_id)
    if effect is None:
        return _reject(RejectCode.UNKNOWN_OBJECT, f"unknown effect {op.effect_id!r}", ref)
    new_doc = replace(doc, effects=tuple(e for e in doc.effects if e.effect_id != op.effect_id))
    inverse: Operation
    if isinstance(effect.mask, MaskRef):
        inverse = BindSubjectEffect(effect, ExistingTrack())
    else:
        inverse = BindEffect(effect)
    return Step(new_doc, inverse, (ref,))


def _effect_descriptor(
    doc: ProjectDocument, effect_id: str, catalog: DescriptorCatalog
) -> tuple[EffectBinding, ServiceDescriptor] | Rejected:
    ref = _ref(ObjectKind.EFFECT, effect_id)
    effect = doc.effect(effect_id)
    if effect is None:
        return _reject(RejectCode.UNKNOWN_OBJECT, f"unknown effect {effect_id!r}", ref)
    expected = ServiceType.FILTER
    found = catalog.service(effect.service.service_id)
    if isinstance(found, Callable) and found.descriptor.service_type is ServiceType.LINK:
        expected = ServiceType.LINK
    descriptor = _service(catalog, effect.service, expected, ref)
    if isinstance(descriptor, Rejected):
        return descriptor
    return effect, descriptor


def _set_parameter(
    doc: ProjectDocument, op: SetParameter | SetKeyframes, catalog: DescriptorCatalog
) -> Step | Rejected:
    found = _effect_descriptor(doc, op.effect_id, catalog)
    if isinstance(found, Rejected):
        return found
    effect, descriptor = found
    ref = _ref(ObjectKind.EFFECT, effect.effect_id)
    problem = validate_assignment(descriptor, op.assignment, str(ref))
    if problem is not None:
        return problem
    if isinstance(op.assignment.value, Animated) and isinstance(effect.target, OccurrenceTarget):
        occurrence = doc.occurrence(effect.target.occurrence_id)
        assert occurrence is not None
        for keyframe in op.assignment.value.keyframes:
            if (
                isinstance(keyframe.at, FrameOffset)
                and keyframe.at.frame >= occurrence[0].place.frames
            ):
                return _reject(
                    RejectCode.OUTSIDE_PLACED_RANGE,
                    f"{ref}: keyframe at offset {keyframe.at.frame} is beyond the"
                    f" {occurrence[0].place.frames}-frame occurrence",
                    ref,
                )
    previous = next((p for p in effect.params if p.param_id == op.assignment.param_id), None)
    params = tuple(
        op.assignment if p.param_id == op.assignment.param_id else p for p in effect.params
    )
    if previous is None:
        params = (*effect.params, op.assignment)
    inverse: Operation = (
        UnsetParameter(effect.effect_id, op.assignment.param_id)
        if previous is None
        else SetParameter(effect.effect_id, previous)
    )
    return Step(_replace_effect(doc, replace(effect, params=params)), inverse, (ref,))


def _unset_parameter(doc: ProjectDocument, op: UnsetParameter) -> Step | Rejected:
    ref = _ref(ObjectKind.EFFECT, op.effect_id)
    effect = doc.effect(op.effect_id)
    if effect is None:
        return _reject(RejectCode.UNKNOWN_OBJECT, f"unknown effect {op.effect_id!r}", ref)
    previous = next((p for p in effect.params if p.param_id == op.param_id), None)
    if previous is None:
        return _reject(
            RejectCode.UNKNOWN_PARAMETER, f"{ref}: parameter {op.param_id!r} is not set", ref
        )
    params = tuple(p for p in effect.params if p.param_id != op.param_id)
    return Step(
        _replace_effect(doc, replace(effect, params=params)),
        SetParameter(op.effect_id, previous),
        (ref,),
    )


# ------------------------------------------------------------ sources, layers, tracks, profile


def _add_generated(
    doc: ProjectDocument, op: AddGeneratedSource, catalog: DescriptorCatalog
) -> Step | Rejected:
    source = op.source
    ref = _ref(ObjectKind.GENERATED, source.source_id)
    if (
        doc.generated_source(source.source_id) is not None
        or doc.asset(source.source_id) is not None
    ):
        return _reject(
            RejectCode.DUPLICATE_OBJECT, f"source id {source.source_id!r} already exists", ref
        )
    descriptor = _service(catalog, source.service, ServiceType.PRODUCER, ref)
    if isinstance(descriptor, Rejected):
        return descriptor
    problem = _validate_params(descriptor, source.params, ref)
    if problem is not None:
        return problem
    return Step(
        replace(doc, generated=(*doc.generated, source)),
        RemoveGeneratedSource(source.source_id),
        (ref,),
    )


def _remove_generated(doc: ProjectDocument, op: RemoveGeneratedSource) -> Step | Rejected:
    ref = _ref(ObjectKind.GENERATED, op.source_id)
    source = doc.generated_source(op.source_id)
    if source is None:
        return _reject(RejectCode.UNKNOWN_OBJECT, f"unknown generated source {op.source_id!r}", ref)
    users = [o.occurrence_id for o in doc.all_occurrences() if o.asset_id == op.source_id]
    if users:
        return Rejected.make(
            RejectCode.DEPENDENTS_EXIST,
            f"generated source {op.source_id} is used by {users}",
            (str(ref), *(f"occurrence:{u}" for u in users)),
        )
    return Step(
        replace(doc, generated=tuple(g for g in doc.generated if g.source_id != op.source_id)),
        AddGeneratedSource(source),
        (ref,),
    )


def _add_layer(doc: ProjectDocument, op: AddLayer) -> Step | Rejected:
    ref = _ref(ObjectKind.LAYER, op.layer_id)
    if doc.layer(op.layer_id) is not None:
        return _reject(RejectCode.DUPLICATE_OBJECT, f"layer {op.layer_id!r} already exists", ref)
    layers = list(doc.sequence.video_layers)
    new_layer = VideoLayer(op.layer_id, (), ())
    if op.above == "bottom":
        layers.insert(0, new_layer)
    else:
        index = next((i for i, v in enumerate(layers) if v.layer_id == op.above), None)
        if index is None:
            return _reject(
                RejectCode.UNKNOWN_OBJECT, f"unknown layer {op.above!r} to stack above", ref
            )
        layers.insert(index + 1, new_layer)
    return Step(
        _with_sequence(doc, replace(doc.sequence, video_layers=tuple(layers))),
        RemoveLayer(op.layer_id),
        (ref,),
    )


def _remove_layer(doc: ProjectDocument, op: RemoveLayer) -> Step | Rejected:
    ref = _ref(ObjectKind.LAYER, op.layer_id)
    layers = list(doc.sequence.video_layers)
    index = next((i for i, v in enumerate(layers) if v.layer_id == op.layer_id), None)
    if index is None:
        return _reject(RejectCode.UNKNOWN_OBJECT, f"unknown layer {op.layer_id!r}", ref)
    layer = layers[index]
    dependents = [
        f"effect:{e.effect_id}"
        for e in doc.effects
        if isinstance(e.target, LayerTarget) and e.target.layer_id == op.layer_id
    ]
    if layer.occurrences or layer.transitions or dependents:
        return Rejected.make(
            RejectCode.DEPENDENTS_EXIST,
            f"layer {op.layer_id} is not empty",
            (str(ref), *dependents),
        )
    if len(layers) == 1:
        return _reject(RejectCode.VALIDATION, "the last video layer cannot be removed", ref)
    below = "bottom" if index == 0 else layers[index - 1].layer_id
    del layers[index]
    return Step(
        _with_sequence(doc, replace(doc.sequence, video_layers=tuple(layers))),
        AddLayer(op.layer_id, below),
        (ref,),
    )


def _add_track(doc: ProjectDocument, op: AddAudioTrack) -> Step | Rejected:
    ref = _ref(ObjectKind.TRACK, op.track_id)
    if doc.track(op.track_id) is not None:
        return _reject(RejectCode.DUPLICATE_OBJECT, f"track {op.track_id!r} already exists", ref)
    tracks = (*doc.sequence.audio_tracks, AudioTrack(op.track_id, (), op.mix))
    return Step(
        _with_sequence(doc, replace(doc.sequence, audio_tracks=tracks)),
        RemoveAudioTrack(op.track_id),
        (ref,),
    )


def _remove_track(doc: ProjectDocument, op: RemoveAudioTrack) -> Step | Rejected:
    ref = _ref(ObjectKind.TRACK, op.track_id)
    track = doc.track(op.track_id)
    if track is None:
        return _reject(RejectCode.UNKNOWN_OBJECT, f"unknown track {op.track_id!r}", ref)
    duckers = [
        t.track_id
        for t in doc.sequence.audio_tracks
        if isinstance(t.mix.ducking, DuckUnder) and t.mix.ducking.speech_track_id == op.track_id
    ]
    if track.occurrences or duckers:
        return Rejected.make(
            RejectCode.DEPENDENTS_EXIST,
            f"track {op.track_id} is not empty or is ducked under",
            (str(ref), *(f"track:{t}" for t in duckers)),
        )
    tracks = tuple(t for t in doc.sequence.audio_tracks if t.track_id != op.track_id)
    return Step(
        _with_sequence(doc, replace(doc.sequence, audio_tracks=tracks)),
        AddAudioTrack(op.track_id, track.mix),
        (ref,),
    )


def _set_profile(
    doc: ProjectDocument, op: SetOutputProfile, catalog: DescriptorCatalog
) -> Step | Rejected:
    ref = _ref(ObjectKind.PROFILE, "output")
    profile = op.profile
    limits = catalog.profile
    reasons: list[str] = []
    if profile.fps not in limits.frame_rates:
        reasons.append(f"frame rate {profile.fps} not in {[str(f) for f in limits.frame_rates]}")
    if profile.width > limits.max_width or profile.height > limits.max_height:
        reasons.append(
            f"{profile.width}x{profile.height} exceeds {limits.max_width}x{limits.max_height}"
        )
    if profile.audio.sample_rate not in limits.sample_rates:
        reasons.append(
            f"sample rate {profile.audio.sample_rate} not in {list(limits.sample_rates)}"
        )
    if profile.audio.layout.value not in limits.layouts:
        reasons.append(f"layout {profile.audio.layout.value} not in {list(limits.layouts)}")
    if profile.container.value not in limits.containers:
        reasons.append(f"container {profile.container.value} not in {list(limits.containers)}")
    if "Sdr709" not in limits.colors:
        reasons.append("catalog declares no SDR Rec.709 output")
    if reasons:
        return _reject(RejectCode.UNSUPPORTED_PROFILE, f"{ref}: " + "; ".join(reasons), ref)
    populated = bool(doc.all_occurrences() or doc.sequence.titles or doc.sequence.captions)
    if populated and profile.fps != doc.profile.fps:
        return _reject(
            RejectCode.UNSUPPORTED_PROFILE,
            f"{ref}: changing the frame rate of a populated sequence ({doc.profile.fps} ->"
            f" {profile.fps}) would retime every placement",
            ref,
        )
    return Step(replace(doc, profile=profile), SetOutputProfile(doc.profile), (ref,))


def _rebind_asset(doc: ProjectDocument, op: RebindAsset) -> Step | Rejected:
    asset = op.asset
    ref = _ref(ObjectKind.ASSET, asset.asset_id)
    if not isinstance(asset.availability, Present):
        return _reject(
            RejectCode.ASSET_NOT_VERIFIED,
            f"{ref}: binding needs verified bytes (Present), got"
            f" {type(asset.availability).__name__}",
            ref,
        )
    if doc.generated_source(asset.asset_id) is not None:
        return _reject(
            RejectCode.DUPLICATE_OBJECT, f"{ref}: id collides with a generated source", ref
        )
    probes = doc.probes if doc.probe(op.probe.receipt_id) is not None else (*doc.probes, op.probe)
    previous = doc.asset(asset.asset_id)
    inverse: Operation
    if previous is None:
        assets = (*doc.assets, asset)
        inverse = RemoveAsset(asset.asset_id)
    else:
        assets = tuple(asset if a.asset_id == asset.asset_id else a for a in doc.assets)
        previous_probe = doc.probe(previous.identity.probe_receipt_id)
        assert previous_probe is not None
        inverse = RebindAsset(previous, previous_probe)
    return Step(replace(doc, assets=assets, probes=probes), inverse, (ref,))


def _remove_asset(doc: ProjectDocument, op: RemoveAsset) -> Step | Rejected:
    ref = _ref(ObjectKind.ASSET, op.asset_id)
    asset = doc.asset(op.asset_id)
    if asset is None:
        return _reject(RejectCode.UNKNOWN_OBJECT, f"unknown asset {op.asset_id!r}", ref)
    users = [o.occurrence_id for o in doc.all_occurrences() if o.asset_id == op.asset_id]
    if users:
        return Rejected.make(
            RejectCode.DEPENDENTS_EXIST,
            f"asset {op.asset_id} is used by {users}",
            (str(ref), *(f"occurrence:{u}" for u in users)),
        )
    probe = doc.probe(asset.identity.probe_receipt_id)
    assert probe is not None
    return Step(
        replace(doc, assets=tuple(a for a in doc.assets if a.asset_id != op.asset_id)),
        RebindAsset(asset, probe),
        (ref,),
    )


def _record_analysis(doc: ProjectDocument, op: RecordAnalysis) -> Step | Rejected:
    ref = _ref(ObjectKind.ANALYSIS, op.ref.ref_id)
    existing = doc.analysis(op.ref.ref_id)
    if existing is not None and existing.kind is not op.ref.kind:
        return _reject(
            RejectCode.VALIDATION, f"{ref}: kind differs from the recorded reference", ref
        )
    if existing is not None and existing.binding != op.ref.binding:
        return _reject(
            RejectCode.VALIDATION, f"{ref}: bound to other source bytes than recorded", ref
        )
    known = {a.identity.sha256 for a in doc.assets}
    if op.ref.binding.asset_sha256 not in known:
        return _reject(
            RejectCode.UNKNOWN_OBJECT, f"{ref}: no asset with the bound content hash", ref
        )
    if existing is None:
        refs = (*doc.analysis_refs, op.ref)
        inverse: Operation = RemoveAnalysis(op.ref.ref_id)
    else:
        refs = tuple(op.ref if a.ref_id == op.ref.ref_id else a for a in doc.analysis_refs)
        inverse = RecordAnalysis(existing)
    return Step(replace(doc, analysis_refs=refs), inverse, (ref,))


def _remove_analysis(doc: ProjectDocument, op: RemoveAnalysis) -> Step | Rejected:
    ref = _ref(ObjectKind.ANALYSIS, op.ref_id)
    existing = doc.analysis(op.ref_id)
    if existing is None:
        return _reject(RejectCode.UNKNOWN_OBJECT, f"unknown analysis reference {op.ref_id!r}", ref)
    users = [
        f"effect:{e.effect_id}"
        for e in doc.effects
        if isinstance(e.mask, MaskRef) and e.mask.track_version_id == op.ref_id
    ]
    users += [f"caption:{c.caption_id}" for c in doc.sequence.captions if c.evidence == op.ref_id]
    users += [
        f"track:{t.track_id}"
        for t in doc.sequence.audio_tracks
        if isinstance(t.mix.ducking, DuckUnder) and t.mix.ducking.evidence == op.ref_id
    ]
    if users:
        return Rejected.make(
            RejectCode.DEPENDENTS_EXIST,
            f"analysis {op.ref_id} is cited by {users}",
            (str(ref), *users),
        )
    refs = tuple(a for a in doc.analysis_refs if a.ref_id != op.ref_id)
    return Step(replace(doc, analysis_refs=refs), RecordAnalysis(existing), (ref,))


def _recompile(
    doc: ProjectDocument, op: RecompileWithNewCatalog, catalog: DescriptorCatalog
) -> Step | Rejected:
    ref = _ref(ObjectKind.PROFILE, "catalog")
    if op.to_digest != catalog.digest:
        return _reject(
            RejectCode.CATALOG_MISMATCH,
            f"target digest {op.to_digest.hex[:12]} is not the installed catalog"
            f" {catalog.digest.hex[:12]}",
            ref,
        )
    missing: list[str] = []

    def rebound(service: ServiceRef) -> ServiceRef:
        if service.catalog_digest != op.from_digest:
            return service
        if not isinstance(catalog.service(service.service_id), Callable):
            missing.append(service.service_id)
        return ServiceRef(service.service_id, op.to_digest)

    effects = tuple(replace(e, service=rebound(e.service)) for e in doc.effects)
    generated = tuple(replace(g, service=rebound(g.service)) for g in doc.generated)
    layers = tuple(
        replace(
            layer, transitions=tuple(replace(t, kind=rebound(t.kind)) for t in layer.transitions)
        )
        for layer in doc.sequence.video_layers
    )
    if missing:
        return _reject(
            RejectCode.CATALOG_MISMATCH,
            f"services {sorted(set(missing))} are not callable in the installed catalog; no"
            " silent fallback",
            ref,
        )
    new_doc = replace(
        doc,
        effects=effects,
        generated=generated,
        sequence=replace(doc.sequence, video_layers=layers),
    )
    return Step(new_doc, RecompileWithNewCatalog(op.to_digest, op.from_digest), (ref,))


# ----------------------------------------------------------------------------- dispatch


def apply_operation(
    doc: ProjectDocument, op: Operation, catalog: DescriptorCatalog, intent_scope: str
) -> Step | Rejected:
    """One concrete operation; ``RevertOperation`` is expanded by :func:`apply_batch`."""
    match op:
        case InsertOccurrence():
            return _insert_occurrence(doc, op, catalog)
        case RemoveOccurrence():
            return _remove_occurrence(doc, op)
        case TrimOccurrence():
            return _trim(doc, op)
        case MoveOccurrence():
            return _move(doc, op)
        case SetConstantSpeed():
            return _set_speed(doc, op, catalog)
        case RetimeOccurrence():
            return _retime(doc, op, catalog)
        case AddTransition():
            return _add_transition(doc, op, catalog)
        case RemoveTransition():
            return _remove_transition(doc, op)
        case SetTransitionSettings():
            return _set_transition_settings(doc, op, catalog)
        case SetAudioMix():
            return _set_audio_mix(doc, op)
        case AddTitle():
            return _add_title(doc, op)
        case RemoveTitle():
            return _remove_title(doc, op)
        case ShiftTitle():
            return _shift_title(doc, op)
        case SetCaptions():
            return _set_captions(doc, op)
        case BindSubjectEffect():
            return _bind_subject(doc, op, catalog, intent_scope)
        case BindEffect():
            return _bind_plain(doc, op.binding, catalog, ServiceType.FILTER)
        case AddLink():
            return _bind_plain(doc, op.binding, catalog, ServiceType.LINK)
        case UnbindEffect():
            return _unbind_effect(doc, op)
        case SetParameter() | SetKeyframes():
            return _set_parameter(doc, op, catalog)
        case UnsetParameter():
            return _unset_parameter(doc, op)
        case AddGeneratedSource():
            return _add_generated(doc, op, catalog)
        case RemoveGeneratedSource():
            return _remove_generated(doc, op)
        case AddLayer():
            return _add_layer(doc, op)
        case RemoveLayer():
            return _remove_layer(doc, op)
        case AddAudioTrack():
            return _add_track(doc, op)
        case RemoveAudioTrack():
            return _remove_track(doc, op)
        case SetOutputProfile():
            return _set_profile(doc, op, catalog)
        case RebindAsset():
            return _rebind_asset(doc, op)
        case RemoveAsset():
            return _remove_asset(doc, op)
        case RecordAnalysis():
            return _record_analysis(doc, op)
        case RemoveAnalysis():
            return _remove_analysis(doc, op)
        case RecompileWithNewCatalog():
            return _recompile(doc, op, catalog)
        case RevertOperation():
            return Rejected.make(
                RejectCode.VALIDATION, "RevertOperation must be expanded by apply_batch"
            )


def inverse(
    op: Operation, doc: ProjectDocument, catalog: DescriptorCatalog
) -> Operation | Rejected:
    """``inverse(op, doc) -> Operation`` of the contract: the operation that undoes ``op``
    when applied to the document ``op`` produced (computed, as at admission, from ``doc``)."""
    step = apply_operation(doc, op, catalog, "inverse")
    return step if isinstance(step, Rejected) else step.inverse


def check_preconditions(doc: ProjectDocument, batch: OperationBatch) -> Rejected | None:
    for pre in batch.preconditions:
        match pre:
            case Exists(ref, version):
                current = doc.object_version(ref)
                if current is None:
                    return _reject(RejectCode.PRECONDITION_FAILED, f"{ref} does not exist", ref)
                if current != version:
                    return _reject(
                        RejectCode.PRECONDITION_FAILED,
                        f"{ref} changed since the client read it (stale input)",
                        ref,
                    )
            case Absent(ref):
                if doc.object_version(ref) is not None:
                    return _reject(RejectCode.PRECONDITION_FAILED, f"{ref} already exists", ref)
    return None


def apply_operations(
    doc: ProjectDocument,
    operations: tuple[Operation, ...],
    catalog: DescriptorCatalog,
    intent_scope: str,
) -> BatchApplied | Rejected:
    """Apply concrete operations in order; the inverse list undoes them in reverse order."""
    working = doc
    applied: list[Operation] = []
    inverses: list[Operation] = []
    affected: dict[ObjectRef, None] = {}
    intents: list[IntentRequest] = []
    for op in operations:
        step = apply_operation(working, op, catalog, intent_scope)
        if isinstance(step, Rejected):
            return step
        working = step.document
        applied.append(op)
        inverses.insert(0, step.inverse)
        for ref in step.affected:
            affected[ref] = None
        intents.extend(step.intents)
    problems = validate_document(working)
    if problems:
        return rejection_for(problems)
    versions = tuple(_versioned(working, ref) for ref in affected)
    before = {
        a.artifact.sha256 for a in doc.analysis_refs if isinstance(a.artifact, EvidenceArtifact)
    }
    referenced = tuple(
        a.artifact.sha256
        for a in working.analysis_refs
        if isinstance(a.artifact, EvidenceArtifact) and a.artifact.sha256 not in before
    )
    return BatchApplied(
        working, tuple(applied), tuple(inverses), versions, tuple(intents), referenced
    )


def _versioned(doc: ProjectDocument, ref: ObjectRef) -> str:
    version = doc.object_version(ref)
    return f"{ref}#{version if version is not None else 'absent'}"


def apply_batch(
    doc: ProjectDocument, batch: OperationBatch, catalog: DescriptorCatalog, history: HistoryView
) -> BatchApplied | Rejected:
    """``apply_batch(doc, batch, catalog) -> ProjectDocument | Rejected`` of the contract,
    with the inverse, affected objects and intents the ledger records alongside."""
    from .undo import UndoConflict, expand_revert

    failed = check_preconditions(doc, batch)
    if failed is not None:
        return failed
    concrete: list[Operation] = []
    working = doc
    scope = batch.base_revision.hex[:16]
    for op in batch.operations:
        if isinstance(op, RevertOperation):
            plan = expand_revert(working, op, catalog, history, scope)
            if isinstance(plan, Rejected):
                return plan
            if isinstance(plan, UndoConflict):
                return plan.as_rejected()
            ops = plan.operations
        else:
            ops = (op,)
        partial = apply_operations(working, ops, catalog, scope)
        if isinstance(partial, Rejected):
            return partial
        working = partial.document
        concrete.extend(ops)
    return apply_operations(doc, tuple(concrete), catalog, scope)


# ----------------------------------------------------------------------------- derived states


@dataclass(frozen=True, slots=True)
class Ready:
    pass


@dataclass(frozen=True, slots=True)
class NoDependency:
    pass


@dataclass(frozen=True, slots=True)
class PendingCoverage:
    """Source intervals the effect's target samples without produced mask coverage."""

    missing: tuple[SourceSpan, ...]
    requested: tuple[SourceSpan, ...]


@dataclass(frozen=True, slots=True)
class UnavailableDependency:
    reason: str
    required_action: str


type DependencyState = Ready | NoDependency | PendingCoverage | UnavailableDependency


def effect_dependency(doc: ProjectDocument, effect: EffectBinding) -> DependencyState:
    if not isinstance(effect.mask, MaskRef):
        return NoDependency()
    track = doc.analysis(effect.mask.track_version_id)
    if track is None:
        return UnavailableDependency("mask track reference is missing", "rebind the effect")
    if isinstance(track.state, UnavailableAnalysis):
        return UnavailableDependency(track.state.reason, track.state.required_action)
    if not isinstance(effect.target, OccurrenceTarget):
        return UnavailableDependency("subject effects need an occurrence target", "rebind")
    found = doc.occurrence(effect.target.occurrence_id)
    if found is None:
        return UnavailableDependency("target occurrence is missing", "rebind the effect")
    missing = coverage_missing(found[0].placement, track.coverage, doc.profile.fps)
    if not missing and isinstance(track.state, Produced):
        return Ready()
    requested: tuple[SourceSpan, ...] = (
        (track.state.requested,) if isinstance(track.state, PendingAnalysis) else ()
    )
    return PendingCoverage(tuple(missing), requested)


@dataclass(frozen=True, slots=True)
class Eligible:
    pending: tuple[str, ...]
    """Effects whose dependencies are still pending (execution waits; nothing is guessed)."""


@dataclass(frozen=True, slots=True)
class Blocked:
    reasons: tuple[Problem, ...]


def execution_eligibility(
    doc: ProjectDocument,
    catalog: DescriptorCatalog,
    observed: Mapping[str, AssetAvailability] | None = None,
) -> Eligible | Blocked:
    """Whether this document may enter executable jobs against the installed catalog.

    ``observed`` carries the store's current availability per asset id (a ``Changed`` or
    ``Missing`` observation overrides what the document recorded at binding time).
    """
    reasons: list[Problem] = []
    current = observed or {}
    for asset in doc.assets:
        availability = current.get(asset.asset_id, asset.availability)
        if not isinstance(availability, Present):
            reasons.append(
                Problem(
                    RejectCode.ASSET_NOT_VERIFIED,
                    f"asset {asset.asset_id} is {type(availability).__name__}; only verified"
                    " present sources enter executable jobs",
                    (f"asset:{asset.asset_id}",),
                )
            )
    refs: list[tuple[str, ServiceRef]] = [(f"effect:{e.effect_id}", e.service) for e in doc.effects]
    refs += [(f"generated:{g.source_id}", g.service) for g in doc.generated]
    for layer in doc.sequence.video_layers:
        refs += [(f"transition:{t.transition_id}", t.kind) for t in layer.transitions]
    for obj, service in refs:
        if service.catalog_digest != catalog.digest:
            reasons.append(
                Problem(
                    RejectCode.CATALOG_MISMATCH,
                    f"{obj}: bound to catalog {service.catalog_digest.hex[:12]}, installed"
                    f" {catalog.digest.hex[:12]}",
                    (obj,),
                )
            )
        elif not isinstance(catalog.service(service.service_id), Callable):
            reasons.append(
                Problem(
                    RejectCode.UNKNOWN_DESCRIPTOR,
                    f"{obj}: service {service.service_id} is not callable",
                    (obj,),
                )
            )
    for occ in doc.all_occurrences():
        unsupported = _check_timing_support(
            occ, catalog, _ref(ObjectKind.OCCURRENCE, occ.occurrence_id)
        )
        if unsupported is not None:
            reasons.append(
                Problem(
                    unsupported.contract_reason.code,
                    unsupported.contract_reason.detail,
                    unsupported.contract_reason.objects,
                )
            )
    for effect in doc.effects:
        state = effect_dependency(doc, effect)
        if isinstance(state, UnavailableDependency):
            reasons.append(
                Problem(
                    RejectCode.VALIDATION,
                    f"effect:{effect.effect_id}: {state.reason}",
                    (f"effect:{effect.effect_id}",),
                )
            )
    if reasons:
        return Blocked(tuple(reasons))
    pending = tuple(
        e.effect_id for e in doc.effects if isinstance(effect_dependency(doc, e), PendingCoverage)
    )
    return Eligible(pending)
