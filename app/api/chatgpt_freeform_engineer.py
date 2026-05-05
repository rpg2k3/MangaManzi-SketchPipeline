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

MODEL = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """
You are the prompt engineer for OpenAI gpt-image-1, specifically for free-form
character illustration sketches in the 9LivesK9 line-art style.

Take the user's plain-English description and expand it into a complete,
technically precise image-generation prompt that gpt-image-1 will receive.

THE OUTPUT PROMPT MUST ALWAYS INCLUDE THESE RULES:
- Line art only — clean black ink lines, varied line weight.
- White background.
- No color, no shading, no rendering, no fills.
- Print-friendly at maximum resolution.
- A4 [portrait|landscape] orientation as specified by the request.

IF THE REQUEST SAYS "has_character_reference: yes":
- Add: "Match the character design from the reference image exactly,
  preserving hair, face, clothing silhouette, accessories, and body proportions."

CONTENT-SAFETY:
- Do not include age numbers, year ranges, or words like teen, teenager,
  young, juvenile, minor, kid, child, baby, infant, boy, girl, adolescent.
- Describe the character through proportion descriptors, design features,
  and pose; not through age.

OUTPUT FORMAT:
Return ONLY the final image-generation prompt as plain text. No preamble,
no markdown, no quotes — just the prompt the image API will receive.
""".strip()


def build_freeform_prompt(api_key: str, description: str, orientation: str,
                          has_character_reference: bool) -> dict:
    """Call Claude to expand a freeform user description into a gpt-image-1 prompt.

    Returns {"success": bool, "prompt": str, "cost": float, "error": str}.
    """
    if orientation not in ("portrait", "landscape"):
        orientation = "portrait"

    user_message = (
        f"Orientation: A4 {orientation}\n"
        f"has_character_reference: {'yes' if has_character_reference else 'no'}\n"
        f"Description: {description.strip()}"
    )

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
