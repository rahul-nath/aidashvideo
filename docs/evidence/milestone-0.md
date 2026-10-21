# Milestone 0 evidence: repository prepared, contracts frozen against the revised design (2026-10-21)

Verification below was performed by the implementing AI on the operator's target machine. It
is not an independent review and not operator approval. Base commit `f04e824` ("create a
complete gitignore") on branch `hfi/8080ec40-b2a2-4170-a952-f1a329802d44/elm`; all Milestone 0
files are uncommitted in the working tree (no commit was requested). README, LICENSE and NOTICE
are byte-identical to HEAD; `docs/milestone-6.md` (the old acceptance contract) is deleted from
the tree and replaced by [../design/milestone-6.md](../design/milestone-6.md).

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
| 7 | `uv run --offline --no-sync pyright` | 0 | 0 errors (strict, `pythonVersion` 3.12) |
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
sandbox runs CPython 3.12 (`UV_PYTHON=3.12 uv sync --locked`); code must stay 3.12-compatible
(ruff/pyright target 3.12). `scripts/make_handover_archive.sh` builds the archive
([../plan/commands.md §8](../plan/commands.md#8-milestone-1-handover-archive)).

## Retained files and hashes

Candidate scope (implementation, tests, requirements, plan; excludes this report). Scope digest
(SHA-256 of the listing below): `166711ae90ce89354ec612d986b84e2cb2d14a7035e5e7fadb53521b4a58673f`.

```text
a1fba70dc9a0b9b1f35067adb5c2324f2a6e512304de09c4ec76f3cfebf0d5dc  .gitignore
a876e0b10411037a012498b9fe18d9bc1df32ed8b722a13564dc944ddcfd9135  .python-version
19e4c0c13618eaec87e7d8a8f4fccdcbf30758629f664c67cf85d0481c0c93d8  README.md
6aadc69855b64637e34e22aea5762d8c198e90a39f0370ff97ba2b4f6989646c  docs/plan/commands.md
e12ab2a76c565a56b140aadab03de302153de2b392173bc5767e8245fa8dad7b  docs/plan/contracts.md
ddbf85a622a39933f9777967b2f7e18ca0627403fcf699d9437ae5b2103fb603  docs/plan/fixtures.md
123ffc8260545efd24f2b114491ddb6f9e79e0fad33bf1a1646b7210b4f652d1  docs/plan/implementation-plan.md
e74a8d30d38c35b12c8467fad7d7169072b2833e8d08226208a1b24d54ce11e1  docs/plan/provider-manifest.json
7c6e0de2ece0bce9a4fe63e9e07b31a073c5148d9430d823ae17755661cffba4  docs/plan/runtime-profile.json
7065bc9799c48485a19a419659b33f4752509a66c77656bf8a06555b622c3ea8  docs/plan/verification-matrix.md
b1dcf3c1c4a8dc857edb84cb04792fe2c4101c4e58221804ae8951168e3361fd  docs/toolchain.md
1658317a8744867c4db208b29169ca3da2393934fcd374df73b7fb12edc904a5  pyproject.toml
3e939b35a989d7d64939d35069489bd1c4f489ae56d9293fd8e47be027e84a99  scripts/build_frozen_toolchain.sh
84cd4d8893ee4bbedf690f4a9a1a6b827d3207b0d2783025ee514377a27c343c  scripts/build_toolchain_macos.sh
4253b7cf395b4a42b776726ccf0f3d9d9fcd4caca0ce25cd43cea62676ac99b2  scripts/generate_gp01_fixtures.sh
53d91853b89090c27e9caf53f49901fd71e0c3c65392cd46ca4e398ecfae8074  scripts/make_handover_archive.sh
75a4a6dc8ffff3a46b9e44428c074770792d3cf1f84c65e4f62e8d1138a56618  scripts/refresh_evidence_hashes.py
166d5e71fe002fde73550126863fdca6bdf6b8d08699b3b08c72bd6b3d03f3c3  scripts/verify_boot_tripwires.sh
f578c792d54478bc646479d1dd4a1f445ce6e9366e3eb474e978168b64425911  src/aidashvideo/__init__.py
9cd6d14c3ca9eaab9da50e20b91f0bb5946440e96c4cd3c9d8a05ae839c3d503  src/aidashvideo/catalog/__init__.py
cdaa589bb0d303487b101a30cedc6b0b46cd498ab91f27c70064d6cf0c0bdf17  src/aidashvideo/catalog/_mlt_probe.py
fb40b39a7c9e506ee5c47d91b747e599b0891200b684f3be8146b155f8842f6e  src/aidashvideo/catalog/_provider_probe.py
bbbbe979ed839df2b3398b0e7e7732b63df8de7e6666d93bcaf06c0315b06501  src/aidashvideo/catalog/doctor.py
fec2350d2687f1d5badaadd6039388fdd97187bd0b6100d706ddee230721085a  src/aidashvideo/catalog/ffmpeg.py
35b9ee199bf754f7e94a84915784327859583ad24c732c5861485152feecddd8  src/aidashvideo/catalog/mlt.py
bc02f4cccbc4be2c5b31d8140b518c1858bc12c87ca0af5f2839c934d24f8211  src/aidashvideo/catalog/models.py
d4cd72cf82b3799b01ad1f8e7d9292448621d6ea6094adc01b717be8e496ce2a  src/aidashvideo/catalog/offline.py
3509711b84070054bc06c0e5ca9074074c85b33c79544180b5113da04efe4f2a  src/aidashvideo/catalog/paths.py
ee90c893e0de654cafa431f8ee78f36a022358aa7763b8b21da02d611fd0dfc7  src/aidashvideo/catalog/pins.py
bdc3446fd56feafb6846dae83f272f7c81016e5ac3abab79608ca8bc65c15240  src/aidashvideo/catalog/providers.py
0967f7ec449f7ba28deb0ed7fbbe3b5ba449f1dad4ddb22d36a6091e4d0917d5  src/aidashvideo/catalog/status.py
88d5c2bda05d9b0b56a092e1305fe5183965d7d99c89ca0eb1c11b4e82a031c9  tests/boot_probe.py
af04966b8d831a675976826223c5827eb9211c101133f443caa4afb0514f53d0  tests/test_boot_isolation.py
1f42732fa03b31d7b2ebc84ac2ae3720eafb4e195acbfa24ee38fb3e3197c0e4  tests/test_catalog.py
cec4392e37d43baa52a627a48f541db0d0cf7bb6befdd1408f41acfe01fa460c  tests/test_plan_integrity.py
5dc31b84ebc19c3f739b14048ae81de1d6e7384ffdfc6272558d8ff12240f948  tests/test_toolchain_live.py
8d7db49d7d4c5c00a78815474f9531cb0fc858429af3b8daf0aa8c28e4372d47  toolchain/models.toml
8975213c1ef86b066adaecaeef02155dc885561167ae139483f96ad9a97825a3  toolchain/profiles/frozen.toml
cdfc35ee67f6d4c790576c50e1f23333596d096e49f7245f77d98f32cc162b77  toolchain/sysroot-noble-amd64.lock
850bcd976a83dd41cabc809fe66683a61f47a0bcb870fe2892bb5d2b6f64900c  uv.lock
```

Local artifacts (git-ignored; produced on and retained by this host under
`AIDASHVIDEO_VAR_DIR`; on another host they are absent and the plan-integrity test skips them,
but any that are present must still match):

```text
2d54a146591c6ca45c1cb11f81b832571933bcf7ef295db890aa4a4f50c50dbf  var/evidence/m0/doctor-target.json
64694b2e0767ec98390ccc7de779d4a7b4525113a9fc9f5b72a556bbc4472189  var/fixtures/gp01/SHA256SUMS
d2f147d8a16d29d062512c8c2d7a7bef1ff58ca590c0a67357a7339d65c873d7  var/fixtures/gp01/broll.mp4
1577dd80903c5385b8260a0b6f1803c2082983f90671de1ae74a5a0d3566173f  var/fixtures/gp01/generator-identity.txt
c8d86af5acf9e262c7d368e1319ffe71b181878eb69c3f7e57cce9565ae7ec85  var/fixtures/gp01/interview.mp4
00abf70d391f4452155d098e868653c56e277cd6237a21ed1b5af92554e43200  var/fixtures/gp01/music-loudness.txt
a22fc98733b5428116b30b6899f6612ec1734ea39d1878d76d29ed2ecba503e5  var/fixtures/gp01/music.wav
560339867fa3df6ff07048229f116b2a32537bc0b31856409b5456748bba8433  var/fixtures/gp01/probe-broll.json
83bf4251bb972357d131576f00b567f8bdaed1fe89257f74a61c6edc30048351  var/fixtures/gp01/probe-interview.json
dd018b55e27b5ddd0301390db5bd9734fc8947f230b100836d9930f612ed7aef  var/fixtures/gp01/probe-music.json
e222db174b302427b3a4264312dd8065caf9c5967d213591a7718d69d9833d62  var/fixtures/gp01/speech-window.txt
```

## Cleanup and blockers

No original was modified; no shared cache or service was changed; nothing was published,
pushed or committed. The 3.3 GB duplicate SAM 3.1 download was deleted on operator instruction;
the stale repository `.deps/` (dylibs only) was removed; the obsolete sandbox profile files were
deleted.

Remaining `Missing` items (recorded in [../plan/runtime-profile.json](../plan/runtime-profile.json)
and [../plan/provider-manifest.json](../plan/provider-manifest.json); none blocks M1):
chat model choice (before M5), word-alignment adapter (V06), title/caption font identity on the
target, operator-owned annotated footage for V06/V07/V08, GP-01 regeneration in the sandbox with
its own generator identity if M1 tests there need media.
