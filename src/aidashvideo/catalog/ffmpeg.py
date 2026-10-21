"""FFmpeg/ffprobe discovery and readiness probe."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .paths import deps_dir
from .pins import FfmpegPins, load_pins
from .status import ComponentStatus, Readiness

_TIMEOUT_S = 60


@dataclass(frozen=True)
class FfmpegTools:
    ffmpeg: Path
    ffprobe: Path


def locate(pins: FfmpegPins | None = None) -> FfmpegTools | None:
    """Resolve ffmpeg/ffprobe: explicit overrides, then the profile's install, then PATH.

    Never installs. With no ``pins`` the selected profile's install is used.
    """
    if pins is None:
        pins = load_pins().ffmpeg
    pinned = deps_dir() / pins.install if pins.install else None
    if pinned is not None and not pinned.is_file():
        pinned = None
    ffmpeg = (
        os.environ.get("AIDASHVIDEO_FFMPEG")
        or (str(pinned) if pinned else None)
        or shutil.which("ffmpeg")
    )
    ffprobe = (
        os.environ.get("AIDASHVIDEO_FFPROBE")
        or (str(pinned.with_name("ffprobe")) if pinned else None)
        or shutil.which("ffprobe")
    )
    if not ffmpeg or not ffprobe or not Path(ffmpeg).is_file() or not Path(ffprobe).is_file():
        return None
    return FfmpegTools(Path(ffmpeg).resolve(), Path(ffprobe).resolve())


def _run(args: list[str]) -> str:
    out = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        check=True,
        stdin=subprocess.DEVNULL,
    )
    return out.stdout


def parse_version(version_output: str) -> str:
    m = re.match(r"ffmpeg version (\S+)", version_output)
    return m.group(1) if m else ""


def parse_codec_list(listing: str) -> list[str]:
    """Names from ``-encoders``/``-decoders`` (rows after the ``------`` separator)."""
    names: list[str] = []
    seen_sep = False
    for line in listing.splitlines():
        if not seen_sep:
            seen_sep = line.strip().startswith("------")
            continue
        parts = line.split()
        if len(parts) >= 2:
            names.append(parts[1])
    return names


_FILTER_ROW = re.compile(r"^ [T.][S.][C.]? (\S+)\s+\S*->\S*\s")


def parse_filter_list(listing: str) -> list[str]:
    return [m.group(1) for line in listing.splitlines() if (m := _FILTER_ROW.match(line))]


def parse_format_list(listing: str) -> list[str]:
    """Names from ``-muxers``/``-demuxers`` (rows after the ``--``/``---`` separator).

    FFmpeg <= 8 prints a ``--`` separator, FFmpeg 9 prints ``---`` with a wider flag column.
    """
    names: list[str] = []
    seen_sep = False
    for line in listing.splitlines():
        if not seen_sep:
            seen_sep = line.strip() in ("--", "---")
            continue
        parts = line.split()
        if len(parts) >= 2:
            names.append(parts[1])
    return names


def capability_digest(catalog: dict[str, list[str]]) -> str:
    canon = json.dumps({k: sorted(set(v)) for k, v in sorted(catalog.items())}, sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def catalog(tools: FfmpegTools) -> dict[str, list[str]]:
    ff = str(tools.ffmpeg)
    return {
        "encoders": parse_codec_list(_run([ff, "-hide_banner", "-encoders"])),
        "decoders": parse_codec_list(_run([ff, "-hide_banner", "-decoders"])),
        "filters": parse_filter_list(_run([ff, "-hide_banner", "-filters"])),
        "muxers": parse_format_list(_run([ff, "-hide_banner", "-muxers"])),
        "demuxers": parse_format_list(_run([ff, "-hide_banner", "-demuxers"])),
    }


def roundtrip_check(tools: FfmpegTools) -> dict[str, str]:
    """Encode 1 s of 1080p30 test video + 48 kHz stereo tone, then probe it.

    This exercises a real encode/mux/demux/decode path rather than trusting exit codes.
    """
    with tempfile.TemporaryDirectory(prefix="aidash-ffcheck-") as tmp:
        out = Path(tmp) / "check.mp4"
        subprocess.run(
            [
                str(tools.ffmpeg),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=1920x1080:rate=30:duration=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=1",
                "-ac",
                "2",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(out),
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=True,
        )
        probe = json.loads(
            _run(
                [
                    str(tools.ffprobe),
                    "-v",
                    "error",
                    "-count_frames",
                    "-show_entries",
                    "stream=codec_type,codec_name,width,height,r_frame_rate,nb_read_frames,"
                    "sample_rate,channels",
                    "-of",
                    "json",
                    str(out),
                ]
            )
        )
    streams = cast(list[dict[str, Any]], probe.get("streams", []))
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None or audio is None:
        raise RuntimeError(f"round-trip output missing streams: {streams}")
    if (video.get("width"), video.get("height"), video.get("r_frame_rate")) != (1920, 1080, "30/1"):
        raise RuntimeError(f"unexpected video stream: {video}")
    if str(video.get("nb_read_frames")) != "30":
        raise RuntimeError(f"expected 30 decoded frames, got {video.get('nb_read_frames')}")
    if (audio.get("sample_rate"), audio.get("channels")) != ("48000", 2):
        raise RuntimeError(f"unexpected audio stream: {audio}")
    return {
        "roundtrip": "1920x1080@30/1 h264 30 frames decoded; aac 48000 Hz stereo",
    }


def probe(pins: FfmpegPins | None = None, functional: bool = True) -> ComponentStatus:
    pins = pins or load_pins().ffmpeg
    tools = locate(pins)
    if tools is None:
        return ComponentStatus(
            "ffmpeg",
            Readiness.MISSING,
            "ffmpeg/ffprobe not found on PATH (set AIDASHVIDEO_FFMPEG/AIDASHVIDEO_FFPROBE "
            "or install the frozen FFmpeg build; see docs/plan/commands.md)",
        )
    facts: dict[str, str] = {"ffmpeg": str(tools.ffmpeg), "ffprobe": str(tools.ffprobe)}
    try:
        version = parse_version(_run([str(tools.ffmpeg), "-hide_banner", "-version"]))
        cat = catalog(tools)
    except (OSError, subprocess.SubprocessError) as exc:
        return ComponentStatus(
            "ffmpeg", Readiness.CONFLICTING, f"ffmpeg failed to run: {exc}", facts
        )
    digest = capability_digest(cat)
    facts.update(
        version=version,
        ffmpeg_sha256=sha256_file(tools.ffmpeg),
        ffprobe_sha256=sha256_file(tools.ffprobe),
        capability_sha256=digest,
        **{f"{k}_count": str(len(v)) for k, v in cat.items()},
    )
    missing = [
        f"{kind}:{name}"
        for kind, names in (
            ("encoder", pins.required_encoders),
            ("decoder", pins.required_decoders),
            ("filter", pins.required_filters),
            ("muxer", pins.required_muxers),
        )
        for name in names
        if name not in cat[f"{kind}s"]
    ]
    if missing:
        return ComponentStatus(
            "ffmpeg",
            Readiness.CONFLICTING,
            f"FFmpeg {version} lacks required capabilities: " + ", ".join(missing),
            facts,
        )
    if functional:
        try:
            facts.update(roundtrip_check(tools))
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
            return ComponentStatus(
                "ffmpeg", Readiness.CONFLICTING, f"round-trip check failed: {exc}", facts
            )
    drift: list[str] = []
    if version != pins.version:
        drift.append(f"version {version!r} != pinned {pins.version!r}")
    if drift:
        return ComponentStatus("ffmpeg", Readiness.CONFLICTING, "; ".join(drift), facts)
    detail = f"FFmpeg {version} matches the {pins.version} pin with all required capabilities"
    return ComponentStatus("ffmpeg", Readiness.VERIFIED, detail, facts)
