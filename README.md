# AiDashVideo

An open-source, AI-directed video editor for common Premiere-style editing workflows.
Describe the changes you want through conversation, preview the results, and refine your edit while keeping the original media intact.

MLT evaluates the timeline and supplies playback/export; FFmpeg supplies explicit media jobs;
timed speech (FFmpeg's `whisper` filter) and a separately qualified SAM 3.1 MLX adapter supply
analysis. Immutable source media plus a versioned project are the only authority.

**Status:** Milestone 0 (repository, frozen contracts and plan, toolchain installed and
smoke-tested) and Milestone 1 (durable project domain: ledger admission, media/artifact
store, timing/geometry algebra, semantic operations, selective undo, portable snapshots;
evidence in [docs/evidence/milestone-1.md](docs/evidence/milestone-1.md)) are complete.
Milestone 2 (MLT engine, previews, media jobs) is next; nothing renders yet. Briefs for
every milestone: [docs/design/](docs/design/README.md).

## Layout

| Path | Purpose |
| --- | --- |
| `docs/design/` | the milestone briefs (M0-M8), coverage map and manifest |
| `docs/plan/` | the frozen plan: contracts, implementation plan, runtime profile, provider manifest, verification matrix, commands, fixtures |
| `docs/evidence/` | per-milestone evidence reports |
| `src/aidashvideo/` | the package: `ledger/` (canonical admission), `store/` (media/artifact store), `project/` (project domain), `catalog/` (toolchain/readiness/descriptors/model assets); the other owners land in their milestones |
| `tests/` | boot-isolation, catalog, plan-integrity and live toolchain tests |
| `scripts/` | toolchain builds (macOS target, Linux sandbox), fixture generation, tripwire proof, handover archive |
| `toolchain/` | pinned profile requirements, model asset manifest, Linux sysroot locks |
| `var/` (git-ignored) | fixtures and local evidence stores |

## Setup

Python 3.14 everywhere (uv-managed on the target, present in the Linux sandbox);
`uv` never downloads an interpreter (`python-downloads = "never"`).

```bash
uv sync --locked --extra sam31-mlx          # macOS target (once, online); sandbox: uv sync --locked
uv run --offline --no-sync aidashvideo-doctor            # readiness: Verified | Missing | Conflicting
uv run --offline --no-sync pytest -q -rA -p no:cacheprovider --strict-markers
uv run --offline --no-sync ruff check . && uv run --offline --no-sync pyright
uv run --offline --no-sync pytest -q -p no:cacheprovider -m "ledger or store or timing or project"   # M1 domain suite
uv run --offline --no-sync python -m aidashvideo.ledger inspect <project_dir>                         # read-only store inspection
```

The frozen toolchain (FFmpeg 9.0.2 built with `--enable-whisper`, whisper.cpp 1.9.5, MLT 7.42.0
with `mlt7` bindings, frei0r 3.6.0) is built from source into `~/.local/share/aidashvideo/deps`
by `scripts/build_toolchain_macos.sh` (target) or `scripts/build_frozen_toolchain.sh` (Linux
sandbox). Model assets are operator-supplied and admitted with `aidashvideo-models admit`;
nothing is downloaded by repository code. Exact commands and prerequisites:
[docs/plan/commands.md](docs/plan/commands.md).

## License

[Apache 2.0](LICENSE) for this project's original code and documentation.
Third-party components retain their respective licenses (see `docs/plan/runtime-profile.json`).
