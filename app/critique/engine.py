"""Critique engine.

Wraps app.claude.critique.critique_image and merges manual user feedback
as a top-priority drift entry (origin: "manual"). Auto-detected drifts
keep origin "auto".
"""

from pathlib import Path

from app.claude.critique import critique_image


def run_critique(
    *,
    image_path: Path,
    sheet: dict,
    scene_description: str,
    anthropic_api_key: str,
    manual_feedback: str | None = None,
) -> dict:
    expected = {
        "archetype": {"code": sheet.get("archetype"), "head_count": sheet.get("head_count")},
        "sheet": sheet,
        "scene": scene_description,
    }
    auto = critique_image(
        api_key=anthropic_api_key,
        image_path=image_path,
        expected=expected,
        character_id=sheet.get("id", ""),
    )

    for d in auto.get("drifts", []):
        d.setdefault("origin", "auto")

    if manual_feedback and manual_feedback.strip():
        manual_entry = {
            "aspect": "manual_feedback",
            "expected": "(user-provided)",
            "observed": manual_feedback.strip(),
            "severity": "major",
            "origin": "manual",
        }
        auto.setdefault("drifts", []).insert(0, manual_entry)
        deltas = auto.setdefault("suggestedPromptDeltas", [])
        deltas.insert(0, f"Manual: {manual_feedback.strip()}")

    return auto
