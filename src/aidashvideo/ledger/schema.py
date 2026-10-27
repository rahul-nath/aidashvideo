"""SQLite schema of ``project.sqlite`` (contracts §5) and the ledger's own version fence."""

from __future__ import annotations

LEDGER_WRITER_VERSION = 1
"""Version this code writes; stored in ``schema_version.writer_version``."""

LEDGER_MIN_READER_VERSION = 1
"""Oldest reader that can still read what this code writes."""

DB_FILENAME = "project.sqlite"

DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    writer_version INTEGER NOT NULL,
    min_reader_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS lineages (
    project_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('canonical', 'import')),
    created_event INTEGER NOT NULL,
    origin_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
    revision_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES lineages(project_id),
    parent_id TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    admitted_event_id INTEGER NOT NULL,
    schema_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS heads (
    project_id TEXT PRIMARY KEY REFERENCES lineages(project_id),
    head_revision_id TEXT NOT NULL REFERENCES revisions(revision_id)
);
CREATE TABLE IF NOT EXISTS operation_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES lineages(project_id),
    kind TEXT NOT NULL CHECK (kind IN ('Edit','Undo','Import','Rebind','JobFact','EffectFact',
                                       'Migration')),
    actor_json TEXT NOT NULL,
    base_revision TEXT NOT NULL,
    result_revision TEXT NOT NULL,
    batch_sha256 TEXT NOT NULL,
    applied_sha256 TEXT NOT NULL,
    inverse_sha256 TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    affected_json TEXT NOT NULL,
    replay_key TEXT NOT NULL,
    intents_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency (
    replay_key TEXT PRIMARY KEY,
    payload_sha256 TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS intents (
    intent_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES lineages(project_id),
    kind TEXT NOT NULL,
    revision_id TEXT NOT NULL REFERENCES revisions(revision_id),
    generation INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('Queued','Running','Cancelled','Failed','Completed',
                                         'Reconciling')),
    spec_json TEXT NOT NULL,
    limits_json TEXT NOT NULL,
    deadline_s INTEGER NOT NULL,
    created_event INTEGER NOT NULL,
    updated_event INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_id TEXT NOT NULL REFERENCES intents(intent_id),
    transition TEXT NOT NULL,
    event_seq INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox_done (
    seq INTEGER PRIMARY KEY,
    intent_id TEXT NOT NULL,
    transition TEXT NOT NULL,
    event_seq INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    dispatched_at TEXT NOT NULL,
    receipt_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    sha256 TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    producer_json TEXT NOT NULL,
    deps_json TEXT NOT NULL,
    semantic_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mask_tracks (
    track_version_id TEXT PRIMARY KEY,
    artifact_sha256 TEXT NOT NULL REFERENCES artifacts(sha256),
    mask_key_json TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    created_event INTEGER NOT NULL
);
"""
