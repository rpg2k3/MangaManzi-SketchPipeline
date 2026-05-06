"""Phase 3 tests — booster gate, tag validator, prompt assembly logging,
token budgets.
"""

import csv
import json
import warnings
from pathlib import Path

import pytest

from app.pixai import LoraSpec, TaskParameters
from app.pixai.tag_validator import (
    load_cache,
    positive_prompt_tokens,
    seed_cache_for_tests,
    validate_tokens,
)


# ─────────────────────────────────────────────────────────────────────
# 3.5 Booster gate
# ─────────────────────────────────────────────────────────────────────

def test_booster_gate_drops_quality_tag_when_not_allowed():
    p = TaskParameters(
        prompts="x", negative_prompts="y",
        quality_tag={"prefix": "", "suffix": "masterpiece"},
        allow_booster=False,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        d = p.to_pixai_dict()
    assert "qualityTag" not in d, "qualityTag must NOT reach the API without explicit opt-in"
    msgs = [str(w.message) for w in caught]
    assert any("allow_booster" in m for m in msgs), \
        f"expected allow_booster warning, got {msgs}"


def test_booster_gate_includes_quality_tag_when_allowed():
    p = TaskParameters(
        prompts="x", negative_prompts="y",
        quality_tag={"prefix": "", "suffix": "masterpiece"},
        allow_booster=True,
    )
    d = p.to_pixai_dict()
    assert d["qualityTag"] == {"prefix": "", "suffix": "masterpiece"}


def test_booster_gate_no_quality_tag_no_warning():
    """The default path: quality_tag=None, allow_booster=False — no
    warning, no qualityTag in payload. This is what the three real stages
    use today."""
    p = TaskParameters(prompts="x", negative_prompts="y")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        d = p.to_pixai_dict()
    assert "qualityTag" not in d
    assert not [w for w in caught if "allow_booster" in str(w.message)]


# ─────────────────────────────────────────────────────────────────────
# 3.3 Tag validator
# ─────────────────────────────────────────────────────────────────────

def test_validate_tokens_returns_empty_when_cache_missing(tmp_path):
    missing = tmp_path / "no_cache.csv"
    assert load_cache(missing) == set()
    assert validate_tokens("1girl, mid_calf_boots", cache_path=missing) == []


def test_validate_tokens_flags_unknown_underscored_tokens(tmp_path):
    cache = tmp_path / "tags.csv"
    seed_cache_for_tests(["1girl", "solo", "fishnet_thighhighs"], cache)
    prompt = "1girl, solo, mid_calf_lace_up_platform_boots, fishnet_thighhighs, invented_tag"
    unknown = validate_tokens(prompt, cache_path=cache)
    assert unknown == ["mid_calf_lace_up_platform_boots", "invented_tag"]


def test_validate_tokens_ignores_natural_language_clauses(tmp_path):
    cache = tmp_path / "tags.csv"
    seed_cache_for_tests(["1girl"], cache)
    # "(token:1.2)" is prompt-weight syntax; "broader shoulders" is natural
    # language. Neither should be flagged as an unknown booru tag.
    prompt = "1girl, (heart_charm:1.3), broader shoulders, female young adult"
    unknown = validate_tokens(prompt, cache_path=cache)
    # Only `heart_charm` is a booru-shaped token (lowercase + underscores)
    # AND not in the cache. Wait — `(heart_charm:1.3)` has parens, so it
    # fails the booru-shape regex. So nothing flagged.
    assert unknown == []


def test_positive_prompt_tokens_strips_and_drops_empty():
    assert positive_prompt_tokens("") == []
    assert positive_prompt_tokens(None) == []
    assert positive_prompt_tokens("a, b, , c ") == ["a", "b", "c"]


def test_load_cache_handles_corrupt_file(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_bytes(b"\xff\xfe\x00\x00not_real_csv")
    # Should not raise
    out = load_cache(bad)
    assert isinstance(out, set)


# ─────────────────────────────────────────────────────────────────────
# 3.1 + 3.2 Assembled-request logging + token budgets
# ─────────────────────────────────────────────────────────────────────

def test_log_assembled_request_writes_run_files(tmp_path, monkeypatch):
    from app.pipeline import stages
    monkeypatch.setattr(stages, "RUNS_ROOT", tmp_path / "runs")

    params = {"prompts": "1girl, solo, full_body, contrapposto", "width": 832}
    stages._log_assembled_request(run_id="my_run", stage=1, params_dict=params)

    run_dir = tmp_path / "runs" / "my_run"
    assert (run_dir / "stage_1_request.json").exists()
    written = json.loads((run_dir / "stage_1_request.json").read_text())
    assert written["prompts"].startswith("1girl")

    manifest = (run_dir / "manifest.jsonl").read_text().strip().splitlines()
    assert len(manifest) == 1
    entry = json.loads(manifest[0])
    assert entry["stage"] == 1
    assert entry["token_count_positive"] == 4


def test_log_assembled_request_no_op_without_run_id(tmp_path, monkeypatch):
    from app.pipeline import stages
    monkeypatch.setattr(stages, "RUNS_ROOT", tmp_path / "runs")
    stages._log_assembled_request(run_id=None, stage=1, params_dict={"prompts": "x"})
    # The runs dir should not have been created
    assert not (tmp_path / "runs").exists()


def test_token_budget_warns_on_breach(tmp_path, monkeypatch):
    from app.pipeline import stages
    monkeypatch.setattr(stages, "RUNS_ROOT", tmp_path / "runs")
    huge = ", ".join(f"t{i}" for i in range(15))  # 15 tokens, Stage 1 cap is 12
    stages._log_assembled_request(run_id="r", stage=1, params_dict={"prompts": huge})
    manifest = (tmp_path / "runs" / "r" / "manifest.jsonl").read_text()
    entry = json.loads(manifest.strip())
    assert entry["budget_warnings"], "expected budget warning for >12-token Stage 1 prompt"
    assert "hard cap" in entry["budget_warnings"][0]


def test_stage_3_token_budget_ideal_range(tmp_path, monkeypatch):
    from app.pipeline import stages
    monkeypatch.setattr(stages, "RUNS_ROOT", tmp_path / "runs")
    # 25 tokens — under the 50 hard cap, but below the 30-40 ideal range.
    short = ", ".join(f"t{i}" for i in range(25))
    stages._log_assembled_request(run_id="r", stage=3, params_dict={"prompts": short})
    entry = json.loads((tmp_path / "runs" / "r" / "manifest.jsonl").read_text().strip())
    assert any("ideal range" in w for w in entry["budget_warnings"])


def test_token_budget_no_warning_in_range(tmp_path, monkeypatch):
    from app.pipeline import stages
    monkeypatch.setattr(stages, "RUNS_ROOT", tmp_path / "runs")
    in_range = ", ".join(f"t{i}" for i in range(35))  # 35 tokens, ideal for Stage 3
    stages._log_assembled_request(run_id="r", stage=3, params_dict={"prompts": in_range})
    entry = json.loads((tmp_path / "runs" / "r" / "manifest.jsonl").read_text().strip())
    assert entry["budget_warnings"] == []


def test_assembled_request_includes_unknown_booru_tags(tmp_path, monkeypatch):
    from app.pipeline import stages
    cache = tmp_path / "tags.csv"
    seed_cache_for_tests(["1girl", "solo", "full_body"], cache)
    monkeypatch.setattr(stages, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr("app.pixai.tag_validator.CACHE_PATH", cache)

    stages._log_assembled_request(
        run_id="r", stage=1,
        params_dict={"prompts": "1girl, solo, full_body, invented_thing, 9k9base"},
    )
    entry = json.loads((tmp_path / "runs" / "r" / "manifest.jsonl").read_text().strip())
    # `9k9base` and `invented_thing` are not in our 3-tag synthetic cache.
    assert set(entry["unknown_booru_tags"]) == {"9k9base", "invented_thing"}
