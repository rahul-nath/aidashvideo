"""Environment that keeps ML providers offline and isolated from shared caches.

Every provider worker must be started with :func:`provider_environment`; it
disables Hugging Face network access and points all caches at ``.deps/models``
so a provider can neither download nor swap a shared model (I8, V14, V18).
"""

from __future__ import annotations

import os

from .paths import hf_hub_cache_dir, models_dir

OFFLINE_FLAGS: dict[str, str] = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "DO_NOT_TRACK": "1",
}


def provider_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.update(OFFLINE_FLAGS)
    env["HF_HUB_CACHE"] = str(hf_hub_cache_dir())
    env["HF_HOME"] = str(models_dir() / "hf-home")
    env["TORCH_HOME"] = str(models_dir() / "torch-home")
    env.pop("HF_TOKEN", None)
    return env
