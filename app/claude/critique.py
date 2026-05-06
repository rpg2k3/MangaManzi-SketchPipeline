"""Claude-driven image critique.

Returns the structured critique format:
  {drifts: [{aspect, expected, observed, severity}],
   successes: [...],
   suggestedPromptDeltas: [...],
   outfit_consistency: {...}   # only when a reference image is supplied}
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
changes.

OUTFIT CONSISTENCY CHECK (only when a reference image is provided as
"Image 1: canonical reference" alongside the generated image as
"Image 2: generated output"):
You MUST fill the `outfit_consistency` field. For each sub-field, set
`matches_reference` based on what the canonical reference shows. Flag any
ADDED elements that appear on the generated output but NOT on the
reference (extra straps, garters, belts, jewelry, cutouts, etc.) in
`added_elements_not_on_reference`. The downstream regenerator uses these
fields to surface concrete prompt deltas, so be specific."""

_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


_OUTFIT_CONSISTENCY_SCHEMA = {
    "type": "object",
    "properties": {
        "boot_silhouette": {
            "type": "object",
            "properties": {
                "height": {"type": "string", "enum": ["ankle", "mid_calf", "knee_high", "thigh_high", "not_present", "other"]},
                "sole": {"type": "string", "enum": ["flat", "moderate_platform", "heavy_lug", "heel", "not_present", "other"]},
                "closure": {"type": "string", "enum": ["lace_up", "zip", "buckle", "slip_on", "not_present", "other"]},
                "matches_reference": {"type": "boolean"},
            },
            "required": ["height", "sole", "closure", "matches_reference"],
        },
        "hosiery": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["none", "sheer", "fishnet_light", "fishnet_dense", "opaque", "other"]},
                "matches_reference": {"type": "boolean"},
            },
            "required": ["type", "matches_reference"],
        },
        "belt": {
            "type": "object",
            "properties": {
                "chain_present": {"type": "boolean"},
                "charm_shape": {"type": "string"},
                "charm_position": {"type": "string", "enum": ["side_left", "side_right", "center", "absent"]},
                "matches_reference": {"type": "boolean"},
            },
            "required": ["chain_present", "charm_shape", "charm_position", "matches_reference"],
        },
        "skirt": {
            "type": "object",
            "properties": {
                "cut": {"type": "string", "enum": ["a_line", "pencil", "pleated", "wrap", "circle", "not_present", "other"]},
                "length": {"type": "string", "enum": ["micro", "mini", "midi", "knee", "long", "not_present"]},
                "matches_reference": {"type": "boolean"},
            },
            "required": ["cut", "length", "matches_reference"],
        },
        "arm_coverage": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["bare", "sleeves", "gloves", "fishnet", "mixed"]},
                "matches_reference": {"type": "boolean"},
            },
            "required": ["type", "matches_reference"],
        },
        "added_elements_not_on_reference": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Elements present on the generated image that do NOT appear on the canonical reference (extra straps, garters, jewelry, cutouts, accessories, etc.).",
        },
    },
    "required": [
        "boot_silhouette",
        "hosiery",
        "belt",
        "skirt",
        "arm_coverage",
        "added_elements_not_on_reference",
    ],
}


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
        "outfit_consistency": _OUTFIT_CONSISTENCY_SCHEMA,
    },
    # outfit_consistency is required only when a reference image is supplied
    # — the schema's `required` list is rewritten dynamically per call.
    "required": ["drifts", "successes", "suggestedPromptDeltas"],
}


def critique_image(
    api_key: str,
    image_path: Path,
    expected: dict,
    *,
    reference_image_path: Path | None = None,
    character_id: str = "",
    pose_id: str = "",
) -> dict:
    """Claude-vision critique of a generated image against an expectation
    dict. When `reference_image_path` is supplied, Claude also receives the
    canonical reference image and the response includes the structured
    `outfit_consistency` field — required for that path.
    """
    image_path = Path(image_path)
    gen_media_type = _MEDIA_TYPES.get(image_path.suffix.lower(), "image/png")

    user_content: list = []
    if reference_image_path is not None:
        ref_path = Path(reference_image_path)
        if ref_path.exists():
            ref_media_type = _MEDIA_TYPES.get(ref_path.suffix.lower(), "image/png")
            user_content.append(
                {"type": "text",
                 "text": "Image 1 — canonical reference (the design we want to match):"}
            )
            user_content.append(
                encode_image_block(ref_path.read_bytes(), media_type=ref_media_type)
            )
            user_content.append(
                {"type": "text",
                 "text": "Image 2 — generated output to critique:"}
            )

    user_content.append(encode_image_block(image_path.read_bytes(), media_type=gen_media_type))
    user_content.append({
        "type": "text",
        "text": (
            "EXPECTATION:\n```json\n"
            + json.dumps(expected, indent=2)
            + "\n```\n\nReturn a structured critique via the tool."
        ),
    })

    schema = json.loads(json.dumps(_TOOL_SCHEMA))  # deep copy so we don't mutate the module-level template
    if reference_image_path is not None and Path(reference_image_path).exists():
        # outfit_consistency is required only when the reference is present
        # (Claude can't fill it without seeing the canonical design).
        schema["required"] = list(schema["required"]) + ["outfit_consistency"]

    return call_with_tool(
        api_key,
        model=MODEL_OPUS,
        system=_SYSTEM,
        user_content=user_content,
        tool_name="report_critique",
        tool_description="Emit a structured critique of the supplied image.",
        tool_input_schema=schema,
        operation="critique_image",
        max_tokens=2500,
        character_id=character_id,
        pose_id=pose_id,
    )
