"""Claude-driven prompt generation for the PixAI pipeline.

generate_prompt() composes the `prompts` + `negative_prompts` strings
(LoRA stacking and ControlNet attachment are decided by the pipeline
stage itself, since those are deterministic from the LoRA registry).
"""

import json

from .client import MODEL_OPUS, call_with_tool

_SYSTEM = """You are the prompt engineer for the 9LivesK9 sketch pipeline.
Your job: turn a structured generation request into image-generation prompts
for PixAI (Stable Diffusion-style: positive `prompts` + `negative_prompts`).

Rules:
- Use the provided LoRA trigger words verbatim (commas separate concepts).
- Honor the character sheet (build, face, hair, outfit, palette) when supplied.
- Use the archetype's head-count to anchor proportions explicitly.
- When prior critiques are supplied, address each listed drift with concrete
  prompt deltas; do NOT re-roll the same prompt.
- Output strict English; no commentary outside the tool call."""


_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "prompts": {
            "type": "string",
            "description": "Positive prompt — comma-separated tags + clauses.",
        },
        "negative_prompts": {
            "type": "string",
            "description": "Negative prompt — concepts to suppress.",
        },
        "rationale": {
            "type": "string",
            "description": "One sentence explaining the key choices.",
        },
    },
    "required": ["prompts", "negative_prompts", "rationale"],
}


def generate_prompt(
    api_key: str,
    *,
    archetype: dict,
    view: str,
    pose: str | None,
    stage: int,
    sheet: dict | None = None,
    prior_critiques: list[dict] | None = None,
    scene_description: str | None = None,
    lora_triggers: list[str] | None = None,
    pose_id: str = "",
) -> dict:
    """Returns {prompts, negative_prompts, rationale}."""
    lines = [
        f"Stage: {stage}",
        f"Archetype: {json.dumps(archetype)}",
        f"View: {view}",
        f"Pose: {pose or 'unspecified'}",
    ]
    if sheet:
        lines.append(f"Character sheet:\n{json.dumps(sheet, indent=2)}")
    if scene_description:
        lines.append(f"Scene: {scene_description}")
    if lora_triggers:
        lines.append("LoRA triggers to incorporate verbatim:")
        for t in lora_triggers:
            lines.append(f"  - {t}")
    if prior_critiques:
        lines.append("Prior critiques (address each drift in this prompt):")
        for c in prior_critiques:
            lines.append(json.dumps(c))
    user = "\n\n".join(lines)

    return call_with_tool(
        api_key,
        model=MODEL_OPUS,
        system=_SYSTEM,
        user_content=user,
        tool_name="emit_prompt",
        tool_description="Emit positive + negative PixAI prompts.",
        tool_input_schema=_TOOL_SCHEMA,
        operation="generate_prompt",
        max_tokens=1500,
        pose_id=pose_id,
    )
