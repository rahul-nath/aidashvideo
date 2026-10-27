"""``ProjectDomain``: the project domain plugged into the ledger's ``DomainPort``.

Bytes in, bytes out: the ledger never interprets a document; this adapter parses the base
document, applies the typed batch against the descriptor catalog, validates the complete
result and returns canonical bytes plus the inverse, affected objects and intents.
"""

from __future__ import annotations

from dataclasses import dataclass

from aidashvideo.catalog.descriptors import DescriptorCatalog
from aidashvideo.ledger.canonical import canonical_bytes, parse_json
from aidashvideo.ledger.domain import (
    Accepted,
    BatchEnvelope,
    HistoryView,
    ImportedDocument,
    Migrated,
    Valid,
)
from aidashvideo.ledger.errors import ContractError
from aidashvideo.ledger.ids import Parent, ParentRef, ProjectId, RevisionId
from aidashvideo.ledger.results import InvalidSnapshot, RejectCode, Rejected, UnsupportedSchema

from . import snapshot as snapshot_module
from .apply import apply_batch
from .document import DOCUMENT_SCHEMA_VERSION, ProjectDocument, rejection_for, validate_document
from .identity import revision_id_of_bytes
from .operations import OperationBatch, operations_to_json


@dataclass(frozen=True, slots=True)
class ProjectDomain:
    catalog: DescriptorCatalog

    @property
    def document_schema_version(self) -> int:
        return DOCUMENT_SCHEMA_VERSION

    def revision_id(self, document: bytes, parent: ParentRef, project_id: ProjectId) -> RevisionId:
        return revision_id_of_bytes(document, parent, project_id)

    def validate_document(self, document: bytes, schema_version: int) -> Valid | Rejected:
        if schema_version != DOCUMENT_SCHEMA_VERSION:
            return Rejected.make(
                RejectCode.UNSUPPORTED_SCHEMA,
                f"document schema {schema_version} is not {DOCUMENT_SCHEMA_VERSION}",
            )
        try:
            parsed = ProjectDocument.from_json(parse_json(document))
        except ContractError as exc:
            return Rejected.make(RejectCode.VALIDATION, f"document: {exc}")
        if parsed.to_bytes() != document:
            return Rejected.make(RejectCode.VALIDATION, "document bytes are not canonical")
        problems = validate_document(parsed)
        if problems:
            return rejection_for(problems)
        return Valid()

    def apply(
        self,
        base_document: bytes,
        base_schema_version: int,
        envelope: BatchEnvelope,
        history: HistoryView,
    ) -> Accepted | Rejected:
        if base_schema_version != DOCUMENT_SCHEMA_VERSION:
            return Rejected.make(RejectCode.MIGRATION_REQUIRED, "base document needs migration")
        try:
            batch = OperationBatch.from_envelope(envelope)
            base = ProjectDocument.from_json(parse_json(base_document))
        except ContractError as exc:
            return Rejected.make(RejectCode.MALFORMED_BATCH, str(exc))
        result = apply_batch(base, batch, self.catalog, history)
        if isinstance(result, Rejected):
            return result
        document = result.document.to_bytes()
        return Accepted(
            document,
            revision_id_of_bytes(document, Parent(envelope.base_revision), envelope.project_id),
            DOCUMENT_SCHEMA_VERSION,
            canonical_bytes(operations_to_json(result.applied)),
            canonical_bytes(operations_to_json(result.inverse)),
            result.affected,
            result.intents,
            result.artifacts,
        )

    def import_snapshot(
        self, snapshot: bytes
    ) -> ImportedDocument | InvalidSnapshot | UnsupportedSchema:
        valid = snapshot_module.validate(snapshot)
        if isinstance(valid, InvalidSnapshot | UnsupportedSchema):
            return valid
        document = snapshot_module.quarantine_assets(valid.document)
        return ImportedDocument(
            document.to_bytes(),
            valid.schema_version,
            snapshot_module.lineage_id_for(snapshot),
            {
                "kind": "ImportSnapshot",
                "origin_project_id": valid.origin_project_id.value,
                "origin_revision_id": valid.origin_revision_id.hex,
                "writer": valid.writer,
            },
        )

    def migrate_document(
        self, document: bytes, from_version: int, to_version: int
    ) -> Migrated | Rejected:
        if from_version == to_version == DOCUMENT_SCHEMA_VERSION:
            return Migrated(document, to_version)
        return Rejected.make(
            RejectCode.NO_MIGRATION_PATH,
            f"no document migration from schema {from_version} to {to_version} exists in this"
            f" writer (it writes {DOCUMENT_SCHEMA_VERSION})",
        )
