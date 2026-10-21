# AiDashVideo contracts (frozen at Milestone 0, revised 2026-10-21 for the single SAM 3.1 MLX profile)

This file is normative. [implementation-plan.md](implementation-plan.md) says who builds what
and when; [verification-matrix.md](verification-matrix.md) says how each rule is proven. Scope
and acceptance come from the operator's briefs in [../design/](../design/README.md); the
acceptance contract is [../design/milestone-6.md](../design/milestone-6.md). Module names,
owners and the head-write rule below are repeated verbatim in the plan and the matrix and
checked by `tests/test_plan_integrity.py`.

## 1. Ownership

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

Sole owners of cross-cutting semantics:

| Semantics | Sole owner | Everyone else |
| --- | --- | --- |
| source/sequence/audio time mapping, retiming maps | `aidashvideo.project.timing` | consumes `SequenceSpan`, `SourceSpan`, `SampleSpan`, `TimeMap` only |
| source/sequence pixel geometry, orientation, mask geometry | `aidashvideo.project.geometry` | consumes `Affine2D`, `OrientedGrid` only |
| revision identity (`revision_id`) and graph identity (`graph_id`) | `aidashvideo.project.identity` / `aidashvideo.compiler.identity` | never recompute |
| supplier readiness words | `aidashvideo.catalog.status.Readiness` | reuse the enum |
| grants and caller identity | `aidashvideo.ledger.grants` | receive a `Grant` value, never construct one |
| durable per-object mask artifacts and their semantic keys | `aidashvideo.analysis.masks` | consume `MaskSpan`/`MaskRef` only |

## 2. Closed variants

All variants are frozen dataclasses created only through validated constructors
(`Type.make(...)` raising `ContractError`); invalid combinations cannot be represented.
No field is `Optional` to stand in for "absent"; absence is its own variant. No
`dict[str, object]` carries domain state; parameter values are typed `ParamValue` variants.
Implemented in the owning milestone named in [implementation-plan.md](implementation-plan.md).
The variants required verbatim by [../design/milestone-0.md](../design/milestone-0.md) are
listed first; supporting types follow.

```text
# ---- required by the design brief -------------------------------------------------------
AssetAvailability = Present(verified_hash, scoped_locator, probe_receipt)
                  | Missing(expected_hash, relink_request)
                  | Changed(expected_hash, observed_hash)

EditProposal      = Applicable(base_revision, typed_patch, affected_objects)
                  | NeedsChoice(candidates, question)
                  | Unsupported(requested_capability, reason)

ApplyResult       = Applied(revision, admitted_event)
                  | AlreadyApplied(original_result)
                  | RevisionConflict(current_revision)
                  | Rejected(contract_reason)

Transcript        = SegmentTimed(source_binding, segments, provenance)
                  | WordAligned(source_binding, segments, words, qualification)
                  | NoSpeech(source_binding, coverage_receipt)

MaskSpan          = Tracked(source_interval, artifact, coordinate_contract, qualification)
                  | NeedsCorrection(source_interval, reason, candidate_refs)
                  | AbsentSubject(source_interval, validated_observation)

MaskRequest       = SAM31MLXRequest(source_binding, source_interval, selection, correction_revision, qualified_profile)

MaskSelection     = VisualSelection(frame_binding, validated_points_or_box)
                  | TextSelection(frame_binding, concept, instance_policy)

InstancePolicy    = AllMatchingInstances
                  | SelectedInstances(candidate_binding, nonempty_subject_ids)

SubjectAssets     = VerifiedLocal(checkpoint_snapshot, tokenizer_snapshot, runtime_manifest)
                  | Missing(required_artifacts)
                  | Invalid(artifact_identity, contract_reason)

PreviewState      = Pending(revision, range, dependency_jobs)
                  | Current(revision, range, preview_binding, dependency_manifest)
                  | Stale(rendered_revision, requested_revision, artifact)
                  | Unavailable(revision, range, typed_reason)

PreviewBinding    = EncodedRange(artifact, output_profile)
                  | FrameSession(session_id, graph_hash, worker_generation, output_profile)

MLTService        = Callable(build_id, descriptor, qualification)
                  | Unavailable(service_id, reason, required_action)

MLTParameter      = Static(value_type, units, constraints)
                  | Animatable(value_type, units, constraints, time_domain, interpolations)

Capability        = Qualified(provider_identity, evidence, resource_profile)
                  | Unavailable(reason, required_action)

RenderOutcome     = VerifiedOutput(job_identity, artifact, validation_receipt)
                  | Failed(typed_cause, retained_diagnostics)
                  | Cancelled(fence_receipt, cleanup_receipt)
                  | NeedsReconciliation(last_observation, effect_identity)

# ---- identity & media (owner: aidashvideo.store, M1) --------------------------------------
SourceIdentity    = SourceIdentity(sha256, size_bytes, probe_receipt_id)         # content identity
ScopedLocator     = ScopedLocator(grant_id, path_within_grant)                   # never a bare path
RelinkRequest     = RelinkRequest(asset_id, expected_hash, last_known_locator)
ProbeReceipt      = ProbeReceipt(probe_tool_identity, streams: tuple[StreamProbe, ...],
                                 container_duration: Rational, sha256_of_json)
StreamProbe       = VideoStream(index, codec, width, height, sar: Rational, fps: Rational,
                                timebase: Rational, start_time: Rational, rotation: Rotation,
                                color: ColorTags, vfr: VfrTable | ConstantRate, has_bframes: bool)
                  | AudioStream(index, codec, sample_rate, channels, layout, timebase, start_time)
VfrTable          = VfrTable(pts: tuple[Rational, ...])       # actual decoded presentation timestamps
ColorTags         = Sdr709 | Hdr(transfer: Pq | Hlg, primaries) | Untagged
Rotation          = R0 | R90 | R180 | R270
SourceBinding     = SourceBinding(asset_sha256, stream_index, probe_receipt_id)   # content + stream, never a path

# ---- project domain (owner: aidashvideo.project, M1) --------------------------------------
Revision          = Revision(revision_id, parent: Root | Parent(revision_id), document: ProjectDocument,
                             admitted_event_id, schema_version)
ProjectDocument   = ProjectDocument(profile: OutputProfile, assets: tuple[AssetRef, ...],
                                    sequence: Sequence, effects: tuple[EffectBinding, ...],
                                    analysis_refs: tuple[TranscriptRef | MaskRef, ...])
OutputProfile     = OutputProfile(width=1920, height=1080, fps: Rational=30/1, color: Sdr709,
                                  audio: AudioProfile, container: Mp4H264Aac)
AudioProfile      = AudioProfile(sample_rate=48000, layout=Stereo,
                                 delivery: Loudness(target_lufs, true_peak_dbtp) | Unconstrained)
AssetRef          = AssetRef(asset_id, identity: SourceIdentity, availability: AssetAvailability)
Sequence          = Sequence(video_layers: tuple[VideoLayer, ...], audio_tracks: tuple[AudioTrack, ...],
                             titles: tuple[Title, ...], captions: tuple[Caption, ...])
VideoLayer        = VideoLayer(layer_id, occurrences: tuple[ClipOccurrence, ...], transitions: tuple[Transition, ...])
AudioTrack        = AudioTrack(track_id, occurrences: tuple[ClipOccurrence, ...], mix: AudioMix)
ClipOccurrence    = ClipOccurrence(occurrence_id, asset_id, stream_index, source: SourceSpan,
                                   place: SequenceSpan, timing: Speed | TimeMap, transform: ClipTransform)
Speed             = Normal | Constant(ratio: Rational > 0)
TimeMap           = TimeMap(points: tuple[(SequenceFrame, SourceTime), ...], interpolation: Hold | Linear,
                            mode: Reverse | Hold | Variable)       # catalog-supported modes only
Transition        = Transition(transition_id, left_occurrence, right_occurrence, kind: ServiceRef,
                               duration_frames, params)
Caption           = Caption(caption_id, text: LiteralText, place: SequenceSpan, language,
                            style: CaptionStyleRef, lines: tuple[LiteralText, ...], evidence: TranscriptRef)
Title             = Title(title_id, text: LiteralText, place: SequenceSpan, style: TitleStyleRef)
EffectBinding     = EffectBinding(effect_id, target: OccurrenceTarget | LayerTarget, service: ServiceRef,
                                  params: tuple[ParamAssignment, ...], mask: NoMask | MaskRef(track_version_id))
ParamAssignment   = ParamAssignment(param_id, value: Static(ParamValue) | Animated(keyframes: tuple[Keyframe, ...], interpolation))
ParamValue        = Int(v) | Float(v) | Bool(v) | Enum(v) | Color(rgba) | Rect(x, y, w, h, opacity) | Text(LiteralText)
OperationBatch    = OperationBatch(actor: ActorId, project_id, base_revision, replay_key, payload_sha256,
                                   preconditions: tuple[ObjectPrecondition, ...], operations: tuple[Operation, ...],
                                   provenance: UserWording(text) | ToolCall(tool, arguments_sha256))
ObjectPrecondition= Exists(object_ref, version) | Absent(object_ref)
Operation         = see section 6 (closed set)
UndoResult        = Undone(revision) | UndoConflict(dependents: tuple[ObjectRef, ...], choices)
ImportResult      = NewLineage(root_revision) | InvalidSnapshot(contract_reason) | UnsupportedSchema(writer_version, min_reader)

# ---- analysis evidence (owner: aidashvideo.analysis, M3/M4) -------------------------------
SpeechOutcome     = Produced(transcript: Transcript)
                  | RecognitionFailed(reason, tool_exit: int, diagnostics_ref)
                  | Unavailable(capability: Capability.Unavailable)
Segment           = Segment(source_interval: SourceSpan, text: LiteralText, confidence: Observed(v) | NotReported)
Word              = Word(source_interval: SourceSpan, text: LiteralText, boundary_error_ms: Qualified(v))
PhraseSelection   = Selected(span, occurrence_id) | Ambiguous(candidates: tuple[(span, occurrence_id, context), ...]) | NotFound
TranscriptCorrection = CorrectedText(raw_ref, text_edits) | CorrectedTiming(raw_ref, timing_edits)   # raw result preserved
MaskTrack         = MaskTrack(track_version_id, subject_id, spans: tuple[MaskSpan, ...], semantic_key: MaskKey,
                              polarity: SubjectIsOne, grid: OrientedGrid, provenance)
MaskKey           = MaskKey(asset_sha256, stream_index, pts_coverage, oriented_grid, selection_hash,
                            correction_revision, checkpoint_revision, tokenizer_revision, runtime_revision,
                            preprocessing, resolution, execution_dtype, context_policy)
SubjectCandidates = Candidates(frame_binding, boxes_scores_ids) | NoCandidates(frame_binding)
FrameBinding      = FrameBinding(source_binding, pts: Rational, oriented_grid: OrientedGrid)

# ---- jobs, preview, export (owner: aidashvideo.jobs / aidashvideo.mltworker, M2) ---------
Intent            = JobIntent(intent_id, kind: Preview | Export | Probe | Proxy | Speech | Mask, revision_id,
                              graph_id, inputs: tuple[InputBinding, ...], generation: int, grant: Grant,
                              limits: ResourceLimits, deadline)
                  | EffectIntent(intent_id, effect_id, revision_id, dependencies: tuple[ArtifactRef, ...], generation)
JobState          = Queued | Running(worker_id, generation) | Cancelled(by) | Failed(reason, receipt)
                  | Completed(receipt) | Reconciling(last_observation)
ExportRequest     = ExportRequest(revision_id, profile, destination: ScopedLocator, grant: ExportGrant)

# ---- grants and identity (owner: aidashvideo.ledger.grants, M1) ---------------------------
ActorId           = LocalUser(os_user, client_session_id)                         # never from model text
Grant             = ProjectGrant(grant_id, project_dir, actor)                     # edits + previews
                  | ExportGrant(grant_id, revision_id, destination: ScopedLocator, actor) # one new file
                  | OverwriteGrant(grant_id, destination: ScopedLocator, expected_sha256, actor)
                  | AcquisitionGrant(grant_id, source_url, sha256, bytes, destination, actor)
Readiness         = Verified | Missing | Conflicting                               # aidashvideo.catalog.status
```

`Rational` is `fractions.Fraction`. `LiteralText` is text that is always passed as data
(never through a shell, never interpolated into MLT XML attributes without escaping) and is
limited to Unicode categories L, M, N, P, S, Zs plus newline; bidi control characters are
refused. `ServiceRef` names a descriptor by `(service_id, catalog_digest)`.

## 3. Invariants (I1-I12) and their enforcement points

| Invariant | Enforced by | Mechanism |
| --- | --- | --- |
| I1 originals never modified | `aidashvideo.store` | sources opened read-only through `ScopedLocator`; jobs read hash-verified clones (section 5); `AssetAvailability.Changed` on mismatch; rebind is a new `AssetRef` in a new revision |
| I2 single admission boundary | `aidashvideo.ledger` | the only module that opens the SQLite connection in write mode; `mltworker`, `client` and the tool server receive read-only snapshots |
| I3 exact replay once, conflicts nothing | `aidashvideo.ledger.idempotency` | `idempotency(replay_key PRIMARY KEY, payload_sha256, result)` checked inside the head transaction; compare-and-swap on `heads` |
| I4 single timing/geometry owners | `aidashvideo.project.timing`, `aidashvideo.project.geometry` | other modules import only value types; Ruff banned-import rule in M1 |
| I5 explicit uncertainty | `aidashvideo.analysis` | `Transcript`/`MaskSpan` variants; `WordAligned` needs a `qualification`; `Tracked` needs current-frame coverage; nothing else is success |
| I6 bound preview/export | `aidashvideo.compiler.identity`, `aidashvideo.jobs` | `graph_id = sha256(canonical graph JSON + catalog digest + input hashes)`; `PreviewState` and `PreviewBinding` carry revision, graph hash, worker generation |
| I7 selective undo | `aidashvideo.project.undo` | dependency graph over `ObjectRef`; `UndoConflict` when a dependent cannot be rebound |
| I8 no undeclared egress/spend | `aidashvideo.catalog.offline`, `aidashvideo.ledger.grants` | providers start with `provider_environment()` (`HF_HUB_OFFLINE=1` before import); downloads need `AcquisitionGrant`; exports need `ExportGrant`; overwrites need `OverwriteGrant` |
| I9 cancellation/recovery | `aidashvideo.jobs` | owned process table, `generation` fencing, `Reconciling` state, reconcile-on-start |
| I10 optional providers isolated | `aidashvideo.catalog`, `aidashvideo.analysis` | lazy imports; `tests/test_boot_isolation.py`; doctor and inspection run with nothing installed |
| I11 complete MLT package callable | `aidashvideo.catalog.descriptors`, `aidashvideo.client.chat.tools` | every `MLTService.Callable` has a tool; unknown params are `Rejected` before compile |
| I12 MLT objects derived | `aidashvideo.compiler` | XML is regenerated from `Revision`; the worker never persists XML or native pointers as authority |

## 4. Timing and geometry algebra (owner: `aidashvideo.project.timing`, `aidashvideo.project.geometry`)

Time values are exact `Fraction`s; no float enters a span. All intervals are finite and
half-open `[start, end)`; three domains exist and are never mixed implicitly: **source**
(seconds in a stream's own timebase after its `start_time` is subtracted once at probe time),
**sequence** (frame indices at `OutputProfile.fps`) and **audio** (sample indices at 48 000 Hz).

- `SourceSpan = [in, out)` in `SourceTime`; `SequenceSpan = [start, end)` in `SequenceFrame`;
  `SampleSpan = [s0, s1)`. The domain interval `[0, 30)` contains 30 frames, never 31.
- Constant positive speed `s` (`Speed.Normal` is `s = 1`):
  `source_time = source_in + s * (timeline_time - clip_start)` over the valid range, with
  `timeline_time = frame / fps`; the inverse maps a source instant to the frame whose start is
  at or before it: `frame = clip_start_frame + floor((source_time - source_in) * fps / s)`.
- `TimeMap` (reverse, hold, variable; only modes the catalog declares): a finite ordered list
  of `(SequenceFrame, SourceTime)` points with declared interpolation; `Hold` repeats the last
  source instant and therefore never divides by a zero sequence-length; one source interval may
  appear in several occurrences or several times inside one map.
- MLT's inclusive `out` is derived only in the compiler: `mlt_out = end - 1`; nothing else
  performs that conversion.
- Audio: `sample(n) = floor(n * 48000 / fps)` from a `SequenceFrame`; per-stream audio offsets
  and sample rates live in `AudioStream` and are applied once by `timing`.
- Captions and transcripts are `SourceSpan`s of the occurrence's asset; placement uses the same
  map; a span outside `[source.in, source.out)` is `OutsidePlacedRange` and is never clamped.
  Requested versus realizable boundaries are both recorded (a segment boundary that falls
  between frames realizes at the frame start).
- Transition handles: a transition of `d` frames between occurrences `L` and `R` requires
  `L.source.out + d/fps <= L.stream_duration` and `R.source.in - d/fps >= 0`; otherwise
  `InsufficientHandles`. Negative title starts and unsupported speed/profile changes fail the
  whole batch atomically.
- Maximum admitted error: caption and mask placement within one output frame on exact synthetic
  fixtures (V03); this is a property of `floor` on exact rationals, tested in M1.
- Geometry: `SourcePixel` is the decoded, *unrotated* buffer with its `sar`. `OrientedGrid` is
  the rotation-applied grid with square pixels. `geometry.display_affine(stream, profile)` =
  `rotation ∘ sar_normalize ∘ fit(Contain)` producing an `Affine2D` into `SequencePixel`. Masks
  are stored on the `OrientedGrid` of the source (`MaskKey.oriented_grid`), so a mask never
  depends on the sequence profile. Visual selections arrive in `SequencePixel` (UI) or
  `OrientedGrid` (tool) and are validated against the frame bounds; a point/box outside the
  frame is `RejectedSelection`.

Visual order (frozen; the compiler lowers in exactly this order):

1. orientation/normalization: rotation, SAR, color tags into the Rec.709 limited-range
   working space;
2. source subject effect (mask composite) in `OrientedGrid` space;
3. clip transform/color: crop, scale, position, SDR adjustments;
4. sequence composition: layers (bottom to top), transitions;
5. titles and captions;
6. output conversion: profile fit, yuv420p, encode.

Alpha, chroma and color: masks are single-channel `[0, 1]` with `SubjectIsOne` polarity and
are stored straight (non-premultiplied); feathering is a declared radius in oriented source
pixels applied before compositing; premultiplication happens only inside MLT compositing;
masks are resampled to the luma grid before any chroma-subsampled composite; HDR inputs are
refused unless a qualified tone-mapping choice is admitted (V04). Stable source snapshot:
every job reads from a hash-verified copy-on-write clone owned by the job (section 5).

## 5. Persistence (owner: `aidashvideo.ledger`, `aidashvideo.store`)

Target-local durable storage lives inside the granted project directory:

```text
<project_dir>/
  project.sqlite          # WAL, foreign_keys=ON, synchronous=FULL; the only authority
  cas/sha256/ab/abcdef... # immutable content-addressed payloads and artifacts (revisions, probes,
                          # proxies, masks, transcripts, receipts); never edited in place
  snapshots/<job_id>/     # hash-verified copy-on-write clones of sources for one job (APFS clonefile,
                          # else reflink, else verified copy); deleted with the job
  scratch/                # worker scratch; deletable at any time; never referenced by a revision
```

Tables (all writes happen through `ledger.admit`):

| Table | Key | Purpose |
| --- | --- | --- |
| `heads` | `project_id` | `head_revision_id`; updated with `WHERE head_revision_id = :expected` (compare-and-swap) |
| `revisions` | `revision_id = sha256(canonical JSON)` | immutable documents (payload bytes in `cas/`), `parent_id`, `admitted_event_id`, `schema_version` |
| `operation_events` | `seq` (monotonic) | append-only; kind ∈ {Edit, Undo, Import, Rebind, JobFact, EffectFact, Migration}; stores the batch, its inverse and provenance |
| `idempotency` | `replay_key` | `payload_sha256`, `result` (serialized `ApplyResult`) |
| `intents` | `intent_id` | job/effect intents with `generation`, `state` (closed set), limits, deadline |
| `outbox` | `seq` | one row per intent transition to dispatch; rows move to `outbox_done` when dispatched |
| `artifacts` | `sha256` | CAS index: kind, size, producer tool identity, dependency identities, semantic key |
| `mask_tracks` | `track_version_id` | durable per-object mask track versions and their `MaskKey` (artifact bytes in `cas/`) |
| `schema_version` | single row | `(writer_version, min_reader_version)`; unsupported writers are fenced (V30) |

Persistence ordering for one admission (single transaction, `BEGIN IMMEDIATE`):

1. **Seal payload bytes first.** Artifacts referenced by the batch, and the new revision's
   canonical document, are written to `cas/` (write temp, fsync, rename) and indexed before the
   transaction; a batch referencing an unknown hash is `Rejected` before the transaction.
   A database transaction does not make these filesystem writes atomic; orphan blobs and an
   interrupted but readable serialization have no admission authority.
2. Validate the complete resulting project (every constructor, every precondition) before any
   write. Idempotency lookup: same `replay_key` + same `payload_sha256` returns
   `AlreadyApplied(original_result)` (no writes); same key + different payload is `Rejected`
   with no writes.
3. `INSERT operation_events`; `INSERT revisions`; `UPDATE heads ... WHERE head_revision_id =
   expected` (row count must be 1, else `ROLLBACK` and `RevisionConflict`); `INSERT idempotency`;
   `INSERT intents` and `outbox`. `COMMIT`.
4. Only after commit does `aidashvideo.jobs` read `outbox`, dispatch to workers and move rows to
   `outbox_done` in its own transaction. Worker results return as `JobFact` commands through
   steps 1-3 with the intent's `generation`; a stale generation is `Rejected`.

Crash at each point (V12): before 3 leaves orphan CAS artifacts without authority; during 3 the
transaction is not visible; after 3 but before 4 the outbox replays on start. Orphan staging
and snapshot directories are deleted by `jobs.reconcile()` on start, never adopted. Portable
import validates the snapshot and admits a **new lineage** (`ImportResult.NewLineage`); it never
replaces the canonical head.

## 6. Operation semantics

`Operation` is closed. Required semantic operations (M1):
`InsertOccurrence | TrimOccurrence | MoveOccurrence | SetConstantSpeed | RetimeOccurrence |
AddTransition | SetAudioMix | AddTitle | ShiftTitle | SetCaptions | BindSubjectEffect |
RevertOperation`. Descriptor-bound operations (validated against `MLTService`/`MLTParameter`):
`AddGeneratedSource | AddLayer | AddAudioTrack | AddLink | BindEffect | SetParameter |
SetKeyframes | SetTransitionSettings | SetOutputProfile | UnbindEffect`. Lifecycle operations:
`RebindAsset | ImportSnapshot | Migrate | RecompileWithNewCatalog`.

Each operation names its target by `ObjectRef` (stable ids, never indices). Source assets have
`asset_id`s; placements have `occurrence_id`s; the same asset may occur many times and each
occurrence stays distinguishable through moves and cuts. Every batch is validated as a whole
against the catalog descriptors before compile and records `affected_objects`. Every operation
has an inverse computed at admission and stored in the event; `RevertOperation(event_seq)`
applies that inverse at the current head as a **new** revision, detects dependents through the
`ObjectRef` graph and returns `UndoConflict(dependents, choices)` instead of guessing; undoing a
cut under a bound subject effect either proves the mask rebinding (same `MaskKey` coverage) or
returns the conflict, and newly exposed source intervals become missing coverage (`Pending`).
Redo is a new validated batch. A batch is applied atomically: any operation failing validation
rejects the whole batch with no mutation. `BindSubjectEffect` with provider assets `Missing`
is admitted as a revision whose effect dependency is `Pending`, never as qualified coverage.

Chat turns produce an `EditProposal`. `Applicable` carries `base_revision`; admission returns
`RevisionConflict` if the displayed revision moved (V09). `NeedsChoice` and `Unsupported`
never mutate. User wording is stored as provenance; the structured batch is authoritative.

## 7. Wire schemas

All JSON is canonical (sorted keys, UTF-8, no NaN) before hashing.

```json
{"$id": "aidashvideo.revision/1", "type": "object", "required": ["revision_id", "parent", "document", "admitted_event_id", "schema_version"],
 "properties": {"revision_id": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "parent": {"oneOf": [{"const": "root"}, {"type": "string", "pattern": "^[0-9a-f]{64}$"}]},
                "document": {"$ref": "aidashvideo.project-document/1"}, "admitted_event_id": {"type": "integer"},
                "schema_version": {"type": "integer"}}}
```

```json
{"$id": "aidashvideo.operation-batch/1", "type": "object",
 "required": ["actor", "project_id", "base_revision", "replay_key", "payload_sha256", "preconditions", "operations", "provenance"],
 "properties": {"actor": {"properties": {"os_user": {}, "client_session_id": {}}},
                "base_revision": {"pattern": "^[0-9a-f]{64}$"}, "replay_key": {"type": "string", "minLength": 16},
                "payload_sha256": {"pattern": "^[0-9a-f]{64}$"},
                "preconditions": {"type": "array", "items": {"oneOf": [{"properties": {"kind": {"const": "Exists"}, "object_ref": {}, "version": {}}}, {"properties": {"kind": {"const": "Absent"}, "object_ref": {}}}]}},
                "operations": {"type": "array", "minItems": 1, "items": {"properties": {"op": {"type": "string"}}}},
                "provenance": {"oneOf": [{"properties": {"kind": {"const": "UserWording"}, "text": {}}}, {"properties": {"kind": {"const": "ToolCall"}, "tool": {}, "arguments_sha256": {}}}]}}}
```

```json
{"$id": "aidashvideo.worker-frame/1", "description": "JSON lines, supervisor <-> mltworker over a pipe",
 "oneOf": [
  {"properties": {"type": {"const": "preview.request"}, "revision_id": {}, "graph_id": {}, "generation": {"type": "integer"}, "xml_sha256": {}, "frame": {"type": "integer"}}},
  {"properties": {"type": {"const": "preview.frame"}, "revision_id": {}, "graph_id": {}, "generation": {"type": "integer"}, "frame": {"type": "integer"}, "image_sha256": {}}},
  {"properties": {"type": {"const": "transport"}, "session_id": {}, "generation": {"type": "integer"}, "command": {"enum": ["play", "pause", "seek", "rate"]}, "frame": {"type": "integer"}, "rate": {"type": "number"}}},
  {"properties": {"type": {"const": "graph.switch"}, "session_id": {}, "generation": {"type": "integer"}, "xml_sha256": {}, "at_frame": {"type": "integer"}}},
  {"properties": {"type": {"const": "export.request"}, "intent_id": {}, "generation": {"type": "integer"}, "xml_sha256": {}, "destination_tmp": {}}},
  {"properties": {"type": {"const": "export.progress"}, "intent_id": {}, "generation": {"type": "integer"}, "frame": {"type": "integer"}}},
  {"properties": {"type": {"const": "export.done"}, "intent_id": {}, "generation": {"type": "integer"}, "output_sha256": {}}},
  {"properties": {"type": {"const": "cancel"}, "intent_id": {}, "generation": {"type": "integer"}}},
  {"properties": {"type": {"const": "fault"}, "generation": {"type": "integer"}, "stage": {}, "detail": {}}}]}
```

```json
{"$id": "aidashvideo.service-descriptor/1", "type": "object",
 "required": ["service_id", "service_type", "module", "title", "build_id", "catalog_digest", "parameters", "resources", "pixel_constraints", "audio_constraints", "interactions", "dependencies", "qualification"],
 "properties": {"service_id": {"type": "string"}, "service_type": {"enum": ["producer", "filter", "transition", "link", "consumer"]},
                "module": {"type": "string"}, "title": {"type": "string"}, "build_id": {"type": "string"}, "catalog_digest": {"pattern": "^[0-9a-f]{64}$"},
                "parameters": {"type": "array", "items": {"type": "object",
                   "required": ["param_id", "kind", "value_type", "units", "default", "mutable"],
                   "properties": {"param_id": {"type": "string"}, "kind": {"enum": ["Static", "Animatable"]},
                                  "value_type": {"enum": ["integer", "float", "boolean", "string", "color", "rect", "enum", "geometry"]},
                                  "units": {"type": "string"}, "minimum": {"type": "number"}, "maximum": {"type": "number"},
                                  "values": {"type": "array", "items": {"type": "string"}}, "default": {}, "mutable": {"type": "boolean"},
                                  "time_domain": {"enum": ["sequence_frame", "source_time", "normalized"]},
                                  "interpolations": {"type": "array", "items": {"enum": ["discrete", "linear", "smooth"]}},
                                  "metadata_source": {"enum": ["upstream_yaml", "version_bound_descriptor"]}}}},
                "resources": {"type": "array", "items": {"properties": {"param_id": {}, "kind": {"enum": ["media", "font", "plugin", "lut"]}, "rule": {"const": "scoped_locator_only"}}}},
                "pixel_constraints": {}, "audio_constraints": {}, "interactions": {"type": "array"}, "dependencies": {"type": "array"},
                "qualification": {"oneOf": [{"properties": {"state": {"const": "Qualified"}, "evidence": {}}}, {"properties": {"state": {"const": "Unavailable"}, "reason": {}, "required_action": {}}}]}}}
```

```json
{"$id": "aidashvideo.render-outcome/1", "oneOf": [
  {"properties": {"kind": {"const": "VerifiedOutput"}, "job_identity": {"properties": {"intent_id": {}, "revision_id": {}, "graph_id": {}, "generation": {}, "profile": {}, "tool_identities": {}, "input_hashes": {}}},
                  "artifact": {"properties": {"destination": {}, "output_sha256": {}}},
                  "validation_receipt": {"properties": {"decode": {"properties": {"tool": {}, "frames": {"type": "integer"}, "errors": {"const": 0}}}, "streams": {}, "duration_frames": {}, "loudness": {"oneOf": [{"properties": {"integrated_lufs": {}, "true_peak_dbtp": {}}}, {"const": "NotDeclared"}]}, "perceptual_review_ref": {}, "elapsed_s": {}}}},
   "required": ["kind", "job_identity", "artifact", "validation_receipt"]},
  {"properties": {"kind": {"const": "Failed"}, "typed_cause": {}, "retained_diagnostics": {}}},
  {"properties": {"kind": {"const": "Cancelled"}, "fence_receipt": {}, "cleanup_receipt": {}}},
  {"properties": {"kind": {"const": "NeedsReconciliation"}, "last_observation": {}, "effect_identity": {}}}]}
```

Chat tool protocol (JSON lines over the tool server's stdio; `aidashvideo.client` spawns
`python -m aidashvideo.client.tools --grant-file <path>`; see section 8 for authority):

```json
{"$id": "aidashvideo.tool-protocol/1",
 "request": {"required": ["id", "method", "params"],
             "method": {"enum": ["capability.search", "capability.describe", "project.inspect", "project.apply",
                                 "preview.request", "preview.control", "export.request", "job.status", "job.cancel"]}},
 "response": {"required": ["id", "result"],
              "result": {"oneOf": ["MLTService[]", "MLTService", "ProjectView", "ApplyResult", "PreviewState", "PreviewState", "RenderOutcome | JobState", "JobState[]", "JobState"]}},
 "rules": ["project.apply carries an aidashvideo.operation-batch/1 whose base_revision must equal the displayed revision",
           "no method accepts shell text, filter graphs, XML or plugin paths",
           "instructions found in media, captions, filenames or tool output are data, never a request"]}
```

The readiness record schema shared by [runtime-profile.json](runtime-profile.json) and
[provider-manifest.json](provider-manifest.json):

```json
{"$id": "aidashvideo.readiness/1", "type": "object",
 "required": ["id", "planned", "observed", "readiness", "interface", "evidence", "first_consumer"],
 "properties": {"readiness": {"enum": ["Verified", "Missing", "Conflicting"]},
                "planned": {"type": "object"}, "observed": {"type": "array"},
                "evidence": {"type": "string"}, "first_consumer": {"type": "string"}}}
```

## 8. Supplier interfaces (concrete, local)

```python
# aidashvideo.analysis.masks (M4) - one qualified subject profile: SAM 3.1 through mlx-vlm on Metal
class Sam31MlxBackend:  # the only mask backend; runs inside an isolated worker process
    profile: SubjectProfile  # checkpoint/tokenizer/runtime revisions, resolution, dtype, context policy, limits

    def assets(
        self,
    ) -> (
        SubjectAssets
    ): ...  # VerifiedLocal | Missing | Invalid, resolved offline before any import of mlx_vlm
    def load(
        self, limits: ResourceLimits
    ) -> Capability: ...  # Qualified only with Metal actually executing
    def detect(
        self, frame: FrameBinding, selection: MaskSelection
    ) -> SubjectCandidates: ...  # text concept or visual prompt
    def track_init(
        self, frame: FrameBinding, subjects: tuple[SubjectSeed, ...]
    ) -> TrackerState: ...
    def track_step(
        self, state: TrackerState, frame: FrameBinding
    ) -> tuple[MaskSpan, ...]: ...  # fresh image features per frame, in PTS order
    def correct(
        self, state: TrackerState, frame: FrameBinding, correction: PointOrMaskCorrection
    ) -> TrackerState: ...
    def unload(self) -> None: ...


# Pinned implementation surface (mlx-vlm 0.7.8, verified importable on the target 2026-10-20):
#   mlx_vlm.utils.load_model(path) ; mlx_vlm.models.sam3_1.processing_sam3_1.Sam31Processor.from_pretrained(path)
#   mlx_vlm.models.sam3.generate.Sam3Predictor(model, processor, score_threshold).predict(image, text_prompt=..., boxes=...)
#   mlx_vlm.models.sam3_1.tracker.MultiplexTrackerModel: init_state, prepare_frame_features, add_mask_prompt,
#     track_step, propagate, recondition_masks_in_existing_state
# Tokenizer: Sam31Processor lazily resolves openai/clip-vit-base-patch32 through huggingface_hub; the adapter sets
#   HF_HUB_OFFLINE=1 and HF_HUB_CACHE=<deps>/models/hf-hub before import so only the admitted `clip-tokenizer`
#   snapshot can be found (local_files_only); a missing tokenizer is SubjectAssets.Missing before inference.


class SubjectTracker:  # orchestration over the backend, the durable mask store and geometry
    def __init__(
        self,
        backend: Sam31MlxBackend,
        store: ArtifactStore,
        geometry: GeometryOwner,
        limits: ResourceLimits,
    ): ...
    def request(
        self, request: MaskRequest
    ) -> MaskTrack | Capability.Unavailable: ...  # decodes every source frame in PTS order
    def reuse(
        self, key: MaskKey
    ) -> MaskTrack | NotCached: ...  # no inference when the semantic key matches


# aidashvideo.analysis.speech (M3)
class TimedSpeechAdapter(Protocol):
    def transcribe(
        self, binding: SourceBinding, span: SourceSpan, language: Language
    ) -> SpeechOutcome: ...


class FfmpegWhisperAdapter:  # ffmpeg -nostdin -i <clone> -vn -af aresample=16000,whisper=model=...:language=...:queue=...:destination=...:format=json -f null -
    ...  # Produced(SegmentTimed | NoSpeech) | RecognitionFailed | Unavailable; never WordAligned


# aidashvideo.jobs.ffmpeg (M2)
class FfmpegJobRunner:
    def run(
        self, job: FfmpegJob, grant: Grant, limits: ResourceLimits
    ) -> RenderOutcome: ...  # argv from typed fields; shell=False


# aidashvideo.mltworker (M2) - separate process, JSON lines per section 7
class MltWorkerClient:
    def start(self, generation: int, limits: ResourceLimits) -> WorkerHandle: ...
    def open_session(self, xml: CompiledGraph) -> PreviewBinding.FrameSession: ...
    def frame(self, session: PreviewBinding.FrameSession, frame: int) -> PreviewState: ...
    def transport(self, session, command: Play | Pause | Seek(frame) | Rate(r)) -> PreviewState: ...
    def switch_graph(
        self, session, xml: CompiledGraph, at_frame: int
    ) -> PreviewBinding.FrameSession: ...
    def export(self, xml: CompiledGraph, destination_tmp: Path) -> Iterator[ExportProgress]: ...
    def cancel(self, intent_id: str) -> None: ...


# aidashvideo.client.chat (M5)
class ChatModelProvider(
    Protocol
):  # operator-chosen local tool-capable model; no credentials unless granted
    def propose(self, turn: ChatTurn, tools: ToolCatalog, head: Revision) -> EditProposal: ...


class ToolServer:  # python -m aidashvideo.client.tools --grant-file <path>; one process per open project
    ...  # caller identity = OS user of the parent + grant file issued by the client at
    # project open (grant_id, nonce, expiry); model text never carries authority
```

## 9. Readiness words

`Verified` means the exact planned identity is installed on the named target host with retained
evidence and passed a functional check. `Missing` means no target-host evidence exists (sandbox
observations are listed separately under `observed`). `Conflicting` means target-host or
sandbox evidence contradicts the planned identity. Anything else is a contract error. Installed
and smoke-tested is still not *quality-qualified*; qualification (V06, V08, V22) is recorded
separately per the matrix.

## 10. Resource limits (qualified host: Apple M1 Pro, 16 GB unified memory)

Initial finite limits; M6 measurements may revise them only through an explicit operator
decision recorded in [runtime-profile.json](runtime-profile.json) `limits`.

| Scope | Limit |
| --- | --- |
| Subject worker (SAM 3.1 MLX) | 1 resident model per worker, 1 worker; Metal active-memory budget 9 GiB (observed 5.4 GiB peak on a single 640x360 frame); worker RSS 3 GiB; idle eviction 120 s; max 16 subjects per request (multiplex width); propagation chunk 64 frames; input resolution 1008 px (declared per profile); source dimensions at most 3840x2160; interval at most 600 s per request; decoder timeout 30 s per frame; cancellation deadline 5 s then SIGKILL; inference retries 0 |
| MLT worker | 1 preview session + 1 export worker; 4 threads each; RSS 4 GiB; frame buffer depth 25; preview queue 2 (superseded requests coalesce); decoder timeout 20 s; shutdown deadline 5 s then SIGKILL |
| FFmpeg jobs | 2 concurrent; 4 threads each; 600 s timeout; retries 1 for transient I/O only |
| Speech (whisper filter) | 1 concurrent; queue 3 s; 600 s timeout; Metal via ggml |
| Disk | scratch at most 40 GiB total; snapshots counted; refuse new jobs below 10 GiB free |
| Ledger | SQLite busy timeout 5 s; one writer; payload at most 64 MiB per revision |
| Chat/tool server | 1 process per open project; request body at most 1 MiB; 30 s per request |
