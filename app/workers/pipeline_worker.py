"""QThread that runs the pipeline so the UI doesn't freeze.

Each completed stage's full request payload (the JSON we sent to PixAI
including positive prompt, negative prompt, LoRA stack, sampling params,
and ControlNets) is emitted to the log signal so the Generate-tab Log
panel shows exactly what was sent. On success, an iteration record is
appended to data/history/<sheet_id>/<scene_id>.jsonl.
"""

import json

from PySide6.QtCore import QThread, Signal

from app.critique.history import append_iteration
from app.pipeline import PipelineRequest, PipelineResult, run_pipeline


class PipelineWorker(QThread):
    log = Signal(str)
    done = Signal(object)  # PipelineResult
    failed = Signal(str)

    def __init__(self, request: PipelineRequest, manual_feedback: str | None = None):
        super().__init__()
        self.request = request
        self.manual_feedback = manual_feedback

    def run(self):
        sheet_or_arch = self.request.sheet_id or f"archetype={self.request.archetype}"
        self.log.emit(
            f"Starting pipeline (stages 1–{self.request.max_stage}) for {sheet_or_arch}…"
        )
        try:
            result: PipelineResult = run_pipeline(self.request)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.log.emit(f"--- Pipeline crashed ---\n{tb}")
            self.failed.emit(f"{type(e).__name__}: {e}")
            return

        for r in (result.base, result.sketch, result.character):
            if r is None or r.task is None:
                continue
            params = r.task.get("parameters") or {}
            self.log.emit(f"--- Stage {r.stage} request payload ---")
            self.log.emit(json.dumps(params, indent=2, ensure_ascii=False))

        if result.character is not None and result.critique is not None and self.request.sheet_id:
            params = (result.character.task or {}).get("parameters") or {}
            try:
                append_iteration(
                    self.request.sheet_id,
                    result.scene_id or "scene",
                    prompt={
                        "prompts": params.get("prompts"),
                        "negative_prompts": params.get("negativePrompts"),
                    },
                    critique=result.critique,
                    output_path=str(result.character.output_image_path),
                    manual_feedback=self.manual_feedback,
                )
                self.log.emit("Iteration saved to scene history.")
            except Exception as e:
                self.log.emit(f"(History append failed: {e})")

        msg_bits = []
        if result.base: msg_bits.append("Stage 1 ✓")
        if result.sketch: msg_bits.append("Stage 2 ✓")
        if result.character: msg_bits.append("Stage 3 ✓")
        if result.critique: msg_bits.append("Stage 4 ✓")
        self.log.emit("Pipeline done — " + ", ".join(msg_bits))
        self.done.emit(result)
