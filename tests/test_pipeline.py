"""Full pipeline + critique loop smoke tests (mocked)."""

import json

import pytest

from app import critique, loras, sheets
from app.loras import LoRA
from app.pipeline import (
    PipelineRequest,
    run_pipeline,
    stage_1_base_mannequin,
    stage_2_sketch_pass,
    stage_3_character_finalization,
    stage_4_critique,
)
from app.pipeline.errors import StageError
from app.pixai import PixAIClient


@pytest.fixture
def char_lora_registered():
    """Phase 1B: Stage 3 looks up the character LoRA by linkedLoraId via
    loras.find_by_pixai_id(). Tests that exercise Stage 3 must register a
    LoRA whose pixai_model_id matches the sample_sheet's linkedLoraId.
    """
    char = LoRA(
        name="test_char_lora",
        pixai_model_id="char_lora_id_12345",
        purpose="test character finalization",
        trigger_words="test_char_trigger",
        weight=0.75,
        base_model="Illustrious-XL-v1.0",
        base_model_id="1844843519625072849",
        used_in_stage=3,
        architecture="illustrious",
    )
    loras.register(char)
    yield char


def test_stage_1_runs_free_with_no_skeleton_or_depth(
    respx_pixai, fake_pixai_responses, tmp_data_root,
):
    """Default Stage 1: txt2img + 9k9base LoRA, NO ControlNet — the LoRA
    was trained to pose itself, ControlNet over-constrains it. Stage 1
    takes archetype directly (no sheet involvement).
    """
    with PixAIClient(api_key="sk-test") as client:
        result = stage_1_base_mannequin(
            pixai_client=client,
            archetype="F_adult",
            view="front",
            pose="contrapposto_classic",
            output_dir=tmp_data_root / "out",
        )
    assert result.stage == 1
    create_calls = [
        c for c in respx_pixai.calls
        if c.request.method == "POST" and "createGenerationTask" in json.loads(c.request.content)["query"]
    ]
    assert len(create_calls) == 1
    params = json.loads(create_calls[0].request.content)["variables"]["parameters"]
    # Phase 1B: 9k9base weight tapered 1.0 -> 0.9.
    assert params["lora"] == {"2006655610114208859": 0.9}
    assert "controlNets" not in params
    # Pinned base model — Illustrious-XL-v1.0 API-callable id (taken from
    # reference task 2006996847850078063 where both parameters.modelId and
    # outputs.detailParameters.modelId showed this value).
    assert params["modelId"] == "1844843519625072849"
    # P18 tight prompt. Whitelist-only rewriter: 1girl/solo/full_body
    # normalized, everything else preserved with spaces.
    # Test runs with pose="contrapposto_classic" → "contrapposto, hand on hip".
    p = params["prompts"]
    assert p == (
        "1girl, solo, full_body, female adult, contrapposto, hand on hip, "
        "9k9base, faceless bald head, head height grid, "
        "light blue pencil, construction lines, white background"
    ), f"prompt does not match tight Stage 1 template: {p!r}"

    # All the band-aids and verbose tokens we previously stacked must be gone.
    for forbidden in (
        "single figure", "single_figure", "one character only", "centered composition",
        "full body figure", "full_body_figure",
        "8 head heights", "shoulders 1.5", "defined waist", "full hips",
        "front view", "Relaxed contrapposto", "weight on left leg",
        "atari bands", "joint ovals", "blueprint style", "technical drawing",
        "no environment", "isolated figure",
        "pure white background", "blank background", "plain white",
        "construction lines visible", "light blue pencil sketch",
        "flat 2D drawing", "line art only", "no shading", "no rendering",
        "line of action visible",
    ):
        assert forbidden not in p, f"prompt should not contain {forbidden!r}: {p}"

    # PixAI parity preserved: clipSkip pinned. qualityTag REMOVED — Booster
    # tokens fight the LoRA.
    assert params["clipSkip"] == 2
    assert "qualityTag" not in params, (
        f"qualityTag must be omitted (Booster opposes the LoRA's training); got {params.get('qualityTag')!r}"
    )

    # Phase 1C: Stage 1 negative uses underscored booru tokens — adds
    # `face_features` (replaces ambiguous `face`), plus `finished_illustration`,
    # `color`, and `photo_realistic` to keep the LoRA's flat-pencil aesthetic.
    neg = params["negativePrompts"]
    assert neg == (
        "nsfw, worst_quality, bad_quality, low_quality, lowres, "
        "bad_anatomy, multiple_figures, clothing, hair, face_features, "
        "shading, finished_illustration, color, photo_realistic"
    ), f"negative does not match Phase 1C Stage 1 template: {neg!r}"

    # High Priority is OFF by default → priority field must be absent.
    assert "priority" not in params, f"priority must be omitted in standard-queue runs: {params.get('priority')!r}"


def test_stage_1_high_priority_sends_int_1000(respx_pixai, fake_pixai_responses, tmp_data_root):
    with PixAIClient(api_key="sk-test") as client:
        stage_1_base_mannequin(
            pixai_client=client,
            archetype="F_adult",
            output_dir=tmp_data_root / "out",
            high_priority=True,
        )
    create_calls = [
        c for c in respx_pixai.calls
        if c.request.method == "POST" and "createGenerationTask" in json.loads(c.request.content)["query"]
    ]
    params = json.loads(create_calls[0].request.content)["variables"]["parameters"]
    # Per PixAI Go-client docs: priority=1000 (int) → immediate-processing queue.
    assert params["priority"] == 1000


def test_stage_1_seed_pinning(respx_pixai, fake_pixai_responses, tmp_data_root):
    with PixAIClient(api_key="sk-test") as client:
        stage_1_base_mannequin(
            pixai_client=client,
            archetype="M_adult",
            view="side_L",
            pose="power_stance",
            output_dir=tmp_data_root / "out",
            seed=42,
        )
    create_calls = [
        c for c in respx_pixai.calls
        if c.request.method == "POST" and "createGenerationTask" in json.loads(c.request.content)["query"]
    ]
    params = json.loads(create_calls[0].request.content)["variables"]["parameters"]
    assert params["seed"] == 42
    p = params["prompts"]
    assert p.startswith("1boy, solo, full_body"), f"prompt missing subject anchor: {p}"
    assert "broader shoulders" in p, f"male proportions missing: {p}"
    # View tokens are deliberately dropped from Stage 1 (LoRA defaults to front;
    # other views handled by Stage 2 ControlNet).
    assert "left-side profile view" not in p, f"view tokens should be dropped: {p}"
    assert "side_l" not in p
    # Pose: power_stance has a curated short tag.
    assert "power stance, feet apart" in p


def test_stage_1_uses_controlnet_when_skeleton_provided(
    respx_pixai, fake_pixai_responses, stub_skeleton, tmp_data_root,
):
    """Override case: user supplied a specific skeleton — attach it as
    ControlNet so the LoRA's free pose generation gets locked.
    """
    with PixAIClient(api_key="sk-test") as client:
        stage_1_base_mannequin(
            pixai_client=client,
            archetype="F_adult",
            skeleton_path=stub_skeleton,
            output_dir=tmp_data_root / "out",
        )
    create_calls = [
        c for c in respx_pixai.calls
        if c.request.method == "POST" and "createGenerationTask" in json.loads(c.request.content)["query"]
    ]
    params = json.loads(create_calls[0].request.content)["variables"]["parameters"]
    # Phase 1B: 9k9base weight tapered 1.0 -> 0.9.
    assert params["lora"] == {"2006655610114208859": 0.9}
    assert any(cn["type"] == "openpose" for cn in params["controlNets"])


def test_stage_2_pure_img2img_with_tapered_controlnet(
    respx_pixai, fake_pixai_responses, sample_sheet, tmp_data_root,
):
    """Phase 1B/1C contract for Stage 2:
    - img2img with mediaId from the Stage 1 output
    - no LoRA (pure refinement)
    - ControlNet tapered: openpose 0.85, depth 0.55
    - CFG 5.5, 24 steps, strength 0.40
    - Stage 2 negative is the short Phase 1C template
    """
    base_media = "stage1-output-media-XYZ"
    with PixAIClient(api_key="sk-test") as client:
        stage_2_sketch_pass(
            pixai_client=client,
            base_media_id=base_media,
            output_dir=tmp_data_root / "out",
        )
    create_calls = [
        c for c in respx_pixai.calls
        if c.request.method == "POST" and "createGenerationTask" in json.loads(c.request.content)["query"]
    ]
    assert len(create_calls) == 1
    params = json.loads(create_calls[0].request.content)["variables"]["parameters"]
    # img2img init from Stage 1 output
    assert params["mediaId"] == base_media
    # ControlNet tapered to 0.85/0.55, both attached to the Stage 1 mediaId
    by_type = {cn["type"]: cn for cn in params["controlNets"]}
    assert set(by_type) == {"openpose", "depth"}
    assert by_type["openpose"]["mediaId"] == base_media
    assert by_type["depth"]["mediaId"] == base_media
    assert by_type["openpose"]["weight"] == 0.85
    assert by_type["depth"]["weight"] == 0.55
    # No LoRA — Stage 2 is pure img2img refinement
    assert "lora" not in params or params["lora"] == {}
    # Phase 1B per-stage params
    assert params["cfgScale"] == 5.5
    assert params["samplingSteps"] == 24
    assert params["strength"] == 0.4
    # Phase 1C short Stage 2 negative
    assert params["negativePrompts"] == (
        "worst_quality, bad_quality, photo_realistic, "
        "finished_illustration, color, multiple_figures"
    )
    # Booster still off
    assert "qualityTag" not in params


def test_stage_3_attaches_controlnet_from_sketch_media_id(
    respx_pixai, fake_pixai_responses, sample_sheet, tmp_data_root,
    patched_claude, char_lora_registered,
):
    sketch_media = "stage2-sketch-media-ABC"
    with PixAIClient(api_key="sk-test") as client:
        stage_3_character_finalization(
            pixai_client=client,
            sketch_media_id=sketch_media,
            sheet=sample_sheet,
            scene_description="test",
            anthropic_api_key="sk-ant-test",
            output_dir=tmp_data_root / "out",
        )
    create_calls = [
        c for c in respx_pixai.calls
        if c.request.method == "POST" and "createGenerationTask" in json.loads(c.request.content)["query"]
    ]
    params = json.loads(create_calls[0].request.content)["variables"]["parameters"]
    assert params["mediaId"] == sketch_media
    # Phase 1B: ControlNet weights tapered to 0.7/0.5 in Stage 3.
    by_type = {cn["type"]: cn for cn in params["controlNets"]}
    assert set(by_type) == {"openpose", "depth"}
    assert by_type["openpose"]["mediaId"] == sketch_media
    assert by_type["depth"]["mediaId"] == sketch_media
    assert by_type["openpose"]["weight"] == 0.7
    assert by_type["depth"]["weight"] == 0.5
    # Phase 1B: char LoRA at sheet.loraWeight (0.9 in this fixture).
    assert params["lora"] == {"char_lora_id_12345": 0.9}
    # Phase 1B: Stage 3 CFG/steps/strength.
    assert params["cfgScale"] == 6.5
    assert params["samplingSteps"] == 28
    assert params["strength"] == 0.6


def test_stage_3_requires_linked_lora(
    respx_pixai, fake_pixai_responses, sample_sheet, tmp_data_root, patched_claude,
):
    sheet_no_lora = dict(sample_sheet)
    sheet_no_lora["linkedLoraId"] = None
    with PixAIClient(api_key="sk-test") as client:
        with pytest.raises(StageError) as ei:
            stage_3_character_finalization(
                pixai_client=client,
                sketch_media_id="media-1",
                sheet=sheet_no_lora,
                scene_description="test",
                anthropic_api_key="sk-ant-test",
                output_dir=tmp_data_root / "out",
            )
    assert ei.value.stage == 3


def test_stage_4_critique_returns_structured_dict(
    fake_pixai_responses, stub_skeleton, sample_sheet, tmp_data_root, patched_claude,
):
    out = stage_4_critique(
        image_path=stub_skeleton,
        sheet=sample_sheet,
        scene_description="test scene",
        anthropic_api_key="sk-ant-test",
        output_dir=tmp_data_root / "out",
    )
    assert "drifts" in out and "successes" in out and "suggestedPromptDeltas" in out
    saved_critique = (tmp_data_root / "out" / "stage_4_critique.json")
    assert saved_critique.exists()


def test_full_pipeline_end_to_end_mocked(
    respx_pixai, fake_pixai_responses, sample_sheet,
    tmp_data_root, patched_claude, char_lora_registered,
):
    """Phase 1B/1C end-to-end contract:
    - Stage 1 txt2img (no ControlNet, no skeleton supplied).
    - Stage 2 img2img with tapered ControlNet (0.85/0.55), no LoRA.
    - Stage 3 img2img with character LoRA + further-tapered ControlNet.
    - Three createGenerationTask calls total.
    - Stage 3 negative is the SDXL template (char_lora_registered fixture
      sets architecture='illustrious').
    """
    sheets.save(sample_sheet)
    req = PipelineRequest(
        sheet_id=sample_sheet["id"],
        scene_description="hero entering tavern at dusk",
        view="front",
        pose="contrapposto_classic",
    )
    result = run_pipeline(
        req,
        pixai_api_key="sk-pixai-test",
        anthropic_api_key="sk-ant-test",
    )
    assert result.base.stage == 1
    assert result.sketch.stage == 2
    assert result.character.stage == 3
    assert "drifts" in result.critique
    for r in (result.base, result.sketch, result.character):
        assert r.output_image_path.exists()

    create_calls = [
        c for c in respx_pixai.calls
        if c.request.method == "POST" and "createGenerationTask" in json.loads(c.request.content)["query"]
    ]
    assert len(create_calls) == 3
    s1_params, s2_params, s3_params = (
        json.loads(c.request.content)["variables"]["parameters"] for c in create_calls
    )
    # Stage 1 runs free
    assert "controlNets" not in s1_params
    # Stage 2: tapered ControlNet from Stage 1 mediaId, no LoRA, denoise 0.40
    by_type_s2 = {cn["type"]: cn for cn in s2_params["controlNets"]}
    assert set(by_type_s2) == {"openpose", "depth"}
    assert s2_params["mediaId"] == result.base.media_id
    assert by_type_s2["openpose"]["mediaId"] == result.base.media_id
    assert by_type_s2["depth"]["mediaId"] == result.base.media_id
    assert by_type_s2["openpose"]["weight"] == 0.85
    assert by_type_s2["depth"]["weight"] == 0.55
    assert "lora" not in s2_params or s2_params["lora"] == {}
    assert s2_params["strength"] == 0.4
    # Stage 3: further-tapered ControlNet from Stage 2 mediaId, char LoRA on
    by_type_s3 = {cn["type"]: cn for cn in s3_params["controlNets"]}
    assert set(by_type_s3) == {"openpose", "depth"}
    assert s3_params["mediaId"] == result.sketch.media_id
    assert by_type_s3["openpose"]["weight"] == 0.7
    assert by_type_s3["depth"]["weight"] == 0.5
    assert s3_params["lora"] == {"char_lora_id_12345": 0.9}
    assert s3_params["strength"] == 0.6
    # Phase 1C: char_lora_registered architecture='illustrious' →
    # SDXL negative template. sample_sheet has empty learnedDrifts so just
    # the base template appears.
    assert s3_params["negativePrompts"] == (
        "worst_quality, bad_quality, very_displeasing, displeasing, "
        "oldest, artistic_error, lowres, jpeg_artifacts, censor, "
        "watermark, bad_hands, bad_anatomy"
    )


@pytest.fixture
def fake_critique_with_major_drift(monkeypatch):
    """Override the patched_claude critique payload so every Stage 4 emits
    one 'major' boot_silhouette drift — used to test the auto-regen loop.
    """
    payload = {
        "drifts": [{"aspect": "boot_silhouette", "expected": "mid_calf",
                    "observed": "knee_high", "severity": "major"}],
        "successes": [],
        "suggestedPromptDeltas": ["mid_calf_boots, lace_up_platform_boots"],
    }
    return payload


@pytest.fixture
def stateful_patched_claude(monkeypatch, fake_prompt_payload):
    """Like patched_claude but lets each test set the critique payload via
    `state["critique"]` and switch payloads partway through (for the
    'clean critique on iter 2' test).
    """
    state = {
        "critique": {
            "drifts": [{"aspect": "boot_silhouette", "expected": "mid_calf",
                        "observed": "knee_high", "severity": "major"}],
            "successes": [],
            "suggestedPromptDeltas": ["mid_calf_boots"],
        },
        "calls": {"emit_prompt": 0, "report_critique": 0},
    }

    def fake_call_with_tool(api_key, *, tool_name, **kwargs):
        state["calls"][tool_name] = state["calls"].get(tool_name, 0) + 1
        if tool_name == "report_critique":
            return dict(state["critique"])
        if tool_name == "emit_prompt":
            return dict(fake_prompt_payload)
        if tool_name == "emit_patch":
            return {"operations": [], "audit_summary": "noop"}
        if tool_name == "emit_scene_plan":
            return {"subjects": [], "prompt_skeleton": "x", "suggested_control_nets": []}
        raise RuntimeError(f"Unmocked tool: {tool_name}")

    monkeypatch.setattr("app.claude.client.call_with_tool", fake_call_with_tool)
    monkeypatch.setattr("app.claude.prompts.call_with_tool", fake_call_with_tool)
    monkeypatch.setattr("app.claude.critique.call_with_tool", fake_call_with_tool)
    monkeypatch.setattr("app.claude.sheets.call_with_tool", fake_call_with_tool)
    monkeypatch.setattr("app.claude.scene.call_with_tool", fake_call_with_tool)
    return state


def test_auto_regen_loop_caps_at_max_iterations(
    respx_pixai, fake_pixai_responses, sample_sheet,
    tmp_data_root, stateful_patched_claude, char_lora_registered,
):
    """Phase 2: with a critique that ALWAYS surfaces a 'major' drift, the
    loop should make exactly max_iterations Stage-3 calls — no infinite
    loop, no extra runs."""
    sheets.save(sample_sheet)
    req = PipelineRequest(
        sheet_id=sample_sheet["id"],
        scene_description="cap_test",
        view="front",
        pose="contrapposto_classic",
        max_iterations=3,
        drift_severity_threshold="high",
    )
    result = run_pipeline(
        req,
        pixai_api_key="sk-pixai-test",
        anthropic_api_key="sk-ant-test",
    )
    create_calls = [
        c for c in respx_pixai.calls
        if c.request.method == "POST" and "createGenerationTask" in json.loads(c.request.content)["query"]
    ]
    # Stage 1 (1) + Stage 2 (1) + Stage 3 initial (1) + Stage 3 iter_2 (1) + Stage 3 iter_3 (1) = 5
    assert len(create_calls) == 5
    # iterations records re-rolls only (initial run is not in this list)
    assert len(result.iterations) == 2
    assert [i["iter"] for i in result.iterations] == [2, 3]
    # The drift persisted across all 3 critiques → consecutive promotion
    assert any(p["aspect"] == "boot_silhouette" for p in result.promoted_drifts)


def test_auto_regen_loop_breaks_on_clean_critique(
    respx_pixai, fake_pixai_responses, sample_sheet,
    tmp_data_root, stateful_patched_claude, char_lora_registered,
):
    """Phase 2: as soon as a critique no longer carries drifts at or above
    the threshold, the loop exits. Iter 2's critique is clean → no iter 3.
    """
    sheets.save(sample_sheet)

    # We need to flip the critique payload after the SECOND Stage-3 call.
    # Track Stage-3 calls (each one triggers a subsequent Stage-4 critique)
    # and switch to a clean payload for iteration 2's critique.
    stage_3_count = {"n": 0}
    original_handler = fake_pixai_responses["graphql_handler"]

    def counting_handler(request):
        body = json.loads(request.content)
        if "mutation createGenerationTask" in body.get("query", ""):
            params = body.get("variables", {}).get("parameters", {})
            # Stage 3 is the only call that uses a non-empty `lora` dict in
            # this fixture's setup (Stage 1 uses 9k9base; Stage 2 has no
            # LoRA). We can use the lora dict's char id presence to detect.
            if params.get("lora", {}).get("char_lora_id_12345") is not None:
                stage_3_count["n"] += 1
                if stage_3_count["n"] >= 2:
                    # Iter 2's critique should be clean — flip the payload now
                    stateful_patched_claude["critique"] = {
                        "drifts": [],
                        "successes": ["everything matches"],
                        "suggestedPromptDeltas": [],
                    }
        return original_handler(request)

    fake_pixai_responses["graphql_handler"] = counting_handler
    respx_pixai.routes[0].mock(side_effect=counting_handler)

    req = PipelineRequest(
        sheet_id=sample_sheet["id"],
        scene_description="break_test",
        view="front",
        pose="contrapposto_classic",
        max_iterations=3,
        drift_severity_threshold="high",
    )
    result = run_pipeline(
        req,
        pixai_api_key="sk-pixai-test",
        anthropic_api_key="sk-ant-test",
    )
    # Initial Stage 3 + 1 re-roll = 2 Stage-3 calls. Iter 3 should NOT happen.
    assert stage_3_count["n"] == 2
    assert len(result.iterations) == 1
    assert result.iterations[0]["iter"] == 2


def test_auto_regen_loop_disabled_with_max_iterations_one(
    respx_pixai, fake_pixai_responses, sample_sheet,
    tmp_data_root, stateful_patched_claude, char_lora_registered,
):
    """max_iterations=1 preserves the original single-pass behavior — no
    re-rolls regardless of critique severity."""
    sheets.save(sample_sheet)
    req = PipelineRequest(
        sheet_id=sample_sheet["id"],
        scene_description="single_pass",
        view="front",
        pose="contrapposto_classic",
        max_iterations=1,
        drift_severity_threshold="high",
    )
    result = run_pipeline(
        req,
        pixai_api_key="sk-pixai-test",
        anthropic_api_key="sk-ant-test",
    )
    assert result.iterations == []
    assert result.promoted_drifts == []


def test_severity_threshold_below_drift_severity_skips_reroll(
    respx_pixai, fake_pixai_responses, sample_sheet,
    tmp_data_root, stateful_patched_claude, char_lora_registered,
):
    """If only minor drifts surface but threshold is 'high', no re-roll."""
    stateful_patched_claude["critique"] = {
        "drifts": [{"aspect": "stray_strand", "expected": "smooth",
                    "observed": "wisp", "severity": "minor"}],
        "successes": [],
        "suggestedPromptDeltas": [],
    }
    sheets.save(sample_sheet)
    req = PipelineRequest(
        sheet_id=sample_sheet["id"],
        scene_description="threshold_test",
        view="front",
        pose="contrapposto_classic",
        max_iterations=3,
        drift_severity_threshold="high",
    )
    result = run_pipeline(
        req,
        pixai_api_key="sk-pixai-test",
        anthropic_api_key="sk-ant-test",
    )
    assert result.iterations == []


def test_compose_corrected_prompt_pulls_recent_history(
    tmp_data_root, sample_sheet, patched_claude,
):
    sheets.save(sample_sheet)
    sid = sample_sheet["id"]
    scene = "regen_test"
    for i in range(4):
        critique.append_iteration(
            sid, scene,
            prompt={"prompts": f"p{i}", "negative_prompts": "n"},
            critique={"drifts": [{"aspect": f"a{i}", "expected": "x", "observed": "y", "severity": "minor"}],
                      "successes": [], "suggestedPromptDeltas": [f"delta-{i}"]},
            output_path=f"/tmp/v{i}.png",
        )
    out = critique.compose_corrected_prompt(
        api_key="sk-ant-test",
        sheet=sample_sheet,
        scene_description="regenerate me",
        scene_id=scene,
        n_history=3,
        manual_feedback="eyes too far apart",
    )
    assert "prompts" in out
    assert "negative_prompts" in out
