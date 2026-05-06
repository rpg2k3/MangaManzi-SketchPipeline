"""Compose a scene plan: which sheets apply, which LoRAs to stack,
prompt skeleton, suggested ControlNet inputs for the user-supplied
OpenPose skeleton + depth maps.
"""

import json

from .client import MODEL_OPUS, call_with_tool

_SYSTEM = """You are scene-composing for 9LivesK9. Inputs: a list of character
sheets and a free-text scene description. Output: a structured scene plan that
the pipeline will use to assemble per-character generation requests.

Decisions:
- Which sheets are subjects vs. background presence
- Which LoRA stack each subject needs (base, sketch, character)
- A high-level prompt skeleton (do NOT write the final positive prompt)
- Suggested ControlNet types based on whether the user provided OpenPose +
  Depth (typical) or only OpenPose (acceptable fallback)"""


_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "subjects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sheetId": {"type": "string"},
                    "role": {"type": "string", "enum": ["primary", "secondary", "background"]},
                    "lora_stack": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["sheetId", "role", "lora_stack"],
            },
        },
        "prompt_skeleton": {"type": "string"},
        "suggested_control_nets": {
            "type": "array",
            "items": {"type": "string"},
            "description": "ControlNet types: openpose, depth, etc.",
        },
        "notes": {"type": "string"},
    },
    "required": ["subjects", "prompt_skeleton", "suggested_control_nets"],
}


def compose_scene(
    api_key: str,
    sheets: list[dict],
    scene_description: str,
) -> dict:
    user = (
        "SHEETS:\n"
        + "\n".join(f"```json\n{json.dumps(s, indent=2)}\n```" for s in sheets)
        + f"\n\nSCENE:\n{scene_description}\n\nEmit the plan via the tool."
    )
    return call_with_tool(
        api_key,
        model=MODEL_OPUS,
        system=_SYSTEM,
        user_content=user,
        tool_name="emit_scene_plan",
        tool_description="Emit the scene composition plan.",
        tool_input_schema=_TOOL_SCHEMA,
        operation="compose_scene",
        max_tokens=2048,
    )
