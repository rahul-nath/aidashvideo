"""Loader for toolchain/profiles/*.toml (planned identities the doctor compares against).

A profile pins versions and required capabilities (encoders, decoders, filters, muxers,
MLT profile id). It deliberately does not pin build digests: those differ per host build
and are recorded as observed facts by the probes instead.

``frozen`` is the plan's target profile (docs/plan/runtime-profile.json) and the only
profile shipped. An additional *observed* profile may be selected explicitly with
``AIDASHVIDEO_PROFILE``; it never changes what the plan calls Verified.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from typing import Any, cast

from .paths import toolchain_dir

DEFAULT_PROFILE = "frozen"


@dataclass(frozen=True)
class FfmpegPins:
    version: str
    install: str  # ffmpeg binary relative to .deps ("" = search PATH)
    required_encoders: tuple[str, ...]
    required_decoders: tuple[str, ...]
    required_filters: tuple[str, ...]
    required_muxers: tuple[str, ...]


@dataclass(frozen=True)
class MltPins:
    version: str
    profile_id: str
    install: str  # install tree relative to .deps (contains profile.json)
    lock: str


@dataclass(frozen=True)
class ProfilePins:
    profile_id: str
    kind: str  # "planned" | "observed"
    os: str
    machine: str
    python_version: str
    ffmpeg: FfmpegPins
    mlt: MltPins


def _strs(value: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in cast(list[Any], value))


def available_profiles() -> list[str]:
    return sorted(p.stem for p in (toolchain_dir() / "profiles").glob("*.toml"))


def selected_profile_id() -> str:
    return os.environ.get("AIDASHVIDEO_PROFILE", DEFAULT_PROFILE)


def load_pins(profile_id: str | None = None) -> ProfilePins:
    profile_id = profile_id or selected_profile_id()
    path = toolchain_dir() / "profiles" / f"{profile_id}.toml"
    if not path.is_file():
        raise FileNotFoundError(
            f"unknown toolchain profile {profile_id!r}; available: {available_profiles()}"
        )
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    ff = cast(dict[str, Any], data["ffmpeg"])
    mlt = cast(dict[str, Any], data["mlt"])
    prof = cast(dict[str, Any], data["profile"])
    return ProfilePins(
        profile_id=str(prof["id"]),
        kind=str(prof["kind"]),
        os=str(prof["os"]),
        machine=str(prof["machine"]),
        python_version=str(cast(dict[str, Any], data["python"])["version"]),
        ffmpeg=FfmpegPins(
            version=str(ff["version"]),
            install=str(ff.get("install", "")),
            required_encoders=_strs(ff["required_encoders"]),
            required_decoders=_strs(ff["required_decoders"]),
            required_filters=_strs(ff["required_filters"]),
            required_muxers=_strs(ff.get("required_muxers", [])),
        ),
        mlt=MltPins(
            version=str(mlt["version"]),
            profile_id=str(mlt["profile_id"]),
            install=str(mlt.get("install", "mlt")),
            lock=str(mlt.get("lock", "")),
        ),
    )
