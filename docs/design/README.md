# Standalone implementation briefs

These nine briefs translate the aidashvideo CGD into sequential tasks for one AI working directly in this repository.
They are instructions to execute later, not a claim that any milestone has run.
The source CGD snapshot and every brief agree on one local SAM 3.1 MLX Metal profile, offline asset loading and durable per-object masks.
The initial repository baseline contains README, LICENSE and NOTICE, with no editor implementation.

## How to use

1. Give the AI repository access and the complete text of the next milestone file.
2. Instruct it to execute only that milestone, preserving the existing repo and the permission limits in the brief.
3. Check its completion evidence and retained artifacts against section 2 before advancing.
4. Start the next milestone using the resulting repository, including its frozen plan and earlier reports; no previous chat history is needed.
5. If a required criterion is blocked, retain the useful work and exact blocker rather than presenting the next milestone as ready.

Each brief has exactly the requested sections: task description, how to judge completion, and other notes for a reviewer.
The briefs embed the relevant product contracts and reference artifacts produced by earlier tasks inside this repository.
Do not feed only the title or this index to the implementer.
A later milestone is standalone relative to conversation/AiDashOS, not independent of the code and records created by its predecessors.

| Milestone | Entry | Result needed by the next task |
| --- | --- | --- |
| [0: Repository and contracts](milestone-0.md) | README, LICENSE, NOTICE | Runnable minimal Python repo, frozen ownership/types/profiles, commands, fixtures and verification plan |
| [1: Durable project domain](milestone-1.md) | M0 passed | Admitted revisions, identity/time algebra, semantic operations, undo, replay/concurrency and portable format |
| [2: MLT and media execution](milestone-2.md) | M1 passed | Complete packaged effects, isolated worker, local previews, safe verified media jobs and export |
| [3: Timed speech](milestone-3.md) | M2 passed | Qualified transcripts, honest timing/phrase selection, captions and speech cuts |
| [4: SAM 3.1 MLX](milestone-4.md) | M3 passed in this sequence | Qualified local text/visual selection, temporal tracking/correction, persistent masks and blur |
| [5: Chat/player integration](milestone-5.md) | M4 passed in this sequence | Real conversational workflow, player/transport, truthful asynchronous states and lifecycle |
| [6: Complete verification](milestone-6.md) | M0-M5 passed | Candidate-bound behavioral, media, provider, failure and performance evidence |
| [7: Operator review](milestone-7.md) | M6 passed | Explicit human approval of the exact candidate and scope |
| [8: Local delivery](milestone-8.md) | M7 approved | Fresh-session reproduction, format/tool contract, manifests, runbook and retained evidence |

Milestone 2 is deliberately broad because the CGD requires the entire frozen packaged MLT editing surface, not just a few filters.
Its internal increments make it reviewable without calling an incomplete engine a finished milestone.
The documents are not an MVP reduction and do not add a requirement to reproduce every Final Cut/Premiere feature.

## Execution contract

- M0 establishes the minimal repository/test bootstrap and concrete domain contracts required by M1.
- The source graph allows speech and subject work after M2 and core UI after M3 independently of subject readiness; execute this packet sequentially from M0 through M8.
- Target-local ownership contracts replace reliance on private orchestration documents; no AiDashOS runtime, WorkUnit, private ledger, hidden daemon or additional AI agent is required.
- New local admission ownership is specified in M0 and implemented/tested first within M1 before mutating consumers integrate; nonexistent owner code is not claimed as an already-qualified supplier.
- Repository evidence records and exact candidate hashes replace AiDashOS artifact transport while retaining source binding, permissions and human review.
- The AI may execute verification itself, but that is not independent human approval; M7 still requires the operator's actual decision.
- Concrete implementation interface/profile choices and real root/toolchain/test-command prerequisites are required M0 outputs; missing dependencies are recorded blockers and may require separate exact acquisition grants later.

This tests the sufficiency of these translated task packets plus the evolving repository.
It is not a blind experiment feeding an unchanged CGD directly to an AI.
Record any clarification the AI needs and the resulting contract decision in M0's plan or the owning milestone report, so gaps in these instructions remain visible.
Implementation follows the source snapshot bound by the manifest; contract changes require an explicit operator instruction and synchronized acceptance requirements.

## Scope and authority

Full v1 means core editing, all declared packaged MLT editing services/parameters, reusable timed speech, the SAM 3.1 MLX subject profile, real chat/preview integration, durable revisions and verified export/recovery.
Unavailable models do not prevent basic boot or project inspection, but required missing qualifications prevent a full-v1 completion claim.
The real QuickTime plus chosen external chat layout is V2; inpainting and DINOv3 are unavailable extension contracts.
No downloads, model installation, uploads, new spend/credentials, destructive actions, shared-service changes, push/merge, public distribution or activation are authorized merely by these briefs.
Running a milestone requires the user's instruction to run that task and any resources it needs.
Writing these documents did not execute M0 or any other milestone.

## Evidence and provenance

Every milestone writes a durable report under `docs/evidence/`; those files do not exist yet because the work has not run.
M0 creates `docs/plan/`, M7 creates `docs/review/`, and M8 supplies the delivery index/runbook.
Future file paths in the prompts are required outputs, not broken claims that those files already exist.
Keep private/large media in an operator-controlled evidence store with stable hashes and access/reproduction instructions.

The [coverage map](coverage.md) traces all source sections, invariants, milestones and verification cases to these tasks.
The [manifest](manifest.json) identifies the source CGD snapshot, target baseline, execution contract and hashes of these briefs.
This provenance is a document check, not a compiler receipt or evidence that the editor is implemented.
