# AiDashVideo implementation plan (frozen at Milestone 0, revised 2026-10-21)

Companion files: [contracts.md](contracts.md) (normative semantics),
[runtime-profile.json](runtime-profile.json) (toolchain identities and limits),
[provider-manifest.json](provider-manifest.json) (analysis adapters and acquisition),
[verification-matrix.md](verification-matrix.md), [commands.md](commands.md),
[fixtures.md](fixtures.md). Scope comes from the operator's briefs in
[../design/](../design/README.md); the acceptance contract is
[../design/milestone-6.md](../design/milestone-6.md). Milestone 0 evidence:
[../evidence/milestone-0.md](../evidence/milestone-0.md).

## 1. Product boundary

AiDashVideo is a standalone local editor controlled through conversation. MLT evaluates the
timeline and supplies playback/export; FFmpeg supplies explicit media jobs; timed speech (FFmpeg
`whisper` filter) and one separately qualified **SAM 3.1 MLX** adapter (mlx-vlm on Apple
Silicon Metal) supply analysis. Immutable source media plus a versioned project in SQLite are
the only authority. Tools run through `uv run --offline --no-sync`; a missing tool is a named
blocker, never permission to fetch it.

Target host: the operator's MacBook Pro (Apple M1 Pro, 16 GB unified memory, macOS arm64).
The frozen identities are installed there ([../evidence/target-m1-install-2026-10-20.md](../evidence/target-m1-install-2026-10-20.md)).
Development sandbox: Linux x86_64, no GPU; it can build and test everything that does not need
Metal (domain, ledger, compiler, MLT engine with the Linux recipe, speech) and must never claim
subject (SAM 3.1) qualification. There is exactly one mask profile; no CPU, remote or
alternative-model fallback exists.

## 2. Module boundaries

### Responsibility owners (bound once)

| Responsibility | Owner module |
| --- | --- |
| project domain | `aidashvideo.project` |
| canonical admission | `aidashvideo.ledger` |
| media/artifact store | `aidashvideo.store` |
| capability catalog | `aidashvideo.catalog` |
| graph compiler | `aidashvideo.compiler` |
| native MLT worker | `aidashvideo.mltworker` |
| speech/mask adapters | `aidashvideo.analysis` |
| one job supervisor | `aidashvideo.jobs` |
| chat/client | `aidashvideo.client` |

Head-write rule: only `aidashvideo.ledger` writes project heads, operation events, idempotency records and job/effect intents, inside one SQLite transaction; `aidashvideo.mltworker` and `aidashvideo.client` cannot write project heads.

| Module | Owns | Public interface (concrete names) | May not |
| --- | --- | --- | --- |
| `aidashvideo.project` | `Revision`, `ProjectDocument`, `OperationBatch`/`Operation`, inverse ops, `undo`, `timing`, `geometry`, `identity`, portable snapshot schema | `apply_batch(doc, batch, catalog) -> ProjectDocument | Rejected`, `inverse(op, doc) -> Operation`, `undo.plan(head, event_seq) -> OperationBatch | UndoConflict`, `timing.*`, `geometry.*`, `identity.revision_id(doc, parent)`, `snapshot.export(revision) / snapshot.validate(bytes)` | touch SQLite, spawn processes, import providers |
| `aidashvideo.ledger` | SQLite schema, `admit(batch, grant) -> ApplyResult`, idempotency, intents, outbox, grants, caller identity, migrations, portable import as new lineage | `Ledger.open(project_dir, grant)`, `Ledger.admit`, `Ledger.head()`, `Ledger.snapshot(revision_id)`, `Ledger.pending_outbox()`, `Ledger.migrate(plan)`, `Ledger.import_snapshot(bytes) -> ImportResult` | compile graphs, run media tools, decide edit semantics |
| `aidashvideo.store` | `SourceIdentity`, `AssetAvailability`, `ProbeReceipt`, CAS artifacts, job snapshots (copy-on-write clones) | `Store.import_source(locator, grant) -> SourceIdentity`, `Store.availability(asset) -> AssetAvailability`, `Store.put(bytes|path, kind, deps) -> ArtifactRef`, `Store.open(ref)`, `Store.snapshot_for_job(asset, job_id) -> VerifiedClone` | write outside `cas/`, `snapshots/` and `scratch/`, modify sources, write heads |
| `aidashvideo.catalog` | host profile requirements, `Readiness`, FFmpeg/MLT probes, service descriptors (`MLTService`/`MLTParameter`), observed digests, model asset admission, offline env, `aidashvideo-doctor`, `aidashvideo-models` | `doctor.collect()`, `ffmpeg.probe()`, `mlt.probe()`, `descriptors.freeze(build) / descriptors.load(catalog_digest)`, `models.admit`, `offline.provider_environment()` | download, install, hold project state |
| `aidashvideo.compiler` | `Revision -> CompiledGraph` (semantic graph JSON + MLT XML), `graph_id`, parameter validation against descriptors, the single inclusive-`out` conversion, visual-order lowering, LiteralText escaping, hashed FFmpeg intermediates | `compile(revision, catalog) -> CompiledGraph | Rejected`, `identity.graph_id(graph, catalog_digest, inputs)` | call MLT bindings, persist XML as authority |
| `aidashvideo.mltworker` | the only process importing `mlt7`; frame sessions (frame pull, play/pause/seek/rate), graph switch at a boundary, avformat export, generation fencing | `python -m aidashvideo.mltworker --generation N` (child), `MltWorkerClient` (parent side) | write `project.sqlite`, publish outputs (writes `destination_tmp` only), decide staleness |
| `aidashvideo.analysis` | `speech` (`FfmpegWhisperAdapter`, phrase selection, corrections, caption events), `masks` (`Sam31MlxBackend`, `SubjectTracker`, durable `MaskTrack` store and `MaskKey`), qualification harnesses | `TimedSpeechAdapter.transcribe`, `speech.select_phrase`, `SubjectTracker.request / reuse`, `qualify_masks(fixture) -> QualityReport`, `qualify_alignment(samples)` | import providers at module import time, fetch weights, write heads, run on CPU and call it qualified |
| `aidashvideo.jobs` | the single supervisor: outbox dispatch, worker/process ownership, limits, cancellation, recovery/reconciliation, `FfmpegJobRunner`, export staging/publication and `RenderOutcome` admission, analysis cache keys | `Supervisor.run_once()`, `Supervisor.cancel(intent_id)`, `Supervisor.reconcile()`, `FfmpegJobRunner.run` | apply edits, talk to the chat model |
| `aidashvideo.client` | local UI (project open/import/preview/export controls, Cancel, history), chat (`ChatModelProvider`, `tools`, `EditProposal` rendering), the stdio `ToolServer`, displayed-revision binding | `python -m aidashvideo.client`, `python -m aidashvideo.client.tools --grant-file`, `chat.propose(turn) -> EditProposal` | write heads; it calls `Ledger.admit` with the displayed `base_revision` |

Dependency direction: `client -> jobs -> {compiler, analysis, mltworker-client} -> {project, store, catalog} -> ledger` is forbidden in reverse; `ledger` depends on nothing above it. Enforced by a Ruff `banned-api`/import-layering rule added in M1.

## 3. Supplier interfaces and readiness

| Supplier | Interface (exact) | Readiness (target) | Evidence | First consumer |
| --- | --- | --- | --- | --- |
| FFmpeg 9.0.2 (+whisper, libass, freetype, x264) | CLI `ffmpeg`/`ffprobe`, argv from typed fields ([contracts §8](contracts.md#8-supplier-interfaces-concrete-local)) | Verified | target build in the deps dir; doctor round trip; `pytest -m live` ([../evidence/target-m1-install-2026-10-20.md](../evidence/target-m1-install-2026-10-20.md)) | `aidashvideo.store` (probe), M1 |
| MLT 7.42.0 (22 modules, Qt6 headless, frei0r 3.6.0) | `melt` CLI for smoke; `mlt7` Python bindings (CPython 3.14) inside `aidashvideo.mltworker`; `melt -query` YAML for descriptors | Verified | target build; 30-frame 1080p30 render decoded; inventory recorded | `aidashvideo.catalog.descriptors`, M2 |
| Python 3.14.7 (uv-managed) + uv 0.12.11 + pyright 1.1.414 | `uv run --offline --no-sync` | Verified | target; sandbox runs the same lock on CPython 3.12 for domain work | all, M1 |
| Timed speech | `FfmpegWhisperAdapter` over the FFmpeg `whisper` filter (whisper.cpp 1.9.5, Metal) + `ggml-base.en.bin` | Verified (installed; not quality-qualified) | synthesized phrase transcribed with queue-quantised segment timing on the target | `aidashvideo.analysis.speech`, M3 |
| SAM 3.1 MLX | `Sam31MlxBackend` over mlx-vlm 0.7.8 (`MultiplexTrackerModel`, `Sam3Predictor`, `Sam31Processor`), `mlx-community/sam3.1-bf16` snapshot `97ae6308…`, `openai/clip-vit-base-patch32` tokenizer files | Verified (installed; not quality-qualified) | offline load and synthetic-subject segmentation on Metal; 5.4 GiB peak | `aidashvideo.analysis.masks`, M4 |
| Chat model | `ChatModelProvider` over an operator-chosen local tool-capable model (OpenAI-compatible HTTP on localhost or an in-process mlx-lm model) | Missing | operator has not named the model; no credentials or egress are granted by the plan | `aidashvideo.client.chat`, M5 |
| Word alignment | adapter producing `Transcript.WordAligned` with a qualification | Missing | deferred (D4); V06 stays open | `aidashvideo.analysis.speech`, after M3 |

Details and observed facts: [runtime-profile.json](runtime-profile.json),
[provider-manifest.json](provider-manifest.json).

## 4. Milestones: entry and exit states (numbering follows [../design/README.md](../design/README.md))

| Milestone | Entry | Exit (all must hold) |
| --- | --- | --- |
| M0 repository and contracts (this) | README, LICENSE, NOTICE | plan files resolve and agree; boot isolation test passes and is mutation-proven; readiness recorded with three words per area; target toolchain and assets installed and smoke-tested; evidence report hashes recompute |
| M1 durable project domain | M0 passed | `ledger` (admission first, tested alone), `store`, `project` (closed variants, `OperationBatch`, all required and descriptor-bound operations, inverses, `undo`, `timing`, `geometry`, portable snapshot/import), grants; real SQLite close/reopen, replay, concurrency and crash-injection evidence; no MLT or model inference required |
| M2 MLT engine, previews, media jobs | M1 passed | `catalog.descriptors` (complete frozen inventory reconciled with the installed build), `compiler`, `mltworker` (frame sessions, transport, graph switch, export), `jobs` (supervisor, limits, `FfmpegJobRunner`, staging/publication, reconciliation); native positive controls for every included service; V12, V13, V15, V16, V22, V23, V25-V29 evidence |
| M3 timed speech | M2 passed | `analysis.speech`: `SegmentTimed`/`NoSpeech`/`RecognitionFailed` on real fixtures, phrase selection with ambiguity, corrections, caption events (burn-in and sidecar), cache identity; V05 evidence; V06 stays blocked until an alignment adapter is decided |
| M4 SAM 3.1 MLX subjects | M3 passed | `analysis.masks`: `SubjectAssets`, isolated Metal worker, text/visual selection, `track_init`/`track_step`/correction in PTS order, durable `MaskTrack`s with `MaskKey`, blur composite; V07, V08, V17, V18, V19 evidence on the target |
| M5 chat, player, lifecycle | M4 passed | `client`: real tool-capable chat through the stdio `ToolServer`, five method families, displayed-revision binding, player/transport, truthful async states, save/reopen/import/relink/migration/rollback; GP-01 steps 1-8 end to end; V01, V02, V09, V10, V11, V14, V20, V21, V24, V30 evidence |
| M6 verification | M0-M5 passed | per [../design/milestone-6.md](../design/milestone-6.md): every row, invariant and GP-01 step with retained evidence, measurements on the named host |
| M7 operator review | M6 passed | explicit human approval of the exact candidate |
| M8 local delivery | M7 approved | fresh-session reproduction, manifests, runbook, retained evidence |

## 5. Incremental work order

1. M1a `aidashvideo.ledger`: closed ids/results, schema, `admit` with seal-then-commit ordering,
   idempotency, compare-and-swap, outbox, grants and caller identity; tested alone with a real
   temporary SQLite store before any consumer exists.
2. M1b `aidashvideo.store`: CAS, probe receipts via `ffprobe` (tool identity recorded; FFmpeg
   9.0.2 on the target, the sandbox's installed FFmpeg is recorded as such), `AssetAvailability`,
   job snapshots.
3. M1c `aidashvideo.project.timing` and `geometry` with property tests (exact rationals, VFR
   tables, `TimeMap` holds/reverse, orientation).
4. M1d `aidashvideo.project` document, required and descriptor-bound operations, inverses,
   `undo.plan`, portable snapshot export/validate and `Ledger.import_snapshot`.
5. M2a `catalog.descriptors` (`melt -query` YAML into `MLTService`/`MLTParameter`, version-bound
   descriptors where upstream metadata is missing), M2b `compiler` (+ `graph_id`, visual order,
   inclusive `out`), M2c `mltworker` sessions/export, M2d `jobs` + `FfmpegJobRunner` + limits +
   publication/reconciliation.
6. M3 `analysis.speech` (adapter, phrase selection, corrections, caption events, cache keys).
7. M4 `analysis.masks` (`SubjectAssets`, worker, selection, tracking, correction, durable
   tracks, composite) on the target only; qualification harness (V08).
8. M5 `client` (`ToolServer`, chat provider, UI, player, lifecycle).
9. M6 verification and measurements; M7 review; M8 delivery.

## 6. Decisions

| # | Decision | Rationale |
| --- | --- | --- |
| D1 | Frozen core identities: FFmpeg 9.0.2, MLT 7.42.0, whisper.cpp 1.9.5, ggml 0.26.0, frei0r 3.6.0, Python 3.14 | latest mutually compatible set (Debian sid pairs MLT 7.42.0-1 with FFmpeg 9.0.2); installed and verified on the target |
| D2 | FFmpeg is built from source with `--enable-whisper --enable-libass --enable-libfreetype --enable-libfontconfig --enable-libharfbuzz --enable-libfribidi --enable-libx264` | Homebrew's and Debian's FFmpeg 9 builds omit whisper; Homebrew's also omits libass/freetype (captions, titles) |
| D3 | Timed ASR = FFmpeg `whisper` filter; whisper.cpp CLI is a named alternative, never an automatic fallback | one fewer process type; same ggml models; segment-level timing is explicit (`SegmentTimed`) |
| D4 | Word-level alignment is deferred; `WordAligned` exists in the contract but no adapter produces it | operator deferred; V06 stays open and captions use segment timing marked unqualified |
| D5 | Exactly one mask profile: SAM 3.1 through mlx-vlm 0.7.8 on Metal with `mlx-community/sam3.1-bf16` and the `openai/clip-vit-base-patch32` tokenizer. SAM 3 (PyTorch/transformers), EdgeTAM, the official `sam3` PyPI package and `sam3-mlx` are dropped | operator decision 2026-10-20/21 (design brief); no CPU, remote or alternative-model fallback can be labeled qualified |
| D6 | Masks stored on the source `OrientedGrid` as durable per-object `MaskTrack` versions keyed by `MaskKey` | profile-independent cache identity; survives restart and model eviction (V18, V21, V27) |
| D7 | SQLite (WAL) in the project directory is the single authority; CAS for payloads and artifacts; outbox for dispatch; seal bytes before the transaction | single canonical transaction boundary (I2, I3, V12) |
| D8 | Worker is a child process with a generation number; the client never holds a write connection | I9, V26-V28 fencing |
| D9 | `requires-python = ">=3.12,<3.15"`; target runs 3.14.7, the sandbox 3.12; ruff/pyright target the lowest supported version | code must run on both; interpreter downloads stay disabled |
| D10 | Chat integration = one local tool-capable model behind `ChatModelProvider` talking to the stdio `ToolServer`; caller identity and grants come from the client process, never from model text | I8, V09, V11; the operator names the model before M5 |
| D11 | Version and capability requirements are pinned; build digests (FFmpeg capability, MLT catalog) are observed facts, not pins | operator decision 2026-10-21; builds differ per host; V29 compares a project's recorded digest with the installed build |
| D12 | Toolchain builds and admitted models live in the per-user data dir (`$XDG_DATA_HOME/aidashvideo/deps`), not in the checkout | checkouts proved ephemeral for ignored files; multi-GB assets must survive sessions |
| D13 | Qualified host is the Apple M1 Pro with 16 GB; limits in [contracts §10](contracts.md#10-resource-limits-qualified-host-apple-m1-pro-16-gb-unified-memory) | the plan's earlier M3 Pro / 36 GB statement was wrong for the operator's machine |
| D14 | Inpainting and DINOv3 are typed `Capability.Unavailable` extension contracts only | design brief; no acquisition or qualification planned |

## 7. Non-goals (v1)

Real-time SAM on arbitrary footage; HDR delivery; multicam and synchronized multicam; cloud
rendering; automatic model download; plug-in marketplaces; editing while a source is being
modified; byte-identical GPU/codec output across hosts (identical semantic graph identities are
required instead); QuickTime automation or arbitrary external chat windows (V2); high-level
stabilization intent solving; arbitrary scripts/XML; general template/interchange compatibility.

## 8. Migration and rollback design

- `schema_version` stores `(writer_version, min_reader_version)`. A newer writer opening an
  older project runs `Ledger.migrate(plan)` only inside one transaction that appends a
  `Migration` operation event and keeps every prior row and payload; a reader older than
  `min_reader_version` refuses to open (fenced, V30); an unsupported version stays readable
  without permitting incompatible writers.
- Rollback of the application: prior binaries keep reading the project because migrations are
  additive until M7; a destructive step requires an explicit operator decision and a copy of
  `project.sqlite` next to it (`project.sqlite.pre-<version>`), recorded in the event.
- Toolchain upgrade (V29): the catalog digest recorded with a revision's compiled graph is
  compared with the installed build; a mismatch is reported and previews/exports need an
  explicit qualified choice (`RecompileWithNewCatalog`) and never a silent default.
- Portable reimport (V30): `Ledger.import_snapshot` validates the file and admits a new
  lineage; sources are matched by content hash, never by path; imported files grant no execution
  permission.

## 9. Open items carried into M1

Recorded as `Missing`/`Conflicting` entries in [runtime-profile.json](runtime-profile.json) and
[provider-manifest.json](provider-manifest.json): chat model choice (before M5), word-alignment
adapter (V06), title/caption font identity on the target, GP-01 fixture regeneration on the
target with the frozen FFmpeg, operator-owned annotated footage for V06/V07/V08.
