"""Critique engine.

Wraps app.claude.critique.critique_image and merges manual user feedback
as a top-priority drift entry (origin: "manual"). Auto-detected drifts
keep origin "auto".

When the sheet carries `referenceAnchors`, the first anchor's path is
forwarded to the critique call so Claude can compare the generated image
against the canonical design and fill the structured `outfit_consistency`
field.
"""

from pathlib import Path

from app.claude.critique import critique_image

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_reference_path(sheet: dict) -> Path | None:
    """First anchor wins. Path is sheet-relative; resolved against repo root.
    Returns None if no anchor is set, the path is empty, or the file does
    not exist on disk."""
    anchors = sheet.get("referenceAnchors") or []
    if not anchors:
        return None
    first = anchors[0]
    raw = (first.get("path") if isinstance(first, dict) else None) or ""
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p if p.exists() else None


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
    reference_path = _resolve_reference_path(sheet)
    auto = critique_image(
        api_key=anthropic_api_key,
        image_path=image_path,
        expected=expected,
        reference_image_path=reference_path,
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
