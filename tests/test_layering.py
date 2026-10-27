"""Import layering and sole-owner lint (implementation plan §2, invariant I4).

Ruff's ``banned-api`` is global and cannot express *directional* rules between packages,
so this test is the M1 layering rule: it parses every module under ``src/aidashvideo`` and
checks the allowed dependency direction
``client -> jobs -> {compiler, analysis, mltworker} -> {project, store, catalog} -> ledger``
(``ledger`` depends on nothing above it) and that frame/sample/pixel arithmetic
(``math.floor``/``math.ceil``/``bisect`` over rationals) lives only in the timing and
geometry owners.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "aidashvideo"

TIER: dict[str, int] = {
    "ledger": 0,
    "project": 1,
    "store": 1,
    "catalog": 1,
    "compiler": 2,
    "analysis": 2,
    "mltworker": 2,
    "jobs": 3,
    "client": 4,
}
# same-tier imports that are allowed (a package may only import packages below it, plus these)
SAME_TIER_ALLOWED: dict[str, set[str]] = {
    "project": {"store", "catalog"},
    "store": {"catalog"},
}
ALGEBRA_OWNERS = {"project/timing.py", "project/geometry.py"}

pytestmark = pytest.mark.project


def _package_of(module: str) -> str:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "aidashvideo" else ""


def _modules() -> list[tuple[str, Path, ast.Module]]:
    out: list[tuple[str, Path, ast.Module]] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC)
        package = rel.parts[0] if len(rel.parts) > 1 else ""
        out.append((package, path, ast.parse(path.read_text("utf-8"), str(path))))
    return out


def _imports(tree: ast.Module, package: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("aidashvideo."):
                    found.add(_package_of(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module is not None:
                found.add(package)  # relative import inside the same package
            elif node.module and node.module.startswith("aidashvideo."):
                found.add(_package_of(node.module))
            elif node.module == "aidashvideo":
                found.update(_package_of(f"aidashvideo.{a.name}") for a in node.names)
    return {f for f in found if f}


def test_packages_only_import_downward() -> None:
    violations: list[str] = []
    for package, path, tree in _modules():
        if package not in TIER:
            continue
        for target in _imports(tree, package):
            if target == package or target not in TIER:
                continue
            if TIER[target] < TIER[package]:
                continue
            if TIER[target] == TIER[package] and target in SAME_TIER_ALLOWED.get(package, set()):
                continue
            violations.append(f"{path.relative_to(SRC)} imports aidashvideo.{target}")
    assert violations == [], "\n".join(violations)


def test_ledger_depends_on_nothing_above_it() -> None:
    for package, path, tree in _modules():
        if package == "ledger":
            assert _imports(tree, package) <= {"ledger"}, path


def test_frame_and_pixel_arithmetic_lives_in_the_algebra_owners() -> None:
    """``math.floor``/``math.ceil``/``bisect`` on rationals are the owners' business (I4)."""
    offenders: list[str] = []
    for _package, path, tree in _modules():
        rel = str(path.relative_to(SRC))
        if rel in ALGEBRA_OWNERS:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "math" and node.attr in {"floor", "ceil"}:
                    offenders.append(f"{rel}: math.{node.attr}")
                if node.value.id == "bisect":
                    offenders.append(f"{rel}: bisect.{node.attr}")
    assert offenders == [], offenders


def test_boot_package_imports_nothing() -> None:
    init = ast.parse((SRC / "__init__.py").read_text("utf-8"))
    assert not [n for n in ast.walk(init) if isinstance(n, ast.Import | ast.ImportFrom)]
