"""Model asset manifest (toolchain/models.toml), status and operator admission.

Weights are licensed assets the operator supplies locally; nothing here downloads.

* ``status`` observes only.
* ``admit`` copies an operator-supplied Hugging Face repository (or single file)
  into the isolated store under ``.deps/models`` and records every file hash in
  ``.deps/models/admissions.json``.

Writes are staged and renamed into place, so an interrupted admission never
leaves a partially written asset that looks ready (V17).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .paths import hf_hub_cache_dir, models_dir, toolchain_dir
from .status import ComponentStatus, Readiness

ADMISSIONS_FILE = "admissions.json"


@dataclass(frozen=True)
class Asset:
    id: str
    profile: str
    kind: str  # "hf-repo" | "file"
    license: str
    repo_id: str = ""
    required_files: tuple[str, ...] = ()
    relpath: str = ""
    sha256: str = ""
    upstream: str = ""
    consumer: str = ""


def load_manifest(path: Path | None = None) -> list[Asset]:
    data = tomllib.loads((path or toolchain_dir() / "models.toml").read_text("utf-8"))
    return [
        Asset(
            id=str(raw["id"]),
            profile=str(raw["profile"]),
            kind=str(raw["kind"]),
            license=str(raw.get("license", "")),
            repo_id=str(raw.get("repo_id", "")),
            required_files=tuple(str(f) for f in raw.get("required_files", [])),
            relpath=str(raw.get("relpath", "")),
            sha256=str(raw.get("sha256", "")),
            upstream=str(raw.get("upstream", "")),
            consumer=str(raw.get("consumer", "")),
        )
        for raw in cast(list[dict[str, Any]], data.get("asset", []))
    ]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- hf cache


def hf_repo_dir(repo_id: str, cache: Path | None = None) -> Path:
    return (cache or hf_hub_cache_dir()) / ("models--" + repo_id.replace("/", "--"))


def hf_snapshot_dir(repo_id: str, cache: Path | None = None) -> Path | None:
    repo = hf_repo_dir(repo_id, cache)
    ref = repo / "refs" / "main"
    if not ref.is_file():
        return None
    snap = repo / "snapshots" / ref.read_text("utf-8").strip()
    return snap if snap.is_dir() else None


def _admissions(root: Path) -> dict[str, Any]:
    path = root / ADMISSIONS_FILE
    if not path.is_file():
        return {}
    return cast(dict[str, Any], json.loads(path.read_text("utf-8")))


def _atomic_write(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=dest.name + ".", suffix=".part", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _write_admissions(root: Path, data: dict[str, Any]) -> None:
    _atomic_write(
        root / ADMISSIONS_FILE, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
    )


# --------------------------------------------------------------------------- status


def asset_status(asset: Asset, root: Path | None = None) -> ComponentStatus:
    root = root or models_dir()
    name = f"asset:{asset.id}"
    facts = {"profile": asset.profile, "license": asset.license, "consumer": asset.consumer}
    record = cast(dict[str, Any], _admissions(root).get(asset.id, {}))
    recorded = cast(dict[str, str], record.get("files", {}))
    if asset.kind == "file":
        path = root / asset.relpath
        facts["path"] = str(path)
        if not path.is_file():
            return ComponentStatus(
                name,
                Readiness.MISSING,
                f"not admitted: operator must supply {asset.upstream or asset.relpath} via "
                f"`aidashvideo-models admit {asset.id} FILE`",
                facts,
                True,
            )
        actual = sha256_file(path)
        facts["sha256"] = actual
        expected = asset.sha256 or recorded.get(Path(asset.relpath).name, "")
        if expected and actual != expected:
            return ComponentStatus(
                name, Readiness.CONFLICTING, "sha256 differs from record", facts, True
            )
        if not expected:
            return ComponentStatus(
                name, Readiness.CONFLICTING, "file has no admission record", facts, True
            )
        return ComponentStatus(name, Readiness.VERIFIED, "admitted, hash verified", facts, True)

    snap = hf_snapshot_dir(asset.repo_id, root / "hf-hub")
    facts["repo_id"] = asset.repo_id
    if snap is None:
        return ComponentStatus(
            name,
            Readiness.MISSING,
            f"not admitted: operator must supply {asset.repo_id} "
            f"({', '.join(asset.required_files)}) via `aidashvideo-models admit {asset.id} DIR`",
            facts,
            True,
        )
    facts["snapshot"] = str(snap)
    missing = [f for f in asset.required_files if not (snap / f).is_file()]
    if missing:
        return ComponentStatus(
            name, Readiness.CONFLICTING, f"snapshot lacks {missing}", facts, True
        )
    if not recorded:
        return ComponentStatus(
            name, Readiness.CONFLICTING, "snapshot has no admission record", facts, True
        )
    for rel, digest in recorded.items():
        if not (snap / rel).is_file() or sha256_file(snap / rel) != digest:
            return ComponentStatus(
                name, Readiness.CONFLICTING, f"{rel} changed since admission", facts, True
            )
    facts["admitted_at"] = str(record.get("admitted_at", ""))
    facts["files"] = str(len(recorded))
    return ComponentStatus(
        name,
        Readiness.VERIFIED,
        "admitted (hashes recorded; upstream hashes not pinned)",
        facts,
        True,
    )


def statuses(root: Path | None = None) -> list[ComponentStatus]:
    return [asset_status(a, root) for a in load_manifest()]


# --------------------------------------------------------------------------- admit


def _source_files(source: Path) -> Path:
    """Accept a plain local-dir download, or a hub-cache repo dir (models--org--name)."""
    if (source / "refs" / "main").is_file() and (source / "snapshots").is_dir():
        snap = source / "snapshots" / (source / "refs" / "main").read_text("utf-8").strip()
        if snap.is_dir():
            return snap
    return source


def _record(root: Path, asset: Asset, entry: dict[str, Any]) -> None:
    records = _admissions(root)
    entry["admitted_at"] = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    entry["license"] = asset.license
    records[asset.id] = entry
    _write_admissions(root, records)


def admit(
    asset: Asset, source: Path, root: Path | None = None, revision: str | None = None
) -> ComponentStatus:
    """Copy an operator-supplied asset into the isolated store, hashing every file."""
    root = root or models_dir()
    source = source.resolve()
    if asset.kind == "file":
        if not source.is_file():
            raise FileNotFoundError(f"{source} is not a file")
        digest = sha256_file(source)
        if asset.sha256 and digest != asset.sha256:
            raise ValueError(f"{asset.id}: sha256 {digest} != pinned {asset.sha256}; not admitted")
        _atomic_write(root / asset.relpath, source.read_bytes())
        _record(root, asset, {"source": str(source), "files": {Path(asset.relpath).name: digest}})
        return asset_status(asset, root)

    src = _source_files(source)
    if not src.is_dir():
        raise FileNotFoundError(f"{source} is not a directory")
    missing = [f for f in asset.required_files if not (src / f).is_file()]
    if missing:
        raise FileNotFoundError(f"{asset.id}: source lacks required files {missing}")
    files = sorted(
        p
        for p in src.rglob("*")
        if p.is_file()
        and ".cache" not in p.relative_to(src).parts
        and not p.name.endswith((".lock", ".incomplete", ".part"))
    )
    digests = {str(p.relative_to(src)): sha256_file(p) for p in files}
    # Content-derived 40-hex revision when the upstream commit is not given.
    rev = revision or hashlib.sha1(json.dumps(digests, sort_keys=True).encode()).hexdigest()
    repo = hf_repo_dir(asset.repo_id, root / "hf-hub")
    repo.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=repo))
    try:
        for p in files:
            dest = stage / p.relative_to(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            if sha256_file(dest) != digests[str(p.relative_to(src))]:
                raise RuntimeError(f"copy verification failed for {p}")
        snaps = repo / "snapshots"
        snaps.mkdir(exist_ok=True)
        final = snaps / rev
        if final.exists():
            shutil.rmtree(final)
        os.replace(stage, final)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    (repo / "refs").mkdir(exist_ok=True)
    _atomic_write(repo / "refs" / "main", rev.encode())
    _record(
        root,
        asset,
        {
            "repo_id": asset.repo_id,
            "revision": rev,
            "revision_is_upstream": revision is not None,
            "source": str(source),
            "files": digests,
        },
    )
    return asset_status(asset, root)


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aidashvideo-models",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show every asset's readiness")
    a = sub.add_parser("admit", help="admit an operator-supplied asset")
    a.add_argument("asset_id")
    a.add_argument("source", type=Path, help="local-dir download, hub-cache models--* dir or file")
    a.add_argument("--revision", help="upstream 40-hex commit, if known")
    args = parser.parse_args(argv)
    assets = {x.id: x for x in load_manifest()}
    if args.cmd == "status":
        results = statuses()
    else:
        if args.asset_id not in assets:
            parser.error(f"unknown asset {args.asset_id!r}; known: {', '.join(assets)}")
        results = [admit(assets[args.asset_id], args.source, revision=args.revision)]
    for r in results:
        print(f"{r.readiness.value:12} {r.component:34} {r.detail}")
    return 0 if args.cmd == "status" or all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
