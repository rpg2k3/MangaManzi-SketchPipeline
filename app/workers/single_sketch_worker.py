"""Background thread for single sketch regeneration (provider-configurable)."""

from pathlib import Path
from PySide6.QtCore import QThread, Signal

from app.api import claude_client, openai_client, gemini_client
from app.keyring_store import get_anthropic_key, get_openai_key, get_google_key
from app import settings_manager


class SingleSketchWorker(QThread):
    log = Signal(str)
    done = Signal(int, str, float)
    failed = Signal(int, str, str)

    def __init__(self, pose, character_json, character_sheet_path,
                 mannequin_dir, output_path):
        super().__init__()
        self.pose = pose
        self.character_json = character_json
        self.character_sheet_path = Path(character_sheet_path)
        self.mannequin_dir = Path(mannequin_dir)
        self.output_path = Path(output_path)

    def run(self):
        provider = settings_manager.get_sketch_provider()
        quality = settings_manager.get_openai_quality()
        anthropic_key = get_anthropic_key()
        image_key = get_openai_key() if provider == "openai" else get_google_key()

        if not anthropic_key or not image_key:
            self.failed.emit(self.pose["number"], self.output_path.name,
                             f"Anthropic + {provider.title()} keys required.")
            return

        character_id = self.character_json.get("character_id", "unknown")
        filename = self.output_path.name
        mannequin_path = self.mannequin_dir / self.pose["filename"]

        self.log.emit(f"[Manual] Regenerating sketch: {filename} via {provider.title()}...")

        # Step 1: Claude prompt assembly
        assembly = claude_client.assemble_pose_prompt(
            api_key=anthropic_key, character_json=self.character_json,
            pose_metadata=self.pose,
            mannequin_image_path=mannequin_path if mannequin_path.exists() else None)

        if not assembly["success"]:
            self.log.emit(f"[Manual] Prompt assembly failed: {assembly.get('error', '')}")
            self.failed.emit(self.pose["number"], filename, assembly.get("error", ""))
            return

        self.log.emit(f"[Manual] Prompt assembled ({len(assembly['prompt'])} chars)")

        # Step 2: Image generation
        if provider == "openai":
            result = openai_client.generate_sketch(
                api_key=image_key, prompt_text=assembly["prompt"],
                mannequin_image_path=mannequin_path,
                character_sheet_path=self.character_sheet_path,
                output_path=self.output_path,
                character_id=character_id, pose_id=filename, quality=quality)
        else:
            result = gemini_client.generate_sketch(
                api_key=image_key, prompt_text=assembly["prompt"],
                mannequin_image_path=mannequin_path,
                character_sheet_path=self.character_sheet_path,
                output_path=self.output_path,
                character_id=character_id, pose_id=filename)

        if result["success"]:
            cost = assembly["cost"] + result.get("cost", 0)
            self.log.emit(f"[Manual] OK: {filename} (${cost:.4f})")
            self.done.emit(self.pose["number"], filename, cost)
        else:
            self.log.emit(f"[Manual] FAILED: {result['error'][:150]}")
            self.failed.emit(self.pose["number"], filename, result["error"])
