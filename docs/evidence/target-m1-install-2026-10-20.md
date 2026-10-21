# Target-host install evidence: Apple M1 Pro (2026-10-20, rebuilt 2026-10-21)

Verification below was performed by the implementing AI on the operator's machine. It is not an
independent review and not operator approval. Candidate: branch
`hfi/8080ec40-b2a2-4170-a952-f1a329802d44/elm` at commit `f04e824`, all Milestone 0 files plus the
changes listed in "Repository changes" uncommitted in the working tree (no commit was requested).

This record complements [milestone-0.md](milestone-0.md) (the Linux sandbox report). Readiness
words follow [../plan/contracts.md §9](../plan/contracts.md#9-readiness-words).

## Host

macOS 27.0.1 (arm64), Apple M1 Pro, 8 cores (6 performance), 16 GiB unified memory.
uv 0.12.11; uv-managed CPython 3.14.7 (`python-preference = "managed"`, downloads disabled).
Homebrew supplies build-time libraries only (versions below). Homebrew's own `ffmpeg` 9.0.2_1 is
present on PATH as an `opencv` dependency; it lacks whisper, libass, freetype, fontconfig, harfbuzz
and fribidi, so the doctor reports it `Conflicting` when the pinned install is absent. The pinned
install always takes precedence over PATH.

## Install location (changed 2026-10-21)

Toolchain, source caches and admitted models live in **`~/.local/share/aidashvideo/deps`**
(`$XDG_DATA_HOME/aidashvideo/deps`; `AIDASHVIDEO_DEPS_DIR` overrides). Resolution order is in
`aidashvideo.catalog.paths.deps_dir`: explicit override, then the repository's `.deps/` if it holds
a toolchain profile or model admissions, then the user data dir.

Why: this checkout is a session worktree that is mirrored between turns. On 2026-10-21 at 11:00
its `.deps/` was reverted to the previous day's state (no `bin/`, no `profile.json`, no
`mlt7.py`, no `admissions.json`) right after `.deps/` and `/*.tar` had been added to `.gitignore`,
and the operator-supplied tarballs vanished from both the worktree root and the main checkout at
the same sync. Everything was rebuilt from scratch into the user data dir, which no sync touches.

## Status by area

| Area | Readiness (this host) | Evidence |
| --- | --- | --- |
| Core (FFmpeg 9.0.2 + whisper, MLT 7.42.0, Python 3.14) | **Verified** | `aidashvideo-doctor` exit 0; real 1 s 1080p30 H.264 + AAC round trip for FFmpeg; MLT render of 30 frames 1920x1080 + 48 kHz stereo decoded by ffprobe |
| Full MLT package inventory | **Verified (inventory recorded)** | 22 modules; `melt -query` 43/558/54/11/310 (producers/filters/transitions/consumers/links); catalog digest `4deb9c31…6e36b` reported as an observed fact |
| Timed speech (FFmpeg `whisper` filter, Metal) | **Verified (installed; not quality-qualified)** | filter present; `ggml-base.en.bin` admitted; synthesized "hello golden path" transcribed as `"Hello Golden Pass!"` `[0,2960]` + `"death."` `[2944,3444]` ms (queue=3 s; segment-only timing) |
| SAM 3.1 MLX (mlx-vlm 0.7.8, Metal) | **Verified (installed; not quality-qualified)** | `mlx-community/sam3.1-bf16` snapshot `97ae6308…` + CLIP tokenizer admitted; loads offline in 3.7 s; segments a synthetic red disc at score 0.96 in 5.8 s; 5.4 GB peak Metal memory |
| SAM 3 (torch) | Missing, **obsolete** | the revised design ([../design/milestone-0.md](../design/milestone-0.md)) names one SAM 3.1 MLX profile only; the `sam3-torch` extra, `sam3-hf` asset and plan rows are left in place until docs/plan is regenerated |

Operator decision 2026-10-21: version and required-capability requirements stay pinned
(`toolchain/profiles/*.toml`); build digests (FFmpeg capability digest, MLT service catalog digest)
are **not** pinned, because they differ per host build. The doctor still computes and reports both
as facts.

## Acceptance commands (repository root; exit codes reproduce)

| # | Command | Exit | Observed |
| --- | --- | --- | --- |
| 1 | `AIDASHVIDEO_DEPS_DIR=~/.local/share/aidashvideo/deps scripts/build_toolchain_macos.sh --clean --allow-download whisper ffmpeg` then `… mlt profile` | 0 / 0 | whisper.cpp 1.9.5 (Metal, embedded shaders), FFmpeg 9.0.2 `--enable-whisper`, MLT 7.42.0 `-DRELOCATABLE=OFF -DSWIG_PYTHON=ON`; `profile.json` written |
| 2 | `uv run --offline --no-sync aidashvideo-models admit …` (whisper-ggml-model, clip-tokenizer, sam31-mlx `--revision 97ae6308acc10e6308529f432c71ebfcd78ac65d`) | 0 | all three `Verified`; hashes in `<deps>/models/admissions.json` |
| 3 | `uv run --offline --no-sync aidashvideo-doctor --json` | 0 | host, ffmpeg, mlt, sam31-mlx, timed-speech, asset:sam31-mlx, asset:clip-tokenizer, asset:whisper-ggml-model `Verified`; sam3-torch and asset:sam3-hf `Missing`; `core_verified: true` |
| 4 | `uv run --offline --no-sync pytest -q -p no:cacheprovider --strict-markers` | 0 | 34 passed (18 catalog/boot, 11 plan, 5 live) |
| 5 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m live` | 0 | ffmpeg pins, whisper transcription, MLT native render, SAM 3.1 Metal segmentation, Hub egress blocked |
| 6 | `uv run --offline --no-sync ruff check .` / `ruff format --check .` | 0 / 0 | clean (`.deps`, `var` excluded) |
| 7 | `uv run --offline --no-sync pyright` | 0 | 0 errors (strict, Python 3.14) |
| 8 | `scripts/verify_boot_tripwires.sh` | 0 | control passes; 4/4 mutations detected (run 2026-10-19 on this host) |
| 9 | `uv lock --check --offline` | 0 | lock current |

## Identities (2026-10-21 build)

| Component | Identity |
| --- | --- |
| `<deps>/frozen/bin/ffmpeg` | 9.0.2, sha256 `d9a1564290804d024b62846cba76226d8bafd3f4ef79682a44a56faf9e830f89`; observed capability digest `3252295d57fb21b5287466c1cce32249553c557063237227b72438a70bc14c9d` (501 filters; identical to the 2026-10-20 build) |
| `<deps>/frozen/bin/ffprobe` | sha256 `e3d74f0aa634428cf71786d389a0a727b540f9f3f71f58db3610826185bd94f1` |
| `<deps>/frozen/bin/melt` | 7.42.0, sha256 `1ea872a90537410c6dad31cf8794ff7056981019f31d1a75dc9a5f3e58e82b99` |
| `<deps>/frozen/lib/libmlt-7.7.dylib` | sha256 `a75f3e28daf3aa3978e4b04a96ca07a1e60e240e67ffcf71db7c1b302e010e80` |
| `<deps>/frozen/lib/python3.14/site-packages/_mlt7.so` | sha256 `df26afb344cedebca0d6cdfc89bed8b1a54cb044a0ebfb4222017bcd3e4bd89e` |
| `<deps>/frozen/bin/whisper-cli` / `libwhisper.1.9.5.dylib` | 1.9.5 (ggml 0.26.0, Metal), sha256 `c5072c93…259f7a` / `cad11e4b…c8f730` |
| MLT modules (22) | avformat core decklink frei0r gdk kdenlive normalize oldfilm openfx placebo plus plusgpl qt6 resample rtaudio rubberband sdl2 sox vidstab vorbis xine xml (movit, opencv, glaxnimate, ndi, spatialaudio, rnnoise, jackrack, ladspa off); observed catalog digest `4deb9c311cdd6b7279d1e5e31d82659c130f7a726f83045363ebe4783d86e36b` (identical to the 2026-10-20 build) |
| Sources | `whisper.cpp-1.9.5.tar.gz` (GitHub release archive) sha256 `ff1a9053feb509ff9d7729703355541ae9690073a6b1c40eb692c962e0dc1720`; `mlt-7.42.0.tar.gz` (GitHub release archive) sha256 `8800e343f43aaa885bd5d9d23553030fa220aa3e2f0c94d9fd6a936d41638cdd`; `ffmpeg_9.0.2.orig.tar.xz` (deb.debian.org) sha256 `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e`. The operator-supplied plain `.tar` archives (`a2e9fd8d…e4c3`, `94c219b2…0ed2`) used on 2026-10-20 were no longer present; the build script accepts either form. The build outputs' capability and catalog digests match the 2026-10-20 build from the operator tarballs |
| Homebrew build deps | cmake 4.4.4, swig 4.5.1, nasm 3.02, pkgconf 3.0.10, x264 r3222, libass 0.17.5, freetype 2.15.0, fontconfig 2.18.3, harfbuzz 14.6.0, fribidi 1.0.17, libvorbis 1.3.7, qtbase 6.12.0, frei0r 3.6.0 (156 plugins; matches the plan pin), rubberband 4.0.0, sox 14.4.2, libvidstab 1.1.2, libsamplerate 0.2.2, fftw 3.3.11 |
| `asset:sam31-mlx` | `mlx-community/sam3.1-bf16` snapshot `97ae6308acc10e6308529f432c71ebfcd78ac65d`: `config.json` (`model_type` `sam3.1_video`), `model.safetensors` 3,493,016,552 bytes, 1961 tensors, 873.2 M parameters, stored **F32** despite the repo name |
| `asset:clip-tokenizer` | `openai/clip-vit-base-patch32` tokenizer/processor files only (no weights); resolved by `Sam31Processor` through `HF_HUB_CACHE=<deps>/models/hf-hub` with `HF_HUB_OFFLINE=1` |
| `asset:whisper-ggml-model` | `ggml-base.en.bin` sha256 `a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002` |
| Python extras | mlx 0.32.3 + mlx-metal, mlx-vlm 0.7.8, transformers 5.19.0, huggingface-hub 1.33.0, numpy 2.5.4, pillow 12.3.0 (extra `sam31-mlx`; `sam3-torch` not installed) |

## Findings worth knowing

- **MLT on macOS defaults to `RELOCATABLE=ON`**, which makes `mlt_factory_init` ignore
  `MLT_REPOSITORY`/`MLT_DATA` and look under `<executable>/../PlugIns/mlt`. With the Python
  bindings the executable is `.venv/bin/python`, so no plugins were found. The build script passes
  `-DRELOCATABLE=OFF`; after that the profile's environment variables drive MLT.
- **The checkout is not durable for ignored files.** See "Install location". Anything the
  project needs across sessions must live in the user data dir or be tracked.
- The whisper base.en model mishears the synthesized "path" ("Pass", "death"); the live test
  asserts only "golden" and segment coverage. Quality qualification (V05/V06) remains open.
- The 3.3 GB duplicate download of the SAM 3.1 checkpoint (`.deps/downloads/sam3.1-bf16`) was
  deleted on operator instruction (2026-10-21); the admitted snapshot is the only copy.

## Repository changes (uncommitted)

- `scripts/build_toolchain_macos.sh` (new): Darwin sibling of the Linux recipe; installs to the
  deps dir; accepts operator `.tar` or upstream `.tar.gz` sources by hash; `--allow-download` grant.
- `tests/test_toolchain_live.py` (new) and the `live` pytest marker.
- `src/aidashvideo/catalog/paths.py`: `deps_dir` resolution order (override, repo, user data dir);
  `pins.py`, `ffmpeg.py`, `mlt.py`: digest pins removed, digests reported as facts.
- `toolchain/profiles/*.toml`: digest lines removed; versions and required capabilities kept.
- `toolchain/models.toml`: `clip-tokenizer` asset added.
- `pyproject.toml`: `python-preference = "managed"`, Python 3.14 for ruff/pyright, ruff excludes.
- `.python-version`: 3.14. `.gitignore`: `/.deps/`, `/*.tar`, `/*.tar.*`, `/*.zip`.
- `tests/test_plan_integrity.py`: acceptance contract path `docs/design/milestone-6.md`; `var/`
  links and hashes treated as host-local evidence; a Verified tool needs a target-host observation.
- `tests/test_catalog.py`: `deps_dir` resolution test.
- `docs/plan/runtime-profile.json`, `provider-manifest.json`: target host recorded; core,
  full-mlt-package, timed-speech, sam31-mlx and all tool rows `Verified` with this report as
  evidence; digest pins removed; frei0r resolved (3.6.0); `sam3-torch` rows marked obsolete.
- `docs/plan/commands.md` §0/§1/§5/§6, `implementation-plan.md` M1 exit, `verification-matrix.md`
  (five cells verbatim from the revised M6), `docs/toolchain.md`: deps dir, no digest pins, host
  statements corrected to M1 Pro / 16 GB.
- `src/aidashvideo/catalog/_provider_probe.py`: torch typed as optional.

## Remaining blockers and stale statements

- `docs/plan/*` still carries the five sandbox-era readiness rows including `sam3-torch`, the
  SAM 3 torch backend in `contracts.md`, and none of the new closed variants from
  `docs/design/milestone-0.md`; regenerating docs/plan against `docs/design/` is the Milestone 0
  re-run the operator has scheduled.
- No quality qualification: V05/V06 (speech), V08 (masks) need the annotated fixtures.
- GP-01 fixtures (`var/fixtures/gp01`) are not generated on this host yet (recipe in
  [../plan/fixtures.md](../plan/fixtures.md); the sandbox used `flite`, this host has `say`).
- `var/` is git-ignored and therefore as ephemeral in this checkout as `.deps/` was; fixtures and
  evidence stores need the same durable-location treatment before M1 relies on them.
