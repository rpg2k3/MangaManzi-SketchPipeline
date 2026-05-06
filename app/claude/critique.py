"""Claude-driven image critique.

Returns the structured critique format defined in Phase 6.5:
  {drifts: [{aspect, expected, observed, severity}],
   successes: [...],
   suggestedPromptDeltas: [...]}
"""

import json
from pathlib import Path

from .client import MODEL_OPUS, call_with_tool, encode_image_block

_SYSTEM = """You are the in-house art director for the 9LivesK9 sketch pipeline.
You review a generated image against an EXPECTATION dict (archetype proportions,
character sheet, scene description) and report a structured critique.

For each drift you identify:
- aspect: short tag (e.g. "head_proportion", "outfit_color", "pose_line_of_action")
- expected: what the spec called for, in concrete terms
- observed: what the image actually shows
- severity: "minor" | "moderate" | "major"

Successes: enumerate what landed well. Used by the regeneration loop to
preserve those qualities.

suggestedPromptDeltas: short, actionable adjustments to the next prompt
that target each drift. Do NOT propose to "re-roll" — propose specific
changes."""

_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "drifts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "aspect": {"type": "string"},
                    "expected": {"type": "string"},
                    "observed": {"type": "string"},
                    "severity": {"type": "string", "enum": ["minor", "moderate", "major"]},
                },
                "required": ["aspect", "expected", "observed", "severity"],
            },
        },
        "successes": {"type": "array", "items": {"type": "string"}},
        "suggestedPromptDeltas": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["drifts", "successes", "suggestedPromptDeltas"],
}


def critique_image(
    api_key: str,
    image_path: Path,
    expected: dict,
    *,
    character_id: str = "",
    pose_id: str = "",
) -> dict:
    image_path = Path(image_path)
    media_type = _MEDIA_TYPES.get(image_path.suffix.lower(), "image/png")
    user_content = [
        encode_image_block(image_path.read_bytes(), media_type=media_type),
        {
            "type": "text",
            "text": (
                "EXPECTATION:\n```json\n"
                + json.dumps(expected, indent=2)
                + "\n```\n\nReturn a structured critique via the tool."
            ),
        },
    ]
    return call_with_tool(
        api_key,
        model=MODEL_OPUS,
        system=_SYSTEM,
        user_content=user_content,
        tool_name="report_critique",
        tool_description="Emit a structured critique of the supplied image.",
        tool_input_schema=_TOOL_SCHEMA,
        operation="critique_image",
        max_tokens=2048,
        character_id=character_id,
        pose_id=pose_id,
    )
