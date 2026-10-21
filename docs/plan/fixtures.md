# Fixtures (frozen at Milestone 0, revised 2026-10-21)

Fixture media live in the git-ignored local store `var/fixtures/<corpus>/` (resolved through
`AIDASHVIDEO_VAR_DIR`; keep it outside ephemeral checkouts). Only recipes, hashes and
annotations are recorded here. Hashes are reproducible only for the same FFmpeg build and
speech synthesizer, so each host records its own generator identity and hashes next to the
corpus (`generator-identity.txt`, `SHA256SUMS`); a hash listed as `Missing` has a recipe but
no retained file yet.

## Consent and provenance

- All GP-01 assets are **synthetic** (FFmpeg `color`/`drawbox`/`testsrc2`/`aevalsrc`, speech from
  the host's offline synthesizer: macOS `say` on the target, `flite` in the sandbox); no person
  appears, so no consent is required. The "consenting subject" is a synthetic figure with an
  analytic ground-truth mask.
- Operator-owned footage (for V07/V08 perceptual review and V06 human word marks) must be
  accompanied by a consent note in `var/fixtures/<corpus>/CONSENT.md` before use and is never
  committed or uploaded.

## GP-01 corpus: `var/fixtures/gp01/`

Recipe: `scripts/generate_gp01_fixtures.sh` (tracked; libx264 `threads=1`, CRF 18, yuv420p,
Rec.709 tags, AAC 48 kHz stereo). It writes `SHA256SUMS`, `generator-identity.txt`,
`speech-window.txt` (silencedetect result) and `probe-*.json` next to the media.

| File | Spec | Probe expectations |
| --- | --- | --- |
| `interview.mp4` | 12 s, 1920x1080, 30/1 fps, h264 yuv420p bt709/tv, aac 48 kHz stereo; synthetic subject; speech "hello golden path" starting at 2.0 s | duration 12.000000; v start 0; a start 0 |
| `broll.mp4` | 4 s, 1920x1080, 30/1 fps, h264 yuv420p bt709/tv, **no audio stream** | duration 4.000000 |
| `music.wav` | 20 s, pcm_s16le 48 kHz stereo chord bed | duration 20.000000; integrated loudness recorded by the script |

Retained hashes:

| Host / generator | interview.mp4 | broll.mp4 | music.wav | speech window (silencedetect -40 dB, 0.3 s) |
| --- | --- | --- | --- | --- |
| linux-sandbox, FFmpeg 6.1.1-3ubuntu5 + flite (2026-10-15) | `b8220b4c…c34b` | `4968a597…6961` | `8b33d9e6…0763` | 2.196 s to 3.256 s |
| macbook-pro-m1pro-16gb, FFmpeg 9.0.2 (frozen build, sha256 `d9a15642…830f89`) + macOS `say` 27.0.1 (2026-10-21) | `c8d86af5acf9e262c7d368e1319ffe71b181878eb69c3f7e57cce9565ae7ec85` | `d2f147d8a16d29d062512c8c2d7a7bef1ff58ca590c0a67357a7339d65c873d7` | `a22fc98733b5428116b30b6899f6612ec1734ea39d1878d76d29ed2ecba503e5` | 2.015 s to 3.105 s; music -15.7 LUFS ([../evidence/milestone-0.md](../evidence/milestone-0.md)) |

Annotations:

- Speech starts at 2.000 s (delay applied to the synthesized utterance); the measured window
  must fall inside the required 2-4 s and is recorded per generator. Word boundaries are not
  human-marked (V06 corpus `annot-words` is `Missing`).
- Subject ground truth at time `t` (seconds), in source pixels, half-open boxes:
  body `x ∈ [560+40t, 880+40t)`, `y ∈ [250, 870)`; head `x ∈ [640+40t, 800+40t)`, `y ∈ [80, 240)`.
  The subject is fully visible for all 12 s (no occlusion); the union of the two boxes is the
  reference mask for V08 IoU on this corpus.
- Expected GP-01 step 3 result: 14-second sequence (12 s interview minus source seconds 6-8
  plus 4 s b-roll), i.e. 420 frames at 30 fps.

## Edge-case corpus (recipes; generated in the owning milestone)

| Corpus id | Purpose | Recipe (FFmpeg) | Ground truth / metric | Hash |
| --- | --- | --- | --- | --- |
| `vfr-60-30` | V03 VFR | `testsrc2=rate=60`, drop pattern via `select='not(mod(n,3))'` + `-vsync vfr`, 10 s | frame timestamps from `showinfo` must map to sequence frames with error ≤ 1 frame | Missing (M1) |
| `rot90` | V03 rotated portrait | 1080x1920 `testsrc2` with a display-matrix rotation of 90° | subject box coordinates after `Rotation.R90` on the `OrientedGrid` | Missing (M1) |
| `mixed-rates` | V03 mixed rates/resolutions | 24/1, 25/1, 30000/1001, 60/1 sources at 1280x720 and 3840x2160 | placement within ≤ 1 output frame | Missing (M1) |
| `bframes` | V03 B-frame reordering | libx264 `bframes=3:b-pyramid=normal`, 10 s | decode order ≠ presentation order; pts mapping exact | Missing (M1) |
| `ts-offset` | V03 nonzero stream offsets | `-output_ts_offset 7.5` and audio `adelay=1000` | `StreamProbe.start_time` subtracted once | Missing (M1) |
| `retime-hold-reverse` | V24 / M1 `TimeMap` | gp01 interview with declared hold at 3 s and reversed 4-6 s | explicit finite map; repeated source instants; no division by zero | Missing (M1) |
| `drift-10min` | V03 A/V drift | 600 s `testsrc2` + 1 kHz tone bursts every 10 s | A/V drift ≤ 1 output frame over the full file | Missing (M2) |
| `sync-tone` | V15 audio sample agreement | 1 s clicks at exact frame boundaries (48 000/30 = 1600 samples) | synthetic audio within one sample before lossy encoding | Missing (M2) |
| `hdr-hlg` | V04 refusal | `testsrc2` tagged `-color_trc arib-std-b67 -color_primaries bt2020` | import returns explicit HDR refusal, no silent conversion | Missing (M2) |
| `descriptor-coverage` | V22/V29 | `melt -query` inventory of the installed 7.42.0 build and one other build | per-service read/change/reopen evidence; digest mismatch explicit | Missing (M2) |
| `param-fuzz` | V23 | generated invalid parameter payloads for every descriptor | all `Rejected` before native construction | Missing (M2) |
| `speech-repeat` | V05 | synthesized "hello golden path" at 2 s and again at 7 s | `PhraseSelection.Ambiguous` with two candidates | Missing (M3) |
| `speech-silence` | V05 | 12 s silence (`anullsrc`) | `NoSpeech` only with completed coverage and silencedetect agreement | Missing (M3) |
| `speech-segment-only` | V05/V06 | GP-01 audio through the FFmpeg whisper filter | `SegmentTimed`, never `WordAligned` | Missing (M3) |
| `annot-words` | V06 | operator-owned speech clips with human-marked word boundaries (CSV: word, start_ms, end_ms) | ≥ 95% of nominated boundaries within 100 ms | Missing (operator) |
| `two-subjects` | V07/V19 | two synthetic figures with similar colours crossing paths | no accepted identity switch; `NeedsCorrection` on crossing; text concept yields two candidates | Missing (M4) |
| `occlusion` | V07 | figure passes behind an opaque bar for 1.5 s | `NeedsCorrection`/`AbsentSubject` span = occlusion span | Missing (M4) |
| `exit-reentry` | V07 | figure leaves frame at 4 s, re-enters at 7 s | absent span reported; re-entry obeys the instance policy | Missing (M4) |
| `shot-cut` | V07 | hard cut between two backgrounds at 6 s | tracking stops at the cut; `NeedsCorrection` | Missing (M4) |
| `annot-masks` | V08 | gp01 analytic masks (above) plus operator-reviewed real clips with annotated frames | median IoU ≥ 0.90, p5 ≥ 0.80; halo/flicker review | gp01 part present (analytic); operator part Missing (operator) |
| `meta-chars` | V11 | captions/paths containing `$(…)`, backticks, quotes, `;`, `%`, newlines, Unicode bidi controls | literal rendering or refusal; no command/network | Missing (M2) |

## Comparison metrics (definitions)

- **Mask IoU**: per annotated frame, `|pred ∧ gt| / |pred ∨ gt|` on the source oriented grid;
  report median and 5th percentile over the agreed visible-subject frames; frames inside
  reported `NeedsCorrection`/`AbsentSubject` spans are excluded from coverage and listed
  separately (V08).
- **Word boundary error**: `|pred_boundary - human_boundary|` in ms per nominated boundary;
  pass when ≥ 95% ≤ 100 ms (V06).
- **Timing error**: `|observed_frame - expected_frame|` in output frames; pass when ≤ 1 (V03, V15).
- **Loudness**: `ebur128` integrated LUFS within 1 LU of the declared target and true peak
  ≤ the declared dBTP (V16).
- **Preview latency**: wall time from edit admission to first current frame of the changed
  ten-second range; claim only if ≤ 15 s on the qualified host.

## Storage locations

| Kind | Location | Git |
| --- | --- | --- |
| fixture media and annotations | `var/fixtures/<corpus>/` (under `AIDASHVIDEO_VAR_DIR`) | ignored |
| retained evidence (doctor JSON, logs, frames, receipts) | `var/evidence/m<N>/<ID>/` | ignored |
| model assets | `<deps>/models/` | ignored |
| evidence reports | `docs/evidence/milestone-<N>.md` | committed |
