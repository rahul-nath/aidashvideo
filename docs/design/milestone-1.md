# Milestone 1: Build durable projects and semantic editing

## 1. Task description

AiDashVideo is a standalone local video editor controlled through conversation, with immutable source media and a versioned project as its authority.
MLT evaluates the timeline and supplies playback/export; FFmpeg supplies explicit media jobs; timed speech and a separately qualified SAM 3.1 MLX adapter supply analysis.
Work only in this repository, using one AI implementer and the files produced by earlier milestones; do not require AiDashOS, private modules, a hidden daemon or previous chat history.
Inspect existing work first, preserve unrelated changes, and implement only this milestone.
Do not download/install packages or models, access new credentials, transfer media/prompts, spend, change shared services, overwrite originals, publish, push or merge without the operator's separate explicit authorization.
Use installed tools through `uv run --offline --no-sync` with automatic Python/package/model acquisition disabled; a missing tool is a named blocker, not permission to fetch it.
Reversible project edits and previews use the user's active project grant; exports additionally name the selected revision and granted new destination.

Entry: Milestone 0 passed, and `docs/plan/implementation-plan.md`, `contracts.md`, runtime/provider manifests, fixtures, verification matrix and commands exist in this repository.
Read that frozen plan and `docs/evidence/milestone-0.md`; surface any contradiction before dependent integration.
Build the authoritative project domain and persistence boundary, using the established package structure.
No MLT rendering or model inference is required to prove this milestone.

Implement in reviewable increments:

1. Implement closed IDs/quantities/results and the canonical admission owner, then test its transaction, replay, authority and outbox interface before wiring any mutating consumer.
2. Add immutable content-addressed project payloads, a source catalog, admitted head/lineage and portable serialization/import with schema compatibility.
3. Add shared timing/coordinate algebra and validated semantic operations, then selective undo/redo and migration/recovery behavior.

The portable schema contains sequence settings, source assets and probe/provenance, distinct clip occurrences, exact ranges, video layers/audio tracks, typed ordered effects, titles/captions and transcript/mask references.
Opaque IDs survive moves/cuts where their semantics permit; multiple occurrences of the same asset remain distinguishable.
Source availability is Present, Missing or Changed; only verified present sources can enter executable jobs.
Seal immutable payload bytes first, then atomically admit head, patch event, evidence references and required outbox intents.
Do not claim a database transaction also makes filesystem writes atomic.
Orphan blobs and interrupted readable serialization have no admission authority.
Importing a portable file validates it and creates a new lineage rather than replacing the canonical head behind its back.

An operation batch binds actor, project, base revision, idempotency key, canonical payload hash and object preconditions.
Validate the complete resulting project before any operation commits.
Same key and payload returns the original result, conflicting replay changes nothing, and only one concurrent expected-head update wins.
Chat/planner strings, client code, workers, copied files and raw model responses cannot become alternate durable writers.
Represent authorization failures and expected unavailability as typed outcomes; impossible internal states fail visibly rather than logging and returning success.

Implement InsertOccurrence, TrimOccurrence, MoveOccurrence, SetConstantSpeed, RetimeOccurrence, AddTransition, SetAudioMix, AddTitle, ShiftTitle, SetCaptions, BindSubjectEffect and RevertOperation with their required preconditions.
Provide descriptor-bound variants for generated sources, layers/tracks, processing links, effects, parameter/keyframe edits, transition settings and output profiles.
Preserve unimplemented provider requests as pending/unavailable dependency states without inventing qualification.
Reject unknown descriptor IDs and unconstrained arbitrary dictionaries.

Use finite rational half-open intervals `[start, end)` and explicit source, sequence and audio domains.
Keep actual decoded presentation timestamps/timebase, VFR mappings, audio offsets/sample rate, orientation and pixel aspect ratio in source contracts.
For constant positive speed `s`, use `source_time = source_in + s * (timeline_time - clip_start)` over the valid range.
Catalog-supported reverse, hold and variable-speed modes use explicit finite ordered timeline-to-source maps and declared interpolation.
Handle one source interval appearing several times without division by zero for holds.
Convert to native inclusive frame endpoints only at the later adapter boundary; domain interval `[0,30)` contains 30 frames, never 31.
Transitions validate both neighbors and sufficient source handles; negative title starts and unsupported profile/speed changes fail atomically.
Share this algebra with later transcripts, captions and masks, including requested versus realizable boundaries.

Selective undo creates a new inverse revision, preserving later independent operations.
Undoing a cut with an attached blur must prove dependent rebinding or return a specific conflict; newly exposed untracked source intervals become missing coverage.
Redo is a new validated operation at the current head.
Migrations create new immutable revisions and preserve old payloads/history; unsupported versions remain readable without permitting incompatible writers.
Relink/replacement requires verified bytes and explicit binding rather than silent path substitution.

## 2. How to judge completion

- Installed offline unit/property and persistence integration checks pass for the domain contracts, including malformed numbers/intervals, VFR boundaries, repeated occurrences, retiming, handles and geometry transforms.
- An actual temporary project database/store survives close/reopen with identical admitted content and lineage.
- Exact replay applies once; conflicting replay, stale client input, denied authority and two concurrent writers preserve the correct head and outbox facts.
- Inject failures before/after blob seal and transaction commit; the prior or newly admitted revision is recoverable without partial patches or duplicate intents.
- Sequence edits and descriptor-bound operations serialize/reopen without loss; unsupported descriptors cannot be made renderable by a copied file.
- Demonstrate cut, blur binding, independent title edit, selective cut inverse and half-second title shift; independent objects survive, and ambiguous rebind or negative start returns a precise conflict/choice.
- Repeated source passages, hold/reverse where declared, audio offsets and source/sequence mapping pass boundary tests without float drift.
- Changed/missing assets and incompatible schemas retain history, refuse execution eligibility and support the declared relink/migration/read-only behavior.
- Source files remain byte-identical; a portable reimport creates a validated lineage and repeated admission does not duplicate effects.
- All tests use real target-local persistence; no dependency on AiDashOS or a model/native engine is needed to import/inspect a project.

Exit state: Milestone 2 receives a tested authoritative project/operation API, immutable snapshots, time mapping and job-intent interface that it can consume without adding another writer.

Retain a source-bound milestone report in `docs/evidence/milestone-1.md` and its referenced local artifacts.
Record the exact commands and exit status, expected and observed results, tool/model/fixture identities, failures, retained artifacts, cleanup and remaining blockers.
For media/provider milestones, include inspectable output and visual/auditory findings, not just test counts.
Keep sensitive fixtures and large media out of Git; reference their operator-controlled local evidence store and record consent/availability.
Use `PASS` only when this milestone's required completion criteria have actual evidence; otherwise report `BLOCKED` or `FAIL` and the smallest missing proof.
Separate core, complete packaged MLT, timed speech and SAM 3.1 MLX readiness rather than collapsing them into one success flag.
Stop before the next milestone.

## 3. Other notes for a reviewer

The domain is the project of record; rendering has not been qualified in this milestone.
A pure function test alone cannot prove transaction atomicity, crash behavior or concurrency, so inspect real-store evidence.
Tests may use explicit unqualified analysis references to exercise pending coverage, but cannot certify providers or native effects.
The key design check is whether illegal executable states are prevented by constructors and ownership, rather than checked inconsistently throughout callers.

Review the exact candidate and the stated milestone scope, not a fluent implementation summary.
If given only a patch or a subset of files, imports may refer to earlier milestone code outside the review bundle.
Request the referenced contracts, implementation and relevant evidence before deciding; missing context is neither automatic failure nor proof of correctness.
Do not treat passing mocks, successful native setters, saved XML, a compiled design, or a zero process exit as proof of media/provider behavior.
The implementing AI's report is evidence to inspect, not an independent approval.
