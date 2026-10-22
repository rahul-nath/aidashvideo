"""The seven docs/plan files and the evidence report must form one consistent plan.

Checks: files exist and are non-trivial; JSON parses; relative links resolve; readiness
words are exactly Verified | Missing | Conflicting with planned/observed kept apart; the
four readiness rows exist and agree across both JSON files; a Verified tool needs
target-host evidence; TODO appears only inside Missing/Conflicting items; the ownership
block and head-write rule are byte-identical in the three narrative files; the matrix
covers V01-V30, I1-I12 and GP-01 steps 1-8 with verbatim text from
docs/design/milestone-6.md.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "plan"
EVIDENCE = ROOT / "docs" / "evidence" / "milestone-0.md"
M6 = ROOT / "docs" / "design" / "milestone-6.md"
MD = [
    "implementation-plan.md",
    "contracts.md",
    "verification-matrix.md",
    "commands.md",
    "fixtures.md",
]
JSON_FILES = ["runtime-profile.json", "provider-manifest.json"]
WORDS = {"Verified", "Missing", "Conflicting"}
FOUR_ROWS = ["core", "full-mlt-package", "timed-speech", "sam31-mlx"]
OWNER_BLOCK_START = "### Responsibility owners (bound once)"
HEAD_RULE = (
    "Head-write rule: only `aidashvideo.ledger` writes project heads, operation events, "
    "idempotency records and job/effect intents, inside one SQLite transaction; "
    "`aidashvideo.mltworker` and `aidashvideo.client` cannot write project heads."
)
OWNERS = {
    "project domain": "aidashvideo.project",
    "canonical admission": "aidashvideo.ledger",
    "media/artifact store": "aidashvideo.store",
    "capability catalog": "aidashvideo.catalog",
    "graph compiler": "aidashvideo.compiler",
    "native MLT worker": "aidashvideo.mltworker",
    "speech/mask adapters": "aidashvideo.analysis",
    "one job supervisor": "aidashvideo.jobs",
    "chat/client": "aidashvideo.client",
}

pytestmark = pytest.mark.plan


def _json(name: str) -> dict[str, Any]:
    return json.loads((PLAN / name).read_text("utf-8"))


def _walk(
    node: object, path: tuple[object, ...] = ()
) -> Iterator[tuple[tuple[object, ...], object]]:
    yield path, node
    if isinstance(node, dict):
        for k, v in cast(dict[str, object], node).items():
            yield from _walk(v, (*path, k))
    elif isinstance(node, list):
        for i, v in enumerate(cast(list[object], node)):
            yield from _walk(v, (*path, i))


def _get(container: object, key: object) -> object:
    if isinstance(container, dict):
        return cast(dict[str, object], container)[cast(str, key)]
    return cast(list[object], container)[cast(int, key)]


def _readiness_of(node: object) -> object | None:
    if isinstance(node, dict):
        return cast(dict[str, object], node).get("readiness")
    return None


def _owner_block(text: str) -> str:
    start = text.index(OWNER_BLOCK_START)
    end = text.index(HEAD_RULE, start) + len(HEAD_RULE)
    return text[start:end]


# ----------------------------------------------------------------------------- existence


def test_all_plan_files_exist_and_are_non_trivial() -> None:
    for name in MD + JSON_FILES:
        path = PLAN / name
        assert path.is_file(), name
        assert path.stat().st_size > 2000, f"{name} is trivial ({path.stat().st_size} bytes)"
    assert EVIDENCE.is_file() and EVIDENCE.stat().st_size > 2000
    for name in JSON_FILES:
        _json(name)  # parses


def test_relative_links_resolve() -> None:
    link = re.compile(r"\]\(([^)\s]+)\)")
    for path in [*(PLAN / n for n in MD), EVIDENCE]:
        for target in link.findall(path.read_text("utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            file_part = target.split("#", 1)[0]
            if not file_part:
                continue
            resolved = (path.parent / file_part).resolve()
            if resolved.is_relative_to(ROOT / "var"):
                # git-ignored artifacts live under AIDASHVIDEO_VAR_DIR on the producing host
                continue
            assert resolved.exists(), f"{path.name}: broken link {target}"


# ----------------------------------------------------------------------------- readiness


def test_readiness_words_and_separated_identities() -> None:
    for name in JSON_FILES:
        for path, node in _walk(_json(name)):
            if path and path[-1] == "readiness" and isinstance(node, str):
                assert node in WORDS, f"{name}: {'/'.join(map(str, path))} = {node!r}"
            if isinstance(node, dict) and "readiness" in node and "interface" in node:
                record = cast(dict[str, object], node)
                assert set(record) >= {
                    "id",
                    "planned",
                    "observed",
                    "readiness",
                    "interface",
                    "evidence",
                    "first_consumer",
                }, f"{name}: {path}"
                assert isinstance(record["planned"], dict)
                assert isinstance(record["observed"], list)


def test_four_separate_readiness_rows_agree_across_files() -> None:
    rp = _json("runtime-profile.json")
    pm = _json("provider-manifest.json")
    rows = {r["id"]: r["readiness"] for r in rp["readiness_rows"]}
    assert list(rows) == FOUR_ROWS
    assert {r["id"]: r["readiness"] for r in pm["readiness_rows"]} == rows
    providers = {p["id"]: p["readiness"] for p in pm["mask_backends"]["profiles"]}
    assert list(providers) == ["sam31-mlx-metal"], "exactly one mask profile (D5)"
    assert providers["sam31-mlx-metal"] == rows["sam31-mlx"]
    assert pm["timed_asr"]["adapter"]["readiness"] == rows["timed-speech"]
    assert pm["timed_asr"]["selected"] == "ffmpeg-whisper-filter"


def test_tools_verified_only_with_target_host_evidence() -> None:
    """A tool is Verified only when an observed entry names the plan's target host and the
    evidence points at a retained report (never a TODO); otherwise it must be Missing or
    Conflicting. Sandbox observations alone never make a tool Verified."""
    rp = _json("runtime-profile.json")
    target = rp["hosts"]["target"]["id"]
    for tool in rp["tool_readiness"]:
        if tool["readiness"] == "Verified":
            hosts = {str(o.get("host")) for o in tool["observed"]}
            assert target in hosts, f"{tool['id']}: Verified without a {target} observation"
            evidence = tool["evidence"]
            assert "TODO" not in evidence and "docs/evidence/" in evidence, tool["id"]
        else:
            assert tool["readiness"] in {"Missing", "Conflicting"}, tool["id"]


def test_todo_only_inside_missing_or_conflicting_items() -> None:
    for name in JSON_FILES:
        data = _json(name)
        for path, node in _walk(data):
            if isinstance(node, str) and "TODO" in node:
                # climb to the nearest enclosing object that declares a readiness
                container: object = data
                readiness: object = None
                for key in path[:-1]:
                    container = _get(container, key)
                    found = _readiness_of(container)
                    if found is not None:
                        readiness = found
                assert readiness in {"Missing", "Conflicting"}, f"{name}: TODO outside item: {path}"
                assert re.search(r"TODO \((Missing|Conflicting)\): \S", node), node
    for path in [*(PLAN / n for n in MD), EVIDENCE]:
        for line in path.read_text("utf-8").splitlines():
            if "TODO" in line:
                assert "(Missing)" in line or "(Conflicting)" in line, f"{path.name}: {line}"


# ----------------------------------------------------------------------------- agreement


def test_ownership_block_identical_in_three_files() -> None:
    blocks = {
        n: _owner_block((PLAN / n).read_text("utf-8"))
        for n in ("implementation-plan.md", "contracts.md", "verification-matrix.md")
    }
    assert len(set(blocks.values())) == 1, "ownership blocks differ"
    block = blocks["contracts.md"]
    for responsibility, module in OWNERS.items():
        assert f"| {responsibility} | `{module}` |" in block
    assert HEAD_RULE in block


def test_module_names_used_consistently() -> None:
    modules = set(OWNERS.values())
    for n in MD:
        text = (PLAN / n).read_text("utf-8")
        found = {f"aidashvideo.{m}" for m in re.findall(r"aidashvideo\.([a-z]+)(?![a-z/-])", text)}
        assert found <= modules | {"aidashvideo.catalog"}, (
            f"{n}: unknown module names {found - modules}"
        )
    contracts = (PLAN / "contracts.md").read_text("utf-8")
    assert re.search(r"class Sam31MlxBackend\b", contracts)
    for banned in ("Sam3TorchBackend", "EdgeTAM", "sam3-torch", "facebook/sam3\b"):
        assert not re.search(banned, contracts), banned


def test_closed_variants_have_no_nullable_escape_hatches() -> None:
    text = (PLAN / "contracts.md").read_text("utf-8")
    block = text[text.index("```text", text.index("## 2. Closed variants")) :]
    block = block[: block.index("```", 8)]
    assert "AssetAvailability = Present(verified_hash, scoped_locator, probe_receipt)" in block
    assert "| Missing(expected_hash, relink_request)" in block
    assert "| Changed(expected_hash, observed_hash)" in block
    assert "EditProposal      = Applicable(base_revision, typed_patch, affected_objects)" in block
    assert "| NeedsChoice(candidates, question)" in block
    assert "| Unsupported(requested_capability, reason)" in block
    for required in (
        "ApplyResult       = Applied(revision, admitted_event)",
        "Transcript        = SegmentTimed(source_binding, segments, provenance)",
        "MaskSpan          = Tracked(source_interval, artifact, coordinate_contract, "
        "qualification)",
        "MaskRequest       = SAM31MLXRequest(source_binding, source_interval, selection, "
        "correction_revision, qualified_profile)",
        "InstancePolicy    = AllMatchingInstances",
        "SubjectAssets     = VerifiedLocal(checkpoint_snapshot, tokenizer_snapshot, "
        "runtime_manifest)",
        "PreviewState      = Pending(revision, range, dependency_jobs)",
        "PreviewBinding    = EncodedRange(artifact, output_profile)",
        "MLTService        = Callable(build_id, descriptor, qualification)",
        "MLTParameter      = Static(value_type, units, constraints)",
        "Capability        = Qualified(provider_identity, evidence, resource_profile)",
        "RenderOutcome     = VerifiedOutput(job_identity, artifact, validation_receipt)",
    ):
        assert required in block, required
    assert "Optional[" not in block and "| None" not in block and "Any" not in block


# ----------------------------------------------------------------------------- matrix


def _m6() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    text = M6.read_text("utf-8")
    rows = {
        m.group(1): m.group(2) for m in re.finditer(r"^\| (V\d\d) \| .*? \| (.*?) \|$", text, re.M)
    }
    invariants = dict(re.findall(r"^- (I\d+): (.*)$", text, re.M))
    steps = dict(re.findall(r"^(\d)\. (.*)$", text, re.M))
    assert len(rows) == 30 and len(invariants) == 12 and len(steps) == 8
    return rows, invariants, steps


def test_matrix_covers_every_case_with_verbatim_thresholds() -> None:
    text = (PLAN / "verification-matrix.md").read_text("utf-8")
    rows, invariants, steps = _m6()
    table_rows = {
        m.group(1): m.group(0)
        for m in re.finditer(r"^\| ((?:V\d\d|I\d+|GP-01 step \d)) \|.*$", text, re.M)
    }
    for key, required in {
        **rows,
        **invariants,
        **{f"GP-01 step {k}": v for k, v in steps.items()},
    }.items():
        assert key in table_rows, f"{key} missing from matrix"
        row = table_rows[key]
        assert required in row, f"{key}: expected result not verbatim"
        cells = [c.strip() for c in row.strip().strip("|").split(" | ")]
        assert len(cells) == 9, f"{key}: expected 9 cells, got {len(cells)}"
        owner, milestone, positive, refusal, fixture, _expected, evidence = cells[2:9]
        assert "aidashvideo." in owner or "tests/" in owner, f"{key}: no owner module"
        assert re.search(r"M\d", milestone), f"{key}: no milestone"
        assert len(positive) > 15 and len(refusal) > 15, f"{key}: controls too thin"
        assert fixture and "var/evidence/" in evidence, key
    for threshold in (
        "at least 95% of nominated word boundaries within 100 ms",
        "Median mask IoU at least 0.90 and fifth percentile at least 0.80",
        "integrated loudness within 1 LU and measured true peak at or below -1 dBTP",
        "must preview within fifteen seconds on the qualified host",
    ):
        assert threshold in text, threshold
