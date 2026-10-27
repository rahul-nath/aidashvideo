"""Composition root for one open project: the ledger with the project domain plugged in.

This is the API later milestones consume (the compiler reads revisions, the jobs
supervisor reads the outbox, the client admits batches against the displayed revision);
none of them adds a writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aidashvideo.catalog.descriptors import DescriptorCatalog
from aidashvideo.ledger.canonical import canonical_bytes, parse_json
from aidashvideo.ledger.domain import EventRecord, UserWording
from aidashvideo.ledger.grants import ProjectGrant
from aidashvideo.ledger.ids import EventSeq, ProjectId, ReplayKey, RevisionId
from aidashvideo.ledger.ledger import Ledger, Opened, OpenResult, RevisionSnapshot
from aidashvideo.ledger.results import (
    AdmittedRevision,
    Applied,
    ApplyResult,
    ImportResult,
    RejectCode,
    Rejected,
)

from . import snapshot as snapshot_module
from . import undo as undo_module
from .document import OutputProfile, ProjectDocument
from .domain import ProjectDomain
from .operations import (
    ObjectPrecondition,
    Operation,
    OperationBatch,
    UndoChoice,
    operations_from_json,
)

WRITER_IDENTITY = "aidashvideo.project/m1"


@dataclass(frozen=True, slots=True)
class Revision:
    """``Revision(revision_id, parent, document, admitted_event_id, schema_version)``."""

    record: AdmittedRevision
    document: ProjectDocument

    @property
    def revision_id(self) -> RevisionId:
        return self.record.revision_id


class Project:
    def __init__(self, ledger: Ledger, domain: ProjectDomain) -> None:
        self.ledger = ledger
        self.domain = domain

    @property
    def catalog(self) -> DescriptorCatalog:
        return self.domain.catalog

    @property
    def grant(self) -> ProjectGrant:
        return self.ledger.grant

    @property
    def project_id(self) -> ProjectId:
        found = self.ledger.canonical_project()
        if found is None:
            raise RuntimeError("store has no canonical project")
        return found

    def close(self) -> None:
        self.ledger.close()

    def __enter__(self) -> Project:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ reads

    def head(self) -> Revision:
        return self.revision(self.ledger.head().revision_id)

    def revision(self, revision_id: RevisionId) -> Revision:
        snap = self.ledger.snapshot(revision_id)
        if not isinstance(snap, RevisionSnapshot):
            raise RuntimeError(f"revision {revision_id} is not in the store")
        return Revision(snap.revision, ProjectDocument.from_json(parse_json(snap.document)))

    def events(self) -> tuple[EventRecord, ...]:
        return self.ledger.events(self.project_id)

    def inverse_of(self, seq: EventSeq) -> tuple[Operation, ...]:
        event = self.ledger.event(seq)
        if isinstance(event, EventRecord):
            return operations_from_json(parse_json(self.ledger.cas.read(event.inverse_sha256)))
        raise RuntimeError(f"event {seq.value} is not in the store")

    # ------------------------------------------------------ writes (through the ledger only)

    def admit(self, batch: OperationBatch) -> ApplyResult:
        return self.ledger.admit(batch.to_envelope(), self.ledger.grant)

    def batch(
        self,
        operations: tuple[Operation, ...],
        *,
        replay_key: ReplayKey,
        provenance_text: str,
        base: RevisionId | None = None,
        preconditions: tuple[ObjectPrecondition, ...] = (),
    ) -> OperationBatch:
        return OperationBatch(
            self.ledger.grant.actor,
            self.project_id,
            base if base is not None else self.ledger.head().revision_id,
            replay_key,
            preconditions,
            operations,
            UserWording(provenance_text),
        )

    def plan_undo(
        self, event_seq: EventSeq, choices: tuple[UndoChoice, ...] = ()
    ) -> undo_module.UndoPlan | undo_module.UndoConflict | Rejected:
        return undo_module.plan(
            self.head().document, event_seq, self.catalog, self.ledger.history(), choices
        )

    def export_snapshot(self, revision_id: RevisionId) -> bytes:
        revision = self.revision(revision_id)
        return snapshot_module.export(revision.record, revision.document, WRITER_IDENTITY)

    def import_snapshot(self, data: bytes) -> ImportResult:
        return self.ledger.import_snapshot(data)


def open_project(project_dir: Path, grant: ProjectGrant, catalog: DescriptorCatalog) -> OpenResult:
    return Ledger.open(project_dir, grant, ProjectDomain(catalog))


def new_project(
    project_dir: Path,
    grant: ProjectGrant,
    catalog: DescriptorCatalog,
    profile: OutputProfile,
    project_id: ProjectId,
) -> Project | Rejected:
    """Create the store and admit the root revision (an empty sequence with the profile)."""
    opened = Ledger.open(project_dir, grant, ProjectDomain(catalog), create=True)
    if not isinstance(opened, Opened):
        return Rejected.make(
            RejectCode.UNAUTHORIZED, f"cannot open {project_dir}: {type(opened).__name__}"
        )
    ledger = opened.ledger
    document = ProjectDocument.new(profile)
    result = ledger.create_lineage(
        project_id,
        document.to_bytes(),
        ProjectDomain(catalog).document_schema_version,
        kind="canonical",
        replay_key=ReplayKey(f"new-project:{project_id.value}"),
        provenance={"kind": "NewProject", "profile": profile.to_json()},
        origin={"kind": "NewProject", "writer": WRITER_IDENTITY},
        source_bytes=canonical_bytes({"kind": "NewProject", "project_id": project_id.value}),
    )
    if not isinstance(result, Applied):
        ledger.close()
        if isinstance(result, Rejected):
            return result
        return Rejected.make(
            RejectCode.DUPLICATE_OBJECT, f"root admission returned {type(result).__name__}"
        )
    return Project(ledger, ProjectDomain(catalog))


def project_from_opened(opened: Opened, catalog: DescriptorCatalog) -> Project:
    return Project(opened.ledger, ProjectDomain(catalog))
