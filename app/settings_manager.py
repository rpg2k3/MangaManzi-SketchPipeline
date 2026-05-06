"""Persistent app settings — JSON file with in-memory cache.

Currently empty of provider config. Phase 3 will add PixAI defaults
(base model, sampling method, dimensions, high-priority opt-in, etc.).
"""

import json
from pathlib import Path

_CONFIG_DIR = Path(__file__).parent.parent / "config"
_CONFIG_PATH = _CONFIG_DIR / "app_settings.json"

DEFAULTS: dict = {}

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if _CONFIG_PATH.exists():
        try:
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            merged = {**DEFAULTS, **data}
            _cache = merged
            return merged
        except Exception:
            pass
    _cache = dict(DEFAULTS)
    return _cache


def _save(data: dict):
    global _cache
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _cache = data


def get(key: str):
    return _load().get(key, DEFAULTS.get(key))


def set_value(key: str, value):
    data = _load()
    data[key] = value
    _save(data)


def get_all() -> dict:
    return dict(_load())


def reset_to_defaults():
    _save(dict(DEFAULTS))
