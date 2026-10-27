"""Selective undo (contracts §6, invariant I7).

``RevertOperation(event_seq)`` applies the inverse stored with that event at the *current*
head as a new revision. Later independent operations are preserved; dependents are found
through the ``ObjectRef`` graph:

* an object the inverse restores that a later event changed (its current version differs
  from the version recorded after the reverted event) needs ``ForceRestore``;
* an effect or transition attached to an occurrence the inverse removes (the right half of
  a cut, for example) must be rebound or dropped - a unique same-source candidate whose
  source range overlaps the effect's coverage proves the rebinding (``UnbindEffect`` then
  ``Bind…`` on the candidate); anything ambiguous is an :class:`UndoConflict` with the exact
  choices, never a guess.

Coverage is never invented: a rebound mask keeps its produced coverage and the newly
exposed source intervals are reported as pending by ``apply.effect_dependency``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from aidashvideo.catalog.descriptors import DescriptorCatalog
from aidashvideo.ledger.canonical import parse_json
from aidashvideo.ledger.domain import EventMissing, HistoryView
from aidashvideo.ledger.ids import EventKind, EventSeq
from aidashvideo.ledger.results import RejectCode, Rejected

from .document import (
    AnalysisKind,
    ClipOccurrence,
    EffectBinding,
    MaskRef,
    ObjectKind,
    ObjectRef,
    OccurrenceTarget,
    PendingAnalysis,
    ProjectDocument,
)
from .operations import (
    AddLayer,
    AddTitle,
    AddTransition,
    BindEffect,
    BindSubjectEffect,
    DropDependent,
    ExistingTrack,
    ForceRestore,
    InsertOccurrence,
    MoveOccurrence,
    Operation,
    RebindAsset,
    RebindTo,
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
    TrimOccurrence,
    UnbindEffect,
    UndoChoice,
    UnsetParameter,
    operations_from_json,
)
from .timing import SourceSpan

_REVERTIBLE = frozenset({EventKind.EDIT, EventKind.UNDO, EventKind.REBIND, EventKind.EFFECT_FACT})


@dataclass(frozen=True, slots=True)
class UndoPlan:
    event_seq: EventSeq
    operations: tuple[Operation, ...]
    rebound: tuple[str, ...]
    """Effect ids whose rebinding was proven (same source bytes, unique candidate)."""


@dataclass(frozen=True, slots=True)
class UndoConflict:
    event_seq: EventSeq
    dependents: tuple[ObjectRef, ...]
    choices: tuple[UndoChoice, ...]
    detail: str

    def as_rejected(self) -> Rejected:
        choices = [c.to_json() for c in self.choices]
        return Rejected.make(
            RejectCode.UNDO_CONFLICT,
            f"{self.detail}; choices: {choices}"
            if choices
            else f"{self.detail}; no choice resolves it",
            tuple(str(d) for d in self.dependents),
        )


def _targets(op: Operation) -> tuple[ObjectRef, ...]:
    """Objects an inverse operation writes (for the "changed later" check)."""
    match op:
        case TrimOccurrence() | MoveOccurrence() | SetConstantSpeed() | RetimeOccurrence():
            return (ObjectRef(ObjectKind.OCCURRENCE, op.occurrence_id),)
        case RemoveOccurrence():
            return (ObjectRef(ObjectKind.OCCURRENCE, op.occurrence_id),)
        case InsertOccurrence():
            return ()
        case AddTransition() | RemoveTransition() | SetTransitionSettings():
            ident = (
                op.transition.transition_id if isinstance(op, AddTransition) else op.transition_id
            )
            return (
                () if isinstance(op, AddTransition) else (ObjectRef(ObjectKind.TRANSITION, ident),)
            )
        case SetAudioMix():
            return (ObjectRef(ObjectKind.TRACK, op.track_id),)
        case RemoveTitle() | ShiftTitle():
            return (ObjectRef(ObjectKind.TITLE, op.title_id),)
        case AddTitle():
            return ()
        case SetCaptions():
            return (ObjectRef(ObjectKind.CAPTIONS, "all"),)
        case UnbindEffect() | SetParameter() | SetKeyframes() | UnsetParameter():
            return (ObjectRef(ObjectKind.EFFECT, op.effect_id),)
        case BindEffect() | BindSubjectEffect():
            return ()
        case RemoveGeneratedSource():
            return (ObjectRef(ObjectKind.GENERATED, op.source_id),)
        case RemoveLayer():
            return (ObjectRef(ObjectKind.LAYER, op.layer_id),)
        case RemoveAudioTrack():
            return (ObjectRef(ObjectKind.TRACK, op.track_id),)
        case SetOutputProfile() | RecompileWithNewCatalog():
            return (ObjectRef(ObjectKind.PROFILE, "output"),)
        case RebindAsset():
            return (ObjectRef(ObjectKind.ASSET, op.asset.asset_id),)
        case RemoveAsset():
            return (ObjectRef(ObjectKind.ASSET, op.asset_id),)
        case RecordAnalysis():
            return (ObjectRef(ObjectKind.ANALYSIS, op.ref.ref_id),)
        case RemoveAnalysis():
            return (ObjectRef(ObjectKind.ANALYSIS, op.ref_id),)
        case AddLayer() | RevertOperation():
            return ()
        case _:
            return ()


def _recorded_versions(affected: tuple[str, ...]) -> dict[ObjectRef, str]:
    out: dict[ObjectRef, str] = {}
    for entry in affected:
        ref_text, _, version = entry.partition("#")
        if version:
            out[ObjectRef.parse(ref_text)] = version
    return out


def _coverage_of(
    doc: ProjectDocument, effect: EffectBinding, original: ClipOccurrence
) -> tuple[SourceSpan, ...]:
    if isinstance(effect.mask, MaskRef):
        track = doc.analysis(effect.mask.track_version_id)
        if track is not None and track.kind is AnalysisKind.MASK_TRACK:
            if track.coverage:
                return track.coverage
            if isinstance(track.state, PendingAnalysis):
                return (track.state.requested,)
    return (original.source,)


def expand_revert(
    doc: ProjectDocument,
    op: RevertOperation,
    catalog: DescriptorCatalog,
    history: HistoryView,
    scope: str,
) -> UndoPlan | UndoConflict | Rejected:
    from .apply import apply_operations

    event = history.event(op.event_seq)
    if isinstance(event, EventMissing):
        return Rejected.make(RejectCode.UNKNOWN_EVENT, f"event {op.event_seq.value} does not exist")
    if event.kind not in _REVERTIBLE:
        return Rejected.make(
            RejectCode.VALIDATION,
            f"event {op.event_seq.value} is a {event.kind.value} event and has no inverse",
        )
    inverse_ops = operations_from_json(parse_json(history.payload(event.inverse_sha256)))
    if not inverse_ops:
        return Rejected.make(
            RejectCode.VALIDATION, f"event {op.event_seq.value} recorded no inverse"
        )
    forced = {c.ref for c in op.choices if isinstance(c, ForceRestore)}
    dropped = {c.ref for c in op.choices if isinstance(c, DropDependent)}
    rebinds = {c.effect_id: c.occurrence_id for c in op.choices if isinstance(c, RebindTo)}
    recorded = _recorded_versions(event.affected_objects)

    # 1. objects the inverse rewrites must be as the reverted event left them
    conflicts: list[ObjectRef] = []
    choices: list[UndoChoice] = []
    for inverse in inverse_ops:
        for ref in _targets(inverse):
            if ref in forced or ref not in recorded:
                continue
            current = doc.object_version(ref)
            if current is None:
                return UndoConflict(
                    op.event_seq,
                    (ref,),
                    (),
                    f"{ref} was removed by a later operation; the revert cannot restore it",
                )
            if current != recorded[ref]:
                conflicts.append(ref)
                choices.append(ForceRestore(ref))
    if conflicts:
        return UndoConflict(
            op.event_seq,
            tuple(conflicts),
            tuple(choices),
            "objects changed by later operations would be overwritten",
        )

    # 2. dependents of occurrences the inverse removes
    removed = [inv.occurrence_id for inv in inverse_ops if isinstance(inv, RemoveOccurrence)]
    pre: list[Operation] = []
    pending_effects: list[tuple[EffectBinding, ClipOccurrence]] = []
    for occurrence_id in removed:
        found = doc.occurrence(occurrence_id)
        if found is None:
            continue
        original = found[0]
        for transition in doc.transitions_on(occurrence_id):
            ref = ObjectRef(ObjectKind.TRANSITION, transition.transition_id)
            if ref in dropped:
                layer = doc.transition(transition.transition_id)
                assert layer is not None
                pre.append(RemoveTransition(layer[1].layer_id, transition.transition_id))
            else:
                conflicts.append(ref)
                choices.append(DropDependent(ref))
        for effect in doc.effects_on(occurrence_id):
            pre.append(UnbindEffect(effect.effect_id))
            ref = ObjectRef(ObjectKind.EFFECT, effect.effect_id)
            if ref not in dropped:
                pending_effects.append((effect, original))
    if conflicts:
        return UndoConflict(
            op.event_seq,
            tuple(conflicts),
            tuple(choices),
            "transitions depend on an occurrence the revert removes",
        )

    # 3. simulate the inverse, then prove or refuse each rebinding on the result
    simulated = apply_operations(doc, (*pre, *inverse_ops), catalog, scope)
    if isinstance(simulated, Rejected):
        return simulated
    after = simulated.document
    post: list[Operation] = []
    rebound: list[str] = []
    for effect, original in pending_effects:
        ref = ObjectRef(ObjectKind.EFFECT, effect.effect_id)
        coverage = _coverage_of(doc, effect, original)
        if effect.effect_id in rebinds:
            chosen = after.occurrence(rebinds[effect.effect_id])
            if (
                chosen is None
                or chosen[0].asset_id != original.asset_id
                or chosen[0].stream_index != original.stream_index
            ):
                return Rejected.make(
                    RejectCode.UNDO_CONFLICT,
                    f"RebindTo names {rebinds[effect.effect_id]!r}, which is not an occurrence"
                    " of the same source",
                    (str(ref),),
                )
            candidates = [chosen[0]]
        else:
            candidates = [
                occ
                for occ in after.all_occurrences()
                if occ.asset_id == original.asset_id
                and occ.stream_index == original.stream_index
                and any(occ.source.overlaps(span) for span in coverage)
            ]
        if len(candidates) != 1:
            options: list[UndoChoice] = [
                RebindTo(effect.effect_id, c.occurrence_id) for c in candidates
            ]
            options.append(DropDependent(ref))
            detail = (
                f"effect {effect.effect_id} was bound to {original.occurrence_id}, which the"
                " revert removes; "
                + (
                    "no occurrence of the same source covers it"
                    if not candidates
                    else f"{len(candidates)} occurrences could take it"
                )
            )
            return UndoConflict(op.event_seq, (ref,), tuple(options), detail)
        candidate = candidates[0]
        same_service = [
            e for e in after.effects_on(candidate.occurrence_id) if e.service == effect.service
        ]
        if same_service:
            twin = same_service[0]
            if twin.params == effect.params and twin.mask == effect.mask:
                rebound.append(
                    effect.effect_id
                )  # identical binding already covers the candidate: merged
                continue
            options = [DropDependent(ref), RebindTo(effect.effect_id, candidate.occurrence_id)]
            return UndoConflict(
                op.event_seq,
                (ref, ObjectRef(ObjectKind.EFFECT, twin.effect_id)),
                tuple(options),
                f"effect {effect.effect_id} and {twin.effect_id} both bind"
                f" {effect.service.service_id} on {candidate.occurrence_id} with different"
                " settings",
            )
        retargeted = replace(effect, target=OccurrenceTarget(candidate.occurrence_id))
        if isinstance(retargeted.mask, MaskRef):
            post.append(BindSubjectEffect(retargeted, ExistingTrack()))
        else:
            post.append(BindEffect(retargeted))
        rebound.append(effect.effect_id)
    if post:
        check = apply_operations(after, tuple(post), catalog, scope)
        if isinstance(check, Rejected):
            return check
    return UndoPlan(op.event_seq, (*pre, *inverse_ops, *post), tuple(rebound))


def plan(
    doc: ProjectDocument,
    event_seq: EventSeq,
    catalog: DescriptorCatalog,
    history: HistoryView,
    choices: tuple[UndoChoice, ...] = (),
) -> UndoPlan | UndoConflict | Rejected:
    """``undo.plan(head, event_seq) -> OperationBatch | UndoConflict`` of the contract: the
    caller wraps the resulting ``RevertOperation(event_seq, choices)`` in a batch at the
    current head; redo is ``plan`` on the undo event itself."""
    return expand_revert(doc, RevertOperation(event_seq, choices), catalog, history, "plan")
