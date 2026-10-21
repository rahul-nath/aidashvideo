"""Child-process probe of the optional ML runtimes (prints one JSON line).

Imports only; never constructs a model from a hub id and never loads weights.
"""

from __future__ import annotations

import importlib
import importlib.metadata as md
import json
import sys
import warnings
from typing import Any


def _version(dist: str) -> str:
    try:
        return md.version(dist)
    except md.PackageNotFoundError:
        return ""


def _try_import(module: str, names: tuple[str, ...] = ()) -> str:
    try:
        mod = importlib.import_module(module)
        for n in names:
            getattr(mod, n)
    except Exception as exc:  # report, never raise: missing optional stacks are data
        return f"{type(exc).__name__}: {exc}"
    return ""


def main() -> int:
    out: dict[str, Any] = {"python": sys.version.split()[0]}
    out["versions"] = {
        d: _version(d)
        for d in ("mlx", "mlx-vlm", "mlx-metal", "huggingface-hub", "transformers", "numpy")
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out["imports"] = {
            "clip-tokenizer": _try_import("transformers", ("CLIPTokenizer",)),
            "mlx": _try_import("mlx.core"),
            "sam3_1-mlx-vlm": _try_import(
                "mlx_vlm.models.sam3_1.tracker", ("MultiplexTrackerModel",)
            ),
        }
        devices: dict[str, bool] = {"cpu": True, "metal": False}
        if not out["imports"]["mlx"]:
            import mlx.core as mx  # type: ignore[import-not-found]  # pyright: ignore

            metal: Any = getattr(mx, "metal", None)
            devices["metal"] = bool(metal is not None and metal.is_available())
        out["devices"] = devices
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
