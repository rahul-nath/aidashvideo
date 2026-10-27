"""Content-addressed immutable blobs: ``<project_dir>/cas/sha256/ab/<sha256>`` (contracts §5).

Sealing writes a temporary file inside ``cas/staging/``, fsyncs it, renames it into place
and fsyncs the directory. A blob that exists is never rewritten. Sealing is a filesystem
fact only: a sealed blob has no admission authority until a committed ledger row
references it (orphans are harmless and are reported by :meth:`CasRoot.orphans`).
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .canonical import sha256_of
from .errors import ContractError
from .ids import Sha256


@dataclass(frozen=True, slots=True)
class BlobPresent:
    sha256: Sha256
    size_bytes: int


@dataclass(frozen=True, slots=True)
class BlobMissing:
    sha256: Sha256


@dataclass(frozen=True, slots=True)
class BlobCorrupt:
    """Bytes on disk do not hash to their name (a foreign edit); never returned as content."""

    sha256: Sha256
    observed: Sha256


type BlobStatus = BlobPresent | BlobMissing | BlobCorrupt


class CasRoot:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.blobs = root / "sha256"
        self.staging = root / "staging"

    def ensure(self) -> None:
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)

    def path_of(self, sha256: Sha256) -> Path:
        return self.blobs / sha256.hex[:2] / sha256.hex

    def seal(self, data: bytes) -> Sha256:
        """Write ``data`` once under its hash (temp + fsync + rename + dir fsync)."""
        digest = sha256_of(data)
        final = self.path_of(digest)
        if final.is_file():
            return digest
        self.ensure()
        final.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=digest.hex[:12] + ".", dir=self.staging)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, final)
            _fsync_dir(final.parent)
        finally:
            if tmp.exists():
                tmp.unlink()
        return digest

    def status(self, sha256: Sha256) -> BlobStatus:
        path = self.path_of(sha256)
        if not path.is_file():
            return BlobMissing(sha256)
        data = path.read_bytes()
        observed = sha256_of(data)
        if observed != sha256:
            return BlobCorrupt(sha256, observed)
        return BlobPresent(sha256, len(data))

    def read(self, sha256: Sha256) -> bytes:
        """Verified read; a missing or corrupt blob is a ``ContractError`` for the caller."""
        path = self.path_of(sha256)
        if not path.is_file():
            raise ContractError(f"CAS: blob {sha256.hex} is missing")
        data = path.read_bytes()
        observed = sha256_of(data)
        if observed != sha256:
            raise ContractError(f"CAS: blob {sha256.hex} is corrupt (hashes to {observed.hex})")
        return data

    def exists(self, sha256: Sha256) -> bool:
        return self.path_of(sha256).is_file()

    def all_blobs(self) -> list[Sha256]:
        if not self.blobs.is_dir():
            return []
        out: list[Sha256] = []
        for shard in sorted(self.blobs.iterdir()):
            if shard.is_dir():
                for entry in sorted(shard.iterdir()):
                    if entry.is_file() and len(entry.name) == 64:
                        out.append(Sha256(entry.name))
        return out

    def orphans(self, referenced: set[Sha256]) -> list[Sha256]:
        return [b for b in self.all_blobs() if b not in referenced]

    def staged_leftovers(self) -> list[Path]:
        if not self.staging.is_dir():
            return []
        return sorted(p for p in self.staging.iterdir() if p.is_file())


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
