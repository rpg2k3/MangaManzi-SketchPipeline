"""Folder-batch worker for the Chat_GPT sketch tab.

Iterates every base-mannequin image in a chosen folder and overlays the
same single character reference onto each one. Mirrors the base batch
worker's pause/resume/cancel/per-item retry pattern.

The archetype + gender selected in the UI are baked into the gpt-image-1
instruction so the character drawing conforms to the head-count and
proportion rules of the underlying base.
"""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.api import chatgpt_image_client
from app.api.chatgpt_prompt_engineer import build_sketch_instruction
from app.keyring_store import get_openai_key
from app import settings_manager

# Image extensions we treat as base-mannequin candidates in the folder.
SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def list_base_files(base_dir: Path) -> list[Path]:
    """Return sorted list of base-image candidate files in the folder."""
    if not base_dir or not Path(base_dir).is_dir():
        return []
    return sorted(
        p for p in Path(base_dir).iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    )


def output_filename_for(base_path: Path, timestamp: str) -> str:
    """Output filename for one batch run.
    Format: sketch_[base_stem]_[timestamp].png — deterministic within a run
    so skip-if-exists and retry can both look the file up by name."""
    return f"sketch_{base_path.stem}_{timestamp}.png"


class ChatGPTSketchBatchWorker(QThread):
    log = Signal(str)
    item_started = Signal(str)                  # base filename
    item_done = Signal(str, float)              # base filename, cost
    item_failed = Signal(str, str, str)         # base filename, base path, error
    progress = Signal(int, int)                 # current, total
    finished_batch = Signal(int, int, float)    # success, failed, total_cost

    def __init__(self, base_dir: Path, character_image_path: Path,
                 orientation: str, output_dir: Path,
                 archetype: str, gender: str, parent=None):
        super().__init__(parent)
        self.base_dir = Path(base_dir)
        self.character_image_path = Path(character_image_path)
        self.orientation = orientation
        self.output_dir = Path(output_dir)
        self.archetype = archetype
        self.gender = gender
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._stop = False
        self._paused = False

    def request_stop(self):
        self._stop = True

    def set_paused(self, paused: bool):
        self._paused = paused

    def run(self):
        openai_key = get_openai_key()
        if not openai_key:
            self.log.emit("ERROR: OpenAI API key not set.")
            self.finished_batch.emit(0, 0, 0.0)
            return
        if not self.character_image_path.exists():
            self.log.emit(f"ERROR: character reference not found: "
                          f"{self.character_image_path}")
            self.finished_batch.emit(0, 0, 0.0)
            return

        bases = list_base_files(self.base_dir)
        total = len(bases)
        if total == 0:
            self.log.emit(f"No base images found in: {self.base_dir}")
            self.finished_batch.emit(0, 0, 0.0)
            return

        self.output_dir.mkdir(parents=True, exist_ok=True)
        quality = settings_manager.get_openai_quality()
        success = 0
        failed = 0
        total_cost = 0.0

        self.log.emit(
            f"[Batch] Starting — {total} base file(s), character "
            f"{self.character_image_path.name}, orientation={self.orientation}, "
            f"archetype={self.archetype}, gender={self.gender}, q={quality}, "
            f"timestamp={self.timestamp}")

        for i, base in enumerate(bases):
            if self._stop:
                self.log.emit("Batch cancelled.")
                break
            while self._paused and not self._stop:
                self.msleep(300)
            if self._stop:
                self.log.emit("Batch cancelled.")
                break

            self.progress.emit(i, total)
            out_name = output_filename_for(base, self.timestamp)
            output_path = self.output_dir / out_name
            self.item_started.emit(base.name)

            if output_path.exists():
                self.log.emit(f"  [{i+1}/{total}] {base.name} → {out_name} — exists, skipping")
                success += 1
                self.item_done.emit(base.name, 0.0)
                continue

            resolved = chatgpt_image_client.resolve_orientation(
                self.orientation, base)
            instruction = build_sketch_instruction(
                self.archetype, self.gender, resolved)
            self.log.emit(
                f"  [{i+1}/{total}] {base.name} — A4 {resolved}"
                f"{' (auto)' if self.orientation == 'auto' else ''}")

            result = chatgpt_image_client.sketch_over_base(
                api_key=openai_key,
                base_image_path=base,
                character_image_path=self.character_image_path,
                orientation=resolved,
                quality=quality,
                instruction=instruction,
            )
            if not result["success"]:
                err = result["error"]
                self.log.emit(f"    failed: {err[:160]}")
                failed += 1
                self.item_failed.emit(base.name, str(base), err)
                continue

            output_path.write_bytes(result["image_bytes"])
            cost = result["cost"]
            total_cost += cost
            success += 1
            self.log.emit(
                f"    OK → {output_path.name} (${cost:.4f}; running ${total_cost:.4f})")
            self.item_done.emit(base.name, cost)

        self.progress.emit(total, total)
        self.log.emit(f"[Batch] saved to {self.output_dir}")
        self.finished_batch.emit(success, failed, total_cost)
