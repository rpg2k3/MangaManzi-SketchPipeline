#!/usr/bin/env python3
"""Extract all 62 F_adult prompts from the PDF using reading-order text extraction.

Produces prompts/mannequin_library/F_adult_prompts.json with the full verbatim
prompt text for each pose — no paraphrasing, no condensing.
"""

import json
import re
from pathlib import Path

import fitz

PDF_PATH = Path("F_adult-(25+)/F_adult-instructions.pdf")
OUTPUT_PATH = Path("prompts/mannequin_library/F_adult_prompts.json")

# From parse_prompts.py — known metadata
POSE_CATEGORY = {
    "contrapposto_classic": "standing",
    "sit_chair_neutral": "sitting",
    "walk_neutral": "walking",
    "run_jog": "walking",
    "kneel_one": "kneeling",
    "combat_ready": "combat",
    "recline_prop": "sitting",
    "jump_air": "dynamic",
    "foreshortening_reach": "camera",
    "combat_kick_high": "combat",
    "low_angle_hero": "camera",
    "high_angle_vulnerable": "camera",
}

LANDSCAPE_COMBOS = {
    ("front", "recline_prop"), ("side_L", "recline_prop"), ("side_R", "recline_prop"),
    ("back", "recline_prop"), ("3q_front_L", "recline_prop"), ("3q_front_R", "recline_prop"),
    ("front", "foreshortening_reach"), ("side_L", "foreshortening_reach"),
    ("side_R", "foreshortening_reach"), ("back", "foreshortening_reach"),
    ("3q_front_L", "foreshortening_reach"), ("3q_front_R", "foreshortening_reach"),
    ("side_L", "run_jog"), ("side_R", "run_jog"),
    ("side_L", "combat_kick_high"), ("side_R", "combat_kick_high"),
}

CLOSEST_THREE = {
    "front": ["front", "3q_front_L", "3q_front_R"],
    "side_L": ["side_L", "front", "3q_front_L"],
    "side_R": ["side_R", "front", "3q_front_R"],
    "back": ["back", "side_L", "side_R"],
    "3q_front_L": ["3q_front_L", "front", "side_L"],
    "3q_front_R": ["3q_front_R", "front", "side_R"],
}

NON_STANDARD_POSES = {
    "recline_prop", "jump_air", "foreshortening_reach",
    "low_angle_hero", "high_angle_vulnerable",
}
ANCHOR_SWAP_CATEGORIES = {"standing", "walking", "sitting", "kneeling", "combat"}


def extract_text_reading_order(pdf_path):
    doc = fitz.open(str(pdf_path))
    all_text = ""
    for page in doc:
        blocks = page.get_text("dict", sort=True)
        for block in blocks["blocks"]:
            if block["type"] == 0:
                for line in block["lines"]:
                    for span in line["spans"]:
                        all_text += span["text"]
                    all_text += "\n"
                all_text += "\n"
    doc.close()
    return all_text


def parse_view(filename):
    middle = filename.replace("F_adult_", "").replace("_01.png", "")
    for v in ["3q_front_L", "3q_front_R", "side_L", "side_R", "front", "back"]:
        if middle.startswith(v + "_") or middle == v:
            return v
    return "front"


def parse_pose(filename):
    middle = filename.replace("F_adult_", "").replace("_01.png", "")
    for v in ["3q_front_L_", "3q_front_R_", "side_L_", "side_R_", "front_", "back_"]:
        if middle.startswith(v):
            return middle[len(v):]
    return middle


def compute_references(view, pose, category, prompt_number):
    base = list(CLOSEST_THREE.get(view, ["front", "3q_front_L", "3q_front_R"]))
    if prompt_number == 1:
        return base
    if pose in NON_STANDARD_POSES:
        return base
    if category in ANCHOR_SWAP_CATEGORIES and "front" in base:
        idx = base.index("front")
        base[idx] = "locked_anchor"
    return base


def main():
    text = extract_text_reading_order(PDF_PATH)

    # Find all prompt headers
    header_re = re.compile(r"#(\d+)\s*(?:—|–|-)\s*(F_adult_\S+\.png)")
    matches = list(header_re.finditer(text))
    print(f"Found {len(matches)} prompt headers")

    prompts = []
    for i, match in enumerate(matches):
        num = int(match.group(1))
        filename = match.group(2)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]

        # Extract prompt body: "I'm attaching" through "OUTPUT: ..."
        prompt_start = block.find("I'm attaching")
        if prompt_start == -1:
            print(f"  WARNING: #{num} missing 'I'm attaching'")
            continue

        # Find the OUTPUT: line (last occurrence before Attach:)
        attach_pos = block.find("Attach:")
        if attach_pos == -1:
            attach_pos = len(block)

        # Find OUTPUT: before Attach:
        search_region = block[prompt_start:attach_pos]
        output_match = None
        for m in re.finditer(r"OUTPUT:.*", search_region):
            output_match = m

        if output_match:
            prompt_body = search_region[:output_match.end()].strip()
        else:
            prompt_body = search_region.strip()
            print(f"  WARNING: #{num} missing OUTPUT: line")

        # Clean trailing whitespace/noise
        # Remove any "Attach:" lines that bled in
        for cut in ["\nAttach:", "\n Once this generation locks", "\nFrom this point forward"]:
            idx = prompt_body.find(cut)
            if idx != -1:
                prompt_body = prompt_body[:idx].strip()

        # Derive metadata
        view = parse_view(filename)
        pose = parse_pose(filename)
        category = POSE_CATEGORY.get(pose, "unknown")
        orientation = "landscape" if (view, pose) in LANDSCAPE_COMBOS else "portrait"
        refs = compute_references(view, pose, category, num)

        prompts.append({
            "number": num,
            "filename": filename,
            "view": view,
            "pose": pose,
            "category": category,
            "orientation": orientation,
            "size": "1536x1024" if orientation == "landscape" else "1024x1536",
            "reference_keys": refs,
            "prompt": prompt_body,
        })

    prompts.sort(key=lambda x: x["number"])
    print(f"\nExtracted {len(prompts)} prompts")

    # Validate completeness
    complete = 0
    broken = 0
    for p in prompts:
        checks = {
            "LOCKED STYLE": "LOCKED STYLE" in p["prompt"],
            "ANATOMY": "ANATOMY" in p["prompt"],
            "POSE RHYTHM": "POSE RHYTHM" in p["prompt"],
            "LINE OF ACTION": "LINE OF ACTION" in p["prompt"],
            "HEAD-HEIGHT GRID": "HEAD-HEIGHT GRID" in p["prompt"],
            "OUTPUT:": "OUTPUT:" in p["prompt"],
        }
        missing = [k for k, v in checks.items() if not v]
        if missing:
            print(f"  #{p['number']:2d} {p['filename']:50s} {len(p['prompt']):5d} chars  MISSING: {', '.join(missing)}")
            broken += 1
        else:
            complete += 1

    print(f"\nComplete: {complete}/62, Broken: {broken}/62")

    # Save
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(prompts, indent=2, ensure_ascii=False))
    print(f"\nSaved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
