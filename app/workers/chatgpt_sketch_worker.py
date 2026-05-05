"""Background thread for the Chat_GPT Single sketch-over-base mode.

Pipeline: OpenAI gpt-image-1 image-edit using two reference images
(base mannequin + character sheet) with the line-art instruction.
"""

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.api import chatgpt_image_client
from app.keyring_store import get_openai_key
from app import settings_manager


class ChatGPTSketchWorker(QThread):
    log = Signal(str)
    done = Signal(bytes, float)              # image_bytes, cost
    failed = Signal(str)                     # error message

    def __init__(self, base_image_path: Path, character_image_path: Path,
                 orientation: str = "auto", parent=None):
        super().__init__(parent)
        self.base_image_path = Path(base_image_path)
        self.character_image_path = Path(character_image_path)
        self.orientation = orientation

    def run(self):
        openai_key = get_openai_key()
        if not openai_key:
            self.failed.emit("OpenAI API key not set. Configure in Settings tab.")
            return
        if not self.base_image_path.exists():
            self.failed.emit(f"Base image not found: {self.base_image_path}")
            return
        if not self.character_image_path.exists():
            self.failed.emit(f"Character image not found: {self.character_image_path}")
            return

        resolved = chatgpt_image_client.resolve_orientation(
            self.orientation, self.base_image_path)
        self.log.emit(
            f"[Sketch] Sending base + character to gpt-image-1 "
            f"(A4 {resolved}{' — auto-detected' if self.orientation == 'auto' else ''})...")

        quality = settings_manager.get_openai_quality()
        result = chatgpt_image_client.sketch_over_base(
            api_key=openai_key,
            base_image_path=self.base_image_path,
            character_image_path=self.character_image_path,
            orientation=self.orientation,
            quality=quality,
        )

        if not result["success"]:
            self.log.emit(f"[Sketch] Failed: {result['error']}")
            self.failed.emit(result["error"])
            return

        self.log.emit(f"[Sketch] OK — {result['size']}, ${result['cost']:.4f}")
        self.done.emit(result["image_bytes"], result["cost"])
