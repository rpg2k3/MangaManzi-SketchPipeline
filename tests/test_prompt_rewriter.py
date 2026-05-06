"""Tests for the whitelist-only booru rewriter."""

from app.pixai.prompt_rewriter import to_booru


def test_known_tag_normalized():
    assert to_booru("Solo") == "solo"
    assert to_booru("Full Body") == "full_body"
    assert to_booru("LOOKING AT VIEWER") == "looking_at_viewer"


def test_unknown_phrase_passes_through_unchanged():
    """Multi-word phrases that aren't real booru tags must keep spaces."""
    assert to_booru("weight on left leg") == "weight on left leg"
    assert to_booru("both arms hanging naturally") == "both arms hanging naturally"
    assert to_booru("Relaxed contrapposto — weight on left leg") == (
        "Relaxed contrapposto — weight on left leg"
    )


def test_mixed_known_and_unknown():
    out = to_booru("1girl, solo, weight on left leg, full body, slight head tilt")
    assert out == "1girl, solo, weight on left leg, full_body, slight head tilt"


def test_quality_booster_tags_normalized():
    out = to_booru("masterpiece, best quality, amazing quality, very aesthetic, absurdres")
    assert out == "masterpiece, best_quality, amazing_quality, very_aesthetic, absurdres"


def test_invented_tokens_NOT_underscored():
    """The earlier mechanical rewriter invented fake tokens — must not happen."""
    out = to_booru("single figure, one character only, centered composition, full body figure")
    # None of these are in the whitelist, so all pass through with spaces.
    assert "single_figure" not in out
    assert "one_character_only" not in out
    assert "centered_composition" not in out
    assert "full_body_figure" not in out
    assert "single figure" in out
    assert "one character only" in out


def test_empty_input():
    assert to_booru("") == ""
    assert to_booru(None) is None


def test_extra_whitespace_collapsed_for_known_tags():
    assert to_booru("  Full   Body  ") == "full_body"
