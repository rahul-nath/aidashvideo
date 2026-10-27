"""Source identity and probe contracts (contracts §2 "identity & media", owner: store).

Every value is exact: timestamps and rates are ``Fraction``s, stream ``start_time`` is kept
as a fact of the probe (``aidashvideo.project.timing`` subtracts it exactly once), decoded
presentation timestamps of variable-rate streams are kept verbatim in :class:`VfrTable`,
and orientation/pixel aspect ratio stay on the stream so geometry can derive the oriented
grid. Nothing here reads files; see :mod:`aidashvideo.store.probe`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from aidashvideo.ledger.canonical import (
    as_bool,
    as_int,
    as_list,
    as_object,
    as_str,
    canonical_bytes,
    canonical_sha256,
    field,
    rational_from_json,
    rational_to_json,
    require_keys,
)
from aidashvideo.ledger.errors import ContractError, is_int, is_str, widen
from aidashvideo.ledger.grants import ScopedLocator
from aidashvideo.ledger.ids import Sha256


class Rotation(StrEnum):
    R0 = "R0"
    R90 = "R90"
    R180 = "R180"
    R270 = "R270"

    @property
    def degrees(self) -> int:
        return {"R0": 0, "R90": 90, "R180": 180, "R270": 270}[self.value]

    @classmethod
    def from_degrees(cls, degrees: int) -> Rotation:
        normalized = degrees % 360
        try:
            return {0: cls.R0, 90: cls.R90, 180: cls.R180, 270: cls.R270}[normalized]
        except KeyError as exc:
            raise ContractError(f"Rotation: unsupported angle {degrees}") from exc


class HdrTransfer(StrEnum):
    PQ = "Pq"
    HLG = "Hlg"


@dataclass(frozen=True, slots=True)
class Sdr709:
    def to_json(self) -> dict[str, object]:
        return {"kind": "Sdr709"}


@dataclass(frozen=True, slots=True)
class Hdr:
    transfer: HdrTransfer
    primaries: str

    def __post_init__(self) -> None:
        if not is_str(self.primaries) or not self.primaries:
            raise ContractError("Hdr.primaries must be a non-empty string")

    def to_json(self) -> dict[str, object]:
        return {"kind": "Hdr", "transfer": self.transfer.value, "primaries": self.primaries}


@dataclass(frozen=True, slots=True)
class Untagged:
    def to_json(self) -> dict[str, object]:
        return {"kind": "Untagged"}


type ColorTags = Sdr709 | Hdr | Untagged


def color_from_json(raw: object) -> ColorTags:
    data = as_object(raw, "ColorTags")
    kind = as_str(field(data, "kind", "ColorTags"), "ColorTags.kind")
    if kind == "Sdr709":
        require_keys(data, "ColorTags", ("kind",))
        return Sdr709()
    if kind == "Untagged":
        require_keys(data, "ColorTags", ("kind",))
        return Untagged()
    if kind == "Hdr":
        require_keys(data, "ColorTags", ("kind", "transfer", "primaries"))
        try:
            transfer = HdrTransfer(as_str(data["transfer"], "transfer"))
        except ValueError as exc:
            raise ContractError(f"ColorTags: unknown transfer: {exc}") from exc
        return Hdr(transfer, as_str(data["primaries"], "primaries"))
    raise ContractError(f"ColorTags: unknown kind {kind!r}")


@dataclass(frozen=True, slots=True)
class VfrTable:
    """Actual decoded presentation timestamps (seconds, stream start already subtracted)."""

    pts: tuple[Fraction, ...]

    def __post_init__(self) -> None:
        if len(self.pts) < 1:
            raise ContractError("VfrTable needs at least one timestamp")
        previous = Fraction(-1)
        for index, value in enumerate(self.pts):
            if not isinstance(widen(value), Fraction):
                raise ContractError(f"VfrTable.pts[{index}] must be a Fraction")
            if index == 0 and value < 0:
                raise ContractError("VfrTable.pts[0] must be >= 0")
            if index > 0 and value <= previous:
                raise ContractError(f"VfrTable.pts must be strictly increasing at index {index}")
            previous = value

    @classmethod
    def make(cls, pts: tuple[Fraction, ...]) -> VfrTable:
        return cls(pts)

    def to_json(self) -> dict[str, object]:
        return {"kind": "VfrTable", "pts": [rational_to_json(p) for p in self.pts]}


@dataclass(frozen=True, slots=True)
class ConstantRate:
    def to_json(self) -> dict[str, object]:
        return {"kind": "ConstantRate"}


type FrameTiming = VfrTable | ConstantRate


def frame_timing_from_json(raw: object) -> FrameTiming:
    data = as_object(raw, "vfr")
    kind = as_str(field(data, "kind", "vfr"), "vfr.kind")
    if kind == "ConstantRate":
        require_keys(data, "vfr", ("kind",))
        return ConstantRate()
    if kind == "VfrTable":
        require_keys(data, "vfr", ("kind", "pts"))
        return VfrTable(
            tuple(rational_from_json(p, "vfr.pts[]") for p in as_list(data["pts"], "vfr.pts"))
        )
    raise ContractError(f"vfr: unknown kind {kind!r}")


def _positive(value: Fraction, what: str) -> None:
    if not isinstance(widen(value), Fraction) or value <= 0:
        raise ContractError(f"{what} must be a positive rational")


def _non_negative(value: Fraction, what: str) -> None:
    if not isinstance(widen(value), Fraction) or value < 0:
        raise ContractError(f"{what} must be a non-negative rational")


@dataclass(frozen=True, slots=True)
class VideoStream:
    index: int
    codec: str
    width: int
    height: int
    sar: Fraction
    fps: Fraction
    timebase: Fraction
    start_time: Fraction
    rotation: Rotation
    color: ColorTags
    vfr: FrameTiming
    has_bframes: bool

    def __post_init__(self) -> None:
        if not is_int(self.index) or self.index < 0:
            raise ContractError("VideoStream.index must be >= 0")
        if not is_str(self.codec) or not self.codec:
            raise ContractError("VideoStream.codec must be non-empty")
        if not is_int(self.width) or not is_int(self.height) or self.width < 1 or self.height < 1:
            raise ContractError("VideoStream dimensions must be positive integers")
        _positive(self.sar, "VideoStream.sar")
        _positive(self.fps, "VideoStream.fps")
        _positive(self.timebase, "VideoStream.timebase")
        if not isinstance(widen(self.start_time), Fraction):
            raise ContractError("VideoStream.start_time must be a Fraction")
        if not isinstance(widen(self.has_bframes), bool):
            raise ContractError("VideoStream.has_bframes must be a bool")

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "VideoStream",
            "index": self.index,
            "codec": self.codec,
            "width": self.width,
            "height": self.height,
            "sar": rational_to_json(self.sar),
            "fps": rational_to_json(self.fps),
            "timebase": rational_to_json(self.timebase),
            "start_time": rational_to_json(self.start_time),
            "rotation": self.rotation.value,
            "color": self.color.to_json(),
            "vfr": self.vfr.to_json(),
            "has_bframes": self.has_bframes,
        }


@dataclass(frozen=True, slots=True)
class AudioStream:
    index: int
    codec: str
    sample_rate: int
    channels: int
    layout: str
    timebase: Fraction
    start_time: Fraction

    def __post_init__(self) -> None:
        if not is_int(self.index) or self.index < 0:
            raise ContractError("AudioStream.index must be >= 0")
        if not is_str(self.codec) or not self.codec:
            raise ContractError("AudioStream.codec must be non-empty")
        if not is_int(self.sample_rate) or self.sample_rate < 1:
            raise ContractError("AudioStream.sample_rate must be a positive integer")
        if not is_int(self.channels) or self.channels < 1:
            raise ContractError("AudioStream.channels must be a positive integer")
        if not is_str(self.layout):
            raise ContractError("AudioStream.layout must be a string")
        _positive(self.timebase, "AudioStream.timebase")
        if not isinstance(widen(self.start_time), Fraction):
            raise ContractError("AudioStream.start_time must be a Fraction")

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "AudioStream",
            "index": self.index,
            "codec": self.codec,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "layout": self.layout,
            "timebase": rational_to_json(self.timebase),
            "start_time": rational_to_json(self.start_time),
        }


type StreamProbe = VideoStream | AudioStream

_VIDEO_KEYS = (
    "kind",
    "index",
    "codec",
    "width",
    "height",
    "sar",
    "fps",
    "timebase",
    "start_time",
    "rotation",
    "color",
    "vfr",
    "has_bframes",
)
_AUDIO_KEYS = (
    "kind",
    "index",
    "codec",
    "sample_rate",
    "channels",
    "layout",
    "timebase",
    "start_time",
)


def stream_from_json(raw: object) -> StreamProbe:
    data = as_object(raw, "StreamProbe")
    kind = as_str(field(data, "kind", "StreamProbe"), "StreamProbe.kind")
    if kind == "VideoStream":
        require_keys(data, "VideoStream", _VIDEO_KEYS)
        try:
            rotation = Rotation(as_str(data["rotation"], "rotation"))
        except ValueError as exc:
            raise ContractError(f"VideoStream.rotation: {exc}") from exc
        return VideoStream(
            as_int(data["index"], "index"),
            as_str(data["codec"], "codec"),
            as_int(data["width"], "width"),
            as_int(data["height"], "height"),
            rational_from_json(data["sar"], "sar"),
            rational_from_json(data["fps"], "fps"),
            rational_from_json(data["timebase"], "timebase"),
            rational_from_json(data["start_time"], "start_time"),
            rotation,
            color_from_json(data["color"]),
            frame_timing_from_json(data["vfr"]),
            as_bool(data["has_bframes"], "has_bframes"),
        )
    if kind == "AudioStream":
        require_keys(data, "AudioStream", _AUDIO_KEYS)
        return AudioStream(
            as_int(data["index"], "index"),
            as_str(data["codec"], "codec"),
            as_int(data["sample_rate"], "sample_rate"),
            as_int(data["channels"], "channels"),
            as_str(data["layout"], "layout"),
            rational_from_json(data["timebase"], "timebase"),
            rational_from_json(data["start_time"], "start_time"),
        )
    raise ContractError(f"StreamProbe: unknown kind {kind!r}")


@dataclass(frozen=True, slots=True)
class ToolIdentity:
    """Which probe produced a receipt (recorded, never assumed: the sandbox's FFmpeg differs)."""

    name: str
    version: str
    binary_sha256: Sha256

    def __post_init__(self) -> None:
        if not is_str(self.name) or not self.name or not is_str(self.version) or not self.version:
            raise ContractError("ToolIdentity needs a name and a version")

    def to_json(self) -> dict[str, object]:
        return {"name": self.name, "version": self.version, "binary_sha256": self.binary_sha256.hex}

    @classmethod
    def from_json(cls, raw: object) -> ToolIdentity:
        data = as_object(raw, "ToolIdentity")
        require_keys(data, "ToolIdentity", ("name", "version", "binary_sha256"))
        return cls(
            as_str(data["name"], "name"),
            as_str(data["version"], "version"),
            Sha256(as_str(data["binary_sha256"], "binary_sha256")),
        )


@dataclass(frozen=True, slots=True)
class ProbeReceipt:
    probe_tool_identity: ToolIdentity
    streams: tuple[StreamProbe, ...]
    container_duration: Fraction
    sha256_of_json: Sha256

    def __post_init__(self) -> None:
        if not self.streams:
            raise ContractError("ProbeReceipt needs at least one stream")
        indices = [s.index for s in self.streams]
        if len(set(indices)) != len(indices):
            raise ContractError("ProbeReceipt stream indices must be unique")
        _non_negative(self.container_duration, "ProbeReceipt.container_duration")
        if self.sha256_of_json != self.identity_hash():
            raise ContractError("ProbeReceipt.sha256_of_json does not match its content")

    @classmethod
    def make(
        cls,
        probe_tool_identity: ToolIdentity,
        streams: tuple[StreamProbe, ...],
        container_duration: Fraction,
    ) -> ProbeReceipt:
        body = _receipt_body(probe_tool_identity, streams, container_duration)
        return cls(probe_tool_identity, streams, container_duration, canonical_sha256(body))

    def identity_hash(self) -> Sha256:
        return canonical_sha256(
            _receipt_body(self.probe_tool_identity, self.streams, self.container_duration)
        )

    @property
    def receipt_id(self) -> Sha256:
        return self.sha256_of_json

    def to_json(self) -> dict[str, object]:
        """The receipt body; its canonical bytes hash to ``sha256_of_json`` (self-certifying)."""
        return _receipt_body(self.probe_tool_identity, self.streams, self.container_duration)

    def to_bytes(self) -> bytes:
        return canonical_bytes(self.to_json())

    @classmethod
    def from_json(cls, raw: object) -> ProbeReceipt:
        data = as_object(raw, "ProbeReceipt")
        require_keys(
            data, "ProbeReceipt", ("$id", "probe_tool_identity", "streams", "container_duration")
        )
        if data["$id"] != RECEIPT_SCHEMA_ID:
            raise ContractError(f"ProbeReceipt: unsupported $id {data['$id']!r}")
        streams = tuple(stream_from_json(s) for s in as_list(data["streams"], "streams"))
        return cls.make(
            ToolIdentity.from_json(data["probe_tool_identity"]),
            streams,
            rational_from_json(data["container_duration"], "container_duration"),
        )

    def video_streams(self) -> tuple[VideoStream, ...]:
        return tuple(s for s in self.streams if isinstance(s, VideoStream))

    def audio_streams(self) -> tuple[AudioStream, ...]:
        return tuple(s for s in self.streams if isinstance(s, AudioStream))

    def stream(self, index: int) -> StreamProbe | None:
        for s in self.streams:
            if s.index == index:
                return s
        return None


RECEIPT_SCHEMA_ID = "aidashvideo.probe-receipt/1"


def _receipt_body(
    tool: ToolIdentity, streams: tuple[StreamProbe, ...], duration: Fraction
) -> dict[str, object]:
    return {
        "$id": RECEIPT_SCHEMA_ID,
        "probe_tool_identity": tool.to_json(),
        "streams": [s.to_json() for s in streams],
        "container_duration": rational_to_json(duration),
    }


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Content identity: hash, size and the receipt describing the bytes (never a path)."""

    sha256: Sha256
    size_bytes: int
    probe_receipt_id: Sha256

    def __post_init__(self) -> None:
        if not is_int(self.size_bytes) or self.size_bytes < 0:
            raise ContractError("SourceIdentity.size_bytes must be >= 0")

    def to_json(self) -> dict[str, object]:
        return {
            "sha256": self.sha256.hex,
            "size_bytes": self.size_bytes,
            "probe_receipt_id": self.probe_receipt_id.hex,
        }

    @classmethod
    def from_json(cls, raw: object) -> SourceIdentity:
        data = as_object(raw, "SourceIdentity")
        require_keys(data, "SourceIdentity", ("sha256", "size_bytes", "probe_receipt_id"))
        return cls(
            Sha256(as_str(data["sha256"], "sha256")),
            as_int(data["size_bytes"], "size_bytes"),
            Sha256(as_str(data["probe_receipt_id"], "probe_receipt_id")),
        )


@dataclass(frozen=True, slots=True)
class SourceBinding:
    """Content + stream, never a path (analysis evidence binds to this)."""

    asset_sha256: Sha256
    stream_index: int
    probe_receipt_id: Sha256

    def __post_init__(self) -> None:
        if not is_int(self.stream_index) or self.stream_index < 0:
            raise ContractError("SourceBinding.stream_index must be >= 0")

    def to_json(self) -> dict[str, object]:
        return {
            "asset_sha256": self.asset_sha256.hex,
            "stream_index": self.stream_index,
            "probe_receipt_id": self.probe_receipt_id.hex,
        }

    @classmethod
    def from_json(cls, raw: object) -> SourceBinding:
        data = as_object(raw, "SourceBinding")
        require_keys(data, "SourceBinding", ("asset_sha256", "stream_index", "probe_receipt_id"))
        return cls(
            Sha256(as_str(data["asset_sha256"], "asset_sha256")),
            as_int(data["stream_index"], "stream_index"),
            Sha256(as_str(data["probe_receipt_id"], "probe_receipt_id")),
        )


@dataclass(frozen=True, slots=True)
class RelinkRequest:
    asset_id: str
    expected_hash: Sha256
    last_known_locator: ScopedLocator

    def __post_init__(self) -> None:
        if not is_str(self.asset_id) or not self.asset_id:
            raise ContractError("RelinkRequest.asset_id must be non-empty")

    def to_json(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "expected_hash": self.expected_hash.hex,
            "last_known_locator": self.last_known_locator.to_json(),
        }


@dataclass(frozen=True, slots=True)
class Present:
    verified_hash: Sha256
    scoped_locator: ScopedLocator
    probe_receipt: Sha256
    """Receipt id (the receipt bytes are a sealed artifact)."""

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "Present",
            "verified_hash": self.verified_hash.hex,
            "scoped_locator": self.scoped_locator.to_json(),
            "probe_receipt": self.probe_receipt.hex,
        }


@dataclass(frozen=True, slots=True)
class Missing:
    expected_hash: Sha256
    relink_request: RelinkRequest

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "Missing",
            "expected_hash": self.expected_hash.hex,
            "relink_request": self.relink_request.to_json(),
        }


@dataclass(frozen=True, slots=True)
class Changed:
    expected_hash: Sha256
    observed_hash: Sha256

    def __post_init__(self) -> None:
        if self.expected_hash == self.observed_hash:
            raise ContractError("Changed: observed hash equals the expected hash")

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "Changed",
            "expected_hash": self.expected_hash.hex,
            "observed_hash": self.observed_hash.hex,
        }


type AssetAvailability = Present | Missing | Changed


def availability_from_json(raw: object) -> AssetAvailability:
    data = as_object(raw, "AssetAvailability")
    kind = as_str(field(data, "kind", "AssetAvailability"), "AssetAvailability.kind")
    if kind == "Present":
        require_keys(data, "Present", ("kind", "verified_hash", "scoped_locator", "probe_receipt"))
        return Present(
            Sha256(as_str(data["verified_hash"], "verified_hash")),
            ScopedLocator.from_json(data["scoped_locator"]),
            Sha256(as_str(data["probe_receipt"], "probe_receipt")),
        )
    if kind == "Missing":
        require_keys(data, "Missing", ("kind", "expected_hash", "relink_request"))
        relink = as_object(data["relink_request"], "relink_request")
        require_keys(relink, "RelinkRequest", ("asset_id", "expected_hash", "last_known_locator"))
        return Missing(
            Sha256(as_str(data["expected_hash"], "expected_hash")),
            RelinkRequest(
                as_str(relink["asset_id"], "asset_id"),
                Sha256(as_str(relink["expected_hash"], "expected_hash")),
                ScopedLocator.from_json(relink["last_known_locator"]),
            ),
        )
    if kind == "Changed":
        require_keys(data, "Changed", ("kind", "expected_hash", "observed_hash"))
        return Changed(
            Sha256(as_str(data["expected_hash"], "expected_hash")),
            Sha256(as_str(data["observed_hash"], "observed_hash")),
        )
    raise ContractError(f"AssetAvailability: unknown kind {kind!r}")
