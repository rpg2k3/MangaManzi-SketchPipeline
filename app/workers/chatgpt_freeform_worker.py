"""Background thread for the Sketch tab — Freeform mode.

Pipeline:
  1. Claude (claude-sonnet-4-20250514) expands the user's plain-English
     description into a complete gpt-image-1 line-art prompt.
  2. OpenAI gpt-image-1 renders it. If a character reference image is
     attached, uses images.edit so the character design can be matched;
     otherwise plain images.generate.
"""

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.api import chatgpt_freeform_engineer, chatgpt_image_client
from app.keyring_store import get_anthropic_key, get_openai_key
from app import settings_manager


class ChatGPTFreeformWorker(QThread):
    log = Signal(str)
    done = Signal(bytes, str, float)         # image_bytes, engineered prompt, total cost
    failed = Signal(str)                     # error message

    def __init__(self, description: str, orientation: str,
                 archetype: str, gender: str,
                 character_image_path: Path | None = None, parent=None):
        super().__init__(parent)
        self.description = description
        self.orientation = orientation
        self.archetype = archetype
        self.gender = gender
        self.character_image_path = (
            Path(character_image_path) if character_image_path else None
        )

    def run(self):
        anthropic_key = get_anthropic_key()
        openai_key = get_openai_key()
        if not anthropic_key:
            self.failed.emit("Anthropic API key not set. Configure in Settings tab.")
            return
        if not openai_key:
            self.failed.emit("OpenAI API key not set. Configure in Settings tab.")
            return

        has_ref = bool(self.character_image_path
                       and self.character_image_path.exists())

        self.log.emit(
            f"[Freeform] Asking Claude to engineer prompt "
            f"(A4 {self.orientation}, character_ref={'yes' if has_ref else 'no'}, "
            f"archetype={self.archetype}, gender={self.gender})...")
        engineered = chatgpt_freeform_engineer.build_freeform_prompt(
            api_key=anthropic_key,
            description=self.description,
            orientation=self.orientation,
            has_character_reference=has_ref,
            archetype=self.archetype,
            gender=self.gender,
        )
        if not engineered["success"]:
            self.log.emit(f"[Freeform] Prompt engineering failed: {engineered['error']}")
            self.failed.emit(engineered["error"])
            return

        prompt_text = engineered["prompt"]
        self.log.emit(
            f"[Freeform] Prompt ready ({len(prompt_text)} chars, "
            f"${engineered['cost']:.4f}). Calling gpt-image-1...")

        quality = settings_manager.get_openai_quality()
        result = chatgpt_image_client.generate_freeform(
            api_key=openai_key,
            prompt=prompt_text,
            orientation=self.orientation,
            character_image_path=self.character_image_path if has_ref else None,
            quality=quality,
        )

        if not result["success"]:
            self.log.emit(f"[Freeform] Image generation failed: {result['error']}")
            self.failed.emit(result["error"])
            return

        total = engineered["cost"] + result["cost"]
        self.log.emit(f"[Freeform] OK — {result['size']}, total ${total:.4f}")
        self.done.emit(result["image_bytes"], prompt_text, total)
