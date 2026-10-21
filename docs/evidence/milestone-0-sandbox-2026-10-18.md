# Milestone 0 evidence (Linux sandbox session, 2026-10-15 to 2026-10-18): repository prepared, first contracts frozen

> Historical record of the sandbox session that produced the first plan. Superseded by
> [milestone-0.md](milestone-0.md) (target host, revised design, 2026-10-21). The hash listings
> below describe the deliverables **as they were at that freeze**; several files have since been
> revised or removed (torch extra, dev-sandbox-linux profile, digest pins) and are not expected to
> recompute. Sandbox observations never count as target-host evidence.

Verification below was performed by the implementing AI. It is not an independent review
and not operator approval. Base commit `7af91bc2f25e10314ef5e56bcb6f1f3096b2ed38` ("baseline"); all Milestone 0 files are
uncommitted in the working tree (no commit was requested). The `__MACOSX/` zip artefacts were
removed from the index (`git rm`); README, LICENSE and NOTICE are byte-identical to HEAD.

## Status by area (readiness words from [../plan/contracts.md §9](../plan/contracts.md#9-readiness-words))

| Area | Readiness (target host) | Evidence / smallest missing proof |
| --- | --- | --- |
| Repo, plan, boot isolation (this milestone) | done | tests, tripwire proof and plan-integrity checks below |
| Core (Python 3.14, uv, FFmpeg 9.0.2+whisper, MLT 7.42.0) | Missing (target) / **Verified in the sandbox at the frozen identities** | no command has been run on the Mac; the sandbox built FFmpeg 9.0.2 `--enable-whisper` and MLT 7.42.0 from source and the doctor reports core `Verified` (host row `Conflicting`: Linux, Python 3.12) |
| Full MLT package inventory (7.42.0) | Missing (target) / observed in the sandbox | 25 modules, `melt -query` 42/544/42/13/282 (producers/filters/transitions/consumers/links), catalogue digest `eab7421a…b8e0` pinned; OpenCV module off; frei0r 1.8.0 vs planned 3.6.0 is `Conflicting` |
| Timed speech (FFmpeg `whisper` filter) | Missing (target) / **Verified in the sandbox** (not quality-qualified) | whisper filter present, `ggml-base.en.bin` admitted; GP-01 phrase transcribed with queue-quantised segment timing (below) |
| SAM 3 (torch, transformers) | Missing | `facebook/sam3` weights; code path exercised on the sandbox with random weights |
| SAM 3.1 (MLX) | Missing | implementation resolved from the operator-supplied model card (mlx-vlm 0.7.8, `mlx_vlm.models.sam3_1`); no target-host run yet |

## Environment (sandbox)

Linux 6.18.44 x86_64, Ubuntu 24.04.3, glibc 2.39, 4 vCPU Intel Xeon @ 2.60 GHz, 15 GiB RAM,
no GPU, no root. Reachable: pypi.org, files.pythonhosted.org, archive.ubuntu.com,
deb.debian.org, registry.npmjs.org. Unreachable: github.com, huggingface.co, download.pytorch.org.
CPython 3.12.3 (system), uv 0.9.10. System FFmpeg `7:6.1.1-3ubuntu5` is preinstalled in the
image at `/usr/bin/ffmpeg` (it is not the frozen identity).

## Acceptance commands (all from the repository root; exit codes reproduce)

| # | Command | Exit | Observed |
| --- | --- | --- | --- |
| 1 | `uv run --offline --no-sync pytest -q -rA -p no:cacheprovider --strict-markers` | 0 | 28 passed, 0 skipped, 0 failed; ids include `test_boot_import_isolation` (boot) and `test_doctor_with_nothing_installed_reports_missing_and_exits_1` |
| 2 | `git rev-parse HEAD && git status --porcelain && uv --version && command -v ffmpeg melt pyright; echo "exit=$?"` | prints `exit=0` | `command -v` returns 0 when *any* name resolves: the image's system `/usr/bin/ffmpeg` 6.1.1 resolves; `command -v melt` and `command -v pyright` each exit 1. The plan records ffmpeg, melt and pyright as `Missing` (tool_readiness), never `Verified` |
| 3 | `scripts/verify_boot_tripwires.sh` | 0 | control passes; mutations thread/socket/subprocess/fake-torch each make the test fail (4/4) |
| 4 | `uv run --offline --no-sync python -I -X importtime -c "import aidashvideo" 2>&1 \| grep -ciE "mlt\|torch\|whisper\|sam\|numpy\|socket"` | 1 (grep: no match) | prints `0` |
| 5 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m plan` | 0 | 11 plan-integrity tests: files, JSON, links, readiness words, five rows, open-item placement, ownership block identity, matrix coverage, evidence hashes |
| 6 | `uv run --offline --no-sync ruff check .` / `ruff format --check .` | 0 / 0 | clean |
| 7 | `uv run --offline --no-sync pyright` | 0 | 0 errors (strict) |
| 8 | `uv run --offline --no-sync aidashvideo-doctor --json` | 0 | frozen profile: ffmpeg 9.0.2 and mlt 7.42.0 `Verified` (real round trip / render + full decode), timed-speech `Verified`, host `Conflicting` (not the Mac), SAM rows `Missing` ([var/evidence/milestone-0/doctor-frozen.json](../../var/evidence/milestone-0/doctor-frozen.json)) |
| 9 | `AIDASHVIDEO_PROFILE=dev-sandbox-linux uv run --offline --no-sync aidashvideo-doctor --json` | 0 | observed sandbox profile: core `Verified` (FFmpeg 6.1.1 round trip, MLT 7.22.0 render + full decode); providers `Missing` |
| 10 | `uv lock --check --offline` | 0 | lock current (70 packages, universal: linux x86_64 + macOS arm64 wheels) |
| 11 | `git check-ignore -q var/fixtures/gp01/interview.mp4 .deps/models/hf-hub/x var/evidence/m6/V01/x` | 0 | fixture, model and evidence-store paths are ignored; no deliverable is ignored |
| 12 | `scripts/build_frozen_toolchain.sh` (stages stamped; offline re-run) | 0 | whisper.cpp 1.9.5, FFmpeg 9.0.2 (+whisper), MLT 7.42.0 present in `.deps/frozen` |
| 13 | `.deps/frozen/bin/ffmpeg -hide_banner -filters \| grep -c ' whisper '` | 0 | prints `1` |
| 14 | `.deps/frozen/bin/melt -version` | 0 | `melt 7.42.0` |
| 15 | `uv run --offline --no-sync aidashvideo-models status` | 0 | `whisper-ggml-model` Verified; `sam3-hf`, `sam31-mlx` Missing |

Command 4 is quoted with escaped pipes for the table; run it as written in
[../plan/commands.md §2](../plan/commands.md#2-boot-isolation-i10-v14).

## Frozen toolchain build in the sandbox (operator uploads of 2026-10-18)

Inputs: `whisper.cpp-1.9.5.tar` (`a2e9fd8d…e4c3`), `mlt-7.42.0.tar` (`94c219b2…0ed2`),
`ggml-base.en.bin` (`a03779c8…f002`), FFmpeg `ffmpeg_9.0.2.orig.tar.xz` from the Debian archive
(`8c385028…002e`), and 166 hash-pinned Ubuntu noble header/tool archives
(`toolchain/sysroot-noble-amd64.lock`) extracted rootlessly into `.deps/sysroot`. Build recipe:
`scripts/build_frozen_toolchain.sh`; output `.deps/frozen` (git-ignored).

| Component | Result |
| --- | --- |
| whisper.cpp 1.9.5 (CPU, AVX2) | built; `whisper-cli` transcribes the GP-01 fixture as "Hello Golden Paths!" in one segment `0.000 → 7.000` |
| FFmpeg 9.0.2 | built with `--enable-gpl --enable-libx264 --enable-libass --enable-libfreetype --enable-libfontconfig --enable-libharfbuzz --enable-libfribidi --enable-libvorbis --enable-whisper`; `ffmpeg` sha256 `b46b0fd5…7757`; capability digest `175d712d…2a83` pinned in `toolchain/profiles/frozen.toml` |
| FFmpeg `whisper` filter on GP-01 | `queue=1`: `[1962,2962] "Hello, Golden."` `[2943,3443] "path."`; `queue=3`: `[0,3000] "Hello, Golden."` `[2986,3486] "paths."`; ground truth 2.196-3.256 s. Timing is quantised to the queue window and the text changes with it: segment-only evidence, no word precision (V05/V06). Files: `whisper_filter_queue1.json`, `whisper_filter_queue3.json` |
| MLT 7.42.0 | built against that FFmpeg; 25 modules (`avformat core decklink frei0r gdk jackrack kdenlive ladspa movit normalize oldfilm openfx placebo plus plusgpl qt6 resample rtaudio rubberband sdl2 sox vidstab vorbis xine xml`); `melt` sha256 `a2b2e148…bd4c`; Python bindings `mlt7` for CPython 3.12; catalogue digest `eab7421a…b8e0` pinned; OpenCV/glaxnimate/ndi/spatialaudio/rnnoise modules off |
| MLT render on GP-01 | interview `[60,179]` + `avfilter.boxblur` for the first 60 frames + Qt6 `dynamictext` title (headless, `QT_QPA_PLATFORM=offscreen`) + music: 120 frames 1920x1080@30 and 48 kHz stereo decoded by ffprobe 9.0.2; frame at 0.5 s blurred, at 3.0 s sharp, title legible (implementer inspection; `mlt742_frame_0.5s.png`, `mlt742_frame_3.0s.png`) |
| Known gaps | frei0r plugins are Ubuntu's 1.8.0 (plan pins 3.6.0; source unreachable) → `Conflicting`; bindings are for 3.12, the target needs 3.14; no Metal here |

## Boot isolation design (criterion 3)

`tests/test_boot_isolation.py` spawns `python -I tests/boot_probe.py`. The probe installs, before
`import aidashvideo`: a `sys.meta_path` finder that records every import and refuses a denylist
(torch, numpy, mlt, transformers, mlx, sam3*, whisper, socket, subprocess, threading, ...);
`_thread.start_new_thread` and `os.fork/posix_spawn/exec*/system/popen/spawn*` replaced by
raising stubs; socket import denied. After the import it asserts the set of newly loaded modules
is exactly `{"aidashvideo"}` and that no forbidden name is in `sys.modules` (this also catches
modules injected without an import). `scripts/verify_boot_tripwires.sh` copies the tree, creates an
offline venv, and shows the test fails for each of the four mutations.

## Sandbox installation evidence (observed; development profile only)

Retained from the first session of this task (report folded into this file):

- Rootless MLT 7.22.0 from 77 hash-pinned Ubuntu archives; 297 ELF RUNPATHs rewritten; all 25
  modules, `melt`, bindings and 136 frei0r plugins resolve; catalogue 44/602/42/17/350
  (producers/filters/transitions/consumers/links), digest `c80f52aa…937d`.
- FFmpeg 6.1.1: 1 s 1080p30 H.264 + AAC round trip decodes to exactly 30 frames; capability
  digest `d327484e…0231`.
- MLT on real media: `avfilter.boxblur` with `in=30 out=59` plus `frei0r.glow` on a synthetic
  clip; full decode clean; frame at 0.5 s sharp and at 1.5 s blurred (inspected by the
  implementer, not a human reviewer); artifacts under `var/evidence/sandbox-install-2026-10-15/`.
- SAM 3 via transformers 5.19.0, offline, CPU, random weights: `Sam3VideoModel` 859.9M params;
  `Sam3TrackerVideoModel` 465.8M params propagated a point prompt over 3 frames at 1008² in
  ≈19 s/frame with 4.1 GB peak RSS. Plumbing only; no quality or speed claim.
- Official `sam3` 0.1.4 PyPI package fails to build on CPU (`device="cuda"` hard-coded,
  ≈40 sites) and was dropped (decision D6). EdgeTAM was dropped by operator decision (D5).

## GP-01 fixtures (synthetic, generated here; see [../plan/fixtures.md](../plan/fixtures.md))

Generated by `var/fixtures/gp01/generate.sh` with FFmpeg 6.1.1-3ubuntu5, twice, with identical
hashes. Speech "hello golden path" measured at 2.196-3.256 s; music -19.0 LUFS integrated.

## Retained files and hashes

Candidate scope (implementation, tests, pins, plan; excludes this report). Scope digest
(SHA-256 of the listing below): `7d1d5498e438f1ecc11032fbdb183bcf68363d5760b8e66bc2c1914975876234`.

```text
a1fba70dc9a0b9b1f35067adb5c2324f2a6e512304de09c4ec76f3cfebf0d5dc  .gitignore
a876e0b10411037a012498b9fe18d9bc1df32ed8b722a13564dc944ddcfd9135  .python-version
a1f1db74a417f34bc1b43455d29d87112f9d752aefafeff84ce12bf7614cb7c4  docs/plan/commands.md
21e71d69e17b435c4a368023400c2008b30d81ecdb9acb6149b51c165c7db36b  docs/plan/contracts.md
c0ff552c9f80a08016956409a8485ded7c8ebbb0f320d8b442879a148f06336b  docs/plan/fixtures.md
a6ace62641fedbb186433a9b4cd0770d0bf27069390efc0e8e518b38b6eaf5f2  docs/plan/implementation-plan.md
687c3627623367c7137002fd71f4a7451dacd2cee66eff5fe1959a25364cfc07  docs/plan/provider-manifest.json
9d00393e72b71585b9ec582cafc40fa45563987ea17d5e22b5bb14e66687934d  docs/plan/runtime-profile.json
b096498465183e0bc3eec67f947134d3ebf6900435d53a651850a3994a766130  docs/plan/verification-matrix.md
4b76a2dcd119635c280a20cada87c486f223b54a1588a9799d70b4a671b2ec6d  docs/toolchain.md
054b7728de49e3838fc0a1be8a1532951fa65652c87ac5c2ff5cf1c20f83fa48  pyproject.toml
845d83ab8f07a18543e8fd7ee85a57452f84539c3bad5cd59ff72a4a98ecde8c  scripts/bootstrap.sh
a248e3c52da9555d341db92e915244a1c2e6416fab5cc6469a4556e5c2d466ff  scripts/bootstrap_mlt.sh
93253e2361e99393131576f8ecda25d492d575569c3a7173a66fe8f8cba89ce2  scripts/build_frozen_toolchain.sh
84cd4d8893ee4bbedf690f4a9a1a6b827d3207b0d2783025ee514377a27c343c  scripts/build_toolchain_macos.sh
630703ad0ccc56384acfd8f2c024307b845b706638f4d03fe3caa13ad09fd6dc  scripts/refresh_evidence_hashes.py
166d5e71fe002fde73550126863fdca6bdf6b8d08699b3b08c72bd6b3d03f3c3  scripts/verify_boot_tripwires.sh
f578c792d54478bc646479d1dd4a1f445ce6e9366e3eb474e978168b64425911  src/aidashvideo/__init__.py
9cd6d14c3ca9eaab9da50e20b91f0bb5946440e96c4cd3c9d8a05ae839c3d503  src/aidashvideo/catalog/__init__.py
cdaa589bb0d303487b101a30cedc6b0b46cd498ab91f27c70064d6cf0c0bdf17  src/aidashvideo/catalog/_mlt_probe.py
dbf13124c03d5229426b7925ef3355c3b974eeae9b9de6de8799a8db8d19aeac  src/aidashvideo/catalog/_provider_probe.py
23da641adc3a6ae368f441fa3e5a83e9999ab943e5a676d2735add961cbd89b9  src/aidashvideo/catalog/doctor.py
fec2350d2687f1d5badaadd6039388fdd97187bd0b6100d706ddee230721085a  src/aidashvideo/catalog/ffmpeg.py
0931d12f7097261f63ce11f098156890e27469ed81290c23d8a6844a57b365ea  src/aidashvideo/catalog/mlt.py
bc02f4cccbc4be2c5b31d8140b518c1858bc12c87ca0af5f2839c934d24f8211  src/aidashvideo/catalog/models.py
d4cd72cf82b3799b01ad1f8e7d9292448621d6ea6094adc01b717be8e496ce2a  src/aidashvideo/catalog/offline.py
983acf051da38c521888ddadd209ba1e084f9c204cb24e12f467d4cb559fa23a  src/aidashvideo/catalog/paths.py
01641aac0269a72422ea1f8a52b24125b6ac6609fc36dd38f86b74c7bb7e2106  src/aidashvideo/catalog/pins.py
c5ee8911f465c87ce87844029dc301e6885460997cd47b39ac6016d0e7c1af73  src/aidashvideo/catalog/providers.py
0967f7ec449f7ba28deb0ed7fbbe3b5ba449f1dad4ddb22d36a6091e4d0917d5  src/aidashvideo/catalog/status.py
88d5c2bda05d9b0b56a092e1305fe5183965d7d99c89ca0eb1c11b4e82a031c9  tests/boot_probe.py
af04966b8d831a675976826223c5827eb9211c101133f443caa4afb0514f53d0  tests/test_boot_isolation.py
03a2edd90cd8bfee9035a2949925ec8f6b3e680e28a5ef663ffbf9494bd9d2e2  tests/test_catalog.py
3b32b93b44671d34ca5e0a21040395ef287050ef3e149cd3da386093ace3aa1c  tests/test_plan_integrity.py
5dc31b84ebc19c3f739b14048ae81de1d6e7384ffdfc6272558d8ff12240f948  tests/test_toolchain_live.py
82936348d0b976902c8c12d85b6739fee31157989da7e2eccb539dd0f43eb403  toolchain/mlt-noble-amd64.lock
44904bd9ea96cb766f6dad60ebb2c04cf6736718ed351b68ce7e1e6b5403a20c  toolchain/models.toml
84ed7af6e7bb28b5c4c8f910defc9c910d23f89e585771058743216afa71e1d9  toolchain/profiles/dev-sandbox-linux.toml
8975213c1ef86b066adaecaeef02155dc885561167ae139483f96ad9a97825a3  toolchain/profiles/frozen.toml
cdfc35ee67f6d4c790576c50e1f23333596d096e49f7245f77d98f32cc162b77  toolchain/sysroot-noble-amd64.lock
0b8451a4e1813e73140b70e397fd9ab2f9313b1b79ec9c15e69330d869b027f2  uv.lock
```

Local artifacts (git-ignored; produced on and retained by the Linux sandbox host; on another
host they are absent and the plan-integrity test skips them, but any that are present must
still match):

```text
f74261b67b925ace59aa5f7e409270bb7bb3f3a9da0a87357430a6a39565085a  var/evidence/milestone-0/criterion2.txt
36535d6516709843ba850c2f3c9fc33c4b6c6ab783182ffb1ac6c019de221b90  var/evidence/milestone-0/doctor-dev-sandbox.json
402892d7a829b6eaa1a52b09992be914c065550d2ab998d2c1afd2c662593ffa  var/evidence/milestone-0/doctor-frozen.json
8fb9996b4c2faec090627fdf8c254684662448731c2d80cf47325753505c978f  var/evidence/milestone-0/mlt742-consumers.txt
3848096fb09083d5752d1944d85f01ceb85a4341b3cc570880952271daf44606  var/evidence/milestone-0/mlt742-filters.txt
b7d208e4506a6b15d3e6b058601f495fbaeeda72315fec0608283d0673e6f07a  var/evidence/milestone-0/mlt742-links.txt
fc0f4b844a5ee782fe7fdf10753d81aeb36168b8ec76d5a59e12db4d49429c88  var/evidence/milestone-0/mlt742-modules.txt
36a28366ccc8099745e170e3f8ae5d4c9e8f1e27991d403ff266a9879af29c0c  var/evidence/milestone-0/mlt742-producers.txt
dfc0da447f2ddee9aa82b18302d61e51e2e0f6a54a54268e5ed35aba45b5b247  var/evidence/milestone-0/mlt742-transitions.txt
1249444e8e3b3851a1cf7cb603edd654c2a82f9bb167c28486585d86e4163e85  var/evidence/milestone-0/mlt742_frame_0.5s.png
523e1a0381c00a2aa58bdfaba4a67a8d02611952bc7c5a7ff37a230b2a2ef40b  var/evidence/milestone-0/mlt742_frame_3.0s.png
b47960df2fdd985cc90a16fc698d262f2a033618c14d0e656fccb2f799fce768  var/evidence/milestone-0/mlt742_render.log
717d0b33a9a803bb9c3cd9eb13c4f84967b775826b3cd175743ba10deadc8064  var/evidence/milestone-0/mlt742_render.mp4
6d88a1b220adb7a3d62092b6e38431f0b3fe8babe9864fab90e5849766260332  var/evidence/milestone-0/pyright.txt
c0a8976836e2854946243a3870cd752228f5ac6bfb04c84d7b88b0b99862060f  var/evidence/milestone-0/ruff.txt
90ca36be416b2e8d2f8e3b2394f46bbcf77c7ffb24ebe42d57c1af2a8e5a9f77  var/evidence/milestone-0/tripwires.txt
51fa3cb75a4316d43b7ed0d16affe4183597c916e490e4cba240378b69fee2ba  var/evidence/milestone-0/whisper_cli.txt
cc11e3c9096037d21b9e895378cdb1ce929e3843aad3c248e62cde27114d488d  var/evidence/milestone-0/whisper_filter_queue1.json
664c489bd273609f5b5c983b75acaee867c34b5931c16fa0088a94d29e8bc2bb  var/evidence/milestone-0/whisper_filter_queue3.json
949249fc9afdba4304f0d542afda8a2dc8a399bd17b24d820830151c88927607  var/evidence/sandbox-install-2026-10-15/candidate_scope.sha256
46440364b495f80746f0f1272dab8183426b0a2c82688c96244cefbbfb75b5fa  var/evidence/sandbox-install-2026-10-15/doctor.json
a2c2680f18bf9b557a5d968bb065832032c37373566415871948ac62917c99b5  var/evidence/sandbox-install-2026-10-15/frame_0.5s.png
8c29d6f97d1e05a20cf4a104bd3c08be7a9a06463b66c212637c2ee541565c76  var/evidence/sandbox-install-2026-10-15/frame_1.5s.png
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  var/evidence/sandbox-install-2026-10-15/melt.log
9c6701c379cf8028e03d4eb6a9bbc0b0d72106c1afe53226018334ec918b440e  var/evidence/sandbox-install-2026-10-15/mlt_closure_packages.txt
a1095cf9a84a9fbc61fa59093876f6efdc95d65828d3d94dae8d308254cbd176  var/evidence/sandbox-install-2026-10-15/mlt_filtered.mp4
ec84f24fe6d996366d056ef613a7d1fb07df891f4d0f3ce0a90e2b2c34be4ce8  var/evidence/sandbox-install-2026-10-15/offline_bootstrap.log
6d88a1b220adb7a3d62092b6e38431f0b3fe8babe9864fab90e5849766260332  var/evidence/sandbox-install-2026-10-15/pyright.txt
f40075c64db980af4f15894555bbcdc9d6ddabca6a238aed514b965c7a37f9d0  var/evidence/sandbox-install-2026-10-15/python_packages.txt
4427e78722f1a1f1b5beb551369194d97ccd95a6bcd2aeb751b35343699a7628  var/evidence/sandbox-install-2026-10-15/ruff.txt
bb4212a5ce2235eaff05f524cfeb9f7cbc4706392d6059bdaa01c9497b58764d  var/evidence/sandbox-install-2026-10-15/src.mp4
7cf4f594b0dcfad0e376a6e7c63cfeb2eff842d679e2ce01e3e114c329686b33  var/fixtures/gp01/SHA256SUMS
4968a5977721b02f3b833e342e2c8f9b3dfab235ce6a8df511681a241edd6961  var/fixtures/gp01/broll.mp4
84c9e59154437342e4de841f63cf88b5e8efd6e513091983590b09ad09997038  var/fixtures/gp01/generate.sh
68d0d8ba86203cf54f75539b33f7b5719b1651a9664b1b84c8b3c000c25a9505  var/fixtures/gp01/generator-identity.txt
b8220b4c7322a2a460ca0aba661c55f43b1d71c76d0c6fbcf9ea02716b58c34b  var/fixtures/gp01/interview.mp4
8b33d9e6bfd6aa7cc2b6f87122abbd30888aa500586d9f1c923cb63e89040763  var/fixtures/gp01/music.wav
```

`var/evidence/milestone-0/pytest.txt` is retained but not hashed (its timing line varies per run).

## Cleanup and blockers

No original was modified; no shared cache or service was changed; nothing was published,
pushed or committed. Temporary clones from the tripwire script are deleted on exit.

Remaining blockers are the `Missing`/`Conflicting` items in
[../plan/runtime-profile.json](../plan/runtime-profile.json) and
[../plan/provider-manifest.json](../plan/provider-manifest.json): target-host toolchain
install (FFmpeg 9.0.2 with `--enable-whisper`, MLT 7.42.0, Python 3.14), SAM 3 / SAM 3.1
weights, ggml whisper model, chat model choice, word
alignment adapter (deferred).
