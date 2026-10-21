#!/usr/bin/env bash
# Build the FROZEN core toolchain identities (docs/plan/runtime-profile.json) in the Linux
# development sandbox, rootlessly, into .deps/frozen:
#
#   whisper.cpp 1.9.5 (bundled ggml)  -> libwhisper + whisper-cli
#   FFmpeg 9.0.2 --enable-whisper     -> ffmpeg/ffprobe + libav* (libavcodec 63 ...)
#   MLT 7.42.0 (+ Python bindings)    -> melt, libmlt7, modules, mlt7 python module
#
# Sources: operator-uploaded tarballs in .deps/uploads (hash-pinned below) and the FFmpeg
# 9.0.2 orig tarball from the Debian archive (hash-pinned). Build-time headers/tools come
# from the pinned Ubuntu noble archives in toolchain/sysroot-noble-amd64.lock, extracted into
# .deps/sysroot (never installed system-wide).
#
# usage: scripts/build_frozen_toolchain.sh [--allow-download] [sysroot|whisper|ffmpeg|mlt|profile ...]
#   default: all stages; each stage is skipped when its .stamp exists.
#   --allow-download is the explicit acquisition grant for the archive fetches (sysroot, ffmpeg src).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Install location: AIDASHVIDEO_DEPS_DIR, else the user data dir, else <repo>/.deps (see
# aidashvideo.catalog.paths.deps_dir). Keep it OUTSIDE synced/ephemeral checkouts.
DEPS="${AIDASHVIDEO_DEPS_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/aidashvideo/deps}"
UPLOADS="$DEPS/uploads"
SYSROOT="$DEPS/sysroot"
SRC="$DEPS/src"
PREFIX="$DEPS/frozen"
CACHE="$DEPS/cache/debs"
LOCK="$REPO/toolchain/sysroot-noble-amd64.lock"
ARCHIVE_BASE="${AIDASH_UBUNTU_ARCHIVE:-http://archive.ubuntu.com/ubuntu}"
DEBIAN_BASE="${AIDASH_DEBIAN_ARCHIVE:-https://deb.debian.org/debian}"
PATCHELF="${PATCHELF:-$REPO/.venv/bin/patchelf}"
JOBS="${JOBS:-$(nproc)}"
LIBDIR_TRIPLET="x86_64-linux-gnu"

# Pinned source identities
WHISPER_TAR="whisper.cpp-1.9.5.tar";  WHISPER_SHA="a2e9fd8dd76d028a747042017ef6b9db605b95e19c45fbd498f8eb309794e4c3"
MLT_TAR="mlt-7.42.0.tar";            MLT_SHA="94c219b256d476dfbf5f7117fcc0d3dec3675fa6d4cdfe51db2eca5a953d0ed2"
FFMPEG_TAR="ffmpeg_9.0.2.orig.tar.xz"; FFMPEG_SHA="8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"
FFMPEG_URL="$DEBIAN_BASE/pool/main/f/ffmpeg/$FFMPEG_TAR"

die() { echo "build_frozen_toolchain: error: $*" >&2; exit 1; }
log() { echo "== $*"; }
check_sha() { echo "$2  $1" | sha256sum -c --quiet - >/dev/null 2>&1; }

ALLOW_DOWNLOAD=0
STAGES=()
for a in "$@"; do
  case "$a" in
    --allow-download) ALLOW_DOWNLOAD=1 ;;
    sysroot|whisper|ffmpeg|mlt|profile) STAGES+=("$a") ;;
    *) die "unknown argument $a" ;;
  esac
done
[[ ${#STAGES[@]} -eq 0 ]] && STAGES=(sysroot whisper ffmpeg mlt profile)
[[ "$(uname -s)-$(uname -m)" == "Linux-x86_64" ]] || die "sandbox recipe is Linux x86_64 only"
[[ -x "$PATCHELF" ]] || die "patchelf not found at $PATCHELF (uv sync first)"
mkdir -p "$CACHE" "$SRC" "$PREFIX"

SYSLIB="$SYSROOT/usr/lib/$LIBDIR_TRIPLET"
export PATH="$PREFIX/bin:$SYSROOT/usr/bin:$PATH"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig:$SYSLIB/pkgconfig:$SYSROOT/usr/share/pkgconfig"
export LD_LIBRARY_PATH="$PREFIX/lib:$SYSLIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export SWIG_LIB="$SYSROOT/usr/share/swig4.0"
export CPATH="$SYSROOT/usr/include:$SYSROOT/usr/include/$LIBDIR_TRIPLET"
export LIBRARY_PATH="$SYSLIB:$PREFIX/lib"
RPATH="$PREFIX/lib:$SYSLIB"

stage_sysroot() {
  [[ -f "$SYSROOT/.stamp" ]] && { log "sysroot: present"; return; }
  log "sysroot: extracting $(grep -vc '^#' "$LOCK") pinned archives"
  rm -rf "$SYSROOT.staging"; mkdir -p "$SYSROOT.staging"
  while read -r pkg ver size sha path; do
    [[ -z "$pkg" || "$pkg" == \#* ]] && continue
    deb="$CACHE/$(basename "$path")"
    if ! { [[ -f "$deb" ]] && check_sha "$deb" "$sha"; }; then
      rm -f "$deb"
      [[ $ALLOW_DOWNLOAD == 1 ]] || die "$pkg $ver not cached (pass --allow-download)"
      curl -fsSL --retry 3 -o "$deb.part" "$ARCHIVE_BASE/$path" || die "download failed: $pkg"
      check_sha "$deb.part" "$sha" || { rm -f "$deb.part"; die "$pkg sha256 mismatch"; }
      mv "$deb.part" "$deb"
    fi
    dpkg-deb -x "$deb" "$SYSROOT.staging"
  done < "$LOCK"
  # Broken relative symlinks (dev .so -> runtime lib that lives in the system) -> absolute.
  while IFS= read -r -d '' link; do
    tgt="$(readlink "$link")"; dir="$(dirname "$link")"
    if [[ ! -e "$dir/$tgt" ]]; then
      rel="${dir#"$SYSROOT.staging"}"
      [[ -e "$rel/$tgt" ]] && ln -sf "$rel/$tgt" "$link"
    fi
  done < <(find "$SYSROOT.staging" -type l -print0)
  # pkg-config files: point prefix at the sysroot.
  find "$SYSROOT.staging" -name '*.pc' -print0 | xargs -0 sed -i -E "s#^prefix=/usr#prefix=$SYSROOT/usr#; s#([=: ])/usr/(include|lib|share)#\1$SYSROOT/usr/\2#g"
  # cmake config files with absolute /usr/include or /usr/lib paths.
  find "$SYSROOT.staging" -name '*.cmake' -print0 | xargs -0 sed -i -E "s#\"/usr/(include|lib)#\"$SYSROOT/usr/\1#g; s#;/usr/(include|lib)#;$SYSROOT/usr/\1#g"
  # Tools (swig, nasm, moc, ...) and libs inside the sysroot resolve their own libs first.
  local n=0
  while IFS= read -r -d '' f; do
    if head -c 4 "$f" | grep -q $'\x7fELF'; then
      "$PATCHELF" --set-rpath "$SYSROOT.staging/usr/lib/$LIBDIR_TRIPLET:$SYSLIB" "$f" 2>/dev/null && n=$((n+1)) || true
    fi
  done < <(find "$SYSROOT.staging" -type f \( -name '*.so' -o -name '*.so.*' -o -path '*/bin/*' -o -path '*/libexec/*' \) -print0)
  log "sysroot: patched RUNPATH on $n ELF files"
  mv "$SYSROOT.staging" "$SYSROOT"
  # RUNPATHs were set with the staging path; rewrite them now that the tree moved.
  while IFS= read -r -d '' f; do
    head -c 4 "$f" | grep -q $'\x7fELF' && "$PATCHELF" --set-rpath "$SYSLIB" "$f" 2>/dev/null || true
  done < <(find "$SYSROOT" -type f \( -name '*.so' -o -name '*.so.*' -o -path '*/bin/*' -o -path '*/libexec/*' \) -print0)
  sha256sum "$LOCK" | cut -d' ' -f1 > "$SYSROOT/.stamp"
}

unpack() { # tarball dest-dir-name
  local tar="$1" name="$2"
  [[ -d "$SRC/$name" ]] && return
  mkdir -p "$SRC"; tar -xf "$tar" -C "$SRC"
  [[ -d "$SRC/$name" ]] || die "unexpected layout in $tar"
}

stage_whisper() {
  [[ -f "$PREFIX/.stamp-whisper" ]] && { log "whisper.cpp: present"; return; }
  check_sha "$UPLOADS/$WHISPER_TAR" "$WHISPER_SHA" || die "missing/mismatched $UPLOADS/$WHISPER_TAR"
  unpack "$UPLOADS/$WHISPER_TAR" whisper.cpp-1.9.5
  log "whisper.cpp 1.9.5: configure + build"
  cmake -S "$SRC/whisper.cpp-1.9.5" -B "$SRC/whisper.cpp-1.9.5/build" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$PREFIX" -DBUILD_SHARED_LIBS=ON -DWHISPER_BUILD_TESTS=OFF \
    -DWHISPER_BUILD_EXAMPLES=ON -DWHISPER_BUILD_SERVER=OFF -DGGML_NATIVE=OFF -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON \
    -DCMAKE_INSTALL_RPATH="$RPATH" > "$SRC/whisper.configure.log"
  cmake --build "$SRC/whisper.cpp-1.9.5/build" -j"$JOBS" > "$SRC/whisper.build.log" 2>&1
  cmake --install "$SRC/whisper.cpp-1.9.5/build" > "$SRC/whisper.install.log"
  [[ -f "$PREFIX/lib/pkgconfig/whisper.pc" ]] || die "whisper.pc not installed"
  echo "$WHISPER_SHA" > "$PREFIX/.stamp-whisper"
}

stage_ffmpeg() {
  [[ -f "$PREFIX/.stamp-ffmpeg" ]] && { log "ffmpeg: present"; return; }
  local tar="$DEPS/cache/$FFMPEG_TAR"
  if ! { [[ -f "$tar" ]] && check_sha "$tar" "$FFMPEG_SHA"; }; then
    rm -f "$tar"
    [[ $ALLOW_DOWNLOAD == 1 ]] || die "$FFMPEG_TAR not cached (pass --allow-download)"
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
      --extra-cflags="-I$SYSROOT/usr/include -I$PREFIX/include" \
      --extra-ldflags="-L$SYSLIB -L$PREFIX/lib -Wl,-rpath,$PREFIX/lib -Wl,-rpath,$SYSLIB" \
      --disable-doc --disable-ffplay > "$SRC/ffmpeg.configure.log" 2>&1 ) || { tail -30 "$SRC/ffmpeg-9.0.2/ffbuild/config.log"; die "ffmpeg configure failed"; }
  make -C "$SRC/ffmpeg-9.0.2" -j"$JOBS" > "$SRC/ffmpeg.build.log" 2>&1 || { tail -30 "$SRC/ffmpeg.build.log"; die "ffmpeg build failed"; }
  make -C "$SRC/ffmpeg-9.0.2" install > "$SRC/ffmpeg.install.log" 2>&1
  "$PREFIX/bin/ffmpeg" -hide_banner -filters 2>/dev/null | grep -q ' whisper ' || die "built ffmpeg lacks the whisper filter"
  echo "$FFMPEG_SHA" > "$PREFIX/.stamp-ffmpeg"
}

stage_mlt() {
  [[ -f "$PREFIX/.stamp-mlt" ]] && { log "mlt: present"; return; }
  check_sha "$UPLOADS/$MLT_TAR" "$MLT_SHA" || die "missing/mismatched $UPLOADS/$MLT_TAR"
  unpack "$UPLOADS/$MLT_TAR" mlt-7.42.0
  log "MLT 7.42.0: configure + build (Python bindings for $(python3 --version))"
  cmake -S "$SRC/mlt-7.42.0" -B "$SRC/mlt-7.42.0/build" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_PREFIX_PATH="$PREFIX;$SYSROOT/usr;$SYSROOT/usr/lib/$LIBDIR_TRIPLET/cmake" \
    -DCMAKE_INSTALL_RPATH="$RPATH" -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
    -DSWIG_PYTHON=ON -DPython3_EXECUTABLE="$(command -v python3)" \
    -DMOD_QT6=ON -DMOD_MOVIT=ON -DMOD_OPENCV=OFF -DMOD_GLAXNIMATE_QT6=OFF -DMOD_NDI=OFF -DMOD_SPATIALAUDIO=OFF \
    -DMOD_DECKLINK=ON -DMOD_RNNOISE=OFF -DMOD_PLACEBO=ON -DMOD_OPENFX=ON -DMOD_SDL1=OFF \
    > "$SRC/mlt.configure.log" 2>&1 || { tail -40 "$SRC/mlt.configure.log"; die "mlt configure failed"; }
  cmake --build "$SRC/mlt-7.42.0/build" -j"$JOBS" > "$SRC/mlt.build.log" 2>&1 || { tail -40 "$SRC/mlt.build.log"; die "mlt build failed"; }
  cmake --install "$SRC/mlt-7.42.0/build" > "$SRC/mlt.install.log" 2>&1
  fix_rpaths
  echo "$MLT_SHA" > "$PREFIX/.stamp-mlt"
}

fix_rpaths() {
  # Everything installed under the prefix resolves the prefix first, then the sysroot.
  local n=0
  while IFS= read -r -d '' f; do
    if head -c 4 "$f" | grep -q $'\x7fELF'; then
      "$PATCHELF" --set-rpath "$RPATH" "$f" 2>/dev/null && n=$((n+1)) || true
    fi
  done < <(find "$PREFIX/bin" "$PREFIX/lib" -type f \( -name '*.so' -o -name '*.so.*' -o -path '*/bin/*' \) -print0)
  log "prefix: RUNPATH set on $n ELF files"
}

stage_profile() {
  local pydir
  pydir="$(find "$PREFIX/lib" -maxdepth 3 -name 'mlt7.py' -printf '%h' -quit)"
  [[ -n "$pydir" ]] || die "mlt7.py not found under $PREFIX/lib"
  python3 - "$PREFIX" "$pydir" "$SYSROOT" <<'PY'
import json, sys, pathlib, os
prefix, pydir, sysroot = map(pathlib.Path, sys.argv[1:4])
rel = lambda p: os.path.relpath(p, prefix)
profile = {
    "schema": "aidashvideo.toolchain.mlt/1",
    "profile_id": "mlt-7.42.0-frozen",
    "mlt_version": "7.42.0",
    "source": "mlt-7.42.0 source build (scripts/build_frozen_toolchain.sh) against FFmpeg 9.0.2 + whisper.cpp 1.9.5",
    "lock_sha256": "",
    "paths": {"melt": "bin/melt", "lib_dir": "lib", "python_dir": rel(pydir), "ffmpeg": "bin/ffmpeg", "ffprobe": "bin/ffprobe"},
    "plugins": {"frei0r": "1.8.0 (Ubuntu noble frei0r-plugins; plan pins 3.6.0 - Conflicting until rebuilt)"},
    "env": {
        "MLT_REPOSITORY": "lib/mlt-7",
        "MLT_DATA": "share/mlt-7",
        "MLT_PROFILES_PATH": "share/mlt-7/profiles",
        "MLT_PRESETS_PATH": "share/mlt-7/presets",
        # Qt6 module (titles/captions) renders headless through the offscreen QPA plugin.
        "QT_QPA_PLATFORM": "offscreen",
        "QT_PLUGIN_PATH": str(sysroot / "usr/lib/x86_64-linux-gnu/qt6/plugins"),
    },
}
# Plugin directories: Ubuntu noble has frei0r 1.8.0 (the plan pins 3.6.0; recorded as Conflicting);
# reuse a rootless tree when present, else the system, else omit (melt still runs).
deps = prefix.parent
for key, sub in (("FREI0R_PATH", "frei0r-1"), ("LADSPA_PATH", "ladspa")):
    for cand in (deps / "mlt/root/usr/lib" / sub, pathlib.Path("/usr/lib") / sub):
        if cand.is_dir():
            profile["env"][key] = str(cand)
            break
(prefix / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")
print("wrote", prefix / "profile.json")
PY
}

for s in "${STAGES[@]}"; do "stage_$s"; done
log "done: $PREFIX"
