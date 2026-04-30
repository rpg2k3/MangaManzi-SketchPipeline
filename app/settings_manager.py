"""Persistent app settings — lane provider config, quality tier, etc."""

import json
from pathlib import Path

_CONFIG_DIR = Path(__file__).parent.parent / "config"
_CONFIG_PATH = _CONFIG_DIR / "app_settings.json"

DEFAULTS = {
    "mannequin_provider": "openai",       # "openai" | "gemini"
    "sketch_provider": "gemini",          # "gemini" | "openai"
    "openai_quality": "medium",           # "low" | "medium" | "high"
    "mannequin_quality_tag": "high quality manga reference mannequin, clean wireframe construction, anime proportions, light blue pencil, professional pose library reference",
    "sketch_quality_tag": "",
    "dual_reference_mode": False,         # False = GPT ref only (safer), True = CSP+GPT dual attach
}

# Provider → model mapping
PROVIDER_MODELS = {
    "openai": "gpt-image-1",
    "gemini": "gemini-2.5-flash-image",
    "anthropic": "claude-haiku-4-5-20251001",
}

# OpenAI pricing per quality tier (1024x1536 portrait)
OPENAI_PRICING = {
    "low": 0.011,
    "medium": 0.042,
    "high": 0.167,
}

# Gemini pricing
GEMINI_PRICING = {
    "batch": 0.0195,
    "standard": 0.039,
}

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if _CONFIG_PATH.exists():
        try:
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            # Merge with defaults for any missing keys
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


def get_mannequin_provider() -> str:
    return get("mannequin_provider")


def get_sketch_provider() -> str:
    return get("sketch_provider")


def get_openai_quality() -> str:
    return get("openai_quality")


def get_mannequin_model() -> str:
    return PROVIDER_MODELS.get(get_mannequin_provider(), "gpt-image-1")


def get_sketch_model() -> str:
    return PROVIDER_MODELS.get(get_sketch_provider(), "gemini-2.5-flash-image")


def estimate_mannequin_cost(count: int) -> float:
    provider = get_mannequin_provider()
    if provider == "openai":
        return count * OPENAI_PRICING.get(get_openai_quality(), 0.042)
    return count * GEMINI_PRICING["standard"]


def estimate_sketch_cost(count: int) -> float:
    provider = get_sketch_provider()
    if provider == "openai":
        return count * OPENAI_PRICING.get(get_openai_quality(), 0.042)
    return count * GEMINI_PRICING["standard"]


def estimate_sketch_cost_per_pose() -> float:
    """Image cost + Claude assembly cost (~$0.006)."""
    provider = get_sketch_provider()
    if provider == "openai":
        img = OPENAI_PRICING.get(get_openai_quality(), 0.042)
    else:
        img = GEMINI_PRICING["standard"]
    return img + 0.006


def reset_to_defaults():
    _save(dict(DEFAULTS))
