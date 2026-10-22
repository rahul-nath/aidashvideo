"""Live checks of the installed toolchain and admitted model assets on this host.

These tests use the real binaries under ``.deps/frozen`` and the real assets under
``.deps/models``. Each one skips with the exact missing proof when its supplier is not
installed; a skip is a named blocker, never success (I8, I10). Select with ``-m live``.

    uv run --offline --no-sync pytest -q -p no:cacheprovider -m live
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from aidashvideo.catalog import ffmpeg as ffmpeg_cat
from aidashvideo.catalog import mlt as mlt_cat
from aidashvideo.catalog import models as models_cat
from aidashvideo.catalog.offline import provider_environment
from aidashvideo.catalog.paths import models_dir
from aidashvideo.catalog.pins import load_pins
from aidashvideo.catalog.status import Readiness

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[1]


def _ffmpeg_tools() -> ffmpeg_cat.FfmpegTools:
    tools = ffmpeg_cat.locate()
    if tools is None:
        pytest.skip("ffmpeg/ffprobe not installed (scripts/build_toolchain_macos.sh)")
    return tools


def _asset_or_skip(asset_id: str) -> Path:
    asset = {a.id: a for a in models_cat.load_manifest()}[asset_id]
    status = models_cat.asset_status(asset)
    if status.readiness is not Readiness.VERIFIED:
        pytest.skip(f"asset {asset_id} not admitted: {status.detail}")
    if asset.kind == "file":
        return models_dir() / asset.relpath
    snap = models_cat.hf_snapshot_dir(asset.repo_id, models_dir() / "hf-hub")
    assert snap is not None
    return snap


# ----------------------------------------------------------------------------- ffmpeg


def test_ffmpeg_matches_pins_with_required_capabilities() -> None:
    _ffmpeg_tools()
    status = ffmpeg_cat.probe(load_pins().ffmpeg, functional=True)
    assert status.readiness is Readiness.VERIFIED, status.detail
    assert status.facts["version"] == load_pins().ffmpeg.version


def test_whisper_filter_transcribes_synthesized_speech(tmp_path: Path) -> None:
    """Timed speech: `say` (macOS) or `flite` (Linux) -> 16 kHz mono -> `whisper` filter -> JSON."""
    tools = _ffmpeg_tools()
    model = _asset_or_skip("whisper-ggml-model")
    wav = tmp_path / "speech.wav"
    out = tmp_path / "whisper.json"
    common = ["-af", "adelay=2000|2000,apad=pad_dur=2", "-ar", "16000", "-ac", "1", str(wav)]
    synth_tool = str(tools.ffmpeg)
    if shutil.which("say") is not None:
        aiff = tmp_path / "speech.aiff"
        subprocess.run(["say", "-o", str(aiff), "hello golden path"], check=True, timeout=60)
        synth = ["-i", str(aiff)]
    else:
        # Any ffmpeg with the flite filter may synthesize; transcription uses the frozen build.
        candidates = [str(tools.ffmpeg), *(p for p in [shutil.which("ffmpeg")] if p)]
        synth_tool = next(
            (
                c
                for c in candidates
                if " flite "
                in subprocess.run(
                    [c, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=60
                ).stdout
            ),
            "",
        )
        if not synth_tool:
            pytest.skip(
                "no offline speech synthesizer (macOS `say` or FFmpeg `flite`) on this host"
            )
        synth = ["-f", "lavfi", "-i", "flite=text='hello golden path':voice=slt"]
    subprocess.run(
        [synth_tool, "-hide_banner", "-loglevel", "error", "-y", *synth, *common],
        check=True,
        timeout=60,
    )
    proc = subprocess.run(
        [
            str(tools.ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(wav),
            "-af",
            f"whisper=model={model}:language=en:queue=3:destination={out}:format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    segments = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert segments, "whisper filter produced no segments"
    text = " ".join(str(s.get("text", "")) for s in segments).lower()
    assert "golden" in text, text
    first = segments[0]
    assert {"start", "end", "text"} <= set(first), first
    # start/end are milliseconds; speech begins after the 2 s delay and the first segment
    # must cover it (start is quantised to the queue window, so only the end is informative)
    assert float(first["end"]) >= 2000 and float(first["start"]) <= 2500, first


# ----------------------------------------------------------------------------- mlt


def test_mlt_native_probe_renders_and_decodes() -> None:
    try:
        mlt_cat.load_profile()
    except mlt_cat.MltUnavailableError as exc:
        pytest.skip(str(exc))
    status = mlt_cat.probe(load_pins().mlt, functional=True)
    assert status.readiness is Readiness.VERIFIED, status.detail
    assert status.facts["render"].startswith("1920x1080@30/1 30 frames decoded")
    assert int(status.facts["filters_count"]) > 100


# ----------------------------------------------------------------------------- sam 3.1


_SAM_SMOKE = r"""
import json, os, sys, time, pathlib
import numpy as np
from PIL import Image, ImageDraw
import mlx.core as mx
from mlx_vlm.utils import load_model
from mlx_vlm.models.sam3.generate import Sam3Predictor
from mlx_vlm.models.sam3_1.processing_sam3_1 import Sam31Processor
snap = pathlib.Path(sys.argv[1])
t0 = time.time()
model = load_model(snap)
processor = Sam31Processor.from_pretrained(str(snap))
load_s = time.time() - t0
img = Image.new("RGB", (640, 360), (240, 240, 240))
ImageDraw.Draw(img).ellipse((200, 80, 440, 320), fill=(200, 30, 30))
pred = Sam3Predictor(model, processor, score_threshold=0.3)
t1 = time.time()
res = pred.predict(img, text_prompt="a red circle")
masks = [np.asarray(m) for m in res.masks]
print(json.dumps({
    "metal": bool(mx.metal.is_available()),
    "device": str(mx.default_device()),
    "load_s": load_s,
    "predict_s": time.time() - t1,
    "scores": [float(s) for s in res.scores],
    "boxes": [[float(v) for v in b] for b in res.boxes],
    "mask_shapes": [list(m.shape) for m in masks],
    "mask_on": [int((m > 0).sum()) for m in masks],
    "peak_gb": mx.get_peak_memory() / 1e9,
}))
"""


def test_sam31_mlx_segments_synthetic_subject_offline_on_metal() -> None:
    """Loads the admitted SAM 3.1 snapshot with HF_HUB_OFFLINE=1 and segments a red disc."""
    if sys.platform != "darwin":
        pytest.skip("SAM 3.1 MLX profile is macOS arm64 only")
    pytest.importorskip("mlx.core", reason="extra `sam31-mlx` not installed")
    pytest.importorskip("mlx_vlm", reason="extra `sam31-mlx` not installed")
    snap = _asset_or_skip("sam31-mlx")
    _asset_or_skip("clip-tokenizer")
    env = provider_environment()
    assert env["HF_HUB_OFFLINE"] == "1"
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _SAM_SMOKE, str(snap)],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    result = json.loads([ln for ln in proc.stdout.splitlines() if ln.startswith("{")][-1])
    assert result["metal"] is True and result["device"].startswith("Device(gpu")
    assert result["scores"], "no detection for the synthetic subject"
    assert max(result["scores"]) >= 0.5
    best = max(range(len(result["scores"])), key=lambda i: result["scores"][i])
    x0, y0, x1, y1 = result["boxes"][best]
    assert abs(x0 - 200) < 20 and abs(y0 - 80) < 20 and abs(x1 - 440) < 20 and abs(y1 - 320) < 20
    assert result["mask_shapes"][best] == [360, 640]
    disc_area = 3.14159 * 120 * 120
    assert 0.8 * disc_area < result["mask_on"][best] < 1.2 * disc_area
    assert result["peak_gb"] < 12.0, "Metal peak memory beyond the 16 GB host budget"


def test_provider_environment_blocks_hub_access(tmp_path: Path) -> None:
    """A repo that is not admitted must fail offline, never fetch (I8)."""
    pytest.importorskip("huggingface_hub")
    code = (
        "from huggingface_hub import snapshot_download\n"
        "try:\n"
        "    snapshot_download('openai/clip-vit-large-patch14')\n"
        "except Exception as exc:\n"
        "    print('BLOCKED', type(exc).__name__)\n"
        "else:\n"
        "    print('FETCHED')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", code],
        env=provider_environment(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "BLOCKED" in proc.stdout, proc.stdout + proc.stderr
    assert not os.path.isdir(models_dir() / "hf-hub" / "models--openai--clip-vit-large-patch14")
