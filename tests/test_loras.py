"""LoRA registry tests."""

import pytest

from app import loras
from app.loras import LoRA


def test_9k9base_is_locked_and_seeded():
    base = loras.get("9k9base")
    assert base.pixai_model_id == "2006655610114208859"
    assert base.locked is True
    # Phase 1B baseline: 0.9 (down from 1.0 — full strength was over-applying
    # the pencil-construction style; Illustrious base does most of the work).
    assert base.weight == 0.9
    assert base.architecture == "illustrious"
    assert base.used_in_stage == 1
    assert "9k9base" in base.trigger_words
    assert "construction lines" in base.positive_append
    assert "nsfw" in base.default_negative


def test_register_replaces_unlocked_entries():
    sketch = LoRA(
        name="sketch_lora",
        pixai_model_id="111",
        purpose="sketch",
        trigger_words="sketch_trigger",
        weight=1.0,
        base_model="Illustrious-XL-v1.0",
        base_model_id="1844843519625072849",
        used_in_stage=2,
    )
    loras.register(sketch)
    assert loras.get("sketch_lora").pixai_model_id == "111"

    sketch2 = LoRA(
        name="sketch_lora",
        pixai_model_id="222",
        purpose="sketch",
        trigger_words="sketch_trigger",
        weight=0.8,
        base_model="Illustrious-XL-v1.0",
        base_model_id="1844843519625072849",
        used_in_stage=2,
    )
    loras.register(sketch2)
    assert loras.get("sketch_lora").pixai_model_id == "222"


def test_register_refuses_to_overwrite_locked():
    overshadow = LoRA(
        name="9k9base", pixai_model_id="999",
        purpose="x", trigger_words="x", weight=1.0,
        base_model="Illustrious-XL-v1.0", base_model_id="x",
        used_in_stage=1, locked=False,
    )
    with pytest.raises(ValueError):
        loras.register(overshadow)


def test_9k9base_pinned_to_illustrious():
    base = loras.get("9k9base")
    assert base.base_model == "Illustrious-XL-v1.0"
    assert base.base_model_id == "1844843519625072849"


def test_stage_loras_filters_by_stage():
    stage1 = loras.stage_loras(1)
    assert any(l.name == "9k9base" for l in stage1)
