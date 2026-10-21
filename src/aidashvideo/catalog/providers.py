"""Readiness of the optional analysis providers: SAM 3.1 (MLX, the only mask profile), timed speech.

``Verified`` here means *installed, importable, device present and licensed assets
admitted*. It is never a quality qualification: V06/V08/V18 qualification needs real
annotated fixtures and is recorded separately (docs/plan/verification-matrix.md).
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, cast

from . import ffmpeg
from .models import asset_status, load_manifest
from .offline import provider_environment
from .status import ComponentStatus, Readiness

_TIMEOUT_S = 300


def run_probe() -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "-m", "aidashvideo.catalog._provider_probe"],
        env=provider_environment(),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        stdin=subprocess.DEVNULL,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    if proc.returncode != 0 or not lines:
        tail = " | ".join((proc.stderr or "").strip().splitlines()[-3:])
        raise RuntimeError(f"provider probe exited {proc.returncode}: {tail}")
    return cast(dict[str, Any], json.loads(lines[-1]))


def _assets(profile: str) -> list[ComponentStatus]:
    return [asset_status(a) for a in load_manifest() if a.profile == profile]


def _with_assets(name: str, profile: str, detail: str, facts: dict[str, str]) -> ComponentStatus:
    pending = [a for a in _assets(profile) if not a.ok]
    if pending:
        what = "; ".join(
            f"{a.component.removeprefix('asset:')} ({a.readiness.value})" for a in pending
        )
        worst = (
            Readiness.CONFLICTING
            if any(a.readiness is Readiness.CONFLICTING for a in pending)
            else Readiness.MISSING
        )
        return ComponentStatus(name, worst, f"{detail}; assets not ready: {what}", facts, True)
    return ComponentStatus(
        name, Readiness.VERIFIED, f"{detail}; assets admitted; NOT quality-qualified", facts, True
    )


def probe_speech(ffmpeg_status: ComponentStatus | None = None) -> ComponentStatus:
    """Timed speech = FFmpeg `whisper` audio filter (FFmpeg >= 8 built with whisper.cpp)."""
    facts: dict[str, str] = {"adapter": "ffmpeg-whisper-filter"}
    tools = ffmpeg.locate()
    if tools is None:
        return ComponentStatus("timed-speech", Readiness.MISSING, "ffmpeg not found", facts, True)
    try:
        filters = ffmpeg.parse_filter_list(
            subprocess.run(
                [str(tools.ffmpeg), "-hide_banner", "-filters"],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
                stdin=subprocess.DEVNULL,
            ).stdout
        )
        version = ffmpeg.parse_version(
            subprocess.run(
                [str(tools.ffmpeg), "-hide_banner", "-version"],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
                stdin=subprocess.DEVNULL,
            ).stdout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ComponentStatus(
            "timed-speech", Readiness.CONFLICTING, f"ffmpeg failed: {exc}", facts, True
        )
    facts["ffmpeg_version"] = version
    if "whisper" not in filters:
        return ComponentStatus(
            "timed-speech",
            Readiness.MISSING,
            f"FFmpeg {version} has no `whisper` filter (needs FFmpeg >= 8 built with "
            "--enable-whisper against whisper.cpp)",
            facts,
            True,
        )
    return _with_assets(
        "timed-speech", "timed-speech", f"FFmpeg {version} whisper filter present", facts
    )


def probe() -> list[ComponentStatus]:
    try:
        info = run_probe()
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        return [ComponentStatus("providers", Readiness.CONFLICTING, str(exc), optional=True)]
    versions = cast(dict[str, str], info.get("versions", {}))
    devices = cast(dict[str, bool], info.get("devices", {}))
    imports = cast(dict[str, str], info.get("imports", {}))
    device_list = ",".join(k for k, v in devices.items() if v) or "none"
    results: list[ComponentStatus] = []

    facts = {
        "implementation": "mlx-vlm mlx_vlm.models.sam3_1 MultiplexTrackerModel",
        "mlx": versions.get("mlx", ""),
        "mlx-vlm": versions.get("mlx-vlm", ""),
        "devices": device_list,
    }
    if not versions.get("mlx"):
        results.append(
            ComponentStatus(
                "sam31-mlx",
                Readiness.MISSING,
                "mlx not installed (extra `sam31-mlx`, macOS arm64 only)",
                facts,
                True,
            )
        )
    elif imports.get("mlx") or imports.get("sam3_1-mlx-vlm"):
        results.append(
            ComponentStatus(
                "sam31-mlx",
                Readiness.CONFLICTING,
                f"import failed: {imports.get('mlx') or imports.get('sam3_1-mlx-vlm')}",
                facts,
                True,
            )
        )
    elif not devices.get("metal"):
        results.append(
            ComponentStatus(
                "sam31-mlx",
                Readiness.CONFLICTING,
                "mlx present but Metal is not available on this host",
                facts,
                True,
            )
        )
    else:
        results.append(_with_assets("sam31-mlx", "sam31-mlx", "code installed (Metal)", facts))

    results.append(probe_speech())
    return results
