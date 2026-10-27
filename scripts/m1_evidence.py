#!/usr/bin/env python
"""Write the Milestone 1 inspectable evidence (V02 demonstration) into the local evidence store.

Creates a real project store in a temporary directory, runs the golden-path style sequence
(insert, cut, title, subject blur, selective undo of the cut, half-second title shift,
negative shift refusal, ambiguous rebind conflict, redo), and writes the documents, undo
plan/conflict, events and ``python -m aidashvideo.ledger inspect`` output as JSON under
``$AIDASHVIDEO_VAR_DIR/evidence/m1/V02/`` (git-ignored).

Usage: ``uv run --offline --no-sync python scripts/m1_evidence.py [--out DIR]``
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import fields, is_dataclass
from fractions import Fraction
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))  # the fixture catalog and builders live with the tests

from aidashvideo.catalog.paths import var_dir  # noqa: E402
from aidashvideo.ledger import Applied, ProjectId, Rejected, ReplayKey, issue_project_grant  # noqa: E402
from aidashvideo.ledger.__main__ import inspect as ledger_inspect  # noqa: E402
from aidashvideo.ledger.grants import current_actor  # noqa: E402
from aidashvideo.project import timing  # noqa: E402
from aidashvideo.project.apply import effect_dependency  # noqa: E402
from aidashvideo.project.document import ObjectKind, ObjectRef, OutputProfile  # noqa: E402
from aidashvideo.project.operations import (  # noqa: E402
    AddTitle,
    BindSubjectEffect,
    DropDependent,
    InsertOccurrence,
    LayerRef,
    MoveOccurrence,
    Operation,
    RebindAsset,
    RevertOperation,
    ShiftTitle,
    SubjectRequest,
    TrimOccurrence,
)
from aidashvideo.project.session import Project, new_project  # noqa: E402
from aidashvideo.project.text import LiteralText  # noqa: E402
from aidashvideo.project.timing import SequenceFrame, SourceSpan  # noqa: E402
from aidashvideo.project.undo import UndoConflict, UndoPlan  # noqa: E402
from project_support import BROLL, CATALOG, INTERVIEW, asset, blur, occurrence  # noqa: E402


def _dataclass_fields(value: object) -> dict[str, object] | None:
    if isinstance(value, type) or not is_dataclass(value):
        return None
    names = [f.name for f in fields(value)]
    return {name: cast(object, getattr(value, name)) for name in names}


def _jsonable(value: object) -> object:
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    to_json = getattr(value, "to_json", None)
    if callable(to_json) and not isinstance(value, type):
        result: object = to_json()
        return result
    members = _dataclass_fields(value)
    if members is not None:
        return {k: _jsonable(v) for k, v in members.items()}
    if isinstance(value, dict):
        items = cast(dict[object, object], value)
        return {str(k): _jsonable(v) for k, v in items.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in cast(Sequence[object], value)]
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return type(value).__name__


def _write(out: Path, name: str, value: object) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n", "utf-8")


def _admit(project: Project, ops: tuple[Operation, ...], key: str, text: str) -> Applied:
    result = project.admit(project.batch(ops, replay_key=ReplayKey(key), provenance_text=text))
    if not isinstance(result, Applied):
        raise SystemExit(f"unexpected admission result: {result}")
    return result


def run(out: Path) -> dict[str, object]:
    steps: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="aidashvideo-m1-") as tmp:
        project_dir = Path(tmp) / "demo-project"
        grant = issue_project_grant(project_dir, current_actor("m1-evidence"))
        project = new_project(
            project_dir, grant, CATALOG, OutputProfile.default(), ProjectId("gp01-demo")
        )
        if not isinstance(project, Project):
            raise SystemExit(f"cannot create the demo project: {project}")
        with project:
            _admit(
                project,
                tuple(
                    RebindAsset(asset(n, r, grant.grant_id), r)
                    for n, r in (("interview", INTERVIEW), ("broll", BROLL))
                ),
                "bind-assets-0123456789",
                "Import interview and broll",
            )
            _admit(
                project,
                (InsertOccurrence(LayerRef("V1"), occurrence("A", "interview", 0, 12, 0)),),
                "insert-0123456789abc",
                "Place interview first",
            )
            cut = _admit(
                project,
                (
                    TrimOccurrence("A", SourceSpan.make(0, 6)),
                    InsertOccurrence(LayerRef("V1"), occurrence("A2", "interview", 8, 12, 180)),
                ),
                "cut-0123456789abcdef",
                "remove source seconds 6 through 8",
            )
            _admit(
                project,
                (InsertOccurrence(LayerRef("V1"), occurrence("B", "broll", 0, 4, 300)),),
                "broll-0123456789abcd",
                "append broll",
            )
            # undoing the cut now would restore A to 360 frames on top of broll at 300: the
            # revert is refused as an exact overlap and nothing is mutated
            blocked = project.plan_undo(cut.admitted_event.seq)
            _write(out, "01a-undo-blocked-by-overlap.json", blocked)
            if not isinstance(blocked, Rejected):
                raise SystemExit(f"expected an overlap rejection, got {blocked}")
            steps.append(
                {
                    "step": "undo refused while broll occupies the restored range",
                    "result": _jsonable(blocked),
                }
            )
            _admit(
                project,
                (MoveOccurrence("B", SequenceFrame(360)),),
                "move-broll-0123456789",
                "move broll after the full interview",
            )
            _admit(
                project,
                (AddTitle("title", LiteralText("Golden path"), 30, 60, "default"),),
                "title-0123456789abcd",
                "Add a title at one second",
            )
            blur_event = _admit(
                project,
                (
                    BindSubjectEffect(
                        blur("blur", "A", "mask-A"),
                        SubjectRequest(
                            LiteralText("the person"), SourceSpan.make(0, 6), "sam31-mlx-metal"
                        ),
                    ),
                ),
                "blur-0123456789abcde",
                "Keep this person sharp and blur the background for the interview",
            )
            before = project.head()
            _write(out, "01-before-undo.document.json", before.document.to_json())
            steps.append(
                {
                    "step": "cut+title+blur admitted",
                    "head": before.record.to_json(),
                    "intents": [i.to_json() for i in project.ledger.intents()],
                }
            )

            plan = project.plan_undo(cut.admitted_event.seq)
            _write(out, "02-undo-plan.json", plan)
            if not isinstance(plan, UndoPlan):
                raise SystemExit(f"expected an undo plan, got {plan}")
            undo = _admit(
                project,
                (RevertOperation(cut.admitted_event.seq, ()),),
                "undo-cut-0123456789ab",
                "Keep the blur, undo the last cut",
            )
            after = project.head()
            _write(out, "03-after-undo.document.json", after.document.to_json())
            effect = after.document.effect("blur")
            assert effect is not None
            coverage = effect_dependency(after.document, effect)
            _write(out, "04-blur-dependency-after-undo.json", coverage)
            steps.append(
                {
                    "step": "selective undo of the cut",
                    "event": undo.admitted_event.to_json(),
                    "blur_dependency": _jsonable(coverage),
                }
            )

            shift = timing.frames_nearest(Fraction(-1, 2), after.document.profile.fps)
            shifted = _admit(
                project,
                (ShiftTitle("title", shift.frames),),
                "shift-0123456789abcd",
                "move the title half a second earlier",
            )
            title = project.head().document.title("title")
            assert title is not None
            steps.append(
                {
                    "step": "half-second title shift",
                    "requested_seconds": "-1/2",
                    "frames": shift.frames,
                    "realized_seconds": str(shift.realized_seconds),
                    "title_place": title.place.to_json(),
                    "event": shifted.admitted_event.to_json(),
                }
            )
            negative = project.admit(
                project.batch(
                    (ShiftTitle("title", -16),),
                    replay_key=ReplayKey("shift2-0123456789abc"),
                    provenance_text="one frame too early",
                )
            )
            _write(out, "05-negative-start-rejection.json", negative)
            steps.append({"step": "negative title start", "result": _jsonable(negative)})

            redo = _admit(
                project,
                (RevertOperation(undo.admitted_event.seq, ()),),
                "redo-0123456789abcde",
                "redo the cut",
            )
            steps.append(
                {"step": "redo (revert of the undo)", "event": redo.admitted_event.to_json()}
            )
            _admit(
                project,
                (
                    BindSubjectEffect(
                        blur("blur-right", "A2", "mask-A2", radius=40),
                        SubjectRequest(
                            LiteralText("the person"), SourceSpan.make(8, 12), "sam31-mlx-metal"
                        ),
                    ),
                ),
                "blur2-0123456789abcd",
                "blur the right half with a different radius",
            )
            conflict = project.plan_undo(cut.admitted_event.seq)
            _write(out, "06-ambiguous-rebind-conflict.json", conflict)
            if not isinstance(conflict, UndoConflict):
                raise SystemExit(f"expected a conflict, got {conflict}")
            rejected = project.admit(
                project.batch(
                    (RevertOperation(cut.admitted_event.seq, ()),),
                    replay_key=ReplayKey("undo2-0123456789abcd"),
                    provenance_text="undo without a choice",
                )
            )
            assert isinstance(rejected, Rejected)
            resolved = _admit(
                project,
                (
                    RevertOperation(
                        cut.admitted_event.seq,
                        (DropDependent(ObjectRef(ObjectKind.EFFECT, "blur-right")),),
                    ),
                ),
                "undo3-0123456789abcd",
                "undo the cut, dropping the right-half blur",
            )
            steps.append(
                {
                    "step": "ambiguous rebind",
                    "conflict": _jsonable(conflict),
                    "rejected_without_choice": _jsonable(rejected),
                    "resolved_event": resolved.admitted_event.to_json(),
                }
            )
            _write(out, "07-final.document.json", project.head().document.to_json())
            _write(out, "08-events.json", [e.to_json() for e in project.events()])
            _write(out, "09-blur-event.json", blur_event.to_json())
            integrity = project.ledger.verify(deep=True)
        report = ledger_inspect(project_dir, deep=True)
        _write(out, "10-ledger-inspect.json", report)
    summary: dict[str, object] = {
        "steps": steps,
        "integrity_ok": integrity.ok,
        "inspect_open": report.get("open"),
    }
    _write(out, "00-summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=var_dir() / "evidence" / "m1" / "V02")
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    summary = run(out)
    print(json.dumps({"out": str(out), "integrity_ok": summary["integrity_ok"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
