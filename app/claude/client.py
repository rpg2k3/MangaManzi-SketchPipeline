"""Shared Anthropic SDK client + tool-use helpers.

Two model lanes:
- Opus (claude-opus-4-7) for heavy reasoning: prompt generation, critique,
  scene composition.
- Haiku (claude-haiku-4-5-20251001) for cheap structured tasks: sheet
  validation, simple lookups.
"""

import json

import anthropic

from app.cost_logger import estimate_claude_cost, log_api_call

MODEL_OPUS = "claude-opus-4-7"
MODEL_HAIKU = "claude-haiku-4-5-20251001"


def get_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key)


def call_with_tool(
    api_key: str,
    *,
    model: str,
    system: str,
    user_content: list | str,
    tool_name: str,
    tool_description: str,
    tool_input_schema: dict,
    operation: str,
    max_tokens: int = 2048,
    character_id: str = "",
    pose_id: str = "",
) -> dict:
    """Single-turn call that forces Claude to invoke a tool with a
    JSON-schema-validated payload. Returns the parsed tool input dict.

    This is the structured-output pattern recommended by Anthropic — the
    model fills out the tool's input schema, and we read that input
    directly instead of parsing free-text.
    """
    client = get_client(api_key)
    if isinstance(user_content, str):
        messages = [{"role": "user", "content": user_content}]
    else:
        messages = [{"role": "user", "content": user_content}]

    tool = {
        "name": tool_name,
        "description": tool_description,
        "input_schema": tool_input_schema,
    }

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool_name},
        )
        tool_use_block = next(
            (b for b in response.content if getattr(b, "type", None) == "tool_use"), None
        )
        if tool_use_block is None:
            raise RuntimeError(
                f"Model did not invoke tool '{tool_name}'. Got: {response.content}"
            )
        result = dict(tool_use_block.input)

        cost = estimate_claude_cost(response.usage.input_tokens, response.usage.output_tokens)
        log_api_call(
            provider="anthropic",
            model=model,
            operation=operation,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            estimated_cost_usd=cost,
            character_id=character_id,
            pose_id=pose_id,
            status="success",
        )
        return result

    except Exception as e:
        log_api_call(
            provider="anthropic",
            model=model,
            operation=operation,
            estimated_cost_usd=0,
            character_id=character_id,
            pose_id=pose_id,
            status=f"error: {str(e)[:200]}",
        )
        raise


def encode_image_block(image_bytes: bytes, media_type: str = "image/png") -> dict:
    """Convenience: package raw image bytes into an Anthropic image content block."""
    import base64

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
        },
    }
