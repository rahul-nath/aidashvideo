"""Filesystem locations of the repository, the pinned toolchain files and local stores."""

from __future__ import annotations

import os
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent


def repo_root() -> Path:
    """Repository root (the project is installed editable from ``src/``)."""
    override = os.environ.get("AIDASHVIDEO_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return _PACKAGE_DIR.parents[2]


def toolchain_dir() -> Path:
    """Committed requirements: profiles/*.toml, models.toml and the Linux sysroot lock."""
    return repo_root() / "toolchain"


def user_data_deps_dir() -> Path:
    """Per-user install location outside any checkout: ``$XDG_DATA_HOME/aidashvideo/deps``."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "aidashvideo" / "deps"


def _is_installed(root: Path) -> bool:
    """A deps dir counts only when it holds a toolchain profile or recorded model admissions."""
    return (root / "frozen" / "profile.json").is_file() or (
        root / "models" / "admissions.json"
    ).is_file()


def deps_dir() -> Path:
    """Rootless toolchain installs, source/archive cache and admitted model assets.

    Resolution order: ``AIDASHVIDEO_DEPS_DIR``; the repository's git-ignored ``.deps/`` when it
    holds an install; the per-user data dir when it holds one; else ``.deps/`` (so a Missing
    report names the default location). Checkouts can be ephemeral (worktrees, synced copies),
    so the user data dir is the durable home for multi-gigabyte builds and weights.
    """
    override = os.environ.get("AIDASHVIDEO_DEPS_DIR")
    if override:
        return Path(override).resolve()
    local = repo_root() / ".deps"
    if _is_installed(local):
        return local
    user = user_data_deps_dir()
    if _is_installed(user):
        return user
    return local


def var_dir() -> Path:
    """Target-local stores named by the plan: fixtures, evidence store, dev projects."""
    override = os.environ.get("AIDASHVIDEO_VAR_DIR")
    if override:
        return Path(override).resolve()
    return repo_root() / "var"


def models_dir() -> Path:
    return deps_dir() / "models"


def hf_hub_cache_dir() -> Path:
    """Isolated Hugging Face hub cache used by the providers (never the shared one)."""
    return models_dir() / "hf-hub"
