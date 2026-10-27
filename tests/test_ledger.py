"""The admission owner tested alone against a real temporary SQLite store (M1a; I2, I3, V09,
V12, V30).

A trivial counter domain (``tests/ledger_support.py``) stands in for the project domain so
that the transaction, replay, authority, outbox, crash and migration behaviour is proven
before any mutating consumer exists.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from aidashvideo.ledger import (
    AlreadyApplied,
    Applied,
    BatchEnvelope,
    ContractError,
    Corrupt,
    Denied,
    EventKind,
    EventSeq,
    ExportGrant,
    FactRecorded,
    Fenced,
    Generation,
    InjectedFault,
    IntentFact,
    IntentId,
    IntentState,
    InvalidSnapshot,
    InvariantViolation,
    Ledger,
    LocalUser,
    MigrationApplied,
    MigrationPlan,
    NewLineage,
    NothingToMigrate,
    Opened,
    OutboxRow,
    Parent,
    ParentRef,
    ProjectId,
    ReadOnly,
    RejectCode,
    Rejected,
    ReplayKey,
    RevisionConflict,
    RevisionId,
    RevisionSnapshot,
    Root,
    ScopedLocator,
    Sha256,
    UnsupportedSchema,
    UserWording,
    Writable,
    canonical_bytes,
    issue_project_grant,
    sha256_of,
)
from aidashvideo.ledger.__main__ import inspect as ledger_inspect
from aidashvideo.ledger.cas import BlobCorrupt, BlobPresent, CasRoot
from ledger_support import (
    ACTOR,
    OTHER_ACTOR,
    PROJECT,
    CounterDomain,
    counter_of,
    envelope,
    event_count,
    new_project,
    open_store,
)

pytestmark = pytest.mark.ledger


# ----------------------------------------------------------------------------- closed values


def test_closed_ids_reject_malformed_values() -> None:
    with pytest.raises(ContractError):
        Sha256("ABCDEF" * 10 + "1234")  # upper case
    with pytest.raises(ContractError):
        Sha256("ab" * 31)
    with pytest.raises(ContractError):
        ReplayKey("short")
    with pytest.raises(ContractError):
        EventSeq(0)
    with pytest.raises(ContractError):
        EventSeq(True)  # bool is not an integer quantity
    with pytest.raises(ContractError):
        Generation(-1)
    with pytest.raises(ContractError):
        ProjectId("has space")
    with pytest.raises(ContractError):
        ScopedLocator("g", "../escape")
    with pytest.raises(ContractError):
        ScopedLocator("g", "/abs")
    with pytest.raises(ContractError):
        LocalUser("", "s")


def test_canonical_json_is_sorted_compact_and_finite() -> None:
    assert canonical_bytes({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'
    with pytest.raises(ContractError):
        canonical_bytes({"x": float("nan")})
    with pytest.raises(ContractError):
        canonical_bytes({"x": float("inf")})
    with pytest.raises(ContractError):
        canonical_bytes({1: "non-string key"})
    with pytest.raises(ContractError):
        canonical_bytes({"x": object()})


def test_cas_seal_is_content_addressed_and_detects_corruption(tmp_path: Path) -> None:
    cas = CasRoot(tmp_path / "cas")
    digest = cas.seal(b"hello")
    assert digest == sha256_of(b"hello")
    assert cas.seal(b"hello") == digest
    assert cas.read(digest) == b"hello"
    assert isinstance(cas.status(digest), BlobPresent)
    assert cas.staged_leftovers() == []
    cas.path_of(digest).write_bytes(b"tampered")
    assert isinstance(cas.status(digest), BlobCorrupt)
    with pytest.raises(ContractError, match="corrupt"):
        cas.read(digest)


# ----------------------------------------------------------------------------- open / authority


def test_open_requires_a_matching_project_grant(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    other = tmp_path / "other"
    other.mkdir()
    grant = issue_project_grant(other, ACTOR)
    assert isinstance(Ledger.open(project, grant, CounterDomain(), create=True), Denied)
    export = ExportGrant("eg-1", RevisionId("0" * 64), ScopedLocator("eg-1", "out.mp4"), ACTOR)
    assert isinstance(Ledger.open(project, export, CounterDomain(), create=True), Denied)
    missing = Ledger.open(project, issue_project_grant(project, ACTOR), CounterDomain())
    assert isinstance(missing, Denied)
    assert missing.reason.code is RejectCode.UNKNOWN_PROJECT


def test_new_store_survives_close_and_reopen_with_identical_content(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    new_project(ledger, 5)
    result = ledger.admit(envelope(ledger, [{"op": "add", "k": 3}]), grant)
    assert isinstance(result, Applied)
    head_before = ledger.head()
    chain_before = ledger.lineage(head_before.revision_id)
    events_before = ledger.all_events()
    snap_before = ledger.snapshot(head_before.revision_id)
    ledger.close()

    reopened, _ = open_store(project, create=False, grant=grant)
    assert reopened.head() == head_before
    assert reopened.lineage(head_before.revision_id) == chain_before
    assert reopened.all_events() == events_before
    assert reopened.snapshot(head_before.revision_id) == snap_before
    assert isinstance(snap_before, RevisionSnapshot)
    assert snap_before.document == b'{"n":8}'
    assert counter_of(reopened) == 8
    assert chain_before[0].parent == Root()
    assert chain_before[1].parent == Parent(chain_before[0].revision_id)
    assert reopened.verify(deep=True).ok
    assert (project / "project.sqlite").is_file()
    assert (project / "cas" / "sha256").is_dir()
    reopened.close()


def test_admission_writes_event_revision_head_and_sealed_payloads(tmp_path: Path) -> None:
    ledger, grant = open_store(tmp_path / "proj")
    new_project(ledger)
    root = ledger.head()
    result = ledger.admit(envelope(ledger, [{"op": "add", "k": 2}]), grant)
    assert isinstance(result, Applied)
    assert result.revision.parent == Parent(root.revision_id)
    assert result.admitted_event.kind is EventKind.EDIT
    assert result.admitted_event.affected_objects == ("counter",)
    assert ledger.head() == result.revision
    event = ledger.event(result.admitted_event.seq)
    assert not isinstance(event, type(None))
    from aidashvideo.ledger import EventRecord

    assert isinstance(event, EventRecord)
    assert event.base_revision == root.revision_id.hex
    assert event.result_revision == result.revision.revision_id
    assert event.provenance == {"kind": "UserWording", "text": "add one"}
    assert ledger.cas.read(event.inverse_sha256) == b'[{"k":-2,"op":"add"}]'
    assert ledger.cas.read(event.applied_sha256) == b'[{"k":2,"op":"add"}]'
    assert ledger.cas.read(result.revision.payload_sha256) == b'{"n":2}'
    assert ledger.cas.orphans(ledger.referenced_blobs()) == []
    ledger.close()


def test_actor_and_grant_authority_are_typed_rejections(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    new_project(ledger)
    head = ledger.head()
    # a batch by another actor under this grant
    res = ledger.admit(envelope(ledger, [{"op": "add", "k": 1}], actor=OTHER_ACTOR), grant)
    assert isinstance(res, Rejected) and res.contract_reason.code is RejectCode.UNAUTHORIZED
    # a grant for another directory / another actor / a non-project grant
    foreign = issue_project_grant(tmp_path / "elsewhere", ACTOR)
    res = ledger.admit(envelope(ledger, [{"op": "add", "k": 1}]), foreign)
    assert isinstance(res, Rejected) and res.contract_reason.code is RejectCode.UNAUTHORIZED
    other_session = issue_project_grant(project, OTHER_ACTOR)
    res = ledger.admit(envelope(ledger, [{"op": "add", "k": 1}], actor=OTHER_ACTOR), other_session)
    assert isinstance(res, Rejected) and res.contract_reason.code is RejectCode.UNAUTHORIZED
    export = ExportGrant("eg-1", head.revision_id, ScopedLocator("eg-1", "out.mp4"), ACTOR)
    res = ledger.admit(envelope(ledger, [{"op": "add", "k": 1}]), export)
    assert isinstance(res, Rejected) and res.contract_reason.code is RejectCode.UNAUTHORIZED
    assert ledger.head() == head and event_count(ledger) == 1
    ledger.close()


def test_malformed_batches_are_rejected_without_writes(tmp_path: Path) -> None:
    ledger, grant = open_store(tmp_path / "proj")
    new_project(ledger)
    head = ledger.head()
    good = envelope(ledger, [{"op": "add", "k": 1}])
    tampered = BatchEnvelope(
        good.actor,
        good.project_id,
        good.base_revision,
        good.replay_key,
        good.payload_sha256,
        good.kind,
        good.payload.replace(b'"k":1', b'"k":9'),
    )
    res = ledger.admit(tampered, grant)
    assert isinstance(res, Rejected)
    assert res.contract_reason.code is RejectCode.PAYLOAD_HASH_MISMATCH
    with pytest.raises(ContractError, match="at least one operation"):
        envelope(ledger, [])
    with pytest.raises(ContractError):
        envelope(ledger, [{"no_op_key": 1}])
    with pytest.raises(ContractError):
        envelope(ledger, [{"op": "add"}], preconditions=[{"kind": "Sometimes", "object_ref": "x"}])
    # the domain rejects: nothing is written and nothing is sealed
    blobs = set(ledger.cas.all_blobs())
    res = ledger.admit(envelope(ledger, [{"op": "boom"}]), grant)
    assert isinstance(res, Rejected) and res.contract_reason.code is RejectCode.VALIDATION
    assert set(ledger.cas.all_blobs()) == blobs
    res = ledger.admit(envelope(ledger, [{"op": "add", "k": -100}]), grant)
    assert isinstance(res, Rejected)
    assert ledger.head() == head and event_count(ledger) == 1
    assert ledger.idempotency_record(good.replay_key) is None
    ledger.close()


def test_unknown_artifact_reference_is_rejected_before_the_transaction(tmp_path: Path) -> None:
    ledger, grant = open_store(tmp_path / "proj")
    new_project(ledger)
    unknown = sha256_of(b"never sealed").hex
    res = ledger.admit(envelope(ledger, [{"op": "artifact", "sha256": unknown}]), grant)
    assert isinstance(res, Rejected) and res.contract_reason.code is RejectCode.UNKNOWN_ARTIFACT
    sealed = ledger.seal_artifact(b"probe", "probe", {"tool": "test"}, (), "probe:x")
    assert not isinstance(sealed, Rejected)
    res = ledger.admit(envelope(ledger, [{"op": "artifact", "sha256": sealed.sha256.hex}]), grant)
    assert isinstance(res, Applied)
    ledger.close()


# ----------------------------------------------------------------------------- replay (I3)


def test_exact_replay_applies_once_and_returns_the_original_result(tmp_path: Path) -> None:
    ledger, grant = open_store(tmp_path / "proj")
    new_project(ledger)
    batch = envelope(ledger, [{"op": "add", "k": 1}, {"op": "intent", "id": "effect-a"}])
    first = ledger.admit(batch, grant)
    assert isinstance(first, Applied)
    again = ledger.admit(batch, grant)
    assert isinstance(again, AlreadyApplied)
    assert again.original_result == first
    # identical ids, no second event, no duplicate intent/outbox row
    assert event_count(ledger) == 2
    assert [i.intent_id.value for i in ledger.intents()] == ["effect-a"]
    assert len(ledger.pending_outbox()) == 1
    assert counter_of(ledger) == 1
    # a rebuilt envelope with the same key and the same canonical body is the same replay
    rebuilt = envelope(
        ledger,
        [{"op": "add", "k": 1}, {"op": "intent", "id": "effect-a"}],
        base=batch.base_revision,
    )
    assert rebuilt.payload_sha256 == batch.payload_sha256
    assert isinstance(ledger.admit(rebuilt, grant), AlreadyApplied)
    ledger.close()


def test_conflicting_replay_changes_nothing(tmp_path: Path) -> None:
    ledger, grant = open_store(tmp_path / "proj")
    new_project(ledger)
    batch = envelope(ledger, [{"op": "add", "k": 1}])
    assert isinstance(ledger.admit(batch, grant), Applied)
    head = ledger.head()
    conflicting = envelope(ledger, [{"op": "add", "k": 2}])  # same key, other payload
    assert conflicting.replay_key == batch.replay_key
    res = ledger.admit(conflicting, grant)
    assert isinstance(res, Rejected)
    assert res.contract_reason.code is RejectCode.REPLAY_KEY_CONFLICT
    assert ledger.head() == head and counter_of(ledger) == 1 and event_count(ledger) == 2
    ledger.close()


def test_stale_base_revision_is_a_revision_conflict(tmp_path: Path) -> None:
    ledger, grant = open_store(tmp_path / "proj")
    new_project(ledger)
    root = ledger.head()
    assert isinstance(
        ledger.admit(envelope(ledger, [{"op": "add", "k": 1}], key="k1-0123456789abcdef"), grant),
        Applied,
    )
    stale = envelope(
        ledger, [{"op": "add", "k": 5}], key="k2-0123456789abcdef", base=root.revision_id
    )
    res = ledger.admit(stale, grant)
    assert isinstance(res, RevisionConflict)
    assert res.current_revision == ledger.head().revision_id
    assert counter_of(ledger) == 1
    assert ledger.idempotency_record(stale.replay_key) is None  # nothing recorded for a conflict
    unknown = envelope(
        ledger, [{"op": "add", "k": 5}], key="k3-0123456789abcdef", base=RevisionId("f" * 64)
    )
    res = ledger.admit(unknown, grant)
    assert isinstance(res, Rejected) and res.contract_reason.code is RejectCode.UNKNOWN_REVISION
    ledger.close()


def test_stale_object_precondition_is_rejected(tmp_path: Path) -> None:
    ledger, grant = open_store(tmp_path / "proj")
    new_project(ledger, 4)
    res = ledger.admit(
        envelope(
            ledger,
            [{"op": "add", "k": 1}],
            preconditions=[{"kind": "Exists", "object_ref": "counter", "version": "3"}],
        ),
        grant,
    )
    assert isinstance(res, Rejected)
    assert res.contract_reason.code is RejectCode.PRECONDITION_FAILED
    assert res.contract_reason.objects == ("counter",)
    ok = ledger.admit(
        envelope(
            ledger,
            [{"op": "add", "k": 1}],
            key="k2-0123456789abcdef",
            preconditions=[{"kind": "Exists", "object_ref": "counter", "version": "4"}],
        ),
        grant,
    )
    assert isinstance(ok, Applied)
    ledger.close()


# ----------------------------------------------------------------------------- concurrency (V09)


def test_two_concurrent_writers_only_one_expected_head_update_wins(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    new_project(ledger)
    base = ledger.head().revision_id
    ledger.close()

    barrier = threading.Barrier(2, timeout=30)
    results: dict[str, object] = {}

    def hook(point: str) -> None:
        if point == "after_seal":
            barrier.wait()  # both writers validated against the same base before either commits

    def writer(name: str, k: int) -> None:
        store, g = open_store(project, create=False, faults=hook, grant=grant)
        try:
            batch = envelope(
                store,
                [{"op": "add", "k": k}, {"op": "intent", "id": f"effect-{name}"}],
                key=f"{name}-0123456789abcdef",
                base=base,
                text=name,
            )
            results[name] = store.admit(batch, g)
        finally:
            store.close()

    threads = [
        threading.Thread(target=writer, args=("a", 1)),
        threading.Thread(target=writer, args=("b", 10)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    kinds = sorted(type(r).__name__ for r in results.values())
    assert kinds == ["Applied", "RevisionConflict"], results
    winner = next(n for n, r in results.items() if isinstance(r, Applied))
    loser = next(n for n, r in results.items() if isinstance(r, RevisionConflict))
    store, _ = open_store(project, create=False, grant=grant)
    applied = results[winner]
    assert isinstance(applied, Applied)
    assert store.head() == applied.revision
    conflict = results[loser]
    assert isinstance(conflict, RevisionConflict)
    assert conflict.current_revision == applied.revision.revision_id
    assert counter_of(store) == (1 if winner == "a" else 10)
    assert [i.intent_id.value for i in store.intents()] == [f"effect-{winner}"]
    assert [o.intent_id.value for o in store.pending_outbox()] == [f"effect-{winner}"]
    assert event_count(store) == 2
    assert store.verify(deep=True).ok
    store.close()


# ----------------------------------------------------------------------------- outbox / facts


def test_outbox_claim_and_generation_fenced_facts(tmp_path: Path) -> None:
    ledger, grant = open_store(tmp_path / "proj")
    new_project(ledger)
    res = ledger.admit(envelope(ledger, [{"op": "intent", "id": "effect-a"}]), grant)
    assert isinstance(res, Applied)
    head = ledger.head()
    pending = ledger.pending_outbox()
    assert len(pending) == 1 and pending[0].transition is IntentState.QUEUED
    claimed = ledger.claim_outbox(pending[0].seq, Generation(7), grant, {"worker": "w1"})
    assert isinstance(claimed, OutboxRow) and claimed.generation == Generation(7)
    assert ledger.pending_outbox() == ()
    assert [o.intent_id.value for o in ledger.dispatched_outbox()] == ["effect-a"]
    stale = ledger.admit_fact(
        IntentFact(IntentId("effect-a"), Generation(6), IntentState.RUNNING, {"pid": 1}), grant
    )
    assert isinstance(stale, Rejected) and stale.contract_reason.code is RejectCode.STALE_GENERATION
    running = ledger.admit_fact(
        IntentFact(IntentId("effect-a"), Generation(7), IntentState.RUNNING, {"pid": 1}), grant
    )
    assert isinstance(running, FactRecorded)
    assert running.intent.state is IntentState.RUNNING
    assert running.event.kind is EventKind.JOB_FACT
    illegal = ledger.admit_fact(
        IntentFact(IntentId("effect-a"), Generation(7), IntentState.QUEUED, {}), grant
    )
    assert isinstance(illegal, Rejected)
    assert illegal.contract_reason.code is RejectCode.ILLEGAL_TRANSITION
    done = ledger.admit_fact(
        IntentFact(IntentId("effect-a"), Generation(7), IntentState.COMPLETED, {"sha": "x"}), grant
    )
    assert isinstance(done, FactRecorded)
    unknown = ledger.admit_fact(
        IntentFact(IntentId("effect-zz"), Generation(7), IntentState.RUNNING, {}), grant
    )
    assert (
        isinstance(unknown, Rejected) and unknown.contract_reason.code is RejectCode.UNKNOWN_INTENT
    )
    assert ledger.head() == head  # facts never move the head
    assert ledger.verify(deep=True).ok
    ledger.close()


# ---------------------------------------------------------------------------- crash injection (V12)


def _raise_at(point: str) -> None:
    raise InjectedFault(point)


@pytest.mark.parametrize("point", ["before_seal", "after_seal", "before_commit"])
def test_fault_before_commit_leaves_prior_head_and_replay_applies_once(
    tmp_path: Path, point: str
) -> None:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    new_project(ledger)
    head = ledger.head()
    referenced = ledger.referenced_blobs()
    ledger.close()

    faulty, _ = open_store(
        project, create=False, grant=grant, faults=lambda p: _raise_at(p) if p == point else None
    )
    batch = envelope(faulty, [{"op": "add", "k": 3}, {"op": "intent", "id": "effect-a"}])
    with pytest.raises(InjectedFault):
        faulty.admit(batch, grant)
    faulty.close()

    store, _ = open_store(project, create=False, grant=grant)
    assert store.head() == head
    assert event_count(store) == 1
    assert store.intents() == () and store.pending_outbox() == ()
    assert store.idempotency_record(batch.replay_key) is None
    orphans = store.cas.orphans(referenced)
    if point == "before_seal":
        assert orphans == []
    else:
        assert orphans, "sealed blobs without authority are readable orphans"
    assert store.verify(deep=True).ok
    assert store.cas.staged_leftovers() == []
    # the same batch replays and applies exactly once
    result = store.admit(batch, grant)
    assert isinstance(result, Applied)
    assert counter_of(store) == 3
    assert [i.intent_id.value for i in store.intents()] == ["effect-a"]
    assert store.cas.orphans(store.referenced_blobs()) == []
    assert isinstance(store.admit(batch, grant), AlreadyApplied)
    store.close()


def test_fault_after_commit_is_recoverable_without_duplicate_intents(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    new_project(ledger)
    ledger.close()
    faulty, _ = open_store(
        project,
        create=False,
        grant=grant,
        faults=lambda p: _raise_at(p) if p == "after_commit" else None,
    )
    batch = envelope(faulty, [{"op": "add", "k": 3}, {"op": "intent", "id": "effect-a"}])
    with pytest.raises(InjectedFault):
        faulty.admit(batch, grant)  # the caller never sees the result
    faulty.close()
    store, _ = open_store(project, create=False, grant=grant)
    assert counter_of(store) == 3 and event_count(store) == 2
    replay = store.admit(batch, grant)
    assert isinstance(replay, AlreadyApplied)
    assert replay.original_result.revision == store.head()
    assert [i.intent_id.value for i in store.intents()] == ["effect-a"]
    assert len(store.pending_outbox()) == 1
    assert store.verify(deep=True).ok
    store.close()


_CRASH_SCRIPT = """
import os, sys
sys.path.insert(0, {tests_dir!r})
from pathlib import Path
from ledger_support import open_store, envelope, ACTOR
from aidashvideo.ledger import ProjectGrant
point = sys.argv[2]
project = Path(sys.argv[1])
grant = ProjectGrant(sys.argv[3], project, ACTOR)
def hook(p):
    if p == point:
        os._exit(137)  # hard crash: no cleanup, no rollback code runs
store, g = open_store(project, create=False, grant=grant, faults=hook)
store.admit(envelope(store, [{{"op": "add", "k": 3}}, {{"op": "intent", "id": "effect-a"}}]), g)
"""


@pytest.mark.parametrize("point", ["after_seal", "before_commit", "after_commit"])
def test_process_killed_at_persistence_points_recovers_on_reopen(
    tmp_path: Path, point: str
) -> None:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    new_project(ledger)
    head = ledger.head()
    ledger.close()
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            _CRASH_SCRIPT.format(tests_dir=str(Path(__file__).parent)),
            str(project),
            point,
            grant.grant_id,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(project),
    )
    assert proc.returncode == 137, proc.stderr
    store, _ = open_store(project, create=False, grant=grant)
    assert store.verify(deep=True).ok
    if point == "after_commit":
        assert counter_of(store) == 3 and event_count(store) == 2
        assert [i.intent_id.value for i in store.intents()] == ["effect-a"]
    else:
        assert store.head() == head and event_count(store) == 1
        assert store.intents() == ()
    batch = envelope(
        store, [{"op": "add", "k": 3}, {"op": "intent", "id": "effect-a"}], base=head.revision_id
    )
    replay = store.admit(batch, grant)
    assert isinstance(replay, AlreadyApplied if point == "after_commit" else Applied)
    assert counter_of(store) == 3 and event_count(store) == 2
    assert [i.intent_id.value for i in store.intents()] == ["effect-a"]
    assert len(store.pending_outbox()) == 1
    store.close()


# ----------------------------------------------------------------------------- foreign writes (I2)


def test_direct_sqlite_head_write_is_detected_as_foreign(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    new_project(ledger)
    root = ledger.head()
    assert isinstance(ledger.admit(envelope(ledger, [{"op": "add", "k": 1}]), grant), Applied)
    ledger.close()
    conn = sqlite3.connect(project / "project.sqlite")
    conn.execute("UPDATE heads SET head_revision_id = ?", (root.revision_id.hex,))
    conn.commit()
    conn.close()
    opened = Ledger.open(project, grant, CounterDomain())
    assert isinstance(opened, Corrupt)
    assert any("latest" in f for f in opened.findings)


def test_edited_payload_file_is_detected(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    new_project(ledger)
    head = ledger.head()
    ledger.close()
    CasRoot(project / "cas").path_of(head.payload_sha256).write_bytes(b'{"n":999}')
    opened = Ledger.open(project, grant, CounterDomain())
    assert isinstance(opened, Corrupt)
    assert any("BlobCorrupt" in f for f in opened.findings)


def test_impossible_domain_output_fails_visibly(tmp_path: Path) -> None:
    """A domain that returns an already-admitted revision id is an impossible state."""

    class BrokenDomain(CounterDomain):
        def revision_id(
            self, document: bytes, parent: ParentRef, project_id: ProjectId
        ) -> RevisionId:
            if isinstance(parent, Parent):
                return parent.revision_id  # claims the base itself as the result
            return super().revision_id(document, parent, project_id)

    ledger, grant = open_store(tmp_path / "proj", domain=BrokenDomain())
    new_project(ledger)
    head = ledger.head()
    with pytest.raises(InvariantViolation):
        ledger.admit(envelope(ledger, [{"op": "add", "k": 1}]), grant)
    assert ledger.head() == head and event_count(ledger) == 1
    ledger.close()


# ----------------------------------------------------------------------------- schema fences (V30)


def _set_schema(project: Path, writer: int, min_reader: int) -> None:
    conn = sqlite3.connect(project / "project.sqlite")
    conn.execute(
        "UPDATE schema_version SET writer_version = ?, min_reader_version = ? WHERE id = 1",
        (writer, min_reader),
    )
    conn.commit()
    conn.close()


def test_newer_writer_is_readable_but_not_writable(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    new_project(ledger, 2)
    head = ledger.head()
    ledger.close()
    _set_schema(project, writer=2, min_reader=1)
    opened = Ledger.open(project, grant, CounterDomain())
    assert isinstance(opened, Opened) and isinstance(opened.mode, ReadOnly)
    store = opened.ledger
    assert store.head() == head and counter_of(store) == 2  # history stays readable
    res = store.admit(envelope(store, [{"op": "add", "k": 1}]), grant)
    assert isinstance(res, Rejected)
    assert res.contract_reason.code is RejectCode.UNSUPPORTED_SCHEMA
    assert isinstance(store.import_snapshot(b'{"$id":"counter-snapshot/1","n":1}'), InvalidSnapshot)
    assert store.head() == head
    store.close()
    report = ledger_inspect(project, deep=True)
    assert report["open"] == "Opened" and report["mode"] == "ReadOnly"


def test_min_reader_above_this_code_is_fenced(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    new_project(ledger)
    ledger.close()
    _set_schema(project, writer=3, min_reader=3)
    opened = Ledger.open(project, grant, CounterDomain())
    assert opened == Fenced(3, 3, 1)
    assert ledger_inspect(project, deep=False)["open"] == "Fenced"


# ----------------------------------------------------------------------------- migration (V30)


def test_migration_creates_new_revisions_and_keeps_old_payloads(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    new_project(ledger, 1)
    assert isinstance(ledger.admit(envelope(ledger, [{"op": "add", "k": 1}]), grant), Applied)
    old_head = ledger.head()
    old_events = ledger.all_events()
    ledger.close()

    v2, _ = open_store(project, create=False, grant=grant, domain=CounterDomain(version=2))
    blocked = v2.admit(envelope(v2, [{"op": "add", "k": 1}], key="v2-0123456789abcdef"), grant)
    assert isinstance(blocked, Rejected)
    assert blocked.contract_reason.code is RejectCode.MIGRATION_REQUIRED
    bad_plan = MigrationPlan(target_document_version=3)
    assert isinstance(v2.migrate(bad_plan, grant), Rejected)
    result = v2.migrate(MigrationPlan(target_document_version=2, backup_copy=True), grant)
    assert isinstance(result, MigrationApplied)
    assert len(result.revisions) == 1 and result.events[0].kind is EventKind.MIGRATION
    new_head = v2.head()
    assert new_head == result.revisions[0]
    assert new_head.parent == Parent(old_head.revision_id) and new_head.schema_version == 2
    assert v2.cas.read(new_head.payload_sha256) == b'{"n":2,"v":2}'
    assert v2.cas.read(old_head.payload_sha256) == b'{"n":2}'  # old payload retained
    assert v2.all_events()[: len(old_events)] == old_events  # history retained
    assert len(v2.lineage(new_head.revision_id)) == 3
    assert (project / "project.sqlite.pre-1").is_file()
    assert result.backup == "project.sqlite.pre-1"
    # repeated migration adds nothing
    assert isinstance(v2.migrate(MigrationPlan(target_document_version=2), grant), NothingToMigrate)
    assert len(v2.all_events()) == len(old_events) + 1
    after = v2.admit(envelope(v2, [{"op": "add", "k": 1}], key="v2-0123456789abcdef"), grant)
    assert isinstance(after, Applied) and counter_of(v2) == 3
    assert v2.verify(deep=True).ok
    v2.close()
    # the old (v1) domain still reads everything, but cannot write on the v2 head
    v1, _ = open_store(project, create=False, grant=grant)
    assert v1.head().schema_version == 2
    res = v1.admit(envelope(v1, [{"op": "add", "k": 1}], key="v1-0123456789abcdef"), grant)
    assert isinstance(res, Rejected) and res.contract_reason.code is RejectCode.MIGRATION_REQUIRED
    v1.close()


# ---------------------------------------------------------------------------- portable import (V30)


def test_import_creates_a_new_lineage_and_never_replaces_the_canonical_head(tmp_path: Path) -> None:
    ledger, grant = open_store(tmp_path / "proj")
    new_project(ledger, 7)
    head = ledger.head()
    snapshot = canonical_bytes({"$id": "counter-snapshot/1", "n": 42})
    result = ledger.import_snapshot(snapshot)
    assert isinstance(result, NewLineage)
    root = result.root_revision
    assert root.project_id != PROJECT and root.parent == Root()
    assert ledger.head() == head  # canonical head untouched
    assert counter_of(ledger, root.project_id) == 42
    assert ledger.lineages() == (PROJECT, root.project_id)
    assert ledger.events(root.project_id)[0].kind is EventKind.IMPORT
    # importing the same bytes again does not duplicate the lineage or its events
    again = ledger.import_snapshot(snapshot)
    assert isinstance(again, NewLineage) and again.root_revision == root
    assert len(ledger.lineages()) == 2 and len(ledger.events(root.project_id)) == 1
    # edits on the imported lineage are ordinary admissions against its own head
    batch = BatchEnvelope.build(
        actor=ACTOR,
        project_id=root.project_id,
        base_revision=root.revision_id,
        replay_key=ReplayKey("import-edit-0123456789"),
        preconditions=[],
        operations=[{"op": "add", "k": 1}],
        provenance=UserWording("edit imported"),
    )
    assert isinstance(ledger.admit(batch, grant), Applied)
    assert counter_of(ledger, root.project_id) == 43 and counter_of(ledger) == 7
    # invalid and unsupported snapshots are typed results
    assert isinstance(ledger.import_snapshot(b"not json"), InvalidSnapshot)
    assert isinstance(ledger.import_snapshot(canonical_bytes({"$id": "other/1"})), InvalidSnapshot)
    unsupported = ledger.import_snapshot(
        canonical_bytes({"$id": "counter-snapshot/1", "n": 1, "schema_version": 9})
    )
    assert unsupported == UnsupportedSchema(9, 1)
    assert ledger.verify(deep=True).ok
    ledger.close()


def test_inspect_command_reports_heads_lineage_and_outbox(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    new_project(ledger)
    assert isinstance(
        ledger.admit(envelope(ledger, [{"op": "intent", "id": "effect-a"}]), grant), Applied
    )
    ledger.close()
    proc = subprocess.run(
        [sys.executable, "-m", "aidashvideo.ledger", "inspect", str(project), "--deep"],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["open"] == "Opened" and report["mode"] == "Writable"
    assert report["integrity"] == {"ok": True, "findings": []}
    assert len(report["lineages"]) == 1 and len(report["lineages"][0]["lineage"]) == 2
    assert report["outbox_pending"][0]["intent_id"] == "effect-a"
    assert report["cas_orphans"] == []


def test_payload_size_limit_is_enforced(tmp_path: Path) -> None:
    ledger, grant = open_store(tmp_path / "proj")
    new_project(ledger)
    huge = envelope(ledger, [{"op": "add", "k": 1, "pad": "x" * (64 * 1024 * 1024 + 1)}])
    res = ledger.admit(huge, grant)
    assert isinstance(res, Rejected) and res.contract_reason.code is RejectCode.PAYLOAD_TOO_LARGE
    ledger.close()


def test_open_modes_are_values(tmp_path: Path) -> None:
    ledger, _ = open_store(tmp_path / "proj")
    assert isinstance(ledger.mode, Writable)
    ledger.close()


def test_store_held_by_another_writer_is_a_typed_unavailability(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    new_project(ledger)
    head = ledger.head()
    holder = sqlite3.connect(project / "project.sqlite", isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")  # a foreign writer holding the lock past the busy timeout
    try:
        res = ledger.admit(envelope(ledger, [{"op": "add", "k": 1}]), grant)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert isinstance(res, Rejected) and res.contract_reason.code is RejectCode.STORE_BUSY
    assert ledger.head() == head and event_count(ledger) == 1
    again = ledger.admit(envelope(ledger, [{"op": "add", "k": 1}]), grant)
    assert isinstance(again, Applied)
    ledger.close()
