"""Portable snapshot (``aidashvideo.portable-snapshot/1``): export a revision, validate a
file, and prepare it for import as a new lineage (contracts §5, V30).

An imported file grants no execution permission: every ``Present`` asset becomes
``Missing`` with a relink request (its locator belonged to another grant), descriptors keep
their recorded catalog digest (so a mismatch stays explicit), and the lineage id is derived
from the snapshot bytes so the same file imported twice finds its existing lineage.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from aidashvideo.ledger.canonical import (
    as_int,
    as_object,
    as_str,
    canonical_bytes,
    parse_json,
    require_keys,
    sha256_of,
)
from aidashvideo.ledger.errors import ContractError
from aidashvideo.ledger.ids import ProjectId, RevisionId
from aidashvideo.ledger.results import (
    AdmittedRevision,
    InvalidSnapshot,
    RejectCode,
    RejectReason,
    UnsupportedSchema,
)
from aidashvideo.store.identity import Missing, Present, RelinkRequest

from .document import DOCUMENT_SCHEMA_VERSION, AssetRef, ProjectDocument, validate_document

SNAPSHOT_SCHEMA_ID = "aidashvideo.portable-snapshot/1"
SNAPSHOT_EXTENSION = ".aidv.json"
MIN_READER_VERSION = 1


@dataclass(frozen=True, slots=True)
class ValidSnapshot:
    document: ProjectDocument
    schema_version: int
    origin_project_id: ProjectId
    origin_revision_id: RevisionId
    writer: str


def export(revision: AdmittedRevision, document: ProjectDocument, writer: str) -> bytes:
    body: dict[str, object] = {
        "$id": SNAPSHOT_SCHEMA_ID,
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "min_reader_version": MIN_READER_VERSION,
        "origin": {
            "project_id": revision.project_id.value,
            "revision_id": revision.revision_id.hex,
            "writer": writer,
        },
        "document": document.to_json(),
    }
    return canonical_bytes(body)


def validate(data: bytes) -> ValidSnapshot | InvalidSnapshot | UnsupportedSchema:
    try:
        raw = as_object(parse_json(data), "snapshot")
        require_keys(
            raw, "snapshot", ("$id", "schema_version", "min_reader_version", "origin", "document")
        )
        if raw["$id"] != SNAPSHOT_SCHEMA_ID:
            return InvalidSnapshot(
                RejectReason.make(RejectCode.VALIDATION, f"not a portable snapshot: {raw['$id']!r}")
            )
        schema_version = as_int(raw["schema_version"], "schema_version")
        min_reader = as_int(raw["min_reader_version"], "min_reader_version")
        if min_reader > DOCUMENT_SCHEMA_VERSION or schema_version > DOCUMENT_SCHEMA_VERSION:
            return UnsupportedSchema(schema_version, min_reader)
        origin = as_object(raw["origin"], "origin")
        require_keys(origin, "origin", ("project_id", "revision_id", "writer"))
        document = ProjectDocument.from_json(raw["document"])
        problems = validate_document(document)
        if problems:
            return InvalidSnapshot(
                RejectReason.make(problems[0].code, problems[0].detail, problems[0].objects)
            )
        return ValidSnapshot(
            document,
            schema_version,
            ProjectId(as_str(origin["project_id"], "origin.project_id")),
            RevisionId(as_str(origin["revision_id"], "origin.revision_id")),
            as_str(origin["writer"], "origin.writer"),
        )
    except ContractError as exc:
        return InvalidSnapshot(RejectReason.make(RejectCode.VALIDATION, str(exc)))


def lineage_id_for(data: bytes) -> ProjectId:
    return ProjectId(f"import-{sha256_of(data).hex[:24]}")


def quarantine_assets(document: ProjectDocument) -> ProjectDocument:
    """Imported sources are matched later by content hash; a path from another grant is only
    a relink hint, never permission."""
    assets: list[AssetRef] = []
    for asset in document.assets:
        if isinstance(asset.availability, Present):
            relink = RelinkRequest(
                asset.asset_id, asset.identity.sha256, asset.availability.scoped_locator
            )
            assets.append(replace(asset, availability=Missing(asset.identity.sha256, relink)))
        else:
            assets.append(asset)
    return replace(document, assets=tuple(assets))
