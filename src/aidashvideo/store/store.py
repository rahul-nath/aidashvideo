"""Media/artifact store (owner of ``SourceIdentity``, ``AssetAvailability``, probe receipts,
CAS artifacts and job snapshots; contracts §2, §5; invariant I1).

Sources are read through a :class:`ProjectGrant` that scopes their ``ScopedLocator`` and are
never written, moved or deleted. The store writes only under ``cas/`` (through the ledger's
artifact index), ``snapshots/<job_id>/`` (hash-verified clones for one job) and ``scratch/``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from aidashvideo.ledger.canonical import as_object, canonical_bytes, parse_json, require_keys
from aidashvideo.ledger.errors import ContractError
from aidashvideo.ledger.grants import Grant, ProjectGrant, ScopedLocator
from aidashvideo.ledger.ids import Sha256
from aidashvideo.ledger.ledger import ArtifactRef, Ledger
from aidashvideo.ledger.results import RejectCode, Rejected, RejectReason

from .identity import (
    AssetAvailability,
    Changed,
    Missing,
    Present,
    ProbeReceipt,
    RelinkRequest,
    SourceIdentity,
)
from .probe import ProbeFailed, ProbeOutcome, ProbeToolMissing

SOURCE_RECORD_KIND = "source-identity"
PROBE_RECEIPT_KIND = "probe-receipt"


class Prober(Protocol):
    def probe(self, path: Path) -> ProbeOutcome: ...


@dataclass(frozen=True, slots=True)
class ImportRefused:
    reason: RejectReason


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """What the store knows about an imported source: identity plus its last locator."""

    identity: SourceIdentity
    locator: ScopedLocator

    def to_json(self) -> dict[str, object]:
        return {
            "$id": "aidashvideo.source-record/1",
            "identity": self.identity.to_json(),
            "locator": self.locator.to_json(),
        }

    @classmethod
    def from_json(cls, raw: object) -> SourceRecord:
        data = as_object(raw, "SourceRecord")
        require_keys(data, "SourceRecord", ("$id", "identity", "locator"))
        if data["$id"] != "aidashvideo.source-record/1":
            raise ContractError("SourceRecord: unsupported $id")
        return cls(
            SourceIdentity.from_json(data["identity"]), ScopedLocator.from_json(data["locator"])
        )


@dataclass(frozen=True, slots=True)
class VerifiedClone:
    job_id: str
    path: Path
    sha256: Sha256


@dataclass(frozen=True, slots=True)
class CloneRefused:
    reason: RejectReason


def hash_file(path: Path) -> tuple[Sha256, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return Sha256(digest.hexdigest()), size


class Store:
    def __init__(self, ledger: Ledger, prober: Prober | ProbeToolMissing) -> None:
        self.ledger = ledger
        self.project_dir = ledger.project_dir
        self._prober = prober
        self._grants: dict[str, ProjectGrant] = {ledger.grant.grant_id: ledger.grant}

    # ------------------------------------------------------------------ grants

    def register_grant(self, grant: ProjectGrant) -> None:
        """A directory the client granted for reading sources (never written by the store)."""
        self._grants[grant.grant_id] = grant

    def _resolve(self, locator: ScopedLocator, grant: Grant) -> Path | ImportRefused:
        if not isinstance(grant, ProjectGrant) or grant.grant_id != locator.grant_id:
            return ImportRefused(
                RejectReason.make(
                    RejectCode.UNAUTHORIZED, "locator is not scoped by the supplied grant"
                )
            )
        try:
            path = grant.resolve(locator)
        except ContractError as exc:
            return ImportRefused(RejectReason.make(RejectCode.UNAUTHORIZED, str(exc)))
        for owned in ("cas", "snapshots", "scratch"):
            if path.is_relative_to(self.project_dir / owned):
                return ImportRefused(
                    RejectReason.make(RejectCode.NOT_A_FILE, f"{owned}/ holds no sources")
                )
        if not path.is_file():
            return ImportRefused(RejectReason.make(RejectCode.NOT_A_FILE, f"{path} is not a file"))
        self._grants[grant.grant_id] = grant
        return path

    # ------------------------------------------------------------------ sources

    def import_source(self, locator: ScopedLocator, grant: Grant) -> SourceIdentity | ImportRefused:
        """Hash, probe and record a source; the original bytes are only ever read."""
        path = self._resolve(locator, grant)
        if isinstance(path, ImportRefused):
            return path
        if isinstance(self._prober, ProbeToolMissing):
            return ImportRefused(RejectReason.make(RejectCode.TOOL_MISSING, self._prober.detail))
        before = path.stat()
        sha256, size = hash_file(path)
        outcome = self._prober.probe(path)
        if isinstance(outcome, ProbeToolMissing):
            return ImportRefused(RejectReason.make(RejectCode.TOOL_MISSING, outcome.detail))
        if isinstance(outcome, ProbeFailed):
            return ImportRefused(
                RejectReason.make(
                    RejectCode.PROBE_FAILED, f"exit {outcome.tool_exit}: {outcome.reason}"
                )
            )
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return ImportRefused(
                RejectReason.make(RejectCode.ASSET_NOT_VERIFIED, "source changed while probing")
            )
        receipt = self.ledger.seal_artifact(
            outcome.to_bytes(),
            PROBE_RECEIPT_KIND,
            outcome.probe_tool_identity.to_json(),
            (),
            f"probe:{sha256.hex}",
        )
        if isinstance(receipt, Rejected):
            return ImportRefused(receipt.contract_reason)
        if receipt.sha256 != outcome.receipt_id:
            raise ContractError("probe receipt bytes do not hash to the receipt id")
        identity = SourceIdentity(sha256, size, outcome.receipt_id)
        record = SourceRecord(identity, locator)
        sealed = self.ledger.seal_artifact(
            _record_bytes(record),
            SOURCE_RECORD_KIND,
            {"store": "aidashvideo.store"},
            (receipt.sha256,),
            f"source:{sha256.hex}",
        )
        if isinstance(sealed, Rejected):
            return ImportRefused(sealed.contract_reason)
        return identity

    def receipt(self, receipt_id: Sha256) -> ProbeReceipt | Rejected:
        if self.ledger.artifact(receipt_id) is None:
            return Rejected.make(RejectCode.UNKNOWN_ARTIFACT, f"receipt {receipt_id} unknown")
        receipt = ProbeReceipt.from_json(parse_json(self.ledger.cas.read(receipt_id)))
        if receipt.receipt_id != receipt_id:
            raise ContractError("receipt content does not match its id")
        return receipt

    def known_sources(self) -> tuple[SourceRecord, ...]:
        out: list[SourceRecord] = []
        for ref in self.ledger.artifacts(SOURCE_RECORD_KIND):
            out.append(SourceRecord.from_json(parse_json(self.ledger.cas.read(ref.sha256))))
        return tuple(out)

    def resolve_by_hash(self, sha256: Sha256) -> tuple[ScopedLocator, ...]:
        """Locators previously recorded for a content hash (never a path guess)."""
        return tuple(r.locator for r in self.known_sources() if r.identity.sha256 == sha256)

    def availability(
        self, asset_id: str, expected: SourceIdentity, locator: ScopedLocator
    ) -> AssetAvailability:
        """Re-verify the bytes at the locator: ``Present`` only after a full hash match."""
        relink = RelinkRequest(asset_id, expected.sha256, locator)
        grant = self._grants.get(locator.grant_id)
        if grant is None:
            return Missing(expected.sha256, relink)
        try:
            path = grant.resolve(locator)
        except ContractError:
            return Missing(expected.sha256, relink)
        if not path.is_file():
            return Missing(expected.sha256, relink)
        observed, _size = hash_file(path)
        if observed != expected.sha256:
            return Changed(expected.sha256, observed)
        return Present(observed, locator, expected.probe_receipt_id)

    # ------------------------------------------------------------------ artifacts

    def put(
        self,
        data: bytes,
        kind: str,
        deps: tuple[Sha256, ...],
        producer: dict[str, object],
        semantic_key: str,
    ) -> ArtifactRef | Rejected:
        return self.ledger.seal_artifact(data, kind, producer, deps, semantic_key)

    def open(self, ref: Sha256) -> bytes | Rejected:
        if self.ledger.artifact(ref) is None:
            return Rejected.make(RejectCode.UNKNOWN_ARTIFACT, f"artifact {ref} is not indexed")
        return self.ledger.cas.read(ref)

    # ------------------------------------------------------------------ job snapshots

    def snapshot_for_job(
        self, expected: SourceIdentity, locator: ScopedLocator, job_id: str
    ) -> VerifiedClone | CloneRefused:
        """A hash-verified copy owned by one job; a changed or missing original is refused."""
        if not job_id or "/" in job_id or job_id in (".", "..") or os.sep in job_id:
            return CloneRefused(RejectReason.make(RejectCode.VALIDATION, "invalid job id"))
        state = self.availability("job", expected, locator)
        if not isinstance(state, Present):
            return CloneRefused(
                RejectReason.make(
                    RejectCode.ASSET_NOT_VERIFIED,
                    f"source is {type(state).__name__}; jobs read verified clones only",
                )
            )
        grant = self._grants[locator.grant_id]
        source = grant.resolve(locator)
        target_dir = self.project_dir / "snapshots" / job_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / expected.sha256.hex
        try:
            shutil.copyfile(source, target)  # copy_file_range/clonefile when the platform allows
            observed, _ = hash_file(target)
        except OSError as exc:
            target.unlink(missing_ok=True)
            return CloneRefused(RejectReason.make(RejectCode.CLONE_FAILED, str(exc)))
        if observed != expected.sha256:
            target.unlink(missing_ok=True)
            return CloneRefused(
                RejectReason.make(RejectCode.CLONE_FAILED, "clone does not hash to the source")
            )
        return VerifiedClone(job_id, target, observed)

    def release_snapshot(self, job_id: str) -> None:
        target_dir = self.project_dir / "snapshots" / job_id
        if target_dir.is_dir():
            shutil.rmtree(target_dir)


def _record_bytes(record: SourceRecord) -> bytes:
    return canonical_bytes(record.to_json())


def open_store(ledger: Ledger) -> Store:
    """A store over an opened ledger using the located ffprobe (or a typed missing tool)."""
    from .probe import locate_prober

    return Store(ledger, locate_prober())


__all__ = [
    "CloneRefused",
    "ImportRefused",
    "Prober",
    "SourceRecord",
    "Store",
    "VerifiedClone",
    "hash_file",
    "open_store",
]
