"""MLT profile discovery, environment, bindings import and readiness probe.

The MLT framework is installed rootlessly under ``<deps>/frozen`` by
``scripts/build_toolchain_macos.sh`` (target) or ``scripts/build_frozen_toolchain.sh``
(Linux sandbox); ``<deps>/frozen/profile.json`` describes that install.
Native MLT work in the probe always runs in a child process so a native crash can
only fail the probe, never the caller.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from .ffmpeg import locate as locate_ffmpeg
from .paths import deps_dir, repo_root
from .pins import MltPins, load_pins
from .status import ComponentStatus, Readiness

_PROBE_TIMEOUT_S = 180


class MltUnavailableError(RuntimeError):
    """The pinned MLT profile is not installed or incomplete (typed, never auto-installed)."""


@dataclass(frozen=True)
class MltProfile:
    root: Path
    data: dict[str, Any]

    @property
    def profile_id(self) -> str:
        return str(self.data.get("profile_id", ""))

    @property
    def version(self) -> str:
        return str(self.data.get("mlt_version", ""))

    @property
    def lock_sha256(self) -> str:
        return str(self.data.get("lock_sha256", ""))

    def path(self, key: str) -> Path:
        return self.root / str(cast(dict[str, Any], self.data["paths"])[key])

    @property
    def melt(self) -> Path:
        return self.path("melt")

    @property
    def python_dir(self) -> Path:
        return self.path("python_dir")

    def environment(self) -> dict[str, str]:
        """MLT/frei0r/LADSPA/Qt settings for this profile (relative paths resolved to root)."""
        env = cast(dict[str, str], self.data["env"])
        return {
            k: (v if v.startswith("/") or k.endswith("PLATFORM") else str(self.root / v))
            for k, v in env.items()
        }


def load_profile(root: Path | None = None, pins: MltPins | None = None) -> MltProfile:
    if root is None:
        pins = pins or load_pins().mlt
        root = deps_dir() / pins.install
    manifest = root / "profile.json"
    if not manifest.is_file():
        raise MltUnavailableError(
            f"MLT profile not installed: {manifest} missing "
            "(install it: target scripts/build_toolchain_macos.sh, Linux sandbox "
            "scripts/build_frozen_toolchain.sh; see docs/plan/commands.md section 6)"
        )
    profile = MltProfile(root, cast(dict[str, Any], json.loads(manifest.read_text("utf-8"))))
    missing = [
        str(p)
        for p in (
            profile.melt,
            profile.python_dir,
            *(Path(v) for k, v in profile.environment().items() if k.endswith("PATH")),
        )
        if not p.exists()
    ]
    if missing:
        raise MltUnavailableError("MLT profile incomplete, missing: " + ", ".join(missing))
    return profile


def child_environment(profile: MltProfile, base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for a child process (melt or a Python worker) using this profile."""
    env = dict(os.environ if base is None else base)
    env.update(profile.environment())
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(profile.python_dir), env.get("PYTHONPATH", "")) if p
    )
    return env


def import_mlt(profile: MltProfile | None = None) -> ModuleType:
    """Import the ``mlt7`` bindings in-process, configured for the pinned profile.

    Raises :class:`MltUnavailableError` (never installs) when the profile is absent.
    """
    profile = profile or load_profile()
    os.environ.update(profile.environment())
    if str(profile.python_dir) not in sys.path:
        sys.path.insert(0, str(profile.python_dir))
    try:
        import mlt7  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise MltUnavailableError(f"MLT Python bindings failed to import: {exc}") from exc
    return cast(ModuleType, mlt7)


def catalog_digest(catalog: dict[str, list[str]]) -> str:
    canon = json.dumps({k: sorted(v) for k, v in sorted(catalog.items())}, sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()


def _lock_sha256(pins: MltPins) -> str:
    return hashlib.sha256((repo_root() / pins.lock).read_bytes()).hexdigest()


def run_native_probe(profile: MltProfile, render_to: Path | None = None) -> dict[str, Any]:
    """Run :mod:`aidashvideo.catalog._mlt_probe` in a child interpreter."""
    args = [sys.executable, "-m", "aidashvideo.catalog._mlt_probe"]
    if render_to is not None:
        args.append(str(render_to))
    proc = subprocess.run(
        args,
        env=child_environment(profile),
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT_S,
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
        raise RuntimeError(f"native MLT probe exited {proc.returncode}: {' | '.join(tail)}")
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    if not lines:
        raise RuntimeError("native MLT probe produced no JSON result")
    return cast(dict[str, Any], json.loads(lines[-1]))


def _verify_render(path: Path) -> str:
    tools = locate_ffmpeg(load_pins().ffmpeg)
    if tools is None:
        return "render written (not decoded: ffprobe unavailable)"
    out = subprocess.run(
        [
            str(tools.ffprobe),
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            "stream=codec_type,width,height,r_frame_rate,nb_read_frames,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    streams = cast(list[dict[str, Any]], json.loads(out.stdout).get("streams", []))
    empty: dict[str, Any] = {}
    video = next((s for s in streams if s.get("codec_type") == "video"), empty)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), empty)
    got = (
        video.get("width"),
        video.get("height"),
        video.get("r_frame_rate"),
        str(video.get("nb_read_frames")),
        audio.get("sample_rate"),
        audio.get("channels"),
    )
    if got != (1920, 1080, "30/1", "30", "48000", 2):
        raise RuntimeError(f"MLT render decoded with unexpected streams: {got}")
    return "1920x1080@30/1 30 frames decoded; audio 48000 Hz stereo"


def probe(pins: MltPins | None = None, functional: bool = True) -> ComponentStatus:
    pins = pins or load_pins().mlt
    try:
        profile = load_profile(pins=pins)
    except MltUnavailableError as exc:
        return ComponentStatus("mlt", Readiness.MISSING, str(exc))
    facts: dict[str, str] = {
        "profile_id": profile.profile_id,
        "root": str(profile.root),
        "melt": str(profile.melt),
    }
    try:
        melt_out = subprocess.run(
            [str(profile.melt), "-version"],
            env=child_environment(profile),
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        facts["melt_version"] = (melt_out.stdout or melt_out.stderr).splitlines()[0].strip()
        with tempfile.TemporaryDirectory(prefix="aidash-mltcheck-") as tmp:
            target = Path(tmp) / "render.mp4" if functional else None
            result = run_native_probe(profile, target)
            if target is not None:
                facts["render"] = _verify_render(target)
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
        return ComponentStatus(
            "mlt", Readiness.CONFLICTING, f"MLT failed its native probe: {exc}", facts
        )
    catalog = cast(dict[str, list[str]], result["catalog"])
    digest = catalog_digest(catalog)
    facts.update(
        bindings_version=str(result["version"]),
        catalog_sha256=digest,
        frame=str(result["frame"]),
        **{f"{k}_count": str(len(v)) for k, v in catalog.items()},
    )
    drift: list[str] = []
    if str(result["version"]) != pins.version:
        drift.append(f"bindings report MLT {result['version']} != pinned {pins.version}")
    if profile.profile_id != pins.profile_id:
        drift.append(f"installed profile {profile.profile_id!r} != pinned {pins.profile_id!r}")
    if pins.lock and profile.lock_sha256 != _lock_sha256(pins):
        drift.append("installed tree was built from a different lock file (re-run bootstrap)")
    if drift:
        return ComponentStatus("mlt", Readiness.CONFLICTING, "; ".join(drift), facts)
    detail = f"MLT {result['version']} ({profile.profile_id}) matches the {pins.version} pin"
    return ComponentStatus("mlt", Readiness.VERIFIED, detail, facts)
