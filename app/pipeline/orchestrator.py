"""Sequential pipeline runner: skeleton → base → sketch → character → critique."""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app import sheets as sheets_pkg
from app.keyring_store import get_anthropic_key, get_pixai_key
from app.pixai import PixAIClient

from .errors import PipelineError
from .stages import (
    StageResult,
    stage_1_base_mannequin,
    stage_2_sketch_pass,
    stage_3_character_finalization,
    stage_4_critique,
)

OUTPUTS_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "outputs"


@dataclass
class PipelineRequest:
    scene_description: str = ""
    sheet_id: str | None = None         # Required for Stage 3+
    archetype: str | None = None        # Used for sheetless Stage 1 / Stage 2 runs
    skeleton_path: Path | None = None   # Optional — only used to pose-lock Stage 1
    depth_path: Path | None = None      # Optional — only used to pose-lock Stage 1
    view: str = "front"
    pose: str | None = None
    high_priority: bool = False
    seed: int | None = None             # Optional — pin for reproducible runs
    prior_critiques: list[dict] | None = None
    scene_id: str | None = None
    max_stage: int = 4  # 1, 2, 3, or 4 — stop after this stage


@dataclass
class PipelineResult:
    base: StageResult | None = None
    sketch: StageResult | None = None
    character: StageResult | None = None
    critique: dict | None = None
    output_dir: Path | None = None
    scene_id: str | None = None


_SAFE_CHARS = re.compile(r"[^a-z0-9_]+")


def _slug(s: str) -> str:
    return _SAFE_CHARS.sub("_", s.lower()).strip("_") or "scene"


def _resolve_scene_id(req: PipelineRequest) -> str:
    if req.scene_id:
        return req.scene_id
    base = _slug(req.scene_description[:40])
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base}_{stamp}"


def run_pipeline(
    req: PipelineRequest,
    *,
    pixai_api_key: str | None = None,
    anthropic_api_key: str | None = None,
    outputs_root: Path | None = None,
) -> PipelineResult:
    pixai_key = pixai_api_key or get_pixai_key()
    anthropic_key = anthropic_api_key or get_anthropic_key()
    if not pixai_key:
        raise PipelineError("PixAI key not set (run onboarding or set PIXAI_API_KEY).")
    if not anthropic_key and req.max_stage >= 3:
        raise PipelineError("Anthropic key not set (required for Stage 3+).")

    sheet = None
    archetype = None
    if req.sheet_id:
        if not sheets_pkg.exists(req.sheet_id):
            raise PipelineError(f"Sheet '{req.sheet_id}' not found in data/sheets/")
        sheet = sheets_pkg.load(req.sheet_id)
        archetype = sheet.get("archetype")
    elif req.archetype:
        archetype = req.archetype
    else:
        raise PipelineError("PipelineRequest needs either sheet_id or archetype.")
    if not archetype:
        raise PipelineError("Could not resolve archetype (sheet missing 'archetype' field?).")
    if req.max_stage >= 3 and sheet is None:
        raise PipelineError("Stages 3+ require a character sheet (linkedLoraId resolution).")

    scene_id = _resolve_scene_id(req)
    subject_dir = req.sheet_id or f"_archetype_{archetype}"
    out_dir = (outputs_root or OUTPUTS_ROOT) / subject_dir / scene_id
    out_dir.mkdir(parents=True, exist_ok=True)

    pose = req.pose or "contrapposto_classic"
    s1 = s2 = s3 = None
    crit = None
    with PixAIClient(api_key=pixai_key) as client:
        s1 = stage_1_base_mannequin(
            pixai_client=client,
            archetype=archetype,
            view=req.view,
            pose=pose,
            skeleton_path=req.skeleton_path,
            depth_path=req.depth_path,
            output_dir=out_dir,
            high_priority=req.high_priority,
            seed=req.seed,
        )
        if req.max_stage >= 2:
            s2 = stage_2_sketch_pass(
                pixai_client=client,
                base_media_id=s1.media_id,
                output_dir=out_dir,
                high_priority=req.high_priority,
            )
        if req.max_stage >= 3:
            s3 = stage_3_character_finalization(
                pixai_client=client,
                sketch_media_id=s2.media_id,
                sheet=sheet,
                scene_description=req.scene_description,
                anthropic_api_key=anthropic_key,
                output_dir=out_dir,
                view=req.view,
                pose=pose,
                prior_critiques=req.prior_critiques,
                high_priority=req.high_priority,
            )

    if req.max_stage >= 4 and s3 is not None:
        crit = stage_4_critique(
            image_path=s3.output_image_path,
            sheet=sheet,
            scene_description=req.scene_description,
            anthropic_api_key=anthropic_key,
            output_dir=out_dir,
        )

    return PipelineResult(
        base=s1, sketch=s2, character=s3,
        critique=crit, output_dir=out_dir, scene_id=scene_id,
    )
