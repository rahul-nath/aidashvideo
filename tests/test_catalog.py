"""Capability-catalog units: pins, FFmpeg listing parsers, asset admission, doctor in isolation.

Every test is host-independent: no real ffmpeg/melt/mlx is required, temp dirs stand in
for `.deps`, and the doctor is exercised with an empty PATH so every supplier is Missing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from aidashvideo.catalog import ffmpeg, mlt, models, pins
from aidashvideo.catalog.doctor import main as doctor_main
from aidashvideo.catalog.offline import provider_environment
from aidashvideo.catalog.status import Readiness

ENCODERS = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC
 A....D aac                  AAC (Advanced Audio Coding)
"""
FILTERS = """Filters:
  T.. = Timeline support
 ... abench            A->A       Benchmark part of a filtergraph.
 TSC boxblur           V->V       Blur the input.
 ..C whisper           A->A       Transcribe audio using whisper.cpp.
"""
MUXERS = """ Muxers:
 D. = Demuxing supported
 --
  E mp4             MP4 (MPEG-4 Part 14)
  E framemd5        Per-frame MD5 testing
"""
MUXERS_V9 = """Formats:
 D.. = Demuxing supported
 .E. = Muxing supported
 ..d = Is a device
 ---
  E  mp4             MP4 (MPEG-4 Part 14)
  E  framemd5        Per-frame MD5 testing
"""
REPO_ASSET = models.Asset(
    id="demo-hf",
    profile="demo",
    kind="hf-repo",
    license="test",
    repo_id="acme/demo",
    required_files=("config.json", "model.safetensors"),
)
FILE_ASSET = models.Asset(
    id="demo-file",
    profile="demo",
    kind="file",
    license="test",
    relpath="demo/model.bin",
)


def _fake_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "config.json").write_text('{"model_type": "demo"}')
    (path / "model.safetensors").write_bytes(b"\0" * 64)
    (path / ".cache").mkdir()
    (path / ".cache" / "junk").write_text("ignored")
    return path


# ----------------------------------------------------------------------------- pins


def test_frozen_profile_is_default_and_planned() -> None:
    frozen = pins.load_pins("frozen")
    assert pins.DEFAULT_PROFILE == "frozen" and frozen.kind == "planned"
    assert (frozen.python_version, frozen.ffmpeg.version, frozen.mlt.version) == (
        "3.14",
        "9.0.2",
        "7.42.0",
    )
    assert "whisper" in frozen.ffmpeg.required_filters
    assert pins.available_profiles() == ["frozen"]


def test_unknown_profile_is_an_error() -> None:
    with pytest.raises(FileNotFoundError, match="unknown toolchain profile"):
        pins.load_pins("no-such-profile")


# ----------------------------------------------------------------------------- ffmpeg parsing


def test_ffmpeg_listing_parsers() -> None:
    assert ffmpeg.parse_codec_list(ENCODERS) == ["libx264", "aac"]
    assert ffmpeg.parse_filter_list(FILTERS) == ["abench", "boxblur", "whisper"]
    assert ffmpeg.parse_format_list(MUXERS) == ["mp4", "framemd5"]
    assert ffmpeg.parse_format_list(MUXERS_V9) == ["mp4", "framemd5"]
    assert ffmpeg.parse_version("ffmpeg version 9.0.2 Copyright") == "9.0.2"


def test_capability_digest_is_order_independent() -> None:
    a = ffmpeg.capability_digest({"filters": ["b", "a"], "encoders": ["x"]})
    b = ffmpeg.capability_digest({"encoders": ["x"], "filters": ["a", "b", "a"]})
    assert a == b and len(a) == 64


def test_ffmpeg_missing_is_typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("AIDASHVIDEO_DEPS_DIR", str(tmp_path))
    monkeypatch.delenv("AIDASHVIDEO_FFMPEG", raising=False)
    monkeypatch.delenv("AIDASHVIDEO_FFPROBE", raising=False)
    status = ffmpeg.probe(pins.load_pins("frozen").ffmpeg, functional=False)
    assert status.readiness is Readiness.MISSING
    assert "not found" in status.detail


# ----------------------------------------------------------------------------- mlt


def test_mlt_missing_profile_is_typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIDASHVIDEO_DEPS_DIR", str(tmp_path))
    status = mlt.probe(pins.load_pins("frozen").mlt, functional=False)
    assert status.readiness is Readiness.MISSING
    assert "docs/plan/commands.md" in status.detail
    with pytest.raises(mlt.MltUnavailableError):
        mlt.import_mlt()


def test_mlt_catalog_digest_is_order_independent() -> None:
    assert mlt.catalog_digest({"filters": ["b", "a"]}) == mlt.catalog_digest(
        {"filters": ["a", "b"]}
    )


# ----------------------------------------------------------------------------- model assets


def test_manifest_names_only_operator_supplied_assets() -> None:
    assets = {a.id: a for a in models.load_manifest()}
    assert set(assets) == {"sam31-mlx", "clip-tokenizer", "whisper-ggml-model"}
    assert assets["clip-tokenizer"].repo_id == "openai/clip-vit-base-patch32"
    assert assets["sam31-mlx"].repo_id == "mlx-community/sam3.1-bf16"
    assert all(a.consumer.startswith("aidashvideo.analysis.") for a in assets.values())


def test_admit_then_resolve_offline_through_isolated_hub_cache(tmp_path: Path) -> None:
    root = tmp_path / "models"
    assert models.asset_status(REPO_ASSET, root).readiness is Readiness.MISSING
    status = models.admit(REPO_ASSET, _fake_repo(tmp_path / "src"), root)
    assert status.readiness is Readiness.VERIFIED, status.detail
    record = json.loads((root / models.ADMISSIONS_FILE).read_text())["demo-hf"]
    assert set(record["files"]) == {"config.json", "model.safetensors"}
    assert record["revision_is_upstream"] is False
    snap = models.hf_snapshot_dir("acme/demo", root / "hf-hub")
    assert snap is not None and (snap / "config.json").is_file()
    # Layout is the hub-cache layout huggingface_hub resolves with HF_HUB_OFFLINE=1.
    assert snap.parent.parent.name == "models--acme--demo"
    assert (snap.parent.parent / "refs" / "main").read_text() == snap.name


def test_admission_detects_tampering_and_missing_files(tmp_path: Path) -> None:
    root = tmp_path / "models"
    models.admit(REPO_ASSET, _fake_repo(tmp_path / "src"), root)
    snap = models.hf_snapshot_dir("acme/demo", root / "hf-hub")
    assert snap is not None
    (snap / "model.safetensors").write_bytes(b"tampered")
    assert models.asset_status(REPO_ASSET, root).readiness is Readiness.CONFLICTING
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    (incomplete / "config.json").write_text("{}")
    with pytest.raises(FileNotFoundError, match=r"model\.safetensors"):
        models.admit(REPO_ASSET, incomplete, tmp_path / "other")
    assert not (tmp_path / "other" / models.ADMISSIONS_FILE).exists()


def test_file_asset_admission_and_pin_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "models"
    src = tmp_path / "ggml.bin"
    src.write_bytes(b"weights")
    assert models.admit(FILE_ASSET, src, root).readiness is Readiness.VERIFIED
    pinned = models.Asset(
        id="p", profile="demo", kind="file", license="t", relpath="p/x.bin", sha256="0" * 64
    )
    with pytest.raises(ValueError, match="not admitted"):
        models.admit(pinned, src, root)
    assert not (root / "p" / "x.bin").exists()


def test_provider_environment_is_offline_and_isolated() -> None:
    env = provider_environment({"HF_TOKEN": "secret", "PATH": "/bin"})
    assert env["HF_HUB_OFFLINE"] == "1" and env["TRANSFORMERS_OFFLINE"] == "1"
    assert "HF_TOKEN" not in env
    assert env["HF_HUB_CACHE"].endswith("models/hf-hub")


# ----------------------------------------------------------------------------- doctor


def test_doctor_with_nothing_installed_reports_missing_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """V14 control: core boot/inspection works and reports truthfully with no suppliers."""
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("AIDASHVIDEO_DEPS_DIR", str(tmp_path))
    monkeypatch.delenv("AIDASHVIDEO_PROFILE", raising=False)
    rc = doctor_main(["--json", "--quick", "--no-providers"])
    report = json.loads(capsys.readouterr().out)
    assert rc == 1 and report["core_verified"] is False and report["profile"] == "frozen"
    by = {c["component"]: c for c in report["components"]}
    assert by["ffmpeg"]["readiness"] == "Missing" and by["mlt"]["readiness"] == "Missing"
    assert by["host"]["optional"] is True  # target binding is reported, never hidden
    assert {c["readiness"] for c in report["components"]} <= {"Verified", "Missing", "Conflicting"}
    assert all(
        by[f"asset:{a}"]["readiness"] == "Missing"
        for a in ("sam31-mlx", "clip-tokenizer", "whisper-ggml-model")
    )


def test_doctor_cli_is_a_real_entry_point() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "aidashvideo.catalog.doctor", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0 and "Verified | Missing | Conflicting" in proc.stdout


# ----------------------------------------------------------------------------- deps dir


def test_deps_dir_prefers_override_then_installed_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aidashvideo.catalog import paths

    repo = tmp_path / "repo"
    (repo / "src" / "aidashvideo" / "catalog").mkdir(parents=True)
    data_home = tmp_path / "xdg"
    monkeypatch.setenv("AIDASHVIDEO_REPO_ROOT", str(repo))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.delenv("AIDASHVIDEO_DEPS_DIR", raising=False)

    # nothing installed anywhere: the repository default is named (so Missing points there)
    assert paths.deps_dir() == repo / ".deps"

    # an install in the user data dir is found when the repo has none
    user = data_home / "aidashvideo" / "deps"
    (user / "models").mkdir(parents=True)
    assert paths.deps_dir() == repo / ".deps"  # an empty models dir is not an install
    (user / "models" / "admissions.json").write_text("{}")
    assert paths.deps_dir() == user

    # a repo-local install wins over the user data dir
    (repo / ".deps" / "frozen").mkdir(parents=True)
    (repo / ".deps" / "frozen" / "profile.json").write_text("{}")
    assert paths.deps_dir() == repo / ".deps"

    # the explicit override wins over everything
    monkeypatch.setenv("AIDASHVIDEO_DEPS_DIR", str(tmp_path / "explicit"))
    assert paths.deps_dir() == (tmp_path / "explicit").resolve()
