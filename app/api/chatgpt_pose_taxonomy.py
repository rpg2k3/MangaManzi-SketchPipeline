"""Pose taxonomy loader for the Chat_GPT base generator tab.

Reads the existing data/pose_library.json (231 entries spanning 41 unique
poses × 6 views) and exposes:
- the canonical list of unique poses (with category + canonical description)
- a helper to look up a pose's description for any view
"""

import json
from pathlib import Path

APP_DIR = Path(__file__).parent.parent.parent
POSE_LIBRARY_PATH = APP_DIR / "data" / "pose_library.json"


def _load_raw() -> list[dict]:
    if not POSE_LIBRARY_PATH.exists():
        return []
    try:
        return json.loads(POSE_LIBRARY_PATH.read_text(encoding="utf-8")).get("poses", [])
    except Exception:
        return []


def list_unique_poses() -> list[dict]:
    """Return one row per unique (pose, category), preserving first-seen order.

    Each row: {"pose": slug, "category": str, "description": str}.
    """
    seen: dict[tuple[str, str], dict] = {}
    for p in _load_raw():
        key = (p.get("pose", ""), p.get("category", ""))
        if not key[0] or key in seen:
            continue
        seen[key] = {
            "pose": key[0],
            "category": key[1],
            "description": p.get("pose_description", "").strip(),
        }
    return list(seen.values())


def list_categories() -> list[str]:
    cats: list[str] = []
    for p in list_unique_poses():
        if p["category"] not in cats:
            cats.append(p["category"])
    return cats


def lookup_description(pose_slug: str, view_library_slug: str) -> str:
    """Return the most specific description for a (pose, view) pair, falling
    back to any view's description if the requested view is missing."""
    raw = _load_raw()
    exact = next(
        (p for p in raw
         if p.get("pose") == pose_slug and p.get("view") == view_library_slug),
        None,
    )
    if exact:
        return exact.get("pose_description", "").strip()
    fallback = next((p for p in raw if p.get("pose") == pose_slug), None)
    return fallback.get("pose_description", "").strip() if fallback else ""
