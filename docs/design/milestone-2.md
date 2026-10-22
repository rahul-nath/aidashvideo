# Milestone 2: Build the local MLT engine, previews and safe media jobs

## 1. Task description

AiDashVideo is a standalone local video editor controlled through conversation, with immutable source media and a versioned project as its authority.
MLT evaluates the timeline and supplies playback/export; FFmpeg supplies explicit media jobs; timed speech and a separately qualified SAM 3.1 MLX adapter supply analysis.
Work only in this repository, using one AI implementer and the files produced by earlier milestones; do not require AiDashOS, private modules, a hidden daemon or previous chat history.
Inspect existing work first, preserve unrelated changes, and implement only this milestone.
Do not download/install packages or models, access new credentials, transfer media/prompts, spend, change shared services, overwrite originals, publish, push or merge without the operator's separate explicit authorization.
Use installed tools through `uv run --offline --no-sync` with automatic Python/package/model acquisition disabled; a missing tool is a named blocker, not permission to fetch it.
Reversible project edits and previews use the user's active project grant; exports additionally name the selected revision and granted new destination.

Entry: Milestone 1 passed; read its evidence and the frozen plan/contracts/runtime profile.
Use the existing admission, artifact and mapping interfaces.
Implement the isolated local native MLT worker, complete packaged capability catalog, deterministic graph compiler, explicit FFmpeg jobs and bounded supervisor.
Qualifying this milestone requires the exact authorized installed native stack; contract work may proceed when it is absent, but do not claim a qualified engine.

Implement in increments with retained native evidence:

1. Inventory/typed descriptors and validation; reconcile the installed build/ABI/plugins with the frozen manifest before graph construction.
2. Immutable graph lowering and real core video/audio/text/mask primitives with native positive controls.
3. Frame preview/transport and immutable encoded ranges; worker generations, graph replacement and dependency/cache handling.
4. Export validation/publication, resource containment, cancellation, interruption and effect reconciliation.

Enumerate all declared editing producers, filters, transitions, links and consumers.
Expose types, units, defaults, enums/ranges, animation/interpolation/time domains, resource constraints, formats and interactions through read-only discovery.
Supplement incomplete upstream metadata with build-bound descriptors and real behavior tests.
Every included service and supported parameter must be callable through the generic domain operation; a metadata listing or setter returning success is not qualification.
Do not shrink the frozen package after failures.
Reject typos, NaN, wrong units/types, unknown properties, unsupported animation and ungranted resources before native calls, preserving the head.
Catalog inspection cannot start model inference, arbitrary media work or acquisition.

Compile each revision to one immutable graph manifest, with explicit hashed external analysis/FFmpeg intermediates.
MLT composes clips/layers/transitions, color/transforms, titles/captions, gain/fades/ducking/mix, catalog effects and supported keyframes/retiming.
FFmpeg jobs handle declared probing, proxy/conversion and preprocessing; they cannot silently substitute a different renderer for unsupported MLT effects.
Native XML/objects are derived artifacts, never editable authoritative project state.
Convert domain half-open spans to MLT inclusive endpoints exactly once and use the shared mapping for caption/mask/audio timing.
Apply the plan's orientation, alpha/color, mask polarity, transform and effect-order contract.
HDR inputs require a visible qualified tone-mapping choice into the SDR profile or explicit refusal; silently stripping HDR metadata is prohibited.
Synthetic masks and timed caption events may qualify composition here; real speech and tracker qualification belong to later milestones.

Use the pinned library API in a supervised target-owned worker, with bounded local subprocess/stdio messages, not an open GUI editor or required remote host.
Serialize graph switches and transport commands; keep native object lifetimes inside the worker.
Provide on-demand frame evaluation without first encoding the movie, plus bounded immutable file previews for clients needing a file.
Bind every frame/session to revision, graph hash, source mapping, profile and worker generation.
Stage/switch new preview graphs at a controlled boundary; drop or visibly mark old frames stale.
Pause/play/seek/viewing-rate controls cannot alter editorial retiming.
An export keeps its own sealed graph even while preview switches to a later revision.
Worker restart invalidates old sessions and rebuilds them from admitted data, not persisted native pointers.

Jobs bind a revision/graph, toolchain, resource grant, deadline, staging ownership and execution fence.
Implement bounded CPU/GPU memory, threads, buffers, queues, scratch disk, decoder timeouts and termination deadlines from the plan.
Use stable hash-verified project-owned snapshots/copy-on-write clones for the entire job; an open descriptor or pre-render hash check alone does not stop in-place source mutation.
Refuse changed originals or insufficient snapshot space without silently rebinding/deleting anything.
Resolve file/plugin/resource handles under the grant at use time; freeze module search paths.
Use controlled serializers and argument arrays with `shell=False`, while separately protecting filter text, XML, codecs, protocols, caption resources, path traversal and symlink races.
No LLM-authored raw shell/filter/XML/plugin path is executable input.

Cache independently: transcripts, masks, reconstruction extensions, proxies and outputs.
Key each by relevant source/stream/range, normalization, tool/model/build, prompt/correction/configuration, seed, output profile and dependency hashes.
Verify cache artifacts before reuse; partial/corrupt output is not a hit.
Preview size/title/blur-strength/order changes reuse unchanged source analysis; model/input-resolution/prompt/correction changes do not.
Missing coverage remains pending and includes tracker/temporal/transition/audio context, even for a small requested preview.
Coalesce superseded presentation jobs while preserving admitted revisions and useful authorized shared analysis.

Export explicitly binds the user's selected revision, output profile and new destination.
Write to owned staging, fully decode/probe and validate it, then atomically publish under the current fence to a reserved destination.
For cross-volume output, stage on the destination volume before final publication.
Refuse source aliases by identity/path/symlink even with an overwrite grant.
Existing non-source output needs a separate exact destination/hash overwrite grant; the default flow refuses it.
Recover publication-before-receipt crashes by inspecting/adopting matching effects, not blindly publishing twice.
Cancellation fences new publication, bounds owned-descendant termination, retains the last good result and honestly reports an output that already won the race.
Cleanup touches only owned uncommitted staging.

## 2. How to judge completion

- Real installed MLT/FFmpeg fixtures cover cuts/order/layers/crossfades, constant speed and catalog-supported retiming/keyframes, transform/color/text/caption/mask composition and audio gain/fades/ducking/mixing.
- The entire frozen editing inventory reconciles with the actual build and has callable typed descriptors plus positive parameter/output, read/change/reopen and refusal evidence; no metadata-only or ignored-property success is counted.
- Inspect output frames/audio, including transform start/mid/end and boundary endpoints; native success without the requested output change fails.
- Frame preview works without a full-movie intermediate; file previews encode only the requested affected range plus required context.
- Two rapid revisions, concurrent export, seek/pause/resume, worker crash/restart and stale frames keep correct revision/generation/graph identities.
- Full exports decode and match duration within one output frame, geometry/rotation/rate/color/channel/sample-rate profile and declared audio targets; synthetic PCM timing agrees within one sample before lossy encoding.
- Changed original during rendering, corrupt/partial cache, malformed paths/text, URLs, plugin substitution and symlink races cannot produce wrong-media output or unauthorized access.
- Failure injection around seal/admission/render/publication/receipt, concurrent exports, cancellation, stuck shutdown and disk/resource exhaustion passes the declared cleanup and reconciliation contracts.
- Missing native packages still allow core package boot and project inspection with exact typed unavailable results, no installation or hidden fallback.
- Offline tests/static checks and real native/media verification pass; retain commands, hashes, probes, decoded output and perceptual review.

Exit state: Milestone 3 can attach timed speech to working admitted media jobs, captions and source-time mapping.
The UI and real speech/subject inference are not certified by engine tests.

Retain a source-bound milestone report in `docs/evidence/milestone-2.md` and its referenced local artifacts.
Record the exact commands and exit status, expected and observed results, tool/model/fixture identities, failures, retained artifacts, cleanup and remaining blockers.
For media/provider milestones, include inspectable output and visual/auditory findings, not just test counts.
Keep sensitive fixtures and large media out of Git; reference their operator-controlled local evidence store and record consent/availability.
Use `PASS` only when this milestone's required completion criteria have actual evidence; otherwise report `BLOCKED` or `FAIL` and the smallest missing proof.
Separate core, complete packaged MLT, timed speech and SAM 3.1 MLX readiness rather than collapsing them into one success flag.
Stop before the next milestone.

## 3. Other notes for a reviewer

This is the largest implementation milestone; its four increments are execution order inside the milestone, not permission to stop after a catalog scaffold.
Every frozen editing capability must be exercised; replacing coverage with a few hand-picked filters changes the contract.
Positive controls matter because native MLT may silently ignore unknown properties.
Synthetic caption/mask fixtures are valid for compositing algebra, not for ASR/SAM quality.
Check source-byte stability, generation fencing and publication reconciliation directly rather than trusting a process exit or filename.

Review the exact candidate and the stated milestone scope, not a fluent implementation summary.
If given only a patch or a subset of files, imports may refer to earlier milestone code outside the review bundle.
Request the referenced contracts, implementation and relevant evidence before deciding; missing context is neither automatic failure nor proof of correctness.
Do not treat passing mocks, successful native setters, saved XML, a compiled design, or a zero process exit as proof of media/provider behavior.
The implementing AI's report is evidence to inspect, not an independent approval.
