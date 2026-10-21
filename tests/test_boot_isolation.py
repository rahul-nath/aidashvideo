"""Import/boot isolation smoke test (I10, V14): ``import aidashvideo`` must be inert.

The probe runs in a child interpreter started with ``-I`` so that neither the
parent's PYTHONPATH, user site nor already-imported modules can mask a violation.
See ``tests/boot_probe.py`` for the tripwires. ``scripts/verify_boot_tripwires.sh``
proves the test is not decorative by mutating the package four ways.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROBE = Path(__file__).with_name("boot_probe.py")


def _run_probe() -> dict[str, object]:
    proc = subprocess.run(
        [sys.executable, "-I", str(PROBE)],
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert lines, f"probe produced no report (exit {proc.returncode}): {proc.stderr[-2000:]}"
    report: dict[str, object] = json.loads(lines[-1])
    report["exit"] = proc.returncode
    return report


@pytest.mark.boot
def test_boot_import_isolation() -> None:
    report = _run_probe()
    assert report["isolated"] == 1, "child must run with -I"
    assert report["error"] == "", report["error"]
    assert report["trips"] == [], report["trips"]
    assert report["forbidden_loaded"] == [], report["forbidden_loaded"]
    assert report["new_modules"] == ["aidashvideo"], report["new_modules"]
    assert report["exit"] == 0 and report["ok"] is True
    assert set(report["tripwires"]) >= {  # type: ignore[arg-type]
        "imports:meta_path",
        "thread:_thread.start_new_thread",
        "process:os.fork/posix_spawn/exec/system/popen/spawn",
        "socket:import-denied",
    }


@pytest.mark.boot
def test_boot_probe_detects_injected_module(tmp_path: Path) -> None:
    """Control: a package that injects a fake torch module during import must fail the probe.

    A shadow ``aidashvideo`` package is placed first on sys.path by a wrapper, so the real
    package is untouched while the probe still runs under ``-I``.
    """
    shadow = tmp_path / "shadow" / "aidashvideo"
    shadow.mkdir(parents=True)
    shadow.joinpath("__init__.py").write_text(
        "import sys, types\nsys.modules['torch'] = types.ModuleType('torch')\n"
    )
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text(
        "import sys, runpy\n"
        f"sys.path.insert(0, {str(shadow.parent)!r})\n"
        f"sys.argv = [{str(PROBE)!r}]\n"
        f"runpy.run_path({str(PROBE)!r}, run_name='__main__')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-I", str(wrapper)], capture_output=True, text=True, timeout=120
    )
    report = json.loads([ln for ln in proc.stdout.splitlines() if ln.startswith("{")][-1])
    assert proc.returncode == 1 and report["ok"] is False
    assert "torch" in report["forbidden_loaded"]
    assert "torch" in report["new_modules"]
