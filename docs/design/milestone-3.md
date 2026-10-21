# Milestone 3: Add reusable timed speech and transcript editing

## 1. Task description

AiDashVideo is a standalone local video editor controlled through conversation, with immutable source media and a versioned project as its authority.
MLT evaluates the timeline and supplies playback/export; FFmpeg supplies explicit media jobs; timed speech and a separately qualified SAM 3.1 MLX adapter supply analysis.
Work only in this repository, using one AI implementer and the files produced by earlier milestones; do not require AiDashOS, private modules, a hidden daemon or previous chat history.
Inspect existing work first, preserve unrelated changes, and implement only this milestone.
Do not download/install packages or models, access new credentials, transfer media/prompts, spend, change shared services, overwrite originals, publish, push or merge without the operator's separate explicit authorization.
Use installed tools through `uv run --offline --no-sync` with automatic Python/package/model acquisition disabled; a missing tool is a named blocker, not permission to fetch it.
Reversible project edits and previews use the user's active project grant; exports additionally name the selected revision and granted new destination.

Entry: Milestone 2 passed; read its evidence and the explicit ASR selection/qualification profile in `docs/plan/provider-manifest.json`.
Implement source-relative timestamped transcripts, phrase selection, corrections, captions and transcript-driven cuts through the existing domain and job owner.
Select the exact qualified FFmpeg whisper filter or whisper.cpp adapter specified by the plan.
Do not rebuild/install FFmpeg, silently switch providers or alter a shared microphone/transcription service to make this task pass.

Normalize chunk/VAD offsets into the original audio stream's timing and coverage.
Reject malformed, decreasing, out-of-bounds or unexplained missing timing; preserve silence gaps and stream offsets.
Represent SegmentTimed, WordAligned and NoSpeech separately, with source/model/build/configuration/coverage provenance.
Cache recognition once per source stream/content, model, language, decoding, VAD and configuration identity.
Changing preview resolution, sequence position or retiming reuses source transcription and maps it through the established timing owner.

Return all matching phrase spans and clip occurrences with audible context and uncertainty.
Repeated phrases, low-confidence words, unclear boundaries or missing audio require an explicit selection/correction.
Segment timing permits segment captions and explicitly previewed coarse cuts, never an invented word timestamp.
WordAligned requires actual qualification of the selected adapter/version/language/footage class; parameter names suggesting word output are not sufficient.
Corrected text and corrected timing are separate versioned edits preserving the raw result.
Use one caption-event model for burn-in and sidecars, with explicit language, style and line breaks.
Cuts, reorder, selective undo and supported retiming must preserve the intended caption/source relationship.

Validate structured inference output, coverage and diagnostics independently of process exit.
A zero FFmpeg exit with an inference error is a failure.
An empty result is NoSpeech only when completed coverage proves it; test silence hallucination explicitly.
Report actual backend execution when GPU/Metal is claimed.
Unavailable build/model, denied acquisition and unsupported precision are truthful capability states and cannot block ordinary project inspection.

## 2. How to judge completion

- Run real authorized spoken and silent fixtures through the explicitly chosen installed adapter; retain model/code/configuration/host identities, output, coverage and diagnostics.
- Repeated phrase and repeated clip occurrences produce a choice; wrong/uncertain words and gaps permit correction without selecting a guessed interval.
- Segment-only output supports bounded coarse operations but rejects word-precise cuts until qualified alignment exists.
- Word-alignment acceptance is at least 95% of nominated boundaries within 100 ms against human-marked local samples; a failure remains preview/correction-only with no precision claim.
- Source/chunk/VAD offsets, mixed audio rates, edits/reordering/speed changes and selective undo keep captions/cuts aligned; exact synthetic mapping error is at most one output frame.
- Burn-in and sidecars derive from the same caption events and match inspected words, timing and line breaks.
- Editing or preview rerendering unchanged original speech reuses cached results rather than re-running inference.
- Zero-exit inference error, malformed timing, empty failure, genuine silence, corrupt cache and absent model are distinguished without fabricated speech evidence or automatic downloads.
- Core import/inspection and existing non-speech media behavior still pass.

Exit state: Milestone 4 has a working engine/domain plus timed speech; later chat integration can expose transcript edits with honest precision limits.
If real-provider or promised alignment evidence is missing, report the exact blocked scope rather than declaring complete speech qualification.

Retain a source-bound milestone report in `docs/evidence/milestone-3.md` and its referenced local artifacts.
Record the candidate commit and dirty diff/file hashes, exact commands and exit status, expected and observed results, tool/model/fixture identities, failures, retained artifact hashes, cleanup and remaining blockers.
For media/provider milestones, include inspectable output and visual/auditory findings, not just test counts.
Keep sensitive fixtures and large media out of Git; reference their operator-controlled local evidence store and record consent/availability.
Use `PASS` only when this milestone's required completion criteria have actual evidence; otherwise report `BLOCKED` or `FAIL` and the smallest missing proof.
Separate core, complete packaged MLT, timed speech and SAM 3.1 MLX readiness rather than collapsing them into one success flag.
Commit only this milestone's authorized files locally if instructed, record their identity, and stop before the next milestone.

## 3. Other notes for a reviewer

Recognition accuracy and timing accuracy are different claims.
Review raw provider output, corrected transcript lineage and human boundary annotations separately.
Mocks can test error routing but cannot certify an ASR build/model or a WordAligned capability.
This task does not require a separate new alignment service unless the selected adapter cannot meet a required qualified profile; such a change needs an explicit plan decision and any acquisition grant.

Review the exact candidate and the stated milestone scope, not a fluent implementation summary.
If given only a patch or a subset of files, imports may refer to earlier milestone code outside the review bundle.
Request the referenced contracts, implementation and relevant evidence before deciding; missing context is neither automatic failure nor proof of correctness.
Do not treat passing mocks, successful native setters, saved XML, a compiled design, or a zero process exit as proof of media/provider behavior.
The implementing AI's report is evidence to inspect, not an independent approval.
