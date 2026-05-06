"""Pipeline orchestration.

  Stage 1 — base mannequin   (PixAI txt2img + 9k9base + ControlNet)
  Stage 2 — sketch pass      (PixAI img2img + sketch_lora)
  Stage 3 — character        (PixAI img2img + character LoRA from sheet)
  Stage 4 — critique         (Claude review)
Each stage is independently callable from app.pipeline.stages.
"""

from .errors import PipelineError, StageError
from .orchestrator import OUTPUTS_ROOT, PipelineRequest, PipelineResult, run_pipeline
from .stages import (
    StageResult,
    stage_1_base_mannequin,
    stage_2_sketch_pass,
    stage_3_character_finalization,
    stage_4_critique,
)

__all__ = [
    "OUTPUTS_ROOT",
    "PipelineRequest",
    "PipelineResult",
    "PipelineError",
    "StageError",
    "StageResult",
    "run_pipeline",
    "stage_1_base_mannequin",
    "stage_2_sketch_pass",
    "stage_3_character_finalization",
    "stage_4_critique",
]
