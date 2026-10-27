"""Grants and caller identity (contracts §2, sole owner: ``aidashvideo.ledger.grants``).

Other modules receive a ``Grant`` value and never construct one; the client process issues
a ``ProjectGrant`` at project open with :func:`issue_project_grant`. Model text, chat
strings and file contents never carry authority (I8, D10).
"""

from __future__ import annotations

import getpass
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .canonical import as_object, as_str, field, require_keys
from .errors import ContractError, is_int, is_str, widen
from .ids import RevisionId, Sha256

_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True, slots=True)
class LocalUser:
    """``ActorId``: the OS user of the client process plus its session (never from model text)."""

    os_user: str
    client_session_id: str

    def __post_init__(self) -> None:
        if not is_str(self.os_user) or not self.os_user or len(self.os_user) > 128:
            raise ContractError("LocalUser.os_user must be a non-empty string")
        if not is_str(self.client_session_id) or not _TOKEN.match(self.client_session_id):
            raise ContractError("LocalUser.client_session_id must be a token")

    @classmethod
    def make(cls, os_user: str, client_session_id: str) -> LocalUser:
        return cls(os_user, client_session_id)

    def to_json(self) -> dict[str, object]:
        return {"os_user": self.os_user, "client_session_id": self.client_session_id}

    @classmethod
    def from_json(cls, raw: object) -> LocalUser:
        data = as_object(raw, "ActorId")
        require_keys(data, "ActorId", ("os_user", "client_session_id"))
        return cls(
            as_str(field(data, "os_user", "ActorId"), "os_user"),
            as_str(field(data, "client_session_id", "ActorId"), "client_session_id"),
        )


type ActorId = LocalUser


@dataclass(frozen=True, slots=True)
class ScopedLocator:
    """A path inside a grant's directory; never a bare path (contracts §2)."""

    grant_id: str
    path_within_grant: str

    def __post_init__(self) -> None:
        if not is_str(self.grant_id) or not _TOKEN.match(self.grant_id):
            raise ContractError("ScopedLocator.grant_id must be a token")
        if not is_str(self.path_within_grant) or not self.path_within_grant:
            raise ContractError("ScopedLocator.path_within_grant must be non-empty")
        rel = PurePosixPath(self.path_within_grant)
        if rel.is_absolute() or ".." in rel.parts or any(p in ("", ".") for p in rel.parts):
            raise ContractError(
                f"ScopedLocator.path_within_grant must be relative without '..': "
                f"{self.path_within_grant!r}"
            )

    @classmethod
    def make(cls, grant_id: str, path_within_grant: str) -> ScopedLocator:
        return cls(grant_id, path_within_grant)

    def to_json(self) -> dict[str, object]:
        return {"grant_id": self.grant_id, "path_within_grant": self.path_within_grant}

    @classmethod
    def from_json(cls, raw: object) -> ScopedLocator:
        data = as_object(raw, "ScopedLocator")
        require_keys(data, "ScopedLocator", ("grant_id", "path_within_grant"))
        return cls(as_str(data["grant_id"], "grant_id"), as_str(data["path_within_grant"], "path"))


@dataclass(frozen=True, slots=True)
class ProjectGrant:
    """Edits and previews inside one project directory."""

    grant_id: str
    project_dir: Path
    actor: LocalUser

    def __post_init__(self) -> None:
        if not is_str(self.grant_id) or not _TOKEN.match(self.grant_id):
            raise ContractError("ProjectGrant.grant_id must be a token")
        if not isinstance(widen(self.project_dir), Path) or not self.project_dir.is_absolute():
            raise ContractError("ProjectGrant.project_dir must be an absolute path")

    def resolve(self, locator: ScopedLocator) -> Path:
        """Resolve a locator under this grant; refuses escapes and foreign grant ids."""
        if locator.grant_id != self.grant_id:
            raise ContractError("locator belongs to another grant")
        resolved = (self.project_dir / locator.path_within_grant).resolve()
        if not resolved.is_relative_to(self.project_dir.resolve()):
            raise ContractError("locator escapes the granted directory")
        return resolved


@dataclass(frozen=True, slots=True)
class ExportGrant:
    """One new output file for one revision."""

    grant_id: str
    revision_id: RevisionId
    destination: ScopedLocator
    actor: LocalUser


@dataclass(frozen=True, slots=True)
class OverwriteGrant:
    grant_id: str
    destination: ScopedLocator
    expected_sha256: Sha256
    actor: LocalUser


@dataclass(frozen=True, slots=True)
class AcquisitionGrant:
    grant_id: str
    source_url: str
    sha256: Sha256
    bytes: int
    destination: ScopedLocator
    actor: LocalUser

    def __post_init__(self) -> None:
        if not is_int(self.bytes) or self.bytes < 0:
            raise ContractError("AcquisitionGrant.bytes must be >= 0")


type Grant = ProjectGrant | ExportGrant | OverwriteGrant | AcquisitionGrant


def current_actor(client_session_id: str) -> LocalUser:
    """The OS user of this process (the client establishes sessions; models never do)."""
    try:
        user = getpass.getuser()
    except KeyError, OSError:
        user = f"uid-{os.getuid()}"
    return LocalUser(user, client_session_id)


def issue_project_grant(project_dir: Path, actor: LocalUser) -> ProjectGrant:
    """Issued by the client process at project open; carries a fresh unguessable id."""
    return ProjectGrant(f"pg-{os.urandom(12).hex()}", project_dir.resolve(), actor)
