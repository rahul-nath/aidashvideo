# Milestone 8: Deliver a reproducible local editor and operating evidence

## 1. Task description

AiDashVideo is a standalone local video editor controlled through conversation, with immutable source media and a versioned project as its authority.
MLT evaluates the timeline and supplies playback/export; FFmpeg supplies explicit media jobs; timed speech and a separately qualified SAM 3.1 MLX adapter supply analysis.
Work only in this repository, using one AI implementer and the files produced by earlier milestones; do not require AiDashOS, private modules, a hidden daemon or previous chat history.
Inspect existing work first, preserve unrelated changes, and implement only this milestone.
Do not download/install packages or models, access new credentials, transfer media/prompts, spend, change shared services, overwrite originals, publish, push or merge without the operator's separate explicit authorization.
Use installed tools through `uv run --offline --no-sync` with automatic Python/package/model acquisition disabled; a missing tool is a named blocker, not permission to fetch it.
Reversible project edits and previews use the user's active project grant; exports additionally name the selected revision and granted new destination.

Entry: Milestone 7 contains explicit approval of the exact candidate from Milestone 6.
Deliver that local editor, project format and reproducible operating package in this repository without publishing, deploying or activating production services.
Do not introduce new product features after review.
Any implementation change returns through affected verification and approval.

Provide a durable delivery index and these materials:

- Versioned project/operation schema, local tool protocol, catalog/descriptor identity and compatibility contract.
- Approved implementation identity and evidence manifest, scoped operator decision and accurate per-capability readiness/limits.
- A reproducible local GP-01 fixture project with source/probe hashes, retained preview/export/mask/transcript evidence and media access/consent instructions.
- Exact pinned toolchain/plugin/font/model/checkpoint/conversion/backend manifests, license notices and separate acquisition/host/grant requirements.
- Operator runbook for permitted setup, launch, import, chat editing, selection/correction, preview/transport, explicit export, cancel and shutdown.
- Missing-dependency and denied-egress behavior, quotas/timeouts, model residency, cache locations, cleanup ownership and troubleshooting.
- Restart/reconciliation, relink, portable import, immutable schema migration, compatible rollback and recovery procedures.
- Explicit non-goals and V2 roadmap: the chosen external chat UI on the left and actual QuickTime on the right with revision-safe updates, without counting it as delivered v1.

Use a fresh session with only the repository and granted local artifacts, no private AiDashOS checkout, prior AI memory or hidden services.
Reopen the fixture project, inspect source/revision/provider evidence and repeat the qualified workflow and key recovery steps.
No unapproved dependency/model fetch, hosted inference or fixture transfer may be used to make reproduction appear complete.
For a required missing tool/model, report the precise blocked reproduction step instead of silently using a different profile.
Preserve the approved implementation identity; adding delivery prose/evidence does not retroactively approve a different runtime.
Update the root README with actual verified status, startup/documentation links, limits and the distinction between local readiness and a public release.

## 2. How to judge completion

- All delivery links and hashes resolve to durable local files or explicitly granted retained artifacts, not temporary folders or chat messages.
- A fresh session reproduces GP-01, full-decode/export checks, save/reopen and the documented recovery path using the approved candidate and exact qualified profiles.
- Project format/tool protocol, fixture, manifests, evidence, operator approval and runbook are complete and agree on versions, scope and readiness.
- Full v1 is claimed only if the complete MLT package, timed speech and any promised alignment, real chat integration and the SAM 3.1 MLX profile have the required behavior evidence.
- Missing optional DINOv3/inpainting remain explicitly unavailable, and V2 QuickTime/multiclient/interchange/template/multicam work is not advertised as finished.
- Originals/history are intact, cleanup is ownership-limited, no new ungranted external action occurred, and the delivered implementation matches the approved digest.
- Record actual fresh-session commands/observations and any reproduction limitation in `docs/evidence/milestone-8.md`, with a delivery record linking all prior milestone reports.

Exit state: The requested local v1 implementation sequence is complete and independently understandable from the repository and granted artifacts.
Public release, remote hosting and production activation remain separate future decisions, not hidden final steps.

Retain a source-bound milestone report in `docs/evidence/milestone-8.md` and its referenced local artifacts.
Record the exact commands and exit status, expected and observed results, tool/model/fixture identities, failures, retained artifacts, cleanup and remaining blockers.
For media/provider milestones, include inspectable output and visual/auditory findings, not just test counts.
Keep sensitive fixtures and large media out of Git; reference their operator-controlled local evidence store and record consent/availability.
Use `PASS` only when this milestone's required completion criteria have actual evidence; otherwise report `BLOCKED` or `FAIL` and the smallest missing proof.
Separate core, complete packaged MLT, timed speech and SAM 3.1 MLX readiness rather than collapsing them into one success flag.
Stop before the next milestone.

## 3. Other notes for a reviewer

The final check is whether another session can use and verify the editor without access to this conversation, not whether a release checklist exists.
Do not equate delivery documentation or a Git commit with a running, qualified feature.
Keep large or private evidence outside the public repository when necessary, but record stable authorized locations, hashes and reproduction/access instructions.
This milestone cannot repair missing earlier approval/provider proof by relabeling the product an MVP.

Review the exact candidate and the stated milestone scope, not a fluent implementation summary.
If given only a patch or a subset of files, imports may refer to earlier milestone code outside the review bundle.
Request the referenced contracts, implementation and relevant evidence before deciding; missing context is neither automatic failure nor proof of correctness.
Do not treat passing mocks, successful native setters, saved XML, a compiled design, or a zero process exit as proof of media/provider behavior.
The implementing AI's report is evidence to inspect, not an independent approval.
