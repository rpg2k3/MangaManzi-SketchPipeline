"""Character sheet extraction + Anthropic key validation.

Ported from the alpha app/api/claude_client.py.
"""

import base64
import json
import time
from pathlib import Path

import anthropic

from app.cost_logger import estimate_claude_cost, log_api_call
from prompts.extraction_system_prompt import EXTRACTION_SYSTEM_PROMPT

MODEL = "claude-haiku-4-5-20251001"

_test_cache: dict[str, tuple[float, str, str]] = {}
_CACHE_TTL = 300


def test_connection(api_key: str, bypass_cache: bool = False) -> tuple[str, str]:
    """Validate Anthropic API key. Returns (status, message).

    status ∈ {"ok", "invalid", "rate_limited", "warning", "error"}
    """
    cache_key = api_key[:8]
    now = time.time()

    if not bypass_cache and cache_key in _test_cache:
        ts, cached_status, cached_msg = _test_cache[cache_key]
        if now - ts < _CACHE_TTL:
            return cached_status, f"{cached_msg} (cached)"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        client.messages.create(
            model=MODEL,
            max_tokens=4,
            messages=[{"role": "user", "content": "Reply OK."}],
        )
        result = ("ok", f"Connected. Model: {MODEL}")
    except anthropic.AuthenticationError:
        result = ("invalid", "Invalid API key (401/403).")
    except anthropic.PermissionDeniedError:
        result = ("invalid", "Permission denied — check key permissions.")
    except anthropic.RateLimitError:
        result = ("rate_limited", "Rate limited — key is valid but throttled.")
    except anthropic.NotFoundError:
        result = ("warning", f"Model {MODEL} not found on this key.")
    except Exception as e:
        err = str(e)
        if "timeout" in err.lower() or "connect" in err.lower():
            result = ("error", f"Network error: {err[:100]}")
        else:
            result = ("error", f"Connection failed: {err[:100]}")

    _test_cache[cache_key] = (now, result[0], result[1])
    return result


def extract_character(api_key: str, image_path: Path, character_id: str = "") -> dict:
    """Upload character sheet image, return structured JSON extraction."""
    client = anthropic.Anthropic(api_key=api_key)

    image_bytes = image_path.read_bytes()
    b64_image = base64.standard_b64encode(image_bytes).decode("utf-8")

    suffix = image_path.suffix.lower()
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    media_type = media_types.get(suffix, "image/png")

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=EXTRACTION_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64_image},
                    },
                    {
                        "type": "text",
                        "text": (
                            f'Extract this character. character_id: "{character_id}"'
                            if character_id else "Extract this character."
                        ),
                    },
                ],
            }],
        )

        raw_text = response.content[0].text
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = estimate_claude_cost(input_tokens, output_tokens)

        log_api_call(
            provider="anthropic", model=MODEL, operation="character_extraction",
            input_tokens=input_tokens, output_tokens=output_tokens,
            estimated_cost_usd=cost, character_id=character_id, status="success",
        )

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            if "```json" in raw_text:
                json_str = raw_text.split("```json")[1].split("```")[0].strip()
                data = json.loads(json_str)
            elif "```" in raw_text:
                json_str = raw_text.split("```")[1].split("```")[0].strip()
                data = json.loads(json_str)
            else:
                return {
                    "success": False, "data": None, "raw": raw_text,
                    "input_tokens": input_tokens, "output_tokens": output_tokens,
                    "cost": cost, "error": "Could not parse JSON from response",
                }

        return {
            "success": True, "data": data, "raw": raw_text,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cost": cost,
        }

    except Exception as e:
        log_api_call(
            provider="anthropic", model=MODEL, operation="character_extraction",
            estimated_cost_usd=0, character_id=character_id, status=f"error: {e}",
        )
        return {"success": False, "data": None, "raw": "", "cost": 0, "error": str(e)}
