"""Persistent app settings — Chat_GPT pipeline only."""

import json
from pathlib import Path

_CONFIG_DIR = Path(__file__).parent.parent / "config"
_CONFIG_PATH = _CONFIG_DIR / "app_settings.json"

DEFAULTS = {
    "openai_quality": "medium",     # "low" | "medium" | "high"
    "chatgpt_output_dir": "",       # blank = use default <repo>/output/chat_gpt_base
}

# OpenAI gpt-image-1 pricing per quality tier (1024x1536 portrait).
OPENAI_PRICING = {
    "low": 0.011,
    "medium": 0.042,
    "high": 0.167,
}

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if _CONFIG_PATH.exists():
        try:
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            _cache = {**DEFAULTS, **data}
            return _cache
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


def get_openai_quality() -> str:
    return get("openai_quality")


def reset_to_defaults():
    _save(dict(DEFAULTS))
