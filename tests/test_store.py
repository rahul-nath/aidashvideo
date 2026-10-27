"""Store (M1b): probe receipt parsing with exact rationals, source identity, availability,
verified job clones and untouched originals (I1, V03 source contracts, V10).

Probe parsing is exercised on synthetic ffprobe JSON so the tests are host-independent;
one test uses the installed ffprobe on a generated file when an ffmpeg is present and
records that tool's identity (the sandbox's FFmpeg is not the frozen 9.0.2).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from aidashvideo.ledger import ContractError, ProjectGrant, RejectCode, ScopedLocator, Sha256
from aidashvideo.ledger.ids import ProjectId
from aidashvideo.store import (
    AudioStream,
    Changed,
    CloneRefused,
    ConstantRate,
    FfprobeProber,
    Hdr,
    HdrTransfer,
    ImportRefused,
    Missing,
    Present,
    ProbeFailed,
    ProbeReceipt,
    ProbeToolMissing,
    Rotation,
    Sdr709,
    SourceIdentity,
    Store,
    ToolIdentity,
    Untagged,
    VerifiedClone,
    VfrTable,
    VideoStream,
    hash_file,
    receipt_from_ffprobe,
)
from aidashvideo.store.probe import frame_timing_from_pts
from ledger_support import ACTOR, open_store

pytestmark = pytest.mark.store

TOOL = ToolIdentity("ffprobe", "test-9.0.2", Sha256("ab" * 32))


def _video(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "index": 0,
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "sample_aspect_ratio": "1:1",
        "r_frame_rate": "30/1",
        "avg_frame_rate": "30/1",
        "time_base": "1/15360",
        "start_pts": 0,
        "start_time": "0.000000",
        "has_b_frames": 0,
        "color_transfer": "bt709",
        "color_primaries": "bt709",
    }
    base.update(overrides)
    return base


def _audio(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "index": 1,
        "codec_type": "audio",
        "codec_name": "aac",
        "sample_rate": "48000",
        "channels": 2,
        "channel_layout": "stereo",
        "time_base": "1/48000",
        "start_pts": 0,
        "start_time": "0.000000",
    }
    base.update(overrides)
    return base


def _frames(pts: list[int]) -> dict[str, object]:
    return {"frames": [{"pts": p, "best_effort_timestamp": p} for p in pts]}


def _probe(streams: list[dict[str, object]], duration: str = "12.000000") -> dict[str, object]:
    return {"streams": streams, "format": {"duration": duration}}


# ----------------------------------------------------------------------------- parsing


def test_constant_rate_receipt_is_exact_and_content_addressed() -> None:
    pts = [i * 512 for i in range(360)]  # 30 fps in a 1/15360 timebase
    receipt = receipt_from_ffprobe(_probe([_video(), _audio()]), {0: _frames(pts)}, TOOL)
    video = receipt.video_streams()[0]
    audio = receipt.audio_streams()[0]
    assert video.fps == Fraction(30) and video.timebase == Fraction(1, 15360)
    assert video.vfr == ConstantRate() and video.color == Sdr709()
    assert video.rotation is Rotation.R0 and video.sar == 1 and not video.has_bframes
    assert audio == AudioStream(1, "aac", 48000, 2, "stereo", Fraction(1, 48000), Fraction(0))
    assert receipt.container_duration == Fraction(12)
    again = ProbeReceipt.from_json(json.loads(receipt.to_bytes()))
    assert again == receipt and again.receipt_id == receipt.receipt_id
    with pytest.raises(ContractError):
        ProbeReceipt(TOOL, receipt.streams, receipt.container_duration, Sha256("0" * 64))


def test_vfr_timestamps_are_kept_verbatim_and_nominal_rate_is_not_trusted() -> None:
    # 60 fps timebase with every third frame dropped: the nominal r_frame_rate lies
    pts = [p for p in range(0, 60) if p % 3 != 2]
    stream = _video(time_base="1/60", r_frame_rate="60/1", avg_frame_rate="40/1")
    receipt = receipt_from_ffprobe(_probe([stream], "1.000000"), {0: _frames(pts)}, TOOL)
    video = receipt.video_streams()[0]
    assert isinstance(video.vfr, VfrTable)
    assert video.vfr.pts[:4] == (Fraction(0), Fraction(1, 60), Fraction(3, 60), Fraction(4, 60))
    assert len(video.vfr.pts) == 40
    # constant spacing is recognised from the timestamps even when r_frame_rate disagrees
    timing, fps = frame_timing_from_pts(tuple(Fraction(p, 25) for p in range(50)), Fraction(30))
    assert timing == ConstantRate() and fps == Fraction(25)


def test_rotation_sar_hdr_bframes_and_offsets_are_recorded() -> None:
    rotated = _video(
        index=0,
        width=1920,
        height=1080,
        side_data_list=[{"side_data_type": "Display Matrix", "rotation": -90.0}],
    )
    legacy = _video(index=1, tags={"rotate": "270"})
    anamorphic = _video(index=2, width=1440, height=1080, sample_aspect_ratio="4:3", has_b_frames=2)
    hlg = _video(index=3, color_transfer="arib-std-b67", color_primaries="bt2020")
    untagged = _video(index=4, color_transfer="unknown", color_primaries="unknown")
    offset_video = _video(index=5, time_base="1/90000", start_pts=675000, start_time="7.500000")
    offset_audio = _audio(index=6, start_pts=408000, start_time="8.500000")
    receipt = receipt_from_ffprobe(
        _probe([rotated, legacy, anamorphic, hlg, untagged, offset_video, offset_audio], "10.5"),
        {},
        TOOL,
    )
    streams = {s.index: s for s in receipt.streams}
    v0 = streams[0]
    assert isinstance(v0, VideoStream) and v0.rotation is Rotation.R90
    v1 = streams[1]
    assert isinstance(v1, VideoStream) and v1.rotation is Rotation.R270
    v2 = streams[2]
    assert isinstance(v2, VideoStream) and v2.sar == Fraction(4, 3) and v2.has_bframes
    v3 = streams[3]
    assert isinstance(v3, VideoStream) and v3.color == Hdr(HdrTransfer.HLG, "bt2020")
    v4 = streams[4]
    assert isinstance(v4, VideoStream) and v4.color == Untagged()
    v5 = streams[5]
    assert isinstance(v5, VideoStream) and v5.start_time == Fraction(15, 2)
    a6 = streams[6]
    assert isinstance(a6, AudioStream) and a6.start_time == Fraction(17, 2)
    assert receipt.container_duration == Fraction(21, 2)


def test_malformed_probe_numbers_are_refused() -> None:
    with pytest.raises(ContractError, match="duration"):
        receipt_from_ffprobe(_probe([_video()], "N/A"), {}, TOOL)
    with pytest.raises(ContractError, match=r"ratio|positive"):
        receipt_from_ffprobe(_probe([_video(r_frame_rate="0/0", avg_frame_rate="0/0")]), {}, TOOL)
    with pytest.raises(ContractError, match="positive"):
        receipt_from_ffprobe(_probe([_video(r_frame_rate="0/1", avg_frame_rate="0/1")]), {}, TOOL)
    with pytest.raises(ContractError):
        receipt_from_ffprobe(_probe([_video(time_base="1/0")]), {}, TOOL)
    with pytest.raises(ContractError):
        receipt_from_ffprobe(_probe([_video(width=0)]), {}, TOOL)
    with pytest.raises(ContractError, match="increasing"):
        receipt_from_ffprobe(_probe([_video()]), {0: _frames([0, 512, 512])}, TOOL)
    with pytest.raises(ContractError):
        VfrTable((Fraction(1), Fraction(1)))
    with pytest.raises(ContractError):
        VfrTable(())
    with pytest.raises(ContractError):
        receipt_from_ffprobe(_probe([]), {}, TOOL)


# ----------------------------------------------------------------------------- store


class FakeProber:
    def __init__(self, outcome: ProbeReceipt | ProbeFailed) -> None:
        self.outcome = outcome
        self.calls: list[Path] = []

    def probe(self, path: Path) -> ProbeReceipt | ProbeFailed:
        self.calls.append(path)
        return self.outcome


def _receipt() -> ProbeReceipt:
    return receipt_from_ffprobe(_probe([_video(), _audio()]), {0: _frames([0, 512, 1024])}, TOOL)


def _project(tmp_path: Path) -> tuple[Store, ProjectGrant, Path, FakeProber]:
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    media = project / "media"
    media.mkdir(parents=True)
    source = media / "interview.bin"
    source.write_bytes(os.urandom(4096))
    prober = FakeProber(_receipt())
    return Store(ledger, prober), grant, source, prober


def test_import_records_identity_receipt_and_leaves_the_original_untouched(tmp_path: Path) -> None:
    store, grant, source, prober = _project(tmp_path)
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    locator = ScopedLocator(grant.grant_id, "media/interview.bin")
    identity = store.import_source(locator, grant)
    assert isinstance(identity, SourceIdentity)
    assert identity.sha256 == hash_file(source)[0] and identity.size_bytes == 4096
    assert identity.probe_receipt_id == _receipt().receipt_id
    assert prober.calls == [source.resolve()]
    receipt = store.receipt(identity.probe_receipt_id)
    assert isinstance(receipt, ProbeReceipt) and receipt == _receipt()
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert store.resolve_by_hash(identity.sha256) == (locator,)
    assert store.availability("a1", identity, locator) == Present(
        identity.sha256, locator, identity.probe_receipt_id
    )
    # the receipt and the source record are sealed artifacts with the tool identity
    art = store.ledger.artifact(identity.probe_receipt_id)
    assert art is not None and art.kind == "probe-receipt"
    assert len(store.known_sources()) == 1
    # importing again is idempotent (no duplicate records)
    assert store.import_source(locator, grant) == identity
    assert len(store.known_sources()) == 1
    store.ledger.close()


def test_import_refusals_are_typed(tmp_path: Path) -> None:
    store, grant, _source, _ = _project(tmp_path)
    with pytest.raises(ContractError):
        ScopedLocator(grant.grant_id, "../outside.bin")
    other = ProjectGrant("pg-other", tmp_path / "elsewhere", ACTOR)
    res = store.import_source(ScopedLocator("pg-other", "x.bin"), grant)
    assert isinstance(res, ImportRefused) and res.reason.code is RejectCode.UNAUTHORIZED
    res = store.import_source(ScopedLocator("pg-other", "x.bin"), other)
    assert isinstance(res, ImportRefused) and res.reason.code is RejectCode.NOT_A_FILE
    res = store.import_source(ScopedLocator(grant.grant_id, "media"), grant)
    assert isinstance(res, ImportRefused) and res.reason.code is RejectCode.NOT_A_FILE
    (store.project_dir / "cas" / "x.bin").write_bytes(b"x")
    res = store.import_source(ScopedLocator(grant.grant_id, "cas/x.bin"), grant)
    assert isinstance(res, ImportRefused) and res.reason.code is RejectCode.NOT_A_FILE
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside the grant")
    (store.project_dir / "media" / "escape.bin").symlink_to(outside)
    res = store.import_source(ScopedLocator(grant.grant_id, "media/escape.bin"), grant)
    assert isinstance(res, ImportRefused) and res.reason.code is RejectCode.UNAUTHORIZED
    failing = Store(store.ledger, FakeProber(ProbeFailed("boom", 1)))
    res = failing.import_source(ScopedLocator(grant.grant_id, "media/interview.bin"), grant)
    assert isinstance(res, ImportRefused) and res.reason.code is RejectCode.PROBE_FAILED
    missing_tool = Store(store.ledger, ProbeToolMissing("no ffprobe"))
    res = missing_tool.import_source(ScopedLocator(grant.grant_id, "media/interview.bin"), grant)
    assert isinstance(res, ImportRefused) and res.reason.code is RejectCode.TOOL_MISSING
    assert store.known_sources() == ()
    store.ledger.close()


def test_availability_is_present_missing_or_changed_by_bytes_not_path(tmp_path: Path) -> None:
    store, grant, source, _ = _project(tmp_path)
    locator = ScopedLocator(grant.grant_id, "media/interview.bin")
    identity = store.import_source(locator, grant)
    assert isinstance(identity, SourceIdentity)
    original = source.read_bytes()
    source.write_bytes(b"replaced bytes at the same path")
    changed = store.availability("a1", identity, locator)
    assert isinstance(changed, Changed) and changed.expected_hash == identity.sha256
    assert changed.observed_hash == hash_file(source)[0]
    source.unlink()
    missing = store.availability("a1", identity, locator)
    assert isinstance(missing, Missing)
    assert missing.relink_request.asset_id == "a1"
    assert missing.relink_request.last_known_locator == locator
    source.write_bytes(original)
    assert isinstance(store.availability("a1", identity, locator), Present)
    unknown_grant = store.availability("a1", identity, ScopedLocator("pg-unknown", "x"))
    assert isinstance(unknown_grant, Missing)
    store.ledger.close()


def test_job_snapshot_is_a_verified_clone_and_refuses_changed_sources(tmp_path: Path) -> None:
    store, grant, source, _ = _project(tmp_path)
    locator = ScopedLocator(grant.grant_id, "media/interview.bin")
    identity = store.import_source(locator, grant)
    assert isinstance(identity, SourceIdentity)
    clone = store.snapshot_for_job(identity, locator, "job-1")
    assert isinstance(clone, VerifiedClone)
    assert clone.path.is_relative_to(store.project_dir / "snapshots" / "job-1")
    assert clone.path.read_bytes() == source.read_bytes() and clone.sha256 == identity.sha256
    source.write_bytes(b"modified after the clone")
    assert clone.path.read_bytes() != source.read_bytes()  # the job keeps its stable copy
    refused = store.snapshot_for_job(identity, locator, "job-2")
    assert isinstance(refused, CloneRefused)
    assert refused.reason.code is RejectCode.ASSET_NOT_VERIFIED
    assert not (store.project_dir / "snapshots" / "job-2").exists()
    bad = store.snapshot_for_job(identity, locator, "../escape")
    assert isinstance(bad, CloneRefused)
    store.release_snapshot("job-1")
    assert not clone.path.exists()
    store.ledger.close()


def test_artifacts_round_trip_through_the_store(tmp_path: Path) -> None:
    store, _grant, _source, _ = _project(tmp_path)
    ref = store.put(b"mask bytes", "mask", (), {"tool": "test"}, "mask:1")
    assert not isinstance(ref, type(None))
    from aidashvideo.ledger import Rejected

    assert not isinstance(ref, Rejected)
    assert store.open(ref.sha256) == b"mask bytes"
    unknown = store.open(Sha256("9" * 64))
    assert (
        isinstance(unknown, Rejected)
        and unknown.contract_reason.code is RejectCode.UNKNOWN_ARTIFACT
    )
    dependent = store.put(b"composite", "composite", (ref.sha256,), {"tool": "test"}, "composite:1")
    assert not isinstance(dependent, Rejected)
    dangling = store.put(b"x", "composite", (Sha256("9" * 64),), {"tool": "test"}, "composite:2")
    assert isinstance(dangling, Rejected)
    store.ledger.close()


# ----------------------------------------------------------------------------- installed ffprobe


def test_installed_ffprobe_produces_a_receipt_with_its_own_identity(tmp_path: Path) -> None:
    ffmpeg = os.environ.get("AIDASHVIDEO_FFMPEG") or shutil.which("ffmpeg")
    ffprobe = os.environ.get("AIDASHVIDEO_FFPROBE") or shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip(
            "no ffmpeg/ffprobe installed: probe receipts need one (docs/plan/commands.md §6)"
        )
    clip = tmp_path / "clip.nut"
    gen = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x36:rate=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "0.4",
            "-c:v",
            "rawvideo",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "pcm_s16le",
            str(clip),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if gen.returncode != 0:
        pytest.skip(f"installed ffmpeg cannot synthesize the fixture: {gen.stderr[-300:]}")
    prober = FfprobeProber(Path(ffprobe))
    receipt = prober.probe(clip)
    assert isinstance(receipt, ProbeReceipt), receipt
    assert receipt.probe_tool_identity.name == "ffprobe"
    assert receipt.probe_tool_identity.version  # recorded, whatever the host has
    video = receipt.video_streams()[0]
    assert (video.width, video.height) == (64, 36)
    assert video.fps == Fraction(25) and video.vfr == ConstantRate()
    assert receipt.audio_streams()[0].sample_rate == 48000
    assert Fraction(3, 10) <= receipt.container_duration <= Fraction(1, 2)
    # wire it through the store against a real ledger
    project = tmp_path / "proj"
    ledger, grant = open_store(project)
    (project / "media").mkdir()
    shutil.copyfile(clip, project / "media" / "clip.nut")
    store = Store(ledger, prober)
    identity = store.import_source(ScopedLocator(grant.grant_id, "media/clip.nut"), grant)
    assert isinstance(identity, SourceIdentity)
    assert store.receipt(identity.probe_receipt_id) == receipt
    ledger.close()


def test_project_id_helper_is_used_for_lineages() -> None:
    assert ProjectId.new().value.startswith("project-")
