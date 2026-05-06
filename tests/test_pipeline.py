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
def sketch_lora_registered():
    sketch = LoRA(
        name="sketch_lora",
        pixai_model_id="sketch-id-123",
        purpose="sketch finishing",
        trigger_words="sketch_style",
        weight=1.0,
        base_model="Illustrious-XL-v1.0",
        base_model_id="1844843519625072849",
        used_in_stage=2,
    )
    loras.register(sketch)
    yield sketch


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

    # P18: drastically simplified negative — only the core safety / failure
    # mode tokens remain. The previous large negative was stacking band-aids
    # for failures the new tight prompt no longer produces.
    neg = params["negativePrompts"]
    assert neg == (
        "nsfw, worst quality, bad quality, low quality, lowres, "
        "bad anatomy, multiple figures, "
        "clothing, hair, face, shading, finished anime"
    ), f"negative does not match P18 simplified template: {neg!r}"

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


@pytest.mark.skip(reason="Phase 1A: Stage 2 is a pass-through placeholder. "
                         "Phase 1B will restore Stage 2 (pure img2img, no LoRA, "
                         "tapered ControlNet) and this test will be rewritten "
                         "against that behavior.")
def test_stage_2_attaches_controlnet_from_base_media_id(
    respx_pixai, fake_pixai_responses, sample_sheet, tmp_data_root, sketch_lora_registered,
):
    """Stage 2 should auto-derive ControlNet (openpose + depth) from the
    Stage 1 output mediaId — PixAI runs the preprocessor server-side.
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
    params = json.loads(create_calls[0].request.content)["variables"]["parameters"]
    assert params["mediaId"] == base_media  # img2img init
    types_to_media = {cn["type"]: cn["mediaId"] for cn in params["controlNets"]}
    assert types_to_media == {"openpose": base_media, "depth": base_media}


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


@pytest.mark.skip(reason="Phase 1A: sketch_lora was never trained (confirmed by "
                         "user). The 'requires sketch_lora' contract is permanently "
                         "removed. Phase 1B's restructured Stage 2 has no LoRA, so "
                         "this test will be deleted then.")
def test_stage_2_requires_sketch_lora(
    respx_pixai, fake_pixai_responses, sample_sheet, tmp_data_root,
):
    # Make sure sketch_lora is NOT registered for this test
    import app.loras.registry as reg
    saved = reg._REGISTRY.pop("sketch_lora", None)
    try:
        with PixAIClient(api_key="sk-test") as client:
            with pytest.raises(StageError) as ei:
                stage_2_sketch_pass(
                    pixai_client=client,
                    base_media_id="media-1",
                    output_dir=tmp_data_root / "out",
                )
        assert ei.value.stage == 2
    finally:
        if saved is not None:
            reg._REGISTRY["sketch_lora"] = saved


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


@pytest.mark.skip(reason="Phase 1A: Stage 2 is a placeholder that issues no "
                         "PixAI call, so this test's '3 createGenerationTask "
                         "calls' assertion fails. Phase 1B will restore Stage "
                         "2's PixAI call (pure img2img, no LoRA, tapered "
                         "ControlNet) and this test will be updated.")
def test_full_pipeline_end_to_end_mocked(
    respx_pixai, fake_pixai_responses, sample_sheet,
    tmp_data_root, patched_claude, sketch_lora_registered,
):
    """No skeleton supplied — Stage 1 runs free, Stages 2/3 derive ControlNet
    from the prior stage's output mediaId."""
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
    # Stages 2 and 3 inherit ControlNets from the previous stage's mediaId
    assert {cn["type"] for cn in s2_params["controlNets"]} == {"openpose", "depth"}
    assert s2_params["mediaId"] == result.base.media_id
    for cn in s2_params["controlNets"]:
        assert cn["mediaId"] == result.base.media_id
    assert s3_params["mediaId"] == result.sketch.media_id
    for cn in s3_params["controlNets"]:
        assert cn["mediaId"] == result.sketch.media_id


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
