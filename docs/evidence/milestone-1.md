# Milestone 1 evidence: durable project domain (Linux sandbox, 2026-10-23)

Verification below was performed by the implementing AI in the Linux sandbox. It is not an
independent review and not operator approval. Scope: [../design/milestone-1.md](../design/milestone-1.md)
against the frozen plan ([../plan/implementation-plan.md](../plan/implementation-plan.md),
[../plan/contracts.md](../plan/contracts.md)) and [milestone-0.md](milestone-0.md).

**Status: PASS for Milestone 1 as specified in [../design/milestone-1.md](../design/milestone-1.md)**,
with the contract refinements in section 3 recorded for the operator's decision (each is
an interpretation needed to make the frozen contract internally consistent; none lowers a
requirement) and the blockers in section 9. No MLT rendering and no model inference were
required or performed.

## Status by area (readiness words from [../plan/contracts.md §9](../plan/contracts.md#9-readiness-words))

| Area | Readiness (this host) | Evidence / smallest missing proof |
| --- | --- | --- |
| M1 domain: ledger, store, timing/geometry, project, undo, snapshot (this milestone) | done | 92 M1 tests (33 ledger, 11 store, 18 timing/geometry, 30 project incl. 4 layering) pass against real temporary SQLite stores; 119 non-live tests pass; ruff, ruff format and pyright strict clean |
| Core (Python 3.14.7, uv 0.9.10; FFmpeg 9.0.2 + MLT 7.42.0 frozen build) | **Conflicting** (sandbox) | the sandbox has no `.deps/frozen` toolchain this session: `tests/test_toolchain_live.py::test_ffmpeg_matches_pins_with_required_capabilities` fails on the system FFmpeg 6.1.1 (`filter:whisper` absent); M1 needs no native engine, and the one store test that uses an `ffprobe` records the sandbox tool identity (6.1.1-3ubuntu5) in the receipt instead of assuming 9.0.2 |
| Full MLT package inventory / descriptors | not started (M2) | `aidashvideo.catalog.descriptors` defines the closed `MLTService`/`MLTParameter`/catalog shapes and digest; the `melt -query` freeze is M2a |
| Timed speech | Missing (sandbox) | untouched; transcript evidence enters the document only through `RecordAnalysis` |
| SAM 3.1 MLX | Missing (sandbox, darwin-only) | untouched; `BindSubjectEffect` records a `Pending` mask track and one `Mask` intent, never coverage |
| Chat model | Missing | untouched |

## 1. What was built (reviewable increments = local commits on top of `0fc56de baseline`)

| Commit | Increment | Modules |
| --- | --- | --- |
| `f75d5c2` | M1a ledger: closed ids/quantities/results, CAS seal-then-commit, `admit` with idempotency and compare-and-swap, intents/outbox, grants and caller identity, facts with generation fencing, schema fence (read-only / fenced), migration, import as new lineage, `python -m aidashvideo.ledger inspect` | `src/aidashvideo/ledger/` (`ids`, `errors`, `results`, `canonical`, `cas`, `grants`, `domain`, `schema`, `ledger`, `__main__`), `tests/test_ledger.py`, `tests/ledger_support.py` |
| `f16aa39` | M1b store: `SourceIdentity`, `ProbeReceipt`/`StreamProbe` with exact rationals and `VfrTable`, `AssetAvailability`, `ffprobe` parsing with recorded tool identity, verified job clones, CAS artifacts | `src/aidashvideo/store/`, `tests/test_store.py` |
| `950325b` | M1c algebra: `project.timing` (spans, constant speed, `TimeMap`, VFR, audio, handles, requested/realized), `project.geometry` (`Affine2D`, `OrientedGrid`, `display_affine`, selections) | `src/aidashvideo/project/timing.py`, `geometry.py`, `text.py`, `tests/test_timing.py` |
| `d97f42a` | M1d project: document/portable schema, typed params, the closed operation set with inverses, `apply_batch`, `undo.plan`, `identity.revision_id`, `snapshot.export/validate`, `ProjectDomain` (ledger port), `session` | `src/aidashvideo/project/` (`document`, `params`, `operations`, `apply`, `undo`, `identity`, `snapshot`, `domain`, `session`), `src/aidashvideo/catalog/descriptors.py`, `tests/test_project.py`, `tests/project_support.py` |
| `d015cb2` and later | layering lint, `RecordAnalysis`/`RemoveAnalysis`, evidence artifacts sealed before admission, `StoreBusy`, captions realized through the shared map, `apply.inverse`, `intents.limits_json`, evidence script, README/pyproject markers, this report | `tests/test_layering.py`, `scripts/m1_evidence.py`, `docs/evidence/milestone-1.md` |

Work order followed [../plan/implementation-plan.md §5](../plan/implementation-plan.md#5-incremental-work-order):
the admission owner was implemented and tested alone (a trivial counter domain stands in
for the project) before any mutating consumer existed.

## 2. Contradictions surfaced in the frozen plan (before dependent integration)

| # | Contradiction | Resolution taken (no plan file was edited) |
| --- | --- | --- |
| C1 | `ledger` "depends on nothing above it" (plan §2) yet `Ledger.admit` must "validate the complete resulting project" (contracts §5 step 2) and `ApplyResult.Applied(revision, …)` carries a project `Revision` | Dependency inversion: `aidashvideo.ledger.domain.DomainPort` (bytes in, bytes out) is implemented by `aidashvideo.project.domain.ProjectDomain` and injected at `Ledger.open`. The ledger sees canonical bytes plus the closed batch header (`aidashvideo.operation-batch/1`); `Applied.revision` is the ledger's `AdmittedRevision` record (same fields as the wire `aidashvideo.revision/1`, document by payload hash) and `project.session.Revision` adds the parsed document. Checked by `tests/test_layering.py::test_ledger_depends_on_nothing_above_it`. |
| C2 | "Every operation has an inverse" (contracts §6) but the closed operation set has no removal operations, so `InsertOccurrence`, `AddTitle`, `AddTransition`, `AddLayer`, … have no expressible inverse; GP-01's "remove source seconds 6 through 8" also needs a split | Inverse-only removals were added as ordinary validated operations: `RemoveOccurrence`, `RemoveTransition`, `RemoveTitle`, `RemoveGeneratedSource`, `RemoveLayer`, `RemoveAudioTrack`, `RemoveAsset`, `UnsetParameter`, `RemoveAnalysis`. A cut is `TrimOccurrence` + `InsertOccurrence` of a second occurrence of the same asset in one batch (the batch/event is the undo unit). |
| C3 | Transition handles need `L.stream_duration`, captions/masks need stream facts, but `AssetRef(asset_id, identity, availability)` carries only a receipt **id** and the domain may not touch the store | `ProjectDocument.probes` keeps every referenced `ProbeReceipt` inline (the portable schema's "source assets and probe/provenance"); `Present.probe_receipt` is the receipt id. Stream duration is the receipt's `container_duration`. |
| C4 | `Ruff banned-api` cannot express directional package rules (it is global) | `tests/test_layering.py` parses every module's imports and enforces `client -> jobs -> {compiler, analysis, mltworker} -> {project, store, catalog} -> ledger` plus the I4 rule that `math.floor`/`math.ceil`/`bisect` arithmetic lives only in `project.timing`/`project.geometry`. |
| C5 | Sources have to be registered somewhere, yet no operation adds a media asset (`AddGeneratedSource` covers producers only); lifecycle lists `RebindAsset` | `RebindAsset(asset, probe)` binds (first time, `Absent` precondition) or relinks; it requires `Present` (verified bytes from the store) and the receipt matching the identity; replacement bytes are a new identity and any mask bound to the old bytes must be unbound first (I1). |
| C6 | Analysis evidence must enter the document for captions/ducking, but worker results are "JobFact commands" that must not write documents | `RecordAnalysis(ref)` / `RemoveAnalysis(ref_id)` operations (event kind `EffectFact`) carry transcript/mask references with coverage and qualification; producers (M3/M4) admit them through the ledger with `ToolCall` provenance. `JobFact` facts (`Ledger.admit_fact`) only move intent states under generation fencing and never touch a head. |
| C7 | `revision_id(doc, parent)` cannot distinguish identical root documents of two lineages (a portable import of an empty project) | `identity.revision_id(doc, parent, project_id)` includes the lineage id. |
| C8 | The contract fixes no portable-snapshot extension (`.gitignore` notes it) | `aidashvideo.portable-snapshot/1`, extension `.aidv.json` (`project.snapshot.SNAPSHOT_EXTENSION`); no `.gitignore` change was made. |

## 3. Contract refinements recorded for the operator (interpretations, not lowered requirements)

- `ProjectDocument` gains `probes` (C3) and `generated` (descriptor-bound generated sources have
  no bytes, hence no `SourceIdentity`); `Caption` gains `requested: SourceSpan` so requested
  versus realized boundaries are both recorded; MLT *links* are `EffectBinding`s whose service
  type is `link` (`AddLink`).
- `AnalysisRef` (transcript or mask-track reference) carries `binding`, `coverage`, `state`
  (`Produced(qualification) | Pending(requested) | Unavailable`) and `artifact`
  (`NoArtifact | Artifact(sha256)`); produced evidence naming an artifact is admitted only
  after the ledger finds it sealed and indexed (`Rejected(UnknownArtifact)` otherwise).
- `BindSubjectEffect.request` is `SubjectRequest | ExistingTrack`: a new track needs the typed
  request (concept, requested interval, the single profile id); re-binding an already recorded
  track requests nothing new, so the inverse of `UnbindEffect` invents no request.
- `AddTitle(start_frame, duration_frames)` takes raw frame counts so a negative start is the
  typed `NegativeStart` rejection rather than an unparseable batch; `ShiftTitle(delta_frames)`
  is in whole frames, and `timing.frames_nearest(seconds, fps)` records the requested seconds
  against the realized frames (half a second = 15 frames at 30/1, 15 frames = 0.5005 s at 30000/1001).
- `Ledger.open` returns a typed `OpenResult` (`Opened(ledger, Writable | ReadOnly)`, `Fenced`,
  `Denied`, `Corrupt`) and a store held by another writer past the 5 s busy timeout is
  `Rejected(StoreBusy)`.
- Event kinds are used as: `Import` (new project root and portable import), `Edit`, `Undo`
  (`RevertOperation` batches, including redo), `Rebind` (`RebindAsset`/`RemoveAsset` batches),
  `EffectFact` (`RecordAnalysis` batches), `JobFact` (intent facts), `Migration`.
- Constant-speed placement length is `ceil(duration * fps / s)` so every frame samples inside
  `[in, out)`; constant-speed caption boundaries realize at the frame start at or before them
  (the contract's inverse formula), map boundaries are the frames whose sampled instant lies in
  the span (holds and reverse passes included).
- Document schema version is 1 and the ledger schema version is `(writer 1, min_reader 1)`; no
  document migration exists yet, so `ProjectDomain.migrate_document` returns
  `Rejected(NoMigrationPath)` for any other version while `Ledger.migrate` itself is proven with
  the counter domain (section 5).

## 4. Environment and identities

Linux x86_64 sandbox (no GPU, no Metal). CPython 3.14.7 (uv-managed, `/opt/uv-python`),
uv 0.9.10, pytest 9.1.1, hypothesis 6.170.2, ruff 0.17.0, pyright 1.1.414 — the `.venv` was
absent in this session and was reproduced **once** with `uv sync --locked` from the committed
`uv.lock` (exactly the locked dev group; no lock change, no other package, no model). The
frozen FFmpeg/MLT toolchain is not installed here; the system `ffprobe` 6.1.1-3ubuntu5
(sha256 `272f6ebc634a63d9…`) is used by one store test and recorded as that identity. No
network was used by repository code; nothing was downloaded, published or pushed.
Fixtures: all probe receipts in the tests are synthetic ffprobe JSON (GP-01 shapes: 12 s
1080p30 h264+aac, 4 s video-only, 20 s wav); no media file is needed by M1.

## 5. Acceptance commands (repository root; logs in `var/evidence/m1/commands/`)

| # | Command | Exit | Observed |
| --- | --- | --- | --- |
| 1 | `uv run --offline --no-sync pytest -q -rA -p no:cacheprovider --strict-markers` | 1 | 119 passed, 4 skipped, **1 failed**: `test_toolchain_live.py::test_ffmpeg_matches_pins_with_required_capabilities` (system FFmpeg 6.1.1 lacks `filter:whisper`; pre-existing sandbox blocker, not M1) |
| 2 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m "ledger or store or timing or project"` | 0 | 92 passed |
| 3 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m "not live"` | 0 | 119 passed |
| 4 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m plan` | 0 | 10 passed (plan files untouched) |
| 5 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m boot` | 0 | 2 passed; `import aidashvideo` still loads only itself |
| 6 | `uv run --offline --no-sync ruff check .` / `ruff format --check .` | 0 / 0 | clean (76 files) |
| 7 | `uv run --offline --no-sync pyright` | 0 | 0 errors (strict, `src`, `tests`, `scripts`) |
| 8 | `uv lock --check --offline` | 0 | lock current |
| 9 | `python -I -X importtime -c "import aidashvideo" \| grep -ciE "mlt\|mlx\|torch\|whisper\|sam\|numpy\|socket"` | 1 (no match) | prints `0` |
| 10 | `scripts/verify_boot_tripwires.sh` | 0 | 4/4 mutations detected |
| 11 | `uv run --offline --no-sync python scripts/m1_evidence.py` | 0 | V02 demonstration written to `var/evidence/m1/V02/` (section 7) |
| 12 | `uv run --offline --no-sync python -m aidashvideo.ledger inspect <dir> --deep` | 0 / 1 | read-only inspection works without MLT or models; exercised by `test_inspect_command_reports_heads_lineage_and_outbox` and the evidence script |

## 6. Completion criteria (design brief §2) with the proving tests

| Criterion | Evidence |
| --- | --- |
| Offline unit/property and persistence integration checks for the domain contracts: malformed numbers/intervals, VFR boundaries, repeated occurrences, retiming, handles, geometry transforms | `test_timing.py` (18, hypothesis properties for constant-speed inverse round trips, placed-span boundaries, exact affine inverses), `test_store.py::test_malformed_probe_numbers_are_refused`, `test_project.py::test_document_round_trips_canonically_and_refuses_arbitrary_keys`, `::test_insert_trim_move_and_repeated_occurrences_stay_distinguishable`, `::test_speed_and_retime_are_catalog_bound_and_exact`, `::test_transitions_validate_neighbours_handles_and_descriptors` |
| A temporary project database/store survives close/reopen with identical admitted content and lineage | `test_ledger.py::test_new_store_survives_close_and_reopen_with_identical_content`, `test_project.py::test_sequence_edits_persist_and_reopen_without_loss` (head record, document bytes, lineage and events compare equal after reopen; `verify(deep=True)` ok) |
| Exact replay applies once; conflicting replay, stale client input, denied authority and two concurrent writers preserve the correct head and outbox facts | `test_exact_replay_applies_once_and_returns_the_original_result`, `test_conflicting_replay_changes_nothing`, `test_stale_base_revision_is_a_revision_conflict`, `test_stale_object_precondition_is_rejected`, `test_actor_and_grant_authority_are_typed_rejections`, `test_two_concurrent_writers_only_one_expected_head_update_wins` (two threads, two connections, barrier after sealing: exactly one `Applied`, one `RevisionConflict`, one intent and one outbox row) |
| Inject failures before/after blob seal and transaction commit; prior or new revision recoverable without partial patches or duplicate intents | `test_fault_before_commit_leaves_prior_head_and_replay_applies_once[before_seal/after_seal/before_commit]`, `test_fault_after_commit_is_recoverable_without_duplicate_intents`, `test_process_killed_at_persistence_points_recovers_on_reopen[after_seal/before_commit/after_commit]` (a child process `os._exit(137)` at the named point; reopen shows the prior or the admitted head, orphan blobs are readable but have no authority, replay applies once or returns `AlreadyApplied`) |
| Sequence edits and descriptor-bound operations serialize/reopen without loss; unsupported descriptors cannot be made renderable by a copied file | `test_every_operation_has_a_wire_form_and_parses_back`, `test_descriptor_bound_operations_and_their_inverses` (every inverse restores the prior bytes), `test_portable_snapshot_exports_validates_and_imports_as_new_lineage` (import under a catalog lacking the service is readable but `Blocked(CatalogMismatch)`, and `RecompileWithNewCatalog` is refused - no silent fallback) |
| Cut, blur binding, independent title edit, selective cut inverse, half-second title shift; independent objects survive; ambiguous rebind or negative start returns a precise conflict/choice | `test_selective_undo_of_a_cut_keeps_the_blur_and_exposes_missing_coverage`, `test_undo_rebinds_a_dependent_effect_only_when_proven`, `test_undo_conflicts_on_later_changes_and_dangling_transitions`, `test_titles_are_exact_and_negative_starts_fail_atomically`; inspectable output in `var/evidence/m1/V02/` (section 7) |
| Repeated source passages, hold/reverse where declared, audio offsets and source/sequence mapping without float drift | `test_hold_map_repeats_an_instant_without_dividing_by_zero`, `test_reverse_map_is_declared_and_exact`, `test_variable_map_repeats_a_source_passage_and_reports_each_pass`, `test_vfr_table_maps_sequence_frames_to_actual_decoded_frames`, `test_audio_samples_and_stream_offsets_have_no_drift` (18000 NTSC frames -> 28 828 800 samples exactly; stream offsets 7.5 s / 8.5 s aligned once) |
| Changed/missing assets and incompatible schemas retain history, refuse execution eligibility and support relink/migration/read-only behaviour | `test_store.py::test_availability_is_present_missing_or_changed_by_bytes_not_path`, `test_project.py::test_rebind_asset_requires_verified_bytes_and_explicit_binding` (observed `Changed` -> `Blocked(AssetNotVerified)` with history intact; relink needs `Present`), `::test_relink_after_import_needs_verified_bytes_through_the_store` (content-hash match through the store, explicit `RebindAsset`, never a path), `test_ledger.py::test_newer_writer_is_readable_but_not_writable`, `::test_min_reader_above_this_code_is_fenced`, `::test_migration_creates_new_revisions_and_keeps_old_payloads`, `test_project.py::test_migration_path_is_explicit_and_history_survives` |
| Source files remain byte-identical; portable reimport creates a validated lineage; repeated admission does not duplicate effects | `test_store.py::test_import_records_identity_receipt_and_leaves_the_original_untouched` (bytes and mtime), `::test_job_snapshot_is_a_verified_clone_and_refuses_changed_sources`, `test_ledger.py::test_import_creates_a_new_lineage_and_never_replaces_the_canonical_head`, `test_project.py::test_sequence_edits_persist_and_reopen_without_loss` (replayed bind batch -> `AlreadyApplied`, one effect, one intent) |
| All tests use real target-local persistence; inspection needs no AiDashOS, model or native engine | every ledger/store/project test opens a real `project.sqlite` + `cas/` in a temporary directory; `python -m aidashvideo.ledger inspect` runs with the inspect-only domain |

## 7. Inspectable evidence: V02 demonstration (`var/evidence/m1/V02/`, git-ignored)

`scripts/m1_evidence.py` builds a real store and writes, in order: `01-before-undo.document.json`
(interview placed, cut into `A` [0,6) and `A2` [8,12), broll appended, title at frame 30,
blur bound to `A` with a `Pending` mask track and one `Mask` intent), `01a-undo-blocked-by-overlap.json`
(while broll sits at 300-420, reverting the cut would restore `A` to 360 frames on top of it:
`Rejected(Overlap)`, nothing mutated), `02-undo-plan.json` (after moving broll to 360: the plan
is exactly `RemoveOccurrence(A2)`, `TrimOccurrence(A, [0,12))`), `03-after-undo.document.json`
(`A` restored to 360 frames, `A2` gone, broll and title untouched, the blur binding intact),
`04-blur-dependency-after-undo.json` (`PendingCoverage`: missing [0,12), requested [0,6) - the
newly exposed 6-12 s was never requested and is reported, not guessed), the half-second shift
(requested -1/2 s = -15 frames exactly, title at [15,75)), `05-negative-start-rejection.json`
(`NegativeStart`: "shifting by -16 frames would start at frame -1"), the redo (a new `Undo`
event re-applying the cut), `06-ambiguous-rebind-conflict.json` (a second blur with a different
radius on `A2`: `UndoConflict` naming both effects and the choices `DropDependent`/`RebindTo`;
the revert without a choice is `Rejected(UndoConflict)`, with `DropDependent` it applies),
`08-events.json`, `10-ledger-inspect.json` (integrity ok, no CAS orphans).

## 8. Design notes for the reviewer (illegal executable states are prevented by construction)

- Every closed variant validates in `__post_init__`: a `SourceSpan` with `in >= out`, a float in
  a span, a `bool` where an integer quantity is expected, a NaN `Float`, a bidi control in
  `LiteralText`, a `TimeMap` whose frames do not strictly increase or whose mode is not what its
  points declare, an `AssetRef` whose availability hash differs from its identity - none can
  exist. JSON parsers require exact key sets, so arbitrary dictionaries never enter a document.
- Only `aidashvideo.ledger` opens `project.sqlite` for writing; inspection opens `mode=ro`;
  a newer writer's store opens read-only; a direct `UPDATE heads` or an edited CAS blob is
  detected at open as `Corrupt` (foreign writes are not admitted heads).
- A batch is applied as a whole: every operation (including the concrete expansion of a
  `RevertOperation`) is applied in order and the complete document is validated before the
  ledger seals anything; any failure is one typed `Rejected` with the offending object refs.
- Coverage is never invented: `BindSubjectEffect` records `Pending(requested)` and an intent;
  `effect_dependency` derives `Ready | PendingCoverage(missing) | UnavailableDependency` from
  the produced coverage spans through `timing.coverage_missing`; fixture tests that need
  coverage use explicit `Unqualified` refs and cannot certify a provider.
- Undo rebinding is proven only for a unique same-source candidate whose source range overlaps
  the effect's coverage and that carries no conflicting same-service effect; otherwise the
  exact dependents and choices are returned.

## 9. Failures, cleanup and remaining blockers

- `tests/test_toolchain_live.py::test_ffmpeg_matches_pins_with_required_capabilities` fails in
  this sandbox session (system FFmpeg 6.1.1, frozen 9.0.2 not installed under `.deps/frozen`):
  a `live` marker blocker outside M1; `scripts/build_frozen_toolchain.sh` (operator archives
  required) restores it. The other live tests skip with their exact blocker.
- Sandbox observations never count as target-host evidence; the readiness rows in
  [../plan/runtime-profile.json](../plan/runtime-profile.json) are unchanged.
- Added files only, plus three edits: `pyproject.toml` (the four M1 pytest markers named in
  [../plan/commands.md](../plan/commands.md) and `extraPaths = ["tests"]` for pyright),
  `README.md` (status/layout lines), this report. Plan and M0 evidence files are untouched.
- Temporary stores from tests live in pytest's temp directories; the evidence script uses a
  `tempfile` directory and keeps only JSON under `var/evidence/m1/`. No original was modified.
- Open for the operator: accept or veto the refinements in sections 2-3 (C2/C6 add operation
  names to the closed set); the M1 handover to M2 is the `project.session` API
  (`Project.admit/head/revision/plan_undo/export_snapshot/import_snapshot`), `Ledger.pending_outbox`
  / `claim_outbox` / `admit_fact` for the supervisor, and `catalog.descriptors.DescriptorCatalog`
  for the M2a freeze.
