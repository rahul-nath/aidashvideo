"""Closed identifiers and quantities shared by the ledger and everything above it.

Every type is a frozen dataclass whose ``__post_init__`` validates, so an invalid value
cannot exist; ``Type.make(...)`` is the documented constructor (contracts §2). Nothing here
is ``Optional``: absence is its own variant (``Root``).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import StrEnum

from .errors import ContractError, is_int, is_str

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True, slots=True)
class Sha256:
    """Lower-case 64-hex content hash."""

    hex: str

    def __post_init__(self) -> None:
        if not is_str(self.hex) or not _HEX64.match(self.hex):
            raise ContractError(f"Sha256: not a 64-hex digest: {self.hex!r}")

    @classmethod
    def make(cls, hex_digest: str) -> Sha256:
        return cls(hex_digest)

    def __str__(self) -> str:
        return self.hex


@dataclass(frozen=True, slots=True)
class RevisionId:
    """``sha256(canonical JSON)`` of a revision (contracts §5)."""

    hex: str

    def __post_init__(self) -> None:
        if not is_str(self.hex) or not _HEX64.match(self.hex):
            raise ContractError(f"RevisionId: not a 64-hex digest: {self.hex!r}")

    @classmethod
    def make(cls, hex_digest: str) -> RevisionId:
        return cls(hex_digest)

    def __str__(self) -> str:
        return self.hex


@dataclass(frozen=True, slots=True)
class Root:
    """The parent of a lineage's first revision."""

    @classmethod
    def make(cls) -> Root:
        return cls()

    def to_json(self) -> str:
        return "root"


@dataclass(frozen=True, slots=True)
class Parent:
    revision_id: RevisionId

    @classmethod
    def make(cls, revision_id: RevisionId) -> Parent:
        return cls(revision_id)

    def to_json(self) -> str:
        return self.revision_id.hex


type ParentRef = Root | Parent


def parent_from_json(value: object) -> ParentRef:
    if value == "root":
        return Root()
    if isinstance(value, str):
        return Parent(RevisionId(value))
    raise ContractError(f"parent: expected 'root' or a revision id, got {value!r}")


@dataclass(frozen=True, slots=True)
class ProjectId:
    """Lineage identifier inside one store (the canonical project or an imported lineage)."""

    value: str

    def __post_init__(self) -> None:
        if not is_str(self.value) or not _TOKEN.match(self.value):
            raise ContractError(f"ProjectId: invalid token {self.value!r}")

    @classmethod
    def make(cls, value: str) -> ProjectId:
        return cls(value)

    @classmethod
    def new(cls, prefix: str = "project") -> ProjectId:
        return cls(f"{prefix}-{os.urandom(12).hex()}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ReplayKey:
    """Idempotency key chosen by the caller (wire schema: minLength 16)."""

    value: str

    def __post_init__(self) -> None:
        if not is_str(self.value) or len(self.value) < 16 or len(self.value) > 256:
            raise ContractError("ReplayKey: must be a string of 16..256 characters")
        if not self.value.isprintable():
            raise ContractError("ReplayKey: must be printable")

    @classmethod
    def make(cls, value: str) -> ReplayKey:
        return cls(value)

    @classmethod
    def new(cls, prefix: str = "batch") -> ReplayKey:
        return cls(f"{prefix}-{os.urandom(16).hex()}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class EventSeq:
    """Monotonic ``operation_events.seq`` (1-based)."""

    value: int

    def __post_init__(self) -> None:
        if not is_int(self.value) or self.value < 1:
            raise ContractError(f"EventSeq: must be a positive integer, got {self.value!r}")

    @classmethod
    def make(cls, value: int) -> EventSeq:
        return cls(value)

    def __int__(self) -> int:
        return self.value


@dataclass(frozen=True, slots=True)
class IntentId:
    value: str

    def __post_init__(self) -> None:
        if not is_str(self.value) or not _TOKEN.match(self.value):
            raise ContractError(f"IntentId: invalid token {self.value!r}")

    @classmethod
    def make(cls, value: str) -> IntentId:
        return cls(value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Generation:
    """Worker/intent generation used for fencing (contracts §5 step 4)."""

    value: int

    def __post_init__(self) -> None:
        if not is_int(self.value) or self.value < 0:
            raise ContractError(f"Generation: must be a non-negative integer, got {self.value!r}")

    @classmethod
    def make(cls, value: int) -> Generation:
        return cls(value)

    def __int__(self) -> int:
        return self.value


class EventKind(StrEnum):
    """``operation_events.kind`` (contracts §5; closed)."""

    EDIT = "Edit"
    UNDO = "Undo"
    IMPORT = "Import"
    REBIND = "Rebind"
    JOB_FACT = "JobFact"
    EFFECT_FACT = "EffectFact"
    MIGRATION = "Migration"


class IntentKind(StrEnum):
    PREVIEW = "Preview"
    EXPORT = "Export"
    PROBE = "Probe"
    PROXY = "Proxy"
    SPEECH = "Speech"
    MASK = "Mask"
    EFFECT = "Effect"


class IntentState(StrEnum):
    """Closed ``JobState`` names stored in ``intents.state``."""

    QUEUED = "Queued"
    RUNNING = "Running"
    CANCELLED = "Cancelled"
    FAILED = "Failed"
    COMPLETED = "Completed"
    RECONCILING = "Reconciling"


_TRANSITIONS: dict[IntentState, frozenset[IntentState]] = {
    IntentState.QUEUED: frozenset({IntentState.RUNNING, IntentState.CANCELLED, IntentState.FAILED}),
    IntentState.RUNNING: frozenset(
        {
            IntentState.COMPLETED,
            IntentState.FAILED,
            IntentState.CANCELLED,
            IntentState.RECONCILING,
        }
    ),
    IntentState.RECONCILING: frozenset(
        {IntentState.COMPLETED, IntentState.FAILED, IntentState.CANCELLED, IntentState.QUEUED}
    ),
    IntentState.COMPLETED: frozenset(),
    IntentState.FAILED: frozenset(),
    IntentState.CANCELLED: frozenset(),
}


def intent_transition_allowed(current: IntentState, target: IntentState) -> bool:
    return target in _TRANSITIONS[current]
