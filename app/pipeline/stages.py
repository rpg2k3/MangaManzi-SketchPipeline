"""Independently callable pipeline stages.

Stage 1 — base mannequin   (PixAI txt2img + 9k9base + ControlNet)
Stage 2 — sketch pass      (PixAI img2img + tapered ControlNet, no LoRA)
Stage 3 — character        (PixAI img2img + character LoRA from sheet)
Stage 4 — critique         (Claude review)

Phase 3: each stage writes its assembled createGenerationTask payload to
`runs/<run_id>/stage_<n>_request.json` before the PixAI call, plus a
manifest line into `runs/<run_id>/manifest.jsonl`. Token-budget breaches
and unknown-booru-tag warnings land in the manifest too.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app import loras
from app.critique.engine import run_critique
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
from app.ui.taxonomy import archetype_core, pose_core, subject_anchor

from .errors import StageError

# Phase 1C Stage 2 negative — short booru-token form per spec.
# Construction-style drift (which the long Stage 1 negative addresses)
# is no longer a Stage 2 concern: this stage starts from a clean Stage 1
# mannequin, so we only need to ward off the universal failure modes.
_STAGE_2_NEGATIVE = (
    "worst_quality, bad_quality, photo_realistic, "
    "finished_illustration, color, multiple_figures"
)

# Phase 3 logging — `runs/` is repo-relative, gitignored. Each stage writes
# the assembled request + a manifest line so a run is reproducible
# offline.
RUNS_ROOT = Path(__file__).resolve().parent.parent.parent / "runs"

# One-shot session debug print: the very first assembled request a
# session emits is also dumped to stdout so an interactive operator
# can sanity-check parameters without opening the JSON file.
_FIRST_LOG_EMITTED = False

# Token budgets per stage. Values are SOFT — runs proceed even on
# breach; the warning lands in the manifest.
_TOKEN_BUDGETS = {
    1: {"hard": 12, "ideal": (1, 12)},
    2: {"hard": 20, "ideal": (1, 20)},
    3: {"hard": 50, "ideal": (30, 40)},
}


def _count_prompt_tokens(prompt: str) -> int:
    """Comma-split token count, ignoring empty parts."""
    if not prompt:
        return 0
    return sum(1 for t in prompt.split(",") if t.strip())


def _log_assembled_request(
    *,
    run_id: str | None,
    stage: int,
    params_dict: dict,
    extra: dict | None = None,
) -> None:
    """Write the assembled PixAI payload and any token-budget /
    tag-validity warnings to runs/<run_id>/. No-op if `run_id is None`
    (so direct-from-test stage calls don't litter the FS).

    The first assembled request per process is also printed to stdout —
    one-shot — so an interactive operator can verify parameters without
    opening files.
    """
    global _FIRST_LOG_EMITTED
    if run_id is None:
        return
    run_dir = RUNS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Token-budget evaluation
    budget = _TOKEN_BUDGETS.get(stage, {})
    positive = params_dict.get("prompts", "")
    token_count = _count_prompt_tokens(positive)
    budget_warnings: list[str] = []
    hard = budget.get("hard")
    ideal = budget.get("ideal")
    if hard is not None and token_count > hard:
        budget_warnings.append(
            f"Stage {stage} positive prompt has {token_count} tokens "
            f"(hard cap {hard}). Soft warning — run continues."
        )
    if (
        ideal is not None
        and token_count > 0
        and not (ideal[0] <= token_count <= ideal[1])
        and not budget_warnings
    ):
        budget_warnings.append(
            f"Stage {stage} positive prompt has {token_count} tokens "
            f"(ideal range {ideal[0]}-{ideal[1]})."
        )

    # Tag-validity check (best-effort; empty-cache returns no warnings)
    try:
        from app.pixai.tag_validator import validate_tokens
        unknown_tags = validate_tokens(positive)
    except Exception as e:  # never let validation break a run
        unknown_tags = []
        budget_warnings.append(f"tag-validator error: {e}")

    request_path = run_dir / f"stage_{stage}_request.json"
    request_path.write_text(
        json.dumps(params_dict, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    manifest_path = run_dir / "manifest.jsonl"
    manifest_entry = {
        "ts": datetime.now().isoformat(),
        "stage": stage,
        "token_count_positive": token_count,
        "budget_warnings": budget_warnings,
        "unknown_booru_tags": unknown_tags,
        "request_file": str(request_path.name),
    }
    if extra:
        manifest_entry.update(extra)
    with open(manifest_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(manifest_entry, ensure_ascii=False) + "\n")

    if not _FIRST_LOG_EMITTED:
        _FIRST_LOG_EMITTED = True
        print(
            f"[pipeline] First assembled request this session — "
            f"stage {stage}, run_id={run_id}, "
            f"{token_count} positive tokens, "
            f"{len(budget_warnings)} budget warnings, "
            f"{len(unknown_tags)} unknown booru tags. "
            f"Full payload: {request_path}",
            flush=True,
        )

# PixAI web UI's default Booster — appended to the positive prompt by the
# server when qualityTag is set. Phase 3: gated behind allow_booster=True
# on TaskParameters; the three real stages keep quality_tag=None.
QUALITY_BOOSTER = {
    "prefix": "",
    "suffix": "masterpiece, best quality, amazing quality, very aesthetic, absurdres",
}


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
    run_id: str | None = None,
) -> StageResult:
    """Run free txt2img with the 9k9base LoRA. Skeleton/depth are OPTIONAL
    overrides — the LoRA was trained to produce well-posed mannequins on
    its own, and adding ControlNet by default suppresses its style.

    Prompt assembly order:
      [subject anchor] + [archetype proportions] + [pose]
      + [9k9base triggers] + [minimal style support] + [white_background]
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

    # Phase 1B baseline: 832x1216 portrait, CFG 6.0, 26 steps come from
    # the global defaults (set in app/pixai/defaults.py). LoRA weight 0.9
    # comes from the registry. Sampler DPM++ 2M Karras and clip_skip 2
    # also from defaults. `priority` field is omitted entirely when
    # high_priority is off (do not pass priority:0).
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

    _log_assembled_request(
        run_id=run_id, stage=1, params_dict=params.to_pixai_dict(),
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
    run_id: str | None = None,
) -> StageResult:
    """Phase 1B: pure img2img refinement on the Stage 1 base, no LoRA.

    The previous design called a `sketch_lora` that was never actually
    trained. The new design refines the Stage 1 mannequin into a cleaner
    pencil sketch via a low-denoise img2img pass (strength 0.40) on the
    same Illustrious base checkpoint, with the original 9k9base
    ControlNet conditioning carried through at tapered weights so the
    pose stays locked but doesn't dominate.

    Parameters per Phase 1B spec:
      cfg_scale=5.5, sampling_steps=24, strength=0.40
      ControlNet weights: openpose 0.85, depth 0.55
      No LoRA. Same base checkpoint as Stage 1 (Illustrious-XL-v1.0).
      qualityTag (Booster) omitted — same logic as Stage 1.
    """
    base = loras.get("9k9base")  # only for base_model_id pinning

    # Stage 2 prompt is intentionally minimal — Phase 1C will harden this
    # to the spec'd "9k9base, refined_pencil_sketch, clean_construction_lines"
    # form. For Phase 1B we keep the Stage 1 trigger language so this
    # commit is parameter-only.
    stage_2_prompt = "9k9base, refined pencil sketch, clean construction lines"

    params = TaskParameters(
        prompts=stage_2_prompt,
        negative_prompts=_STAGE_2_NEGATIVE,
        loras=[],
        media_id=base_media_id,
        strength=0.40,
        cfg_scale=5.5,
        sampling_steps=24,
        control_nets=[
            ControlNetSpec(type="openpose", media_id=base_media_id, weight=0.85),
            ControlNetSpec(type="depth", media_id=base_media_id, weight=0.55),
        ],
        priority=(1000 if high_priority else None),
        model_id=base.base_model_id,
        quality_tag=None,
    )

    _log_assembled_request(
        run_id=run_id, stage=2, params_dict=params.to_pixai_dict(),
    )

    task = _run_task(pixai_client, params, timeout=timeout)
    media_ids = media_ids_from_task(task)
    if not media_ids:
        raise StageError("Stage 2 produced no output media", stage=2)

    out_path = _save_output(pixai_client, media_ids[0], output_dir / "stage_2_sketch.png")
    return StageResult(stage=2, task=task, output_image_path=out_path, media_id=media_ids[0])


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
    high_priority: bool = False,
    timeout: float = 180.0,
    run_id: str | None = None,
) -> StageResult:
    """Phase 1B: character finalization via the per-sheet character LoRA.

    Parameters per Phase 1B spec:
      cfg_scale=6.5, sampling_steps=28, strength=0.60
      ControlNet weights: openpose 0.7, depth 0.5 (further tapered from S2)
      Character LoRA at sheet.loraWeight (default 0.75).
      9k9base is OFF in Stage 3 — the pose is now locked by ControlNet.
      qualityTag (Booster) omitted — same logic as Stage 1/2.

    Two spec items remain unimplementable on the current PixAI GraphQL
    surface and are tracked for Phase 2 / 4:
      - "ControlNet end at 0.85" (guidance end / control-end timing) —
        ControlNetSpec has no field for it; PixAI's exposed schema in
        this codebase doesn't accept one.
      - Reference-image conditioning at weight 0.55 / 0.5 (IP-Adapter
        Plus or Reference-Only ControlNet) — neither type string is
        documented in the codebase. Sheet.referenceAnchors is carried
        through the pipeline but no API call references it yet.
    """
    char_lora_id = sheet.get("linkedLoraId")
    if not char_lora_id:
        raise StageError(
            f"Sheet '{sheet.get('id')}' has no linkedLoraId — cannot finalize "
            "character. Supply the PixAI model id on the sheet's linkedLoraId "
            "field, then register the LoRA via app.loras.register() so Stage 3 "
            "can resolve its architecture and base_model_id.",
            stage=3,
        )
    char_lora = loras.find_by_pixai_id(char_lora_id)
    if char_lora is None:
        raise StageError(
            f"linkedLoraId={char_lora_id!r} is not in the LoRA registry. "
            "Register the LoRA first via app.loras.register() — Stage 3 needs "
            "its architecture (DiT.2 vs SDXL) and base_model_id to assemble a "
            "valid request.",
            stage=3,
        )

    char_weight = float(sheet.get("loraWeight") or 0.75)
    triggers = sheet.get("triggerWords") or []
    if isinstance(triggers, list):
        char_triggers = ", ".join(triggers)
    else:
        char_triggers = str(triggers)

    # Phase 1C: pass the character LoRA's architecture so generate_prompt
    # can fork its post-processing — DiT.2 routes drift corrections into
    # the positive prompt and clears the negative; SDXL/Illustrious uses
    # the deterministic SDXL negative template + drift identifiers.
    prompt_data = generate_prompt(
        api_key=anthropic_api_key,
        architecture=char_lora.architecture,
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

    params = TaskParameters(
        prompts=prompt_data["prompts"],
        negative_prompts=prompt_data["negative_prompts"],
        loras=[LoraSpec(model_id=char_lora.pixai_model_id, weight=char_weight)],
        media_id=sketch_media_id,
        strength=0.60,
        cfg_scale=6.5,
        sampling_steps=28,
        control_nets=[
            ControlNetSpec(type="openpose", media_id=sketch_media_id, weight=0.7),
            ControlNetSpec(type="depth", media_id=sketch_media_id, weight=0.5),
        ],
        priority=(1000 if high_priority else None),
        model_id=char_lora.base_model_id,
        quality_tag=None,
    )

    _log_assembled_request(
        run_id=run_id, stage=3, params_dict=params.to_pixai_dict(),
        extra={"architecture": char_lora.architecture},
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
    """Phase 2: delegates to `app.critique.engine.run_critique` so the
    reference-image resolution (sheet.referenceAnchors[0].path → Claude's
    second image block) and outfit-consistency schema live in one place.
    """
    critique = run_critique(
        image_path=image_path,
        sheet=sheet,
        scene_description=scene_description,
        anthropic_api_key=anthropic_api_key,
        manual_feedback=None,
    )
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "stage_4_critique.json").write_text(
            json.dumps(critique, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return critique
