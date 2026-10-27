"""Sole owner of revision identity (contracts §1): ``revision_id(doc, parent, project_id)``.

``revision_id = sha256(canonical JSON of {parent, lineage, document})``; the lineage id is
included so the same document at the root of two lineages (an import of an empty project,
say) never collides. Nothing else recomputes this.
"""

from __future__ import annotations

from aidashvideo.ledger.canonical import canonical_sha256, parse_json
from aidashvideo.ledger.ids import ParentRef, ProjectId, RevisionId

from .document import ProjectDocument

IDENTITY_SCHEMA_ID = "aidashvideo.revision-identity/1"


def revision_id(document: ProjectDocument, parent: ParentRef, project_id: ProjectId) -> RevisionId:
    return revision_id_of_bytes(document.to_bytes(), parent, project_id)


def revision_id_of_bytes(document: bytes, parent: ParentRef, project_id: ProjectId) -> RevisionId:
    digest = canonical_sha256(
        {
            "$id": IDENTITY_SCHEMA_ID,
            "parent": parent.to_json(),
            "lineage": project_id.value,
            "document": parse_json(document),
        }
    )
    return RevisionId(digest.hex)
