# Milestone 6: Verify the complete editor against the frozen contract

## 1. Task description

AiDashVideo is a standalone local video editor controlled through conversation, with immutable source media and a versioned project as its authority.
MLT evaluates the timeline and supplies playback/export; FFmpeg supplies explicit media jobs; timed speech and a separately qualified SAM 3.1 MLX adapter supply analysis.
Work only in this repository, using one AI implementer and the files produced by earlier milestones; do not require AiDashOS, private modules, a hidden daemon or previous chat history.
Inspect existing work first, preserve unrelated changes, and implement only this milestone.
Do not download/install packages or models, access new credentials, transfer media/prompts, spend, change shared services, overwrite originals, publish, push or merge without the operator's separate explicit authorization.
Use installed tools through `uv run --offline --no-sync` with automatic Python/package/model acquisition disabled; a missing tool is a named blocker, not permission to fetch it.
Reversible project edits and previews use the user's active project grant; exports additionally name the selected revision and granted new destination.

Entry: Milestones 0-5 passed with retained target-local evidence and an exact integrated candidate.
Execute the frozen verification matrix against that candidate, real UI/commands and authorized media/providers.
This is comprehensive behavioral verification, not another feature expansion or a design-compilation check.
Check the actual repository and existing evidence, then independently rerun the decisive cases; do not assume author-reported results are true.
One AI may prepare and run the checks, but describe this as verification performed by the implementer, not as a separate independent reviewer.
The human approval gate remains Milestone 7.

Use installed tools via `uv run --offline --no-sync` and the exact commands fixed in the plan.
Run from the actual aidashvideo root with the declared installed Python/toolchain and working-directory/configuration prerequisites.
Verify intended nonempty test collection and retain exact pytest, Ruff and Pyright command/source results; absent tools, dependencies or layout mismatches are blockers, never placeholder success or weakened checks.
When linked-project registration is used, verify its declared commands match these actual root/environment/configuration requirements without requiring AiDashOS for standalone execution.
Run focused tests, Ruff/Pyright, real native/provider integration, UI walkthrough, output probes/full decode and perceptual checks.
Missing dependencies, footage annotations, host capability, grants or tools are exact blockers; do not fetch anything or replace a required provider with a mock.
Fix in-scope discovered defects in reviewable changes, rerun affected/dependent checks, and bind final evidence to the final candidate.
Source changes invalidate stale evidence where the change can affect the tested contract.

Use the following complete golden path, preserving its assets, messages, expected duration and reset:

GP-01 caller: a local editor on the pinned Mac MLT/FFmpeg core profile with a qualified local SAM 3.1 MLX backend, existing licensed model assets and a grant limited to one disposable project directory.
Prepare local synthetic or operator-owned `interview.mp4` (12 seconds, one visible consenting subject, spoken phrase "hello golden path" at seconds 2-4), `broll.mp4` (4 seconds) and `music.wav` (20 seconds); retain hashes and probe results instead of assuming codec or timing support.

1. Choose New Project, select the granted directory, Import the three files and choose SDR Rec.709, 1920x1080, 30 fps; inspect each source identity, stream probe and initial project revision.
2. Send `Place interview first, remove source seconds 6 through 8, append broll, caption the spoken phrase, and duck music under speech`; inspect the proposed source ranges and timed-transcript evidence, then apply against the displayed revision.
3. Preview; expect a 14-second sequence with the two-second interval absent, the phrase caption aligned to qualified timing and audible ducking under speech.
4. Select the subject at interview source second 3 and send `Keep this person sharp and blur the background for the interview`; inspect full-span mask coverage, or NeedsCorrection/Unavailable instead of a completed effect.
5. Export the displayed revision to a new `golden-export.mp4`; accept only a VerifiedOutput receipt bound to a full decode, expected duration/streams and retained visual/audio review.
6. Ask the chat to list available effects, describe a packaged transform's animatable parameters, and animate the broll scale from 100% to 110% over its four seconds; inspect start/mid/end frames, save/reopen, and compare preview with export under the same effect identity.
7. Ask to set a nonexistent parameter on that effect; expect a typed rejection with the prior revision unchanged, then seek/pause/resume the valid preview through chat and inspect its displayed revision.
8. Cancel unfinished fixture jobs through their displayed Cancel control and reset by reopening the initial admitted revision; keep originals unchanged and delete only disposable exports after retaining evidence.

This milestone's GP-01 verification reuses these exact three assets and messages, then tests missing transcript timing, lost mask interval, stale revision and interrupted export; quality checks include actual preview/export frames and audio.
For the reset, reopen the initial revision for inspection or a new explicitly admitted edit lineage; do not rewind or delete canonical history.
All editor actions are proposed contracts and unexecuted here; qualifying the SAM 3.1 MLX host/backend is a blocking prerequisite for subject-aware acceptance, not evidence supplied by compilation.

The full acceptance matrix is embedded here so this milestone does not require the original CGD or previous chat:

| ID | Case | Required observation |
| --- | --- | --- |
| V01 | Full golden flow with several clips, titles, captions, music and blur | Saved revisions, preview and decoded export reflect every instruction; a human can hear/see the exact affected intervals; I1-I7 hold |
| V02 | Selective undo after blur plus half-second title shift | Only cut inverse and title timing change; blur binding survives; newly exposed untracked frames require repair instead of guessed masks |
| V03 | VFR, rotated portrait, mixed rates/resolutions, B-frame reordering and nonzero stream offsets | Correct orientation, subject coordinates and source-to-sequence mapping; caption/mask error at most one output frame on exact synthetic fixtures; A/V drift at most one output frame over a ten-minute fixture |
| V04 | Insufficient transition handles, negative title start, unsupported speed/HDR input | Explicit result; no partial patch, hidden clamping or silent color conversion |
| V05 | Repeated phrase, segment-only timing, silence, recognition error and failed inference with zero FFmpeg exit | Explicit span selection or refusal; no fabricated word time, transcript success or no-speech result |
| V06 | Word-alignment qualification | Against human-marked local samples, at least 95% of nominated word boundaries within 100 ms; failures remain preview/correction-only, with no precision claim outside the qualified footage/language profile |
| V07 | SAM occlusion, similar people, exit/re-entry, shot cut and correction | No accepted identity switch; questionable spans require correction; quality report includes boundary flicker and retained mask overlays |
| V08 | Qualified SAM 3.1 MLX mask quality | Median mask IoU at least 0.90 and fifth percentile at least 0.80 on agreed annotated visible-subject frames for text/visual selections, corrections and multi-object cases; no unacceptable halo/flicker in operator-reviewed clips; flagged loss is reported separately and cannot count as successful coverage |
| V09 | Deterministic edit replay, two concurrent clients and stale chat reply | Same validated patch produces the same project/graph hashes; one concurrent head update wins; stale writer and conflicting idempotency key fail without mutation |
| V10 | Corrupted cache, replaced/missing source, original modified during render and incompatible project version | No wrong-source or corrupt-mask reuse; render uses the verified stable source snapshot or fails; source/profile/precision/selection/correction changes cannot match old analysis; verified relink/migration preserves prior history |
| V11 | Metacharacters in captions/paths, network URLs and symlink races | Correct literal text or refusal; no unintended command, network request or access outside grants |
| V12 | Crash at payload seal, head commit, render, output publish and receipt admission | One admitted revision/effect; orphan staging has no authority; published outputs are adopted only with matching proof |
| V13 | Cancel during render, concurrent export, source-alias destination and disk/GPU exhaustion | Bounded owned-process cleanup, retained last good result, explicit published-race outcome, no original/foreign file deletion; even an overwrite grant cannot authorize a source-alias destination |
| V14 | Clean boot without optional packages; denied download/egress; unavailable SAM 3.1 MLX backend | Core boot/project inspection works; unavailable feature reported truthfully; no implicit install, upload, provider switch or shared model swap |
| V15 | Real preview/export correctness | Full decode passes; duration within one output frame; dimensions, rotation, rate, color tags, channel layout and sample rate match profile; synthetic audio agrees within one sample before lossy encoding; perceptual checks cover transitions, sync, titles, captions and masks |
| V16 | Audio delivery | A profile declaring -16 LUFS and -1 dBTP passes integrated loudness within 1 LU and measured true peak at or below -1 dBTP; other explicit delivery profiles use their own retained targets |
| V17 | Offline asset setup, missing tokenizer/model, corrupt files and failed Metal initialization | Complete pinned checkpoint/config/tokenizer/runtime assets run with denied egress and HF_HUB_OFFLINE=1; empty, incomplete or corrupt stores return Unavailable without fetching; repeated/interrupted setup preserves verified assets; actual execution is Metal and no CPU fallback is labeled qualified |
| V18 | SAM 3.1 MLX profile identity, residency and durable per-object masks | Exact profile/source/subject/PTS/precision bindings survive save/reopen/export; restart or model eviction reuses verified masks without inference; blur strength, titles, cuts, reorder and repeated occurrences preserve valid source masks; corrections invalidate affected propagation/dependents and missing ranges remain pending |
| V19 | SAM 3.1 MLX text/visual selection, interactive correction and fresh-frame tracking | Direct positive/negative points/boxes and native text produce confirmed or explicitly all-matching subject identities; ambiguous subjects require choice; correction and multi-object propagation use ordered actual source PTS/current-frame features; no skipped or stale-feature frame counts as qualified coverage; manual selection requires no extra VLM |
| V20 | Edits during delayed analysis, rapid blur changes and preview cancellation | Durable revisions survive restart before inference completes; independent edits remain available; unchanged mask dependencies run once; old output stays visibly stale and cannot replace a newer requested preview |
| V21 | Deferred export, uncached masks and preview/export agreement | No full-sequence encoding on ordinary edits; partial previews include required context; missing masks stay pending; export binds the selected revision/profile and cached mask identities, preserves sources and writes a separate file |
| V22 | Complete MLT package coverage | Frozen inventory reconciles with the installed build; every included editing service and parameter has a callable descriptor, read/change/reopen coverage and retained behavior evidence, including actual frame/audio changes; missing metadata/dependencies block full-profile qualification |
| V23 | Parameter typo, wrong type/units, NaN, out-of-range value, unsupported animation and malicious resource/plugin reference | Rejected before native graph construction with unchanged project head; no silent native ignore, clamping, module load or filesystem/network access |
| V24 | Chat-driven parameter/keyframe/retiming edits | Real chat tools enumerate and describe a service, admit its operations, persist/reopen them, selectively undo and produce inspected output; time-domain, inclusive-endpoint, hold/reverse and repeated-source mappings pass meaningful boundary cases for included services |
| V25 | Local operation without GUI editors or network | Granted installed MLT profile edits, previews and exports in aidashvideo without running Shotcut/Kdenlive or a remote render host; inspection with missing bindings/plugins returns a typed unavailable result and never installs them |
| V26 | Frame preview, seek/pause/resume and two rapid revisions | Actual MLT consumer displays the declared graph without full-movie encoding; obsolete frames cannot be labeled current; playhead mapping after a cut is explicit and viewing rate cannot retime the project |
| V27 | Concurrent playback graph replacement and export | Export keeps its original sealed revision/effect/profile; preview switches only at the declared boundary; cached masks and FFmpeg intermediates retain identical dependency identities |
| V28 | MLT crash, stale native session and stuck shutdown | Bounded owned-process cleanup, generation fencing and restart from durable project state; no stale frames, duplicated export publication or lost admitted edit |
| V29 | MLT build/plugin upgrade and missing service | Catalog digest mismatch is explicit; no silently changed defaults, effects or fallback renderer; prior project remains readable and migration/fallback needs an explicit qualified choice |
| V30 | Upgrade/rollback/portable reimport | History survives; old unsupported writers are fenced; reimport creates validated lineage; repeated migration/replay does not duplicate sources, revisions or effects |


Verify these invariants across the matrix:

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

Retain complete build/service/parameter coverage rather than extrapolating from a few effects.
Capture successful controls alongside refusal tests so an editor that refuses all edits cannot pass.
Keep core, complete MLT package, timed speech/alignment, real chat, SAM 3.1 MLX qualification independently inspectable.
Only explicitly excluded non-v1 capabilities may be marked not applicable with rationale; missing required work is not an exclusion.
Do not lower thresholds or narrow the frozen package after seeing failures; any contract change requires the operator's explicit decision and renewed evidence.

## 2. How to judge completion

- GP-01 and every applicable matrix row have observed results, command/UI steps, expected/actual comparison, artifacts and named candidate/environment identities.
- All I1-I12 requirements hold; each refusal case has a corresponding working control.
- Real media passes full decode, stream/profile/timing validation and visual/auditory inspection; actual speech and the real SAM 3.1 MLX mask profile meet their stated thresholds.
- Candidate-bound offline tests, Ruff/Pyright and UI integration checks pass; mocks prove control logic only and are not provider qualification.
- Retain missing proofs and limitations separately, including any unqualified alignment/profile/service, and do not label a partial pass full v1.

Measure these separately on named hardware:

- Edit admission and queue delay; model load; first usable fresh-frame mask; full-range masks; cached/uncached preview; full-export throughput; RAM/VRAM/scratch use; cache hits.
- SAM 3.1 MLX text/visual selection, correction and multi-object tracking on fresh source frames at the declared resolution/dtype; separately measure cold asset loading, model residency, full source-PTS coverage and durable-mask reuse without inference.
- Complete local asset setup under denied egress, including missing tokenizer/model and corrupt stores; restart/eviction and source/profile/selection/correction changes exercise persistent cache identity and invalidation.
- Remaining analysis based on actual missing source-frame coverage, observed uncached throughput and required temporal context; cold estimates marked provisional.
- MLT frame-preview startup, seek latency, buffer depth, dropped frames and sustained playback rate separately from encoded-range completion.

The agreed 1080p30 core fixture's cached-analysis ten-second changed range must preview within fifteen seconds on the qualified host to support the interactive-performance claim.
If it fails, retain the measured limit and block that claim until fixed or the operator explicitly approves a contract revision.
There is no universal real-time SAM or reconstruction claim.
Require identical semantic graph/dependency identities and declared output tolerances, not universal byte-identical GPU/codec output.

Each receipt binds candidate commit, dirty-source digest, tool/model/build hashes, fixture IDs, resource/authority identity, expected/observed result, elapsed time, output hashes and cleanup.
Leave a review bundle with the requirement matrix, source/diff inventory, evidence index, known limits and precise reproduction commands.
Hash the implementation/test/runtime/fixture scope of the candidate separately from later review/delivery prose to avoid circular approval identities.

Exit state: Milestone 7 has an exact reproducible candidate and complete evidence suitable for a human decision.
Any failed mandatory criterion or absent host/provider/grant proof prevents full v1 completion.

Retain a source-bound milestone report in `docs/evidence/milestone-6.md` and its referenced local artifacts.
Record the candidate commit and dirty diff/file hashes, exact commands and exit status, expected and observed results, tool/model/fixture identities, failures, retained artifact hashes, cleanup and remaining blockers.
For media/provider milestones, include inspectable output and visual/auditory findings, not just test counts.
Keep sensitive fixtures and large media out of Git; reference their operator-controlled local evidence store and record consent/availability.
Use `PASS` only when this milestone's required completion criteria have actual evidence; otherwise report `BLOCKED` or `FAIL` and the smallest missing proof.
Separate core, complete packaged MLT, timed speech and SAM 3.1 MLX readiness rather than collapsing them into one success flag.
Commit only this milestone's authorized files locally if instructed, record their identity, and stop before the next milestone.

## 3. Other notes for a reviewer

This milestone tests product behavior, not whether the design compiled or whether every file has a unit test.
Use actual audible/visible inspection and human annotations where specified; absence of those cannot be replaced by the same model's confident description.
The same implementer may execute verification, but must not call that independent operator approval.
The most important failure is a plausible result for the wrong revision, person, phrase or destination.
Review source identity, graph identity, coverage, authority and media quality together.

Review the exact candidate and the stated milestone scope, not a fluent implementation summary.
If given only a patch or a subset of files, imports may refer to earlier milestone code outside the review bundle.
Request the referenced contracts, implementation and relevant evidence before deciding; missing context is neither automatic failure nor proof of correctness.
Do not treat passing mocks, successful native setters, saved XML, a compiled design, or a zero process exit as proof of media/provider behavior.
The implementing AI's report is evidence to inspect, not an independent approval.
