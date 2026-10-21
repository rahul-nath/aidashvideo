#!/usr/bin/env bash
# Generate the synthetic GP-01 corpus (docs/plan/fixtures.md) with the pinned FFmpeg and the
# host's offline speech synthesizer. Writes media, probes, hashes and the generator identity.
#
#   scripts/generate_gp01_fixtures.sh [<out-dir>]      default: $AIDASHVIDEO_VAR_DIR/fixtures/gp01 (else <repo>/var/fixtures/gp01)
#
# Speech: macOS `say` (target) or `flite` (Linux sandbox); neither downloads anything.
# No person appears in any file; the subject is an analytic figure (ground truth in fixtures.md).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VAR="${AIDASHVIDEO_VAR_DIR:-$REPO/var}"
OUT="${1:-$VAR/fixtures/gp01}"
mkdir -p "$OUT"
FF="${AIDASHVIDEO_FFMPEG:-}"; FP="${AIDASHVIDEO_FFPROBE:-}"
if [[ -z "$FF" ]]; then
  FF="$(cd "$REPO" && uv run --offline --no-sync python -c 'from aidashvideo.catalog.ffmpeg import locate; t=locate(); print(t.ffmpeg if t else "")')"
  FP="${FF%ffmpeg}ffprobe"
fi
[[ -x "$FF" && -x "$FP" ]] || { echo "generate_gp01_fixtures: ffmpeg/ffprobe not found (install the frozen toolchain or set AIDASHVIDEO_FFMPEG/AIDASHVIDEO_FFPROBE)" >&2; exit 1; }
TMP="$(mktemp -d "${TMPDIR:-/tmp}/gp01.XXXXXX")"; trap 'rm -rf "$TMP"' EXIT

# ---- speech: "hello golden path", 16 kHz mono, starting at exactly 2.000 s, padded to 12 s
if command -v say >/dev/null; then
  say -o "$TMP/speech.aiff" "hello golden path"; SYNTH="macOS say $(sw_vers -productVersion 2>/dev/null || true)"
  SPEECH_IN="$TMP/speech.aiff"
elif command -v flite >/dev/null; then
  flite -t "hello golden path" -o "$TMP/speech.wav"; SYNTH="flite $(flite --version 2>&1 | head -1)"
  SPEECH_IN="$TMP/speech.wav"
else
  echo "generate_gp01_fixtures: no offline speech synthesizer (say or flite)" >&2; exit 1
fi
"$FF" -hide_banner -loglevel error -y -i "$SPEECH_IN" -af "aresample=48000,adelay=2000|2000,apad=whole_dur=12" -ac 2 -ar 48000 "$TMP/speech48.wav"

# ---- interview.mp4: moving analytic subject (body + head boxes per fixtures.md) over a flat background
"$FF" -hide_banner -loglevel error -y \
  -f lavfi -i "color=c=0x6f7f8f:s=1920x1080:r=30:d=12,format=yuv420p" -i "$TMP/speech48.wav" \
  -vf "drawbox=x='560+40*t':y=250:w=320:h=620:color=0xc08060:t=fill,drawbox=x='640+40*t':y=80:w=160:h=160:color=0xe0b090:t=fill,format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv" \
  -c:v libx264 -preset medium -crf 18 -x264-params "threads=1:colorprim=bt709:transfer=bt709:colormatrix=bt709:range=tv" -pix_fmt yuv420p \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv \
  -c:a aac -b:a 160k -ar 48000 -ac 2 -shortest -movflags +faststart "$OUT/interview.mp4"

# ---- broll.mp4: 4 s testsrc2, no audio
"$FF" -hide_banner -loglevel error -y -f lavfi -i "testsrc2=s=1920x1080:r=30:d=4,format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv" \
  -c:v libx264 -preset medium -crf 18 -x264-params "threads=1:colorprim=bt709:transfer=bt709:colormatrix=bt709:range=tv" -pix_fmt yuv420p \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv -an -movflags +faststart "$OUT/broll.mp4"

# ---- music.wav: 20 s chord bed, pcm_s16le 48 kHz stereo, around -19 LUFS
"$FF" -hide_banner -loglevel error -y -f lavfi \
  -i "aevalsrc=exprs='0.12*sin(2*PI*220*t)+0.10*sin(2*PI*277.18*t)+0.08*sin(2*PI*329.63*t)+0.04*sin(2*PI*440*t)|0.12*sin(2*PI*220*t+0.3)+0.10*sin(2*PI*277.18*t)+0.08*sin(2*PI*329.63*t+0.2)+0.04*sin(2*PI*440*t)':s=48000:d=20" \
  -c:a pcm_s16le -ar 48000 -ac 2 "$OUT/music.wav"

# ---- annotations and identities
for f in interview.mp4 broll.mp4 music.wav; do
  "$FP" -v error -show_format -show_streams -of json "$OUT/$f" > "$OUT/probe-${f%.*}.json"
done
"$FF" -hide_banner -i "$OUT/interview.mp4" -af "silencedetect=n=-40dB:d=0.3" -f null - 2>&1 | grep -oE "silence_(start|end): [0-9.]+" > "$OUT/speech-window.txt" || true
"$FF" -hide_banner -i "$OUT/music.wav" -af "ebur128=framelog=verbose" -f null - 2>&1 | grep -E "^\s+I:" | tail -1 > "$OUT/music-loudness.txt" || true
{
  echo "generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host: $(uname -s) $(uname -m) $(hostname -s 2>/dev/null || true)"
  echo "ffmpeg: $("$FF" -hide_banner -version | head -1)"
  echo "ffmpeg_sha256: $(shasum -a 256 "$FF" | cut -d' ' -f1)"
  echo "speech_synthesizer: $SYNTH"
  echo "recipe: scripts/generate_gp01_fixtures.sh"
} > "$OUT/generator-identity.txt"
( cd "$OUT" && shasum -a 256 interview.mp4 broll.mp4 music.wav > SHA256SUMS )
cat "$OUT/SHA256SUMS"; cat "$OUT/speech-window.txt"; cat "$OUT/music-loudness.txt"
echo "wrote $OUT"
