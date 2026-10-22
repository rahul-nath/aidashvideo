# Milestone 7: Prepare and obtain human review of the exact candidate

## 1. Task description

AiDashVideo is a standalone local video editor controlled through conversation, with immutable source media and a versioned project as its authority.
MLT evaluates the timeline and supplies playback/export; FFmpeg supplies explicit media jobs; timed speech and a separately qualified SAM 3.1 MLX adapter supply analysis.
Work only in this repository, using one AI implementer and the files produced by earlier milestones; do not require AiDashOS, private modules, a hidden daemon or previous chat history.
Inspect existing work first, preserve unrelated changes, and implement only this milestone.
Do not download/install packages or models, access new credentials, transfer media/prompts, spend, change shared services, overwrite originals, publish, push or merge without the operator's separate explicit authorization.
Use installed tools through `uv run --offline --no-sync` with automatic Python/package/model acquisition disabled; a missing tool is a named blocker, not permission to fetch it.
Reversible project edits and previews use the user's active project grant; exports additionally name the selected revision and granted new destination.

Entry: Milestone 6 has a complete candidate-bound verification bundle.
Prepare a concise human review package and obtain the operator's explicit decision about the exact candidate and verified scope.
This milestone is a review gate; the AI cannot provide its own operator approval or infer approval from silence.

Create `docs/review/candidate.md` containing:

- Exact implementation/test/configuration/descriptor scope, plus links to the verification evidence index and manifests.
- Requirement-by-requirement results, complete MLT coverage, core/timed speech/real chat/SAM 3.1 MLX readiness and all known limitations.
- Actual tool/model/font/plugin license/provenance and acquisition/host/resource manifest, distinguishing installed/qualified state from a proposed setup.
- Evidence that originals/history survive, authority cannot be manufactured by a client/model, stable sources and job fences hold, and exports match the selected revision.
- Inspected media examples, timing/quality/performance results, correction/unavailable UI and reproduction instructions.
- Recovery, migration, rollback, installation interruption and operator controls, with explicit v1 versus future scope.

Ask the operator to inspect the concrete package and record one of Pending, ChangesRequested or Approved, bound to the candidate digest and scope.
An approval names what was reviewed and its limits; it does not grant downloads, uploads, redistribution, deployment, publication or production activation.
If changes are requested, return to the owning implementation milestone, update evidence through Milestone 6 and present the changed candidate for review.
Any changed implementation or test/runtime/fixture contract requires impact review and fresh approval; do not transfer approval by branch name.
Keep a verbatim or linked operator decision record in `docs/review/operator-decision.md` with provenance; the AI may transcribe an actual decision, not invent the speaker or approval.

## 2. How to judge completion

- The human can locate and reproduce the exact reviewed implementation and evidence without conversation history.
- The review includes source preservation, authority/replay, cancellation/reconciliation, media quality, all package/model readiness, licenses/resources and lifecycle limits.
- Required readiness gaps are not hidden behind a general success statement.
- A real explicit operator approval exists for the exact candidate digest and declared scope, with provenance; pending/changes requested is not a pass.
- No unreviewed source change is introduced after the approval, and any permitted documentation-only additions are distinguished from the approved implementation scope.

Exit state: Milestone 8 may assemble the approved local delivery.
Without the human decision, finish the review preparation and report BLOCKED awaiting that specific approval.

Retain a source-bound milestone report in `docs/evidence/milestone-7.md` and its referenced local artifacts.
Record the exact commands and exit status, expected and observed results, tool/model/fixture identities, failures, retained artifacts, cleanup and remaining blockers.
For media/provider milestones, include inspectable output and visual/auditory findings, not just test counts.
Keep sensitive fixtures and large media out of Git; reference their operator-controlled local evidence store and record consent/availability.
Use `PASS` only when this milestone's required completion criteria have actual evidence; otherwise report `BLOCKED` or `FAIL` and the smallest missing proof.
Separate core, complete packaged MLT, timed speech and SAM 3.1 MLX readiness rather than collapsing them into one success flag.
Stop before the next milestone.

## 3. Other notes for a reviewer

This is the intentional human checkpoint in an otherwise single-AI implementation sequence.
It preserves the original CGD's operator-review milestone outside AiDashOS without pretending a private ledger or another AI agent is required.
The AI can collect and explain evidence but cannot be both the implementation author and the approving operator.
Reviewing a partial useful build is possible, but it cannot satisfy this full-v1 chain while required capabilities remain unqualified.

Review the exact candidate and the stated milestone scope, not a fluent implementation summary.
If given only a patch or a subset of files, imports may refer to earlier milestone code outside the review bundle.
Request the referenced contracts, implementation and relevant evidence before deciding; missing context is neither automatic failure nor proof of correctness.
Do not treat passing mocks, successful native setters, saved XML, a compiled design, or a zero process exit as proof of media/provider behavior.
The implementing AI's report is evidence to inspect, not an independent approval.
