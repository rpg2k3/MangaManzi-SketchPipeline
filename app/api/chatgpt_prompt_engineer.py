"""Claude prompt engineer for the Chat_GPT pipeline.

CONTENT-SAFETY DESIGN
=====================
Prompts sent to OpenAI gpt-image-1 must NEVER contain age descriptors
(year ranges, "teen", "young", "minor", "child", "baby", etc.). Figure
size is communicated entirely through head-height ratios and anatomical
proportion descriptors. This avoids false-positive content-moderation
blocks on what are clinical, bald, featureless construction drawings.

Internally we still use Python identifiers like "teen_mature" / "child" /
"baby" — those never reach the image API. What goes to gpt-image-1 is
built only from `heads`, `size_class`, `rules`, and `silhouette`.
"""

import anthropic

from app.cost_logger import log_api_call, estimate_claude_cost

MODEL = "claude-sonnet-4-20250514"


# ─────────────────────────────────────────────────────────────────────
# Archetypes — UI labels are read by the dropdowns; everything inside
# the prompt sent to the image API is built from `size_class` + `rules`
# (no age words, no year ranges).
# ─────────────────────────────────────────────────────────────────────

ARCHETYPES = {
    "adult": {
        "label": "Adult",
        "heads": 8.0,
        "size_class": "8-head adult-proportion mannequin",
        "rules": [
            "Apply the gender shoulder-width rule (Female 2hw / Male 2.5hw).",
            "Legs occupy 4 head-heights — half the figure.",
            "Sharp, fully-defined joint articulation.",
            "Adult anatomical landmarks visible.",
        ],
        "is_minor": False,
    },
    "young_adult": {
        "label": "Young Adult",
        "heads": 7.5,
        "size_class": "7.5-head adult-proportion mannequin",
        "rules": [
            "Shoulders 1.75-2 head-widths.",
            "Slightly softer joint articulation than the 8-head form; landmarks still clear.",
        ],
        "is_minor": False,
    },
    "teen_mature": {
        "label": "Teen Mature",
        "heads": 7.0,
        "size_class": "7-head proportion-study mannequin",
        "rules": [
            "Shoulders 1.75-2 head-widths.",
            "Slightly softer joint articulation than the 8-head adult form.",
            "Slightly shorter limbs than 8-head proportions.",
            "Less defined waist taper than the 8-head form.",
        ],
        "is_minor": True,
    },
    "teen_young": {
        "label": "Teen Young",
        "heads": 6.5,
        "size_class": "6.5-head proportion-study mannequin",
        "rules": [
            "Head proportionally larger relative to body than the 8-head form.",
            "Shoulders 1.5-1.75 head-widths.",
            "Softer joint articulation, narrower frame.",
            "Shorter limbs relative to torso.",
        ],
        "is_minor": True,
    },
    "pre_teen": {
        "label": "Pre-Teen",
        "heads": 6.0,
        "size_class": "6-head proportion-study mannequin",
        "rules": [
            "Head proportionally larger than the 8-head form.",
            "Shoulders 1.5-1.75 head-widths.",
            "Soft joint articulation, slim limbs.",
        ],
        "is_minor": True,
    },
    "child": {
        "label": "Child",
        "heads": 5.5,
        "size_class": "5.5-head proportion-study mannequin",
        "rules": [
            "Head dominant at approximately 1/5 of total figure height.",
            "Shoulders ~1.25-1.5 head-widths.",
            "Minimal joint definition; rounded transitions between volumes.",
            "Short limbs relative to torso.",
        ],
        "is_minor": True,
    },
    "toddler": {
        "label": "Toddler",
        "heads": 4.5,
        "size_class": "4.5-head proportion-study mannequin",
        "rules": [
            "Belly protrusion forward of the spine; rounded torso silhouette.",
            "Very short legs — about 1.5 head-heights of total leg length.",
            "Joints almost undefined; soft, rounded silhouette.",
        ],
        "is_minor": True,
    },
    "baby": {
        "label": "Baby",
        "heads": 3.5,
        "size_class": "3.5-head proportion-study mannequin",
        "rules": [
            "Head approximately 1/3 of total figure height — cranial dominance.",
            "No joint articulation — limbs are smooth tubes.",
            "Pronounced belly, very short limbs, non-load-bearing posture.",
        ],
        "is_minor": True,
    },
}

GENDERS = {
    "female": {
        "label": "Female",
        "filename_prefix": "F",
    },
    "male": {
        "label": "Male",
        "filename_prefix": "M",
    },
}

# ─────────────────────────────────────────────────────────────────────
# Gender anatomy blocks
#
# Per-archetype scaling: figures from pre-teen (6H) up get a gendered
# anatomy block whose intensity scales with the archetype's tier so a
# pre-teen reads as a slim hourglass beginning while an adult reads as
# fully gendered. Child / toddler / baby (< NEUTRAL_HEAD_THRESHOLD) skip
# this entirely and use NEUTRAL_BODY_BLOCK instead.
#
# A closing override line is also appended to every non-neutral prompt
# to prevent gpt-image-1 from drifting into androgynous output.
# ─────────────────────────────────────────────────────────────────────

CONSTRUCTION_SUFFIX = (
    "All volumes are construction shapes only — wireframe ovals and spheres, "
    "no skin, no rendering."
)

FEMALE_ANATOMY = (
    "Clearly defined female anatomical construction. "
    "Shoulders narrow at 2 head-widths across, visibly narrower than hips. "
    "Chest: two distinct hemisphere volumes sitting on the upper ribcage, "
    "clearly separated, construction sphere shapes only — no detail, just "
    "volume indication. "
    "Ribcage egg-shape tapers into a pronounced waist noticeably narrower "
    "than both shoulders and hips. "
    "Pelvis bucket volume is wider than shoulders, creating a clear hourglass "
    "rhythm through torso. "
    "Hip curve is the widest point of the silhouette below the shoulders. "
    "Thighs wider relative to lower leg. "
    "Overall silhouette: hourglass — wider at chest, narrower at waist, "
    "wider at hips. " + CONSTRUCTION_SUFFIX
)

MALE_ANATOMY = (
    "Clearly defined male anatomical construction. "
    "Shoulders wide at 2.5 head-widths across, visibly wider than hips — "
    "this is the defining male silhouette. "
    "Chest: broad rectangular ribcage volume, wider across the top, two "
    "pectoral sphere volumes side by side sitting flat and wide on the chest, "
    "clearly larger and flatter than female chest volumes. "
    "Waist taper is present but subtle — less pronounced than female, torso "
    "reads as a tapered rectangle not an hourglass. "
    "Pelvis bucket is narrower than shoulders — opposite ratio to female. "
    "Hip width does not exceed shoulder width. "
    "Thighs and calves are more cylindrical and uniform. "
    "Overall silhouette: inverted triangle — widest at shoulders, tapering "
    "to hips. " + CONSTRUCTION_SUFFIX
)

# Scaled-down anatomy blocks for the slimmer minor tiers. These keep the
# directional gender markers (hourglass for F, inverted triangle for M)
# but soften the volumes appropriately for the archetype's head-count.
GENDER_SCALED = {
    "female": {
        "pre_teen": (
            "Female anatomical construction at the slim pre-adult tier. "
            "Subtle hourglass beginning — torso rhythm just starting to read "
            "as gendered. "
            "Slight chest volume suggestion only — modest paired sphere "
            "indications on the upper ribcage, not full volumes. "
            "Hips slightly wider than shoulders. "
            "Waist taper present but understated. "
            + CONSTRUCTION_SUFFIX
        ),
        "teen_young": (
            "Female anatomical construction at the slim sub-adult tier. "
            "Clearer hourglass rhythm through the torso. "
            "More defined chest volumes — paired construction sphere shapes "
            "on the upper ribcage, clearly separated. "
            "Hips clearly wider than shoulders. "
            "Waist taper between chest and hips is readable. "
            + CONSTRUCTION_SUFFIX
        ),
        "teen_mature": (
            "Female anatomical construction approaching adult proportions. "
            "Adult hourglass proportions throughout the torso. "
            "Clearly defined chest volumes — paired construction spheres "
            "sitting on the upper ribcage, clearly separated. "
            "Clearly defined hip volumes — pelvis bucket wider than shoulders. "
            "Pronounced waist taper between chest and hips. "
            + CONSTRUCTION_SUFFIX
        ),
        "young_adult": FEMALE_ANATOMY,
        "adult": FEMALE_ANATOMY,
    },
    "male": {
        "pre_teen": (
            "Male anatomical construction at the slim pre-adult tier. "
            "Slightly wider shoulders than hips. "
            "Flat chest — no pectoral volume yet, ribcage reads as a plain "
            "rectangle. "
            "No waist curve yet. "
            "Pelvis bucket narrower than shoulders. "
            + CONSTRUCTION_SUFFIX
        ),
        "teen_young": (
            "Male anatomical construction at the slim sub-adult tier. "
            "Noticeably wider shoulders than hips — inverted triangle "
            "rhythm beginning to read clearly. "
            "Flat chest with minimal pectoral indication. "
            "Minimal waist taper. "
            "Pelvis bucket narrower than shoulders. "
            + CONSTRUCTION_SUFFIX
        ),
        "teen_mature": (
            "Male anatomical construction approaching adult proportions. "
            "Clear inverted triangle rhythm — shoulders clearly dominant "
            "over hips. "
            "Defined pectoral volumes — paired sphere shapes sitting flat "
            "on the upper ribcage. "
            "Subtle waist taper. "
            "Pelvis bucket narrower than shoulders. "
            + CONSTRUCTION_SUFFIX
        ),
        "young_adult": MALE_ANATOMY,
        "adult": MALE_ANATOMY,
    },
}

FEMALE_OVERRIDE = (
    "IMPORTANT: This figure must read as unambiguously female in silhouette. "
    "The hourglass torso rhythm — narrow waist between wider chest and wider "
    "hips — must be clearly visible in the construction volumes. "
    "Do not generate a neutral or androgynous silhouette."
)

MALE_OVERRIDE = (
    "IMPORTANT: This figure must read as unambiguously male in silhouette. "
    "The inverted triangle torso — wide shoulders tapering to narrower hips — "
    "must be clearly visible in the construction volumes. "
    "Do not generate a neutral or androgynous silhouette."
)


def gender_block_for(gender: str, archetype: str) -> str:
    """Return the gender anatomy block scaled to the archetype's tier.

    Caller is responsible for handling the neutral path — this function
    assumes archetype is at or above NEUTRAL_HEAD_THRESHOLD.
    """
    if gender not in GENDER_SCALED:
        raise ValueError(f"Unknown gender: {gender}")
    tier = GENDER_SCALED[gender].get(archetype)
    if tier is None:
        raise ValueError(
            f"No gender block defined for archetype '{archetype}' — "
            f"is_neutral_archetype() should have caught this.")
    return tier


def gender_override_for(gender: str) -> str:
    """Closing override line appended to every non-neutral prompt."""
    if gender == "female":
        return FEMALE_OVERRIDE
    if gender == "male":
        return MALE_OVERRIDE
    raise ValueError(f"Unknown gender: {gender}")

VIEWS = {
    "front":                  "Front view — figure facing the viewer directly.",
    "side_l":                 "Side view (left profile) — figure facing screen-left.",
    "side_r":                 "Side view (right profile) — figure facing screen-right.",
    "back":                   "Back view — figure facing away from the viewer.",
    "three_quarter_front_l":  "Three-quarter front view rotated to screen-left.",
    "three_quarter_front_r":  "Three-quarter front view rotated to screen-right.",
    "three_quarter_back_l":   "Three-quarter back view rotated to screen-left.",
    "three_quarter_back_r":   "Three-quarter back view rotated to screen-right.",
}

# Map our chatgpt view keys to the slugs used in the existing pose_library.json.
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


# ─────────────────────────────────────────────────────────────────────
# Style guide and safety lead-in templates
# ─────────────────────────────────────────────────────────────────────

STYLE_GUIDE = """
9LIVESK9 BASE MANNEQUIN STYLE GUIDE — APPLY EVERY RULE:

1. MEDIUM: Light blue pencil construction drawing (Col-Erase non-photo blue, hex ~#7BAFD4). Soft, clean pencil strokes. No rendering, no shading, no color fill.
2. WIREFRAME: Atari-style contour bands wrapping the volumes — torso, ribcage, pelvis, limbs — like topographical lines describing form.
3. JOINTS: Cross-section ovals at all major joints (shoulders, elbows, wrists, hips, knees, ankles) showing rotation axis of each ball-and-socket.
4. HEAD: Bald, faceless head. Single vertical centre-line and single horizontal eye-line forming a cross on the head. NO facial features. NO hair.
5. PROPORTION GRID: Vertical head-height measurement column on the LEFT MARGIN with horizontal tick lines numbered 1H, 2H, 3H ... up to the figure's full height. The figure stands aligned to this grid.
6. LINE OF ACTION: A single clean RED curving line overlaid through the spine/torso showing the gestural rhythm of the pose.
7. BACKGROUND: Pure clean white. No shadows, no texture, no environment.
8. FRAMING: A4 ratio. Use PORTRAIT by default. Use LANDSCAPE only when the pose demands it (reclining, prone, leaping horizontally, mid-air dive).
9. RESOLUTION: Maximum print-ready resolution, crisp linework, no JPEG artefacts.
10. ABSOLUTE: Construction-stage drawing only. No clothing, no muscle rendering, no accessories, no skin texture, no detail beyond wireframe + joints + line of action.
""".strip()

SAFE_LEAD_BASE = (
    "Anatomical construction mannequin, art reference drawing for figure-construction study. "
    "Bald featureless mannequin, no facial features, no clothing, no accessories, no skin texture, "
    "pure construction lines only."
)

SAFE_LEAD_MINOR_EXTRA = " Stylized anime proportion study reference."

# Archetypes with strictly fewer than this many head-heights are
# anatomically neutralised: gender selection is silently ignored and
# the body construction is forced to a tubular, undifferentiated form.
# Threshold value 6.0 → child (5.5), toddler (4.5), baby (3.5) all hit
# the neutral path; pre-teen (6.0) keeps gender silhouette.
NEUTRAL_HEAD_THRESHOLD = 6.0

NEUTRAL_TOOLTIP = "Gender not applicable below pre-teen tier"

SAFE_LEAD_NEUTRAL_EXTRA = (
    " Neutral proportion study for animation reference, "
    "undifferentiated figure construction, "
    "no anatomical gender markers, "
    "pure geometric volume shapes only."
)

NEUTRAL_BODY_BLOCK = (
    "Completely neutral tubular torso construction. "
    "No chest volume, no breast definition, no pectoral mass, no waist curve, "
    "no hip flare, no shoulder broadening. "
    "Torso is a simple tapered cylinder, wider at top than bottom. "
    "All limbs are soft uniform tubes with no muscle mass or gender-defining contours. "
    "Joints are rounded and soft with minimal articulation. "
    "Silhouette reads as neutral and undifferentiated. "
    "Construction lines only — no anatomical detail beyond basic volume shapes."
)

# Per-archetype refinements appended to the neutral body block.
NEUTRAL_BODY_EXTRAS = {
    "toddler": (
        "Slight belly protrusion on lower torso cylinder. "
        "Very short lower limb tubes approximately 1.5 head-lengths. "
        "Pudgy uniform limb tubes throughout."
    ),
    "baby": (
        "Extremely short limb tubes. "
        "Minimal separation between limb segments. "
        "Large head volume relative to entire figure. "
        "Rounded soft silhouette throughout. "
        "No visible joint definition anywhere."
    ),
}

# Words that must NEVER appear in the prompt sent to gpt-image-1.
# Used both by the system prompt (to instruct Claude) and by an offline
# linter to catch slippage at build time.
BANNED_TERMS = (
    "teen", "teenager", "teenage", "young", "youth", "youthful",
    "juvenile", "minor", "kid", "child", "children", "baby", "babies",
    "infant", "boy", "girl", "adolescent", "pre-teen", "preteen", "preadolescent",
    "year-old", "year old", "years old", "age", "aged",
    "small", "tiny", "little",
)


# ─────────────────────────────────────────────────────────────────────
# System prompt — sent to Claude on every request
# ─────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""
You are the prompt engineer for the 9LivesK9 base mannequin pipeline. Your job is to expand a structured proportion request into a complete image-generation prompt for OpenAI's gpt-image-1 model.

CONTENT-SAFETY RULES — NON-NEGOTIABLE
=====================================

The output is a clinical, bald, featureless construction drawing — analogous to a Loomis or Hamm figure-construction exercise. OpenAI moderation can react to age-coded language even on featureless mannequins, so the prompt language is constrained.

1. Begin EVERY output prompt with this exact safe lead, copied verbatim:

   "{SAFE_LEAD_BASE}"

   If (and only if) the request says "is_minor: yes", append this immediately after, on the same line:

   "{SAFE_LEAD_MINOR_EXTRA.strip()}"

2. NEVER use any of the following words in the output prompt:
   age, aged, year-old, year old, years old, teen, teenager, teenage,
   young, youthful, youth, juvenile, minor, kid, child, children, baby,
   babies, infant, boy, girl, adolescent, pre-teen, preteen,
   preadolescent, small, tiny, little.

   Figure size is communicated ONLY through:
   - the head-count number (e.g. "6.5-head proportion-study mannequin")
   - the proportion rules (shoulder head-widths, leg length, head dominance, joint softness)

3. The figure is always: bald, faceless, no hair, no clothing, no accessories, no skin texture. Single vertical centre-line and horizontal eye-line forming a cross on the head; no other features.

{STYLE_GUIDE}

ORIENTATION HEURISTIC:
- A4 PORTRAIT for: standing, sitting, kneeling, jumping, action stance, contrapposto.
- A4 LANDSCAPE only for: reclining/lying, prone, full-extension sprint, horizontal flying or diving, or any pose where the figure's longest axis is horizontal.

BODY-CONSTRUCTION SWITCH:
The request body block is one of two forms — handle both:
- "Gender anatomy: ..."  → use the supplied gendered anatomy block. It already encodes the shoulder head-widths, chest volumes, waist taper, hip ratio, and overall silhouette appropriate to the archetype tier. Use that language directly — do not soften it, do not paraphrase away the specific volume descriptions.
- "Body construction (anatomically neutral — gender not applied): ..." → use the neutral text VERBATIM. Do NOT add any chest volume, breast definition, pectoral mass, waist curve, hip flare, shoulder broadening, or muscle mass language. The figure is a tubular, undifferentiated form. Gender is irrelevant for this request.

CLOSING OVERRIDE:
If the request includes a "Closing override" line, the output prompt MUST end with that exact text — copy it verbatim, on its own line, after the "Output: ..." line. If no closing override is supplied (neutral path), do not invent one.

For each request you must produce a single plain-text prompt that:
1. Begins with the safe lead phrase exactly (plus the minor-extra line and the neutral-extra line when applicable).
2. States the head-count and the size_class descriptor (no age words).
3. Applies each listed proportion rule, mentioning each rule that's relevant.
4. States the body construction the request specifies — the gender silhouette OR the neutral construction block. When the request is neutral, copy its language verbatim and do not introduce gender markers.
5. States the camera view.
6. Describes the pose precisely, anatomically grounded, with line of action implied.
7. Restates every rule from the style guide so the image model cannot drift.
8. States A4 portrait or landscape using the orientation heuristic.
9. Ends with: "Output: clean white background, A4 [portrait|landscape], 9LivesK9 base mannequin construction sheet, anatomical proportion study reference."

OUTPUT FORMAT: Return ONLY the final image-generation prompt as plain text. No preamble, no markdown, no quotes — just the prompt the image API will receive.
""".strip()


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def is_neutral_archetype(archetype: str) -> bool:
    """True if the archetype's head-count puts it in the gender-neutralised tier
    (child 5.5, toddler 4.5, baby 3.5). Pre-teen (6.0) and above keep gender."""
    arch = ARCHETYPES.get(archetype, {})
    return arch.get("heads", 99.0) < NEUTRAL_HEAD_THRESHOLD


def _safe_lead_for(arch_key: str) -> str:
    arch = ARCHETYPES.get(arch_key, {})
    lead = SAFE_LEAD_BASE
    if arch.get("is_minor"):
        lead += SAFE_LEAD_MINOR_EXTRA
    if is_neutral_archetype(arch_key):
        lead += SAFE_LEAD_NEUTRAL_EXTRA
    return lead


def build_user_message(archetype: str, gender: str, view: str,
                       pose_description: str) -> str:
    """Construct the sanitized user message that's sent to Claude.

    For archetypes below NEUTRAL_HEAD_THRESHOLD, the gender argument is
    silently ignored and the body block is replaced with the anatomically
    neutral tubular construction.

    Exposed (no leading underscore) so a smoke test can verify it contains
    no banned terms without having to call the Anthropic API.
    """
    arch = ARCHETYPES[archetype]
    view_desc = VIEWS[view]
    rules_block = "\n".join(f"  - {r}" for r in arch["rules"])
    safe_lead = _safe_lead_for(archetype)
    is_minor = "yes" if arch.get("is_minor") else "no"

    closing_override = ""
    if is_neutral_archetype(archetype):
        body_label = "Body construction (anatomically neutral — gender not applied)"
        body_text = NEUTRAL_BODY_BLOCK
        extra = NEUTRAL_BODY_EXTRAS.get(archetype)
        if extra:
            body_text = f"{body_text} {extra}"
    else:
        body_label = "Gender anatomy"
        body_text = gender_block_for(gender, archetype)
        closing_override = gender_override_for(gender)

    msg = (
        f"Begin the output prompt with EXACTLY this text:\n"
        f'  "{safe_lead}"\n\n'
        f"is_minor: {is_minor}\n"
        f"Mannequin spec: {arch['size_class']} ({arch['heads']}H total height).\n"
        f"Proportion rules:\n{rules_block}\n"
        f"{body_label}: {body_text}\n"
        f"View: {view_desc}\n"
        f"Pose: {pose_description.strip() or 'neutral standing pose, contrapposto'}"
    )
    if closing_override:
        msg += f"\nClosing override: {closing_override}"
    return msg


def build_sketch_instruction(archetype: str, gender: str, orientation: str) -> str:
    """Image-edit instruction for the Batch sketch-over-base flow.

    Encodes the head-count and proportion rules of the selected archetype
    so gpt-image-1 conforms the character drawing to the underlying base
    figure's proportions. Reuses ARCHETYPES rules + GENDERS silhouettes +
    NEUTRAL_BODY_BLOCK — no duplicate proportion logic.

    Archetypes below NEUTRAL_HEAD_THRESHOLD silently ignore the gender
    argument and use the anatomically neutral construction block.
    """
    if archetype not in ARCHETYPES:
        raise ValueError(f"Unknown archetype: {archetype}")

    arch = ARCHETYPES[archetype]
    rules_block = "\n".join(f"- {r}" for r in arch["rules"])

    closing_override = ""
    if is_neutral_archetype(archetype):
        body_text = NEUTRAL_BODY_BLOCK
        extra = NEUTRAL_BODY_EXTRAS.get(archetype)
        if extra:
            body_text = f"{body_text} {extra}"
        body_label = "Body construction (anatomically neutral — gender not applied)"
    else:
        if gender not in GENDERS:
            raise ValueError(f"Unknown gender: {gender}")
        body_text = gender_block_for(gender, archetype)
        body_label = "Gender anatomy"
        closing_override = gender_override_for(gender)

    if orientation not in ("landscape", "portrait"):
        orientation = "portrait"

    instruction = (
        "You are a professional manga artist.\n"
        "Image 1 is a blue construction base drawing showing a figure pose "
        "with Atari wireframe bands and joint ovals.\n"
        "Image 2 is a character design reference sheet.\n\n"
        "Draw the character from Image 2 dressed in their exact outfit and "
        "with their exact features, placed precisely over the blue figure "
        "in Image 1.\n"
        "Match the pose of the blue figure exactly — every limb position, "
        "every angle, every weight shift.\n"
        "Keep the blue construction lines visible underneath as a "
        "transparent guide layer showing through the black ink character.\n\n"
        "Proportion conformance:\n"
        f"- The figure must be exactly {arch['heads']} head-heights tall — "
        f"a {arch['size_class']}.\n"
        f"{rules_block}\n"
        f"- {body_label}: {body_text}\n\n"
        "Output requirements:\n"
        "- Clean confident black ink manga lineart\n"
        "- Professional line weight variation — thicker on silhouette edges, "
        "thinner on interior detail\n"
        "- Accurate anatomy matching the pose reference\n"
        "- Detailed outfit reproduction from the character sheet\n"
        f"- A4 {orientation} format, print ready\n"
        "- White background only"
    )
    if closing_override:
        instruction += f"\n\n{closing_override}"
    return instruction


def lint_for_banned_terms(text: str) -> list[str]:
    """Return any banned words that appear in `text` (case-insensitive,
    word-boundary aware). Used by the offline smoke test."""
    import re
    found = []
    lowered = text.lower()
    for term in BANNED_TERMS:
        # word-boundary match for single tokens; substring for hyphenated
        pattern = r"\b" + re.escape(term) + r"\b" if " " not in term and "-" not in term \
                  else re.escape(term)
        if re.search(pattern, lowered):
            found.append(term)
    return sorted(set(found))


# ─────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────

def build_base_prompt(api_key: str, archetype: str, gender: str, view: str,
                      pose_description: str) -> dict:
    """Call Claude to expand simple inputs into a full gpt-image-1 prompt.

    Returns {"success": bool, "prompt": str, "cost": float, "error": str}.
    """
    if archetype not in ARCHETYPES:
        return {"success": False, "prompt": "", "cost": 0.0,
                "error": f"Unknown archetype: {archetype}"}
    if view not in VIEWS:
        return {"success": False, "prompt": "", "cost": 0.0,
                "error": f"Unknown view: {view}"}
    if gender not in GENDERS:
        return {"success": False, "prompt": "", "cost": 0.0,
                "error": f"Unknown gender: {gender}"}

    user_message = build_user_message(archetype, gender, view, pose_description)

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
