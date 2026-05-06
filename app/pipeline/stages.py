"""Independently callable pipeline stages.

Stage 1 — base mannequin   (PixAI txt2img + 9k9base + ControlNet)
Stage 2 — sketch pass      (PixAI img2img + sketch_lora)
Stage 3 — character        (PixAI img2img + character LoRA from sheet)
Stage 4 — critique         (Claude review)
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app import loras
from app.claude.critique import critique_image
from app.claude.prompts import generate_prompt
from app.pixai import (
    ControlNetSpec,
    LoraSpec,
    PixAIClient,
    TaskParameters,
    inflight_slot,
    media_ids_from_task,
    poll_until_complete,
)
from app.pixai.prompt_rewriter import to_booru

# PixAI web UI's default Booster — appended to the positive prompt by the
# server when qualityTag is set.
QUALITY_BOOSTER = {
    "prefix": "",
    "suffix": "masterpiece, best quality, amazing quality, very aesthetic, absurdres",
}
from app.ui.taxonomy import archetype_core, pose_core, subject_anchor

from .errors import StageError


@dataclass
class StageResult:
    stage: int
    task: dict
    output_image_path: Path
    media_id: str


def _archetype_dict(sheet: dict) -> dict:
    return {
        "code": sheet.get("archetype"),
        "head_count": sheet.get("head_count"),
    }


def _save_output(client: PixAIClient, media_id: str, dest: Path) -> Path:
    media = client.get_media_by_id(media_id)
    img = client.download_media(media)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(img)
    return dest


def _run_task(client: PixAIClient, params: TaskParameters, *, timeout: float = 180.0) -> dict:
    with inflight_slot():
        created = client.create_generation_task(params.to_pixai_dict())
        task_id = created.get("id")
        if not task_id:
            raise StageError(f"createGenerationTask returned no id: {created}", stage=-1)
        return poll_until_complete(client, task_id, timeout=timeout)


def stage_1_base_mannequin(
    *,
    pixai_client: PixAIClient,
    archetype: str,
    output_dir: Path,
    view: str = "front",
    pose: str = "contrapposto_classic",
    skeleton_path: Path | None = None,
    depth_path: Path | None = None,
    high_priority: bool = False,
    seed: int | None = None,
    timeout: float = 180.0,
) -> StageResult:
    """Run free txt2img with the 9k9base LoRA. Skeleton/depth are OPTIONAL
    overrides — the LoRA was trained to produce well-posed mannequins on
    its own, and adding ControlNet by default suppresses its style.

    Prompt assembly order (from spec):
      [subject anchor] + [archetype proportions] + [view] + [pose]
      + [9k9base triggers] + [9k9base positive_append] + [isolation]
    """
    base = loras.get("9k9base")

    control_nets: list[ControlNetSpec] = []
    if skeleton_path is not None:
        pose_media_id = pixai_client.upload_media_file(skeleton_path)
        control_nets.append(ControlNetSpec(type="openpose", media_id=pose_media_id))
    if depth_path is not None:
        depth_media_id = pixai_client.upload_media_file(depth_path)
        control_nets.append(ControlNetSpec(type="depth", media_id=depth_media_id))

    # Stage 1 prompt — selective style reinforcement. The first attempt
    # without ANY style tokens produced rendered/shaded output, so the LoRA
    # needs prompt support after all — but `blueprint style` / `technical
    # drawing` are excluded because they previously pulled the model toward
    # architectural diagrams. The white-background line is tripled because
    # plain "white background" wasn't holding (tile patterns bled in).
    # P18: tight Stage 1 prompt — matches the user's working web-UI test
    # (Booster OFF, short prompt). View tokens dropped (LoRA defaults to
    # front; Stage 2 ControlNet handles other views). Anatomy/style spam
    # dropped — the LoRA already knows construction-mannequin language;
    # restating it dilutes attention.
    parts = [
        subject_anchor(archetype),                          # "1girl, solo, full_body"
        archetype_core(archetype),                          # "female adult"
        pose_core(pose),                                    # "contrapposto"
        "9k9base, faceless bald head, head height grid",    # LoRA trigger + 2 cues
        "light blue pencil, construction lines",            # minimal style support
        "white background",
    ]
    natural_prompts = ", ".join(p for p in parts if p)
    # Whitelist-only rewriter: 1girl/solo/full_body get normalized; everything
    # else passes through with spaces preserved.
    prompts = to_booru(natural_prompts)

    params = TaskParameters(
        prompts=prompts,
        negative_prompts=base.default_negative,
        loras=[LoraSpec(model_id=base.pixai_model_id, weight=base.weight)],
        control_nets=control_nets,
        priority=(1000 if high_priority else None),
        seed=seed,
        # Pin the base checkpoint to the LoRA's training base — SDXL LoRAs
        # require their native base or output is degraded.
        model_id=base.base_model_id,
        # P18: qualityTag (Booster) intentionally omitted — its style tokens
        # ("expressive faces", "controlled shading", "polished finish") fight
        # the 9k9base LoRA's training (faceless, flat, pencil construction).
        quality_tag=None,
    )

    task = _run_task(pixai_client, params, timeout=timeout)
    media_ids = media_ids_from_task(task)
    if not media_ids:
        raise StageError("Stage 1 produced no output media", stage=1)

    out_path = _save_output(pixai_client, media_ids[0], output_dir / "stage_1_base.png")
    return StageResult(stage=1, task=task, output_image_path=out_path, media_id=media_ids[0])


def stage_2_sketch_pass(
    *,
    pixai_client: PixAIClient,
    base_media_id: str,
    output_dir: Path,
    high_priority: bool = False,
    timeout: float = 180.0,
) -> StageResult:
    """Phase 1A placeholder — pass-through.

    The original Stage 2 called `loras.get("sketch_lora")`, but that LoRA
    was never trained (confirmed by user). Until Phase 1B restructures
    Stage 2 into a proper pure-img2img refinement step (no LoRA, denoise
    0.40, tapered ControlNet), this placeholder forwards the Stage 1
    media id and image path unchanged. No PixAI call is issued.

    `pixai_client`, `high_priority`, and `timeout` are kept in the
    signature for API stability with the orchestrator caller and so
    Phase 1B can fill the body without touching call sites.
    """
    del pixai_client, high_priority, timeout  # intentionally unused — Phase 1B fills these
    stage_1_path = output_dir / "stage_1_base.png"
    return StageResult(
        stage=2,
        task={"placeholder": "phase_1a_passthrough"},
        output_image_path=stage_1_path,
        media_id=base_media_id,
    )


def stage_3_character_finalization(
    *,
    pixai_client: PixAIClient,
    sketch_media_id: str,
    sheet: dict,
    scene_description: str,
    anthropic_api_key: str,
    output_dir: Path,
    view: str = "front",
    pose: str | None = None,
    prior_critiques: list[dict] | None = None,
    strength: float = 0.55,
    high_priority: bool = False,
    timeout: float = 180.0,
) -> StageResult:
    char_lora_id = sheet.get("linkedLoraId")
    if not char_lora_id:
        raise StageError(
            f"Sheet '{sheet.get('id')}' has no linkedLoraId — cannot finalize character.",
            stage=3,
        )
    char_weight = float(sheet.get("loraWeight") or 1.0)
    char_triggers = sheet.get("triggerWords") or ""

    prompt_data = generate_prompt(
        api_key=anthropic_api_key,
        archetype=_archetype_dict(sheet),
        view=view,
        pose=pose,
        stage=3,
        sheet=sheet,
        prior_critiques=prior_critiques,
        scene_description=scene_description,
        lora_triggers=[char_triggers] if char_triggers else None,
        pose_id=pose or "",
    )

    # Stage 3 uses the same base checkpoint as the sketch_lora — the chain
    # stays on one model family for visual consistency.
    sketch = loras.get("sketch_lora")
    params = TaskParameters(
        prompts=prompt_data["prompts"],
        negative_prompts=prompt_data["negative_prompts"],
        loras=[LoraSpec(model_id=char_lora_id, weight=char_weight)],
        media_id=sketch_media_id,
        strength=strength,
        control_nets=[
            ControlNetSpec(type="openpose", media_id=sketch_media_id),
            ControlNetSpec(type="depth", media_id=sketch_media_id),
        ],
        priority=(1000 if high_priority else None),
        model_id=sketch.base_model_id,
    )

    task = _run_task(pixai_client, params, timeout=timeout)
    media_ids = media_ids_from_task(task)
    if not media_ids:
        raise StageError("Stage 3 produced no output media", stage=3)

    out_path = _save_output(pixai_client, media_ids[0], output_dir / "stage_3_character.png")
    return StageResult(stage=3, task=task, output_image_path=out_path, media_id=media_ids[0])


def stage_4_critique(
    *,
    image_path: Path,
    sheet: dict,
    scene_description: str,
    anthropic_api_key: str,
    output_dir: Path | None = None,
) -> dict:
    expected = {
        "archetype": _archetype_dict(sheet),
        "sheet": sheet,
        "scene": scene_description,
    }
    critique = critique_image(
        api_key=anthropic_api_key,
        image_path=image_path,
        expected=expected,
        character_id=sheet.get("id", ""),
    )
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "stage_4_critique.json").write_text(
            json.dumps(critique, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return critique
