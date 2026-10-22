# Toolchain notes

The frozen identities (FFmpeg 9.0.2 `--enable-whisper`, MLT 7.42.0 with `mlt7` bindings,
whisper.cpp 1.9.5, Python 3.14) are defined in [plan/runtime-profile.json](plan/runtime-profile.json)
and `toolchain/profiles/frozen.toml`; install recipes are in [plan/commands.md](plan/commands.md) §6
(target) and §7 (Linux sandbox). Versions and required capabilities are pinned; build digests are
observed facts (decision D11).

## Where things live

| What | Location |
| --- | --- |
| Toolchain build (`frozen/bin`, `frozen/lib`, `frozen/profile.json`), source archives, admitted models | `<deps>` = `AIDASHVIDEO_DEPS_DIR`, else `<repo>/.deps` when it holds an install, else `~/.local/share/aidashvideo/deps` |
| Fixtures and retained evidence | `<var>` = `AIDASHVIDEO_VAR_DIR`, else `<repo>/var` (git-ignored; prefer a durable location) |
| Model asset manifest | [`toolchain/models.toml`](../toolchain/models.toml): `sam31-mlx`, `clip-tokenizer`, `whisper-ggml-model` |
| Linux sandbox header pins | [`toolchain/sysroot-noble-amd64.lock`](../toolchain/sysroot-noble-amd64.lock) (used by `scripts/build_frozen_toolchain.sh`) |

## Check readiness

```bash
uv run --offline --no-sync aidashvideo-doctor          # exit 0 = core (host, FFmpeg, MLT) Verified; providers reported separately
uv run --offline --no-sync aidashvideo-models status   # admitted assets
uv run --offline --no-sync pytest -q -p no:cacheprovider -m live   # real ffmpeg / whisper / MLT / SAM 3.1 checks on this host
```

Readiness words are `Verified | Missing | Conflicting` ([plan/contracts.md §9](plan/contracts.md#9-readiness-words)).
Only core decides the exit status; optional providers never break boot.

## Target host (macOS arm64, Apple M1 Pro, 16 GB)

Built on 2026-10-20 and rebuilt on 2026-10-21 by `scripts/build_toolchain_macos.sh` into
`~/.local/share/aidashvideo/deps`: whisper.cpp 1.9.5 (Metal, embedded shader library), FFmpeg
9.0.2 with whisper/libass/freetype/fontconfig/harfbuzz/fribidi/x264/vorbis, MLT 7.42.0 with 22
modules and bindings for CPython 3.14.7 (`-DRELOCATABLE=OFF` is required on macOS or MLT ignores
`MLT_REPOSITORY`). Homebrew supplies build-time libraries only; its own `ffmpeg`/`mlt` formulae
are unusable (no whisper/libass; no Python bindings). Evidence:
[evidence/target-m1-install-2026-10-20.md](evidence/target-m1-install-2026-10-20.md).

Python extras on the target: `sam31-mlx` (mlx 0.32.3, mlx-vlm 0.7.8, transformers 5.19.0 for the
CLIP tokenizer, huggingface-hub 1.33.0). Admitted assets: SAM 3.1 snapshot `97ae6308…` (3.49 GB,
stored F32), CLIP tokenizer files, `ggml-base.en.bin`.

## Linux sandbox (domain, engine and speech work; no Metal)

`scripts/build_frozen_toolchain.sh` builds the same identities rootlessly from the operator's
archives plus hash-pinned Ubuntu noble headers; bindings target CPython 3.14.7 there too. The
`sam31-mlx` extra cannot be installed there (darwin-only markers) and nothing substitutes for
it. Sandbox evidence is labelled with its host and never promoted to target evidence
([evidence/milestone-0-sandbox-2026-10-18.md](evidence/milestone-0-sandbox-2026-10-18.md)).

## Model assets

Providers run with `aidashvideo.catalog.offline.provider_environment()` (HF offline flags set
before import, isolated `HF_HUB_CACHE` under `<deps>/models/hf-hub`, `HF_TOKEN` removed). Admit
operator-supplied downloads with `aidashvideo-models admit <asset-id> <dir|file>`; admission
hashes every file and later changes make the asset `Conflicting`. The acquisition manifest
(sources, hashes, bytes, licenses, destinations, interruption behaviour) is in
[plan/provider-manifest.json](plan/provider-manifest.json) `acquisition_manifest`.
