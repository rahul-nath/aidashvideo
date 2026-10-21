#!/usr/bin/env bash
# Build the FROZEN core toolchain identities (toolchain/profiles/frozen.toml) on the macOS
# arm64 target, rootlessly, into .deps/frozen:
#
#   whisper.cpp 1.9.5 (Metal, embedded shader library) -> libwhisper + whisper-cli
#   FFmpeg 9.0.2 --enable-whisper                       -> ffmpeg/ffprobe + libav* (dylibs)
#   MLT 7.42.0 (+ Python bindings for the project venv) -> melt, libmlt-7, modules, mlt7
#
# Sources: operator-supplied tarballs (repository root or .deps/uploads; hash-pinned below) and
# the FFmpeg 9.0.2 orig tarball from the Debian archive (hash-pinned). Build-time libraries
# come from Homebrew (the operator installs them; this script never calls `brew install`).
# This is the Darwin sibling of scripts/build_frozen_toolchain.sh (the Linux sandbox recipe).
#
# usage: scripts/build_toolchain_macos.sh [--allow-download] [--clean] [whisper|ffmpeg|mlt|profile ...]
#   default: all stages; each stage is skipped when its .stamp exists.
#   --allow-download is the explicit acquisition grant for source archive fetches (FFmpeg from the
#   Debian archive; whisper.cpp / MLT release archives from GitHub when no operator tarball is present).
#   --clean removes .deps/frozen and the extracted source trees first (never models/uploads).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Install location: AIDASHVIDEO_DEPS_DIR, else the user data dir, else <repo>/.deps (see
# aidashvideo.catalog.paths.deps_dir). Keep it OUTSIDE synced/ephemeral checkouts.
DEPS="${AIDASHVIDEO_DEPS_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/aidashvideo/deps}"
UPLOADS="$DEPS/uploads"
SRC="$DEPS/src"
PREFIX="$DEPS/frozen"
CACHE="$DEPS/cache"
BREW="${HOMEBREW_PREFIX:-/opt/homebrew}"
DEBIAN_BASE="${AIDASH_DEBIAN_ARCHIVE:-https://deb.debian.org/debian}"
JOBS="${JOBS:-$(sysctl -n hw.ncpu)}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python3}"

# Pinned source identities. Each component accepts either the operator-supplied plain .tar
# (Linux recipe identity) or the upstream release archive (hashes recorded 2026-10-21).
WHISPER_SOURCES=("whisper.cpp-1.9.5.tar:a2e9fd8dd76d028a747042017ef6b9db605b95e19c45fbd498f8eb309794e4c3"
                 "whisper.cpp-1.9.5.tar.gz:ff1a9053feb509ff9d7729703355541ae9690073a6b1c40eb692c962e0dc1720")
WHISPER_URL="https://github.com/ggml-org/whisper.cpp/archive/refs/tags/v1.9.5.tar.gz"
MLT_SOURCES=("mlt-7.42.0.tar:94c219b256d476dfbf5f7117fcc0d3dec3675fa6d4cdfe51db2eca5a953d0ed2"
             "mlt-7.42.0.tar.gz:8800e343f43aaa885bd5d9d23553030fa220aa3e2f0c94d9fd6a936d41638cdd")
MLT_URL="https://github.com/mltframework/mlt/releases/download/v7.42.0/mlt-7.42.0.tar.gz"
FFMPEG_TAR="ffmpeg_9.0.2.orig.tar.xz"; FFMPEG_SHA="8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"
FFMPEG_URL="$DEBIAN_BASE/pool/main/f/ffmpeg/$FFMPEG_TAR"

die() { echo "build_toolchain_macos: error: $*" >&2; exit 1; }
log() { echo "== $*"; }
check_sha() { echo "$2  $1" | shasum -a 256 -c --quiet - >/dev/null 2>&1; }

ALLOW_DOWNLOAD=0; CLEAN=0
STAGES=()
for a in "$@"; do
  case "$a" in
    --allow-download) ALLOW_DOWNLOAD=1 ;;
    --clean) CLEAN=1 ;;
    whisper|ffmpeg|mlt|profile) STAGES+=("$a") ;;
    *) die "unknown argument $a" ;;
  esac
done
[[ ${#STAGES[@]} -eq 0 ]] && STAGES=(whisper ffmpeg mlt profile)
[[ "$(uname -s)-$(uname -m)" == "Darwin-arm64" ]] || die "this recipe is macOS arm64 only"
[[ -x "$PYTHON" ]] || die "project interpreter not found at $PYTHON (uv sync first)"
for tool in cmake nasm pkg-config swig; do
  command -v "$tool" >/dev/null || die "$tool not found (Homebrew build dependency; operator installs it)"
done
for pc in x264 libass freetype2 fontconfig harfbuzz fribidi vorbis; do
  PKG_CONFIG_PATH="$BREW/lib/pkgconfig" pkg-config --exists "$pc" || die "Homebrew library '$pc' not found"
done

if [[ $CLEAN == 1 ]]; then
  log "clean: removing $PREFIX and $SRC"
  rm -rf "$PREFIX" "$SRC"
fi
mkdir -p "$CACHE" "$SRC" "$PREFIX" "$UPLOADS"

export PATH="$PREFIX/bin:$PATH"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig:$BREW/lib/pkgconfig"
export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-$(sw_vers -productVersion | cut -d. -f1).0}"
RPATH="$PREFIX/lib;$BREW/lib"

find_source() { # url entry... -> prints path of the first hash-verified archive (fetching the
                 # upstream release only with --allow-download)
  local url="$1"; shift
  local entry name sha cand
  for entry in "$@"; do
    name="${entry%%:*}"; sha="${entry##*:}"
    for cand in "$UPLOADS/$name" "$REPO/$name"; do
      [[ -f "$cand" ]] && check_sha "$cand" "$sha" && { echo "$cand"; return; }
    done
  done
  entry="${*: -1}"; name="${entry%%:*}"; sha="${entry##*:}"
  [[ $ALLOW_DOWNLOAD == 1 ]] || die "no hash-verified archive for ${1%%:*} in $UPLOADS or $REPO (pass --allow-download to fetch $url)"
  log "fetching $url"
  curl -fsSL --retry 3 -o "$UPLOADS/$name.part" "$url" || die "download failed: $url"
  check_sha "$UPLOADS/$name.part" "$sha" || { rm -f "$UPLOADS/$name.part"; die "$name sha256 mismatch"; }
  mv "$UPLOADS/$name.part" "$UPLOADS/$name"; echo "$UPLOADS/$name"
}

unpack() { # tarball dest-dir-name
  local tar="$1" name="$2"
  [[ -d "$SRC/$name" ]] && return
  tar -xf "$tar" -C "$SRC"
  [[ -d "$SRC/$name" ]] || die "unexpected layout in $tar"
}

stage_whisper() {
  [[ -f "$PREFIX/.stamp-whisper" ]] && { log "whisper.cpp: present"; return; }
  local tar; tar="$(find_source "$WHISPER_URL" "${WHISPER_SOURCES[@]}")"
  unpack "$tar" whisper.cpp-1.9.5
  log "whisper.cpp 1.9.5: configure + build (Metal, embedded shader library)"
  cmake -S "$SRC/whisper.cpp-1.9.5" -B "$SRC/whisper.cpp-1.9.5/build" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$PREFIX" -DBUILD_SHARED_LIBS=ON -DWHISPER_BUILD_TESTS=OFF \
    -DWHISPER_BUILD_EXAMPLES=ON -DWHISPER_BUILD_SERVER=OFF \
    -DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON -DGGML_NATIVE=OFF \
    -DCMAKE_INSTALL_RPATH="$RPATH" -DCMAKE_INSTALL_NAME_DIR="$PREFIX/lib" -DCMAKE_MACOSX_RPATH=ON \
    > "$SRC/whisper.configure.log" 2>&1 || { tail -30 "$SRC/whisper.configure.log"; die "whisper configure failed"; }
  cmake --build "$SRC/whisper.cpp-1.9.5/build" -j"$JOBS" > "$SRC/whisper.build.log" 2>&1 || { tail -30 "$SRC/whisper.build.log"; die "whisper build failed"; }
  cmake --install "$SRC/whisper.cpp-1.9.5/build" > "$SRC/whisper.install.log" 2>&1
  [[ -f "$PREFIX/lib/pkgconfig/whisper.pc" ]] || die "whisper.pc not installed"
  [[ -x "$PREFIX/bin/whisper-cli" ]] || die "whisper-cli not installed"
  shasum -a 256 "$tar" | cut -d" " -f1 > "$PREFIX/.stamp-whisper"
}

stage_ffmpeg() {
  [[ -f "$PREFIX/.stamp-ffmpeg" ]] && { log "ffmpeg: present"; return; }
  local tar="$CACHE/$FFMPEG_TAR"
  if ! { [[ -f "$tar" ]] && check_sha "$tar" "$FFMPEG_SHA"; }; then
    rm -f "$tar"
    [[ $ALLOW_DOWNLOAD == 1 ]] || die "$FFMPEG_TAR not cached in $CACHE (pass --allow-download)"
    log "FFmpeg 9.0.2: fetching $FFMPEG_URL"
    curl -fsSL --retry 3 -o "$tar.part" "$FFMPEG_URL" || die "download failed: ffmpeg source"
    check_sha "$tar.part" "$FFMPEG_SHA" || { rm -f "$tar.part"; die "ffmpeg source sha256 mismatch"; }
    mv "$tar.part" "$tar"
  fi
  if [[ ! -d "$SRC/ffmpeg-9.0.2" ]]; then
    mkdir -p "$SRC/ffmpeg-9.0.2"; tar -xf "$tar" -C "$SRC/ffmpeg-9.0.2" --strip-components=1
  fi
  log "FFmpeg 9.0.2: configure (--enable-whisper) + build"
  ( cd "$SRC/ffmpeg-9.0.2" && ./configure --prefix="$PREFIX" --enable-gpl --enable-version3 --enable-shared --disable-static \
      --enable-libx264 --enable-libass --enable-libfreetype --enable-libfontconfig --enable-libharfbuzz \
      --enable-libfribidi --enable-libvorbis --enable-whisper --enable-rpath \
      --install-name-dir="$PREFIX/lib" \
      --extra-cflags="-I$PREFIX/include -I$BREW/include" \
      --extra-ldflags="-L$PREFIX/lib -L$BREW/lib -Wl,-rpath,$PREFIX/lib -Wl,-rpath,$BREW/lib" \
      --disable-doc --disable-ffplay > "$SRC/ffmpeg.configure.log" 2>&1 ) || { tail -30 "$SRC/ffmpeg-9.0.2/ffbuild/config.log"; die "ffmpeg configure failed"; }
  grep -q '^whisper=yes' "$SRC/ffmpeg-9.0.2/ffbuild/config.log" || die "configure did not enable whisper (see ffbuild/config.log)"
  make -C "$SRC/ffmpeg-9.0.2" -j"$JOBS" > "$SRC/ffmpeg.build.log" 2>&1 || { tail -30 "$SRC/ffmpeg.build.log"; die "ffmpeg build failed"; }
  make -C "$SRC/ffmpeg-9.0.2" install > "$SRC/ffmpeg.install.log" 2>&1
  local filters
  filters="$("$PREFIX/bin/ffmpeg" -hide_banner -filters 2>&1)" || die "installed ffmpeg does not run: $(echo "$filters" | tail -3)"
  echo "$filters" | grep -q ' whisper ' || die "built ffmpeg lacks the whisper filter"
  echo "$FFMPEG_SHA" > "$PREFIX/.stamp-ffmpeg"
}

stage_mlt() {
  [[ -f "$PREFIX/.stamp-mlt" ]] && { log "mlt: present"; return; }
  local tar; tar="$(find_source "$MLT_URL" "${MLT_SOURCES[@]}")"
  unpack "$tar" mlt-7.42.0
  # RELOCATABLE is ON by default on macOS and makes MLT ignore MLT_REPOSITORY/MLT_DATA in
  # favour of <exe>/../PlugIns/mlt; the profile drives MLT through those variables, so OFF.
  log "MLT 7.42.0: configure + build (Python bindings for $("$PYTHON" --version))"
  cmake -S "$SRC/mlt-7.42.0" -B "$SRC/mlt-7.42.0/build" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DCMAKE_PREFIX_PATH="$PREFIX;$BREW;$BREW/opt/qtbase;$BREW/opt/qtsvg;$BREW/opt/qt5compat" \
    -DCMAKE_INSTALL_RPATH="$RPATH" -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
    -DCMAKE_INSTALL_NAME_DIR="$PREFIX/lib" -DCMAKE_MACOSX_RPATH=ON \
    -DSWIG_PYTHON=ON -DPython3_EXECUTABLE="$PYTHON" \
    -DRELOCATABLE=OFF \
    -DMOD_QT6=ON -DMOD_MOVIT=OFF -DMOD_OPENCV=OFF -DMOD_GLAXNIMATE_QT6=OFF -DMOD_NDI=OFF \
    -DMOD_SPATIALAUDIO=OFF -DMOD_RNNOISE=OFF -DMOD_JACKRACK=OFF -DMOD_SDL1=OFF \
    > "$SRC/mlt.configure.log" 2>&1 || { tail -40 "$SRC/mlt.configure.log"; die "mlt configure failed"; }
  cmake --build "$SRC/mlt-7.42.0/build" -j"$JOBS" > "$SRC/mlt.build.log" 2>&1 || { tail -40 "$SRC/mlt.build.log"; die "mlt build failed"; }
  cmake --install "$SRC/mlt-7.42.0/build" > "$SRC/mlt.install.log" 2>&1
  [[ -x "$PREFIX/bin/melt" ]] || die "melt not installed"
  shasum -a 256 "$tar" | cut -d" " -f1 > "$PREFIX/.stamp-mlt"
}

stage_profile() {
  local pydir moddir datadir
  pydir="$(dirname "$(find "$PREFIX/lib" -maxdepth 3 -name 'mlt7.py' | head -1)")"
  [[ -f "$pydir/mlt7.py" ]] || die "mlt7.py not found under $PREFIX/lib"
  moddir="$(find "$PREFIX/lib" -maxdepth 1 -type d -name 'mlt*' | head -1)"
  datadir="$(find "$PREFIX/share" -maxdepth 1 -type d -name 'mlt*' | head -1)"
  [[ -d "$moddir" && -d "$datadir" ]] || die "MLT module/data directories not found under $PREFIX"
  "$PYTHON" - "$PREFIX" "$pydir" "$moddir" "$datadir" "$BREW" <<'PY'
import json, os, pathlib, sys
prefix, pydir, moddir, datadir, brew = map(pathlib.Path, sys.argv[1:6])
rel = lambda p: os.path.relpath(p, prefix)
profile = {
    "schema": "aidashvideo.toolchain.mlt/1",
    "profile_id": "mlt-7.42.0-frozen",
    "mlt_version": "7.42.0",
    "source": "mlt-7.42.0 source build (scripts/build_toolchain_macos.sh) against FFmpeg 9.0.2 + whisper.cpp 1.9.5 (Metal)",
    "lock_sha256": "",
    "paths": {"melt": "bin/melt", "lib_dir": "lib", "python_dir": rel(pydir), "ffmpeg": "bin/ffmpeg", "ffprobe": "bin/ffprobe"},
    "plugins": {"frei0r": "Homebrew frei0r (see `brew list --versions frei0r`)"},
    "env": {
        "MLT_REPOSITORY": rel(moddir),
        "MLT_DATA": rel(datadir),
        "MLT_PROFILES_PATH": rel(datadir / "profiles"),
        "MLT_PRESETS_PATH": rel(datadir / "presets"),
        # Qt6 module (titles/captions) renders headless through the offscreen QPA plugin.
        "QT_QPA_PLATFORM": "offscreen",
        "QT_PLUGIN_PATH": str(brew / "opt/qtbase/share/qt/plugins"),
    },
}
frei0r = brew / "lib/frei0r-1"
if frei0r.is_dir():
    profile["env"]["FREI0R_PATH"] = str(frei0r)
for key in ("MLT_PROFILES_PATH", "MLT_PRESETS_PATH", "QT_PLUGIN_PATH"):
    p = pathlib.Path(profile["env"][key])
    if not p.is_absolute():
        p = prefix / p
    if not p.is_dir():
        sys.exit(f"profile: {key} -> {p} does not exist")
(prefix / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")
print("wrote", prefix / "profile.json")
PY
}

for s in "${STAGES[@]}"; do "stage_$s"; done
log "done: $PREFIX"
