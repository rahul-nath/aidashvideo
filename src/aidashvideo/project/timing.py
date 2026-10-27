"""Sole owner of source/sequence/audio time mapping and retiming maps (contracts §4, I4).

Three domains, never mixed implicitly:

* **source**: seconds in a stream's own timebase after its ``start_time`` was subtracted
  once at probe time (:class:`SourceTime`, :class:`SourceSpan` = ``[in, out)``);
* **sequence**: frame indices at ``OutputProfile.fps`` (:class:`SequenceFrame`,
  :class:`SequenceSpan` = ``[start, end)``; ``[0, 30)`` holds 30 frames, never 31);
* **audio**: sample indices at 48 000 Hz (:class:`SampleIndex`, :class:`SampleSpan`).

All values are exact ``Fraction``s; no float enters a span. Constant positive speed ``s``
maps ``source_time = source_in + s * (timeline_time - clip_start)``; a :class:`TimeMap`
(reverse, hold, variable - only modes the catalog declares) is a finite ordered list of
``(frame offset, source instant)`` points with declared interpolation whose segment lengths
are positive by construction, so holds never divide by zero. MLT's inclusive ``out`` is
**not** produced here (compiler only, M2).
"""

from __future__ import annotations

import bisect
import itertools
import math
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from aidashvideo.ledger.canonical import (
    as_int,
    as_list,
    as_object,
    as_str,
    field,
    rational_from_json,
    rational_to_json,
    require_keys,
)
from aidashvideo.ledger.errors import ContractError, is_int, widen
from aidashvideo.store.identity import AudioStream, ConstantRate, VfrTable, VideoStream

AUDIO_SAMPLE_RATE = 48_000


def _fraction(value: object, what: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, Fraction | int):
        raise ContractError(
            f"{what} must be an exact rational (Fraction), got {type(value).__name__}"
        )
    return Fraction(value)


# ----------------------------------------------------------------------------- instants


@dataclass(frozen=True, slots=True)
class SourceTime:
    seconds: Fraction

    def __post_init__(self) -> None:
        if not isinstance(widen(self.seconds), Fraction):
            raise ContractError("SourceTime.seconds must be a Fraction")
        if self.seconds < 0:
            raise ContractError(f"SourceTime must be >= 0, got {self.seconds}")

    @classmethod
    def make(cls, seconds: Fraction | int) -> SourceTime:
        return cls(_fraction(seconds, "SourceTime"))

    def to_json(self) -> str:
        return rational_to_json(self.seconds)

    @classmethod
    def from_json(cls, raw: object) -> SourceTime:
        return cls(rational_from_json(raw, "SourceTime"))


@dataclass(frozen=True, slots=True)
class SequenceFrame:
    index: int

    def __post_init__(self) -> None:
        if not is_int(self.index) or self.index < 0:
            raise ContractError(f"SequenceFrame must be a non-negative integer, got {self.index!r}")

    @classmethod
    def make(cls, index: int) -> SequenceFrame:
        return cls(index)

    def to_json(self) -> int:
        return self.index

    @classmethod
    def from_json(cls, raw: object) -> SequenceFrame:
        return cls(as_int(raw, "SequenceFrame"))


@dataclass(frozen=True, slots=True)
class SampleIndex:
    index: int

    def __post_init__(self) -> None:
        if not is_int(self.index) or self.index < 0:
            raise ContractError("SampleIndex must be a non-negative integer")


# ----------------------------------------------------------------------------- spans


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """``[in, out)`` in source seconds; finite and non-empty."""

    in_: SourceTime
    out: SourceTime

    def __post_init__(self) -> None:
        if not isinstance(widen(self.in_), SourceTime) or not isinstance(
            widen(self.out), SourceTime
        ):
            raise ContractError("SourceSpan bounds must be SourceTime")
        if self.out.seconds <= self.in_.seconds:
            raise ContractError(
                f"SourceSpan must satisfy in < out, got [{self.in_.seconds}, {self.out.seconds})"
            )

    @classmethod
    def make(cls, in_: Fraction | int, out: Fraction | int) -> SourceSpan:
        return cls(SourceTime.make(in_), SourceTime.make(out))

    @property
    def duration(self) -> Fraction:
        return self.out.seconds - self.in_.seconds

    def contains(self, t: SourceTime) -> bool:
        return self.in_.seconds <= t.seconds < self.out.seconds

    def covers(self, other: SourceSpan) -> bool:
        return self.in_.seconds <= other.in_.seconds and other.out.seconds <= self.out.seconds

    def overlaps(self, other: SourceSpan) -> bool:
        return self.in_.seconds < other.out.seconds and other.in_.seconds < self.out.seconds

    def to_json(self) -> dict[str, object]:
        return {"in": self.in_.to_json(), "out": self.out.to_json()}

    @classmethod
    def from_json(cls, raw: object) -> SourceSpan:
        data = as_object(raw, "SourceSpan")
        require_keys(data, "SourceSpan", ("in", "out"))
        return cls(SourceTime.from_json(data["in"]), SourceTime.from_json(data["out"]))


@dataclass(frozen=True, slots=True)
class SequenceSpan:
    """``[start, end)`` in sequence frames; finite and non-empty."""

    start: SequenceFrame
    end: SequenceFrame

    def __post_init__(self) -> None:
        if not isinstance(widen(self.start), SequenceFrame) or not isinstance(
            widen(self.end), SequenceFrame
        ):
            raise ContractError("SequenceSpan bounds must be SequenceFrame")
        if self.end.index <= self.start.index:
            raise ContractError(
                f"SequenceSpan must satisfy start < end, got [{self.start.index}, {self.end.index})"
            )

    @classmethod
    def make(cls, start: int, end: int) -> SequenceSpan:
        return cls(SequenceFrame(start), SequenceFrame(end))

    @property
    def frames(self) -> int:
        """Number of frames: ``[0, 30)`` contains 30."""
        return self.end.index - self.start.index

    def contains(self, frame: SequenceFrame) -> bool:
        return self.start.index <= frame.index < self.end.index

    def overlaps(self, other: SequenceSpan) -> bool:
        return self.start.index < other.end.index and other.start.index < self.end.index

    def shifted(self, delta_frames: int) -> SequenceSpan | NegativeStart:
        if not is_int(delta_frames):
            raise ContractError("shift delta must be an integer number of frames")
        new_start = self.start.index + delta_frames
        if new_start < 0:
            return NegativeStart(new_start)
        return SequenceSpan.make(new_start, self.end.index + delta_frames)

    def to_json(self) -> dict[str, object]:
        return {"start": self.start.to_json(), "end": self.end.to_json()}

    @classmethod
    def from_json(cls, raw: object) -> SequenceSpan:
        data = as_object(raw, "SequenceSpan")
        require_keys(data, "SequenceSpan", ("start", "end"))
        return cls(SequenceFrame.from_json(data["start"]), SequenceFrame.from_json(data["end"]))


@dataclass(frozen=True, slots=True)
class NegativeStart:
    """A shift would move a start before frame 0 (contracts §4: fails atomically)."""

    would_be_start: int


@dataclass(frozen=True, slots=True)
class SampleSpan:
    s0: SampleIndex
    s1: SampleIndex

    def __post_init__(self) -> None:
        if self.s1.index <= self.s0.index:
            raise ContractError("SampleSpan must satisfy s0 < s1")

    @property
    def samples(self) -> int:
        return self.s1.index - self.s0.index


# ----------------------------------------------------------------------------- timing kinds


@dataclass(frozen=True, slots=True)
class Normal:
    """``s = 1``."""

    def to_json(self) -> dict[str, object]:
        return {"kind": "Normal"}

    @property
    def ratio(self) -> Fraction:
        return Fraction(1)


@dataclass(frozen=True, slots=True)
class Constant:
    ratio: Fraction

    def __post_init__(self) -> None:
        if not isinstance(widen(self.ratio), Fraction) or self.ratio <= 0:
            raise ContractError(
                f"Constant speed ratio must be a positive rational, got {self.ratio!r}"
            )

    @classmethod
    def make(cls, ratio: Fraction | int) -> Constant:
        return cls(_fraction(ratio, "Constant.ratio"))

    def to_json(self) -> dict[str, object]:
        return {"kind": "Constant", "ratio": rational_to_json(self.ratio)}


type Speed = Normal | Constant


class Interpolation(StrEnum):
    HOLD = "Hold"
    LINEAR = "Linear"


class RetimeMode(StrEnum):
    REVERSE = "Reverse"
    HOLD = "Hold"
    VARIABLE = "Variable"


@dataclass(frozen=True, slots=True)
class TimeMapPoint:
    frame: int
    """Offset in frames from the placement start (so moves never invalidate a map)."""

    source: SourceTime

    def __post_init__(self) -> None:
        if not is_int(self.frame) or self.frame < 0:
            raise ContractError("TimeMapPoint.frame must be a non-negative integer offset")
        if not isinstance(widen(self.source), SourceTime):
            raise ContractError("TimeMapPoint.source must be a SourceTime")

    def to_json(self) -> dict[str, object]:
        return {"frame": self.frame, "source": self.source.to_json()}


@dataclass(frozen=True, slots=True)
class TimeMap:
    """Finite ordered timeline-to-source map; ``points[0].frame == 0`` and the last point's
    frame is the placement duration (exclusive end). Segment lengths are therefore >= 1:
    ``Hold`` segments repeat an instant without any division."""

    points: tuple[TimeMapPoint, ...]
    interpolation: Interpolation
    mode: RetimeMode

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ContractError("TimeMap needs at least two points (start and exclusive end)")
        if self.points[0].frame != 0:
            raise ContractError("TimeMap must start at frame offset 0")
        for index, (a, b) in enumerate(itertools.pairwise(self.points)):
            if b.frame <= a.frame:
                raise ContractError(f"TimeMap frames must strictly increase at point {index + 1}")
        if not isinstance(widen(self.interpolation), Interpolation):
            raise ContractError("TimeMap.interpolation must be an Interpolation")
        if not isinstance(widen(self.mode), RetimeMode):
            raise ContractError("TimeMap.mode must be a RetimeMode")
        sources = [p.source.seconds for p in self.points]
        steps = [b - a for a, b in itertools.pairwise(sources)]
        if self.mode is RetimeMode.REVERSE and (
            any(s > 0 for s in steps) or not any(s < 0 for s in steps)
        ):
            raise ContractError("Reverse TimeMap must be non-increasing with a decrease")
        if self.mode is RetimeMode.HOLD and (
            any(s < 0 for s in steps) or not any(s == 0 for s in steps)
        ):
            raise ContractError("Hold TimeMap must be non-decreasing with a held segment")

    @classmethod
    def make(
        cls,
        points: tuple[tuple[int, Fraction | int], ...],
        interpolation: Interpolation,
        mode: RetimeMode,
    ) -> TimeMap:
        return cls(
            tuple(TimeMapPoint(f, SourceTime.make(s)) for f, s in points), interpolation, mode
        )

    @property
    def duration_frames(self) -> int:
        return self.points[-1].frame

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "TimeMap",
            "points": [p.to_json() for p in self.points],
            "interpolation": self.interpolation.value,
            "mode": self.mode.value,
        }

    def segment_samples(self) -> tuple[tuple[int, int, SourceTime, SourceTime], ...]:
        """Per segment ``(first_offset, last_offset, source_at_first, source_at_last)``."""
        out: list[tuple[int, int, SourceTime, SourceTime]] = []
        for a, b in itertools.pairwise(self.points):
            first, last = a.frame, b.frame - 1
            out.append((first, last, self.source_at_offset(first), self.source_at_offset(last)))
        return tuple(out)

    def source_at_offset(self, offset: int) -> SourceTime:
        if not 0 <= offset < self.duration_frames:
            raise ContractError(f"offset {offset} outside [0, {self.duration_frames})")
        index = bisect.bisect_right([p.frame for p in self.points], offset) - 1
        a, b = self.points[index], self.points[index + 1]
        if self.interpolation is Interpolation.HOLD or a.source == b.source:
            return a.source
        span = b.frame - a.frame  # >= 1 by construction: no division by zero
        value = a.source.seconds + (b.source.seconds - a.source.seconds) * Fraction(
            offset - a.frame, span
        )
        return SourceTime(value)


type Timing = Speed | TimeMap


def timing_to_json(timing: Timing) -> dict[str, object]:
    return timing.to_json()


def timing_from_json(raw: object) -> Timing:
    data = as_object(raw, "timing")
    kind = as_str(field(data, "kind", "timing"), "timing.kind")
    if kind == "Normal":
        require_keys(data, "timing", ("kind",))
        return Normal()
    if kind == "Constant":
        require_keys(data, "timing", ("kind", "ratio"))
        return Constant(rational_from_json(data["ratio"], "Constant.ratio"))
    if kind == "TimeMap":
        require_keys(data, "timing", ("kind", "points", "interpolation", "mode"))
        points: list[TimeMapPoint] = []
        for raw_point in as_list(data["points"], "TimeMap.points"):
            p = as_object(raw_point, "TimeMapPoint")
            require_keys(p, "TimeMapPoint", ("frame", "source"))
            points.append(
                TimeMapPoint(as_int(p["frame"], "frame"), SourceTime.from_json(p["source"]))
            )
        try:
            interpolation = Interpolation(as_str(data["interpolation"], "interpolation"))
            mode = RetimeMode(as_str(data["mode"], "mode"))
        except ValueError as exc:
            raise ContractError(f"TimeMap: {exc}") from exc
        return TimeMap(tuple(points), interpolation, mode)
    raise ContractError(f"timing: unknown kind {kind!r}")


# ----------------------------------------------------------------------------- placement


@dataclass(frozen=True, slots=True)
class Placement:
    """The timing-relevant part of a clip occurrence."""

    source: SourceSpan
    place: SequenceSpan
    timing: Timing

    def __post_init__(self) -> None:
        if isinstance(self.timing, TimeMap) and self.timing.duration_frames != self.place.frames:
            raise ContractError(
                f"TimeMap covers {self.timing.duration_frames} frames but the placement has "
                f"{self.place.frames}"
            )


@dataclass(frozen=True, slots=True)
class OutsidePlacedRange:
    """A time or span that is not inside the placement (never clamped)."""

    detail: str


@dataclass(frozen=True, slots=True)
class Mapped:
    source: SourceTime


def timeline_time(frame: SequenceFrame, fps: Fraction) -> Fraction:
    _check_fps(fps)
    return Fraction(frame.index) / fps


def _check_fps(fps: Fraction) -> None:
    if not isinstance(widen(fps), Fraction) or fps <= 0:
        raise ContractError("fps must be a positive rational")


def duration_frames(source: SourceSpan, timing: Timing, fps: Fraction) -> int:
    """Frames a placement occupies: ``ceil(duration * fps / s)`` for constant speed
    (every frame samples inside ``[in, out)``) or the map's declared length."""
    _check_fps(fps)
    if isinstance(timing, TimeMap):
        return timing.duration_frames
    return math.ceil(source.duration * fps / timing.ratio)


def validate_placement(placement: Placement, fps: Fraction) -> OutsidePlacedRange | None:
    """Every sampled instant must lie inside ``[in, out)`` and the length must be derived."""
    expected = duration_frames(placement.source, placement.timing, fps)
    if placement.place.frames != expected:
        return OutsidePlacedRange(
            f"placement has {placement.place.frames} frames but its source/timing derive {expected}"
        )
    if isinstance(placement.timing, TimeMap):
        for _first, _last, s_first, s_last in placement.timing.segment_samples():
            for instant in (s_first, s_last):
                if not placement.source.contains(instant):
                    return OutsidePlacedRange(
                        f"TimeMap samples source {instant.seconds} outside "
                        f"[{placement.source.in_.seconds}, {placement.source.out.seconds})"
                    )
    return None


def source_time_at(
    placement: Placement, frame: SequenceFrame, fps: Fraction
) -> Mapped | OutsidePlacedRange:
    """``source_in + s * (timeline_time - clip_start)`` or the map's instant."""
    _check_fps(fps)
    if not placement.place.contains(frame):
        return OutsidePlacedRange(f"frame {frame.index} is outside {placement.place.to_json()}")
    offset = frame.index - placement.place.start.index
    if isinstance(placement.timing, TimeMap):
        return Mapped(placement.timing.source_at_offset(offset))
    s = placement.timing.ratio
    value = placement.source.in_.seconds + s * Fraction(offset) / fps
    if value >= placement.source.out.seconds:
        return OutsidePlacedRange(f"frame {frame.index} samples past the source out point")
    return Mapped(SourceTime(value))


def frame_for_source_time(
    placement: Placement, t: SourceTime, fps: Fraction
) -> SequenceFrame | OutsidePlacedRange:
    """Constant speed inverse: the frame whose start is at or before the instant:
    ``clip_start_frame + floor((source_time - source_in) * fps / s)``."""
    _check_fps(fps)
    if isinstance(placement.timing, TimeMap):
        frames = frames_for_source_time(placement, t, fps)
        if not frames:
            return OutsidePlacedRange(f"source {t.seconds} is not sampled by the map")
        return frames[0]
    if not placement.source.contains(t):
        return OutsidePlacedRange(
            f"source {t.seconds} is outside [{placement.source.in_.seconds},"
            f" {placement.source.out.seconds})"
        )
    s = placement.timing.ratio
    offset = math.floor((t.seconds - placement.source.in_.seconds) * fps / s)
    frame = SequenceFrame(placement.place.start.index + offset)
    if not placement.place.contains(frame):
        return OutsidePlacedRange(f"source {t.seconds} maps past the placement end")
    return frame


def frames_for_source_time(
    placement: Placement, t: SourceTime, fps: Fraction
) -> tuple[SequenceFrame, ...]:
    """Every frame that samples exactly ``t`` (several for holds or repeated passages)."""
    _check_fps(fps)
    if not isinstance(placement.timing, TimeMap):
        found = frame_for_source_time(placement, t, fps)
        if isinstance(found, OutsidePlacedRange):
            return ()
        mapped = source_time_at(placement, found, fps)
        return (found,) if isinstance(mapped, Mapped) and mapped.source == t else ()
    start = placement.place.start.index
    out: list[SequenceFrame] = []
    for a, b in itertools.pairwise(placement.timing.points):
        first, last = a.frame, b.frame - 1
        if placement.timing.interpolation is Interpolation.HOLD or a.source == b.source:
            if a.source == t:
                out.extend(SequenceFrame(start + o) for o in range(first, last + 1))
            continue
        slope = (b.source.seconds - a.source.seconds) / (b.frame - a.frame)
        offset = (t.seconds - a.source.seconds) / slope
        if offset.denominator == 1 and first <= a.frame + offset.numerator <= last:
            out.append(SequenceFrame(start + a.frame + offset.numerator))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class PlacedRun:
    frames: SequenceSpan
    first_source: SourceTime
    last_source: SourceTime


@dataclass(frozen=True, slots=True)
class PlacedSpan:
    """Requested versus realizable boundaries (a boundary between frames realizes at the
    frame start; the error is bounded by one frame)."""

    requested: SourceSpan
    runs: tuple[PlacedRun, ...]


def place_source_span(
    placement: Placement, span: SourceSpan, fps: Fraction
) -> PlacedSpan | OutsidePlacedRange:
    """Sequence frames realizing ``span``; the span must be inside the placement's source
    range (``OutsidePlacedRange`` otherwise, never clamped).

    Constant speed: each boundary realizes at the frame start at or before it (the
    contract's inverse formula), so the error is below one frame per boundary. Maps: the
    frames whose sampled instant lies in the span (holds and reverse passes included)."""
    _check_fps(fps)
    if not placement.source.covers(span):
        return OutsidePlacedRange(
            f"[{span.in_.seconds}, {span.out.seconds}) is not inside "
            f"[{placement.source.in_.seconds}, {placement.source.out.seconds})"
        )
    start = placement.place.start.index
    offsets: list[int] = []
    if isinstance(placement.timing, TimeMap):
        for a, b in itertools.pairwise(placement.timing.points):
            first, last = a.frame, b.frame - 1
            if placement.timing.interpolation is Interpolation.HOLD or a.source == b.source:
                if span.contains(a.source):
                    offsets.extend(range(first, last + 1))
                continue
            slope = (b.source.seconds - a.source.seconds) / (b.frame - a.frame)
            if slope > 0:
                lo = math.ceil((span.in_.seconds - a.source.seconds) / slope)
                hi = math.ceil((span.out.seconds - a.source.seconds) / slope) - 1
            else:
                lo = math.floor((a.source.seconds - span.out.seconds) / -slope) + 1
                hi = math.floor((a.source.seconds - span.in_.seconds) / -slope)
            lo, hi = max(lo, 0), min(hi, last - first)
            offsets.extend(range(first + lo, first + hi + 1))
    else:
        # constant speed: each boundary realizes at the start of the frame whose start is at
        # or before it (the contract's inverse formula); at least one frame is produced
        s = placement.timing.ratio
        lo = math.floor((span.in_.seconds - placement.source.in_.seconds) * fps / s)
        hi = math.floor((span.out.seconds - placement.source.in_.seconds) * fps / s)
        hi = min(max(hi, lo + 1), placement.place.frames)
        offsets.extend(range(lo, hi))
    runs: list[PlacedRun] = []
    for run_start, run_end in _runs(sorted(set(offsets))):
        first = source_time_at(placement, SequenceFrame(start + run_start), fps)
        last = source_time_at(placement, SequenceFrame(start + run_end - 1), fps)
        if not isinstance(first, Mapped) or not isinstance(last, Mapped):
            raise ContractError("placed run maps outside its own placement")
        runs.append(
            PlacedRun(
                SequenceSpan.make(start + run_start, start + run_end), first.source, last.source
            )
        )
    return PlacedSpan(span, tuple(runs))


def _runs(offsets: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for o in offsets:
        if out and out[-1][1] == o:
            out[-1] = (out[-1][0], o + 1)
        else:
            out.append((o, o + 1))
    return out


def realized_source_span(
    placement: Placement, frames: SequenceSpan, fps: Fraction
) -> SourceSpan | OutsidePlacedRange:
    """For constant speed: the exact source interval those frames cover, ``[t(start), t(end))``."""
    _check_fps(fps)
    if isinstance(placement.timing, TimeMap):
        return OutsidePlacedRange("a TimeMap run has no single realized interval; use its runs")
    if not placement.place.contains(frames.start) or frames.end.index > placement.place.end.index:
        return OutsidePlacedRange("frames are not inside the placement")
    s = placement.timing.ratio
    base = placement.source.in_.seconds
    start_offset = frames.start.index - placement.place.start.index
    end_offset = frames.end.index - placement.place.start.index
    begin = base + s * Fraction(start_offset) / fps
    end = min(base + s * Fraction(end_offset) / fps, placement.source.out.seconds)
    return SourceSpan(SourceTime(begin), SourceTime(end))


def sampled_instants(placement: Placement, fps: Fraction) -> tuple[SourceTime, ...]:
    """Every source instant the placement samples, in sequence order (repeats preserved)."""
    out: list[SourceTime] = []
    for index in range(placement.place.start.index, placement.place.end.index):
        mapped = source_time_at(placement, SequenceFrame(index), fps)
        if not isinstance(mapped, Mapped):
            raise ContractError("placement samples outside its own range")
        out.append(mapped.source)
    return tuple(out)


def merge_spans(spans: tuple[SourceSpan, ...]) -> tuple[SourceSpan, ...]:
    """Union as disjoint, sorted half-open intervals (adjacent intervals are joined)."""
    merged: list[SourceSpan] = []
    for span in sorted(spans, key=lambda x: x.in_.seconds):
        if merged and span.in_.seconds <= merged[-1].out.seconds:
            last = merged[-1]
            merged[-1] = SourceSpan(last.in_, SourceTime(max(last.out.seconds, span.out.seconds)))
        else:
            merged.append(span)
    return tuple(merged)


def coverage_missing(
    placement: Placement, covered: tuple[SourceSpan, ...], fps: Fraction
) -> tuple[SourceSpan, ...]:
    """Source intervals the placement samples that no covered span contains (``Pending``
    coverage after a cut is undone, for example). Exact: interval subtraction for constant
    speed; for maps every sampled instant is checked and reported as a one-frame-step
    interval clipped to the source range."""
    _check_fps(fps)
    if not isinstance(placement.timing, TimeMap):
        return subtract_spans(placement.source, covered)
    step = Fraction(1) / fps
    missing: list[SourceSpan] = []
    for instant in sampled_instants(placement, fps):
        if any(c.contains(instant) for c in covered):
            continue
        end = min(instant.seconds + step, placement.source.out.seconds)
        missing.append(SourceSpan(instant, SourceTime(end)))
    return merge_spans(tuple(missing))


def subtract_spans(span: SourceSpan, covered: tuple[SourceSpan, ...]) -> tuple[SourceSpan, ...]:
    """``span`` minus the union of ``covered`` as disjoint half-open intervals."""
    remaining: list[tuple[Fraction, Fraction]] = [(span.in_.seconds, span.out.seconds)]
    for c in sorted(covered, key=lambda x: x.in_.seconds):
        next_remaining: list[tuple[Fraction, Fraction]] = []
        for lo, hi in remaining:
            if c.out.seconds <= lo or c.in_.seconds >= hi:
                next_remaining.append((lo, hi))
                continue
            if c.in_.seconds > lo:
                next_remaining.append((lo, c.in_.seconds))
            if c.out.seconds < hi:
                next_remaining.append((c.out.seconds, hi))
        remaining = next_remaining
    return tuple(SourceSpan(SourceTime(lo), SourceTime(hi)) for lo, hi in remaining)


# ----------------------------------------------------------------------------- seconds <-> frames


@dataclass(frozen=True, slots=True)
class RealizedFrames:
    """Requested seconds versus the realizable whole frames at ``fps``."""

    requested_seconds: Fraction
    frames: int
    realized_seconds: Fraction

    @property
    def exact(self) -> bool:
        return self.requested_seconds == self.realized_seconds


def frames_floor(seconds: Fraction, fps: Fraction) -> RealizedFrames:
    """A boundary between frames realizes at the frame start (floor toward -inf)."""
    _check_fps(fps)
    frames = math.floor(seconds * fps)
    return RealizedFrames(seconds, frames, Fraction(frames) / fps)


def frames_nearest(seconds: Fraction, fps: Fraction) -> RealizedFrames:
    """A delta (such as "half a second earlier") realizes at the nearest whole frame;
    exact halves round away from zero."""
    _check_fps(fps)
    exact = seconds * fps
    magnitude = math.floor(abs(exact) + Fraction(1, 2))
    frames = magnitude if exact >= 0 else -magnitude
    return RealizedFrames(seconds, frames, Fraction(frames) / fps)


# ----------------------------------------------------------------------------- audio


def sample_for_frame(
    frame: SequenceFrame, fps: Fraction, sample_rate: int = AUDIO_SAMPLE_RATE
) -> SampleIndex:
    """``sample(n) = floor(n * 48000 / fps)``."""
    _check_fps(fps)
    if not is_int(sample_rate) or sample_rate < 1:
        raise ContractError("sample_rate must be a positive integer")
    return SampleIndex(math.floor(Fraction(frame.index) * sample_rate / fps))


def sample_span_for_frames(
    span: SequenceSpan, fps: Fraction, sample_rate: int = AUDIO_SAMPLE_RATE
) -> SampleSpan:
    return SampleSpan(
        sample_for_frame(span.start, fps, sample_rate), sample_for_frame(span.end, fps, sample_rate)
    )


def stream_sample_for_source_time(stream: AudioStream, t: SourceTime) -> SampleIndex:
    """Sample index inside the stream (its own rate; the start offset was subtracted at probe)."""
    return SampleIndex(math.floor(t.seconds * stream.sample_rate))


def container_time(stream: VideoStream | AudioStream, t: SourceTime) -> Fraction:
    """Back to the container timeline: the stream's ``start_time`` is applied exactly once here."""
    return t.seconds + stream.start_time


def source_time_from_container(
    stream: VideoStream | AudioStream, container: Fraction
) -> SourceTime | OutsidePlacedRange:
    value = container - stream.start_time
    if value < 0:
        return OutsidePlacedRange(
            f"container time {container} precedes the stream start {stream.start_time}"
        )
    return SourceTime(value)


def align_span(
    span: SourceSpan, from_stream: VideoStream | AudioStream, to_stream: VideoStream | AudioStream
) -> SourceSpan | OutsidePlacedRange:
    """The same container interval expressed in another stream's source domain (A/V sync
    across different stream offsets)."""
    begin = source_time_from_container(to_stream, container_time(from_stream, span.in_))
    end = source_time_from_container(to_stream, container_time(from_stream, span.out))
    if isinstance(begin, OutsidePlacedRange):
        return begin
    if isinstance(end, OutsidePlacedRange):
        return end
    return SourceSpan(begin, end)


# ----------------------------------------------------------------------------- source frames (VFR)


@dataclass(frozen=True, slots=True)
class BeforeFirstFrame:
    t: SourceTime


def source_frame_index(stream: VideoStream, t: SourceTime) -> int | BeforeFirstFrame:
    """Index of the decoded frame presented at ``t``: the last pts at or before ``t``
    (actual timestamps for VFR, ``floor(t * fps)`` for constant rate)."""
    if isinstance(stream.vfr, ConstantRate):
        return math.floor(t.seconds * stream.fps)
    table = stream.vfr
    index = bisect.bisect_right(table.pts, t.seconds) - 1
    if index < 0:
        return BeforeFirstFrame(t)
    return index


def source_frame_pts(stream: VideoStream, index: int) -> SourceTime | OutsidePlacedRange:
    if not is_int(index) or index < 0:
        raise ContractError("frame index must be a non-negative integer")
    if isinstance(stream.vfr, VfrTable):
        if index >= len(stream.vfr.pts):
            return OutsidePlacedRange(
                f"frame {index} beyond the {len(stream.vfr.pts)} decoded frames"
            )
        return SourceTime(stream.vfr.pts[index])
    return SourceTime(Fraction(index) / stream.fps)


def stream_frame_count(stream: VideoStream, container_duration: Fraction) -> int:
    if isinstance(stream.vfr, VfrTable):
        return len(stream.vfr.pts)
    return math.floor((container_duration - stream.start_time) * stream.fps)


# ----------------------------------------------------------------------------- transitions


@dataclass(frozen=True, slots=True)
class HandlesOk:
    pass


@dataclass(frozen=True, slots=True)
class InsufficientHandles:
    detail: str


def transition_handles(
    left: Placement,
    right: Placement,
    duration_frames: int,
    fps: Fraction,
    left_stream_duration: Fraction,
    right_stream_duration: Fraction,
) -> HandlesOk | InsufficientHandles:
    """``L.source.out + d/fps <= L.stream_duration`` and ``R.source.in - d/fps >= 0``."""
    _check_fps(fps)
    if not is_int(duration_frames) or duration_frames < 1:
        return InsufficientHandles("a transition needs at least one frame")
    if left.place.end != right.place.start:
        return InsufficientHandles("left and right occurrences are not adjacent")
    handle = Fraction(duration_frames) / fps
    if left.source.out.seconds + handle > left_stream_duration:
        return InsufficientHandles(
            f"left needs {handle} s after its out point {left.source.out.seconds} s but the "
            f"stream ends at {left_stream_duration} s"
        )
    if right.source.in_.seconds - handle < 0:
        return InsufficientHandles(
            f"right needs {handle} s before its in point {right.source.in_.seconds} s"
        )
    if duration_frames > min(left.place.frames, right.place.frames):
        return InsufficientHandles("transition longer than a neighbour")
    _ = right_stream_duration
    return HandlesOk()
