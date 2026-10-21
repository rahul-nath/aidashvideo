"""``aidashvideo-doctor``: report supplier readiness without changing anything.

Readiness words are exactly those of docs/plan: ``Verified | Missing | Conflicting``.
Core (FFmpeg, MLT at the profile's pinned identities) decides the exit status. The
``host`` row states whether this machine is the profile's host (target binding) and
optional providers (SAM 3 torch, SAM 3.1 MLX, timed speech) are reported separately;
both only fail the run when required with ``--require`` (I10: a missing optional stack
never breaks core boot).

Usage::

    uv run --offline --no-sync aidashvideo-doctor [--json] [--quick] [--no-providers]
                                                  [--require sam31-mlx,timed-speech]
    AIDASHVIDEO_DEPS_DIR=<dir> uv run --offline --no-sync aidashvideo-doctor   # explicit deps dir
"""

from __future__ import annotations

import argparse
import json
import platform
import sys

from . import ffmpeg, mlt, models, providers
from .pins import ProfilePins, load_pins
from .status import ComponentStatus, Readiness

CORE = ("ffmpeg", "mlt")


def host_status(pins: ProfilePins) -> ComponentStatus:
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    facts = {
        "profile": pins.profile_id,
        "profile_kind": pins.kind,
        "os": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "executable": sys.executable,
    }
    drift: list[str] = []
    if (platform.system(), platform.machine()) != (pins.os, pins.machine):
        drift.append(f"host {platform.system()}/{platform.machine()} != {pins.os}/{pins.machine}")
    if py != pins.python_version:
        drift.append(f"python {py} != pinned {pins.python_version}")
    if drift:
        return ComponentStatus(
            "host",
            Readiness.CONFLICTING,
            "not the profile's host: " + "; ".join(drift),
            facts,
            True,
        )
    return ComponentStatus(
        "host", Readiness.VERIFIED, f"{pins.profile_id} (Python {py})", facts, True
    )


def collect(quick: bool = False, with_providers: bool = True) -> list[ComponentStatus]:
    pins = load_pins()
    results = [
        host_status(pins),
        ffmpeg.probe(pins.ffmpeg, functional=not quick),
        mlt.probe(pins.mlt, functional=not quick),
    ]
    if with_providers:
        results += providers.probe()
    results += models.statuses()
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aidashvideo-doctor",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--quick", action="store_true", help="skip real render/encode checks")
    parser.add_argument(
        "--no-providers", action="store_true", help="skip the (slower) optional provider probe"
    )
    parser.add_argument(
        "--require", default="", help="comma-separated optional components that must be Verified"
    )
    args = parser.parse_args(argv)

    pins = load_pins()
    results = collect(quick=args.quick, with_providers=not args.no_providers)
    required = set(CORE) | {r.strip() for r in args.require.split(",") if r.strip()}
    by_name = {r.component: r for r in results}
    unknown = required - by_name.keys()
    failed = sorted(n for n in required & by_name.keys() if not by_name[n].ok) + sorted(unknown)
    core_ready = all(by_name[n].ok for n in CORE)

    if args.json:
        print(
            json.dumps(
                {
                    "profile": pins.profile_id,
                    "profile_kind": pins.kind,
                    "core_verified": core_ready,
                    "required": sorted(required),
                    "failed": failed,
                    "components": [r.to_json() for r in results],
                },
                indent=2,
            )
        )
    else:
        print(f"profile: {pins.profile_id} ({pins.kind})")
        for r in results:
            tag = "optional" if r.optional else "core"
            print(f"{r.readiness.value:12} {r.component:30} [{tag}] {r.detail}")
        print()
        print("core: " + ("Verified" if core_ready else "NOT verified"))
        if failed:
            print("required but not Verified: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
