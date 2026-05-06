"""Sheet schema, CRUD, and migration tests."""

import json

import pytest

from app import sheets


def test_upgrade_sheet_is_non_destructive_and_adds_new_fields(sample_sheet):
    alpha = {
        "character_id": "x_y",
        "archetype": "F_adult",
        "head_count": 8,
        "build": {"shoulder_width_heads": 1.8},
        "notes_for_generation": "preserve mesh wraps",
    }
    upgraded = sheets.upgrade_sheet(alpha)
    assert upgraded["id"] == "x_y"
    assert upgraded["name"] == "X Y"
    assert upgraded["linkedLoraId"] is None
    assert upgraded["loraWeight"] == 1.0
    assert upgraded["designNotes"] == "preserve mesh wraps"
    assert upgraded["learnedDrifts"] == []
    assert upgraded["audit"] == []
    # Alpha fields preserved
    assert upgraded["character_id"] == "x_y"
    assert upgraded["archetype"] == "F_adult"
    assert upgraded["head_count"] == 8
    assert upgraded["build"] == {"shoulder_width_heads": 1.8}


def test_upgrade_sheet_preserves_existing_new_fields():
    s = {
        "id": "z", "character_id": "z",
        "linkedLoraId": "abc", "loraWeight": 0.7,
        "designNotes": "do not overwrite", "learnedDrifts": [{"aspect": "x"}],
    }
    out = sheets.upgrade_sheet(s)
    assert out["linkedLoraId"] == "abc"
    assert out["loraWeight"] == 0.7
    assert out["designNotes"] == "do not overwrite"
    assert out["learnedDrifts"] == [{"aspect": "x"}]


def test_save_load_roundtrip(tmp_data_root, sample_sheet):
    sheets.save(sample_sheet)
    out = sheets.load(sample_sheet["id"])
    assert out["id"] == sample_sheet["id"]
    assert out["archetype"] == "F_yadult"


def test_list_ids_and_exists_and_delete(tmp_data_root, sample_sheet):
    assert sheets.list_ids() == []
    sheets.save(sample_sheet)
    assert sheets.exists(sample_sheet["id"])
    assert sample_sheet["id"] in sheets.list_ids()
    assert sheets.delete(sample_sheet["id"]) is True
    assert sheets.exists(sample_sheet["id"]) is False


def test_apply_patch_set_append_remove_with_audit(tmp_data_root, sample_sheet):
    ops = [
        {"op": "set", "path": "build.muscle_definition", "value": "lean", "reason": "test"},
        {"op": "append", "path": "continuityRules", "value": "always_keep_cat_ears", "reason": "test"},
        {"op": "remove", "path": "color_palette.primary", "reason": "test"},
    ]
    out = sheets.apply_patch(sample_sheet, ops, summary="unit-test patch")
    assert out["build"]["muscle_definition"] == "lean"
    assert out["continuityRules"] == ["always_keep_cat_ears"]
    assert "primary" not in out["color_palette"]
    assert out["audit"][-1]["summary"] == "unit-test patch"
    assert len(out["audit"][-1]["operations"]) == 3


def test_migration_idempotent(tmp_data_root, tmp_path):
    char_root = tmp_path / "characters" / "alpha_char"
    char_root.mkdir(parents=True)
    (char_root / "extracted.json").write_text(json.dumps({
        "character_id": "alpha_char",
        "archetype": "F_adult",
        "head_count": 8,
        "notes_for_generation": "alpha note",
    }))
    migrated_first = sheets.migrate_alpha_characters(characters_root=tmp_path / "characters")
    migrated_second = sheets.migrate_alpha_characters(characters_root=tmp_path / "characters")
    assert migrated_first == ["alpha_char"]
    assert migrated_second == []
    out = sheets.load("alpha_char")
    assert out["designNotes"] == "alpha note"
    assert out["learnedDrifts"] == []
