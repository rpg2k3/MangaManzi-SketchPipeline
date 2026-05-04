"""Background thread for the Chat_GPT base generator tab.

Pipeline: Claude (claude-sonnet-4-20250514) prompt assembly → OpenAI gpt-image-1 generate.
"""

from PySide6.QtCore import QThread, Signal

from app.api import chatgpt_prompt_engineer, chatgpt_image_client
from app.keyring_store import get_anthropic_key, get_openai_key
from app import settings_manager


class ChatGPTBaseWorker(QThread):
    log = Signal(str)
    done = Signal(bytes, str, float)         # image_bytes, prompt, total_cost
    failed = Signal(str)                     # error message

    def __init__(self, archetype: str, gender: str, view: str,
                 pose_description: str, orientation: str, parent=None):
        super().__init__(parent)
        self.archetype = archetype
        self.gender = gender
        self.view = view
        self.pose_description = pose_description
        self.orientation = orientation

    def run(self):
        anthropic_key = get_anthropic_key()
        openai_key = get_openai_key()
        if not anthropic_key:
            self.failed.emit("Anthropic API key not set. Configure in Settings tab.")
            return
        if not openai_key:
            self.failed.emit("OpenAI API key not set. Configure in Settings tab.")
            return

        self.log.emit(f"[Base] Asking Claude to engineer prompt "
                      f"({self.gender} {self.archetype} / {self.view})...")
        engineered = chatgpt_prompt_engineer.build_base_prompt(
            api_key=anthropic_key,
            archetype=self.archetype,
            gender=self.gender,
            view=self.view,
            pose_description=self.pose_description,
        )
        if not engineered["success"]:
            self.log.emit(f"[Base] Prompt engineering failed: {engineered['error']}")
            self.failed.emit(engineered["error"])
            return

        prompt_text = engineered["prompt"]
        self.log.emit(f"[Base] Prompt ready ({len(prompt_text)} chars, "
                      f"${engineered['cost']:.4f}). Calling gpt-image-1...")

        # If user picked auto, let the engineered prompt's own choice win
        orientation = self.orientation
        if orientation == "auto":
            orientation = "landscape" if "landscape" in prompt_text.lower() else "portrait"

        quality = settings_manager.get_openai_quality()
        result = chatgpt_image_client.generate_base(
            api_key=openai_key,
            prompt=prompt_text,
            orientation=orientation,
            quality=quality,
        )

        if not result["success"]:
            self.log.emit(f"[Base] Image generation failed: {result['error']}")
            self.failed.emit(result["error"])
            return

        total = engineered["cost"] + result["cost"]
        self.log.emit(f"[Base] OK — {result['size']} ({orientation}), total ${total:.4f}")
        self.done.emit(result["image_bytes"], prompt_text, total)
