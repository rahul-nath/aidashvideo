"""Closed results of admission, import and open (contracts §2: ``ApplyResult``, ``ImportResult``).

Authorization failures and expected unavailability are values of these types; an
impossible internal state raises :class:`~aidashvideo.ledger.errors.InvariantViolation`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .canonical import as_int, as_list, as_object, as_str, field
from .errors import ContractError, is_int, is_str, widen
from .ids import (
    EventKind,
    EventSeq,
    IntentId,
    ParentRef,
    ProjectId,
    RevisionId,
    Sha256,
    parent_from_json,
)


class RejectCode(StrEnum):
    """Closed contract reasons. Domain codes are listed here so every module shares one set."""

    # boundary / authority
    UNAUTHORIZED = "Unauthorized"
    READ_ONLY = "ReadOnly"
    STORE_BUSY = "StoreBusy"
    MALFORMED_BATCH = "MalformedBatch"
    PAYLOAD_HASH_MISMATCH = "PayloadHashMismatch"
    REPLAY_KEY_CONFLICT = "ReplayKeyConflict"
    UNKNOWN_PROJECT = "UnknownProject"
    UNKNOWN_REVISION = "UnknownRevision"
    UNKNOWN_EVENT = "UnknownEvent"
    UNKNOWN_ARTIFACT = "UnknownArtifact"
    UNKNOWN_INTENT = "UnknownIntent"
    STALE_GENERATION = "StaleGeneration"
    ILLEGAL_TRANSITION = "IllegalTransition"
    PAYLOAD_TOO_LARGE = "PayloadTooLarge"
    MIGRATION_REQUIRED = "MigrationRequired"
    NO_MIGRATION_PATH = "NoMigrationPath"
    UNSUPPORTED_SCHEMA = "UnsupportedSchema"
    # domain validation
    PRECONDITION_FAILED = "PreconditionFailed"
    VALIDATION = "Validation"
    UNKNOWN_OBJECT = "UnknownObject"
    DUPLICATE_OBJECT = "DuplicateObject"
    UNKNOWN_DESCRIPTOR = "UnknownDescriptor"
    UNKNOWN_PARAMETER = "UnknownParameter"
    PARAMETER_TYPE = "ParameterType"
    PARAMETER_RANGE = "ParameterRange"
    UNSUPPORTED_ANIMATION = "UnsupportedAnimation"
    OVERLAP = "Overlap"
    INSUFFICIENT_HANDLES = "InsufficientHandles"
    NEGATIVE_START = "NegativeStart"
    UNSUPPORTED_SPEED = "UnsupportedSpeed"
    UNSUPPORTED_PROFILE = "UnsupportedProfile"
    OUTSIDE_PLACED_RANGE = "OutsidePlacedRange"
    OUTSIDE_SOURCE = "OutsideSource"
    UNDO_CONFLICT = "UndoConflict"
    DEPENDENTS_EXIST = "DependentsExist"
    ASSET_NOT_VERIFIED = "AssetNotVerified"
    CATALOG_MISMATCH = "CatalogMismatch"
    # store
    TOOL_MISSING = "ToolMissing"
    PROBE_FAILED = "ProbeFailed"
    NOT_A_FILE = "NotAFile"
    CLONE_FAILED = "CloneFailed"


@dataclass(frozen=True, slots=True)
class RejectReason:
    """Typed contract reason carried by ``Rejected``."""

    code: RejectCode
    detail: str
    objects: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(widen(self.code), RejectCode):
            raise ContractError("RejectReason.code must be a RejectCode")
        if not is_str(self.detail) or not self.detail:
            raise ContractError("RejectReason.detail must be a non-empty string")

    @classmethod
    def make(cls, code: RejectCode, detail: str, objects: tuple[str, ...] = ()) -> RejectReason:
        return cls(code, detail, tuple(objects))

    def to_json(self) -> dict[str, object]:
        return {"code": self.code.value, "detail": self.detail, "objects": list(self.objects)}

    @classmethod
    def from_json(cls, raw: object) -> RejectReason:
        data = as_object(raw, "RejectReason")
        try:
            code = RejectCode(as_str(field(data, "code", "RejectReason"), "RejectReason.code"))
        except ValueError as exc:
            raise ContractError(f"RejectReason: unknown code: {exc}") from exc
        objects = as_list(data.get("objects", []), "RejectReason.objects")
        return cls(
            code,
            as_str(field(data, "detail", "RejectReason"), "RejectReason.detail"),
            tuple(as_str(o, "RejectReason.objects[]") for o in objects),
        )


@dataclass(frozen=True, slots=True)
class AdmittedRevision:
    """The ledger's record of one immutable revision (wire schema ``aidashvideo.revision/1``).

    The document itself lives in the CAS under ``payload_sha256``; the domain's typed
    ``Revision`` wraps this record with the parsed document.
    """

    revision_id: RevisionId
    project_id: ProjectId
    parent: ParentRef
    payload_sha256: Sha256
    admitted_event_id: EventSeq
    schema_version: int

    def __post_init__(self) -> None:
        if not is_int(self.schema_version) or self.schema_version < 1:
            raise ContractError("AdmittedRevision.schema_version must be >= 1")

    def to_json(self) -> dict[str, object]:
        return {
            "revision_id": self.revision_id.hex,
            "project_id": self.project_id.value,
            "parent": self.parent.to_json(),
            "payload_sha256": self.payload_sha256.hex,
            "admitted_event_id": self.admitted_event_id.value,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class AdmittedEvent:
    seq: EventSeq
    kind: EventKind
    project_id: ProjectId
    result_revision: RevisionId
    affected_objects: tuple[str, ...]
    intent_ids: tuple[IntentId, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "seq": self.seq.value,
            "kind": self.kind.value,
            "project_id": self.project_id.value,
            "result_revision": self.result_revision.hex,
            "affected_objects": list(self.affected_objects),
            "intent_ids": [i.value for i in self.intent_ids],
        }


@dataclass(frozen=True, slots=True)
class Applied:
    revision: AdmittedRevision
    admitted_event: AdmittedEvent

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "Applied",
            "revision": self.revision.to_json(),
            "admitted_event": self.admitted_event.to_json(),
        }

    @classmethod
    def from_json(cls, raw: object) -> Applied:
        data = as_object(raw, "Applied")
        return cls(
            admitted_revision_from_json(field(data, "revision", "Applied")),
            admitted_event_from_json(field(data, "admitted_event", "Applied")),
        )


def admitted_revision_from_json(raw: object) -> AdmittedRevision:
    r = as_object(raw, "AdmittedRevision")
    return AdmittedRevision(
        RevisionId(as_str(field(r, "revision_id", "AdmittedRevision"), "revision_id")),
        ProjectId(as_str(field(r, "project_id", "AdmittedRevision"), "project_id")),
        parent_from_json(field(r, "parent", "AdmittedRevision")),
        Sha256(as_str(field(r, "payload_sha256", "AdmittedRevision"), "payload_sha256")),
        EventSeq(as_int(field(r, "admitted_event_id", "AdmittedRevision"), "admitted_event_id")),
        as_int(field(r, "schema_version", "AdmittedRevision"), "schema_version"),
    )


def admitted_event_from_json(raw: object) -> AdmittedEvent:
    e = as_object(raw, "AdmittedEvent")
    try:
        kind = EventKind(as_str(field(e, "kind", "AdmittedEvent"), "kind"))
    except ValueError as exc:
        raise ContractError(f"AdmittedEvent: unknown kind: {exc}") from exc
    return AdmittedEvent(
        EventSeq(as_int(field(e, "seq", "AdmittedEvent"), "seq")),
        kind,
        ProjectId(as_str(field(e, "project_id", "AdmittedEvent"), "project_id")),
        RevisionId(as_str(field(e, "result_revision", "AdmittedEvent"), "result_revision")),
        tuple(
            as_str(a, "affected_objects[]")
            for a in as_list(e.get("affected_objects", []), "affected_objects")
        ),
        tuple(
            IntentId(as_str(i, "intent_ids[]"))
            for i in as_list(e.get("intent_ids", []), "intent_ids")
        ),
    )


@dataclass(frozen=True, slots=True)
class AlreadyApplied:
    original_result: Applied


@dataclass(frozen=True, slots=True)
class RevisionConflict:
    current_revision: RevisionId


@dataclass(frozen=True, slots=True)
class Rejected:
    contract_reason: RejectReason

    @classmethod
    def make(cls, code: RejectCode, detail: str, objects: tuple[str, ...] = ()) -> Rejected:
        return cls(RejectReason.make(code, detail, objects))


type ApplyResult = Applied | AlreadyApplied | RevisionConflict | Rejected


def apply_result_to_json(result: ApplyResult) -> dict[str, object]:
    match result:
        case Applied():
            return result.to_json()
        case AlreadyApplied(original):
            return {"kind": "AlreadyApplied", "original_result": original.to_json()}
        case RevisionConflict(current):
            return {"kind": "RevisionConflict", "current_revision": current.hex}
        case Rejected(reason):
            return {"kind": "Rejected", "contract_reason": reason.to_json()}


# ----------------------------------------------------------------------------- import


@dataclass(frozen=True, slots=True)
class NewLineage:
    root_revision: AdmittedRevision


@dataclass(frozen=True, slots=True)
class InvalidSnapshot:
    contract_reason: RejectReason


@dataclass(frozen=True, slots=True)
class UnsupportedSchema:
    writer_version: int
    min_reader: int


type ImportResult = NewLineage | InvalidSnapshot | UnsupportedSchema


# ----------------------------------------------------------------------------- open


@dataclass(frozen=True, slots=True)
class Writable:
    pass


@dataclass(frozen=True, slots=True)
class ReadOnly:
    reason: RejectReason


type OpenMode = Writable | ReadOnly


@dataclass(frozen=True, slots=True)
class Fenced:
    """The store requires a newer reader than this code (``min_reader_version`` too high)."""

    writer_version: int
    min_reader_version: int
    supported_reader: int


@dataclass(frozen=True, slots=True)
class Denied:
    reason: RejectReason


@dataclass(frozen=True, slots=True)
class Corrupt:
    """The store contradicts its own invariants (foreign write, missing payload)."""

    findings: tuple[str, ...]
