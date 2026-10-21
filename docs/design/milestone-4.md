# Milestone 4: Add local SAM 3.1 MLX tracking and subject effects

## 1. Task description

AiDashVideo is a standalone local video editor controlled through conversation, with immutable source media and a versioned project as its authority.
MLT evaluates the timeline and supplies playback/export; FFmpeg supplies explicit media jobs; timed speech and a separately qualified SAM 3.1 MLX adapter supply analysis.
Work only in this repository, using one AI implementer and the files produced by earlier milestones; do not require AiDashOS, private modules, a hidden daemon or previous chat history.
Inspect existing work first, preserve unrelated changes, and implement only this milestone.
Do not download/install packages or models, access new credentials, transfer media/prompts, spend, change shared services, overwrite originals, publish, push or merge without the operator's separate explicit authorization.
Use installed tools through `uv run --offline --no-sync` with automatic Python/package/model acquisition disabled; a missing tool is a named blocker, not permission to fetch it.
Reversible project edits and previews use the user's active project grant; exports additionally name the selected revision and granted new destination.

Entry in this sequential experiment: Milestone 3 passed; the functional source dependency is the domain/engine from Milestone 2.
Read the frozen provider/asset manifests and earlier source-bound evidence.
Implement the complete contract below in the existing job, artifact and coordinate owners.
The SAM 3.1 MLX profile is required for full v1; core editing/inspection remains usable without its packages or assets.

Subject selection, segmentation, temporal tracking and correction use one qualified local SAM 3.1 MLX profile on Apple Silicon Metal.
Use `mlx_vlm` to execute `mlx-community/sam3.1-bf16`; `huggingface_hub` owns pinned local snapshot lookup, and Transformers supplies the compatible CLIP tokenizer rather than SAM 3.1 model execution.
The provider adapter hides model loading, tokenizer configuration, tensor layout, preprocessing, session APIs and native runtime assumptions from the project domain.
Pin a tested `mlx-vlm` release or commit containing the full multiplex temporal tracker and required correction APIs, plus compatible MLX, Transformers, Hub and image-processing dependencies.
Reference interfaces: [MLX SAM 3.1](https://github.com/Blaizzy/mlx-vlm/tree/main/mlx_vlm/models/sam3_1), [tracker model](https://github.com/Blaizzy/mlx-vlm/blob/main/mlx_vlm/models/sam3_1/sam3_1.py), [interactive tracker](https://github.com/Blaizzy/mlx-vlm/blob/main/mlx_vlm/models/sam3_1/tracker.py) and [processor](https://github.com/Blaizzy/mlx-vlm/blob/main/mlx_vlm/models/sam3/processing_sam3.py).
Upstream moving links describe candidate interfaces; The frozen plan records the exact qualified code and asset identities.

The complete local asset set includes the SAM checkpoint/configuration and the compatible `openai/clip-vit-base-patch32` tokenizer files used by the processor.
An explicit setup action places and verifies those files on local disk; no hosted service is required.
The runtime accepts only verified local paths or pinned snapshots resolved with `local_files_only=True`, with `HF_HUB_OFFLINE=1` set before provider imports.
Bind the processor to the verified local tokenizer explicitly; a lazy loader may not resolve an unpinned repository ID or fetch missing tokenizer files at first text use.
Missing, corrupt or incompatible assets produce a typed unavailable result before inference, including when only the tokenizer is missing.
The asset label does not establish tensor precision: record observed storage and execution dtypes and bind any explicit cast to the qualified profile and mask cache key.
Use actual resource measurements for admission; checkpoint file size alone is not a readiness failure or an estimate of peak working memory.

The admitted request binds the source content/stream, source-time interval, selection, correction revision and exact qualified profile before execution.
Support direct positive/negative points and boxes, native text-concept selection, candidate confirmation and point/mask corrections through the same source/frame coordinate boundary.
Selection binds source hash, presentation timestamp, oriented frame dimensions and validated coordinates; text binds its concept and explicit instance policy.
An explicit all-matching selection may create multiple stable subject IDs; an ambiguous single-subject instruction returns candidates for a choice rather than picking a similar person silently.
The user may select directly or an already authorized vision-capable chat model may propose a frame-bound visual selection; a separate VLM and whole-video LLM analysis are not required.
New detections, re-entry and reacquisition obey the admitted instance policy and never silently replace an existing subject identity.
Switching checkpoint, precision, preprocessing or runtime profile requires an explicit admitted operation and new dependent mask bindings; missing Metal or failed inference never selects CPU, a remote provider or another model automatically.

Run a bounded, isolated, on-demand inference worker through the existing job/resource owner.
Load the profile for admitted subject jobs, reuse it while useful work is queued and evict it after the configured idle period or resource pressure without affecting shared chat/speech services.
Use temporal tracker initialization/propagation and correction APIs directly rather than treating an annotated demo video as source-mask output.
Decode and process every required source frame in presentation order with its actual PTS, source orientation and current image features, including necessary context from the selection frame or a compatible tracker checkpoint.
Reusing a frame's backbone features for repeated work on that exact frame is valid; reusing earlier-frame image features or dropping source frames cannot produce qualified complete coverage.
Realtime demos and approximate previews may have different policies, but their output is labeled approximate and cannot enter the faithful preview/export mask cache.
Cancellation fences publication; partial results identify their exact coverage and cannot become a completed range.
Segmentation may run slower than playback; v1 requires usable asynchronous editing and truthful progress, not real-time full-resolution inference.

A mask sample describes one subject on one source frame; a track is the ordered collection of those samples over a declared interval.
Store verified masks as durable project-referenced analysis artifacts, optionally chunked across frames, rather than session-only GPU state or a temporary rendered overlay.
Their semantic key binds source content hash, stream, exact PTS/coverage, oriented grid, selection and correction identity, checkpoint/tokenizer/runtime revisions, preprocessing, resolution, execution dtype and tracking-context policy.
Persist polarity, coordinate mapping, stable subject IDs, coverage, quality/provenance and artifact integrity with each track version.
Separate downloaded-asset storage, transient model/feature residency and durable mask storage; releasing the model never deletes masks.
Reopening the project after application restart or model eviction reuses verified masks without inference when those semantic dependencies match.
Cuts, reorder, repeated clip occurrences, titles and blur-strength changes reuse the same source-space masks; a different source, selection, correction or provider profile cannot match that cache entry.
Newly exposed source ranges request missing samples plus necessary temporal context, and a correction invalidates affected propagation/dependent composites without recomputing independent tracks.
Keep referenced mask versions available for admitted revisions and portable snapshots; cache cleanup is explicit and cannot silently remove the only artifacts needed to reproduce a retained edit.

Store `Tracked`, `NeedsCorrection` and `AbsentSubject` spans distinctly.
Occlusion, shot cuts, exit/re-entry, similar people and uncertain identity require an explicit observation or correction; missing coverage is neither absence evidence nor permission for indefinite last-mask reuse.
Inspect normalized masks and final MLT composites under the Milestone 6 coordinate, quality and identity-continuity cases.
Measure cold load, first fresh-frame mask, warm different-frame inference, complete source coverage, peak memory and unload separately; cached or dropped-frame FPS is not full-shot throughput.
Record actual Metal execution rather than inferring it from successful imports or model initialization.

DINOv3 reacquisition and inpainting remain unavailable extension contracts unless separately qualified and authorized.
DINOv3 may propose reacquisition candidates but cannot silently assign another person to a subject.
Inpainting consumes source frames and masks and returns new derived media with timing/geometry/reconstruction provenance; it never overwrites sources or reports a blur as reconstructed scenery.
Changing masks invalidates dependent reconstruction, whose temporal quality and altered unmasked regions require separate acceptance.

Compose foreground * mask + blurred background * (1 - mask) through the existing MLT alpha/color/transform/retiming contract.
Any FFmpeg preprocessing is an explicit hashed dependency shared by preview/export.
Persist admitted edits while inference is pending; retain useful shared mask work when its preview is superseded and keep stale output visibly distinct.
Implement the acquisition plan without executing unapproved downloads: identify each runtime/checkpoint/config/tokenizer artifact, revision, hash, license, size, destination and qualification fixture.
Repeat/interrupted local setup must preserve the previous verified profile and never promote incomplete assets.

## 2. How to judge completion

- The exact local profile runs real authorized text/visual selections, temporal tracking, interactive corrections and multi-object fixtures on Metal; retain masks, overlays, composites and actual backend/code/model/tokenizer/precision identities.
- Median mask IoU is at least 0.90 and fifth percentile at least 0.80 on agreed annotated visible-subject frames, with no unacceptable halo/flicker in reviewed clips; flagged loss cannot inflate successful coverage.
- Every required source PTS has a corresponding current-frame-derived mask or explicit missing/ambiguous/absent state; frame skipping, stale feature reuse and dropped-frame FPS never establish full-shot success.
- Selection/coordinates, rotation, crop/scale, repeated/retimed occurrences, similar people, occlusion, cuts and exit/re-entry produce no accepted identity switch; ambiguous text needs choice and corrections invalidate affected propagation.
- Complete verified local weights/config/tokenizer/runtime assets work with denied egress and HF_HUB_OFFLINE=1; missing tokenizer, missing model, empty/corrupt stores or incompatible runtime return precise Unavailable without fetches or fallback.
- Save masks per subject and source PTS, restart the application and evict/reload the model; matching masks are reused without inference, and changed source/selection/correction/profile/precision never collides with that cache entry.
- Blur strength, titles, cuts, reorder and repeated source occurrences reuse matching masks; newly exposed coverage and affected correction context are computed while independent tracks remain cached.
- Profile identity survives reopen/export, and unavailable Metal or resource pressure never silently selects another model, CPU or remote execution.
- Cold load, first fresh-frame result, warm different-frame inference, full-range completion, memory and unload are measured separately; no real-time or cross-model speed ratio is required.
- Repeat/interrupted setup preserves the previous verified profile; core-without-models boot and inspection pass, and reconstruction remains explicitly unavailable.

Exit state: Milestone 5 can connect the qualified subject capabilities to the client, with pending/correction/unavailable states intact.
Missing required local profile proof prevents full v1 completion.

Retain a source-bound milestone report in `docs/evidence/milestone-4.md` and its referenced local artifacts.
Record the candidate commit and dirty diff/file hashes, exact commands and exit status, expected and observed results, tool/model/fixture identities, failures, retained artifact hashes, cleanup and remaining blockers.
For media/provider milestones, include inspectable output and visual/auditory findings, not just test counts.
Keep sensitive fixtures and large media out of Git; reference their operator-controlled local evidence store and record consent/availability.
Use `PASS` only when this milestone's required completion criteria have actual evidence; otherwise report `BLOCKED` or `FAIL` and the smallest missing proof.
Separate core, complete packaged MLT, timed speech and SAM 3.1 MLX readiness rather than collapsing them into one success flag.
Commit only this milestone's authorized files locally if instructed, record their identity, and stop before the next milestone.

## 3. Other notes for a reviewer

Review the exact local MLX worker's behavior, offline asset closure, timestamp/subject bindings, persistent mask reuse and final composition quality.
Model weights on disk, a resident model, transient backbone features and durable masks have different lifetimes and invalidation rules.
Neither an annotated demo video nor fast repeated inference on cached image features proves accurate source-time video tracking.
The source graph allows core UI work independently of subject readiness; this packet's sequential execution still requires the stated milestone entry evidence.
Verify the required selection/correction/propagation APIs in the pinned code; package branding and checkpoint names cannot establish capabilities or dtype.
Do not add dependency downloads, a second model profile, remote execution or broader feature parity as implicit requirements.
