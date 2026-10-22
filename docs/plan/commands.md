# Commands (frozen at Milestone 0, revised 2026-10-21)

All development commands run offline through `uv run --offline --no-sync`. Prerequisites are
listed per command; a missing prerequisite is a named blocker, never permission to fetch.
Readiness words come from [contracts.md §9](contracts.md#9-readiness-words).

## 0. Prerequisites and locations

| Prerequisite | How to check | If absent |
| --- | --- | --- |
| Repository root = the directory containing `pyproject.toml`; every command below runs from it | `test -f pyproject.toml` | wrong directory |
| uv >= 0.9.10 (target: 0.12.11) | `uv --version` | blocker (do not install from this repo) |
| CPython 3.14 on every host; `python-downloads = "never"`; uv-managed interpreters already present are allowed (`python-preference = "managed"`) | `uv python find 3.14` | blocker (sandbox fallback: `scripts/build_frozen_toolchain.sh python` builds 3.14.7 from the archived source) |
| `.venv` synced from `uv.lock` (target: `--extra sam31-mlx`; sandbox: dev group only, the extra is darwin-only) | `uv sync --locked --offline --extra sam31-mlx` (target) / `uv sync --locked --offline` (sandbox); the uv cache is populated once, online, with the operator's grant | run the online sync once with the operator's explicit acquisition grant |
| Deps dir `<deps>` = `AIDASHVIDEO_DEPS_DIR`, else the repository's `.deps/` when it holds an install, else `$XDG_DATA_HOME/aidashvideo/deps` (`~/.local/share/aidashvideo/deps`); holds `frozen/` (toolchain), `models/` (admitted assets), `uploads/`, `cache/`, `src/` | `uv run --offline --no-sync python -c "from aidashvideo.catalog.paths import deps_dir; print(deps_dir())"` | see §6 |
| Local stores `var/fixtures/`, `var/evidence/` are git-ignored; checkouts can be ephemeral, so point `AIDASHVIDEO_VAR_DIR` at a durable location (target: `~/.local/share/aidashvideo/var`) | `echo $AIDASHVIDEO_VAR_DIR` | fixtures regenerate from [fixtures.md](fixtures.md) recipes |
| FFmpeg 9.0.2 (+whisper) and MLT 7.42.0 in `<deps>/frozen` | `uv run --offline --no-sync aidashvideo-doctor --quick --no-providers` | `Missing`/`Conflicting`; follow §6 |

## 1. Development loop (offline)

```bash
uv sync --locked --offline --extra sam31-mlx                 # target: reproduce .venv from uv.lock (cache only)
uv sync --locked --offline                                   # Linux sandbox: dev group only (hypothesis, pytest, ruff, pyright, patchelf)
uv run --offline --no-sync pytest -q -rA -p no:cacheprovider --strict-markers   # unit + boot isolation + plan integrity + live (live skips with the blocker when a supplier is absent)
uv run --offline --no-sync pytest -q -p no:cacheprovider -m "not live"          # host-independent subset
uv run --offline --no-sync ruff check . && uv run --offline --no-sync ruff format --check .
uv run --offline --no-sync pyright
uv run --offline --no-sync aidashvideo-doctor [--json] [--quick] [--no-providers]
uv run --offline --no-sync aidashvideo-models status
uv lock --check --offline
```

Pytest markers (declared in `pyproject.toml`): `boot` (import isolation), `plan` (plan
consistency), `live` (installed toolchain and admitted models on this host). Milestone
markers are added by the owning milestone: `ledger`, `timing`, `store`, `project` (M1),
`integration`, `mlt` (M2), `speech` (M3), `subjects` (M4), `chat`, `ui` (M5).

Formatting and static scope: `ruff` over the repository (`.deps`, `var` excluded), target
version py314; `pyright` strict over `src`, `tests`, `scripts` with `pythonVersion = "3.14"`.
Property tests use `hypothesis` (dev group).

## 2. Boot isolation (I10, V14)

```bash
uv run --offline --no-sync pytest -q -p no:cacheprovider -m boot
scripts/verify_boot_tripwires.sh                                   # proves the test fails for 4 mutations
uv run --offline --no-sync python -I -X importtime -c "import aidashvideo" 2>&1 | grep -ciE "mlt|mlx|torch|whisper|sam|numpy|socket"   # prints 0
```

## 3. Plan integrity

```bash
uv run --offline --no-sync pytest -q -p no:cacheprovider -m plan
```

## 4. Model assets (operator-supplied; nothing is downloaded by the repository)

```bash
uv run --offline --no-sync aidashvideo-models status
uv run --offline --no-sync aidashvideo-models admit whisper-ggml-model <file: ggml-base.en.bin>
uv run --offline --no-sync aidashvideo-models admit sam31-mlx <dir: mlx-community/sam3.1-bf16 snapshot or hub repo dir> --revision <40-hex>
uv run --offline --no-sync aidashvideo-models admit clip-tokenizer <dir: openai/clip-vit-base-patch32 tokenizer files>
```

## 5. Verification commands per milestone (planned; exact names fixed here)

| Milestone | Command | Purpose |
| --- | --- | --- |
| M1 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m "ledger or store or timing or project"` | admission, replay, concurrency, crash injection, CAS, timing/geometry properties, operations, undo, snapshot import |
| M1 | `uv run --offline --no-sync python -m aidashvideo.ledger inspect <project_dir>` | read-only inspection of heads, lineage and outbox (works without MLT or models) |
| M2 | `uv run --offline --no-sync python -m aidashvideo.catalog.descriptors --freeze` | enumerate the installed MLT build (modules, services, parameters) into the frozen descriptor set; the catalog digest is recorded as an observed fact |
| M2 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m "integration and mlt"` | compiler + worker + export receipts on the real MLT (needs core `Verified`) |
| M2 | `uv run --offline --no-sync python -m aidashvideo.jobs export --project <dir> --revision <id> --to <new-file>` | export with `ExportGrant` |
| M3 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m speech` | real spoken/silent fixtures through the whisper filter; selection, correction, caption events |
| M3 | `uv run --offline --no-sync python -m aidashvideo.analysis.speech qualify --samples var/fixtures/annot-words` | V06 harness (blocked until an alignment adapter exists) |
| M4 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m subjects` | SAM 3.1 MLX assets, selection, tracking, correction, durable masks (target only) |
| M4 | `uv run --offline --no-sync python -m aidashvideo.analysis.masks qualify --fixture var/fixtures/annot-masks` | V08 for the SAM 3.1 MLX profile, on the target |
| M5 | `uv run --offline --no-sync python -m aidashvideo.client` / `python -m aidashvideo.client.tools --grant-file <path>` | UI and the stdio tool server |
| M5 | `uv run --offline --no-sync pytest -q -p no:cacheprovider -m "chat or ui"` | tool protocol, displayed-revision binding, lifecycle |
| M6 | all of the above plus `docs/evidence/milestone-6.md` | verification |

## 6. Frozen toolchain install (target host; requires the operator's explicit acquisition grant)

The target recipe is `scripts/build_toolchain_macos.sh` (macOS arm64). It builds whisper.cpp 1.9.5
(Metal), FFmpeg 9.0.2 `--enable-whisper` and MLT 7.42.0 (`-DRELOCATABLE=OFF -DSWIG_PYTHON=ON`,
bindings for the project interpreter) from hash-verified source archives and writes
`<deps>/frozen/profile.json`. Homebrew supplies build-time libraries only (cmake, swig, nasm,
pkgconf, x264, libass, freetype, fontconfig, harfbuzz, fribidi, libvorbis, qtbase, frei0r, rubberband,
sox, libvidstab, libsamplerate, fftw); the operator installs them. Homebrew's own `ffmpeg` and
`mlt` formulae are `Conflicting` (no whisper/libass filters; no Python bindings) and are not used.

```bash
export AIDASHVIDEO_DEPS_DIR=~/.local/share/aidashvideo/deps     # optional; the default resolves the same dir
# Operator-supplied archives go in <deps>/uploads (or the repo root):
#   whisper.cpp-1.9.5.tar | whisper.cpp-1.9.5.tar.gz, mlt-7.42.0.tar | mlt-7.42.0.tar.gz (hashes in the script)
scripts/build_toolchain_macos.sh --allow-download                # grant: FFmpeg 9.0.2 orig tarball (Debian) and,
                                                                 # when no operator archive is present, the upstream
                                                                 # whisper.cpp / MLT release archives (GitHub)
scripts/build_toolchain_macos.sh                                 # offline re-run (stages are stamped; idempotent)
uv run --offline --no-sync aidashvideo-doctor --json > "$AIDASHVIDEO_VAR_DIR/evidence/m0/doctor-target.json"
uv run --offline --no-sync pytest -q -p no:cacheprovider -m live   # real ffmpeg/whisper/MLT/SAM 3.1 checks on this host
```

Version and required-capability requirements live in `toolchain/profiles/frozen.toml`; build digests
(FFmpeg capability digest, MLT service catalog digest) are reported by the doctor as observed facts
and are not pinned, because they differ per host build (D11). V29 compares the digest recorded with
a project against the installed build at open time.

## 7. Linux sandbox (domain and engine work without Metal)

```bash
uv sync --locked --offline                                           # dev group; the sam31-mlx extra is darwin-only
scripts/build_frozen_toolchain.sh --allow-download                    # same identities, rootless, into <deps>/frozen
                                                                      # (needs the whisper.cpp / MLT archives in <deps>/uploads
                                                                      # and the hash-pinned Ubuntu noble headers from toolchain/sysroot-noble-amd64.lock)
scripts/build_frozen_toolchain.sh                                     # offline re-run (stages are stamped)
uv run --offline --no-sync aidashvideo-models admit whisper-ggml-model <deps>/uploads/ggml-base.en.bin
uv run --offline --no-sync aidashvideo-doctor                        # host row Conflicting (not the Mac), ffmpeg/mlt/timed-speech may be Verified; sam31-mlx Missing
```

What the sandbox can do: all of M1 (no native engine needed; `ffprobe` of any installed FFmpeg
produces probe receipts whose tool identity is recorded), M2 engine and compiler work against
the Linux build of the same FFmpeg/MLT identities, M3 speech with the CPU ggml backend. What it
cannot do: anything under `sam31-mlx` (mlx is darwin-only; there is no CPU fallback), any
`Verified` claim for the target host, the M6 measurements. Evidence produced there is labelled
with its host and never promoted to target evidence.

## 8. Milestone-1 handover archive

```bash
scripts/make_handover_archive.sh [<output.tar.gz>]     # repository deliverables (+ optional fixtures, source archives, whisper model)
```

The script never includes `.venv`, build trees, SAM 3.1 weights (darwin-only use) or the
`claude-hfi` binary; see its header for the exact include list.
