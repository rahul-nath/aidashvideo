# Milestone 0: Prepare the repository and freeze implementable contracts

## 1. Task description

AiDashVideo is a standalone local video editor controlled through conversation, with immutable source media and a versioned project as its authority.
MLT evaluates the timeline and supplies playback/export; FFmpeg supplies explicit media jobs; timed speech and a separately qualified SAM 3.1 MLX adapter supply analysis.
Work only in this repository, using one AI implementer and the files produced by earlier milestones; do not require AiDashOS, private modules, a hidden daemon or previous chat history.
Inspect existing work first, preserve unrelated changes, and implement only this milestone.
Do not download/install packages or models, access new credentials, transfer media/prompts, spend, change shared services, overwrite originals, publish, push or merge without the operator's separate explicit authorization.
Use installed tools through `uv run --offline --no-sync` with automatic Python/package/model acquisition disabled; a missing tool is a named blocker, not permission to fetch it.
Reversible project edits and previews use the user's active project grant; exports additionally name the selected revision and granted new destination.

Start from the current repository containing README, LICENSE and NOTICE, with no editor implementation assumed.
The outcome is a runnable minimal Python repository and a frozen implementation plan precise enough for Milestone 1 to begin without inventing ownership or data semantics.
Establish the minimal repository bootstrap and frozen plan required by Milestone 1; this milestone does not implement the editor or run model inference.

Create these target-local planning artifacts and make their references resolve:

- `docs/plan/implementation-plan.md`: module boundaries, concrete public/local supplier interfaces, milestone entry/exit states, incremental work order, decisions, non-goals and migration/rollback design.
- `docs/plan/contracts.md`: closed domain/result variants, invariants, wire schemas, sole owners, timing/geometry algebra, operation semantics and persistence ordering.
- `docs/plan/runtime-profile.json`: exact MLT/native/Python/FFmpeg profile, full module/service inventory, descriptor schemas, fonts/codecs and dependency/build/license identities, with separately represented planned identities and observed installation evidence.
- `docs/plan/provider-manifest.json`: explicitly selected timed-ASR adapter and one SAM 3.1 MLX runtime/checkpoint/tokenizer/backend profile, acquisition requirements and readiness evidence.
- `docs/plan/verification-matrix.md`: each requirement, invariant and verification case mapped to an owning module, implementation milestone, positive control, refusal/failure test, fixture, expected result and retained evidence location.
- `docs/plan/commands.md`: exact offline development, formatting, static checking, unit/integration/UI verification, startup and future provider qualification commands, with explicit prerequisites.
The command plan names the actual aidashvideo root and installed Python/toolchain, working directory, configuration files and exact pytest, Ruff and Pyright scope.
Probe real intended test collection and command availability after bootstrap; an empty test set or scaffold does not prove readiness.
When an AiDashOS linked-project registration is used, inspect and correct its root/toolchain/verification commands through its existing owner; standalone execution records equivalent target-local commands without requiring AiDashOS.
- `docs/plan/fixtures.md`: GP-01 and edge-case corpus, source consent, existing asset hashes or reproducible generation recipes, annotations, comparison metrics and storage locations.
- Minimal `pyproject.toml`, lightweight `src/aidashvideo/` package, test configuration, `.gitignore` and one real import/boot isolation smoke test.

Choose maintainable concrete module names and a target-local durable storage implementation.
Use a single canonical transaction boundary for project heads, operation events, idempotency records and job/effect intents, plus immutable content-addressed artifacts and a transactional outbox.
A transactional local database is a possible implementation, not a requirement to copy any private system.
Bind each responsibility once: project domain; canonical admission; media/artifact store; capability catalog; graph compiler; native MLT worker; speech/mask adapters; one job supervisor; chat/client.
The worker and client cannot write project heads.
Record supplier readiness as `Verified | Missing | Conflicting`, the exact interface/evidence and first consumer.
For new target-local owners, freeze their contract here, then implement and test the admission owner first in Milestone 1 before integrating its mutating consumers.

Implement the following as closed variants with validated constructors in the later owning milestone; do not use nullable fields or unrestricted property bags to hide invalid combinations:

```text
AssetAvailability = Present(verified_hash, scoped_locator, probe_receipt)
                  | Missing(expected_hash, relink_request)
                  | Changed(expected_hash, observed_hash)

EditProposal = Applicable(base_revision, typed_patch, affected_objects)
             | NeedsChoice(candidates, question)
             | Unsupported(requested_capability, reason)

ApplyResult = Applied(revision, admitted_event)
            | AlreadyApplied(original_result)
            | RevisionConflict(current_revision)
            | Rejected(contract_reason)

Transcript = SegmentTimed(source_binding, segments, provenance)
           | WordAligned(source_binding, segments, words, qualification)
           | NoSpeech(source_binding, coverage_receipt)

MaskSpan = Tracked(source_interval, artifact, coordinate_contract, qualification)
         | NeedsCorrection(source_interval, reason, candidate_refs)
         | AbsentSubject(source_interval, validated_observation)

MaskRequest = SAM31MLXRequest(source_binding, source_interval, selection, correction_revision, qualified_profile)

MaskSelection = VisualSelection(frame_binding, validated_points_or_box)
              | TextSelection(frame_binding, concept, instance_policy)

InstancePolicy = AllMatchingInstances
               | SelectedInstances(candidate_binding, nonempty_subject_ids)

SubjectAssets = VerifiedLocal(checkpoint_snapshot, tokenizer_snapshot, runtime_manifest)
              | Missing(required_artifacts)
              | Invalid(artifact_identity, contract_reason)

PreviewState = Pending(revision, range, dependency_jobs)
             | Current(revision, range, preview_binding, dependency_manifest)
             | Stale(rendered_revision, requested_revision, artifact)
             | Unavailable(revision, range, typed_reason)

PreviewBinding = EncodedRange(artifact, output_profile)
               | FrameSession(session_id, graph_hash, worker_generation, output_profile)

MLTService = Callable(build_id, descriptor, qualification)
           | Unavailable(service_id, reason, required_action)

MLTParameter = Static(value_type, units, constraints)
             | Animatable(value_type, units, constraints, time_domain, interpolations)

Capability = Qualified(provider_identity, evidence, resource_profile)
           | Unavailable(reason, required_action)

RenderOutcome = VerifiedOutput(job_identity, artifact, validation_receipt)
              | Failed(typed_cause, retained_diagnostics)
              | Cancelled(fence_receipt, cleanup_receipt)
              | NeedsReconciliation(last_observation, effect_identity)
```

Freeze actor/project/base-revision/replay-key/payload-hash/object-precondition fields for operation batches.
Define whole-batch validation, exact replay, conflicting-key rejection, compare-and-swap, selective inverse dependencies and staged-blob recovery.
Define source asset versus clip occurrence IDs, immutable revision lineage and portable snapshot import as new admitted lineage.
Use rational half-open intervals, one source/sequence/audio mapping, actual VFR presentation timestamps, one oriented coordinate mapping and one conversion to MLT inclusive endpoints.
Define constant speed, catalog-supported animation/retiming, transition handles, caption timing and source-time mask coverage.
Freeze the visual order: orientation/normalization, source subject effect, clip transform/color, sequence/layers/transitions, titles/captions, output conversion.
Define alpha polarity/premultiplication, feathering, chroma/color handling and stable source snapshot behavior.

Preserve all twelve invariants:

- I1: Originals are never modified; replacement bytes require a new asset identity and an explicit rebind.
- I2: Only the canonical transition boundary commits project heads and job/effect facts; chat and files cannot bypass it.
- I3: Exact replay applies once, conflicting replay applies nothing, and concurrent edits cannot silently overwrite each other.
- I4: All source/sequence/audio timing and mask geometry flow through their single domain mapping owners.
- I5: Transcript and subject identity uncertainty stays explicit; unsupported precision or missing coverage cannot become successful evidence.
- I6: Preview frames/sessions and export artifacts bind the exact revision, graph, worker generation, inputs, capabilities and validation evidence; stale or partial output is visibly distinct.
- I7: Selective undo preserves independent later operations and either proves dependent rebinding or returns a conflict.
- I8: No download, upload, model fallback, shared service change, spend, overwrite or publication occurs without its declared grant.
- I9: Job cancellation/recovery respects ownership and fencing; ambiguous effects are reconciled, never guessed or blindly repeated.
- I10: Optional providers remain isolated; a missing optional stack cannot break basic project inspection or core boot.
- I11: Every editing service/parameter in the frozen MLT package has a chat-callable contract and retained qualification; unknown or ignored values cannot become admitted success.
- I12: MLT objects/XML are derived execution state; graph replacement, viewing controls and native failures cannot alter project authority or an already-bound export.

Freeze the complete MLT package before implementation.
List editing producers, filters, transitions, links and consumers with every supported parameter's type, units, defaults, ranges/enums, resource rules, animation/time domains, pixel/audio constraints, interactions and dependencies.
Distinguish excluded framework/capture/network plumbing from missing editing dependencies.
Missing upstream metadata requires a version-bound descriptor and behavior test, not a silent omission.
Include at least core video composition, keyframable transform, text/captions, audio mixing/ducking and mask composition.
Fix the initial SDR Rec.709 profile, dimensions, rational frame rate, stereo layout and exact codec/container pair.
An uninstalled component is not verified; record a precise acquisition blocker without downloading anything.
If available evidence cannot fix an exact package boundary or required interface, keep that planning item blocked instead of inventing a pin.

Pin a qualified-candidate FFmpeg-whisper or whisper.cpp adapter explicitly.
Pin `mlx-vlm` with the full SAM 3.1 temporal tracker/correction APIs and compatible MLX, Transformers, Hub and preprocessing packages; bind `mlx-community/sam3.1-bf16` checkpoint/configuration and compatible `openai/clip-vit-base-patch32` tokenizer snapshots.
Use one isolated local Metal worker, explicit local tokenizer binding and pinned snapshot/path lookup with `local_files_only=True` and `HF_HUB_OFFLINE=1` before provider imports.
Freeze text/visual selection, explicit instance policy, positive/negative points/boxes, correction, ordered source-PTS tracking with fresh image features, observed precision and actual Metal execution.
Define persistent per-object source-frame mask artifacts with source/stream/PTS/grid, subject/selection/correction, model/tokenizer/runtime/preprocessing/precision/context keys; separate durable masks from asset storage and transient model/feature residency.
Model eviction or application restart preserves masks; cuts/reorder/repeated clip occurrences/title/blur changes reuse matching masks, while changed dependencies and newly exposed source coverage require the precise invalidation/recompute path.
No source-frame drop or earlier-frame backbone reuse may count as faithful mask coverage; segmentation need not run in real time.
Define an acquisition manifest with source/version/hash, license/access terms, bytes, destination, host/backend, conversion inputs, transitive dependencies and repeat/interruption behavior.
Keep the runtime package licenses and Meta SAM model terms/access requirements distinct from this repository's own license.
Include missing-tokenizer/model, corrupt/empty stores, denied-egress, repeat/interrupted setup, restart/cache-reuse and correction-invalidation cases in the qualification plan.
Local-only is the default; a remote adapter requires an explicit named host, frame/media/prompt/transcript/mask transfer scope, retention policy, credential owner, resource/cost ceiling and cancellation contract.
Naming a candidate remote host in the plan does not grant any transfer, inference or spending.
Use one resident segmentation model per worker by default, bounded reuse and idle eviction.
Set finite limits for CPU/GPU memory, threads, queues, buffers, disk, dimensions/duration, process/decoder timeout, cancellation deadline and retries appropriate to the qualified host.
Keep source-aware analysis separate from project admission, faithful preview, approximate preview and final export.

Define one real tool-capable chat integration and local subprocess/stdio protocol for capability search/describe, project inspect/apply, preview request/control, export request and job status/cancel.
Declare how caller identity and project/resource grants are established without treating model text as authority.
No external AI API usage or new credential access is granted by selecting an interface.

Required first-release behavior includes core cuts/order/layers/constant positive speed/crossfades/titles/captions/crop/scale/SDR adjustments/audio gain/fades/ducking/mix; all declared MLT editing services and parameters; supported keyframes/retiming; local frame and bounded file previews; timed speech; the SAM 3.1 MLX mask profile; selective undo; portable projects; recovery and verified export.
Core remains usable when model packages are absent, but full v1 requires the SAM 3.1 MLX mask profile and the complete frozen MLT package to qualify.
Inpainting and DINOv3 have typed unavailable extension contracts only.
Exhaustive commercial-editor parity, HDR grading, live multicam, synchronized multicam workflow, collaboration, 3D, automatic identity recognition, arbitrary scripts/XML, general template/interchange compatibility and automatic installs/publishing are outside this version.
High-level stabilization intent solving is future work even if a packaged stabilization filter is callable.
The user's chosen external chat on the left and actual QuickTime on the right is V2; v1 needs one working chat/player integration, not QuickTime automation.

Embed the GP-01 flow and the entire verification checklist from `milestone-6.md` in the plan's requirement map, including thresholds.
Do not lower requirements after a failed result; a proposed contract change needs an explicit operator decision and preserved prior requirement/evidence.
Do not download fixtures or models to finish planning.

## 2. How to judge completion

- Repository inspection confirms the initial state and preserves the existing README, license and notice meaning.
- The minimal package imports and its isolation smoke test actually runs using installed tools without loading MLT, MLX, mlx-vlm, Transformers, Torch, SAM, Whisper or starting services.
- Exact verification commands run from the actual target root with the declared installed environment and intended nonempty tests; missing tools/configuration are explicit blockers rather than zero-test success.
- All planning files above exist and agree on exact interfaces, owners, schemas, package boundary and readiness states; no required architecture choice is left as an unexplained TODO.
- Every invariant I1-I12 and every `V01` onward case in the packet coverage map has a concrete implementation owner and positive/negative acceptance plan.
- Required fixtures absent locally have exact preparation recipes and permission blockers; invented media/model hashes do not count as evidence.
- The installation/acquisition plan distinguishes desired exact artifacts from observed installed identities and never labels an absent dependency qualified.
- The plan defines replay/concurrency, authority, stable media, migration and failure contracts sufficiently for Milestone 1 to implement them without a private supplier.
- Missing native/model tools may remain recorded blockers for later qualification without blocking domain implementation; an unresolved foundational contract or failed bootstrap check prevents Milestone 0 PASS.

Exit state: Milestone 1 can start building the durable domain from concrete contracts in a working repository.
No editing, playback, transcription or segmentation capability is claimed yet.

Retain a source-bound milestone report in `docs/evidence/milestone-0.md` and its referenced local artifacts.
Record the candidate commit and dirty diff/file hashes, exact commands and exit status, expected and observed results, tool/model/fixture identities, failures, retained artifact hashes, cleanup and remaining blockers.
For media/provider milestones, include inspectable output and visual/auditory findings, not just test counts.
Keep sensitive fixtures and large media out of Git; reference their operator-controlled local evidence store and record consent/availability.
Use `PASS` only when this milestone's required completion criteria have actual evidence; otherwise report `BLOCKED` or `FAIL` and the smallest missing proof.
Separate core, complete packaged MLT, timed speech and SAM 3.1 MLX readiness rather than collapsing them into one success flag.
Commit only this milestone's authorized files locally if instructed, record their identity, and stop before the next milestone.

## 3. Other notes for a reviewer

This is planning plus the minimal repository bootstrap needed for the user's sequential experiment.
The original CGD labels Milestone 0 PLAN; adding an importable package and test entrypoint is an explicit adaptation, not evidence that the original milestone implemented these already.
Evaluate completeness of decisions and traceability, not the existence of a large folder skeleton.
Empty feature modules, fake native adapters and passing placeholder tests are unnecessary and do not advance readiness.
Future provider absence is acceptable only when exactly identified and isolated from the domain work that follows.
Do not require the next AI to rediscover private owner documents or request choices already fixed by this task.

Review the exact candidate and the stated milestone scope, not a fluent implementation summary.
If given only a patch or a subset of files, imports may refer to earlier milestone code outside the review bundle.
Request the referenced contracts, implementation and relevant evidence before deciding; missing context is neither automatic failure nor proof of correctness.
Do not treat passing mocks, successful native setters, saved XML, a compiled design, or a zero process exit as proof of media/provider behavior.
The implementing AI's report is evidence to inspect, not an independent approval.
