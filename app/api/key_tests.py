"""Lightweight API-key validation for OpenAI and Anthropic.

Used by the Settings tab and the first-run onboarding dialog. Caches the
last result for 5 minutes to avoid hammering the providers when the user
clicks Test repeatedly.
"""

import time

import anthropic
import openai

CLAUDE_PROBE_MODEL = "claude-haiku-4-5-20251001"
OPENAI_PROBE_MODEL = "gpt-image-1"

_CACHE_TTL = 300  # seconds
_cache: dict[tuple[str, str], tuple[float, str, str]] = {}


def _cached(provider: str, key: str) -> tuple[str, str] | None:
    entry = _cache.get((provider, key[:8]))
    if not entry:
        return None
    ts, status, msg = entry
    if time.time() - ts < _CACHE_TTL:
        return status, f"{msg} (cached)"
    return None


def _record(provider: str, key: str, status: str, msg: str) -> tuple[str, str]:
    _cache[(provider, key[:8])] = (time.time(), status, msg)
    return status, msg


def test_openai(key: str, bypass_cache: bool = False) -> tuple[str, str]:
    if not bypass_cache:
        c = _cached("openai", key)
        if c:
            return c
    try:
        openai.OpenAI(api_key=key).models.list()
        return _record("openai", key, "ok", f"Connected. Model: {OPENAI_PROBE_MODEL}")
    except openai.AuthenticationError:
        return _record("openai", key, "invalid", "Invalid API key (401).")
    except openai.PermissionDeniedError:
        return _record("openai", key, "invalid", "Permission denied (403).")
    except openai.RateLimitError:
        return _record("openai", key, "rate_limited",
                       "Rate limited — key is valid but throttled.")
    except Exception as e:
        err = str(e)[:100]
        kind = "error"
        if "timeout" in err.lower() or "connect" in err.lower():
            err = f"Network error: {err}"
        return _record("openai", key, kind, err)


def test_anthropic(key: str, bypass_cache: bool = False) -> tuple[str, str]:
    if not bypass_cache:
        c = _cached("anthropic", key)
        if c:
            return c
    try:
        anthropic.Anthropic(api_key=key).messages.create(
            model=CLAUDE_PROBE_MODEL, max_tokens=4,
            messages=[{"role": "user", "content": "Reply OK."}],
        )
        return _record("anthropic", key, "ok", f"Connected. Probe: {CLAUDE_PROBE_MODEL}")
    except anthropic.AuthenticationError:
        return _record("anthropic", key, "invalid", "Invalid API key (401/403).")
    except anthropic.PermissionDeniedError:
        return _record("anthropic", key, "invalid", "Permission denied.")
    except anthropic.RateLimitError:
        return _record("anthropic", key, "rate_limited",
                       "Rate limited — key is valid but throttled.")
    except anthropic.NotFoundError:
        return _record("anthropic", key, "warning",
                       f"Probe model {CLAUDE_PROBE_MODEL} not available on this key.")
    except Exception as e:
        err = str(e)[:100]
        kind = "error"
        if "timeout" in err.lower() or "connect" in err.lower():
            err = f"Network error: {err}"
        return _record("anthropic", key, kind, err)
