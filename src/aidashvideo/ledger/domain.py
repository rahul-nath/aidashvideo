"""The domain port: how the ledger validates a complete resulting project without
deciding edit semantics (implementation plan §2: ``ledger`` depends on nothing above it).

``aidashvideo.project`` implements :class:`DomainPort`; the ledger calls it before any
write (contracts §5 step 2). The ledger's own tests use a trivial domain. The port sees
documents and batches as canonical bytes plus the closed header fields of the wire schema
``aidashvideo.operation-batch/1``; it returns either a complete validated result
(:class:`Accepted`) or a typed :class:`~aidashvideo.ledger.results.Rejected`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .canonical import (
    as_list,
    as_object,
    as_str,
    canonical_bytes,
    parse_json,
    require_keys,
    sha256_of,
)
from .canonical import field as json_field
from .errors import ContractError, is_int, is_str
from .grants import LocalUser
from .ids import (
    EventKind,
    EventSeq,
    IntentId,
    IntentKind,
    ParentRef,
    ProjectId,
    ReplayKey,
    RevisionId,
    Sha256,
)
from .results import AdmittedRevision, InvalidSnapshot, Rejected, UnsupportedSchema

BATCH_SCHEMA_ID = "aidashvideo.operation-batch/1"
BATCH_HEADER_KEYS = (
    "$id",
    "actor",
    "project_id",
    "base_revision",
    "preconditions",
    "operations",
    "provenance",
)
_ADMITTABLE_KINDS = frozenset(
    {EventKind.EDIT, EventKind.UNDO, EventKind.REBIND, EventKind.EFFECT_FACT}
)


@dataclass(frozen=True, slots=True)
class UserWording:
    text: str

    def to_json(self) -> dict[str, object]:
        return {"kind": "UserWording", "text": self.text}


@dataclass(frozen=True, slots=True)
class ToolCall:
    tool: str
    arguments_sha256: Sha256

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "ToolCall",
            "tool": self.tool,
            "arguments_sha256": self.arguments_sha256.hex,
        }


type Provenance = UserWording | ToolCall


def provenance_from_json(raw: object) -> Provenance:
    data = as_object(raw, "provenance")
    kind = as_str(json_field(data, "kind", "provenance"), "provenance.kind")
    if kind == "UserWording":
        require_keys(data, "provenance", ("kind", "text"))
        return UserWording(as_str(data["text"], "provenance.text"))
    if kind == "ToolCall":
        require_keys(data, "provenance", ("kind", "tool", "arguments_sha256"))
        return ToolCall(
            as_str(data["tool"], "provenance.tool"),
            Sha256(as_str(data["arguments_sha256"], "provenance.arguments_sha256")),
        )
    raise ContractError(f"provenance: unknown kind {kind!r}")


@dataclass(frozen=True, slots=True)
class BatchEnvelope:
    """Wire form of an operation batch as the ledger sees it.

    ``payload`` is the canonical JSON of the batch body (header fields, preconditions,
    operations, provenance) and ``payload_sha256`` its hash: that is the "canonical payload
    hash" of the idempotency contract. The header fields are repeated outside the payload
    so the ledger can check them without interpreting operations.
    """

    actor: LocalUser
    project_id: ProjectId
    base_revision: RevisionId
    replay_key: ReplayKey
    payload_sha256: Sha256
    kind: EventKind
    payload: bytes

    def __post_init__(self) -> None:
        if self.kind not in _ADMITTABLE_KINDS:
            raise ContractError(f"BatchEnvelope.kind {self.kind} is not admittable through admit")
        if not isinstance(self.payload, bytes):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ContractError("BatchEnvelope.payload must be bytes")

    @classmethod
    def build(
        cls,
        *,
        actor: LocalUser,
        project_id: ProjectId,
        base_revision: RevisionId,
        replay_key: ReplayKey,
        preconditions: list[object],
        operations: list[object],
        provenance: Provenance,
        kind: EventKind = EventKind.EDIT,
    ) -> BatchEnvelope:
        """Canonicalize the body, hash it and bind the header (the only way to build one)."""
        body: dict[str, object] = {
            "$id": BATCH_SCHEMA_ID,
            "actor": actor.to_json(),
            "project_id": project_id.value,
            "base_revision": base_revision.hex,
            "preconditions": preconditions,
            "operations": operations,
            "provenance": provenance.to_json(),
        }
        payload = canonical_bytes(body)
        envelope = cls(
            actor, project_id, base_revision, replay_key, sha256_of(payload), kind, payload
        )
        envelope.parse_body()  # structural validation of what we just built
        return envelope

    def parse_body(self) -> ParsedBody:
        """Structural check of the wire schema; never interprets operation semantics."""
        if sha256_of(self.payload) != self.payload_sha256:
            raise ContractError("payload_sha256 does not match the canonical payload")
        if canonical_bytes(parse_json(self.payload)) != self.payload:
            raise ContractError("payload is not canonical JSON")
        data = as_object(parse_json(self.payload), "batch")
        require_keys(data, "batch", BATCH_HEADER_KEYS)
        if data["$id"] != BATCH_SCHEMA_ID:
            raise ContractError(f"batch: unsupported $id {data['$id']!r}")
        actor = LocalUser.from_json(data["actor"])
        if actor != self.actor:
            raise ContractError("batch.actor does not match the envelope actor")
        if as_str(data["project_id"], "project_id") != self.project_id.value:
            raise ContractError("batch.project_id does not match the envelope")
        if as_str(data["base_revision"], "base_revision") != self.base_revision.hex:
            raise ContractError("batch.base_revision does not match the envelope")
        operations = as_list(data["operations"], "operations")
        if not operations:
            raise ContractError("batch.operations must contain at least one operation")
        for index, op in enumerate(operations):
            as_str(json_field(as_object(op, f"operations[{index}]"), "op", "operation"), "op")
        preconditions = as_list(data["preconditions"], "preconditions")
        for index, pre in enumerate(preconditions):
            p = as_object(pre, f"preconditions[{index}]")
            kind = as_str(json_field(p, "kind", "precondition"), "precondition.kind")
            if kind == "Exists":
                require_keys(p, "precondition", ("kind", "object_ref", "version"))
                as_str(p["object_ref"], "object_ref")
                as_str(p["version"], "version")
            elif kind == "Absent":
                require_keys(p, "precondition", ("kind", "object_ref"))
                as_str(p["object_ref"], "object_ref")
            else:
                raise ContractError(f"precondition: unknown kind {kind!r}")
        provenance = provenance_from_json(data["provenance"])
        return ParsedBody(tuple(preconditions), tuple(operations), provenance)


@dataclass(frozen=True, slots=True)
class ParsedBody:
    preconditions: tuple[object, ...]
    operations: tuple[object, ...]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class IntentRequest:
    """A job/effect intent the domain asks the ledger to enqueue with the revision."""

    intent_id: IntentId
    kind: IntentKind
    spec: dict[str, object]
    deadline_s: int
    limits: dict[str, object] = field(default_factory=lambda: {})
    """Resource limits the supervisor applies (contracts §10); filled by the requester."""

    def __post_init__(self) -> None:
        if not is_int(self.deadline_s) or self.deadline_s <= 0:
            raise ContractError("IntentRequest.deadline_s must be a positive integer")
        canonical_bytes(self.spec)
        canonical_bytes(self.limits)


@dataclass(frozen=True, slots=True)
class Accepted:
    """A complete validated result: the ledger seals and commits exactly this."""

    document: bytes
    revision_id: RevisionId
    schema_version: int
    applied_operations: bytes
    inverse: bytes
    affected_objects: tuple[str, ...]
    intents: tuple[IntentRequest, ...]
    artifacts: tuple[Sha256, ...]

    def __post_init__(self) -> None:
        if not is_int(self.schema_version) or self.schema_version < 1:
            raise ContractError("Accepted.schema_version must be >= 1")
        for name in ("document", "applied_operations", "inverse"):
            if not isinstance(getattr(self, name), bytes):
                raise ContractError(f"Accepted.{name} must be bytes")
        for obj in self.affected_objects:
            if not is_str(obj) or not obj:
                raise ContractError("Accepted.affected_objects must be non-empty strings")


@dataclass(frozen=True, slots=True)
class Valid:
    """A whole-document validation passed."""


@dataclass(frozen=True, slots=True)
class ImportedDocument:
    """A validated portable snapshot, ready to become the root of a new lineage."""

    document: bytes
    schema_version: int
    project_id: ProjectId
    origin: dict[str, object]


@dataclass(frozen=True, slots=True)
class Migrated:
    document: bytes
    schema_version: int


@dataclass(frozen=True, slots=True)
class EventRecord:
    seq: EventSeq
    project_id: ProjectId
    kind: EventKind
    actor: LocalUser
    base_revision: str
    result_revision: RevisionId
    batch_sha256: Sha256
    applied_sha256: Sha256
    inverse_sha256: Sha256
    provenance: dict[str, object]
    affected_objects: tuple[str, ...]
    replay_key: str
    intent_ids: tuple[IntentId, ...]
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "seq": self.seq.value,
            "project_id": self.project_id.value,
            "kind": self.kind.value,
            "actor": self.actor.to_json(),
            "base_revision": self.base_revision,
            "result_revision": self.result_revision.hex,
            "batch_sha256": self.batch_sha256.hex,
            "applied_sha256": self.applied_sha256.hex,
            "inverse_sha256": self.inverse_sha256.hex,
            "provenance": self.provenance,
            "affected_objects": list(self.affected_objects),
            "replay_key": self.replay_key,
            "intent_ids": [i.value for i in self.intent_ids],
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class EventMissing:
    seq: EventSeq


@dataclass(frozen=True, slots=True)
class RevisionMissing:
    revision_id: RevisionId


class HistoryView(Protocol):
    """Read-only access the ledger hands to the domain during ``apply``."""

    def event(self, seq: EventSeq) -> EventRecord | EventMissing: ...
    def revision(self, revision_id: RevisionId) -> AdmittedRevision | RevisionMissing: ...
    def payload(self, sha256: Sha256) -> bytes: ...
    def events_after(self, project_id: ProjectId, seq: EventSeq) -> tuple[EventRecord, ...]: ...


class DomainPort(Protocol):
    """Implemented by ``aidashvideo.project.domain.ProjectDomain`` (and test doubles)."""

    @property
    def document_schema_version(self) -> int: ...

    def revision_id(self, document: bytes, parent: ParentRef, project_id: ProjectId) -> RevisionId:
        """Sole identity owner (``aidashvideo.project.identity``); the ledger never recomputes."""
        ...

    def validate_document(self, document: bytes, schema_version: int) -> Valid | Rejected:
        """Every constructor over the whole document."""
        ...

    def apply(
        self,
        base_document: bytes,
        base_schema_version: int,
        envelope: BatchEnvelope,
        history: HistoryView,
    ) -> Accepted | Rejected: ...

    def import_snapshot(
        self, snapshot: bytes
    ) -> ImportedDocument | InvalidSnapshot | UnsupportedSchema: ...

    def migrate_document(
        self, document: bytes, from_version: int, to_version: int
    ) -> Migrated | Rejected: ...
