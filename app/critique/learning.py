"""Promote recurring drifts to a character's `learnedDrifts` sheet field.

Rule (from Phase 6.5 spec): when the SAME drift `aspect` appears 3+ times
across different scenes for one character, bubble it into the sheet so
future generations pre-correct for it.
"""

from collections import Counter
from datetime import datetime

from app import sheets as sheets_pkg

from .history import all_iterations_for_character

DEFAULT_THRESHOLD = 3


def count_drift_recurrences(sheet_id: str) -> dict[str, int]:
    """Count distinct-scene appearances of each drift aspect for one character."""
    iters = all_iterations_for_character(sheet_id)
    seen: dict[str, set[str]] = {}
    for it in iters:
        scene = it.get("scene_id", "")
        for d in (it.get("critique") or {}).get("drifts", []):
            aspect = d.get("aspect")
            if not aspect:
                continue
            if d.get("origin") == "manual":
                continue
            seen.setdefault(aspect, set()).add(scene)
    return {a: len(scenes) for a, scenes in seen.items()}


def promote_recurring_drifts(sheet_id: str, threshold: int = DEFAULT_THRESHOLD) -> list[dict]:
    """Promote drifts seen ≥ threshold scenes into sheet.learnedDrifts.

    Returns the list of newly-promoted drift records (could be empty if none
    are above threshold or if all already learned).
    """
    if not sheets_pkg.exists(sheet_id):
        return []
    sheet = sheets_pkg.load(sheet_id)
    learned_aspects = {ld.get("aspect") for ld in sheet.get("learnedDrifts", [])}

    counts = count_drift_recurrences(sheet_id)
    iters = all_iterations_for_character(sheet_id)

    promoted: list[dict] = []
    for aspect, count in counts.items():
        if count < threshold or aspect in learned_aspects:
            continue
        examples = []
        for it in iters:
            for d in (it.get("critique") or {}).get("drifts", []):
                if d.get("aspect") == aspect:
                    examples.append({
                        "scene_id": it.get("scene_id"),
                        "expected": d.get("expected"),
                        "observed": d.get("observed"),
                        "severity": d.get("severity"),
                    })
        promoted.append({
            "aspect": aspect,
            "scene_count": count,
            "first_seen": iters[0].get("ts") if iters else "",
            "promoted_at": datetime.now().isoformat(),
            "examples": examples[:5],
        })

    if promoted:
        operations = [{
            "op": "append",
            "path": "learnedDrifts",
            "value": p,
            "reason": f"Auto-promoted: drift '{p['aspect']}' seen in {p['scene_count']} scenes (≥ {threshold}).",
        } for p in promoted]
        updated = sheets_pkg.apply_patch(
            sheet,
            operations,
            summary=f"Auto-learned {len(promoted)} drift(s) at recurrence threshold {threshold}.",
        )
        sheets_pkg.save(updated)
    return promoted
