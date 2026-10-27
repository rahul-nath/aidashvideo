"""Timing and geometry algebra (M1c; I4, V03, V04, V24): exact rationals, half-open spans,
constant speed, declared hold/reverse/variable maps, VFR tables, audio offsets, handles,
requested-versus-realized boundaries and oriented geometry. Property tests use hypothesis.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aidashvideo.ledger import ContractError
from aidashvideo.project import geometry, timing
from aidashvideo.project.geometry import Box, OrientedGrid, Point, ProfileFrame, RejectedSelection
from aidashvideo.project.timing import (
    BeforeFirstFrame,
    Constant,
    HandlesOk,
    InsufficientHandles,
    Interpolation,
    Mapped,
    NegativeStart,
    Normal,
    OutsidePlacedRange,
    Placement,
    RetimeMode,
    SequenceFrame,
    SequenceSpan,
    SourceSpan,
    SourceTime,
    TimeMap,
    timing_from_json,
    timing_to_json,
)
from aidashvideo.store import ConstantRate, Rotation, Sdr709, VfrTable, VideoStream

pytestmark = pytest.mark.timing

FPS30 = Fraction(30)
NTSC = Fraction(30000, 1001)
F = Fraction
ONE = F(1)
ZERO = F(0)
CFR = ConstantRate()


def _placement(in_: F | int, out: F | int, start: int, speed: timing.Timing, fps: F) -> Placement:
    source = SourceSpan.make(in_, out)
    frames = timing.duration_frames(source, speed, fps)
    return Placement(source, SequenceSpan.make(start, start + frames), speed)


def _video(
    fps: F = FPS30,
    width: int = 1920,
    height: int = 1080,
    sar: F = ONE,
    rotation: Rotation = Rotation.R0,
    vfr: VfrTable | ConstantRate = CFR,
    start_time: F = ZERO,
) -> VideoStream:
    return VideoStream(
        0, "h264", width, height, sar, fps, F(1, 90000), start_time, rotation, Sdr709(), vfr, False
    )


# ----------------------------------------------------------------------------- spans


def test_spans_are_finite_half_open_and_exact() -> None:
    assert SequenceSpan.make(0, 30).frames == 30
    assert SequenceSpan.make(0, 30).contains(SequenceFrame(29))
    assert not SequenceSpan.make(0, 30).contains(SequenceFrame(30))
    assert SourceSpan.make(F(1, 3), 2).duration == F(5, 3)
    with pytest.raises(ContractError):
        SequenceSpan.make(5, 5)
    with pytest.raises(ContractError):
        SequenceSpan.make(6, 5)
    with pytest.raises(ContractError):
        SequenceSpan.make(-1, 5)
    with pytest.raises(ContractError):
        SourceSpan.make(2, 2)
    with pytest.raises(ContractError):
        SourceTime(F(-1))
    with pytest.raises(ContractError):
        SourceTime.make(0.5)  # type: ignore[arg-type]  # floats never enter a span
    with pytest.raises(ContractError):
        SequenceFrame(True)  # bools are not frame counts
    with pytest.raises(ContractError):
        Constant.make(0)
    with pytest.raises(ContractError):
        Constant.make(F(-1, 2))
    assert SequenceSpan.make(10, 20).shifted(-10) == SequenceSpan.make(0, 10)
    assert SequenceSpan.make(10, 20).shifted(-11) == NegativeStart(-1)


def test_malformed_json_numbers_and_intervals_are_refused() -> None:
    for raw in ("1/0", "nan", "0.5", 1.5, "", "a/b", "1/-2"):
        with pytest.raises(ContractError):
            SourceTime.from_json(raw)
    with pytest.raises(ContractError):
        SourceSpan.from_json({"in": "2/1", "out": "1/1"})
    with pytest.raises(ContractError):
        SourceSpan.from_json({"in": "1/1", "out": "2/1", "extra": 1})
    with pytest.raises(ContractError):
        SequenceSpan.from_json({"start": 0, "end": 0})
    with pytest.raises(ContractError):
        timing_from_json({"kind": "Constant", "ratio": "0/1"})
    with pytest.raises(ContractError):
        timing_from_json({"kind": "Warp"})
    with pytest.raises(ContractError):
        timing_from_json({"kind": "Normal", "ratio": "1/1"})
    assert timing_from_json(timing_to_json(Constant.make(F(3, 2)))) == Constant.make(F(3, 2))


# ----------------------------------------------------------------------------- constant speed


def test_constant_speed_formula_and_inverse() -> None:
    p = _placement(F(2), F(14), 100, Normal(), FPS30)
    assert p.place == SequenceSpan.make(100, 460)
    assert timing.source_time_at(p, SequenceFrame(100), FPS30) == Mapped(SourceTime(F(2)))
    assert timing.source_time_at(p, SequenceFrame(130), FPS30) == Mapped(SourceTime(F(3)))
    assert timing.source_time_at(p, SequenceFrame(459), FPS30) == Mapped(
        SourceTime(F(2) + F(359, 30))
    )
    assert isinstance(timing.source_time_at(p, SequenceFrame(460), FPS30), OutsidePlacedRange)
    assert isinstance(timing.source_time_at(p, SequenceFrame(99), FPS30), OutsidePlacedRange)
    assert timing.frame_for_source_time(p, SourceTime(F(3)), FPS30) == SequenceFrame(130)
    assert timing.frame_for_source_time(p, SourceTime(F(3) + F(1, 1000)), FPS30) == SequenceFrame(
        130
    )
    assert isinstance(timing.frame_for_source_time(p, SourceTime(F(14)), FPS30), OutsidePlacedRange)
    fast = _placement(F(0), F(12), 0, Constant.make(2), FPS30)
    assert fast.place.frames == 180
    assert timing.source_time_at(fast, SequenceFrame(179), FPS30) == Mapped(SourceTime(F(358, 30)))
    slow = _placement(F(0), F(1), 0, Constant.make(F(1, 2)), FPS30)
    assert slow.place.frames == 60
    assert timing.source_time_at(slow, SequenceFrame(59), FPS30) == Mapped(SourceTime(F(59, 60)))
    # ceil keeps every frame inside [in, out): 1.09 s at 30 fps -> 33 frames
    assert (
        timing.duration_frames(SourceSpan.make(F(2015, 1000), F(3105, 1000)), Normal(), FPS30) == 33
    )


@settings(max_examples=300, deadline=None)
@given(
    fps=st.sampled_from([F(24), F(25), FPS30, NTSC, F(60), F(24000, 1001)]),
    in_num=st.integers(0, 5000),
    dur_num=st.integers(1, 5000),
    speed_num=st.integers(1, 8),
    speed_den=st.integers(1, 8),
    start=st.integers(0, 1000),
)
def test_constant_speed_inverse_round_trips_every_frame(
    fps: F, in_num: int, dur_num: int, speed_num: int, speed_den: int, start: int
) -> None:
    source = SourceSpan(SourceTime(F(in_num, 100)), SourceTime(F(in_num + dur_num, 100)))
    speed = Constant.make(F(speed_num, speed_den))
    frames = timing.duration_frames(source, speed, fps)
    p = Placement(source, SequenceSpan.make(start, start + frames), speed)
    assert timing.validate_placement(p, fps) is None
    for index in range(p.place.start.index, p.place.end.index):
        mapped = timing.source_time_at(p, SequenceFrame(index), fps)
        assert isinstance(mapped, Mapped)
        assert source.contains(mapped.source)
        assert timing.frame_for_source_time(p, mapped.source, fps) == SequenceFrame(index)
    last = timing.source_time_at(p, SequenceFrame(p.place.end.index - 1), fps)
    assert isinstance(last, Mapped)
    # the frame after the last would sample at or past the out point: the ceil rule is tight
    assert last.source.seconds + speed.ratio / fps >= source.out.seconds


# ----------------------------------------------------------------------------- placement of spans


def test_caption_span_realizes_at_frame_starts_within_one_frame() -> None:
    p = _placement(0, 12, 0, Normal(), FPS30)
    requested = SourceSpan.make(F(2015, 1000), F(3105, 1000))
    placed = timing.place_source_span(p, requested, FPS30)
    assert not isinstance(placed, OutsidePlacedRange)
    assert placed.requested == requested and len(placed.runs) == 1
    run = placed.runs[0]
    assert run.frames == SequenceSpan.make(60, 93)  # 2.015 s -> frame 60 start; 3.105 s -> 93
    assert run.first_source == SourceTime(F(2)) and run.last_source == SourceTime(F(92, 30))
    realized = timing.realized_source_span(p, run.frames, FPS30)
    assert realized == SourceSpan.make(2, F(93, 30))
    assert isinstance(realized, SourceSpan)
    assert abs(realized.in_.seconds - requested.in_.seconds) < 1 / FPS30
    assert abs(realized.out.seconds - requested.out.seconds) < 1 / FPS30
    outside = timing.place_source_span(p, SourceSpan.make(11, 13), FPS30)
    assert isinstance(outside, OutsidePlacedRange)  # never clamped
    shifted = _placement(4, 8, 300, Normal(), FPS30)
    inner = timing.place_source_span(shifted, SourceSpan.make(5, 6), FPS30)
    assert not isinstance(inner, OutsidePlacedRange)
    assert inner.runs[0].frames == SequenceSpan.make(330, 360)
    tiny = timing.place_source_span(p, SourceSpan.make(F(1, 100), F(2, 100)), FPS30)
    assert not isinstance(tiny, OutsidePlacedRange)
    assert tiny.runs[0].frames == SequenceSpan.make(0, 1)  # shorter than a frame: one frame
    tail = timing.place_source_span(p, SourceSpan.make(F(119, 10), 12), FPS30)
    assert not isinstance(tail, OutsidePlacedRange)
    assert tail.runs[0].frames == SequenceSpan.make(357, 360)


@settings(max_examples=200, deadline=None)
@given(
    fps=st.sampled_from([F(24), FPS30, NTSC, F(60)]),
    a=st.integers(0, 10000),
    b=st.integers(1, 10000),
    speed_num=st.integers(1, 4),
)
def test_placed_span_boundaries_realize_at_frame_starts_within_one_frame(
    fps: F, a: int, b: int, speed_num: int
) -> None:
    speed = Constant.make(F(speed_num, 2))
    p = _placement(0, 20, 7, speed, fps)
    span = SourceSpan(SourceTime(F(a, 1000)), SourceTime(F(a + b, 1000)))
    if span.out.seconds > 20:
        return
    placed = timing.place_source_span(p, span, fps)
    assert not isinstance(placed, OutsidePlacedRange)
    assert len(placed.runs) == 1
    run = placed.runs[0]
    assert run.frames.start == timing.frame_for_source_time(p, span.in_, fps)
    assert p.place.contains(run.frames.start) and run.frames.end.index <= p.place.end.index
    step = speed.ratio / fps
    assert run.first_source.seconds <= span.in_.seconds < run.first_source.seconds + step
    realized = timing.realized_source_span(p, run.frames, fps)
    assert not isinstance(realized, OutsidePlacedRange)
    assert realized.out.seconds <= max(span.out.seconds, realized.in_.seconds + step)
    assert span.out.seconds - realized.out.seconds < step


# ----------------------------------------------------------------------------- time maps


def test_hold_map_repeats_an_instant_without_dividing_by_zero() -> None:
    # interview plays 0-3 s, holds at 3 s for one second, then plays 3-6 s (fixture recipe)
    tm = TimeMap.make(((0, 0), (90, 3), (120, 3), (210, 6)), Interpolation.LINEAR, RetimeMode.HOLD)
    p = Placement(SourceSpan.make(0, 6), SequenceSpan.make(0, 210), tm)
    assert timing.validate_placement(p, FPS30) is None
    assert timing.source_time_at(p, SequenceFrame(45), FPS30) == Mapped(SourceTime(F(3, 2)))
    for frame in range(90, 120):
        assert timing.source_time_at(p, SequenceFrame(frame), FPS30) == Mapped(SourceTime(F(3)))
    assert timing.source_time_at(p, SequenceFrame(150), FPS30) == Mapped(SourceTime(F(4)))
    assert timing.source_time_at(p, SequenceFrame(209), FPS30) == Mapped(
        SourceTime(F(3) + F(89, 30))
    )
    held = timing.frames_for_source_time(p, SourceTime(F(3)), FPS30)
    assert [f.index for f in held] == list(range(90, 121))  # hold plus the linear boundary frame
    placed = timing.place_source_span(p, SourceSpan.make(F(5, 2), F(7, 2)), FPS30)
    assert not isinstance(placed, OutsidePlacedRange)
    assert [r.frames for r in placed.runs] == [SequenceSpan.make(75, 135)]
    # one-frame hold segments: lengths are 1, never 0
    tiny = TimeMap.make(((0, 1), (1, 1), (2, 1), (3, 2)), Interpolation.HOLD, RetimeMode.HOLD)
    tp = Placement(SourceSpan.make(1, 3), SequenceSpan.make(0, 3), tiny)
    assert timing.sampled_instants(tp, FPS30) == (SourceTime(F(1)),) * 3
    with pytest.raises(ContractError, match="strictly increase"):
        TimeMap.make(((0, 1), (1, 1), (1, 2)), Interpolation.HOLD, RetimeMode.HOLD)
    with pytest.raises(ContractError, match="held segment"):
        TimeMap.make(((0, 0), (30, 1)), Interpolation.LINEAR, RetimeMode.HOLD)
    with pytest.raises(ContractError, match="offset 0"):
        TimeMap.make(((1, 0), (30, 1)), Interpolation.LINEAR, RetimeMode.VARIABLE)


def test_reverse_map_is_declared_and_exact() -> None:
    tm = TimeMap.make(((0, 6), (180, 0)), Interpolation.LINEAR, RetimeMode.REVERSE)
    p = Placement(SourceSpan.make(0, F(61, 10)), SequenceSpan.make(30, 210), tm)
    assert timing.validate_placement(p, FPS30) is None
    assert timing.source_time_at(p, SequenceFrame(30), FPS30) == Mapped(SourceTime(F(6)))
    assert timing.source_time_at(p, SequenceFrame(209), FPS30) == Mapped(SourceTime(F(1, 30)))
    placed = timing.place_source_span(p, SourceSpan.make(2, 4), FPS30)
    assert not isinstance(placed, OutsidePlacedRange)
    assert [r.frames for r in placed.runs] == [SequenceSpan.make(91, 151)]
    assert placed.runs[0].first_source == SourceTime(F(6) - F(61, 30))
    assert placed.runs[0].last_source == SourceTime(F(2))
    with pytest.raises(ContractError, match="Reverse"):
        TimeMap.make(((0, 0), (180, 6)), Interpolation.LINEAR, RetimeMode.REVERSE)


def test_reverse_map_sampling_the_out_point_is_outside_placed_range() -> None:
    tm = TimeMap.make(((0, 6), (180, 0)), Interpolation.LINEAR, RetimeMode.REVERSE)
    p = Placement(SourceSpan.make(0, 6), SequenceSpan.make(0, 180), tm)
    # frame 0 samples 6.0 which is not inside [0, 6): the placement is invalid, not clamped
    assert isinstance(timing.validate_placement(p, FPS30), OutsidePlacedRange)
    ok = Placement(SourceSpan.make(0, F(61, 10)), SequenceSpan.make(0, 180), tm)
    assert timing.validate_placement(ok, FPS30) is None


def test_variable_map_repeats_a_source_passage_and_reports_each_pass() -> None:
    tm = TimeMap.make(
        ((0, 0), (60, 2), (120, 0), (180, 2)), Interpolation.LINEAR, RetimeMode.VARIABLE
    )
    p = Placement(SourceSpan.make(0, F(21, 10)), SequenceSpan.make(0, 180), tm)
    assert timing.validate_placement(p, FPS30) is None
    passes = timing.frames_for_source_time(p, SourceTime(F(1)), FPS30)
    assert [f.index for f in passes] == [30, 90, 150]
    placed = timing.place_source_span(p, SourceSpan.make(F(1, 2), F(3, 2)), FPS30)
    assert not isinstance(placed, OutsidePlacedRange)
    assert [r.frames for r in placed.runs] == [
        SequenceSpan.make(15, 45),
        SequenceSpan.make(76, 106),
        SequenceSpan.make(135, 165),
    ]
    for run in placed.runs:
        for index in range(run.frames.start.index, run.frames.end.index):
            mapped = timing.source_time_at(p, SequenceFrame(index), FPS30)
            assert isinstance(mapped, Mapped) and F(1, 2) <= mapped.source.seconds < F(3, 2)
    with pytest.raises(ContractError, match="frames"):
        Placement(SourceSpan.make(0, 3), SequenceSpan.make(0, 100), tm)
    assert timing_from_json(timing_to_json(tm)) == tm


def test_coverage_missing_reports_newly_exposed_intervals() -> None:
    p = _placement(0, 12, 0, Normal(), FPS30)
    covered = (SourceSpan.make(0, 6), SourceSpan.make(8, 12))
    assert timing.coverage_missing(p, covered, FPS30) == (SourceSpan.make(6, 8),)
    assert timing.coverage_missing(p, (SourceSpan.make(0, 12),), FPS30) == ()
    assert timing.coverage_missing(p, (), FPS30) == (SourceSpan.make(0, 12),)
    assert timing.subtract_spans(
        SourceSpan.make(0, 10),
        (SourceSpan.make(2, 3), SourceSpan.make(2, 5), SourceSpan.make(9, 20)),
    ) == (
        SourceSpan.make(0, 2),
        SourceSpan.make(5, 9),
    )
    tm = TimeMap.make(((0, 0), (90, 3), (120, 3), (210, 6)), Interpolation.LINEAR, RetimeMode.HOLD)
    held = Placement(SourceSpan.make(0, 6), SequenceSpan.make(0, 210), tm)
    missing = timing.coverage_missing(held, (SourceSpan.make(0, 3),), FPS30)
    assert missing == (SourceSpan.make(3, 6),)
    assert timing.coverage_missing(
        held, (SourceSpan.make(0, 3), SourceSpan.make(3, F(301, 100))), FPS30
    ) == (SourceSpan.make(F(91, 30), 6),)


# ----------------------------------------------------------------------------- VFR and streams


def test_vfr_table_maps_sequence_frames_to_actual_decoded_frames() -> None:
    pts = tuple(F(p, 60) for p in range(0, 60) if p % 3 != 2)  # 60 fps source dropping every third
    stream = _video(fps=F(60), vfr=VfrTable(pts))
    assert timing.source_frame_index(stream, SourceTime(F(0))) == 0
    assert timing.source_frame_index(stream, SourceTime(F(1, 60))) == 1
    assert timing.source_frame_index(stream, SourceTime(F(2, 60))) == 1  # dropped frame 2: hold 1
    assert timing.source_frame_index(stream, SourceTime(F(3, 60))) == 2
    assert timing.source_frame_pts(stream, 2) == SourceTime(F(3, 60))
    assert isinstance(timing.source_frame_pts(stream, 40), OutsidePlacedRange)
    assert timing.stream_frame_count(stream, F(1)) == 40
    # a 30 fps sequence frame n samples source n/30 = 2n/60 -> decoded frame index by bisect
    p = _placement(0, 1, 0, Normal(), FPS30)
    expected = [0, 1, 3, 4, 5, 7, 8, 9, 11, 12]
    for n in range(10):
        mapped = timing.source_time_at(p, SequenceFrame(n), FPS30)
        assert isinstance(mapped, Mapped)
        assert timing.source_frame_index(stream, mapped.source) == expected[n]
    late = VideoStream(
        0,
        "h264",
        16,
        16,
        F(1),
        F(30),
        F(1, 30),
        F(0),
        Rotation.R0,
        Sdr709(),
        VfrTable((F(1, 2), F(1))),
        False,
    )
    assert timing.source_frame_index(late, SourceTime(F(1, 4))) == BeforeFirstFrame(
        SourceTime(F(1, 4))
    )
    cfr = _video(fps=NTSC)
    assert timing.source_frame_index(cfr, SourceTime(F(1001, 30000) * 7)) == 7
    assert timing.source_frame_index(cfr, SourceTime(F(1001, 30000) * 7 - F(1, 10**9))) == 6


def test_audio_samples_and_stream_offsets_have_no_drift() -> None:
    assert timing.sample_for_frame(SequenceFrame(1), FPS30).index == 1600
    assert timing.sample_for_frame(SequenceFrame(18000), NTSC).index == 28828800
    ten_minutes = timing.sample_span_for_frames(SequenceSpan.make(0, 18000), FPS30)
    assert ten_minutes.samples == 18000 * 1600
    # exact rational arithmetic: the 10-minute NTSC boundary is floor(18000*48000*1001/30000)
    assert (
        timing.sample_for_frame(SequenceFrame(17982), NTSC).index == (17982 * 48000 * 1001) // 30000
    )
    from aidashvideo.store import AudioStream

    video = _video(start_time=F(15, 2))
    audio = AudioStream(1, "aac", 48000, 2, "stereo", F(1, 48000), F(17, 2))
    assert timing.container_time(video, SourceTime(F(2))) == F(19, 2)
    assert timing.align_span(SourceSpan.make(2, 4), video, audio) == SourceSpan.make(1, 3)
    assert isinstance(timing.align_span(SourceSpan.make(0, 2), video, audio), OutsidePlacedRange)
    assert timing.stream_sample_for_source_time(audio, SourceTime(F(1, 3))).index == 16000
    odd = AudioStream(1, "pcm", 44100, 2, "stereo", F(1, 44100), F(0))
    assert timing.stream_sample_for_source_time(odd, SourceTime(F(1, 3))).index == 14700


def test_seconds_to_frames_record_requested_and_realized() -> None:
    half = timing.frames_nearest(F(-1, 2), FPS30)
    assert (half.frames, half.realized_seconds, half.exact) == (-15, F(-1, 2), True)
    ntsc = timing.frames_nearest(F(-1, 2), NTSC)
    assert ntsc.frames == -15 and ntsc.realized_seconds == F(-15 * 1001, 30000) and not ntsc.exact
    assert timing.frames_nearest(F(1, 2), F(24)).frames == 12
    assert timing.frames_nearest(F(1, 48), F(24)).frames == 1  # exact half rounds away from zero
    floor = timing.frames_floor(F(2015, 1000), FPS30)
    assert (floor.frames, floor.realized_seconds) == (60, F(2))


# ----------------------------------------------------------------------------- handles


def test_transition_handles_check_both_neighbours() -> None:
    left = _placement(0, 6, 0, Normal(), FPS30)
    right = _placement(8, 12, 180, Normal(), FPS30)
    assert timing.transition_handles(left, right, 15, FPS30, F(12), F(12)) == HandlesOk()
    short_left = timing.transition_handles(left, right, 15, FPS30, F(6), F(12))
    assert isinstance(short_left, InsufficientHandles)
    right_at_zero = _placement(0, 4, 180, Normal(), FPS30)
    assert isinstance(
        timing.transition_handles(left, right_at_zero, 15, FPS30, F(12), F(4)), InsufficientHandles
    )
    gap = _placement(8, 12, 181, Normal(), FPS30)
    assert isinstance(
        timing.transition_handles(left, gap, 15, FPS30, F(12), F(12)), InsufficientHandles
    )
    assert isinstance(
        timing.transition_handles(left, right, 0, FPS30, F(12), F(12)), InsufficientHandles
    )
    assert isinstance(
        timing.transition_handles(left, right, 200, FPS30, F(100), F(100)), InsufficientHandles
    )
    exact = timing.transition_handles(left, right, 120, FPS30, F(10), F(12))
    assert exact == HandlesOk()  # 4 s after the out point of a 10 s stream fits exactly


# ----------------------------------------------------------------------------- geometry


def test_rotation_and_sar_produce_the_oriented_grid() -> None:
    portrait = _video(rotation=Rotation.R90)
    assert geometry.oriented_grid(portrait) == OrientedGrid(1080, 1920)
    affine = geometry.source_to_oriented(portrait)
    assert affine.apply(F(0), F(0)) == (F(1080), F(0))
    assert geometry.transform_box(affine, Box.make(0, 0, 1, 1)) == Box.make(1079, 0, 1080, 1)
    # fixture ground truth at t = 3 s: body x in [680, 1000), y in [250, 870) on the unrotated grid
    body = Box.make(680, 250, 1000, 870)
    oriented = geometry.source_box_to_oriented(portrait, body)
    assert not isinstance(oriented, RejectedSelection)
    assert oriented.box == Box.make(210, 680, 830, 1000)
    anamorphic = _video(width=1440, sar=F(4, 3))
    assert geometry.oriented_grid(anamorphic) == OrientedGrid(1920, 1080)
    wide = geometry.source_box_to_oriented(anamorphic, Box.make(0, 0, 720, 540))
    assert not isinstance(wide, RejectedSelection) and wide.box == Box.make(0, 0, 960, 540)
    upside = _video(rotation=Rotation.R180)
    assert geometry.transform_box(
        geometry.source_to_oriented(upside), Box.make(0, 0, 10, 10)
    ) == Box.make(1910, 1070, 1920, 1080)
    r270 = _video(rotation=Rotation.R270)
    assert geometry.transform_box(
        geometry.source_to_oriented(r270), Box.make(0, 0, 10, 10)
    ) == Box.make(0, 1910, 10, 1920)


def test_display_affine_fits_contain_and_rejects_letterbox_clicks() -> None:
    portrait = _video(rotation=Rotation.R90)
    frame = ProfileFrame(1920, 1080)
    affine = geometry.display_affine(portrait, frame)
    scale = F(9, 16)
    assert affine.apply(F(0), F(0)) == (F(1920 - 1080 * scale, 2) + 1080 * scale, F(0))
    assert geometry.oriented_to_sequence(portrait, frame).apply(F(0), F(0)) == (
        F(1920 - 1080 * scale, 2),
        F(0),
    )
    click = Point(F(1920 - 1080 * scale, 2) + 10 * scale, 100 * scale)
    mapped = geometry.sequence_point_to_oriented(portrait, frame, click)
    assert not isinstance(mapped, RejectedSelection) and mapped.point == Point.make(10, 100)
    assert isinstance(
        geometry.sequence_point_to_oriented(portrait, frame, Point.make(100, 100)),
        RejectedSelection,
    )
    assert isinstance(
        geometry.validate_point(OrientedGrid(10, 10), Point.make(10, 0)), RejectedSelection
    )
    assert isinstance(
        geometry.validate_box(OrientedGrid(10, 10), Box.make(5, 5, 11, 6)), RejectedSelection
    )
    box = geometry.sequence_box_to_oriented(
        portrait, frame, Box(click.x, click.y, click.x + 5 * scale, click.y + 5 * scale)
    )
    assert not isinstance(box, RejectedSelection) and box.box == Box.make(10, 100, 15, 105)
    with pytest.raises(ContractError, match="invertible"):
        geometry.Affine2D.make(0, 0, 0, 0, 0, 0)


@settings(max_examples=200, deadline=None)
@given(
    rotation=st.sampled_from(list(Rotation)),
    sar=st.sampled_from([F(1), F(4, 3), F(16, 15), F(8, 9)]),
    x=st.integers(0, 1919),
    y=st.integers(0, 1079),
)
def test_affines_invert_exactly(rotation: Rotation, sar: F, x: int, y: int) -> None:
    stream = _video(rotation=rotation, sar=sar)
    affine = geometry.display_affine(stream, ProfileFrame(1280, 720))
    forward = affine.apply(F(x), F(y))
    back = affine.inverse().apply(*forward)
    assert back == (F(x), F(y))
    w, h = geometry.oriented_size(stream)
    corner = geometry.source_to_oriented(stream).apply(F(stream.width), F(stream.height))
    assert max(abs(corner[0]), abs(corner[1])) <= max(w, h)
