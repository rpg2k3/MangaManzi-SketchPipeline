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


def test_promote_consecutive_drifts_in_one_scene(tmp_data_root, sample_sheet):
    """Phase 2: a drift that recurs in N consecutive iterations of ONE scene
    auto-promotes to learnedDrifts (separate from the cross-scene rule).
    """
    sheets.save(sample_sheet)
    sid = sample_sheet["id"]
    drift = {"aspect": "boot_silhouette", "expected": "mid_calf",
             "observed": "knee_high", "severity": "major"}
    for i in range(3):
        critique.append_iteration(
            sid, "scene_alpha",
            prompt={"prompts": f"v{i}"},
            critique={"drifts": [drift], "successes": [],
                      "suggestedPromptDeltas": []},
            output_path=f"/tmp/v{i}.png",
        )
    promoted = critique.promote_consecutive_drifts(
        sid, "scene_alpha", threshold=3,
        source_run_ids=["scene_alpha", "scene_alpha_iter_2", "scene_alpha_iter_3"],
    )
    assert len(promoted) == 1
    p = promoted[0]
    assert p["aspect"] == "boot_silhouette"
    assert p["scene_id"] == "scene_alpha"
    assert p["consecutive_count"] == 3
    assert p["sourceRunIds"] == ["scene_alpha", "scene_alpha_iter_2", "scene_alpha_iter_3"]
    assert p["origin"] == "consecutive_in_scene"
    assert p["promotedAt"]  # ISO timestamp present
    fresh = sheets.load(sid)
    assert any(ld["aspect"] == "boot_silhouette" for ld in fresh["learnedDrifts"])
    # Idempotent
    again = critique.promote_consecutive_drifts(sid, "scene_alpha", threshold=3)
    assert again == []


def test_promote_consecutive_drifts_requires_aspect_in_all_iterations(tmp_data_root, sample_sheet):
    sheets.save(sample_sheet)
    sid = sample_sheet["id"]
    boots = {"aspect": "boot_silhouette", "expected": "mid_calf",
             "observed": "knee_high", "severity": "major"}
    hair = {"aspect": "hair_color", "expected": "magenta",
            "observed": "pink", "severity": "moderate"}
    # boot_silhouette in all 3, hair_color only in iteration 2
    critique.append_iteration(sid, "s",
        prompt={}, critique={"drifts": [boots], "successes": [], "suggestedPromptDeltas": []},
        output_path="/tmp/1.png",
    )
    critique.append_iteration(sid, "s",
        prompt={}, critique={"drifts": [boots, hair], "successes": [], "suggestedPromptDeltas": []},
        output_path="/tmp/2.png",
    )
    critique.append_iteration(sid, "s",
        prompt={}, critique={"drifts": [boots], "successes": [], "suggestedPromptDeltas": []},
        output_path="/tmp/3.png",
    )
    promoted = critique.promote_consecutive_drifts(sid, "s", threshold=3)
    aspects = {p["aspect"] for p in promoted}
    assert aspects == {"boot_silhouette"}, "hair_color was not in all 3 iterations"


def test_promote_consecutive_drifts_excludes_manual_feedback(tmp_data_root, sample_sheet):
    sheets.save(sample_sheet)
    sid = sample_sheet["id"]
    manual = {"aspect": "manual_feedback", "expected": "(user)",
              "observed": "make eyes wider", "severity": "major", "origin": "manual"}
    for _ in range(3):
        critique.append_iteration(sid, "s",
            prompt={}, critique={"drifts": [manual], "successes": [], "suggestedPromptDeltas": []},
            output_path="/tmp/x.png",
        )
    promoted = critique.promote_consecutive_drifts(sid, "s", threshold=3)
    assert promoted == []


def test_promote_consecutive_drifts_short_history_no_op(tmp_data_root, sample_sheet):
    sheets.save(sample_sheet)
    sid = sample_sheet["id"]
    drift = {"aspect": "x", "expected": "a", "observed": "b", "severity": "major"}
    # Only 2 iterations — threshold 3 means no promotion.
    for _ in range(2):
        critique.append_iteration(sid, "s",
            prompt={}, critique={"drifts": [drift], "successes": [], "suggestedPromptDeltas": []},
            output_path="/tmp/x.png",
        )
    assert critique.promote_consecutive_drifts(sid, "s", threshold=3) == []


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
