"""Context-aware regeneration: load last N iterations, compose a corrected prompt.

The user's plan is explicit that the regeneration prompt MUST address each
listed drift — not re-roll the same prompt. We pass `prior_critiques`
through to the existing `app.claude.prompts.generate_prompt`, which is
already wired to honor them.
"""

from app.claude.prompts import generate_prompt

from .history import recent_iterations


def compose_corrected_prompt(
    *,
    api_key: str,
    sheet: dict,
    scene_description: str,
    scene_id: str,
    view: str = "front",
    pose: str | None = None,
    n_history: int = 3,
    manual_feedback: str | None = None,
) -> dict:
    """Read the last N iterations from history and ask Claude for a corrected prompt."""
    iters = recent_iterations(sheet.get("id", ""), scene_id, n=n_history)

    prior_critiques = []
    for it in iters:
        crit = it.get("critique") or {}
        prior_critiques.append({
            "iteration_index": it.get("iteration_index"),
            "drifts": crit.get("drifts", []),
            "successes": crit.get("successes", []),
            "suggestedPromptDeltas": crit.get("suggestedPromptDeltas", []),
            "manual_feedback": it.get("manual_feedback"),
        })

    if manual_feedback and manual_feedback.strip():
        prior_critiques.append({
            "iteration_index": "incoming",
            "drifts": [{
                "aspect": "manual_feedback",
                "expected": "(user-provided)",
                "observed": manual_feedback.strip(),
                "severity": "major",
                "origin": "manual",
            }],
            "successes": [],
            "suggestedPromptDeltas": [f"Manual: {manual_feedback.strip()}"],
            "manual_feedback": manual_feedback.strip(),
        })

    return generate_prompt(
        api_key=api_key,
        archetype={"code": sheet.get("archetype"), "head_count": sheet.get("head_count")},
        view=view,
        pose=pose,
        stage=3,
        sheet=sheet,
        prior_critiques=prior_critiques,
        scene_description=scene_description,
        lora_triggers=[sheet.get("triggerWords")] if sheet.get("triggerWords") else None,
        pose_id=pose or "",
    )
