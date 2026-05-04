"""Claude prompt engineer for the Chat_GPT pipeline.

Takes a simple user request (archetype + view + plain-English pose) and
expands it into a full 9LivesK9 technical prompt suitable for OpenAI
gpt-image-1. The full style guide and archetype proportion rules live in
the system prompt so the user never has to know them.
"""

import anthropic

from app.cost_logger import log_api_call, estimate_claude_cost

MODEL = "claude-sonnet-4-20250514"

ARCHETYPES = {
    "adult":        {"label": "Adult (25+)",         "heads": 8.0},
    "young_adult":  {"label": "Young Adult (18-24)", "heads": 7.5},
    "teen_mature":  {"label": "Teen Mature (15-17)", "heads": 7.0},
    "teen_young":   {"label": "Teen Young (12-14)",  "heads": 6.5},
    "pre_teen":     {"label": "Pre-Teen (10-11)",    "heads": 6.0},
    "child":        {"label": "Child (6-9)",         "heads": 5.5},
    "toddler":      {"label": "Toddler (2-5)",       "heads": 4.5},
    "baby":         {"label": "Baby (0-1)",          "heads": 3.5},
}

GENDERS = {
    "female": {"label": "Female", "filename_prefix": "F"},
    "male":   {"label": "Male",   "filename_prefix": "M"},
}

VIEWS = {
    "front":                  "Front view — character facing the viewer directly.",
    "side_l":                 "Side view (left profile) — character facing screen-left.",
    "side_r":                 "Side view (right profile) — character facing screen-right.",
    "back":                   "Back view — character facing away from the viewer.",
    "three_quarter_front_l":  "Three-quarter front view rotated to screen-left.",
    "three_quarter_front_r":  "Three-quarter front view rotated to screen-right.",
    "three_quarter_back_l":   "Three-quarter back view rotated to screen-left.",
    "three_quarter_back_r":   "Three-quarter back view rotated to screen-right.",
}

# Map our chatgpt view keys to the slugs used in the existing pose_library.json
# (the library's 6-view scheme; the two 3q-back views are net-new).
VIEW_LIBRARY_SLUGS = {
    "front":                  "front",
    "side_l":                 "side_L",
    "side_r":                 "side_R",
    "back":                   "back",
    "three_quarter_front_l":  "3q_front_L",
    "three_quarter_front_r":  "3q_front_R",
    "three_quarter_back_l":   "3q_back_L",
    "three_quarter_back_r":   "3q_back_R",
}

STYLE_GUIDE = """
9LIVESK9 BASE MANNEQUIN STYLE GUIDE — APPLY EVERY RULE:

1. MEDIUM: Light blue pencil construction drawing (Col-Erase non-photo blue, hex ~#7BAFD4). Soft, clean pencil strokes. No rendering, no shading, no color fill.
2. WIREFRAME: Atari-style contour bands wrapping the volumes — torso, ribcage, pelvis, limbs — like topographical lines describing form.
3. JOINTS: Cross-section ovals at all major joints (shoulders, elbows, wrists, hips, knees, ankles) showing rotation axis of each ball-and-socket.
4. HEAD: Bald, faceless head. Single vertical centre-line and single horizontal eye-line forming a cross on the face. No features. No hair.
5. PROPORTION GRID: Vertical head-height measurement column on the LEFT MARGIN with horizontal tick lines numbered 1H, 2H, 3H ... up to the figure's full height. The figure stands aligned to this grid.
6. LINE OF ACTION: A single clean RED curving line overlaid through the spine/torso showing the gestural rhythm of the pose.
7. BACKGROUND: Pure clean white. No shadows, no texture, no environment.
8. FRAMING: A4 ratio. Use PORTRAIT by default. Use LANDSCAPE only when the pose demands it (reclining, prone, leaping horizontally, mid-air dive).
9. RESOLUTION: Maximum print-ready resolution, crisp linework, no JPEG artefacts.
10. ABSOLUTE: Construction-stage drawing only. No clothing, no muscle rendering, no detail beyond wireframe + joints + line of action.
""".strip()

GENDER_RULES = """
GENDER PROPORTION RULES (apply on top of archetype rules; head-count is identical for both genders):

- FEMALE:
    * Shoulders: 2 head-widths across (narrower than male).
    * Defined waist taper — clear narrowing at the natural waist.
    * Wider hip ratio — pelvis silhouette as wide as or wider than the shoulders.
    * Softer ribcage volume; chest volume implied at upper torso.
- MALE:
    * Shoulders: 2.5 head-widths across (athletic, broader than female).
    * Less pronounced waist taper — more of a straight or V-shaped torso.
    * Narrower hips relative to shoulders — V-tapered torso.
    * Broader chest volume; squarer ribcage.

For pre-teen / child / toddler / baby archetypes, gender silhouette differences
should be subtle but still applied at the indicated head-width values.
""".strip()

PROPORTION_RULES = """
ARCHETYPE PROPORTION RULES (head-count = total figure height in head units):

- adult (8.0 heads, 25+):
    * Use gender shoulder rule (Female 2hw / Male 2.5hw).
    * Legs occupy 4 heads (half the figure).
    * Sharp, fully-defined joint articulation. Adult anatomical landmarks visible.
- young_adult (7.5 heads, 18-24):
    * Shoulders 1.75-2 head-widths.
    * Slightly softer joint articulation than adult; landmarks still clear.
- teen_mature (7.0 heads, 15-17):
    * Shoulders 1.75-2 head-widths.
    * Slightly softer joints than adult; emerging adult silhouette.
- teen_young (6.5 heads, 12-14):
    * Head visibly larger relative to body than adult.
    * Shoulders 1.5-1.75 head-widths.
    * Softer joints, narrower frame.
- pre_teen (6.0 heads, 10-11):
    * Head visibly larger; shoulders 1.5-1.75 head-widths.
    * Soft joints, slim limbs.
- child (5.5 heads, 6-9):
    * Head dominant — about 1/5 of total figure height.
    * Shoulders narrow (~1.25-1.5 head-widths).
    * Minimal joint definition; rounded transitions.
- toddler (4.5 heads, 2-5):
    * Belly protrusion forward of the spine; rounded torso.
    * Very short legs — about 1.5 heads of total leg length.
    * Joints almost undefined; soft, chubby silhouette.
- baby (3.5 heads, 0-1):
    * Head ~1/3 of total figure height (cranial dominance).
    * No joint articulation — limbs are smooth tubes.
    * Pronounced belly, very short limbs, non-load-bearing posture.

ORIENTATION HEURISTIC:
- A4 PORTRAIT for: any standing, sitting, kneeling, jumping, action-stance, contrapposto pose.
- A4 LANDSCAPE only for: reclining/lying poses, prone poses, full-extension sprint poses,
  horizontal flying or diving poses, or any pose where the figure's longest axis is horizontal.
""".strip()

SYSTEM_PROMPT = f"""
You are the prompt engineer for the 9LivesK9 base mannequin pipeline. Your job is to expand a short user request into a complete, technically precise image-generation prompt for OpenAI's gpt-image-1 model.

{STYLE_GUIDE}

{GENDER_RULES}

{PROPORTION_RULES}

For each request (archetype, gender, view, pose description), you must:
1. State the archetype, exact head-count, and visible age range.
2. State the gender and apply its silhouette rule (shoulder width, waist taper, hip ratio, chest volume).
3. Apply the per-archetype proportion rules above (leg length, joint softness, head dominance, belly/baby rules) — explicitly mention each rule that is relevant.
4. State the camera view explicitly.
5. Describe the pose precisely, anatomically grounded, with the line of action implied.
6. Restate every rule from the style guide so the image model cannot drift.
7. Decide A4 portrait vs landscape using the orientation heuristic above, and state your choice.
8. End with: "Output: clean white background, A4 [portrait|landscape], 9LivesK9 base mannequin construction sheet."

OUTPUT FORMAT: Return ONLY the final image-generation prompt as plain text. No preamble, no markdown, no quotes — just the prompt the image API will receive.
""".strip()


def build_base_prompt(api_key: str, archetype: str, gender: str, view: str,
                      pose_description: str) -> dict:
    """Call Claude to expand simple inputs into a full gpt-image-1 prompt.

    Returns {"success": bool, "prompt": str, "cost": float, "error": str}.
    """
    arch = ARCHETYPES.get(archetype)
    view_desc = VIEWS.get(view)
    gender_meta = GENDERS.get(gender)
    if not arch:
        return {"success": False, "prompt": "", "cost": 0.0,
                "error": f"Unknown archetype: {archetype}"}
    if not view_desc:
        return {"success": False, "prompt": "", "cost": 0.0,
                "error": f"Unknown view: {view}"}
    if not gender_meta:
        return {"success": False, "prompt": "", "cost": 0.0,
                "error": f"Unknown gender: {gender}"}

    user_message = (
        f"Archetype: {archetype} — {arch['label']} — {arch['heads']} heads tall\n"
        f"Gender: {gender} ({gender_meta['label']})\n"
        f"View: {view} — {view_desc}\n"
        f"Pose: {pose_description.strip() or 'neutral standing pose, contrapposto'}"
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        prompt_text = response.content[0].text.strip()
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = estimate_claude_cost(input_tokens, output_tokens)

        log_api_call(
            provider="anthropic", model=MODEL, operation="chatgpt_base_prompt",
            input_tokens=input_tokens, output_tokens=output_tokens,
            estimated_cost_usd=cost, status="success",
        )
        return {"success": True, "prompt": prompt_text, "cost": cost, "error": ""}

    except Exception as e:
        log_api_call(
            provider="anthropic", model=MODEL, operation="chatgpt_base_prompt",
            estimated_cost_usd=0, status=f"error: {e}",
        )
        return {"success": False, "prompt": "", "cost": 0.0, "error": str(e)}
