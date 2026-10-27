"""The canonical admission owner (contracts §1, §5; implementation plan M1a).

Only this module opens ``project.sqlite`` for writing. One admission is one
``BEGIN IMMEDIATE`` transaction preceded by sealing the payload bytes into the CAS:

1. seal the resulting document, the batch, the applied operations and the inverse
   (filesystem facts without authority);
2. validate through the domain port (the complete resulting project) - done before
   sealing, because a rejected batch must write nothing;
3. ``INSERT operation_events``; ``INSERT revisions``; ``UPDATE heads ... WHERE
   head_revision_id = :expected`` (row count must be 1, else ``ROLLBACK`` and
   ``RevisionConflict``); ``INSERT idempotency``; ``INSERT intents`` and ``outbox``;
   ``COMMIT``.

A database transaction does not make the CAS writes atomic: an orphan blob (crash
between 1 and 3) is readable but has no admission authority because no committed row
references it. Fault hooks (``faults``) exist only so V12 can inject crashes at the named
points; production callers pass none.
"""

from __future__ import annotations

import datetime as _dt
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .canonical import as_list, as_object, as_str, canonical_bytes, parse_json, sha256_of
from .cas import BlobPresent, CasRoot
from .domain import (
    BatchEnvelope,
    DomainPort,
    EventMissing,
    EventRecord,
    HistoryView,
    ImportedDocument,
    IntentRequest,
    RevisionMissing,
    Valid,
)
from .errors import ContractError, InvariantViolation
from .grants import Grant, LocalUser, ProjectGrant
from .ids import (
    EventKind,
    EventSeq,
    Generation,
    IntentId,
    IntentKind,
    IntentState,
    Parent,
    ParentRef,
    ProjectId,
    ReplayKey,
    RevisionId,
    Root,
    Sha256,
    intent_transition_allowed,
    parent_from_json,
)
from .results import (
    AdmittedEvent,
    AdmittedRevision,
    AlreadyApplied,
    Applied,
    ApplyResult,
    Corrupt,
    Denied,
    Fenced,
    ImportResult,
    InvalidSnapshot,
    NewLineage,
    OpenMode,
    ReadOnly,
    RejectCode,
    Rejected,
    RejectReason,
    RevisionConflict,
    UnsupportedSchema,
    Writable,
)
from .schema import DB_FILENAME, DDL, LEDGER_MIN_READER_VERSION, LEDGER_WRITER_VERSION

MAX_PAYLOAD_BYTES = 64 * 1024 * 1024  # contracts §10: payload at most 64 MiB per revision
BUSY_TIMEOUT_S = 5.0  # contracts §10
FAULT_POINTS = ("before_seal", "after_seal", "before_commit", "after_commit")
SYSTEM_ACTOR = LocalUser("ledger", "system")

type FaultHook = Callable[[str], None]


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="microseconds")


def _dumps(value: object) -> str:
    return canonical_bytes(value).decode("utf-8")


# ----------------------------------------------------------------------------- records


@dataclass(frozen=True, slots=True)
class Opened:
    ledger: Ledger
    mode: OpenMode


type OpenResult = Opened | Fenced | Denied | Corrupt


@dataclass(frozen=True, slots=True)
class RevisionSnapshot:
    revision: AdmittedRevision
    document: bytes


@dataclass(frozen=True, slots=True)
class IntentRecord:
    intent_id: IntentId
    project_id: ProjectId
    kind: IntentKind
    revision_id: RevisionId
    generation: Generation
    state: IntentState
    spec: dict[str, object]
    limits: dict[str, object]
    deadline_s: int
    created_event: EventSeq
    updated_event: EventSeq

    def to_json(self) -> dict[str, object]:
        return {
            "intent_id": self.intent_id.value,
            "project_id": self.project_id.value,
            "kind": self.kind.value,
            "revision_id": self.revision_id.hex,
            "generation": self.generation.value,
            "state": self.state.value,
            "spec": self.spec,
            "limits": self.limits,
            "deadline_s": self.deadline_s,
            "created_event": self.created_event.value,
            "updated_event": self.updated_event.value,
        }


@dataclass(frozen=True, slots=True)
class OutboxRow:
    seq: int
    intent_id: IntentId
    transition: IntentState
    event_seq: EventSeq
    generation: Generation
    payload: dict[str, object]

    def to_json(self) -> dict[str, object]:
        return {
            "seq": self.seq,
            "intent_id": self.intent_id.value,
            "transition": self.transition.value,
            "event_seq": self.event_seq.value,
            "generation": self.generation.value,
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    sha256: Sha256
    kind: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class IntentFact:
    """A worker/supervisor observation about an intent, admitted with its generation."""

    intent_id: IntentId
    generation: Generation
    target_state: IntentState
    receipt: dict[str, object]
    kind: EventKind = EventKind.JOB_FACT

    def __post_init__(self) -> None:
        if self.kind not in (EventKind.JOB_FACT, EventKind.EFFECT_FACT):
            raise ContractError("IntentFact.kind must be JobFact or EffectFact")
        canonical_bytes(self.receipt)


@dataclass(frozen=True, slots=True)
class FactRecorded:
    event: AdmittedEvent
    intent: IntentRecord


type FactResult = FactRecorded | Rejected


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """Target versions for :meth:`Ledger.migrate`; additive unless ``backup_copy`` is set."""

    target_document_version: int
    target_writer_version: int = LEDGER_WRITER_VERSION
    target_min_reader_version: int = LEDGER_MIN_READER_VERSION
    backup_copy: bool = False

    def __post_init__(self) -> None:
        if self.target_min_reader_version > self.target_writer_version:
            raise ContractError("MigrationPlan: min_reader cannot exceed writer version")
        if self.target_writer_version > LEDGER_WRITER_VERSION:
            raise ContractError("MigrationPlan: this code cannot write a newer ledger version")


@dataclass(frozen=True, slots=True)
class MigrationApplied:
    revisions: tuple[AdmittedRevision, ...]
    events: tuple[AdmittedEvent, ...]
    backup: str


@dataclass(frozen=True, slots=True)
class NothingToMigrate:
    pass


type MigrationResult = MigrationApplied | NothingToMigrate | Rejected


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    findings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.findings


@dataclass(frozen=True, slots=True)
class SchemaVersions:
    writer_version: int
    min_reader_version: int


# ----------------------------------------------------------------------------- ledger


class _History(HistoryView):
    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def event(self, seq: EventSeq) -> EventRecord | EventMissing:
        return self._ledger.event(seq)

    def revision(self, revision_id: RevisionId) -> AdmittedRevision | RevisionMissing:
        return self._ledger.revision(revision_id)

    def payload(self, sha256: Sha256) -> bytes:
        return self._ledger.cas.read(sha256)

    def events_after(self, project_id: ProjectId, seq: EventSeq) -> tuple[EventRecord, ...]:
        return tuple(e for e in self._ledger.events(project_id) if e.seq.value > seq.value)


class Ledger:
    """One open store. Construct through :meth:`open`; never share across threads."""

    def __init__(
        self,
        project_dir: Path,
        grant: ProjectGrant,
        domain: DomainPort,
        conn: sqlite3.Connection,
        mode: OpenMode,
        faults: FaultHook,
    ) -> None:
        self.project_dir = project_dir
        self.grant = grant
        self.domain = domain
        self._conn = conn
        self.mode = mode
        self._faults = faults
        self.cas = CasRoot(project_dir / "cas")

    # ------------------------------------------------------------------ open/close

    @classmethod
    def open(
        cls,
        project_dir: Path,
        grant: Grant,
        domain: DomainPort,
        *,
        create: bool = False,
        faults: FaultHook | None = None,
    ) -> OpenResult:
        if not isinstance(grant, ProjectGrant):
            return Denied(
                RejectReason.make(RejectCode.UNAUTHORIZED, "opening a project needs a ProjectGrant")
            )
        project_dir = project_dir.resolve()
        if grant.project_dir.resolve() != project_dir:
            return Denied(
                RejectReason.make(RejectCode.UNAUTHORIZED, "grant is for another project directory")
            )
        db = project_dir / DB_FILENAME
        if not db.is_file():
            if not create:
                return Denied(
                    RejectReason.make(
                        RejectCode.UNKNOWN_PROJECT, f"no {DB_FILENAME} in {project_dir}"
                    )
                )
            project_dir.mkdir(parents=True, exist_ok=True)
            conn = _connect(db, read_only=False)
            try:
                conn.executescript(DDL)
                conn.execute(
                    "INSERT OR IGNORE INTO schema_version(id, writer_version, min_reader_version)"
                    " VALUES (1, ?, ?)",
                    (LEDGER_WRITER_VERSION, LEDGER_MIN_READER_VERSION),
                )
            finally:
                conn.close()
        conn = _connect(db, read_only=True)
        try:
            row = conn.execute(
                "SELECT writer_version, min_reader_version FROM schema_version WHERE id = 1"
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            conn.close()
            return Corrupt((f"schema_version unreadable: {exc}",))
        if row is None:
            conn.close()
            return Corrupt(("schema_version row missing",))
        writer_version, min_reader = int(row[0]), int(row[1])
        if min_reader > LEDGER_WRITER_VERSION:
            conn.close()
            return Fenced(writer_version, min_reader, LEDGER_WRITER_VERSION)
        mode: OpenMode
        if writer_version > LEDGER_WRITER_VERSION:
            mode = ReadOnly(
                RejectReason.make(
                    RejectCode.UNSUPPORTED_SCHEMA,
                    f"written by ledger version {writer_version} > supported "
                    f"{LEDGER_WRITER_VERSION}; readable, not writable",
                )
            )
        else:
            conn.close()
            conn = _connect(db, read_only=False)
            mode = Writable()
        ledger = cls(
            project_dir, grant, domain, conn, mode, faults if faults is not None else _no_faults
        )
        if isinstance(mode, Writable):
            ledger.cas.ensure()
        report = ledger.verify(deep=False)
        if not report.ok:
            ledger.close()
            return Corrupt(report.findings)
        return Opened(ledger, mode)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ guards

    def _fault(self, point: str) -> None:
        if point not in FAULT_POINTS:
            raise InvariantViolation(f"unknown fault point {point}")
        self._faults(point)

    def _begin(self) -> Rejected | None:
        """``BEGIN IMMEDIATE``; a store held by another writer past the busy timeout is an
        expected unavailability, reported as a typed result rather than an exception."""
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            return Rejected.make(
                RejectCode.STORE_BUSY,
                f"another writer holds the store beyond the {BUSY_TIMEOUT_S:.0f} s busy timeout:"
                f" {exc}; nothing was written",
            )
        return None

    def _writable(self) -> Rejected | None:
        if isinstance(self.mode, ReadOnly):
            return Rejected(self.mode.reason)
        return None

    def _authorize(self, actor: LocalUser, grant: Grant) -> Rejected | None:
        if not isinstance(grant, ProjectGrant):
            return Rejected.make(
                RejectCode.UNAUTHORIZED, f"{type(grant).__name__} does not authorize edits"
            )
        if grant.grant_id != self.grant.grant_id or grant.project_dir.resolve() != self.project_dir:
            return Rejected.make(
                RejectCode.UNAUTHORIZED, "grant is not the one this store was opened with"
            )
        if grant.actor != self.grant.actor:
            return Rejected.make(
                RejectCode.UNAUTHORIZED, "grant actor differs from the opening actor"
            )
        if actor != grant.actor:
            return Rejected.make(RejectCode.UNAUTHORIZED, "batch actor is not the granted actor")
        return None

    # ------------------------------------------------------------------ reads

    def schema_versions(self) -> SchemaVersions:
        row = self._conn.execute(
            "SELECT writer_version, min_reader_version FROM schema_version WHERE id = 1"
        ).fetchone()
        if row is None:
            raise InvariantViolation("schema_version row missing")
        return SchemaVersions(int(row[0]), int(row[1]))

    def canonical_project(self) -> ProjectId | None:
        row = self._conn.execute(
            "SELECT project_id FROM lineages WHERE kind = 'canonical'"
            " ORDER BY created_event LIMIT 1"
        ).fetchone()
        return None if row is None else ProjectId(str(row[0]))

    def lineages(self) -> tuple[ProjectId, ...]:
        rows = self._conn.execute(
            "SELECT project_id FROM lineages ORDER BY created_event"
        ).fetchall()
        return tuple(ProjectId(str(r[0])) for r in rows)

    def head(self) -> AdmittedRevision:
        """Head of the canonical lineage (the project of record)."""
        project_id = self.canonical_project()
        if project_id is None:
            raise InvariantViolation("store has no canonical lineage")
        return self.head_of(project_id)

    def head_of(self, project_id: ProjectId) -> AdmittedRevision:
        head_id = self._head_id(project_id)
        if head_id is None:
            raise InvariantViolation(f"lineage {project_id} has no head")
        found = self.revision(head_id)
        if isinstance(found, RevisionMissing):
            raise InvariantViolation(f"head {head_id} of {project_id} has no revision row")
        return found

    def _head_id(self, project_id: ProjectId) -> RevisionId | None:
        row = self._conn.execute(
            "SELECT head_revision_id FROM heads WHERE project_id = ?", (project_id.value,)
        ).fetchone()
        return None if row is None else RevisionId(str(row[0]))

    def revision(self, revision_id: RevisionId) -> AdmittedRevision | RevisionMissing:
        row = self._conn.execute(
            "SELECT revision_id, project_id, parent_id, payload_sha256, admitted_event_id,"
            " schema_version FROM revisions WHERE revision_id = ?",
            (revision_id.hex,),
        ).fetchone()
        if row is None:
            return RevisionMissing(revision_id)
        return AdmittedRevision(
            RevisionId(str(row[0])),
            ProjectId(str(row[1])),
            parent_from_json(str(row[2])),
            Sha256(str(row[3])),
            EventSeq(int(row[4])),
            int(row[5]),
        )

    def snapshot(self, revision_id: RevisionId) -> RevisionSnapshot | RevisionMissing:
        """Verified read of one immutable revision and its document bytes."""
        found = self.revision(revision_id)
        if isinstance(found, RevisionMissing):
            return found
        return RevisionSnapshot(found, self.cas.read(found.payload_sha256))

    def lineage(self, revision_id: RevisionId) -> tuple[AdmittedRevision, ...]:
        """Root-first chain of revisions ending at ``revision_id``."""
        chain: list[AdmittedRevision] = []
        seen: set[str] = set()
        current: ParentRef = Parent(revision_id)
        while isinstance(current, Parent):
            if current.revision_id.hex in seen:
                raise InvariantViolation("revision parent chain has a cycle")
            seen.add(current.revision_id.hex)
            found = self.revision(current.revision_id)
            if isinstance(found, RevisionMissing):
                raise InvariantViolation(
                    f"lineage refers to missing revision {current.revision_id}"
                )
            chain.append(found)
            current = found.parent
        chain.reverse()
        return tuple(chain)

    def event(self, seq: EventSeq) -> EventRecord | EventMissing:
        row = self._conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM operation_events WHERE seq = ?", (seq.value,)
        ).fetchone()
        return EventMissing(seq) if row is None else _event_from_row(row)

    def events(self, project_id: ProjectId) -> tuple[EventRecord, ...]:
        rows = self._conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM operation_events WHERE project_id = ? ORDER BY seq",
            (project_id.value,),
        ).fetchall()
        return tuple(_event_from_row(r) for r in rows)

    def all_events(self) -> tuple[EventRecord, ...]:
        rows = self._conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM operation_events ORDER BY seq"
        ).fetchall()
        return tuple(_event_from_row(r) for r in rows)

    def history(self) -> HistoryView:
        return _History(self)

    def intent(self, intent_id: IntentId) -> IntentRecord | None:
        row = self._conn.execute(
            f"SELECT {_INTENT_COLUMNS} FROM intents WHERE intent_id = ?", (intent_id.value,)
        ).fetchone()
        return None if row is None else _intent_from_row(row)

    def intents(self) -> tuple[IntentRecord, ...]:
        rows = self._conn.execute(
            f"SELECT {_INTENT_COLUMNS} FROM intents ORDER BY created_event"
        ).fetchall()
        return tuple(_intent_from_row(r) for r in rows)

    def pending_outbox(self) -> tuple[OutboxRow, ...]:
        rows = self._conn.execute(
            "SELECT seq, intent_id, transition, event_seq, generation, payload_json FROM outbox"
            " ORDER BY seq"
        ).fetchall()
        return tuple(_outbox_from_row(r) for r in rows)

    def dispatched_outbox(self) -> tuple[OutboxRow, ...]:
        rows = self._conn.execute(
            "SELECT seq, intent_id, transition, event_seq, generation, payload_json"
            " FROM outbox_done ORDER BY seq"
        ).fetchall()
        return tuple(_outbox_from_row(r) for r in rows)

    def artifact(self, sha256: Sha256) -> ArtifactRef | None:
        row = self._conn.execute(
            "SELECT sha256, kind, size_bytes FROM artifacts WHERE sha256 = ?", (sha256.hex,)
        ).fetchone()
        return None if row is None else ArtifactRef(Sha256(str(row[0])), str(row[1]), int(row[2]))

    def artifacts(self, kind: str) -> tuple[ArtifactRef, ...]:
        rows = self._conn.execute(
            "SELECT sha256, kind, size_bytes FROM artifacts WHERE kind = ? ORDER BY rowid", (kind,)
        ).fetchall()
        return tuple(ArtifactRef(Sha256(str(r[0])), str(r[1]), int(r[2])) for r in rows)

    def artifacts_by_semantic_key(self, semantic_key: str) -> tuple[ArtifactRef, ...]:
        rows = self._conn.execute(
            "SELECT sha256, kind, size_bytes FROM artifacts WHERE semantic_key = ? ORDER BY rowid",
            (semantic_key,),
        ).fetchall()
        return tuple(ArtifactRef(Sha256(str(r[0])), str(r[1]), int(r[2])) for r in rows)

    def idempotency_record(self, replay_key: ReplayKey) -> tuple[Sha256, Applied] | None:
        row = self._conn.execute(
            "SELECT payload_sha256, result_json FROM idempotency WHERE replay_key = ?",
            (replay_key.value,),
        ).fetchone()
        if row is None:
            return None
        return Sha256(str(row[0])), Applied.from_json(parse_json(str(row[1]).encode("utf-8")))

    # ------------------------------------------------------------------ integrity

    def verify(self, *, deep: bool) -> IntegrityReport:
        """Detect foreign writes: every head must be the result of its latest event and
        every referenced payload must hash to its name (``deep`` checks every revision)."""
        findings: list[str] = []
        for project_id in self.lineages():
            head_id = self._head_id(project_id)
            if head_id is None:
                findings.append(f"{project_id}: no head row")
                continue
            found = self.revision(head_id)
            if isinstance(found, RevisionMissing):
                findings.append(f"{project_id}: head {head_id} has no revision row")
                continue
            if found.project_id != project_id:
                findings.append(f"{project_id}: head {head_id} belongs to {found.project_id}")
            status = self.cas.status(found.payload_sha256)
            if not isinstance(status, BlobPresent):
                findings.append(
                    f"{project_id}: head payload {found.payload_sha256} {type(status).__name__}"
                )
            last = self._conn.execute(
                "SELECT result_revision FROM operation_events WHERE project_id = ?"
                " AND kind IN ('Edit','Undo','Import','Rebind','EffectFact','Migration')"
                " ORDER BY seq DESC LIMIT 1",
                (project_id.value,),
            ).fetchone()
            if last is None or str(last[0]) != head_id.hex:
                findings.append(
                    f"{project_id}: head {head_id.hex[:12]} is not the result of the latest"
                    " admitted event"
                )
            admitting = self.event(found.admitted_event_id)
            if isinstance(admitting, EventMissing) or admitting.result_revision != head_id:
                findings.append(
                    f"{project_id}: head revision's admitting event does not produce it"
                )
            if deep:
                try:
                    chain = self.lineage(head_id)
                except InvariantViolation as exc:
                    findings.append(f"{project_id}: {exc}")
                    continue
                for rev in chain:
                    if not isinstance(self.cas.status(rev.payload_sha256), BlobPresent):
                        findings.append(
                            f"{project_id}: payload of {rev.revision_id.hex[:12]} unreadable"
                        )
                    ev = self.event(rev.admitted_event_id)
                    if isinstance(ev, EventMissing) or ev.result_revision != rev.revision_id:
                        findings.append(
                            f"{project_id}: revision {rev.revision_id.hex[:12]} lacks its event"
                        )
        return IntegrityReport(tuple(findings))

    def referenced_blobs(self) -> set[Sha256]:
        out: set[Sha256] = set()
        for row in self._conn.execute("SELECT payload_sha256 FROM revisions").fetchall():
            out.add(Sha256(str(row[0])))
        for row in self._conn.execute(
            "SELECT batch_sha256, applied_sha256, inverse_sha256 FROM operation_events"
        ).fetchall():
            out.update(Sha256(str(c)) for c in row)
        for row in self._conn.execute("SELECT sha256 FROM artifacts").fetchall():
            out.add(Sha256(str(row[0])))
        return out

    # ------------------------------------------------------------------ artifacts

    def seal_artifact(
        self,
        data: bytes,
        kind: str,
        producer: dict[str, object],
        deps: tuple[Sha256, ...],
        semantic_key: str,
    ) -> ArtifactRef | Rejected:
        """Seal bytes into the CAS and index them (outside any head transaction)."""
        denied = self._writable()
        if denied is not None:
            return denied
        for dep in deps:
            if self.artifact(dep) is None:
                return Rejected.make(
                    RejectCode.UNKNOWN_ARTIFACT, f"dependency {dep} is not indexed"
                )
        digest = self.cas.seal(data)
        busy = self._begin()
        if busy is not None:
            return busy
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO artifacts(sha256, kind, size_bytes, producer_json,"
                " deps_json, semantic_key) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    digest.hex,
                    kind,
                    len(data),
                    _dumps(producer),
                    _dumps([d.hex for d in deps]),
                    semantic_key,
                ),
            )
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        return ArtifactRef(digest, kind, len(data))

    # ------------------------------------------------------------------ lineage creation

    def create_lineage(
        self,
        project_id: ProjectId,
        document: bytes,
        schema_version: int,
        *,
        kind: str,
        replay_key: ReplayKey,
        provenance: dict[str, object],
        origin: dict[str, object],
        source_bytes: bytes,
    ) -> ApplyResult:
        """Admit a root revision (new project or imported lineage) in one transaction."""
        denied = self._writable()
        if denied is not None:
            return denied
        if kind not in ("canonical", "import"):
            raise InvariantViolation(f"unknown lineage kind {kind}")
        if kind == "canonical" and self.canonical_project() is not None:
            return Rejected.make(
                RejectCode.DUPLICATE_OBJECT, "store already has a canonical lineage"
            )
        if len(document) > MAX_PAYLOAD_BYTES:
            return Rejected.make(RejectCode.PAYLOAD_TOO_LARGE, "document exceeds 64 MiB")
        replay = self.idempotency_record(replay_key)
        if replay is not None:
            recorded_sha, original = replay
            return (
                AlreadyApplied(original)
                if recorded_sha == sha256_of(source_bytes)
                else Rejected.make(
                    RejectCode.REPLAY_KEY_CONFLICT, "replay key used with other bytes"
                )
            )
        check = self.domain.validate_document(document, schema_version)
        if isinstance(check, Rejected):
            return check
        revision_id = self.domain.revision_id(document, Root(), project_id)
        if not isinstance(self.revision(revision_id), RevisionMissing):
            return Rejected.make(
                RejectCode.DUPLICATE_OBJECT, f"revision {revision_id} already exists"
            )
        self._fault("before_seal")
        doc_sha = self.cas.seal(document)
        batch_sha = self.cas.seal(source_bytes)
        empty_sha = self.cas.seal(canonical_bytes([]))
        self._fault("after_seal")
        busy = self._begin()
        if busy is not None:
            return busy
        try:
            replay = self.idempotency_record(replay_key)
            if replay is not None:
                self._conn.execute("ROLLBACK")
                recorded_sha, original = replay
                if recorded_sha == sha256_of(source_bytes):
                    return AlreadyApplied(original)
                return Rejected.make(RejectCode.REPLAY_KEY_CONFLICT, "replay key raced")
            if self._conn.execute(
                "SELECT 1 FROM lineages WHERE project_id = ?", (project_id.value,)
            ).fetchone():
                self._conn.execute("ROLLBACK")
                return Rejected.make(RejectCode.DUPLICATE_OBJECT, f"lineage {project_id} exists")
            self._conn.execute(
                "INSERT INTO lineages(project_id, kind, created_event, origin_json)"
                " VALUES (?, ?, 0, ?)",
                (project_id.value, kind, _dumps(origin)),
            )
            seq = self._insert_event(
                project_id,
                EventKind.IMPORT,
                SYSTEM_ACTOR,
                "root",
                revision_id,
                batch_sha,
                empty_sha,
                empty_sha,
                provenance,
                (),
                replay_key.value,
                (),
            )
            self._conn.execute(
                "UPDATE lineages SET created_event = ? WHERE project_id = ?",
                (seq.value, project_id.value),
            )
            self._insert_revision(revision_id, project_id, Root(), doc_sha, seq, schema_version)
            self._conn.execute(
                "INSERT INTO heads(project_id, head_revision_id) VALUES (?, ?)",
                (project_id.value, revision_id.hex),
            )
            applied = Applied(
                AdmittedRevision(revision_id, project_id, Root(), doc_sha, seq, schema_version),
                AdmittedEvent(seq, EventKind.IMPORT, project_id, revision_id, (), ()),
            )
            self._insert_idempotency(replay_key, sha256_of(source_bytes), applied)
            self._fault("before_commit")
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._fault("after_commit")
        return applied

    def import_snapshot(self, snapshot: bytes) -> ImportResult:
        """Validate a portable file and admit it as a **new lineage** (never the canonical head)."""
        if isinstance(self.mode, ReadOnly):
            return InvalidSnapshot(self.mode.reason)
        imported = self.domain.import_snapshot(snapshot)
        if isinstance(imported, InvalidSnapshot | UnsupportedSchema):
            return imported
        assert isinstance(imported, ImportedDocument)
        snapshot_sha = sha256_of(snapshot)
        existing_head = self._head_id(imported.project_id)
        if existing_head is not None:
            # Same bytes imported twice: the lineage already exists; no duplicate lineage/revision.
            chain = self.lineage(existing_head)
            return NewLineage(chain[0])
        result = self.create_lineage(
            imported.project_id,
            imported.document,
            imported.schema_version,
            kind="import",
            replay_key=ReplayKey(f"import:{snapshot_sha.hex}"),
            provenance={"kind": "ImportSnapshot", "snapshot_sha256": snapshot_sha.hex},
            origin=imported.origin,
            source_bytes=snapshot,
        )
        match result:
            case Applied(revision, _):
                return NewLineage(revision)
            case AlreadyApplied(original):
                return NewLineage(original.revision)
            case Rejected(reason):
                return InvalidSnapshot(reason)
            case RevisionConflict(_):
                raise InvariantViolation("a root admission cannot conflict on a head")

    # ------------------------------------------------------------------ admission

    def admit(self, envelope: BatchEnvelope, grant: Grant) -> ApplyResult:
        """The single admission boundary (contracts §5); see the module docstring."""
        denied = self._authorize(envelope.actor, grant) or self._writable()
        if denied is not None:
            return denied
        if len(envelope.payload) > MAX_PAYLOAD_BYTES:
            return Rejected.make(RejectCode.PAYLOAD_TOO_LARGE, "batch payload exceeds 64 MiB")
        try:
            envelope.parse_body()
        except ContractError as exc:
            code = (
                RejectCode.PAYLOAD_HASH_MISMATCH
                if "payload_sha256" in str(exc)
                else RejectCode.MALFORMED_BATCH
            )
            return Rejected.make(code, str(exc))
        replay = self._check_replay(envelope)
        if replay is not None:
            return replay
        if (
            self._conn.execute(
                "SELECT 1 FROM lineages WHERE project_id = ?", (envelope.project_id.value,)
            ).fetchone()
            is None
        ):
            return Rejected.make(
                RejectCode.UNKNOWN_PROJECT, f"unknown lineage {envelope.project_id}"
            )
        base = self.revision(envelope.base_revision)
        if isinstance(base, RevisionMissing) or base.project_id != envelope.project_id:
            return Rejected.make(
                RejectCode.UNKNOWN_REVISION,
                f"base revision {envelope.base_revision} is not in this lineage",
            )
        current = self._head_id(envelope.project_id)
        if current is None:
            raise InvariantViolation(f"lineage {envelope.project_id} has no head")
        if current != base.revision_id:
            return RevisionConflict(current)
        if base.schema_version != self.domain.document_schema_version:
            return Rejected.make(
                RejectCode.MIGRATION_REQUIRED,
                f"base document schema {base.schema_version} differs from the writer's"
                f" {self.domain.document_schema_version}; run Ledger.migrate first",
            )
        outcome = self.domain.apply(
            self.cas.read(base.payload_sha256), base.schema_version, envelope, self.history()
        )
        if isinstance(outcome, Rejected):
            return outcome
        if outcome.schema_version != self.domain.document_schema_version:
            raise InvariantViolation("domain produced a document of an unexpected schema version")
        if len(outcome.document) > MAX_PAYLOAD_BYTES:
            return Rejected.make(RejectCode.PAYLOAD_TOO_LARGE, "resulting document exceeds 64 MiB")
        for sha in outcome.artifacts:
            if self.artifact(sha) is None or not self.cas.exists(sha):
                return Rejected.make(RejectCode.UNKNOWN_ARTIFACT, f"artifact {sha} is not sealed")
        if not isinstance(self.revision(outcome.revision_id), RevisionMissing):
            raise InvariantViolation(
                f"domain produced an existing revision id {outcome.revision_id}"
            )
        # 1. seal payload bytes first (no authority yet)
        self._fault("before_seal")
        doc_sha = self.cas.seal(outcome.document)
        batch_sha = self.cas.seal(envelope.payload)
        applied_sha = self.cas.seal(outcome.applied_operations)
        inverse_sha = self.cas.seal(outcome.inverse)
        self._fault("after_seal")
        # 3. one transaction
        busy = self._begin()
        if busy is not None:
            return busy
        try:
            replay = self._check_replay(envelope)
            if replay is not None:
                self._conn.execute("ROLLBACK")
                return replay
            provenance = as_object(
                as_object(parse_json(envelope.payload), "batch")["provenance"], "provenance"
            )
            seq = self._insert_event(
                envelope.project_id,
                envelope.kind,
                envelope.actor,
                base.revision_id.hex,
                outcome.revision_id,
                batch_sha,
                applied_sha,
                inverse_sha,
                provenance,
                outcome.affected_objects,
                envelope.replay_key.value,
                tuple(i.intent_id for i in outcome.intents),
            )
            self._insert_revision(
                outcome.revision_id,
                envelope.project_id,
                Parent(base.revision_id),
                doc_sha,
                seq,
                outcome.schema_version,
            )
            cur = self._conn.execute(
                "UPDATE heads SET head_revision_id = ?"
                " WHERE project_id = ? AND head_revision_id = ?",
                (outcome.revision_id.hex, envelope.project_id.value, base.revision_id.hex),
            )
            if cur.rowcount != 1:
                self._conn.execute("ROLLBACK")
                moved = self._head_id(envelope.project_id)
                if moved is None:
                    raise InvariantViolation("head row vanished during admission")
                return RevisionConflict(moved)
            applied = Applied(
                AdmittedRevision(
                    outcome.revision_id,
                    envelope.project_id,
                    Parent(base.revision_id),
                    doc_sha,
                    seq,
                    outcome.schema_version,
                ),
                AdmittedEvent(
                    seq,
                    envelope.kind,
                    envelope.project_id,
                    outcome.revision_id,
                    outcome.affected_objects,
                    tuple(i.intent_id for i in outcome.intents),
                ),
            )
            self._insert_idempotency(envelope.replay_key, envelope.payload_sha256, applied)
            for intent in outcome.intents:
                self._insert_intent(intent, envelope.project_id, outcome.revision_id, seq)
            self._fault("before_commit")
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        self._fault("after_commit")
        return applied

    def _check_replay(self, envelope: BatchEnvelope) -> ApplyResult | None:
        replay = self.idempotency_record(envelope.replay_key)
        if replay is None:
            return None
        recorded_sha, original = replay
        if recorded_sha == envelope.payload_sha256:
            return AlreadyApplied(original)
        return Rejected.make(
            RejectCode.REPLAY_KEY_CONFLICT,
            "replay key already used with a different payload; nothing applied",
        )

    # ------------------------------------------------------------------ facts and outbox

    def admit_fact(self, fact: IntentFact, grant: Grant) -> FactResult:
        """Worker/supervisor facts: generation-fenced intent transitions as events."""
        denied = self._authorize(grant.actor, grant) or self._writable()
        if denied is not None:
            return denied
        busy = self._begin()
        if busy is not None:
            return busy
        try:
            current = self.intent(fact.intent_id)
            if current is None:
                self._conn.execute("ROLLBACK")
                return Rejected.make(RejectCode.UNKNOWN_INTENT, f"unknown intent {fact.intent_id}")
            if current.generation != fact.generation:
                self._conn.execute("ROLLBACK")
                return Rejected.make(
                    RejectCode.STALE_GENERATION,
                    f"fact generation {fact.generation.value} != intent generation "
                    f"{current.generation.value}",
                )
            if not intent_transition_allowed(current.state, fact.target_state):
                self._conn.execute("ROLLBACK")
                return Rejected.make(
                    RejectCode.ILLEGAL_TRANSITION,
                    f"{current.state.value} -> {fact.target_state.value} is not allowed",
                )
            head = self._head_id(current.project_id)
            if head is None:
                raise InvariantViolation("intent's lineage has no head")
            receipt_sha = self.cas.seal(canonical_bytes(fact.receipt))
            empty_sha = self.cas.seal(canonical_bytes([]))
            seq = self._insert_event(
                current.project_id,
                fact.kind,
                grant.actor,
                head.hex,
                head,
                receipt_sha,
                empty_sha,
                empty_sha,
                {
                    "kind": "IntentFact",
                    "intent_id": fact.intent_id.value,
                    "target": fact.target_state.value,
                },
                (f"intent:{fact.intent_id.value}",),
                f"fact:{fact.intent_id.value}:{fact.generation.value}:{_now()}",
                (fact.intent_id,),
            )
            self._conn.execute(
                "UPDATE intents SET state = ?, updated_event = ? WHERE intent_id = ?",
                (fact.target_state.value, seq.value, fact.intent_id.value),
            )
            if fact.target_state is IntentState.QUEUED:
                self._conn.execute(
                    "INSERT INTO outbox(intent_id, transition, event_seq, generation, payload_json)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        fact.intent_id.value,
                        IntentState.QUEUED.value,
                        seq.value,
                        current.generation.value,
                        _dumps(current.spec),
                    ),
                )
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        updated = self.intent(fact.intent_id)
        if updated is None:
            raise InvariantViolation("intent vanished after its fact was committed")
        return FactRecorded(
            AdmittedEvent(
                seq,
                fact.kind,
                current.project_id,
                head,
                (f"intent:{fact.intent_id.value}",),
                (fact.intent_id,),
            ),
            updated,
        )

    def claim_outbox(
        self, seq: int, generation: Generation, grant: Grant, receipt: dict[str, object]
    ) -> OutboxRow | Rejected:
        """Move one outbox row to ``outbox_done``; bind the intent to the dispatching generation."""
        denied = self._authorize(grant.actor, grant) or self._writable()
        if denied is not None:
            return denied
        busy = self._begin()
        if busy is not None:
            return busy
        try:
            row = self._conn.execute(
                "SELECT seq, intent_id, transition, event_seq, generation, payload_json FROM outbox"
                " WHERE seq = ?",
                (seq,),
            ).fetchone()
            if row is None:
                self._conn.execute("ROLLBACK")
                return Rejected.make(RejectCode.UNKNOWN_INTENT, f"outbox row {seq} is not pending")
            pending = _outbox_from_row(row)
            self._conn.execute("DELETE FROM outbox WHERE seq = ?", (seq,))
            self._conn.execute(
                "INSERT INTO outbox_done(seq, intent_id, transition, event_seq, generation,"
                " payload_json, dispatched_at, receipt_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pending.seq,
                    pending.intent_id.value,
                    pending.transition.value,
                    pending.event_seq.value,
                    generation.value,
                    _dumps(pending.payload),
                    _now(),
                    _dumps(receipt),
                ),
            )
            self._conn.execute(
                "UPDATE intents SET generation = ? WHERE intent_id = ?",
                (generation.value, pending.intent_id.value),
            )
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return OutboxRow(
            pending.seq,
            pending.intent_id,
            pending.transition,
            pending.event_seq,
            generation,
            pending.payload,
        )

    # ------------------------------------------------------------------ migration

    def migrate(self, plan: MigrationPlan, grant: Grant) -> MigrationResult:
        """Move every lineage head to ``plan.target_document_version`` with new immutable
        revisions and ``Migration`` events, then record the ledger versions; one transaction.
        Prior rows and payloads are kept. A destructive (non-additive) step copies the
        database next to itself first when ``backup_copy`` is set."""
        denied = self._authorize(grant.actor, grant) or self._writable()
        if denied is not None:
            return denied
        if plan.target_document_version != self.domain.document_schema_version:
            return Rejected.make(
                RejectCode.NO_MIGRATION_PATH,
                f"domain writes document schema {self.domain.document_schema_version},"
                f" plan targets {plan.target_document_version}",
            )
        versions = self.schema_versions()
        heads = [(pid, self.head_of(pid)) for pid in self.lineages()]
        stale = [
            (pid, rev) for pid, rev in heads if rev.schema_version != plan.target_document_version
        ]
        ledger_change = (versions.writer_version, versions.min_reader_version) != (
            plan.target_writer_version,
            plan.target_min_reader_version,
        )
        if not stale and not ledger_change:
            return NothingToMigrate()
        for _pid, rev in stale:
            if rev.schema_version > plan.target_document_version:
                return Rejected.make(
                    RejectCode.NO_MIGRATION_PATH,
                    f"revision {rev.revision_id} has schema {rev.schema_version} > target",
                )
        migrated: list[tuple[ProjectId, AdmittedRevision, bytes, RevisionId]] = []
        for pid, rev in stale:
            outcome = self.domain.migrate_document(
                self.cas.read(rev.payload_sha256), rev.schema_version, plan.target_document_version
            )
            if isinstance(outcome, Rejected):
                return outcome
            check = self.domain.validate_document(outcome.document, outcome.schema_version)
            if isinstance(check, Rejected):
                return check
            assert isinstance(check, Valid)
            new_id = self.domain.revision_id(outcome.document, Parent(rev.revision_id), pid)
            migrated.append((pid, rev, outcome.document, new_id))
        backup = ""
        if plan.backup_copy:
            target = self.project_dir / f"{DB_FILENAME}.pre-{versions.writer_version}"
            if not target.exists():
                self._conn.execute("PRAGMA wal_checkpoint(FULL)")
                shutil.copy2(self.project_dir / DB_FILENAME, target)
            backup = target.name
        self._fault("before_seal")
        sealed: list[tuple[ProjectId, AdmittedRevision, Sha256, RevisionId, Sha256]] = []
        for pid, rev, doc, new_id in migrated:
            batch = canonical_bytes(
                {
                    "op": "Migrate",
                    "from_version": rev.schema_version,
                    "to_version": plan.target_document_version,
                }
            )
            sealed.append((pid, rev, self.cas.seal(doc), new_id, self.cas.seal(batch)))
        empty_sha = self.cas.seal(canonical_bytes([]))
        self._fault("after_seal")
        revisions: list[AdmittedRevision] = []
        events: list[AdmittedEvent] = []
        busy = self._begin()
        if busy is not None:
            return busy
        try:
            for pid, rev, doc_sha, new_id, batch_sha in sealed:
                if self._head_id(pid) != rev.revision_id:
                    self._conn.execute("ROLLBACK")
                    return Rejected.make(
                        RejectCode.PRECONDITION_FAILED, f"head of {pid} moved during migration"
                    )
                seq = self._insert_event(
                    pid,
                    EventKind.MIGRATION,
                    grant.actor,
                    rev.revision_id.hex,
                    new_id,
                    batch_sha,
                    batch_sha,
                    empty_sha,
                    {
                        "kind": "Migrate",
                        "from_version": rev.schema_version,
                        "to_version": plan.target_document_version,
                        "backup": backup,
                    },
                    ("document",),
                    f"migrate:{pid.value}:{rev.revision_id.hex}:{plan.target_document_version}",
                    (),
                )
                self._insert_revision(
                    new_id, pid, Parent(rev.revision_id), doc_sha, seq, plan.target_document_version
                )
                cur = self._conn.execute(
                    "UPDATE heads SET head_revision_id = ?"
                    " WHERE project_id = ? AND head_revision_id = ?",
                    (new_id.hex, pid.value, rev.revision_id.hex),
                )
                if cur.rowcount != 1:
                    raise InvariantViolation("head changed inside the migration transaction")
                revisions.append(
                    AdmittedRevision(
                        new_id,
                        pid,
                        Parent(rev.revision_id),
                        doc_sha,
                        seq,
                        plan.target_document_version,
                    )
                )
                events.append(
                    AdmittedEvent(seq, EventKind.MIGRATION, pid, new_id, ("document",), ())
                )
            self._conn.execute(
                "UPDATE schema_version SET writer_version = ?, min_reader_version = ? WHERE id = 1",
                (plan.target_writer_version, plan.target_min_reader_version),
            )
            self._fault("before_commit")
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        self._fault("after_commit")
        return MigrationApplied(tuple(revisions), tuple(events), backup)

    # ------------------------------------------------------------------ row helpers

    def _insert_event(
        self,
        project_id: ProjectId,
        kind: EventKind,
        actor: LocalUser,
        base_revision: str,
        result_revision: RevisionId,
        batch_sha: Sha256,
        applied_sha: Sha256,
        inverse_sha: Sha256,
        provenance: dict[str, object],
        affected: tuple[str, ...],
        replay_key: str,
        intent_ids: tuple[IntentId, ...],
    ) -> EventSeq:
        cur = self._conn.execute(
            "INSERT INTO operation_events(project_id, kind, actor_json, base_revision,"
            " result_revision, batch_sha256, applied_sha256, inverse_sha256, provenance_json,"
            " affected_json, replay_key, intents_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id.value,
                kind.value,
                _dumps(actor.to_json()),
                base_revision,
                result_revision.hex,
                batch_sha.hex,
                applied_sha.hex,
                inverse_sha.hex,
                _dumps(provenance),
                _dumps(list(affected)),
                replay_key,
                _dumps([i.value for i in intent_ids]),
                _now(),
            ),
        )
        if cur.lastrowid is None:
            raise InvariantViolation("operation_events insert returned no seq")
        return EventSeq(int(cur.lastrowid))

    def _insert_revision(
        self,
        revision_id: RevisionId,
        project_id: ProjectId,
        parent: ParentRef,
        payload_sha: Sha256,
        seq: EventSeq,
        schema_version: int,
    ) -> None:
        try:
            self._conn.execute(
                "INSERT INTO revisions(revision_id, project_id, parent_id, payload_sha256,"
                " admitted_event_id, schema_version) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    revision_id.hex,
                    project_id.value,
                    parent.to_json(),
                    payload_sha.hex,
                    seq.value,
                    schema_version,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise InvariantViolation(f"revision {revision_id} already exists: {exc}") from exc

    def _insert_idempotency(
        self, replay_key: ReplayKey, payload_sha: Sha256, applied: Applied
    ) -> None:
        try:
            self._conn.execute(
                "INSERT INTO idempotency(replay_key, payload_sha256, result_json) VALUES (?, ?, ?)",
                (replay_key.value, payload_sha.hex, _dumps(applied.to_json())),
            )
        except sqlite3.IntegrityError as exc:
            raise InvariantViolation(f"replay key {replay_key} raced: {exc}") from exc

    def _insert_intent(
        self, intent: IntentRequest, project_id: ProjectId, revision_id: RevisionId, seq: EventSeq
    ) -> None:
        try:
            self._conn.execute(
                "INSERT INTO intents(intent_id, project_id, kind, revision_id, generation, state,"
                " spec_json, limits_json, deadline_s, created_event, updated_event)"
                " VALUES (?, ?, ?, ?, 0, 'Queued', ?, ?, ?, ?, ?)",
                (
                    intent.intent_id.value,
                    project_id.value,
                    intent.kind.value,
                    revision_id.hex,
                    _dumps(intent.spec),
                    _dumps(intent.limits),
                    intent.deadline_s,
                    seq.value,
                    seq.value,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise InvariantViolation(f"intent {intent.intent_id} already exists: {exc}") from exc
        self._conn.execute(
            "INSERT INTO outbox(intent_id, transition, event_seq, generation, payload_json)"
            " VALUES (?, 'Queued', ?, 0, ?)",
            (intent.intent_id.value, seq.value, _dumps(intent.spec)),
        )


# ----------------------------------------------------------------------------- helpers


def _no_faults(_point: str) -> None:
    return None


def _connect(db: Path, *, read_only: bool) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(
            f"file:{db}?mode=ro", uri=True, timeout=BUSY_TIMEOUT_S, isolation_level=None
        )
    else:
        conn = sqlite3.connect(db, timeout=BUSY_TIMEOUT_S, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={int(BUSY_TIMEOUT_S * 1000)}")
    return conn


_EVENT_COLUMNS = (
    "seq, project_id, kind, actor_json, base_revision, result_revision, batch_sha256,"
    " applied_sha256, inverse_sha256, provenance_json, affected_json, replay_key, intents_json,"
    " created_at"
)
_INTENT_COLUMNS = (
    "intent_id, project_id, kind, revision_id, generation, state, spec_json, limits_json,"
    " deadline_s, created_event, updated_event"
)


def _event_from_row(row: tuple[object, ...]) -> EventRecord:
    affected = as_list(parse_json(str(row[10]).encode("utf-8")), "affected")
    intents = as_list(parse_json(str(row[12]).encode("utf-8")), "intents")
    return EventRecord(
        EventSeq(int(str(row[0]))),
        ProjectId(str(row[1])),
        EventKind(str(row[2])),
        LocalUser.from_json(parse_json(str(row[3]).encode("utf-8"))),
        str(row[4]),
        RevisionId(str(row[5])),
        Sha256(str(row[6])),
        Sha256(str(row[7])),
        Sha256(str(row[8])),
        as_object(parse_json(str(row[9]).encode("utf-8")), "provenance"),
        tuple(as_str(a, "affected[]") for a in affected),
        str(row[11]),
        tuple(IntentId(as_str(i, "intents[]")) for i in intents),
        str(row[13]),
    )


def _intent_from_row(row: tuple[object, ...]) -> IntentRecord:
    return IntentRecord(
        IntentId(str(row[0])),
        ProjectId(str(row[1])),
        IntentKind(str(row[2])),
        RevisionId(str(row[3])),
        Generation(int(str(row[4]))),
        IntentState(str(row[5])),
        as_object(parse_json(str(row[6]).encode("utf-8")), "intent.spec"),
        as_object(parse_json(str(row[7]).encode("utf-8")), "intent.limits"),
        int(str(row[8])),
        EventSeq(int(str(row[9]))),
        EventSeq(int(str(row[10]))),
    )


def _outbox_from_row(row: tuple[object, ...]) -> OutboxRow:
    return OutboxRow(
        int(str(row[0])),
        IntentId(str(row[1])),
        IntentState(str(row[2])),
        EventSeq(int(str(row[3]))),
        Generation(int(str(row[4]))),
        as_object(parse_json(str(row[5]).encode("utf-8")), "outbox.payload"),
    )
