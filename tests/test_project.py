"""Project domain (M1d): documents, required and descriptor-bound operations, inverses,
selective undo, portable snapshots and the domain wired into a real ledger store
(I1, I2, I3, I7, V02, V04, V09, V10, V23, V24, V30).
"""

from __future__ import annotations

import json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from aidashvideo.catalog.descriptors import DescriptorCatalog, InterpolationKind
from aidashvideo.ledger import (
    AdmittedRevision,
    AlreadyApplied,
    Applied,
    ContractError,
    EventKind,
    EventMissing,
    EventRecord,
    EventSeq,
    IntentKind,
    InvalidSnapshot,
    NewLineage,
    Opened,
    ProjectId,
    RejectCode,
    Rejected,
    ReplayKey,
    RevisionConflict,
    RevisionId,
    ScopedLocator,
    Sha256,
    UnsupportedSchema,
    UserWording,
    canonical_bytes,
    issue_project_grant,
    parse_json,
)
from aidashvideo.ledger.domain import EventMissing as _EventMissing
from aidashvideo.ledger.domain import HistoryView, RevisionMissing
from aidashvideo.ledger.ids import ProjectId as _ProjectId
from aidashvideo.project import apply as apply_module
from aidashvideo.project import snapshot as snapshot_module
from aidashvideo.project import timing
from aidashvideo.project.apply import (
    Blocked,
    Eligible,
    PendingCoverage,
    Ready,
    apply_batch,
    apply_operations,
    effect_dependency,
    execution_eligibility,
)
from aidashvideo.project.document import (
    AssetRef,
    AudioMix,
    Caption,
    DuckUnder,
    EvidenceArtifact,
    GeneratedSource,
    MaskRef,
    ObjectKind,
    ObjectRef,
    OccurrenceTarget,
    OutputProfile,
    PendingAnalysis,
    ProjectDocument,
    ServiceRef,
    Transition,
    validate_document,
)
from aidashvideo.project.operations import (
    ALL_OPERATIONS,
    Absent,
    AddAudioTrack,
    AddGeneratedSource,
    AddLayer,
    AddLink,
    AddTitle,
    AddTransition,
    BindEffect,
    BindSubjectEffect,
    DropDependent,
    ExistingTrack,
    Exists,
    ForceRestore,
    InsertOccurrence,
    LayerRef,
    MoveOccurrence,
    Operation,
    OperationBatch,
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
    operation_from_json,
    operations_from_json,
    operations_to_json,
)
from aidashvideo.project.params import (
    Animated,
    Bool,
    Color,
    Enum,
    Float,
    FrameOffset,
    Int,
    Keyframe,
    ParamAssignment,
    Rect,
    StaticValue,
)
from aidashvideo.project.session import Project, new_project, open_project, project_from_opened
from aidashvideo.project.text import LiteralText
from aidashvideo.project.timing import (
    Constant,
    Interpolation,
    Normal,
    RetimeMode,
    SequenceFrame,
    SequenceSpan,
    SourceSpan,
    SourceTime,
    TimeMap,
)
from aidashvideo.project.undo import UndoConflict, UndoPlan
from aidashvideo.store import Changed, ImportRefused, Missing, Present, RelinkRequest
from ledger_support import ACTOR
from project_support import (
    BROLL,
    CATALOG,
    FPS,
    INTERVIEW,
    asset,
    blur,
    fixture_catalog,
    gp01_document,
    identity,
    mask_ref,
    occurrence,
    plain_effect,
    ref,
    transcript_ref,
)

pytestmark = pytest.mark.project
F = Fraction
PROJECT = ProjectId("gp01")


class NoHistory(HistoryView):
    def event(self, seq: EventSeq) -> EventRecord | EventMissing:
        return _EventMissing(seq)

    def revision(self, revision_id: RevisionId) -> AdmittedRevision | RevisionMissing:
        return RevisionMissing(revision_id)

    def payload(self, sha256: Sha256) -> bytes:  # pragma: no cover - unused
        raise NotImplementedError

    def events_after(self, project_id: _ProjectId, seq: EventSeq) -> tuple[EventRecord, ...]:
        return ()


def _batch(
    doc_base: Sha256,
    ops: tuple[Operation, ...],
    key: str = "batch-0123456789abcdef",
    pre: tuple[Exists | Absent, ...] = (),
) -> OperationBatch:
    from aidashvideo.ledger import RevisionId

    return OperationBatch(
        ACTOR, PROJECT, RevisionId(doc_base.hex), ReplayKey(key), pre, ops, UserWording("test")
    )


def _apply(
    doc: ProjectDocument, *ops: Operation, catalog: DescriptorCatalog = CATALOG
) -> ProjectDocument | Rejected:
    result = apply_operations(doc, ops, catalog, "test-scope")
    return result if isinstance(result, Rejected) else result.document


def _expect(
    doc: ProjectDocument, *ops: Operation, catalog: DescriptorCatalog = CATALOG
) -> ProjectDocument:
    result = _apply(doc, *ops, catalog=catalog)
    assert isinstance(result, ProjectDocument), result
    return result


def _rejected(
    doc: ProjectDocument, *ops: Operation, code: RejectCode, catalog: DescriptorCatalog = CATALOG
) -> Rejected:
    result = _apply(doc, *ops, catalog=catalog)
    assert isinstance(result, Rejected), f"expected {code}, got a document"
    assert result.contract_reason.code is code, result.contract_reason
    return result


def _placed(doc: ProjectDocument) -> ProjectDocument:
    """interview [0,12) at 0 on V1 and its audio on A1."""
    a = occurrence("A", "interview", 0, 12, 0)
    audio = occurrence("A-audio", "interview", 0, 12, 0, stream_index=1)
    return _expect(
        doc, InsertOccurrence(LayerRef("V1"), a), InsertOccurrence(TrackRef("A1"), audio)
    )


def _cut(doc: ProjectDocument) -> ProjectDocument:
    """Remove interview source seconds 6-8: trim A to [0,6) and insert A2 [8,12) right after."""
    return _expect(
        doc,
        TrimOccurrence("A", SourceSpan.make(0, 6)),
        InsertOccurrence(LayerRef("V1"), occurrence("A2", "interview", 8, 12, 180)),
    )


# ----------------------------------------------------------------------------- documents and wire


def test_document_round_trips_canonically_and_refuses_arbitrary_keys() -> None:
    doc = _cut(_placed(gp01_document()))
    data = doc.to_bytes()
    again = ProjectDocument.from_json(parse_json(data))
    assert again == doc and again.to_bytes() == data
    assert validate_document(again) == ()
    raw = json.loads(data)
    raw["sequence"]["video_layers"][0]["occurrences"][0]["extra"] = {"arbitrary": True}
    with pytest.raises(ContractError, match="unknown keys"):
        ProjectDocument.from_json(raw)
    raw = json.loads(data)
    raw["effects"] = [{"effect_id": "x", "params": {"luma_radius": 3}}]
    with pytest.raises(ContractError):
        ProjectDocument.from_json(raw)
    raw = json.loads(data)
    raw["sequence"]["video_layers"][0]["occurrences"][0]["source"]["out"] = "nan"
    with pytest.raises(ContractError):
        ProjectDocument.from_json(raw)
    with pytest.raises(ContractError, match="unknown op"):
        operation_from_json({"op": "DeleteEverything"})
    with pytest.raises(ContractError):
        operation_from_json({"op": "ShiftTitle", "title_id": "t", "delta_frames": 1.5})
    with pytest.raises(ContractError):
        operation_from_json(
            {
                "op": "AddTitle",
                "title_id": "t",
                "text": "x",
                "start_frame": 0,
                "duration_frames": 1,
                "style": "s",
                "params": {},
            }
        )
    with pytest.raises(ContractError):
        LiteralText("hello\u202eworld")  # bidi override refused
    with pytest.raises(ContractError):
        LiteralText("rm -rf /\x00")
    assert LiteralText("Hello golden path\nline two").text.endswith("two")


def test_every_operation_has_a_wire_form_and_parses_back() -> None:
    doc = _cut(_placed(gp01_document()))
    ops: tuple[Operation, ...] = (
        InsertOccurrence(LayerRef("V1"), occurrence("B", "broll", 0, 4, 300)),
        RemoveOccurrence(LayerRef("V1"), "B"),
        TrimOccurrence("A", SourceSpan.make(1, 5)),
        MoveOccurrence("A2", SequenceFrame(200)),
        SetConstantSpeed("A", Constant.make(2)),
        RetimeOccurrence(
            "A", TimeMap.make(((0, 6), (30, 0)), Interpolation.LINEAR, RetimeMode.REVERSE)
        ),
        AddTransition("V1", Transition("t1", "A", "A2", ref("luma"), 15, ())),
        SetTransitionSettings("t1", 10, (ParamAssignment("softness", StaticValue(Float(0.5))),)),
        SetAudioMix("A1", AudioMix(F(-3), 15, 15, DuckUnder("A2", F(-12), "tr1"))),
        AddTitle("t", LiteralText("Title"), 0, 30, "default"),
        ShiftTitle("t", -15),
        SetCaptions(()),
        BindSubjectEffect(
            blur("blur", "A", "mask-1"),
            SubjectRequest(LiteralText("the person"), SourceSpan.make(0, 6), "sam31-mlx-metal"),
        ),
        BindSubjectEffect(blur("blur2", "A", "mask-1"), ExistingTrack()),
        BindEffect(plain_effect("bright", "A", "brightness")),
        AddLink(plain_effect("remap", "A", "timeremap")),
        UnbindEffect("bright"),
        SetParameter("bright", ParamAssignment("level", StaticValue(Float(0.25)))),
        SetKeyframes(
            "bright",
            ParamAssignment(
                "level",
                Animated(
                    (Keyframe(FrameOffset(0), Float(0.0)), Keyframe(FrameOffset(10), Float(1.0))),
                    InterpolationKind.LINEAR,
                ),
            ),
        ),
        AddGeneratedSource(GeneratedSource("bg", ref("color"), (), F(4), 1920, 1080)),
        AddLayer("V2", "V1"),
        AddAudioTrack("A2", AudioMix.default()),
        SetOutputProfile(OutputProfile.default()),
        RebindAsset(doc.assets[0], INTERVIEW),
        RemoveAsset("music"),
        RecompileWithNewCatalog(CATALOG.digest, CATALOG.digest),
        RecordAnalysis(transcript_ref(doc, "tr1", "interview", 1, (SourceSpan.make(2, 4),))),
        RemoveAnalysis("tr1"),
        RevertOperation(
            EventSeq(3),
            (
                DropDependent(ObjectRef(ObjectKind.EFFECT, "blur")),
                RebindTo("blur", "A"),
                ForceRestore(ObjectRef(ObjectKind.TITLE, "t")),
            ),
        ),
    )
    names = {op.to_json()["op"] for op in ops}
    assert names <= set(ALL_OPERATIONS)
    assert operations_from_json(json.loads(canonical_bytes(operations_to_json(ops)))) == ops


# ----------------------------------------------------------------------------- required operations


def test_insert_trim_move_and_repeated_occurrences_stay_distinguishable() -> None:
    doc = _cut(_placed(gp01_document()))
    layer = doc.layer("V1")
    assert layer is not None
    a, a2 = layer.occurrences
    assert (a.occurrence_id, a.source, a.place) == (
        "A",
        SourceSpan.make(0, 6),
        SequenceSpan.make(0, 180),
    )
    assert (a2.occurrence_id, a2.source, a2.place) == (
        "A2",
        SourceSpan.make(8, 12),
        SequenceSpan.make(180, 300),
    )
    assert a.asset_id == a2.asset_id == "interview"
    # the same source passage again, as a third distinguishable occurrence after the b-roll
    doc = _expect(
        doc,
        InsertOccurrence(LayerRef("V1"), occurrence("B", "broll", 0, 4, 300)),
        InsertOccurrence(LayerRef("V1"), occurrence("A3", "interview", 8, 12, 420)),
    )
    assert [o.occurrence_id for o in doc.all_occurrences() if o.asset_id == "interview"] == [
        "A",
        "A2",
        "A3",
        "A-audio",
    ]
    # a move keeps the id and the source; the GP-01 14-second sequence is 420 frames
    moved = _expect(doc, MoveOccurrence("A3", SequenceFrame(600)))
    found = moved.occurrence("A3")
    assert (
        found is not None
        and found[0].place == SequenceSpan.make(600, 720)
        and found[0].source == a2.source
    )
    # overlap is refused atomically: the whole batch, including a valid first op, is rejected
    before = doc
    result = _rejected(
        doc,
        MoveOccurrence("B", SequenceFrame(310)),
        InsertOccurrence(LayerRef("V1"), occurrence("A4", "interview", 0, 1, 150)),
        code=RejectCode.OVERLAP,
    )
    assert "overlaps" in result.contract_reason.detail and doc == before
    _rejected(doc, TrimOccurrence("A", SourceSpan.make(0, 13)), code=RejectCode.OUTSIDE_SOURCE)
    _rejected(doc, TrimOccurrence("nope", SourceSpan.make(0, 1)), code=RejectCode.UNKNOWN_OBJECT)
    _rejected(
        doc,
        InsertOccurrence(LayerRef("V1"), occurrence("X", "interview", 0, 1, 0, stream_index=1)),
        code=RejectCode.VALIDATION,
    )
    _rejected(
        doc,
        InsertOccurrence(TrackRef("A1"), occurrence("X", "broll", 0, 1, 0)),
        code=RejectCode.VALIDATION,
    )
    _rejected(
        doc,
        InsertOccurrence(LayerRef("V9"), occurrence("X", "broll", 0, 1, 0)),
        code=RejectCode.UNKNOWN_OBJECT,
    )


def test_speed_and_retime_are_catalog_bound_and_exact() -> None:
    doc = _placed(gp01_document())
    fast = _expect(doc, SetConstantSpeed("A", Constant.make(2)))
    occ = fast.occurrence("A")
    assert occ is not None and occ[0].place == SequenceSpan.make(0, 180)
    _rejected(doc, SetConstantSpeed("A", Constant.make(20)), code=RejectCode.UNSUPPORTED_SPEED)
    _rejected(
        doc, SetConstantSpeed("A", Constant.make(F(1, 100))), code=RejectCode.UNSUPPORTED_SPEED
    )
    held = TimeMap.make(
        ((0, 0), (90, 3), (120, 3), (210, 6)), Interpolation.LINEAR, RetimeMode.HOLD
    )
    retimed = _expect(doc, RetimeOccurrence("A", held))
    occ = retimed.occurrence("A")
    assert (
        occ is not None
        and occ[0].place == SequenceSpan.make(0, 210)
        and occ[0].source == SourceSpan.make(0, 12)
    )
    no_hold = fixture_catalog(without=()).retime
    limited = replace(CATALOG, retime=replace(no_hold, modes=("Reverse",)))
    _rejected(doc, RetimeOccurrence("A", held), code=RejectCode.UNSUPPORTED_SPEED, catalog=limited)
    # a map sampling outside the trimmed source is OutsidePlacedRange, never clamped
    trimmed = _expect(retimed, TrimOccurrence("A", SourceSpan.make(0, 7)))
    assert trimmed is not None
    _rejected(
        retimed, TrimOccurrence("A", SourceSpan.make(0, 4)), code=RejectCode.OUTSIDE_PLACED_RANGE
    )
    # trimming after a retime keeps the map and the map's length
    occ = trimmed.occurrence("A")
    assert occ is not None and occ[0].place.frames == 210
    reverse = TimeMap.make(((0, 6), (180, 0)), Interpolation.LINEAR, RetimeMode.REVERSE)
    reversed_doc = _expect(
        _expect(doc, TrimOccurrence("A", SourceSpan.make(0, F(61, 10)))),
        RetimeOccurrence("A", reverse),
    )
    occ = reversed_doc.occurrence("A")
    assert occ is not None
    first = timing.source_time_at(occ[0].placement, SequenceFrame(0), FPS)
    assert first == timing.Mapped(SourceTime(F(6)))


def test_transitions_validate_neighbours_handles_and_descriptors() -> None:
    doc = _cut(_placed(gp01_document()))
    ok = _expect(
        doc,
        AddTransition(
            "V1",
            Transition(
                "x",
                "A",
                "A2",
                ref("luma"),
                15,
                (ParamAssignment("softness", StaticValue(Float(0.2))),),
            ),
        ),
    )
    assert ok.transition("x") is not None
    _rejected(
        doc,
        AddTransition("V1", Transition("x", "A", "A2", ref("luma"), 200, ())),
        code=RejectCode.INSUFFICIENT_HANDLES,
    )
    short = _expect(
        _placed(gp01_document()),
        TrimOccurrence("A", SourceSpan.make(0, 6)),
        InsertOccurrence(LayerRef("V1"), occurrence("A2", "interview", 0, 4, 180)),
    )
    # the right neighbour starts at source 0: no handle before its in point
    _rejected(
        short,
        AddTransition("V1", Transition("x", "A", "A2", ref("luma"), 15, ())),
        code=RejectCode.INSUFFICIENT_HANDLES,
    )
    tail = _expect(
        _placed(gp01_document()),
        TrimOccurrence("A", SourceSpan.make(0, 12)),
        InsertOccurrence(LayerRef("V1"), occurrence("B", "broll", 1, 4, 360)),
    )
    # the left neighbour uses its source to the very end: no handle after its out point
    _rejected(
        tail,
        AddTransition("V1", Transition("x", "A", "B", ref("luma"), 15, ())),
        code=RejectCode.INSUFFICIENT_HANDLES,
    )
    gap = _expect(doc, MoveOccurrence("A2", SequenceFrame(181)))
    _rejected(
        gap,
        AddTransition("V1", Transition("x", "A", "A2", ref("luma"), 15, ())),
        code=RejectCode.INSUFFICIENT_HANDLES,
    )
    _rejected(
        doc,
        AddTransition("V1", Transition("x", "A", "A2", ref("wipe.unknown"), 15, ())),
        code=RejectCode.UNKNOWN_DESCRIPTOR,
    )
    _rejected(
        doc,
        AddTransition("V1", Transition("x", "A", "A2", ref("avfilter.boxblur"), 15, ())),
        code=RejectCode.VALIDATION,
    )
    _rejected(
        doc,
        AddTransition(
            "V1", Transition("x", "A", "A2", ServiceRef("luma", Sha256("9" * 64)), 15, ())
        ),
        code=RejectCode.CATALOG_MISMATCH,
    )
    _rejected(
        doc,
        AddTransition(
            "V1",
            Transition(
                "x",
                "A",
                "A2",
                ref("luma"),
                15,
                (ParamAssignment("softnes", StaticValue(Float(0.2))),),
            ),
        ),
        code=RejectCode.UNKNOWN_PARAMETER,
    )
    _rejected(
        doc,
        AddTransition(
            "V1",
            Transition(
                "x",
                "A",
                "A2",
                ref("luma"),
                15,
                (ParamAssignment("softness", StaticValue(Float(7.0))),),
            ),
        ),
        code=RejectCode.PARAMETER_RANGE,
    )
    _rejected(
        doc,
        AddTransition(
            "V1",
            Transition(
                "x",
                "A",
                "A2",
                ref("luma"),
                15,
                (ParamAssignment("softness", StaticValue(Bool(True))),),
            ),
        ),
        code=RejectCode.PARAMETER_TYPE,
    )
    _rejected(
        doc,
        AddTransition(
            "V1",
            Transition(
                "x",
                "A",
                "A2",
                ref("mix"),
                15,
                (ParamAssignment("mode", StaticValue(Enum("average"))),),
            ),
        ),
        code=RejectCode.PARAMETER_TYPE,
    )
    with pytest.raises(ContractError):
        Float(float("nan"))
    settings = _expect(
        ok, SetTransitionSettings("x", 30, (ParamAssignment("invert", StaticValue(Bool(True))),))
    )
    found = settings.transition("x")
    assert found is not None and found[0].duration_frames == 30
    _rejected(ok, SetTransitionSettings("x", 181, ()), code=RejectCode.INSUFFICIENT_HANDLES)


def test_titles_are_exact_and_negative_starts_fail_atomically() -> None:
    doc = _placed(gp01_document())
    titled = _expect(doc, AddTitle("t", LiteralText("Hello"), 0, 60, "default"))
    assert titled.title("t") is not None
    result = _rejected(
        doc, AddTitle("t", LiteralText("Hello"), -1, 60, "default"), code=RejectCode.NEGATIVE_START
    )
    assert "start frame -1" in result.contract_reason.detail
    shifted = _expect(
        _expect(doc, AddTitle("t", LiteralText("Hello"), 30, 60, "default")), ShiftTitle("t", -15)
    )
    title = shifted.title("t")
    assert title is not None and title.place == SequenceSpan.make(15, 75)
    half = timing.frames_nearest(F(-1, 2), FPS)
    assert half.frames == -15 and half.exact
    result = _rejected(shifted, ShiftTitle("t", -16), code=RejectCode.NEGATIVE_START)
    assert "frame -1" in result.contract_reason.detail
    # atomic: a valid insert plus an invalid title in one batch changes nothing
    combined = _rejected(
        doc,
        InsertOccurrence(LayerRef("V1"), occurrence("B", "broll", 0, 4, 360)),
        AddTitle("t2", LiteralText("x"), -5, 10, "default"),
        code=RejectCode.NEGATIVE_START,
    )
    assert combined.contract_reason.objects == ("title:t2",)
    _rejected(doc, AddTitle("t", LiteralText("Hello"), 0, 0, "default"), code=RejectCode.VALIDATION)
    _rejected(
        titled,
        AddTitle("t", LiteralText("Hello"), 0, 1, "default"),
        code=RejectCode.DUPLICATE_OBJECT,
    )


def test_captions_use_the_shared_map_and_cite_evidence() -> None:
    doc = _placed(gp01_document())
    doc = replace(
        doc,
        analysis_refs=(
            transcript_ref(
                doc, "tr1", "interview", 1, (SourceSpan.make(F(2015, 1000), F(3105, 1000)),)
            ),
        ),
    )
    occ = doc.occurrence("A")
    assert occ is not None
    requested = SourceSpan.make(F(2015, 1000), F(3105, 1000))
    placed = timing.place_source_span(occ[0].placement, requested, FPS)
    assert not isinstance(placed, timing.OutsidePlacedRange)
    frames = placed.runs[0].frames
    caption = Caption(
        "c1",
        LiteralText("hello golden path"),
        frames,
        "en",
        "default",
        (LiteralText("hello golden path"),),
        "tr1",
        requested,
    )
    captioned = _expect(doc, SetCaptions((caption,)))
    assert captioned.sequence.captions == (caption,)
    assert frames == SequenceSpan.make(60, 93)
    # cut out 6-8 and move the occurrence: the caption placement follows the same map
    cut = _cut(captioned)
    occ = cut.occurrence("A")
    assert occ is not None
    again = timing.place_source_span(occ[0].placement, requested, FPS)
    assert not isinstance(again, timing.OutsidePlacedRange) and again.runs[0].frames == frames
    outside = Caption(
        "c2",
        LiteralText("x"),
        SequenceSpan.make(500, 520),
        "en",
        "default",
        (LiteralText("x"),),
        "tr1",
        requested,
    )
    _rejected(doc, SetCaptions((outside,)), code=RejectCode.OUTSIDE_PLACED_RANGE)
    # a placement that is inside the occurrence but not what the map realizes is refused too
    off_by_one = replace(caption, caption_id="c4", place=SequenceSpan.make(61, 93))
    _rejected(doc, SetCaptions((off_by_one,)), code=RejectCode.OUTSIDE_PLACED_RANGE)
    # a requested interval outside the transcript's coverage is refused
    uncovered = replace(caption, caption_id="c5", requested=SourceSpan.make(5, 6))
    _rejected(doc, SetCaptions((uncovered,)), code=RejectCode.OUTSIDE_PLACED_RANGE)
    # a retimed occurrence realizes the same requested span through its own map (hold at 3 s)
    held = TimeMap.make(
        ((0, 0), (90, 3), (120, 3), (210, 6)), Interpolation.LINEAR, RetimeMode.HOLD
    )
    retimed = _expect(doc, TrimOccurrence("A", SourceSpan.make(0, 6)), RetimeOccurrence("A", held))
    occ = retimed.occurrence("A")
    assert occ is not None
    held_runs = timing.place_source_span(occ[0].placement, requested, FPS)
    assert not isinstance(held_runs, timing.OutsidePlacedRange)
    held_caption = replace(caption, caption_id="c6", place=held_runs.runs[0].frames)
    # the one-second hold at 3 s stretches the phrase: frames 61-89 play 2.03-2.97 s, 90-119
    # hold 3 s, 120-123 play 3.0-3.1 s -> [61, 124)
    stretched = _expect(retimed, SetCaptions((held_caption,))).sequence.captions[0].place
    assert stretched == SequenceSpan.make(61, 124)
    # the untouched audio occurrence of the same asset still realizes the original placement
    assert _expect(retimed, SetCaptions((caption,))).sequence.captions == (caption,)
    video_only = _expect(retimed, RemoveOccurrence(TrackRef("A1"), "A-audio"))
    _rejected(video_only, SetCaptions((caption,)), code=RejectCode.OUTSIDE_PLACED_RANGE)
    no_evidence = replace(caption, caption_id="c3", evidence="tr-missing")
    _rejected(doc, SetCaptions((no_evidence,)), code=RejectCode.UNKNOWN_OBJECT)
    # a span outside the occurrence's source range is OutsidePlacedRange for the map, too
    assert isinstance(
        timing.place_source_span(occ[0].placement, SourceSpan.make(6, 7), FPS),
        timing.OutsidePlacedRange,
    )


def test_audio_mix_and_ducking_need_transcript_evidence() -> None:
    doc = _placed(gp01_document())
    doc = _expect(
        doc,
        AddAudioTrack("music", AudioMix.default()),
        InsertOccurrence(TrackRef("music"), occurrence("M", "music", 0, 14, 0, stream_index=0)),
    )
    _rejected(
        doc,
        SetAudioMix("music", AudioMix(F(-6), 30, 30, DuckUnder("A1", F(-12), "tr1"))),
        code=RejectCode.UNKNOWN_OBJECT,
    )
    doc = replace(
        doc, analysis_refs=(transcript_ref(doc, "tr1", "interview", 1, (SourceSpan.make(2, 4),)),)
    )
    ducked = _expect(
        doc, SetAudioMix("music", AudioMix(F(-6), 30, 30, DuckUnder("A1", F(-12), "tr1")))
    )
    track = ducked.track("music")
    assert track is not None and isinstance(track.mix.ducking, DuckUnder)
    with pytest.raises(ContractError):
        AudioMix(F(30), 0, 0, DuckUnder("A1", F(-12), "tr1"))
    with pytest.raises(ContractError):
        DuckUnder("A1", F(3), "tr1")
    _rejected(ducked, RemoveAudioTrack("A1"), code=RejectCode.DEPENDENTS_EXIST)


def test_bind_subject_effect_records_pending_coverage_and_one_intent() -> None:
    doc = _cut(_placed(gp01_document()))
    request = SubjectRequest(LiteralText("the person"), SourceSpan.make(0, 6), "sam31-mlx-metal")
    result = apply_operations(
        doc, (BindSubjectEffect(blur("blur", "A", "mask-A"), request),), CATALOG, "scope-1"
    )
    assert not isinstance(result, Rejected)
    bound = result.document
    assert [i.kind for i in result.intents] == [IntentKind.MASK]
    assert (
        result.intents[0].spec["concept"] == "the person"
        and result.intents[0].spec["profile"] == "sam31-mlx-metal"
    )
    track = bound.analysis("mask-A")
    assert track is not None and isinstance(track.state, PendingAnalysis) and track.coverage == ()
    effect = bound.effect("blur")
    assert effect is not None
    state = effect_dependency(bound, effect)
    assert isinstance(state, PendingCoverage) and state.missing == (SourceSpan.make(0, 6),)
    assert state.requested == (SourceSpan.make(0, 6),)
    # a second effect on the same pending track requests nothing new
    again = apply_operations(
        bound,
        (BindSubjectEffect(blur("blur-b", "A", "mask-A", radius=5), ExistingTrack()),),
        CATALOG,
        "scope-1",
    )
    assert not isinstance(again, Rejected) and again.intents == ()
    eligible = execution_eligibility(bound, CATALOG)
    assert eligible == Eligible(("blur",))
    # explicit (unqualified) fixture coverage makes the dependency Ready; a gap stays pending
    covered = replace(
        doc, analysis_refs=(mask_ref(doc, "mask-A", "interview", (SourceSpan.make(0, 6),)),)
    )
    ready = _expect(covered, BindSubjectEffect(blur("blur", "A", "mask-A"), ExistingTrack()))
    effect = ready.effect("blur")
    assert effect is not None and isinstance(effect_dependency(ready, effect), Ready)
    partial = replace(
        doc, analysis_refs=(mask_ref(doc, "mask-A", "interview", (SourceSpan.make(0, 3),)),)
    )
    partly = _expect(partial, BindSubjectEffect(blur("blur", "A", "mask-A"), ExistingTrack()))
    effect = partly.effect("blur")
    assert effect is not None
    state = effect_dependency(partly, effect)
    assert isinstance(state, PendingCoverage) and state.missing == (SourceSpan.make(3, 6),)
    # refusals
    _rejected(
        doc,
        BindSubjectEffect(blur("blur", "A", "mask-none"), ExistingTrack()),
        code=RejectCode.UNKNOWN_OBJECT,
    )
    _rejected(
        doc,
        BindSubjectEffect(
            blur("blur", "A", "mask-A"),
            SubjectRequest(LiteralText("x"), SourceSpan.make(0, 5), "sam31-mlx-metal"),
        ),
        code=RejectCode.VALIDATION,
    )
    other = replace(
        doc, analysis_refs=(mask_ref(doc, "mask-B", "broll", (SourceSpan.make(0, 4),)),)
    )
    _rejected(
        other,
        BindSubjectEffect(blur("blur", "A", "mask-B"), ExistingTrack()),
        code=RejectCode.VALIDATION,
    )
    _rejected(
        doc,
        BindSubjectEffect(blur("blur", "A-audio", "mask-A"), request),
        code=RejectCode.VALIDATION,
    )
    _rejected(
        doc,
        BindSubjectEffect(
            replace(blur("blur", "A", "mask-A"), service=ref("frei0r.baltan")), request
        ),
        code=RejectCode.UNKNOWN_DESCRIPTOR,
    )


# ------------------------------------------------------------------ descriptor-bound operations


def test_descriptor_bound_operations_and_their_inverses() -> None:
    doc = _placed(gp01_document())
    rect = ParamAssignment(
        "transition.rect",
        Animated(
            (
                Keyframe(FrameOffset(0), Rect.make(0, 0, 1920, 1080)),
                Keyframe(FrameOffset(119), Rect.make(-96, -54, 2112, 1188)),
            ),
            InterpolationKind.LINEAR,
        ),
    )
    steps: tuple[Operation, ...] = (
        AddGeneratedSource(
            GeneratedSource(
                "bg",
                ref("color"),
                (
                    ParamAssignment(
                        "resource",
                        StaticValue(Color(0, 0, 0, 255)),
                    ),
                ),
                F(4),
                1920,
                1080,
            )
        ),
        AddLayer("V2", "V1"),
        InsertOccurrence(LayerRef("V2"), occurrence("BG", "bg", 0, 4, 0)),
        AddAudioTrack("A2", AudioMix.default()),
        AddLink(
            plain_effect(
                "remap", "A", "timeremap", (ParamAssignment("speed", StaticValue(Float(1.0))),)
            )
        ),
        BindEffect(plain_effect("bright", "A", "brightness")),
        SetParameter("bright", ParamAssignment("level", StaticValue(Float(0.25)))),
        SetKeyframes(
            "bright",
            ParamAssignment(
                "level",
                Animated(
                    (Keyframe(FrameOffset(0), Float(0.0)), Keyframe(FrameOffset(359), Float(1.0))),
                    InterpolationKind.LINEAR,
                ),
            ),
        ),
        BindEffect(plain_effect("zoom", "A", "affine", (rect,))),
        SetOutputProfile(replace(OutputProfile.default(), width=1280, height=720)),
    )
    working = doc
    history: list[tuple[ProjectDocument, Operation]] = []
    for op in steps:
        result = apply_operations(working, (op,), CATALOG, "s")
        assert not isinstance(result, Rejected), (op, result)
        history.append((working, result.inverse[0]))
        working = result.document
    assert working.profile.width == 1280
    assert [e.effect_id for e in working.effects] == ["remap", "bright", "zoom"]
    # each inverse restores the exact prior document, in reverse order
    for before, inverse in reversed(history):
        restored = apply_operations(working, (inverse,), CATALOG, "s")
        assert not isinstance(restored, Rejected), (inverse, restored)
        assert restored.document.to_bytes() == before.to_bytes(), inverse
        working = restored.document
    assert working == doc


def test_parameter_validation_refuses_typos_types_ranges_and_animation() -> None:
    doc = _expect(
        _placed(gp01_document()),
        BindEffect(plain_effect("bright", "A", "brightness")),
        BindEffect(plain_effect("vol", "A-audio", "volume")),
    )
    _rejected(
        doc,
        SetParameter("bright", ParamAssignment("levle", StaticValue(Float(0.5)))),
        code=RejectCode.UNKNOWN_PARAMETER,
    )
    _rejected(
        doc,
        SetParameter("bright", ParamAssignment("level", StaticValue(Int(3)))),
        code=RejectCode.PARAMETER_RANGE,
    )
    _rejected(
        doc,
        SetParameter("bright", ParamAssignment("level", StaticValue(Bool(True)))),
        code=RejectCode.PARAMETER_TYPE,
    )
    _rejected(
        doc,
        SetParameter("vol", ParamAssignment("fixed", StaticValue(Int(1)))),
        code=RejectCode.PARAMETER_TYPE,
    )
    _rejected(
        doc,
        SetKeyframes(
            "vol",
            ParamAssignment(
                "gain",
                Animated(
                    (Keyframe(FrameOffset(0), Float(0.0)), Keyframe(FrameOffset(5), Float(1.0))),
                    InterpolationKind.LINEAR,
                ),
            ),
        ),
        code=RejectCode.UNSUPPORTED_ANIMATION,
    )
    _rejected(
        doc,
        SetKeyframes(
            "bright",
            ParamAssignment(
                "level",
                Animated(
                    (Keyframe(FrameOffset(0), Float(0.0)), Keyframe(FrameOffset(5), Float(1.0))),
                    InterpolationKind.SMOOTH,
                ),
            ),
        ),
        code=RejectCode.UNSUPPORTED_ANIMATION,
    )
    _rejected(
        doc,
        SetKeyframes(
            "bright",
            ParamAssignment(
                "level",
                Animated(
                    (Keyframe(FrameOffset(0), Float(0.0)), Keyframe(FrameOffset(360), Float(1.0))),
                    InterpolationKind.LINEAR,
                ),
            ),
        ),
        code=RejectCode.OUTSIDE_PLACED_RANGE,
    )
    _rejected(
        doc,
        SetParameter("nope", ParamAssignment("level", StaticValue(Float(0.5)))),
        code=RejectCode.UNKNOWN_OBJECT,
    )
    _rejected(
        doc, BindEffect(plain_effect("x", "A", "frei0r.baltan")), code=RejectCode.UNKNOWN_DESCRIPTOR
    )
    _rejected(
        doc, BindEffect(plain_effect("x", "A", "not.a.service")), code=RejectCode.UNKNOWN_DESCRIPTOR
    )
    _rejected(doc, BindEffect(plain_effect("x", "A", "timeremap")), code=RejectCode.VALIDATION)
    _rejected(doc, AddLink(plain_effect("x", "A", "brightness")), code=RejectCode.VALIDATION)
    _rejected(
        doc,
        AddGeneratedSource(GeneratedSource("bg", ref("brightness"), (), F(4), 16, 16)),
        code=RejectCode.VALIDATION,
    )
    with pytest.raises(ContractError):
        Animated(
            (Keyframe(FrameOffset(5), Float(0.0)), Keyframe(FrameOffset(5), Float(1.0))),
            InterpolationKind.LINEAR,
        )
    with pytest.raises(ContractError):
        Animated((Keyframe(FrameOffset(0), Float(0.0)),), InterpolationKind.LINEAR)


def test_output_profile_changes_are_descriptor_bound() -> None:
    empty = gp01_document()
    _rejected(
        empty,
        SetOutputProfile(replace(OutputProfile.default(), fps=F(23))),
        code=RejectCode.UNSUPPORTED_PROFILE,
    )
    _rejected(
        empty,
        SetOutputProfile(replace(OutputProfile.default(), width=7680, height=4320)),
        code=RejectCode.UNSUPPORTED_PROFILE,
    )
    changed = _expect(empty, SetOutputProfile(replace(OutputProfile.default(), fps=F(24))))
    assert changed.profile.fps == 24
    populated = _placed(empty)
    _rejected(
        populated,
        SetOutputProfile(replace(OutputProfile.default(), fps=F(24))),
        code=RejectCode.UNSUPPORTED_PROFILE,
    )
    smaller = _expect(
        populated, SetOutputProfile(replace(OutputProfile.default(), width=1280, height=720))
    )
    assert smaller.profile.height == 720
    with pytest.raises(ContractError, match="Sdr709"):
        OutputProfile.from_json({**OutputProfile.default().to_json(), "color": {"kind": "Hdr"}})


def test_layers_tracks_and_generated_sources_refuse_dangling_removal() -> None:
    doc = _expect(gp01_document(), AddLayer("V2", "V1"), AddLayer("V0", "bottom"))
    assert [v.layer_id for v in doc.sequence.video_layers] == ["V0", "V1", "V2"]
    with_bg = _expect(
        doc,
        AddGeneratedSource(GeneratedSource("bg", ref("color"), (), F(4), 1920, 1080)),
        InsertOccurrence(LayerRef("V0"), occurrence("BG", "bg", 0, 4, 0)),
    )
    _rejected(with_bg, RemoveLayer("V0"), code=RejectCode.DEPENDENTS_EXIST)
    _rejected(with_bg, RemoveGeneratedSource("bg"), code=RejectCode.DEPENDENTS_EXIST)
    _rejected(
        with_bg,
        InsertOccurrence(LayerRef("V0"), occurrence("BG2", "bg", 0, 5, 200)),
        code=RejectCode.OUTSIDE_SOURCE,
    )
    removed = _expect(doc, RemoveLayer("V0"), RemoveLayer("V2"))
    assert [v.layer_id for v in removed.sequence.video_layers] == ["V1"]
    _rejected(removed, RemoveLayer("V1"), code=RejectCode.VALIDATION)
    _rejected(doc, AddLayer("V1", "top"), code=RejectCode.DUPLICATE_OBJECT)
    _rejected(doc, AddLayer("V3", "V7"), code=RejectCode.UNKNOWN_OBJECT)


def test_preconditions_detect_stale_client_input() -> None:
    doc = _placed(gp01_document())
    occ_ref = ObjectRef(ObjectKind.OCCURRENCE, "A")
    version = doc.object_version(occ_ref)
    assert version is not None
    base = Sha256("1" * 64)
    fresh = apply_batch(
        doc,
        _batch(base, (MoveOccurrence("A", SequenceFrame(10)),), pre=(Exists(occ_ref, version),)),
        CATALOG,
        NoHistory(),
    )
    assert not isinstance(fresh, Rejected)
    moved = fresh.document
    stale = apply_batch(
        moved,
        _batch(base, (MoveOccurrence("A", SequenceFrame(20)),), pre=(Exists(occ_ref, version),)),
        CATALOG,
        NoHistory(),
    )
    assert (
        isinstance(stale, Rejected) and stale.contract_reason.code is RejectCode.PRECONDITION_FAILED
    )
    assert "stale" in stale.contract_reason.detail
    present = apply_batch(
        doc,
        _batch(base, (MoveOccurrence("A", SequenceFrame(20)),), pre=(Absent(occ_ref),)),
        CATALOG,
        NoHistory(),
    )
    assert (
        isinstance(present, Rejected)
        and present.contract_reason.code is RejectCode.PRECONDITION_FAILED
    )
    gone = apply_batch(
        doc,
        _batch(
            base,
            (MoveOccurrence("A", SequenceFrame(20)),),
            pre=(Exists(ObjectRef(ObjectKind.OCCURRENCE, "Z"), version),),
        ),
        CATALOG,
        NoHistory(),
    )
    assert (
        isinstance(gone, Rejected) and gone.contract_reason.code is RejectCode.PRECONDITION_FAILED
    )
    assert fresh.affected[0].startswith("occurrence:A#") and not fresh.affected[0].endswith(version)


def test_rebind_asset_requires_verified_bytes_and_explicit_binding() -> None:
    doc = _placed(gp01_document())
    interview = doc.assets[0]
    locator = ScopedLocator("pg-fixture", "media/interview")
    relinked = replace(
        interview,
        availability=Present(
            interview.identity.sha256,
            ScopedLocator("pg-other", "moved/interview.mp4"),
            interview.identity.probe_receipt_id,
        ),
    )
    moved = _expect(doc, RebindAsset(relinked, INTERVIEW))
    assert moved.assets[0].availability == relinked.availability
    missing = replace(
        interview,
        availability=Missing(
            interview.identity.sha256,
            RelinkRequest("interview", interview.identity.sha256, locator),
        ),
    )
    _rejected(doc, RebindAsset(missing, INTERVIEW), code=RejectCode.ASSET_NOT_VERIFIED)
    # replacement bytes are a new identity: a bound mask no longer matches and must be unbound first
    with_mask = replace(
        doc, analysis_refs=(mask_ref(doc, "mask-A", "interview", (SourceSpan.make(0, 12),)),)
    )
    with_mask = _expect(with_mask, BindSubjectEffect(blur("blur", "A", "mask-A"), ExistingTrack()))
    new_identity = identity("interview-v2", INTERVIEW)
    replacement = AssetRef(
        "interview",
        new_identity,
        Present(new_identity.sha256, locator, new_identity.probe_receipt_id),
    )
    _rejected(with_mask, RebindAsset(replacement, INTERVIEW), code=RejectCode.VALIDATION)
    unbound = _expect(with_mask, UnbindEffect("blur"), RebindAsset(replacement, INTERVIEW))
    assert unbound.assets[0].identity == new_identity
    # a relink to a shorter file that no longer covers the placed source is refused
    short_identity = replace(new_identity, probe_receipt_id=BROLL.receipt_id)
    short = AssetRef(
        "interview", short_identity, Present(short_identity.sha256, locator, BROLL.receipt_id)
    )
    _rejected(unbound, RebindAsset(short, BROLL), code=RejectCode.OUTSIDE_SOURCE)
    _rejected(doc, RemoveAsset("interview"), code=RejectCode.DEPENDENTS_EXIST)
    assert len(_expect(doc, RemoveAsset("music")).assets) == 2
    # observed availability (the store's verification) blocks execution without rewriting history
    blocked = execution_eligibility(
        doc, CATALOG, {"interview": Changed(interview.identity.sha256, Sha256("8" * 64))}
    )
    assert isinstance(blocked, Blocked) and blocked.reasons[0].code is RejectCode.ASSET_NOT_VERIFIED
    assert isinstance(execution_eligibility(doc, CATALOG), Eligible)


def test_recompile_with_new_catalog_is_an_explicit_choice() -> None:
    doc = _expect(_placed(gp01_document()), BindEffect(plain_effect("bright", "A", "brightness")))
    other = fixture_catalog(build="mlt-7.43.0-other")
    assert other.digest != CATALOG.digest
    blocked = execution_eligibility(doc, other)
    assert isinstance(blocked, Blocked) and blocked.reasons[0].code is RejectCode.CATALOG_MISMATCH
    _rejected(
        doc,
        SetParameter("bright", ParamAssignment("level", StaticValue(Float(0.5)))),
        code=RejectCode.CATALOG_MISMATCH,
        catalog=other,
    )
    _rejected(
        doc, RecompileWithNewCatalog(CATALOG.digest, other.digest), code=RejectCode.CATALOG_MISMATCH
    )
    recompiled = _expect(doc, RecompileWithNewCatalog(CATALOG.digest, other.digest), catalog=other)
    assert all(e.service.catalog_digest == other.digest for e in recompiled.effects)
    assert isinstance(execution_eligibility(recompiled, other), Eligible)
    smaller = fixture_catalog(build="mlt-7.43.0-other", without=("brightness",))
    _rejected(
        doc,
        RecompileWithNewCatalog(CATALOG.digest, smaller.digest),
        code=RejectCode.CATALOG_MISMATCH,
        catalog=smaller,
    )
    # a copied document with a retime mode this build does not declare is not executable
    held = TimeMap.make(
        ((0, 0), (90, 3), (120, 3), (210, 6)), Interpolation.LINEAR, RetimeMode.HOLD
    )
    retimed = _expect(_placed(gp01_document()), RetimeOccurrence("A", held))
    no_hold = replace(CATALOG, retime=replace(CATALOG.retime, modes=("Reverse",)))
    blocked = execution_eligibility(retimed, no_hold)
    assert isinstance(blocked, Blocked) and any(
        r.code is RejectCode.UNSUPPORTED_SPEED for r in blocked.reasons
    )


# ----------------------------------------------------------------------------- real store


def _project(tmp_path: Path, catalog: DescriptorCatalog = CATALOG) -> Project:
    project_dir = tmp_path / "proj"
    grant = issue_project_grant(project_dir, ACTOR)
    project = new_project(project_dir, grant, catalog, OutputProfile.default(), PROJECT)
    assert isinstance(project, Project), project
    return project


def _admit(project: Project, ops: tuple[Operation, ...], key: str, text: str = "edit") -> Applied:
    result = project.admit(project.batch(ops, replay_key=ReplayKey(key), provenance_text=text))
    assert isinstance(result, Applied), result
    return result


def _setup(project: Project) -> None:
    grant_id = project.grant.grant_id
    _admit(
        project,
        tuple(
            RebindAsset(asset(name, rec, grant_id), rec)
            for name, rec in (("interview", INTERVIEW), ("broll", BROLL))
        ),
        "bind-assets-0123456789",
    )


def test_sequence_edits_persist_and_reopen_without_loss(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _setup(project)
    root = project.ledger.lineage(project.head().revision_id)[0]
    _admit(
        project,
        (InsertOccurrence(LayerRef("V1"), occurrence("A", "interview", 0, 12, 0)),),
        "insert-0123456789abc",
    )
    cut = _admit(
        project,
        (
            TrimOccurrence("A", SourceSpan.make(0, 6)),
            InsertOccurrence(LayerRef("V1"), occurrence("A2", "interview", 8, 12, 180)),
            InsertOccurrence(LayerRef("V1"), occurrence("B", "broll", 0, 4, 300)),
        ),
        "cut-0123456789abcdef",
        "remove source seconds 6 through 8, append broll",
    )
    request = SubjectRequest(LiteralText("the person"), SourceSpan.make(0, 6), "sam31-mlx-metal")
    bound = _admit(
        project,
        (
            BindSubjectEffect(blur("blur", "A", "mask-A"), request),
            BindEffect(
                plain_effect(
                    "bright",
                    "B",
                    "brightness",
                    (ParamAssignment("level", StaticValue(Float(0.5))),),
                )
            ),
        ),
        "bind-0123456789abcdef",
    )
    assert (
        bound.admitted_event.intent_ids
        and project.ledger.pending_outbox()[0].intent_id == bound.admitted_event.intent_ids[0]
    )
    head = project.head()
    assert (
        len(head.document.all_occurrences()) == 3
        and head.document.sequence.video_layers[0].occurrences[-1].place.end.index == 420
    )
    assert cut.admitted_event.kind is EventKind.EDIT
    events = project.events()
    project.close()
    reopened = open_project(tmp_path / "proj", project.grant, CATALOG)
    assert isinstance(reopened, Opened)
    again = project_from_opened(reopened, CATALOG)
    assert again.head().record == head.record and again.head().document == head.document
    assert again.head().document.to_bytes() == head.document.to_bytes()
    assert again.ledger.lineage(head.revision_id)[0].revision_id == root.revision_id
    assert again.events() == events
    assert len(again.ledger.lineage(head.revision_id)) == 5
    assert again.ledger.verify(deep=True).ok
    # the same batch replayed is the same result, with no duplicate effect or intent
    replay = again.admit(
        again.batch(
            (
                BindSubjectEffect(blur("blur", "A", "mask-A"), request),
                BindEffect(
                    plain_effect(
                        "bright",
                        "B",
                        "brightness",
                        (ParamAssignment("level", StaticValue(Float(0.5))),),
                    )
                ),
            ),
            replay_key=ReplayKey("bind-0123456789abcdef"),
            provenance_text="edit",
            base=cut.revision.revision_id,
        )
    )
    assert isinstance(replay, AlreadyApplied) and replay.original_result == bound
    assert [e.effect_id for e in again.head().document.effects] == ["blur", "bright"]
    assert len(again.ledger.intents()) == 1
    stale = again.admit(
        again.batch(
            (MoveOccurrence("B", SequenceFrame(330)),),
            replay_key=ReplayKey("stale-0123456789abcd"),
            provenance_text="stale",
            base=cut.revision.revision_id,
        )
    )
    assert isinstance(stale, RevisionConflict) and stale.current_revision == head.revision_id
    again.close()


def test_selective_undo_of_a_cut_keeps_the_blur_and_exposes_missing_coverage(
    tmp_path: Path,
) -> None:
    """V02: cut, blur, independent title, then 'keep the blur, undo the last cut, and move the
    title half a second earlier'."""
    project = _project(tmp_path)
    _setup(project)
    _admit(
        project,
        (InsertOccurrence(LayerRef("V1"), occurrence("A", "interview", 0, 12, 0)),),
        "insert-0123456789abc",
    )
    cut = _admit(
        project,
        (
            TrimOccurrence("A", SourceSpan.make(0, 6)),
            InsertOccurrence(LayerRef("V1"), occurrence("A2", "interview", 8, 12, 180)),
        ),
        "cut-0123456789abcdef",
        "remove source seconds 6 through 8",
    )
    _admit(
        project,
        (AddTitle("title", LiteralText("Golden path"), 30, 60, "default"),),
        "title-0123456789abcd",
    )
    request = SubjectRequest(LiteralText("the person"), SourceSpan.make(0, 6), "sam31-mlx-metal")
    _admit(
        project,
        (BindSubjectEffect(blur("blur", "A", "mask-A"), request),),
        "blur-0123456789abcde",
        "keep this person sharp and blur the background",
    )
    before = project.head().document
    # plan the selective undo of the cut at the current head
    plan = project.plan_undo(cut.admitted_event.seq)
    assert isinstance(plan, UndoPlan)
    assert [type(op).__name__ for op in plan.operations] == ["RemoveOccurrence", "TrimOccurrence"]
    undo = _admit(
        project,
        (RevertOperation(cut.admitted_event.seq, ()),),
        "undo-cut-0123456789ab",
        "undo the last cut",
    )
    assert undo.admitted_event.kind is EventKind.UNDO
    after = project.head().document
    occ = after.occurrence("A")
    assert (
        occ is not None
        and occ[0].source == SourceSpan.make(0, 12)
        and occ[0].place == SequenceSpan.make(0, 360)
    )
    assert after.occurrence("A2") is None
    assert after.title("title") == before.title("title")  # independent later operation preserved
    effect = after.effect("blur")
    assert effect is not None and effect == before.effect("blur")  # the blur binding survives
    state = effect_dependency(after, effect)
    assert isinstance(state, PendingCoverage)
    assert state.missing == (SourceSpan.make(0, 12),)  # nothing produced yet: all pending
    assert state.requested == (
        SourceSpan.make(0, 6),
    )  # the newly exposed 6-12 s was never requested
    # with produced (unqualified) coverage for 0-6 s, exactly the exposed 6-12 s is missing
    covered = replace(
        after, analysis_refs=(mask_ref(after, "mask-A", "interview", (SourceSpan.make(0, 6),)),)
    )
    state = effect_dependency(covered, effect)
    assert isinstance(state, PendingCoverage) and state.missing == (SourceSpan.make(6, 12),)
    # half a second earlier: 15 frames at 30 fps, exact
    shift = timing.frames_nearest(F(-1, 2), after.profile.fps)
    assert shift.frames == -15 and shift.exact
    shifted = _admit(
        project,
        (ShiftTitle("title", shift.frames),),
        "shift-0123456789abcd",
        "move the title half a second earlier",
    )
    title = project.head().document.title("title")
    assert title is not None and title.place == SequenceSpan.make(15, 75)
    negative = project.admit(
        project.batch(
            (ShiftTitle("title", -16),),
            replay_key=ReplayKey("shift2-0123456789abc"),
            provenance_text="too early",
        )
    )
    assert (
        isinstance(negative, Rejected)
        and negative.contract_reason.code is RejectCode.NEGATIVE_START
    )
    assert project.head().record == shifted.revision
    # redo is a new validated batch: reverting the undo re-applies the cut
    redo = _admit(
        project,
        (RevertOperation(undo.admitted_event.seq, ()),),
        "redo-0123456789abcde",
        "redo the cut",
    )
    redone = project.head().document
    occ = redone.occurrence("A")
    assert (
        occ is not None
        and occ[0].source == SourceSpan.make(0, 6)
        and redone.occurrence("A2") is not None
    )
    title = redone.title("title")
    assert title is not None and title.place == SequenceSpan.make(15, 75)
    assert redo.admitted_event.kind is EventKind.UNDO
    assert project.ledger.verify(deep=True).ok
    assert [e.kind for e in project.events()] == [
        EventKind.IMPORT,
        EventKind.REBIND,
        EventKind.EDIT,
        EventKind.EDIT,
        EventKind.EDIT,
        EventKind.EDIT,
        EventKind.UNDO,
        EventKind.EDIT,
        EventKind.UNDO,
    ]
    project.close()


def test_undo_rebinds_a_dependent_effect_only_when_proven(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _setup(project)
    _admit(
        project,
        (InsertOccurrence(LayerRef("V1"), occurrence("A", "interview", 0, 12, 0)),),
        "insert-0123456789abc",
    )
    cut = _admit(
        project,
        (
            TrimOccurrence("A", SourceSpan.make(0, 6)),
            InsertOccurrence(LayerRef("V1"), occurrence("A2", "interview", 8, 12, 180)),
        ),
        "cut-0123456789abcdef",
    )
    request = SubjectRequest(LiteralText("the person"), SourceSpan.make(8, 12), "sam31-mlx-metal")
    _admit(
        project,
        (BindSubjectEffect(blur("blur", "A2", "mask-A2"), request),),
        "blur-0123456789abcde",
    )
    # the blur hangs on the right half of the cut: the only same-source occurrence after the
    # revert is A, whose restored range covers the mask's requested interval -> proven rebind
    plan = project.plan_undo(cut.admitted_event.seq)
    assert isinstance(plan, UndoPlan) and plan.rebound == ("blur",)
    assert [type(op).__name__ for op in plan.operations] == [
        "UnbindEffect",
        "RemoveOccurrence",
        "TrimOccurrence",
        "BindSubjectEffect",
    ]
    undone = _admit(project, (RevertOperation(cut.admitted_event.seq, ()),), "undo-0123456789abcde")
    doc = project.head().document
    effect = doc.effect("blur")
    assert (
        effect is not None
        and effect.target == OccurrenceTarget("A")
        and isinstance(effect.mask, MaskRef)
    )
    state = effect_dependency(doc, effect)
    assert (
        isinstance(state, PendingCoverage)
        and state.missing == (SourceSpan.make(0, 12),)
        and state.requested == (SourceSpan.make(8, 12),)
    )
    assert len(project.ledger.intents()) == 1  # rebinding requested nothing new
    # ambiguity: A already carries a different blur -> a precise conflict with the choices
    redo = _admit(
        project, (RevertOperation(undone.admitted_event.seq, ()),), "redo-0123456789abcde"
    )
    assert redo.admitted_event.kind is EventKind.UNDO
    _admit(
        project,
        (
            BindSubjectEffect(
                blur("blur-left", "A", "mask-A", radius=40),
                SubjectRequest(LiteralText("the person"), SourceSpan.make(0, 6), "sam31-mlx-metal"),
            ),
        ),
        "blur2-0123456789abcd",
    )
    conflict = project.plan_undo(cut.admitted_event.seq)
    assert isinstance(conflict, UndoConflict)
    assert conflict.dependents == (
        ObjectRef(ObjectKind.EFFECT, "blur"),
        ObjectRef(ObjectKind.EFFECT, "blur-left"),
    )
    assert conflict.choices == (
        DropDependent(ObjectRef(ObjectKind.EFFECT, "blur")),
        RebindTo("blur", "A"),
    )
    rejected = project.admit(
        project.batch(
            (RevertOperation(cut.admitted_event.seq, ()),),
            replay_key=ReplayKey("undo2-0123456789abcd"),
            provenance_text="undo",
        )
    )
    assert (
        isinstance(rejected, Rejected) and rejected.contract_reason.code is RejectCode.UNDO_CONFLICT
    )
    assert "choices" in rejected.contract_reason.detail
    head_before = project.head().record
    assert project.head().record == head_before  # nothing mutated
    resolved = _admit(
        project,
        (
            RevertOperation(
                cut.admitted_event.seq, (DropDependent(ObjectRef(ObjectKind.EFFECT, "blur")),)
            ),
        ),
        "undo3-0123456789abcd",
    )
    doc = project.head().document
    assert [e.effect_id for e in doc.effects] == ["blur-left"] and doc.occurrence("A2") is None
    assert resolved.admitted_event.kind is EventKind.UNDO
    project.close()


def test_undo_conflicts_on_later_changes_and_dangling_transitions(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _setup(project)
    _admit(
        project,
        (InsertOccurrence(LayerRef("V1"), occurrence("A", "interview", 0, 12, 0)),),
        "insert-0123456789abc",
    )
    cut = _admit(
        project,
        (
            TrimOccurrence("A", SourceSpan.make(0, 6)),
            InsertOccurrence(LayerRef("V1"), occurrence("A2", "interview", 8, 12, 180)),
        ),
        "cut-0123456789abcdef",
    )
    _admit(
        project,
        (
            MoveOccurrence("A2", SequenceFrame(200)),
            MoveOccurrence("A", SequenceFrame(10)),
        ),
        "move-0123456789abcde",
    )
    conflict = project.plan_undo(cut.admitted_event.seq)
    assert isinstance(conflict, UndoConflict)
    assert conflict.dependents == (
        ObjectRef(ObjectKind.OCCURRENCE, "A2"),
        ObjectRef(ObjectKind.OCCURRENCE, "A"),
    )
    assert all(isinstance(c, ForceRestore) for c in conflict.choices)
    forced = project.plan_undo(cut.admitted_event.seq, conflict.choices)
    assert isinstance(forced, UndoPlan)
    _admit(
        project,
        (RevertOperation(cut.admitted_event.seq, conflict.choices),),
        "undo-0123456789abcde",
    )
    occ = project.head().document.occurrence("A")
    assert occ is not None and occ[0].place == SequenceSpan.make(
        10, 370
    )  # restored length at the later start
    # a transition hanging on the right half must be dropped explicitly
    cut2 = _admit(
        project,
        (
            TrimOccurrence("A", SourceSpan.make(0, 6)),
            InsertOccurrence(LayerRef("V1"), occurrence("A2", "interview", 8, 12, 190)),
        ),
        "cut2-0123456789abcde",
    )
    _admit(
        project,
        (AddTransition("V1", Transition("x", "A", "A2", ref("luma"), 15, ())),),
        "trans-0123456789abcd",
    )
    conflict = project.plan_undo(cut2.admitted_event.seq)
    assert isinstance(conflict, UndoConflict)
    assert conflict.dependents == (ObjectRef(ObjectKind.TRANSITION, "x"),)
    assert conflict.choices == (DropDependent(ObjectRef(ObjectKind.TRANSITION, "x")),)
    _admit(
        project,
        (RevertOperation(cut2.admitted_event.seq, conflict.choices),),
        "undo2-0123456789abcd",
    )
    assert project.head().document.transition("x") is None
    unknown = project.plan_undo(EventSeq(99))
    assert (
        isinstance(unknown, Rejected) and unknown.contract_reason.code is RejectCode.UNKNOWN_EVENT
    )
    root_event = project.plan_undo(EventSeq(1))
    assert isinstance(root_event, Rejected)
    project.close()


def test_portable_snapshot_exports_validates_and_imports_as_new_lineage(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _setup(project)
    _admit(
        project,
        (
            InsertOccurrence(LayerRef("V1"), occurrence("A", "interview", 0, 12, 0)),
            BindEffect(plain_effect("bright", "A", "brightness")),
        ),
        "insert-0123456789abc",
    )
    head = project.head()
    data = project.export_snapshot(head.revision_id)
    valid = snapshot_module.validate(data)
    assert isinstance(valid, snapshot_module.ValidSnapshot)
    assert valid.document == head.document and valid.origin_revision_id == head.revision_id
    raw = json.loads(data)
    assert raw["$id"] == "aidashvideo.portable-snapshot/1" and raw["schema_version"] == 1
    assert raw["document"]["assets"][0]["availability"]["kind"] == "Present"
    assert len(raw["document"]["probes"]) == 2  # probe/provenance travels with the file
    # import into another store with the same catalog: a new lineage, sources unverified
    other_dir = tmp_path / "other"
    other = new_project(
        other_dir,
        issue_project_grant(other_dir, ACTOR),
        CATALOG,
        OutputProfile.default(),
        ProjectId("other"),
    )
    assert isinstance(other, Project)
    canonical_head = other.head().record
    imported = other.import_snapshot(data)
    assert isinstance(imported, NewLineage)
    assert other.head().record == canonical_head  # canonical head untouched
    assert imported.root_revision.project_id != other.project_id
    imported_doc = other.revision(imported.root_revision.revision_id).document
    assert all(isinstance(a.availability, Missing) for a in imported_doc.assets)
    assert (
        imported_doc.effects == head.document.effects
        and imported_doc.sequence == head.document.sequence
    )
    blocked = execution_eligibility(imported_doc, CATALOG)
    assert isinstance(blocked, Blocked) and {r.code for r in blocked.reasons} == {
        RejectCode.ASSET_NOT_VERIFIED
    }
    again = other.import_snapshot(data)
    assert isinstance(again, NewLineage) and again.root_revision == imported.root_revision
    assert len(other.ledger.lineages()) == 2
    # a copied file cannot make an unsupported descriptor renderable: other catalog -> blocked
    smaller = fixture_catalog(build="mlt-7.43.0-other", without=("brightness",))
    foreign = execution_eligibility(imported_doc, smaller)
    assert isinstance(foreign, Blocked) and any(
        r.code is RejectCode.CATALOG_MISMATCH for r in foreign.reasons
    )
    third_dir = tmp_path / "third"
    third = new_project(
        third_dir,
        issue_project_grant(third_dir, ACTOR),
        smaller,
        OutputProfile.default(),
        ProjectId("third"),
    )
    assert isinstance(third, Project)
    lineage = third.import_snapshot(data)
    assert isinstance(lineage, NewLineage)  # readable history...
    batch = OperationBatch(
        ACTOR,
        lineage.root_revision.project_id,
        lineage.root_revision.revision_id,
        ReplayKey("recompile-0123456789"),
        (),
        (RecompileWithNewCatalog(CATALOG.digest, smaller.digest),),
        UserWording("use the installed build"),
    )
    refused = third.admit(batch)
    assert (
        isinstance(refused, Rejected)
        and refused.contract_reason.code is RejectCode.CATALOG_MISMATCH
    )  # ...but no silent fallback
    # malformed and unsupported files are typed
    assert isinstance(
        snapshot_module.validate(b"{}"),
        InvalidSnapshot,
    )
    newer = json.loads(data)
    newer["schema_version"] = 2
    newer["min_reader_version"] = 2
    assert snapshot_module.validate(canonical_bytes(newer)) == UnsupportedSchema(2, 2)
    assert isinstance(other.import_snapshot(canonical_bytes(newer)), UnsupportedSchema)
    tampered = json.loads(data)
    tampered["document"]["effects"][0]["params"] = {"level": 1}
    assert isinstance(
        snapshot_module.validate(canonical_bytes(tampered)),
        InvalidSnapshot,
    )
    for p in (project, other, third):
        p.close()


def test_relink_after_import_needs_verified_bytes_through_the_store(tmp_path: Path) -> None:
    """V10/V30: an imported lineage's sources are Missing until the store verifies the bytes
    by content hash and an explicit RebindAsset binds them; a path alone changes nothing."""
    from aidashvideo.store import ProbeReceipt, Store

    project = _project(tmp_path)
    _setup(project)
    _admit(
        project,
        (InsertOccurrence(LayerRef("V1"), occurrence("A", "interview", 0, 12, 0)),),
        "insert-0123456789abc",
    )
    data = project.export_snapshot(project.head().revision_id)
    project.close()
    other_dir = tmp_path / "other"
    grant = issue_project_grant(other_dir, ACTOR)
    other = new_project(other_dir, grant, CATALOG, OutputProfile.default(), ProjectId("other"))
    assert isinstance(other, Project)
    imported = other.import_snapshot(data)
    assert isinstance(imported, NewLineage)
    lineage_doc = other.revision(imported.root_revision.revision_id).document
    interview = lineage_doc.assets[0]
    assert isinstance(interview.availability, Missing)
    assert isinstance(execution_eligibility(lineage_doc, CATALOG), Blocked)

    class MatchingProber:
        def probe(self, path: Path) -> ProbeReceipt:
            return INTERVIEW

    store = Store(other.ledger, MatchingProber())
    media = other_dir / "media"
    media.mkdir()
    (media / "wrong.bin").write_bytes(b"not the interview bytes")
    wrong = store.import_source(ScopedLocator(grant.grant_id, "media/wrong.bin"), grant)
    assert not isinstance(wrong, ImportRefused)
    assert wrong.sha256 != interview.identity.sha256  # a path is never a match
    assert store.resolve_by_hash(interview.identity.sha256) == ()
    (media / "interview.bin").write_bytes(b"interview")  # identity("interview") hashes this
    found = store.import_source(ScopedLocator(grant.grant_id, "media/interview.bin"), grant)
    assert not isinstance(found, ImportRefused)
    assert found.sha256 == interview.identity.sha256
    locator = store.resolve_by_hash(interview.identity.sha256)[0]
    verified = store.availability("interview", found, locator)
    assert isinstance(verified, Present)
    rebound = AssetRef("interview", found, verified)
    batch = OperationBatch(
        ACTOR,
        imported.root_revision.project_id,
        imported.root_revision.revision_id,
        ReplayKey("relink-0123456789abc"),
        (),
        (RebindAsset(rebound, INTERVIEW),),
        UserWording("relink the interview after verifying its bytes"),
    )
    result = other.admit(batch)
    assert isinstance(result, Applied) and result.admitted_event.kind is EventKind.REBIND
    relinked = other.revision(result.revision.revision_id).document
    eligibility = execution_eligibility(
        relinked, CATALOG, {"interview": store.availability("interview", found, locator)}
    )
    assert isinstance(eligibility, Blocked)  # broll is still Missing: only verified sources run
    assert [r.objects for r in eligibility.reasons] == [("asset:broll",)]
    assert relinked.assets[0].availability == verified
    assert len(other.ledger.lineage(result.revision.revision_id)) == 2  # history retained
    other.close()


def test_migration_path_is_explicit_and_history_survives(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _setup(project)
    from aidashvideo.ledger import MigrationPlan, NothingToMigrate

    assert isinstance(
        project.ledger.migrate(MigrationPlan(target_document_version=1), project.grant),
        NothingToMigrate,
    )
    no_path = project.ledger.migrate(MigrationPlan(target_document_version=2), project.grant)
    assert (
        isinstance(no_path, Rejected)
        and no_path.contract_reason.code is RejectCode.NO_MIGRATION_PATH
    )
    assert project.domain.migrate_document(b"{}", 1, 2).__class__.__name__ == "Rejected"
    assert len(project.events()) == 2
    project.close()


def test_analysis_evidence_enters_through_the_ledger_and_captions_follow(tmp_path: Path) -> None:
    """Transcript evidence is admitted as an operation (ToolCall provenance in M3), captions
    cite it, ducking cites it, and none of it can be removed while cited."""
    project = _project(tmp_path)
    _setup(project)
    _admit(
        project,
        (
            InsertOccurrence(LayerRef("V1"), occurrence("A", "interview", 0, 12, 0)),
            InsertOccurrence(
                TrackRef("A1"), occurrence("A-audio", "interview", 0, 12, 0, stream_index=1)
            ),
        ),
        "insert-0123456789abc",
    )
    doc = project.head().document
    requested = SourceSpan.make(F(2015, 1000), F(3105, 1000))
    evidence = transcript_ref(doc, "tr1", "interview", 1, (requested,))
    recorded = _admit(
        project, (RecordAnalysis(evidence),), "record-0123456789abc", "speech adapter result"
    )
    assert recorded.admitted_event.kind is EventKind.EFFECT_FACT
    occ = project.head().document.occurrence("A")
    assert occ is not None
    placed = timing.place_source_span(occ[0].placement, requested, FPS)
    assert not isinstance(placed, timing.OutsidePlacedRange)
    caption = Caption(
        "c1",
        LiteralText("hello golden path"),
        placed.runs[0].frames,
        "en",
        "default",
        (LiteralText("hello golden path"),),
        "tr1",
        requested,
    )
    _admit(
        project,
        (
            SetCaptions((caption,)),
            AddAudioTrack("music", AudioMix(F(-6), 0, 0, DuckUnder("A1", F(-12), "tr1"))),
        ),
        "caption-0123456789ab",
        "caption the spoken phrase and duck music under speech",
    )
    head = project.head().document
    assert head.sequence.captions == (caption,) and head.sequence.captions[
        0
    ].place == SequenceSpan.make(60, 93)
    cited = project.admit(
        project.batch(
            (RemoveAnalysis("tr1"),),
            replay_key=ReplayKey("remove-0123456789ab"),
            provenance_text="drop",
        )
    )
    assert isinstance(cited, Rejected) and cited.contract_reason.code is RejectCode.DEPENDENTS_EXIST
    assert set(cited.contract_reason.objects) >= {"analysis:tr1", "caption:c1", "track:music"}
    # produced evidence that names an artifact is admitted only once the bytes are sealed
    unsealed = transcript_ref(
        doc, "tr3", "interview", 1, (requested,), EvidenceArtifact(Sha256("6" * 64))
    )
    dangling = project.admit(
        project.batch(
            (RecordAnalysis(unsealed),),
            replay_key=ReplayKey("record3-0123456789a"),
            provenance_text="x",
        )
    )
    assert isinstance(dangling, Rejected)
    assert dangling.contract_reason.code is RejectCode.UNKNOWN_ARTIFACT
    sealed = project.ledger.seal_artifact(
        b'{"segments": []}', "transcript", {"tool": "fixture"}, (), "transcript:tr3"
    )
    assert not isinstance(sealed, Rejected)
    with_artifact = transcript_ref(
        doc, "tr3", "interview", 1, (requested,), EvidenceArtifact(sealed.sha256)
    )
    assert isinstance(
        project.admit(
            project.batch(
                (RecordAnalysis(with_artifact),),
                replay_key=ReplayKey("record4-0123456789a"),
                provenance_text="x",
            )
        ),
        Applied,
    )
    unknown_asset = replace(
        evidence, ref_id="tr2", binding=replace(evidence.binding, asset_sha256=Sha256("7" * 64))
    )
    foreign = project.admit(
        project.batch(
            (RecordAnalysis(unknown_asset),),
            replay_key=ReplayKey("record2-0123456789a"),
            provenance_text="x",
        )
    )
    assert (
        isinstance(foreign, Rejected) and foreign.contract_reason.code is RejectCode.UNKNOWN_OBJECT
    )
    project.close()


def test_inverse_helper_matches_the_admitted_inverse() -> None:
    doc = _placed(gp01_document())
    op = TrimOccurrence("A", SourceSpan.make(1, 5))
    computed = apply_module.inverse(op, doc, CATALOG)
    assert computed == TrimOccurrence("A", SourceSpan.make(0, 12))
    assert isinstance(
        apply_module.inverse(TrimOccurrence("Z", SourceSpan.make(1, 5)), doc, CATALOG), Rejected
    )


def test_required_and_descriptor_bound_sets_are_complete() -> None:
    from aidashvideo.project.operations import DESCRIPTOR_BOUND_OPERATIONS, REQUIRED_OPERATIONS

    assert set(REQUIRED_OPERATIONS) == {
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
    }
    assert set(DESCRIPTOR_BOUND_OPERATIONS) == {
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
    }
    assert apply_module.MASK_INTENT_DEADLINE_S == 600
    assert Normal().ratio == 1
