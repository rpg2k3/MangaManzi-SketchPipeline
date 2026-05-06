"""Outfit-consistency check + reference-image plumbing tests.

The Phase 2 critique pipeline accepts a canonical reference image alongside
the generated image. When supplied, Claude's vision call sees both, and
the structured `outfit_consistency` field becomes required output.
"""

import json
from pathlib import Path

import pytest

from app.claude import critique as critique_mod
from app.critique import engine as engine_mod


@pytest.fixture
def captured_call_with_tool(monkeypatch):
    """Record the kwargs passed into call_with_tool so tests can assert on
    the schema and user_content sent to Claude. Returns a plain dict by
    default; tests can override via `captured.return_value = ...`.
    """
    captured: dict = {"calls": [], "return_value": {
        "drifts": [],
        "successes": [],
        "suggestedPromptDeltas": [],
    }}

    def fake_call_with_tool(api_key, **kwargs):
        captured["calls"].append(kwargs)
        return dict(captured["return_value"])

    monkeypatch.setattr("app.claude.critique.call_with_tool", fake_call_with_tool)
    return captured


@pytest.fixture
def stub_image(tmp_path):
    p = tmp_path / "generated.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n_GENERATED_")
    return p


@pytest.fixture
def stub_reference(tmp_path):
    p = tmp_path / "reference.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n_REFERENCE_")
    return p


def test_critique_without_reference_keeps_outfit_consistency_optional(
    captured_call_with_tool, stub_image,
):
    """When no reference image is supplied, the tool schema does NOT require
    outfit_consistency — Claude can't fill it without seeing the canonical
    design."""
    critique_mod.critique_image(
        api_key="sk-ant-test",
        image_path=stub_image,
        expected={"sheet": {"id": "x"}},
    )
    schema = captured_call_with_tool["calls"][0]["tool_input_schema"]
    assert "outfit_consistency" not in schema["required"]
    # Schema still defines the property (so Claude MAY return it if it wants)
    assert "outfit_consistency" in schema["properties"]


def test_critique_with_reference_requires_outfit_consistency(
    captured_call_with_tool, stub_image, stub_reference,
):
    critique_mod.critique_image(
        api_key="sk-ant-test",
        image_path=stub_image,
        expected={"sheet": {"id": "x"}},
        reference_image_path=stub_reference,
    )
    schema = captured_call_with_tool["calls"][0]["tool_input_schema"]
    assert "outfit_consistency" in schema["required"]
    # The original module-level template is unchanged (we deep-copied)
    assert "outfit_consistency" not in critique_mod._TOOL_SCHEMA["required"]


def test_critique_with_reference_sends_two_image_blocks(
    captured_call_with_tool, stub_image, stub_reference,
):
    critique_mod.critique_image(
        api_key="sk-ant-test",
        image_path=stub_image,
        expected={"sheet": {"id": "x"}},
        reference_image_path=stub_reference,
    )
    user_content = captured_call_with_tool["calls"][0]["user_content"]
    image_blocks = [b for b in user_content if isinstance(b, dict) and b.get("type") == "image"]
    text_blocks = [b for b in user_content if isinstance(b, dict) and b.get("type") == "text"]
    assert len(image_blocks) == 2, "expected reference + generated image blocks"
    # The ref label appears before the gen label
    text_joined = " | ".join(t["text"] for t in text_blocks)
    assert text_joined.index("Image 1 — canonical reference") < text_joined.index("Image 2 — generated output")


def test_critique_with_missing_reference_falls_back_to_single_image(
    captured_call_with_tool, stub_image, tmp_path,
):
    """A reference path that points at a non-existent file silently falls
    back to the single-image flow — this protects against half-configured
    sheets without raising mid-run."""
    missing = tmp_path / "does_not_exist.png"
    critique_mod.critique_image(
        api_key="sk-ant-test",
        image_path=stub_image,
        expected={"sheet": {"id": "x"}},
        reference_image_path=missing,
    )
    user_content = captured_call_with_tool["calls"][0]["user_content"]
    image_blocks = [b for b in user_content if isinstance(b, dict) and b.get("type") == "image"]
    assert len(image_blocks) == 1


def test_engine_resolves_reference_anchor_path(
    captured_call_with_tool, stub_image, stub_reference, monkeypatch,
):
    """run_critique pulls the first referenceAnchor from the sheet, resolves
    relative paths against repo root, and forwards into critique_image."""
    monkeypatch.setattr(engine_mod, "REPO_ROOT", stub_reference.parent)
    sheet = {
        "id": "x",
        "archetype": "F_yadult",
        "head_count": 7.5,
        "referenceAnchors": [
            {"path": stub_reference.name, "role": "design", "weight": 0.55},
        ],
    }
    engine_mod.run_critique(
        image_path=stub_image,
        sheet=sheet,
        scene_description="test",
        anthropic_api_key="sk-ant-test",
    )
    schema = captured_call_with_tool["calls"][0]["tool_input_schema"]
    assert "outfit_consistency" in schema["required"]


def test_outfit_consistency_schema_shape():
    """Lock the structured fields so future schema drift is caught."""
    oc = critique_mod._OUTFIT_CONSISTENCY_SCHEMA
    assert set(oc["required"]) == {
        "boot_silhouette",
        "hosiery",
        "belt",
        "skirt",
        "arm_coverage",
        "added_elements_not_on_reference",
    }
    boot = oc["properties"]["boot_silhouette"]["properties"]
    assert set(boot["height"]["enum"]) >= {"ankle", "mid_calf", "knee_high"}
    assert set(boot["sole"]["enum"]) >= {"flat", "moderate_platform", "heavy_lug"}
    assert set(boot["closure"]["enum"]) >= {"lace_up", "zip", "buckle"}
    hos = oc["properties"]["hosiery"]["properties"]
    assert set(hos["type"]["enum"]) >= {"none", "sheer", "fishnet_light", "fishnet_dense"}
    belt = oc["properties"]["belt"]["properties"]
    assert "chain_present" in belt and "charm_position" in belt
