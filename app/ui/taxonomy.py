"""9LivesK9 archetype + view + pose taxonomy used by the UI dropdowns
and the Stage 1 prompt assembler.
"""

import json
from pathlib import Path

ARCHETYPES = [
    ("F_adult",   "Female Adult (25+)",       8.0),
    ("M_adult",   "Male Adult (25+)",         8.0),
    ("F_yadult",  "Female Young Adult (18+)", 7.5),
    ("M_yadult",  "Male Young Adult (18+)",   7.5),
    ("F_teenM",   "Female Teen Mature (16+)", 7.0),
    ("M_teenM",   "Male Teen Mature (16+)",   7.0),
    ("F_teenY",   "Female Teen Young (14+)",  6.5),
    ("M_teenY",   "Male Teen Young (14+)",    6.5),
    ("F_preteen", "Female Pre-Teen (12+)",    6.0),
    ("M_preteen", "Male Pre-Teen (12+)",      6.0),
    ("child",     "Child (8–11)",             5.5),
    ("toddler",   "Toddler (2–4)",            4.5),
    ("baby",      "Baby (0–1)",               3.5),
]

VIEWS = ["front", "side_L", "side_R", "back", "3q_front_L", "3q_front_R"]

# Subject anchors are independent of the LoRA registry — they tell SD WHO is
# being drawn so it doesn't drift to architectural blueprints when the prompt
# is otherwise dominated by style + construction tokens.
SUBJECT_ANCHORS = {
    "F_adult":   "1girl, solo, full_body",
    "F_yadult":  "1girl, solo, full_body",
    "F_teenM":   "1girl, solo, full_body",
    "F_teenY":   "1girl, solo, full_body",
    "F_preteen": "1girl, solo, full_body",
    "M_adult":   "1boy, solo, full_body",
    "M_yadult":  "1boy, solo, full_body",
    "M_teenM":   "1boy, solo, full_body",
    "M_teenY":   "1boy, solo, full_body",
    "M_preteen": "1boy, solo, full_body",
    "child":     "1child, solo, full_body",
    "toddler":   "1child, solo, full_body",
    "baby":      "1child, solo, full_body",
}

# P18: simplified. The previous verbose anatomy spec was diluting LoRA
# attention. The LoRA already knows adult proportions — we only inject
# head/limb hints for archetypes that are conceptually different (toddler,
# baby). Male archetypes get "broader shoulders" so the LoRA doesn't default
# to its more common feminine silhouette.
ARCHETYPE_CORE = {
    "F_adult":   "female adult",
    "F_yadult":  "female young adult",
    "F_teenM":   "female teen",
    "F_teenY":   "female young teen",
    "F_preteen": "female pre-teen",
    "M_adult":   "male adult, broader shoulders",
    "M_yadult":  "male young adult, broader shoulders",
    "M_teenM":   "male teen",
    "M_teenY":   "male young teen",
    "M_preteen": "male pre-teen",
    "child":     "child",
    "toddler":   "toddler, big head, short limbs",
    "baby":      "baby, very large head, short limbs",
}

# Short pose tags. Listed entries match the user's spec; unknown poses fall
# back to a slug-with-spaces. Verbose pose-library descriptions are gone —
# they bloated the prompt without helping the LoRA.
POSE_CORE = {
    "contrapposto_relaxed": "contrapposto",
    "contrapposto_classic": "contrapposto, hand on hip",
    "power_stance":         "power stance, feet apart",
    "idle_casual":          "casual standing pose",
    "walk_neutral":         "walking pose, mid-stride",
    "combat_ready":         "fighting stance",
}

VIEW_DESCRIPTIONS = {
    "front":      "front view",
    "back":       "back view",
    "side_L":     "left-side profile view",
    "side_R":     "right-side profile view",
    "3q_front_L": "three-quarter front view from the left",
    "3q_front_R": "three-quarter front view from the right",
}

_POSE_LIBRARY = Path(__file__).resolve().parent.parent.parent / "data" / "pose_library.json"


def archetype_label(code: str) -> str:
    for c, label, _ in ARCHETYPES:
        if c == code:
            return label
    return code


def archetype_head_count(code: str) -> float:
    for c, _, hc in ARCHETYPES:
        if c == code:
            return hc
    return 8.0


def subject_anchor(archetype: str) -> str:
    return SUBJECT_ANCHORS.get(archetype, "1person, solo, full body figure")


def archetype_core(archetype: str) -> str:
    return ARCHETYPE_CORE.get(archetype, "")


def view_description(view: str) -> str:
    return VIEW_DESCRIPTIONS.get(view, view.replace("_", " "))


def _load_pose_library() -> list:
    if not _POSE_LIBRARY.exists():
        return []
    try:
        data = json.loads(_POSE_LIBRARY.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict) and isinstance(data.get("poses"), list):
        return data["poses"]
    if isinstance(data, list):
        return data
    return []


def list_poses() -> list[str]:
    """Distinct pose names from data/pose_library.json. Fallback to a built-in set."""
    poses = set()
    for entry in _load_pose_library():
        if isinstance(entry, dict) and entry.get("pose"):
            poses.add(entry["pose"])
    return sorted(poses) if poses else _DEFAULT_POSES


def pose_core(pose: str) -> str:
    """Short pose tag. Hardcoded for the curated set; everything else
    falls back to a slug-with-spaces so the model gets *something* to read.
    The verbose pose-library descriptions are intentionally not used here —
    they bloated the prompt without helping the LoRA.
    """
    if pose in POSE_CORE:
        return POSE_CORE[pose]
    return pose.replace("_", " ")


_DEFAULT_POSES = [
    "contrapposto_classic",
    "combat_ready",
    "walking",
    "running",
    "sitting",
    "kneeling",
]
