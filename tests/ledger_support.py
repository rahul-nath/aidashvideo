"""A trivial domain for testing the ledger alone (implementation plan M1a).

The document is ``{"n": int}``; operations are ``add`` (``k``), ``intent`` (enqueue a job
intent), ``artifact`` (reference a sealed artifact) and ``boom`` (always rejected). The
ledger never interprets these; it only sees bytes, hashes and the closed header fields.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from aidashvideo.ledger import (
    Accepted,
    BatchEnvelope,
    HistoryView,
    ImportedDocument,
    IntentId,
    IntentKind,
    IntentRequest,
    InvalidSnapshot,
    Ledger,
    LocalUser,
    Migrated,
    Opened,
    Parent,
    ParentRef,
    ProjectGrant,
    ProjectId,
    RejectCode,
    Rejected,
    ReplayKey,
    RevisionId,
    RevisionSnapshot,
    Sha256,
    UnsupportedSchema,
    UserWording,
    Valid,
    canonical_bytes,
    canonical_sha256,
    issue_project_grant,
    parse_json,
    sha256_of,
)
from aidashvideo.ledger.canonical import as_int, as_object, as_str

ACTOR = LocalUser("tester", "session-1")
OTHER_ACTOR = LocalUser("tester", "session-2")
PROJECT = ProjectId("counter-project")


@dataclass(frozen=True)
class CounterDomain:
    version: int = 1

    @property
    def document_schema_version(self) -> int:
        return self.version

    def revision_id(self, document: bytes, parent: ParentRef, project_id: ProjectId) -> RevisionId:
        digest = canonical_sha256(
            {
                "parent": parent.to_json(),
                "project": project_id.value,
                "document": parse_json(document),
            }
        )
        return RevisionId(digest.hex)

    def validate_document(self, document: bytes, schema_version: int) -> Valid | Rejected:
        data = as_object(parse_json(document), "doc")
        if schema_version != self.version:
            return Rejected.make(RejectCode.UNSUPPORTED_SCHEMA, "schema mismatch")
        if self.version >= 2 and data.get("v") != self.version:
            return Rejected.make(RejectCode.VALIDATION, "missing v marker")
        n = as_int(data["n"], "n")
        if n < 0:
            return Rejected.make(RejectCode.VALIDATION, "counter below zero")
        return Valid()

    def apply(
        self,
        base_document: bytes,
        base_schema_version: int,
        envelope: BatchEnvelope,
        history: HistoryView,
    ) -> Accepted | Rejected:
        body = envelope.parse_body()
        doc = as_object(parse_json(base_document), "doc")
        n = as_int(doc["n"], "n")
        for pre in body.preconditions:
            p = as_object(pre, "pre")
            if (
                p["kind"] == "Exists"
                and p["object_ref"] == "counter"
                and as_str(p["version"], "version") != str(n)
            ):
                return Rejected.make(
                    RejectCode.PRECONDITION_FAILED, f"counter is at {n}", ("counter",)
                )
        intents: list[IntentRequest] = []
        artifacts: list[Sha256] = []
        inverse: list[object] = []
        for raw in body.operations:
            op = as_object(raw, "op")
            kind = as_str(op["op"], "op")
            if kind == "add":
                k = as_int(op["k"], "k")
                n += k
                inverse.insert(0, {"op": "add", "k": -k})
            elif kind == "intent":
                intents.append(
                    IntentRequest(
                        IntentId(as_str(op["id"], "id")),
                        IntentKind.EFFECT,
                        {"effect": as_str(op["id"], "id"), "n": n},
                        600,
                    )
                )
            elif kind == "artifact":
                artifacts.append(Sha256(as_str(op["sha256"], "sha256")))
            elif kind == "boom":
                return Rejected.make(RejectCode.VALIDATION, "boom is never valid")
            else:
                return Rejected.make(RejectCode.MALFORMED_BATCH, f"unknown op {kind}")
        if n < 0:
            return Rejected.make(RejectCode.VALIDATION, "counter would go below zero")
        new_doc: dict[str, object] = {"n": n}
        if self.version >= 2:
            new_doc["v"] = self.version
        document = canonical_bytes(new_doc)
        return Accepted(
            document,
            self.revision_id(document, _parent(envelope.base_revision), envelope.project_id),
            self.version,
            canonical_bytes(list(body.operations)),
            canonical_bytes(inverse),
            ("counter",),
            tuple(intents),
            tuple(artifacts),
        )

    def import_snapshot(
        self, snapshot: bytes
    ) -> ImportedDocument | InvalidSnapshot | UnsupportedSchema:
        try:
            data = as_object(parse_json(snapshot), "snapshot")
            if data.get("$id") != "counter-snapshot/1":
                return InvalidSnapshot(
                    Rejected.make(RejectCode.VALIDATION, "not a counter snapshot").contract_reason
                )
            version = as_int(data.get("schema_version", 1), "schema_version")
            if version > self.version:
                return UnsupportedSchema(version, self.version)
            n = as_int(data["n"], "n")
        except Exception as exc:
            return InvalidSnapshot(Rejected.make(RejectCode.VALIDATION, str(exc)).contract_reason)
        doc: dict[str, object] = {"n": n}
        if self.version >= 2:
            doc["v"] = self.version
        return ImportedDocument(
            canonical_bytes(doc),
            self.version,
            ProjectId(f"import-{sha256_of(snapshot).hex[:24]}"),
            {"snapshot_sha256": sha256_of(snapshot).hex},
        )

    def migrate_document(
        self, document: bytes, from_version: int, to_version: int
    ) -> Migrated | Rejected:
        if (from_version, to_version) != (1, 2) or self.version != 2:
            return Rejected.make(RejectCode.NO_MIGRATION_PATH, f"{from_version}->{to_version}")
        data = as_object(parse_json(document), "doc")
        data["v"] = 2
        return Migrated(canonical_bytes(data), 2)


def _parent(revision_id: RevisionId) -> ParentRef:
    return Parent(revision_id)


def open_store(
    project_dir: Path,
    *,
    domain: CounterDomain | None = None,
    create: bool = True,
    faults: Callable[[str], None] | None = None,
    grant: ProjectGrant | None = None,
) -> tuple[Ledger, ProjectGrant]:
    grant = grant or issue_project_grant(project_dir, ACTOR)
    opened = Ledger.open(
        project_dir, grant, domain or CounterDomain(), create=create, faults=faults
    )
    assert isinstance(opened, Opened), opened
    return opened.ledger, grant


def new_project(ledger: Ledger, n: int = 0) -> None:
    result = ledger.create_lineage(
        PROJECT,
        canonical_bytes(
            {"n": n} if ledger.domain.document_schema_version == 1 else {"n": n, "v": 2}
        ),
        ledger.domain.document_schema_version,
        kind="canonical",
        replay_key=ReplayKey("create:counter-project"),
        provenance={"kind": "NewProject"},
        origin={"kind": "NewProject"},
        source_bytes=canonical_bytes({"new": "counter-project"}),
    )
    assert type(result).__name__ == "Applied", result


def envelope(
    ledger: Ledger,
    operations: list[object],
    *,
    key: str = "key-0123456789abcdef",
    base: RevisionId | None = None,
    actor: LocalUser = ACTOR,
    preconditions: list[object] | None = None,
    text: str = "add one",
) -> BatchEnvelope:
    return BatchEnvelope.build(
        actor=actor,
        project_id=PROJECT,
        base_revision=base or ledger.head().revision_id,
        replay_key=ReplayKey(key),
        preconditions=preconditions or [],
        operations=operations,
        provenance=UserWording(text),
    )


def counter_of(ledger: Ledger, project_id: ProjectId = PROJECT) -> int:
    snap = ledger.snapshot(ledger.head_of(project_id).revision_id)
    assert isinstance(snap, RevisionSnapshot)
    return as_int(as_object(parse_json(snap.document), "doc")["n"], "n")


def event_count(ledger: Ledger) -> int:
    return len(ledger.all_events())
