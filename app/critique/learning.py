"""Promote recurring drifts to a character's `learnedDrifts` sheet field.

Two rules feed `learnedDrifts`:
- Cross-scene recurrence (`promote_recurring_drifts`) — same aspect across
  >=N distinct scenes.
- Consecutive in-scene recurrence (`promote_consecutive_drifts`) — same
  aspect in N back-to-back iterations of one scene. Triggered after each
  auto-regenerate iteration so a stubborn drift inside one regen loop
  bubbles into the sheet for future scenes.
"""

from collections import Counter
from datetime import datetime

from app import sheets as sheets_pkg

from .history import all_iterations_for_character, recent_iterations

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


def promote_consecutive_drifts(
    sheet_id: str,
    scene_id: str,
    threshold: int = DEFAULT_THRESHOLD,
    *,
    source_run_ids: list[str] | None = None,
) -> list[dict]:
    """Promote drifts that recur in the most recent `threshold` consecutive
    iterations of ONE scene.

    Used by the auto-regenerate loop after each iteration: a stubborn drift
    that the regenerator can't fix in `threshold` tries gets bubbled into
    `sheet.learnedDrifts` so future scenes pre-correct for it. Manual
    feedback drifts (origin == "manual") are excluded — those carry
    user-specific guidance, not a recurring model failure.

    Idempotent: an aspect already in `learnedDrifts` is skipped.

    Returns the list of newly-promoted drift records.
    """
    if not sheets_pkg.exists(sheet_id):
        return []
    if threshold < 1:
        return []

    iters = recent_iterations(sheet_id, scene_id, n=threshold)
    if len(iters) < threshold:
        return []

    # Find aspects that appear in EVERY one of the last `threshold` critiques.
    aspect_sets: list[set[str]] = []
    for it in iters:
        aspects: set[str] = set()
        for d in (it.get("critique") or {}).get("drifts", []):
            if d.get("origin") == "manual":
                continue
            aspect = d.get("aspect")
            if aspect:
                aspects.add(aspect)
        aspect_sets.append(aspects)
    if not aspect_sets:
        return []
    consecutive_aspects = set.intersection(*aspect_sets)

    if not consecutive_aspects:
        return []

    sheet = sheets_pkg.load(sheet_id)
    learned_aspects = {ld.get("aspect") for ld in sheet.get("learnedDrifts", [])}

    promoted: list[dict] = []
    now_iso = datetime.now().isoformat()
    for aspect in sorted(consecutive_aspects):
        if aspect in learned_aspects:
            continue
        # Pull the most-recent example of the drift for context.
        example: dict = {}
        for it in reversed(iters):
            for d in (it.get("critique") or {}).get("drifts", []):
                if d.get("aspect") == aspect:
                    example = {
                        "expected": d.get("expected"),
                        "observed": d.get("observed"),
                        "severity": d.get("severity"),
                    }
                    break
            if example:
                break
        promoted.append({
            "aspect": aspect,
            "scene_id": scene_id,
            "consecutive_count": threshold,
            "promotedAt": now_iso,
            "sourceRunIds": list(source_run_ids or []),
            "example": example,
            "origin": "consecutive_in_scene",
        })

    if promoted:
        operations = [{
            "op": "append",
            "path": "learnedDrifts",
            "value": p,
            "reason": (
                f"Auto-promoted (consecutive): drift '{p['aspect']}' "
                f"persisted across {threshold} consecutive iterations of "
                f"scene '{scene_id}'."
            ),
        } for p in promoted]
        updated = sheets_pkg.apply_patch(
            sheet,
            operations,
            summary=(
                f"Auto-learned {len(promoted)} consecutive drift(s) in "
                f"scene '{scene_id}' (threshold={threshold})."
            ),
        )
        sheets_pkg.save(updated)
    return promoted
