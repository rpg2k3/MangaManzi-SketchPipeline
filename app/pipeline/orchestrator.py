"""Sequential pipeline runner: skeleton → base → sketch → character → critique.

Phase 2 adds the auto-regenerate loop. After the initial S1→S4 run, if
the critique surfaces drifts at or above `drift_severity_threshold` and
iterations remain, Stage 3 is re-rolled with prior critiques bundled so
Claude composes a corrected positive prompt. Each re-roll iteration:
- Re-uses the same Stage 1 base + Stage 2 sketch (no re-rendering — those
  are pose-locked and stable)
- Saves to a sibling run dir runs/<scene_id>/iter_<n>/ for the assembled
  request manifests Phase 3 will write there
- Appends to history (`app.critique.history`)
- Triggers `promote_consecutive_drifts` so a stubborn drift bubbles into
  `sheet.learnedDrifts` for future scenes.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app import sheets as sheets_pkg
from app.critique import (
    append_iteration,
    promote_consecutive_drifts,
)
from app.critique.regenerate import compose_corrected_prompt
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
RUNS_ROOT = Path(__file__).resolve().parent.parent.parent / "runs"

# Severity ladder — used by the auto-regen loop. "high" is the user-facing
# alias for the schema's "major" enum value (the critique tool emits
# minor/moderate/major; PipelineRequest takes the friendlier "high").
_SEVERITY_RANK = {"minor": 1, "moderate": 2, "major": 3}
_SEVERITY_ALIASES = {
    "low": "minor",
    "minor": "minor",
    "med": "moderate",
    "medium": "moderate",
    "moderate": "moderate",
    "high": "major",
    "major": "major",
}


def _normalize_severity(s: str) -> str:
    return _SEVERITY_ALIASES.get((s or "").strip().lower(), "major")


def _has_drifts_at_or_above(critique: dict | None, threshold: str) -> bool:
    if not critique:
        return False
    floor = _SEVERITY_RANK[_normalize_severity(threshold)]
    for d in critique.get("drifts") or []:
        sev = _normalize_severity(d.get("severity", ""))
        if _SEVERITY_RANK.get(sev, 0) >= floor:
            return True
    return False


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
    # Phase 2 auto-regenerate loop:
    max_iterations: int = 3             # 1 = original behavior (no auto re-roll)
    drift_severity_threshold: str = "high"  # "minor" | "moderate" | "major" / "high"


@dataclass
class PipelineResult:
    base: StageResult | None = None
    sketch: StageResult | None = None
    character: StageResult | None = None
    critique: dict | None = None
    output_dir: Path | None = None
    scene_id: str | None = None
    # Phase 2 auto-regen iterations beyond the initial run.
    # Empty when max_iterations <= 1 or the critique was clean on first try.
    iterations: list[dict] = field(default_factory=list)
    promoted_drifts: list[dict] = field(default_factory=list)


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
    iterations: list[dict] = []
    promoted_drifts: list[dict] = []

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
            # Phase 2: append the initial run to per-scene history so the
            # consecutive-drift promotion + auto-regen loop have a record
            # to read from.
            if req.sheet_id and sheet is not None:
                append_iteration(
                    sheet_id=req.sheet_id,
                    scene_id=scene_id,
                    prompt={"iter": 1, "scene_id": scene_id},
                    critique=crit,
                    output_path=str(s3.output_image_path),
                )

            # Phase 2: auto-regenerate loop. Re-roll Stage 3 (S1+S2 are
            # pose-locked and stable; only S3 produces character-detail
            # drift). Each re-roll uses prior critiques to compose a
            # corrected positive prompt.
            if (req.max_iterations > 1
                    and req.sheet_id
                    and sheet is not None):
                for n in range(2, req.max_iterations + 1):
                    if not _has_drifts_at_or_above(
                        crit, req.drift_severity_threshold
                    ):
                        break

                    iter_out_dir = out_dir / f"iter_{n}"
                    iter_out_dir.mkdir(parents=True, exist_ok=True)

                    bundle = _build_prior_critiques_bundle(
                        sheet_id=req.sheet_id,
                        scene_id=scene_id,
                        n=req.max_iterations,
                    )

                    s3 = stage_3_character_finalization(
                        pixai_client=client,
                        sketch_media_id=s2.media_id,
                        sheet=sheet,
                        scene_description=req.scene_description,
                        anthropic_api_key=anthropic_key,
                        output_dir=iter_out_dir,
                        view=req.view,
                        pose=pose,
                        prior_critiques=bundle,
                        high_priority=req.high_priority,
                    )
                    crit = stage_4_critique(
                        image_path=s3.output_image_path,
                        sheet=sheet,
                        scene_description=req.scene_description,
                        anthropic_api_key=anthropic_key,
                        output_dir=iter_out_dir,
                    )
                    append_iteration(
                        sheet_id=req.sheet_id,
                        scene_id=scene_id,
                        prompt={"iter": n, "scene_id": scene_id},
                        critique=crit,
                        output_path=str(s3.output_image_path),
                    )
                    iterations.append({
                        "iter": n,
                        "media_id": s3.media_id,
                        "output_image_path": str(s3.output_image_path),
                        "critique": crit,
                    })

                # Phase 2.2: after the loop, promote any drift that
                # persisted across `max_iterations` consecutive iterations
                # of this scene into sheet.learnedDrifts.
                if req.sheet_id and iterations:
                    run_ids = [scene_id] + [
                        f"{scene_id}_iter_{i['iter']}" for i in iterations
                    ]
                    promoted_drifts = promote_consecutive_drifts(
                        req.sheet_id,
                        scene_id,
                        threshold=req.max_iterations,
                        source_run_ids=run_ids,
                    )

    return PipelineResult(
        base=s1, sketch=s2, character=s3,
        critique=crit, output_dir=out_dir, scene_id=scene_id,
        iterations=iterations, promoted_drifts=promoted_drifts,
    )


def _build_prior_critiques_bundle(*, sheet_id: str, scene_id: str, n: int) -> list[dict]:
    """Pull the last `n` iteration critiques from history, formatted for
    `app.claude.prompts.generate_prompt(prior_critiques=...)`.
    """
    from app.critique import recent_iterations
    out: list[dict] = []
    for it in recent_iterations(sheet_id, scene_id, n=n):
        crit = it.get("critique") or {}
        out.append({
            "iteration_index": it.get("iteration_index"),
            "drifts": crit.get("drifts", []),
            "successes": crit.get("successes", []),
            "suggestedPromptDeltas": crit.get("suggestedPromptDeltas", []),
            "outfit_consistency": crit.get("outfit_consistency"),
        })
    return out
