"""Claude-driven prompt generation for the PixAI pipeline.

generate_prompt() composes the `prompts` + `negative_prompts` strings
(LoRA stacking and ControlNet attachment are decided by the pipeline
stage itself, since those are deterministic from the LoRA registry).

Stage 3 fork: the character LoRA's architecture decides how
sheet.learnedDrifts are injected.
- DiT.2 — negative prompts unsupported. Drift CORRECTIONS go into the
  positive prompt as re-specifications. Negative is forced to "".
- SDXL / Illustrious — Drift IDENTIFIERS go into the negative prompt
  as absences, atop a fixed SDXL template. Claude's negative is
  discarded in favor of the deterministic template.
- Unknown — warn once; fall back to SDXL/Illustrious behavior (safer
  default since it adds a negative prompt rather than relying on
  positive re-specification only).
"""

import json
import warnings

from .client import MODEL_OPUS, call_with_tool

# SDXL/Illustrious Stage 3 negative template (per Phase 1C spec).
SDXL_STAGE_3_NEGATIVE_BASE = (
    "worst_quality, bad_quality, very_displeasing, displeasing, "
    "oldest, artistic_error, lowres, jpeg_artifacts, censor, "
    "watermark, bad_hands, bad_anatomy"
)


def _apply_architecture_handling(
    result: dict, architecture: str, sheet: dict | None
) -> dict:
    """Post-process Claude's prompt output based on the character LoRA's
    architecture. See module docstring for the decision matrix.
    """
    drifts: list[dict] = []
    if sheet:
        drifts = sheet.get("learnedDrifts") or []

    if architecture == "dit2":
        corrections = [
            (d.get("correction") or "").strip()
            for d in drifts
            if d.get("correction")
        ]
        positive_parts = [result.get("prompts", "").strip(), *corrections]
        result["prompts"] = ", ".join(p for p in positive_parts if p)
        result["negative_prompts"] = ""
        return result

    if architecture == "unknown":
        warnings.warn(
            "generate_prompt: architecture='unknown' on the character LoRA. "
            "Falling back to SDXL/Illustrious negative-template behavior "
            "(safer than DiT.2 positive-only since it adds a negative). Set "
            "architecture on the LoRA registry entry to remove this warning.",
            stacklevel=2,
        )
    # SDXL / Illustrious / unknown — deterministic SDXL template + drifts.
    drift_terms = [
        (d.get("drift") or "").strip()
        for d in drifts
        if d.get("drift")
    ]
    negative_parts = [SDXL_STAGE_3_NEGATIVE_BASE, *drift_terms]
    result["negative_prompts"] = ", ".join(p for p in negative_parts if p)
    return result

_SYSTEM = """You are the prompt engineer for the 9LivesK9 sketch pipeline.
Your job: turn a structured generation request into image-generation prompts
for PixAI (Stable Diffusion-style: positive `prompts` + `negative_prompts`).

Rules:
- Use the provided LoRA trigger words verbatim (commas separate concepts).
- Honor the character sheet (build, face, hair, outfit, palette) when supplied.
- Use the archetype's head-count to anchor proportions explicitly.
- When prior critiques are supplied, address each listed drift with concrete
  prompt deltas; do NOT re-roll the same prompt.
- Output strict English; no commentary outside the tool call.

STAGE 3 TOKEN ORDER AND WEIGHTING (apply when stage == 3):

The positive prompt for the character finalization stage MUST be ordered
from highest to lowest priority, so attention concentrates on character
identity before drifting to style. Order:

  1. Trigger words (verbatim from the LoRA — never re-weight; never reorder
     internally; commas as supplied).
  2. Subject anchor: 1girl / 1boy / 1child + solo.
  3. View tag (front, cowboy_shot, full_body, three_quarter_view, etc.).
  4. Pose tag (contrapposto, hand_on_hip, walking, etc.).
  5. Anatomy / proportion (head-height count, build descriptors).
  6. Hair tags (color, length, texture, style).
  7. Face / skin tags (skin tone, eye color, expression).
  8. Outfit tags — APPLY WEIGHTING HERE:
       - Main garments: wrap as `(token:1.2)` — e.g. (fitted_a_line_mini_skirt:1.2)
       - Accessories: wrap as `(token:1.3)` — e.g. (heart_charm:1.3),
         (side_belt_chain:1.3), (mid_calf_lace_up_platform_boots:1.3)
       - The `(token:weight)` syntax is preserved verbatim through the
         booru rewriter. Use it ONLY here; never on triggers or quality.
  9. Style boosters — wrap as `(token:0.9)` so they don't out-rank outfit
     terms. Examples: (cinematic_lighting:0.9), (dynamic_pose:0.9).
  10. Quality tags (no weighting): masterpiece, best_quality, absurdres,
      newest, etc.

WHY: outfit fidelity drift is the #1 failure mode for character LoRAs.
Up-weighting accessories and main garments while down-weighting style
boosters ensures the model attends to character identity tokens before
the looser style terms.

DiT.2 ARCHITECTURE NOTE: when the request specifies architecture="dit2",
the pipeline post-processes the result to inject sheet.learnedDrifts
corrections positively and to clear the negative prompt. You may still
emit a negative — it will be discarded for DiT.2 — but emitting one
is harmless. Concentrate on the positive ordering rules above."""


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
    architecture: str = "unknown",
) -> dict:
    """Returns {prompts, negative_prompts, rationale}.

    For Stage 3, post-processes Claude's output per the character LoRA's
    `architecture`. See module docstring for the decision matrix.
    """
    lines = [
        f"Stage: {stage}",
        f"Architecture: {architecture}",
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

    result = call_with_tool(
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
    if stage >= 3:
        result = _apply_architecture_handling(result, architecture, sheet)
    return result
