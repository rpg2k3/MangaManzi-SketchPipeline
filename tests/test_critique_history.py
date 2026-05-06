"""Critique history append + recent + drift learning tests."""

import pytest

from app import critique, sheets


def test_append_and_recent_iterations(tmp_data_root, sample_sheet):
    sheets.save(sample_sheet)
    sid = sample_sheet["id"]
    for i in range(5):
        critique.append_iteration(
            sid, "scene_a",
            prompt={"prompts": f"v{i}"},
            critique={"drifts": [], "successes": [], "suggestedPromptDeltas": []},
            output_path=f"/tmp/v{i}.png",
        )
    recent = critique.recent_iterations(sid, "scene_a", n=3)
    assert len(recent) == 3
    assert [r["iteration_index"] for r in recent] == [2, 3, 4]


def test_count_drift_recurrences_distinct_scenes(tmp_data_root, sample_sheet):
    sheets.save(sample_sheet)
    sid = sample_sheet["id"]
    drift = {"aspect": "head_proportion", "expected": "7.5", "observed": "7.0", "severity": "moderate"}
    # head_proportion appears in 3 scenes — should pass threshold
    for scene in ("scene_a", "scene_b", "scene_c"):
        critique.append_iteration(
            sid, scene,
            prompt={"prompts": "p"},
            critique={"drifts": [drift], "successes": [], "suggestedPromptDeltas": []},
            output_path="/tmp/x.png",
        )
    # eye_color appears only in scene_a — below threshold
    critique.append_iteration(
        sid, "scene_a",
        prompt={"prompts": "p"},
        critique={"drifts": [{"aspect": "eye_color", "expected": "green", "observed": "blue", "severity": "minor"}],
                  "successes": [], "suggestedPromptDeltas": []},
        output_path="/tmp/x.png",
    )
    counts = critique.count_drift_recurrences(sid)
    assert counts["head_proportion"] == 3
    assert counts.get("eye_color", 0) == 1


def test_promote_recurring_drifts_writes_to_sheet(tmp_data_root, sample_sheet):
    sheets.save(sample_sheet)
    sid = sample_sheet["id"]
    drift = {"aspect": "shoulder_width", "expected": "1.7 heads",
             "observed": "1.5 heads", "severity": "moderate"}
    for scene in ("a", "b", "c", "d"):
        critique.append_iteration(
            sid, scene,
            prompt={"prompts": "p"},
            critique={"drifts": [drift], "successes": [], "suggestedPromptDeltas": []},
            output_path="/tmp/x.png",
        )
    promoted = critique.promote_recurring_drifts(sid, threshold=3)
    assert len(promoted) == 1
    assert promoted[0]["aspect"] == "shoulder_width"
    assert promoted[0]["scene_count"] == 4
    # Sheet was actually updated
    fresh = sheets.load(sid)
    assert any(ld["aspect"] == "shoulder_width" for ld in fresh["learnedDrifts"])
    # Idempotent: a second call doesn't re-promote
    promoted_again = critique.promote_recurring_drifts(sid, threshold=3)
    assert promoted_again == []


def test_manual_feedback_excluded_from_recurrence_count(tmp_data_root, sample_sheet):
    sheets.save(sample_sheet)
    sid = sample_sheet["id"]
    manual = {"aspect": "manual_feedback", "expected": "(user)",
              "observed": "eyes too far apart", "severity": "major", "origin": "manual"}
    for scene in ("a", "b", "c"):
        critique.append_iteration(
            sid, scene,
            prompt={"prompts": "p"},
            critique={"drifts": [manual], "successes": [], "suggestedPromptDeltas": []},
            output_path="/tmp/x.png",
        )
    promoted = critique.promote_recurring_drifts(sid, threshold=3)
    assert promoted == []
