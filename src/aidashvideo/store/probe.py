"""Probe receipts from ``ffprobe`` (pure parsing plus one thin subprocess runner).

``receipt_from_ffprobe`` turns ``ffprobe -show_streams -show_format`` JSON and, per video
stream, ``-show_frames`` JSON into a :class:`ProbeReceipt` with exact rationals. The
decoded timestamps decide ``ConstantRate`` versus ``VfrTable``; the nominal ``r_frame_rate``
is never trusted over observed frame spacing. The tool identity (name, version, binary
hash) is recorded in every receipt: the sandbox's FFmpeg is not the frozen 9.0.2 and says so.
"""

from __future__ import annotations

import hashlib
import itertools
import re
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from aidashvideo.ledger.canonical import as_list, as_object, parse_json
from aidashvideo.ledger.errors import ContractError
from aidashvideo.ledger.ids import Sha256

from .identity import (
    AudioStream,
    ColorTags,
    ConstantRate,
    FrameTiming,
    Hdr,
    HdrTransfer,
    ProbeReceipt,
    Rotation,
    Sdr709,
    StreamProbe,
    ToolIdentity,
    Untagged,
    VfrTable,
    VideoStream,
)

_TIMEOUT_S = 600


@dataclass(frozen=True, slots=True)
class ProbeFailed:
    reason: str
    tool_exit: int


@dataclass(frozen=True, slots=True)
class ProbeToolMissing:
    detail: str


type ProbeOutcome = ProbeReceipt | ProbeFailed | ProbeToolMissing


# ----------------------------------------------------------------------------- parsing


def _fraction_field(data: dict[str, object], key: str, what: str) -> Fraction:
    raw = data.get(key)
    if isinstance(raw, bool) or raw is None:
        raise ContractError(f"{what}: missing {key}")
    if isinstance(raw, int):
        return Fraction(raw)
    if isinstance(raw, float):
        raise ContractError(f"{what}: {key} must be exact text, not a float")
    if not isinstance(raw, str):
        raise ContractError(f"{what}: {key} has type {type(raw).__name__}")
    text = raw.strip()
    if "/" in text:
        num, den = text.split("/", 1)
        if not re.fullmatch(r"-?\d+", num) or not re.fullmatch(r"\d+", den) or int(den) == 0:
            raise ContractError(f"{what}: malformed ratio {raw!r} in {key}")
        return Fraction(int(num), int(den))
    if ":" in text:
        num, den = text.split(":", 1)
        if not re.fullmatch(r"\d+", num) or not re.fullmatch(r"\d+", den) or int(den) == 0:
            raise ContractError(f"{what}: malformed ratio {raw!r} in {key}")
        return Fraction(int(num), int(den))
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        raise ContractError(f"{what}: malformed decimal {raw!r} in {key}")
    return Fraction(text)


def _int_field(data: dict[str, object], key: str, what: str) -> int:
    raw = data.get(key)
    if isinstance(raw, bool) or raw is None:
        raise ContractError(f"{what}: missing {key}")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and re.fullmatch(r"-?\d+", raw.strip()):
        return int(raw)
    raise ContractError(f"{what}: {key} is not an integer: {raw!r}")


def _str_field(data: dict[str, object], key: str, what: str) -> str:
    raw = data.get(key)
    if not isinstance(raw, str) or not raw:
        raise ContractError(f"{what}: missing {key}")
    return raw


def _start_time(stream: dict[str, object], timebase: Fraction, what: str) -> Fraction:
    if "start_pts" in stream and stream["start_pts"] not in (None, "N/A"):
        return _int_field(stream, "start_pts", what) * timebase
    if "start_time" in stream and stream["start_time"] not in (None, "N/A"):
        return _fraction_field(stream, "start_time", what)
    return Fraction(0)


def _rotation(stream: dict[str, object]) -> Rotation:
    if "side_data_list" in stream:
        for entry in as_list(stream["side_data_list"], "side_data_list"):
            item = as_object(entry, "side_data")
            if item.get("side_data_type") == "Display Matrix" and "rotation" in item:
                raw = item["rotation"]
                if isinstance(raw, int | float) and not isinstance(raw, bool):
                    # ffprobe reports the matrix angle; display rotation is its negation
                    return Rotation.from_degrees(round(-float(raw)) % 360)
    if "tags" in stream:
        rotate = as_object(stream["tags"], "tags").get("rotate")
        if isinstance(rotate, str) and re.fullmatch(r"-?\d+", rotate):
            return Rotation.from_degrees(int(rotate) % 360)
    return Rotation.R0


def _color(stream: dict[str, object]) -> ColorTags:
    transfer = stream.get("color_transfer")
    primaries = stream.get("color_primaries")
    if transfer == "smpte2084":
        return Hdr(HdrTransfer.PQ, str(primaries or "bt2020"))
    if transfer == "arib-std-b67":
        return Hdr(HdrTransfer.HLG, str(primaries or "bt2020"))
    if transfer == "bt709":
        return Sdr709()
    return Untagged()


def frame_pts_from_ffprobe(
    frames_json: object, timebase: Fraction, start_time: Fraction
) -> tuple[Fraction, ...]:
    """Decoded presentation timestamps in seconds with the stream start subtracted once."""
    data = as_object(frames_json, "frames")
    frames = as_list(data.get("frames", []), "frames")
    out: list[Fraction] = []
    for index, raw in enumerate(frames):
        frame = as_object(raw, f"frames[{index}]")
        key = (
            "pts"
            if "pts" in frame and frame["pts"] not in (None, "N/A")
            else "best_effort_timestamp"
        )
        if key not in frame or frame[key] in (None, "N/A"):
            continue
        out.append(_int_field(frame, key, f"frames[{index}]") * timebase - start_time)
    return tuple(out)


def frame_timing_from_pts(
    pts: tuple[Fraction, ...], nominal_fps: Fraction
) -> tuple[FrameTiming, Fraction]:
    """Observed spacing decides: equal deltas are ``ConstantRate`` (fps = 1/delta), else a table."""
    if len(pts) < 2:
        return ConstantRate(), nominal_fps
    deltas = {b - a for a, b in itertools.pairwise(pts)}
    if len(deltas) == 1:
        delta = next(iter(deltas))
        if delta <= 0:
            raise ContractError("frame timestamps are not increasing")
        return ConstantRate(), 1 / delta
    return VfrTable(pts), nominal_fps


def receipt_from_ffprobe(
    probe_json: object,
    frames_by_stream: dict[int, object],
    tool: ToolIdentity,
) -> ProbeReceipt:
    """Build a receipt from parsed ffprobe JSON; raises ``ContractError`` on malformed input."""
    data = as_object(probe_json, "ffprobe")
    fmt = as_object(data.get("format", {}), "format")
    duration = _fraction_field(fmt, "duration", "format")
    streams: list[StreamProbe] = []
    for raw in as_list(data.get("streams", []), "streams"):
        stream = as_object(raw, "stream")
        kind = stream.get("codec_type")
        index = _int_field(stream, "index", "stream")
        what = f"stream[{index}]"
        if kind == "video":
            timebase = _fraction_field(stream, "time_base", what)
            start = _start_time(stream, timebase, what)
            nominal = _fraction_field(stream, "r_frame_rate", what)
            if nominal <= 0:
                nominal = _fraction_field(stream, "avg_frame_rate", what)
            sar = (
                _fraction_field(stream, "sample_aspect_ratio", what)
                if stream.get("sample_aspect_ratio") not in (None, "N/A", "0:1")
                else Fraction(1)
            )
            if index in frames_by_stream:
                pts = frame_pts_from_ffprobe(frames_by_stream[index], timebase, start)
                timing, fps = frame_timing_from_pts(pts, nominal)
            else:
                timing, fps = ConstantRate(), nominal
            has_bframes = (
                _int_field(stream, "has_b_frames", what) > 0 if "has_b_frames" in stream else False
            )
            streams.append(
                VideoStream(
                    index,
                    _str_field(stream, "codec_name", what),
                    _int_field(stream, "width", what),
                    _int_field(stream, "height", what),
                    sar,
                    fps,
                    timebase,
                    start,
                    _rotation(stream),
                    _color(stream),
                    timing,
                    has_bframes,
                )
            )
        elif kind == "audio":
            timebase = _fraction_field(stream, "time_base", what)
            streams.append(
                AudioStream(
                    index,
                    _str_field(stream, "codec_name", what),
                    _int_field(stream, "sample_rate", what),
                    _int_field(stream, "channels", what),
                    str(stream.get("channel_layout", "")),
                    timebase,
                    _start_time(stream, timebase, what),
                )
            )
        # data/subtitle/attachment streams are not editing inputs and are left out
    return ProbeReceipt.make(tool, tuple(streams), duration)


# ----------------------------------------------------------------------------- runner


class FfprobeProber:
    """Runs the located ``ffprobe`` with ``shell=False`` argv from typed fields."""

    def __init__(self, ffprobe: Path) -> None:
        self.ffprobe = ffprobe
        self._identity: ToolIdentity | None = None

    def identity(self) -> ToolIdentity:
        if self._identity is None:
            out = subprocess.run(
                [str(self.ffprobe), "-version"],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
                stdin=subprocess.DEVNULL,
            ).stdout
            match = re.match(r"ffprobe version (\S+)", out)
            version = match.group(1) if match else "unknown"
            digest = hashlib.sha256(self.ffprobe.read_bytes()).hexdigest()
            self._identity = ToolIdentity("ffprobe", version, Sha256(digest))
        return self._identity

    def probe(self, path: Path) -> ProbeOutcome:
        base = [str(self.ffprobe), "-v", "error", "-print_format", "json"]
        try:
            tool = self.identity()
            streams = subprocess.run(
                [*base, "-show_format", "-show_streams", str(path)],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_S,
                check=False,
                stdin=subprocess.DEVNULL,
            )
            if streams.returncode != 0:
                return ProbeFailed(streams.stderr.strip()[-2000:], streams.returncode)
            probe_json = parse_json(streams.stdout.encode("utf-8"))
            frames_by_stream: dict[int, object] = {}
            for raw in as_list(as_object(probe_json, "ffprobe").get("streams", []), "streams"):
                stream = as_object(raw, "stream")
                if stream.get("codec_type") != "video":
                    continue
                index = _int_field(stream, "index", "stream")
                frames = subprocess.run(
                    [
                        *base,
                        "-select_streams",
                        str(index),
                        "-show_entries",
                        "frame=pts,best_effort_timestamp",
                        "-show_frames",
                        str(path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=_TIMEOUT_S,
                    check=False,
                    stdin=subprocess.DEVNULL,
                )
                if frames.returncode != 0:
                    return ProbeFailed(frames.stderr.strip()[-2000:], frames.returncode)
                frames_by_stream[index] = parse_json(frames.stdout.encode("utf-8"))
            return receipt_from_ffprobe(probe_json, frames_by_stream, tool)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ProbeFailed(str(exc), -1)
        except ContractError as exc:
            return ProbeFailed(f"unparseable ffprobe output: {exc}", 0)


def locate_prober() -> FfprobeProber | ProbeToolMissing:
    """Resolve ffprobe through the catalog (explicit override, pinned install, then PATH)."""
    from aidashvideo.catalog import ffmpeg as ffmpeg_catalog

    tools = ffmpeg_catalog.locate()
    if tools is None:
        return ProbeToolMissing(
            "ffprobe not found (AIDASHVIDEO_FFPROBE, the frozen toolchain or PATH); "
            "install per docs/plan/commands.md section 6"
        )
    return FfprobeProber(tools.ffprobe)
