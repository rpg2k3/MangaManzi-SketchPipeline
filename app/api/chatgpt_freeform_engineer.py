"""Claude prompt engineer for the Sketch tab — Freeform mode.

Takes a plain-English description (and an optional flag indicating a
character reference image is attached) and expands it into a complete,
technically precise gpt-image-1 line-art prompt.

Kept separate from chatgpt_prompt_engineer (which is tuned for the base
mannequin construction style) — freeform produces a finished line-art
sketch, not a construction drawing.
"""

import anthropic

from app.cost_logger import log_api_call, estimate_claude_cost
from app.api.chatgpt_prompt_engineer import (
    ARCHETYPES, GENDERS, NEUTRAL_BODY_BLOCK, NEUTRAL_BODY_EXTRAS,
    gender_block_for, gender_override_for, is_neutral_archetype,
)

MODEL = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """
You are the prompt engineer for OpenAI gpt-image-1, specifically for free-form
character illustration sketches in the 9LivesK9 line-art style.

Take the user's plain-English description and expand it into a complete,
technically precise image-generation prompt that gpt-image-1 will receive.

PROMPT PRIORITY ORDER — non-negotiable structure for every output prompt:

If the request says "has_character_reference: yes", the output prompt MUST be
ordered exactly as follows, highest priority first. Note that for free-form
mode the character reference is the only image attached, so it is "Image 1".

1. CHARACTER SHEET FIRST (highest priority).
   Begin with this block, copied verbatim:

   "The character design in Image 1 is the absolute source of truth. Reproduce every detail exactly:
   - Face structure, eye shape, expression style
   - Hair texture, volume, and style precisely as drawn
   - Every outfit element: garments, accessories, straps, belts, boots, gloves, stockings
   - Body proportions as shown in the reference
   - Any unique features: ears, tail, markings
   Do not invent, simplify, or substitute any character detail. If it is in the reference, it must appear in the output."

2. POSE / SCENE SECOND.
   State the pose, action, and setting from the user description in clear,
   anatomically grounded language. Do not restate character design here.

3. STYLE AND QUALITY TAGS LAST (lowest priority).
   Begin this section with the literal phrase:
   "Apply these style qualities without overriding the character design:"
   Then list the style and technical requirements (line art, line weight,
   A4 orientation, white background, print-ready, etc.).

PROPORTION GUIDANCE BLOCK:
The request always contains a "Proportion guidance" block describing the
archetype's head-count and silhouette rules. You MUST include it inside
section 3, after the style/quality bullets, prefixed verbatim with this
subheader on its own line:
"Proportion guidance (subordinate to the character sheet — apply only where the character design allows):"
Copy the block content verbatim under that subheader. Do not paraphrase
the head-count number, size class, or anatomy descriptions.

If the request includes a "Closing override" line, append its content
verbatim on its own line just before the final conflict-resolution line.

End the prompt with this exact line on its own:
"If style instructions conflict with the character sheet, always follow the character sheet."

If the request says "has_character_reference: no", omit section 1 and the
final conflict-resolution line. Describe the pose / scene first, then the
style/quality tags last, and still include the Proportion guidance block
inside section 3 with the same subheader.

THE OUTPUT PROMPT MUST ALWAYS INCLUDE THESE RULES (place them in section 3):
- Line art only — clean black ink lines, varied line weight.
- White background.
- No color, no shading, no rendering, no fills.
- Print-friendly at maximum resolution.
- A4 [portrait|landscape] orientation as specified by the request.

CONTENT-SAFETY:
- Do not include age numbers, year ranges, or words like teen, teenager,
  young, juvenile, minor, kid, child, baby, infant, boy, girl, adolescent.
- Describe the character through proportion descriptors, design features,
  and pose; not through age.

OUTPUT FORMAT:
Return ONLY the final image-generation prompt as plain text. No preamble,
no markdown, no quotes — just the prompt the image API will receive.
""".strip()


def _proportion_guidance_block(archetype: str, gender: str) -> tuple[str, str]:
    """Return (guidance_text, closing_override) for the requested archetype/gender.

    Reuses the same anatomy/head-count rules as build_sketch_instruction so
    Single, Batch, and Freeform all draw from one source of truth. Returns
    closing_override = "" for archetypes below the neutral threshold.
    """
    if archetype not in ARCHETYPES:
        raise ValueError(f"Unknown archetype: {archetype}")
    arch = ARCHETYPES[archetype]
    rules_block = "\n".join(f"- {r}" for r in arch["rules"])

    if is_neutral_archetype(archetype):
        body_text = NEUTRAL_BODY_BLOCK
        extra = NEUTRAL_BODY_EXTRAS.get(archetype)
        if extra:
            body_text = f"{body_text} {extra}"
        body_label = "Body construction (anatomically neutral — gender not applied)"
        closing_override = ""
    else:
        if gender not in GENDERS:
            raise ValueError(f"Unknown gender: {gender}")
        body_text = gender_block_for(gender, archetype)
        body_label = "Gender anatomy"
        closing_override = gender_override_for(gender)

    guidance = (
        f"- The figure should read as approximately {arch['heads']} "
        f"head-heights tall — a {arch['size_class']}.\n"
        f"{rules_block}\n"
        f"- {body_label}: {body_text}"
    )
    return guidance, closing_override


def build_freeform_prompt(api_key: str, description: str, orientation: str,
                          has_character_reference: bool,
                          archetype: str, gender: str) -> dict:
    """Call Claude to expand a freeform user description into a gpt-image-1 prompt.

    Returns {"success": bool, "prompt": str, "cost": float, "error": str}.
    """
    if orientation not in ("portrait", "landscape"):
        orientation = "portrait"

    guidance, closing_override = _proportion_guidance_block(archetype, gender)

    user_message = (
        f"Orientation: A4 {orientation}\n"
        f"has_character_reference: {'yes' if has_character_reference else 'no'}\n"
        f"Description: {description.strip()}\n\n"
        f"Proportion guidance:\n{guidance}"
    )
    if closing_override:
        user_message += f"\n\nClosing override: {closing_override}"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        prompt_text = response.content[0].text.strip()
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = estimate_claude_cost(input_tokens, output_tokens)
        log_api_call(
            provider="anthropic", model=MODEL, operation="chatgpt_freeform_prompt",
            input_tokens=input_tokens, output_tokens=output_tokens,
            estimated_cost_usd=cost, status="success",
        )
        return {"success": True, "prompt": prompt_text, "cost": cost, "error": ""}
    except Exception as e:
        log_api_call(
            provider="anthropic", model=MODEL, operation="chatgpt_freeform_prompt",
            estimated_cost_usd=0, status=f"error: {e}",
        )
        return {"success": False, "prompt": "", "cost": 0.0, "error": str(e)}
