"""Background thread for sketch overlay generation (provider-configurable)."""

from pathlib import Path
from PySide6.QtCore import QThread, Signal

from app.api import claude_client, openai_client, gemini_client
from app.keyring_store import get_anthropic_key, get_openai_key, get_google_key
from app import settings_manager


class SketchWorker(QThread):
    log = Signal(str)
    pose_done = Signal(int, str, float)
    pose_failed = Signal(int, str, str)
    progress = Signal(int, int)
    finished_batch = Signal(int, int)

    def __init__(self, poses, character_json, character_sheet_path,
                 mannequin_dir, output_dir):
        super().__init__()
        self.poses = poses
        self.character_json = character_json
        self.character_sheet_path = Path(character_sheet_path)
        self.mannequin_dir = Path(mannequin_dir)
        self.output_dir = Path(output_dir)
        self._stop = False
        self._paused = False

    def request_stop(self):
        self._stop = True

    def set_paused(self, paused):
        self._paused = paused

    def run(self):
        anthropic_key = get_anthropic_key()
        provider = settings_manager.get_sketch_provider()
        quality = settings_manager.get_openai_quality()

        if provider == "openai":
            image_key = get_openai_key()
        else:
            image_key = get_google_key()

        if not anthropic_key or not image_key:
            self.log.emit(f"ERROR: Anthropic + {provider.title()} API keys required.")
            self.finished_batch.emit(0, len(self.poses))
            return

        total = len(self.poses)
        success = 0
        failed = 0
        character_id = self.character_json.get("character_id", "unknown")

        for i, pose in enumerate(self.poses):
            if self._stop:
                self.log.emit("Batch cancelled.")
                break

            while self._paused and not self._stop:
                self.msleep(300)

            self.progress.emit(i, total)
            mannequin_filename = pose["filename"]
            sketch_filename = f"{character_id}_{mannequin_filename}"
            output_path = self.output_dir / sketch_filename
            mannequin_path = self.mannequin_dir / mannequin_filename
            filename = sketch_filename

            if output_path.exists():
                self.log.emit(f"  [{i+1}/{total}] {filename} — exists, skipping")
                success += 1
                self.pose_done.emit(pose["number"], filename, 0)
                continue

            self.log.emit(f"  [{i+1}/{total}] Assembling prompt for {filename}...")

            assembly_result = claude_client.assemble_pose_prompt(
                api_key=anthropic_key, character_json=self.character_json,
                pose_metadata=pose,
                mannequin_image_path=mannequin_path if mannequin_path.exists() else None)

            if not assembly_result["success"]:
                self.log.emit(f"    Prompt assembly failed: {assembly_result.get('error', '')}")
                failed += 1
                self.pose_failed.emit(pose["number"], filename, assembly_result.get("error", ""))
                continue

            prompt_text = assembly_result["prompt"]
            self.log.emit(f"    Prompt assembled ({len(prompt_text)} chars, ${assembly_result['cost']:.4f})")
            self.log.emit(f"    [Batch] Generating sketch via {provider.title()}...")

            if provider == "openai":
                gen_result = openai_client.generate_sketch(
                    api_key=image_key, prompt_text=prompt_text,
                    mannequin_image_path=mannequin_path,
                    character_sheet_path=self.character_sheet_path,
                    output_path=output_path,
                    character_id=character_id, pose_id=filename, quality=quality)
            else:
                gen_result = gemini_client.generate_sketch(
                    api_key=image_key, prompt_text=prompt_text,
                    mannequin_image_path=mannequin_path,
                    character_sheet_path=self.character_sheet_path,
                    output_path=output_path,
                    character_id=character_id, pose_id=filename)

            if gen_result["success"]:
                total_cost = assembly_result["cost"] + gen_result.get("cost", 0)
                self.log.emit(f"    OK (${total_cost:.4f})")
                success += 1
                self.pose_done.emit(pose["number"], filename, total_cost)
            else:
                self.log.emit(f"    FAILED: {gen_result['error'][:150]}")
                failed += 1
                self.pose_failed.emit(pose["number"], filename, gen_result["error"])

        self.progress.emit(total, total)
        self.finished_batch.emit(success, failed)
