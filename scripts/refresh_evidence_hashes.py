"""Regenerate the hash listings inside docs/evidence/milestone-0.md.

Run after editing any file in the candidate scope (pyproject, uv.lock, docs/plan, src, tests,
scripts, toolchain) or any retained artifact under the var dir (AIDASHVIDEO_VAR_DIR, else var/),
then re-run the test suite:

    uv run --offline --no-sync python scripts/refresh_evidence_hashes.py
    uv run --offline --no-sync pytest -q -p no:cacheprovider -m plan

Only the two ```text blocks and the scope digest line are rewritten; prose is untouched.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "evidence" / "milestone-0.md"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def main() -> int:
    deliverables = sorted(
        {
            *(
                ROOT / p
                for p in (
                    ".gitignore",
                    ".python-version",
                    "pyproject.toml",
                    "uv.lock",
                    "docs/toolchain.md",
                    "README.md",
                )
            ),
            *ROOT.glob("docs/plan/*"),
            *ROOT.rglob("src/aidashvideo/**/*.py"),
            *ROOT.glob("tests/*.py"),
            *ROOT.glob("scripts/*.sh"),
            *ROOT.glob("scripts/*.py"),
            *(p for p in ROOT.rglob("toolchain/**/*") if p.is_file()),
        }
    )
    var = Path(os.environ.get("AIDASHVIDEO_VAR_DIR") or ROOT / "var")
    artifacts = sorted(
        p
        for pattern in ("fixtures/gp01/*", "evidence/m0/*")
        for p in var.glob(pattern)
        if p.is_file() and p.name != "pytest.txt"
    )
    scope_lines = "\n".join(f"{sha(p)}  {rel(p)}" for p in deliverables)
    digest = hashlib.sha256(scope_lines.encode()).hexdigest()
    # artifact paths are recorded relative to the var dir, prefixed `var/`, so the listing is
    # host-independent; tests/test_plan_integrity.py resolves them through AIDASHVIDEO_VAR_DIR
    art_lines = "\n".join(f"{sha(p)}  var/{p.relative_to(var).as_posix()}" for p in artifacts)
    doc = REPORT.read_text("utf-8")
    doc, n = re.subn(
        r"(Scope digest\n\(SHA-256 of the listing below\): `)[0-9a-f]{64}(`)",
        rf"\g<1>{digest}\g<2>",
        doc,
    )
    blocks = list(re.finditer(r"```text\n.*?```", doc, re.S))
    if n != 1 or len(blocks) != 2:
        print("unexpected report layout", file=sys.stderr)
        return 1
    # Replace by position (never by content: two identical blocks would both be rewritten).
    first, second = blocks
    if artifacts:
        second_text = "```text\n" + art_lines + "\n```"
        note = f"{len(artifacts)} artifacts"
    else:
        # No var/ artifacts on this host (they are git-ignored and stay on the host that
        # produced them): keep the recorded listing instead of erasing that evidence.
        second_text = second.group(0)
        note = "no local artifacts; artifact listing kept as recorded"
    doc = (
        doc[: first.start()]
        + "```text\n"
        + scope_lines
        + "\n```"
        + doc[first.end() : second.start()]
        + second_text
        + doc[second.end() :]
    )
    REPORT.write_text(doc, "utf-8")
    print(f"scope digest {digest} ({len(deliverables)} files); {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
