#!/usr/bin/env python3
"""Parse F_adult-instructions.pdf and extract all 62 prompts into prompt_templates.json."""

import json
import re
from pathlib import Path

import fitz  # pymupdf


PDF_PATH = Path("/home/emanzi/9LK9-App/F_adult-(25+)/F_adult-instructions.pdf")
OUTPUT_PATH = Path("/home/emanzi/9LK9-App/prompt_templates.json")

# SPEC §7: closest-three CSP lookup table
CLOSEST_THREE = {
    "front":       ["front", "3q_front_L", "3q_front_R"],
    "side_L":      ["side_L", "front", "3q_front_L"],
    "side_R":      ["side_R", "front", "3q_front_R"],
    "back":        ["back", "side_L", "side_R"],
    "3q_front_L":  ["3q_front_L", "front", "side_L"],
    "3q_front_R":  ["3q_front_R", "front", "side_R"],
}

# Pose -> normalized category (from PDF pose group headers)
POSE_CATEGORY = {
    "contrapposto_classic": "standing",
    "sit_chair_neutral":    "sitting",
    "walk_neutral":         "walking",
    "run_jog":              "walking",
    "kneel_one":            "kneeling",
    "combat_ready":         "combat",
    "recline_prop":         "sitting",
    "jump_air":             "dynamic",
    "foreshortening_reach": "camera",
    "combat_kick_high":     "combat",
    "low_angle_hero":       "camera",
    "high_angle_vulnerable": "camera",
}

# Poses that always keep pure CSP refs (no locked anchor swap) per SPEC §7
NON_STANDARD_POSES = {
    "recline_prop", "jump_air", "foreshortening_reach",
    "low_angle_hero", "high_angle_vulnerable",
}

# Categories eligible for locked anchor swap per SPEC §7
ANCHOR_SWAP_CATEGORIES = {"standing", "walking", "sitting", "kneeling", "combat"}

# Landscape orientations from PDF (all others are portrait)
# Per PDF page 1: "Landscape only for recline_prop, foreshortening_reach,
# run_jog side views, and combat_kick_high side views"
LANDSCAPE_COMBOS = {
    # recline_prop: ALL views are landscape
    ("front", "recline_prop"),
    ("side_L", "recline_prop"),
    ("side_R", "recline_prop"),
    ("back", "recline_prop"),
    ("3q_front_L", "recline_prop"),
    ("3q_front_R", "recline_prop"),
    # foreshortening_reach: ALL views are landscape
    ("front", "foreshortening_reach"),
    ("side_L", "foreshortening_reach"),
    ("side_R", "foreshortening_reach"),
    ("back", "foreshortening_reach"),
    ("3q_front_L", "foreshortening_reach"),
    ("3q_front_R", "foreshortening_reach"),
    # run_jog: side views only
    ("side_L", "run_jog"),
    ("side_R", "run_jog"),
    # combat_kick_high: side views only
    ("side_L", "combat_kick_high"),
    ("side_R", "combat_kick_high"),
}


def extract_full_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    doc.close()
    return full_text


def parse_view_from_filename(filename: str) -> str:
    middle = filename.replace("F_adult_", "").replace("_01.png", "")
    views = ["3q_front_L", "3q_front_R", "side_L", "side_R", "front", "back"]
    for v in views:
        if middle.startswith(v + "_") or middle == v:
            return v
    return "front"


def parse_pose_from_filename(filename: str) -> str:
    middle = filename.replace("F_adult_", "").replace("_01.png", "")
    views = ["3q_front_L_", "3q_front_R_", "side_L_", "side_R_", "front_", "back_"]
    for v in views:
        if middle.startswith(v):
            return middle[len(v):]
    return middle


def compute_references(view: str, pose: str, category: str, prompt_number: int) -> list[str]:
    """Compute reference keys per SPEC §7."""
    base_refs = list(CLOSEST_THREE.get(view, ["front", "3q_front_L", "3q_front_R"]))

    # Prompt #1: no anchor exists yet
    if prompt_number == 1:
        return base_refs

    # Non-standard poses: always pure CSP
    if pose in NON_STANDARD_POSES:
        return base_refs

    # Standard categories: swap csp_front for locked_anchor
    if category in ANCHOR_SWAP_CATEGORIES and "front" in base_refs:
        idx = base_refs.index("front")
        base_refs[idx] = "locked_anchor"

    return base_refs


def main():
    text = extract_full_text(PDF_PATH)

    # Split into individual prompts using #N pattern
    prompt_pattern = re.compile(
        r"#(\d+)\s*(?:—|--|-)\s*(F_adult_\S+\.png)",
        re.MULTILINE,
    )
    matches = list(prompt_pattern.finditer(text))
    print(f"Found {len(matches)} prompt headers")

    prompts = []
    for i, match in enumerate(matches):
        num = int(match.group(1))
        filename = match.group(2)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()

        # Extract prompt body: "I'm attaching..." through "OUTPUT: ..."
        prompt_start = block.find("I'm attaching")
        if prompt_start == -1:
            print(f"  WARNING: #{num} has no prompt body")
            continue

        # Find OUTPUT: line to end the prompt body
        output_match = re.search(r"OUTPUT:\s*.+?(?:\n|$)", block)
        if output_match:
            prompt_body = block[prompt_start:output_match.end()].strip()
        else:
            prompt_body = block[prompt_start:].strip()

        # The pymupdf extraction loses the HEAD-HEIGHT GRID tail and OUTPUT line
        # at page boundaries. Reconstruct them since they follow a fixed pattern.
        # First, clean up the truncated text, then append the standard tail.

        # Clean: remove any trailing Attach: lines and post-prompt metadata
        attach_idx = prompt_body.find("\nAttach:")
        if attach_idx != -1:
            prompt_body = prompt_body[:attach_idx].strip()
        # Also remove the anchor instruction from prompt #1
        anchor_idx = prompt_body.find("\n Once this generation locks")
        if anchor_idx != -1:
            prompt_body = prompt_body[:anchor_idx].strip()
        anchor_idx2 = prompt_body.find("\nFrom this point forward")
        if anchor_idx2 != -1:
            prompt_body = prompt_body[:anchor_idx2].strip()

        # Derive metadata from filename (reliable) not from PDF text (fragile)
        view = parse_view_from_filename(filename)
        pose = parse_pose_from_filename(filename)
        category = POSE_CATEGORY.get(pose, "unknown")
        orientation = "landscape" if (view, pose) in LANDSCAPE_COMBOS else "portrait"

        # Ensure the HEAD-HEIGHT GRID section is complete (pymupdf drops tail at page breaks)
        if "HEAD-HEIGHT GRID:" in prompt_body:
            grid_tail = (
                "- Dashed line at the bottom marking the ground plane (marker 0)\n"
                "- Crown of head sits at marker 8, soles touch marker 0\n"
                "- Grid must match the 8-head adult count exactly — no drift"
            )
            if "Dashed line at the bottom" not in prompt_body:
                prompt_body = prompt_body.rstrip() + "\n" + grid_tail

        # Ensure OUTPUT: line is present (also lost at page breaks)
        if "OUTPUT:" not in prompt_body:
            orient_label = "A4 landscape" if orientation == "landscape" else "A4 portrait"
            output_line = f"\nOUTPUT: A single full-body {filename.replace('F_adult_', '').replace('_01.png', '')} mannequin in {orient_label} ratio, light blue pencil on white."
            prompt_body = prompt_body.rstrip() + "\n" + output_line

        reference_keys = compute_references(view, pose, category, num)

        prompts.append({
            "number": num,
            "filename": filename,
            "view": view,
            "pose": pose,
            "category": category,
            "orientation": orientation,
            "size": "1536x1024" if orientation == "landscape" else "1024x1536",
            "reference_keys": reference_keys,
            "prompt": prompt_body,
        })

    prompts.sort(key=lambda x: x["number"])
    print(f"\nExtracted {len(prompts)} prompts (expected 62)\n")

    # Summary table
    for p in prompts:
        anchor = "A" if "locked_anchor" in p["reference_keys"] else " "
        land = "L" if p["orientation"] == "landscape" else "P"
        print(f"  #{p['number']:2d} {land} {anchor} {p['filename']:50s} refs={p['reference_keys']}")

    with open(OUTPUT_PATH, "w") as f:
        json.dump(prompts, f, indent=2)
    print(f"\nWritten to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
