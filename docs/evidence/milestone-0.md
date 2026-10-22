# Milestone 0 evidence: repository prepared, contracts frozen against the revised design (2026-10-21)

Verification below was performed by the implementing AI on the operator's target machine. It
is not an independent review and not operator approval. `docs/milestone-6.md` (the old
acceptance contract) is replaced by [../design/milestone-6.md](../design/milestone-6.md).

Scope source: the operator's revised briefs in [../design/](../design/README.md) (manifest
`docs/design/manifest.json`, created 2026-10-12, placed in the repository 2026-10-20). Earlier
records: [milestone-0-sandbox-2026-10-18.md](milestone-0-sandbox-2026-10-18.md) (Linux sandbox
session that produced the first plan) and
[target-m1-install-2026-10-20.md](target-m1-install-2026-10-20.md) (toolchain and model
installation on this host).

**Status: PASS for Milestone 0 as specified in [../design/milestone-0.md](../design/milestone-0.md)**,
with the open items listed at the end recorded as `Missing` (none blocks Milestone 1).

## Status by area (readiness words from [../plan/contracts.md §9](../plan/contracts.md#9-readiness-words))

| Area | Readiness (target host) | Evidence / smallest missing proof |
| --- | --- | --- |
| Repository, plan, boot isolation (this milestone) | done | 33 tests pass (18 catalog/boot, 10 plan, 5 live); tripwire proof 4/4; plan-integrity checks below |
| Core (Python 3.14.7, uv 0.12.11, FFmpeg 9.0.2 + whisper, MLT 7.42.0 + `mlt7`) | **Verified** | `aidashvideo-doctor` exit 0 with a real FFmpeg round trip and a decoded MLT render |
| Full MLT package inventory | **Verified (inventory recorded; descriptors are M2 work)** | 22 modules, `melt -query` 43/558/54/11/310; digest `4deb9c31…6e36b` observed, not pinned (D11) |
| Timed speech (FFmpeg `whisper` filter, Metal) | **Verified (installed; not quality-qualified)** | synthesized phrase transcribed; V05/V06 open |
| SAM 3.1 MLX (mlx-vlm 0.7.8, Metal) | **Verified (installed; not quality-qualified)** | offline load + synthetic-subject segmentation on Metal; V08 open |
| Chat model | Missing | operator names the local model before M5 |
| Word alignment | Missing | deferred (D4) |

## What changed in this re-plan (design 2026-10-20 → plan 2026-10-21)

- One mask profile. `SAM 3 (torch/transformers)` is gone from the plan, the code (`providers`,
  `_provider_probe`), the manifest (`toolchain/models.toml`), the extras (`pyproject.toml`,
  `uv.lock`) and the readiness rows (now four: core, full-mlt-package, timed-speech, sam31-mlx).
- Contracts rewritten to the brief's closed variants (`ApplyResult`, `Transcript`, `MaskSpan`,
  `MaskRequest = SAM31MLXRequest`, `MaskSelection`, `InstancePolicy`, `SubjectAssets`,
  `PreviewState`, `PreviewBinding`, `MLTService`, `MLTParameter`, `Capability`,
  `RenderOutcome`), the operation batch fields, the required and descriptor-bound operations,
  the visual order, alpha/chroma rules, the stdio chat tool protocol, the explicit CLIP tokenizer
  binding and the resource limits for the 16 GB host.
- Milestone numbering follows the briefs (M3 speech, M4 SAM 3.1 MLX, M5 chat/player, M6
  verification, M7 review, M8 delivery); the matrix is regenerated from the new M6 with every
  expected-result cell verbatim.
- Version/capability requirements stay pinned; build digests are observed facts (D11). The
  obsolete 7.22.0 sandbox profile, its archive lock and bootstrap scripts were removed; the
  Linux sandbox uses the same frozen identities through `scripts/build_frozen_toolchain.sh`.
- Toolchain and models live in `~/.local/share/aidashvideo/deps`; fixtures and evidence in
  `~/.local/share/aidashvideo/var` (`AIDASHVIDEO_DEPS_DIR` / `AIDASHVIDEO_VAR_DIR`), because
  this checkout proved ephemeral for ignored files (D12).

## Environment (target)

macOS 27.0.1 arm64, Apple M1 Pro (8 cores), 16 GiB unified memory. uv 0.12.11; uv-managed
CPython 3.14.7 (`python-preference = "managed"`, downloads disabled). Homebrew build libraries
as listed in [target-m1-install-2026-10-20.md](target-m1-install-2026-10-20.md). Network was
used only under the operator's grant of 2026-10-20 (toolchain sources, dev wheels); no model
was downloaded by repository code.

## Acceptance commands (repository root; exit codes reproduce)

| # | Command | Exit | Observed |
| --- | --- | --- | --- |
| 1 | `uv run --offline --no-sync pytest -q -rA -p no:cacheprovider --strict-markers` | 0 | 33 passed, 0 skipped, 0 failed; ids include `test_boot_import_isolation`, `test_doctor_with_nothing_installed_reports_missing_and_exits_1`, `test_four_separate_readiness_rows_agree_across_files`, `test_sam31_mlx_segments_synthetic_subject_offline_on_metal` |
| 2 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m plan` | 0 | 10 plan-integrity tests: files, JSON, links, readiness words, four rows, Verified needs target-host evidence, open-item placement, ownership block identity, closed variants, matrix coverage verbatim from `docs/design/milestone-6.md`, evidence hashes |
| 3 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m live` | 0 | FFmpeg pins and round trip; whisper transcription of the synthesized phrase; MLT 30-frame render decoded; SAM 3.1 segmentation on Metal (score 0.96, box within 20 px, 5.4 GiB peak); Hub egress blocked |
| 4 | `scripts/verify_boot_tripwires.sh` | 0 | control passes; thread/socket/subprocess/fake-ML-module mutations each make the boot test fail (4/4) |
| 5 | `uv run --offline --no-sync python -I -X importtime -c "import aidashvideo" 2>&1 \| grep -ciE "mlt\|mlx\|torch\|whisper\|sam\|numpy\|socket"` | 1 (grep: no match) | prints `0` |
| 6 | `uv run --offline --no-sync ruff check .` / `ruff format --check .` | 0 / 0 | clean (`.deps`, `var` excluded) |
| 7 | `uv run --offline --no-sync pyright` | 0 | 0 errors (strict) |
| 8 | `uv run --offline --no-sync aidashvideo-doctor --json` | 0 | host, ffmpeg, mlt, sam31-mlx, timed-speech and the three admitted assets `Verified`; `core_verified: true` |
| 9 | `uv run --offline --no-sync aidashvideo-models status` | 0 | `sam31-mlx`, `clip-tokenizer`, `whisper-ggml-model` Verified |
| 10 | `uv lock --check --offline` | 0 | lock current after removing the torch extra (82 packages, universal) |
| 11 | `scripts/generate_gp01_fixtures.sh` (with `AIDASHVIDEO_VAR_DIR=~/.local/share/aidashvideo/var`) | 0 | three GP-01 files written with probes, hashes and generator identity (below) |
| 12 | `git check-ignore -q .deps/x var/fixtures/gp01/interview.mp4 whisper.cpp-1.9.5.tar` | 0 | toolchain, fixtures and source archives are ignored; no deliverable is ignored |

## Identities

Toolchain and model identities (unchanged since the 2026-10-21 rebuild) are listed in
[target-m1-install-2026-10-20.md](target-m1-install-2026-10-20.md): `ffmpeg` sha256
`d9a15642…830f89`, `melt` `1ea872a9…e82b99`, `_mlt7.so` `df26afb3…4bd89e`, SAM 3.1 snapshot
`97ae6308acc10e6308529f432c71ebfcd78ac65d`, `ggml-base.en.bin` `a03779c8…c6d002`.

GP-01 fixtures generated on this host (`~/.local/share/aidashvideo/var/fixtures/gp01`; FFmpeg
9.0.2 frozen build, macOS `say` 27.0.1; recipe `scripts/generate_gp01_fixtures.sh`):

| File | SHA-256 | Probe |
| --- | --- | --- |
| `interview.mp4` | `c8d86af5acf9e262c7d368e1319ffe71b181878eb69c3f7e57cce9565ae7ec85` | 12.000000 s; h264 yuv420p 1920x1080 30/1, bt709/bt709/bt709 tv; aac 48 kHz stereo; v/a start 0; speech window (silencedetect -40 dB, 0.3 s) **2.015 s to 3.105 s** |
| `broll.mp4` | `d2f147d8a16d29d062512c8c2d7a7bef1ff58ca590c0a67357a7339d65c873d7` | 4.000000 s; h264 yuv420p 1920x1080 30/1, bt709 tv; no audio |
| `music.wav` | `a22fc98733b5428116b30b6899f6612ec1734ea39d1878d76d29ed2ecba503e5` | 20.000000 s; pcm_s16le 48 kHz stereo; integrated loudness -15.7 LUFS |

## Boot isolation design (I10, V14)

`tests/test_boot_isolation.py` spawns `python -I tests/boot_probe.py`. The probe installs, before
`import aidashvideo`, a `sys.meta_path` finder that records every import and refuses a denylist
(mlx, mlx_vlm, numpy, mlt, transformers, torch, sam3*, whisper, socket, subprocess, threading,
...); `_thread.start_new_thread` and `os.fork/posix_spawn/exec*/system/popen/spawn*` are replaced
by raising stubs; socket import is denied. After the import it asserts the set of newly loaded
modules is exactly `{"aidashvideo"}` and that no forbidden name is in `sys.modules`.
`scripts/verify_boot_tripwires.sh` copies the tree, creates an offline venv, and shows the test
fails for each of the four mutations.

## Handover to the Linux sandbox for Milestone 1

What the sandbox can do for [../design/milestone-1.md](../design/milestone-1.md): everything.
M1 is the durable project domain (ledger admission, CAS store, timing/geometry algebra,
operations, undo, portable snapshot/import) and explicitly needs no MLT rendering or model
inference. Probe receipts need an `ffprobe`; the sandbox may use its installed FFmpeg (identity
recorded in every `ProbeReceipt`) or build the frozen 9.0.2 with
`scripts/build_frozen_toolchain.sh`. What it cannot do: anything under `sam31-mlx` (darwin-only;
no CPU fallback exists), any `Verified` claim for the target host, the M6 measurements. The
sandbox runs the same uv-managed CPython 3.14.7 (`uv sync --locked`); see the sandbox
re-baseline section below. `scripts/make_handover_archive.sh` builds the archive
([../plan/commands.md §8](../plan/commands.md#8-milestone-1-handover-archive)).

## Retained files

The deliverable and artifact listing with hashes that this section used to carry was dropped on
operator instruction (2026-10-21): reports no longer bind a candidate commit or require hash
recomputation. The handover manifest written at archive time (`handover/SHA256SUMS`) remains the
record of the files as shipped.

## Sandbox re-baseline (Linux, 2026-10-22, operator instructions)

Performed in the Linux sandbox after unpacking the 2026-10-21 handover archive (manifest
`handover/SHA256SUMS` verified, all OK) on the operator's instructions:

| Instruction | Done |
| --- | --- |
| add `hypothesis` to the dev group and relock | `hypothesis==6.170.2` in `[dependency-groups].dev`; `uv.lock` relocked (84 packages, `requires-python == 3.14.*`) |
| upgrade everything to Python 3.14 | `requires-python = ">=3.14,<3.15"`, ruff `py314`, pyright `pythonVersion = "3.14"`; the sandbox uses its uv-managed CPython 3.14.7 (`/opt/uv-python`); `scripts/build_frozen_toolchain.sh python` builds 3.14.7 from the archived source as a fallback on hosts without one; `mlt7` bindings rebuilt for 3.14.7 |
| revise the README | rewritten for the current state (status, layout, setup, toolchain, licensing) |
| drop the candidate-commit / "commit if instructed" / hash-recompute requirements | removed from every brief in `docs/design/` (manifest hashes refreshed), the plan, the evidence reports, the handover script; `tests/test_plan_integrity.py::test_evidence_hashes_recompute` and `scripts/refresh_evidence_hashes.py` deleted |
| frei0r 3.6.0 from the supplied source | built into the prefix (163 plugins; content digest pinned in the build script); MLT 7.42.0 rebuilt with the target's module set (movit/jackrack/ladspa off): 22 modules |

Toolchain location: `~/.local/share/aidashvideo/deps` (the repo's `.deps` is a symlink to it;
`.gitignore` now ignores the symlink as well as the directory).

| # | Command (sandbox) | Exit | Observed |
| --- | --- | --- | --- |
| 1 | `uv sync --locked` (once, online, under the operator's instruction to relock) | 0 | CPython 3.14.7, hypothesis 6.170.2 |
| 2 | `uv run --offline --no-sync pytest -q -rA -p no:cacheprovider --strict-markers` | 0 | 30 passed, 2 skipped (SAM 3.1 MLX is macOS-only; `huggingface_hub` is not in the sandbox env); the whisper live test now synthesizes with `flite` when `say` is absent and transcribes "golden" through the frozen FFmpeg 9.0.2 |
| 3 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m plan` | 0 | 10 plan-integrity tests |
| 4 | `uv run --offline --no-sync ruff check .` / `ruff format --check .` / `pyright` | 0 / 0 / 0 | clean (py314 targets) |
| 5 | `scripts/verify_boot_tripwires.sh` | 0 | 4/4 mutations detected |
| 6 | `uv run --offline --no-sync python -I -X importtime -c "import aidashvideo" 2>&1 \| grep -ciE "mlt\|mlx\|torch\|whisper\|sam\|numpy\|socket"` | 1 (no match) | prints `0` |
| 7 | `uv run --offline --no-sync aidashvideo-doctor --no-providers` | 0 | ffmpeg 9.0.2 `Verified`, mlt 7.42.0 `Verified` (22 modules, catalog digest `9671b6c7…c1e` observed; target `4deb9c31…36b`), host `Conflicting` (Linux, not the Mac), whisper model `Verified`, SAM 3.1 assets `Missing` |
| 8 | `uv lock --check --offline` | 0 | lock current |

Sandbox observations never count as target-host evidence; readiness rows in the plan are
unchanged.

## Cleanup and blockers

No original was modified; no shared cache or service was changed; nothing was published
or pushed. The 3.3 GB duplicate SAM 3.1 download was deleted on operator instruction;
the stale repository `.deps/` (dylibs only) was removed; the obsolete sandbox profile files were
deleted.

Remaining `Missing` items (recorded in [../plan/runtime-profile.json](../plan/runtime-profile.json)
and [../plan/provider-manifest.json](../plan/provider-manifest.json); none blocks M1):
chat model choice (before M5), word-alignment adapter (V06), title/caption font identity on the
target, operator-owned annotated footage for V06/V07/V08, GP-01 regeneration in the sandbox with
its own generator identity if M1 tests there need media.
