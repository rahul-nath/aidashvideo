#!/usr/bin/env bash
# Build the archive handed to the Linux sandbox for Milestone 1 (docs/plan/commands.md §8).
#
#   scripts/make_handover_archive.sh [<output.tar.gz>]   default: ~/aidashvideo-handover-<date>.tar.gz
#
# Included (always):   tracked files and the Milestone 0 deliverables: pyproject.toml, uv.lock,
#                      .python-version, .gitignore, README/LICENSE/NOTICE, src/, tests/, scripts/,
#                      toolchain/, docs/ (design, plan, evidence), and .git/ when present (so the
#                      sandbox works from the same tree).
# Included (optional): GP-01 fixtures from <var>/fixtures/gp01 (--fixtures), the toolchain source
#                      archives from <deps>/uploads and <deps>/cache (--sources), the whisper ggml
#                      model from <deps>/models/whisper (--whisper).
# Never included:      .venv, <deps>/frozen|src (host binaries), SAM 3.1 weights and the CLIP
#                      tokenizer (darwin-only use; 3.5 GB), var/evidence, the claude-hfi binary,
#                      __pycache__, .DS_Store.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPS="${AIDASHVIDEO_DEPS_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/aidashvideo/deps}"
VAR="${AIDASHVIDEO_VAR_DIR:-$REPO/var}"
OUT=""; WANT_FIX=0; WANT_SRC=0; WANT_WHISPER=0
for a in "$@"; do
  case "$a" in
    --fixtures) WANT_FIX=1 ;; --sources) WANT_SRC=1 ;; --whisper) WANT_WHISPER=1 ;; --all) WANT_FIX=1; WANT_SRC=1; WANT_WHISPER=1 ;;
    -*) echo "unknown flag $a" >&2; exit 2 ;; *) OUT="$a" ;;
  esac
done
OUT="${OUT:-$HOME/aidashvideo-handover-$(date +%Y%m%d).tar.gz}"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/handover.XXXXXX")"; trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/aidashvideo"; mkdir -p "$ROOT"

copy() { # src dest-relative
  [[ -e "$1" ]] || return 0
  mkdir -p "$ROOT/$(dirname "$2")"
  rsync -a --exclude '__pycache__' --exclude '.DS_Store' --exclude '*.pyc' "$1" "$ROOT/$2"
}
for f in pyproject.toml uv.lock .python-version .gitignore README.md LICENSE NOTICE; do copy "$REPO/$f" "$f"; done
for d in src tests scripts toolchain docs; do copy "$REPO/$d/" "$d/"; done
[[ -d "$REPO/.git" ]] && copy "$REPO/.git/" ".git/"
[[ -f "$REPO/.git" ]] && echo "note: $REPO is a worktree (.git is a file); history is not included; commit in the main checkout and archive from there if the sandbox needs it" >&2

if [[ $WANT_FIX == 1 ]]; then copy "$VAR/fixtures/gp01/" "var/fixtures/gp01/"; fi
if [[ $WANT_SRC == 1 ]]; then
  for f in "$DEPS"/uploads/whisper.cpp-1.9.5.tar* "$DEPS"/uploads/mlt-7.42.0.tar* "$DEPS"/cache/ffmpeg_9.0.2.orig.tar.xz; do
    [[ -f "$f" ]] && copy "$f" "handover/sources/$(basename "$f")"
  done
fi
if [[ $WANT_WHISPER == 1 ]]; then copy "$DEPS/models/whisper/ggml-base.en.bin" "handover/models/ggml-base.en.bin"; fi

( cd "$ROOT" && find . -type f ! -path './.git/*' -print0 | sort -z | xargs -0 shasum -a 256 ) > "$ROOT/handover/SHA256SUMS" 2>/dev/null || { mkdir -p "$ROOT/handover"; ( cd "$ROOT" && find . -type f ! -path './.git/*' -print0 | sort -z | xargs -0 shasum -a 256 ) > "$ROOT/handover/SHA256SUMS"; }
cat > "$ROOT/handover/README.md" <<EOF
# AiDashVideo handover ($(date -u +%Y-%m-%d))

Start here: docs/design/README.md (scope), docs/plan/ (frozen plan), docs/evidence/milestone-0.md (state),
docs/plan/commands.md §7 (Linux sandbox setup) and §5 (Milestone 1 commands). Next milestone: docs/design/milestone-1.md.

Sandbox bootstrap:
  uv sync --locked                                   # once online (dev group only; sam31-mlx is darwin-only)
  uv run --offline --no-sync pytest -q -p no:cacheprovider -m "not live"
  export AIDASHVIDEO_DEPS_DIR=\$HOME/.local/share/aidashvideo/deps AIDASHVIDEO_VAR_DIR=\$HOME/.local/share/aidashvideo/var
  mkdir -p \$AIDASHVIDEO_DEPS_DIR/uploads && cp handover/sources/* \$AIDASHVIDEO_DEPS_DIR/uploads/   # if --sources was used
  scripts/build_frozen_toolchain.sh --allow-download   # optional for M1; required from M2

Contents are listed with hashes in handover/SHA256SUMS.
EOF
tar -C "$STAGE" -czf "$OUT" aidashvideo
echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"
( cd "$ROOT" && du -sh . src tests scripts toolchain docs var handover 2>/dev/null | sed 's/^/  /' )
