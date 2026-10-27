"""``python -m aidashvideo.ledger inspect <project_dir>``: read-only inspection.

Prints heads, lineage, events, intents and outbox as JSON. Needs no MLT, FFmpeg or model;
the domain is not consulted (documents are reported by hash and size only), so the command
works on a project whose writer is newer than this code (read-only) and says so.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .domain import BatchEnvelope, HistoryView, ImportedDocument, Migrated, Valid
from .errors import ContractError
from .grants import current_actor, issue_project_grant
from .ids import ParentRef, ProjectId, RevisionId
from .ledger import Ledger, Opened
from .results import Corrupt, Denied, Fenced, InvalidSnapshot, ReadOnly, Rejected


class _InspectOnlyDomain:
    """A domain that refuses every write: inspection never admits anything."""

    document_schema_version = 0

    def revision_id(self, document: bytes, parent: ParentRef, project_id: ProjectId) -> RevisionId:
        raise ContractError("inspection domain cannot compute identities")

    def validate_document(self, document: bytes, schema_version: int) -> Valid | Rejected:
        raise ContractError("inspection domain cannot validate")

    def apply(
        self,
        base_document: bytes,
        base_schema_version: int,
        envelope: BatchEnvelope,
        history: HistoryView,
    ) -> Rejected:
        raise ContractError("inspection domain cannot apply")

    def import_snapshot(self, snapshot: bytes) -> ImportedDocument | InvalidSnapshot:
        raise ContractError("inspection domain cannot import")

    def migrate_document(self, document: bytes, from_version: int, to_version: int) -> Migrated:
        raise ContractError("inspection domain cannot migrate")


def inspect(project_dir: Path, *, deep: bool) -> dict[str, object]:
    grant = issue_project_grant(project_dir, current_actor("inspect"))
    opened = Ledger.open(project_dir, grant, _InspectOnlyDomain())
    match opened:
        case Fenced(writer, min_reader, supported):
            return {
                "open": "Fenced",
                "writer_version": writer,
                "min_reader_version": min_reader,
                "supported_reader": supported,
            }
        case Denied(reason):
            return {"open": "Denied", "reason": reason.to_json()}
        case Corrupt(findings):
            return {"open": "Corrupt", "findings": list(findings)}
        case Opened(ledger, mode):
            with ledger:
                versions = ledger.schema_versions()
                report = ledger.verify(deep=deep)
                lineages: list[dict[str, object]] = []
                for pid in ledger.lineages():
                    head = ledger.head_of(pid)
                    chain = ledger.lineage(head.revision_id)
                    lineages.append(
                        {
                            "project_id": pid.value,
                            "canonical": ledger.canonical_project() == pid,
                            "head": head.to_json(),
                            "lineage": [r.revision_id.hex for r in chain],
                            "events": [e.to_json() for e in ledger.events(pid)],
                        }
                    )
                return {
                    "open": "Opened",
                    "mode": "ReadOnly" if isinstance(mode, ReadOnly) else "Writable",
                    "mode_reason": mode.reason.to_json() if isinstance(mode, ReadOnly) else "",
                    "schema_version": {
                        "writer_version": versions.writer_version,
                        "min_reader_version": versions.min_reader_version,
                    },
                    "integrity": {"ok": report.ok, "findings": list(report.findings)},
                    "lineages": lineages,
                    "intents": [i.to_json() for i in ledger.intents()],
                    "outbox_pending": [o.to_json() for o in ledger.pending_outbox()],
                    "outbox_done": [o.to_json() for o in ledger.dispatched_outbox()],
                    "cas_blobs": len(ledger.cas.all_blobs()),
                    "cas_orphans": [b.hex for b in ledger.cas.orphans(ledger.referenced_blobs())],
                }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aidashvideo.ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    ins = sub.add_parser("inspect", help="read-only inspection of heads, lineage and outbox")
    ins.add_argument("project_dir", type=Path)
    ins.add_argument("--deep", action="store_true", help="verify every revision payload")
    args = parser.parse_args(argv)
    report = inspect(Path(args.project_dir).resolve(), deep=bool(args.deep))
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report.get("open") == "Opened" else 1


if __name__ == "__main__":
    sys.exit(main())
