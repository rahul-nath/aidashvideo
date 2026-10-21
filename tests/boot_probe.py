"""Child-interpreter boot probe: run as ``python -I tests/boot_probe.py``.

Installs tripwires BEFORE ``import aidashvideo`` and then asserts on ``sys.modules``:

* imports  - a ``sys.meta_path`` finder records every import and refuses a denylist
             (torch, numpy, mlt, transformers, mlx, sam3*, whisper, socket, subprocess,
             threading, asyncio, ...);
* threads  - ``_thread.start_new_thread`` raises;
* sockets  - ``_socket``/``socket`` cannot be imported (and ``socket.socket`` raises if
             they somehow are);
* processes- ``os.fork``/``posix_spawn``/``exec*``/``system``/``popen``/``spawn*`` raise and
             ``_posixsubprocess`` cannot be imported.

After the import, the set of newly loaded modules must be exactly {"aidashvideo"}
and no forbidden name may be present in ``sys.modules`` (catches modules injected
without an import statement). Prints one JSON line and exits non-zero on any violation.
"""

from __future__ import annotations

import os
import re
import sys

FORBIDDEN = re.compile(
    r"^(torch|torchvision|numpy|mlt7?|transformers|mlx|mlx_vlm|sam3|sam2|whisper|"
    r"huggingface_hub|socket|_socket|ssl|subprocess|_posixsubprocess|threading|asyncio|"
    r"multiprocessing|concurrent|ctypes|urllib|http|requests)(\.|$)",
)
ALLOWED_NEW = {"aidashvideo"}

trips: list[str] = []
imports_seen: list[str] = []


class _Tripwire:
    """Minimal meta-path finder (no importlib.abc import: keeps the probe's footprint tiny)."""

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        imports_seen.append(fullname)
        if FORBIDDEN.match(fullname):
            trips.append(f"import:{fullname}")
            raise ImportError(f"boot tripwire: import of {fullname!r} is forbidden at boot")
        return None


def _deny(name: str):  # type: ignore[no-untyped-def]
    def _raise(*_a: object, **_k: object) -> None:
        trips.append(name)
        raise RuntimeError(f"boot tripwire: {name} is forbidden at boot")

    return _raise


def main() -> int:
    sys.meta_path.insert(0, _Tripwire())
    import _thread

    _thread.start_new_thread = _deny("thread:start_new_thread")  # type: ignore[assignment]
    if "threading" in sys.modules:
        sys.modules["threading"]._start_new_thread = _deny("thread:start")  # type: ignore[attr-defined]
    for fn in (
        "fork",
        "forkpty",
        "posix_spawn",
        "posix_spawnp",
        "system",
        "popen",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "execl",
        "execlp",
        "spawnv",
        "spawnve",
        "spawnvp",
    ):
        if hasattr(os, fn):
            setattr(os, fn, _deny(f"process:os.{fn}"))
    if "socket" in sys.modules:
        sys.modules["socket"].socket = _deny("socket:socket")  # type: ignore[attr-defined]

    before = set(sys.modules)
    error = ""
    try:
        import aidashvideo  # noqa: F401  # pyright: ignore[reportUnusedImport]
    except BaseException as exc:  # any failure is a finding, not a crash
        error = f"{type(exc).__name__}: {exc}"
    new_modules = sorted(set(sys.modules) - before)
    forbidden_loaded = sorted(m for m in sys.modules if FORBIDDEN.match(m))
    unexpected = sorted(m for m in new_modules if m not in ALLOWED_NEW)
    ok = (
        not error
        and not trips
        and not forbidden_loaded
        and not unexpected
        and "aidashvideo" in sys.modules
        and sys.flags.isolated == 1
    )
    import json  # imported only after the measurements above

    print(
        json.dumps(
            {
                "ok": ok,
                "isolated": sys.flags.isolated,
                "error": error,
                "trips": trips,
                "new_modules": new_modules,
                "unexpected_modules": unexpected,
                "forbidden_loaded": forbidden_loaded,
                "imports_seen": imports_seen,
                "tripwires": [
                    "imports:meta_path",
                    "thread:_thread.start_new_thread",
                    "process:os.fork/posix_spawn/exec/system/popen/spawn",
                    "socket:import-denied",
                ],
            }
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
