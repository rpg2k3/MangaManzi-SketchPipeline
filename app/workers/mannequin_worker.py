"""Background thread for mannequin base generation (Claude prompt assembly + provider-configurable image gen)."""

from pathlib import Path
from PySide6.QtCore import QThread, Signal

from app.api import openai_client, gemini_client, prompt_assembler
from app.keyring_store import get_openai_key, get_google_key
from app import settings_manager
from app.archetype_scanner import get_dual_references


class MannequinWorker(QThread):
    log = Signal(str)
    pose_done = Signal(int, str, float)
    pose_failed = Signal(int, str, str)
    progress = Signal(int, int)
    finished_batch = Signal(int, int)

    def __init__(self, poses, archetype, output_dir):
        super().__init__()
        self.poses = poses
        self.archetype = archetype  # dict from archetype_scanner
        self.output_dir = Path(output_dir)
        self._stop = False
        self._paused = False

    def request_stop(self):
        self._stop = True

    def set_paused(self, paused):
        self._paused = paused

    def run(self):
        provider = settings_manager.get_mannequin_provider()
        quality = settings_manager.get_openai_quality()
        quality_tag = settings_manager.get("mannequin_quality_tag") or ""

        if provider == "openai":
            api_key = get_openai_key()
        else:
            api_key = get_google_key()
        if not api_key:
            self.log.emit(f"ERROR: {provider.title()} API key not set.")
            self.finished_batch.emit(0, len(self.poses))
            return

        total = len(self.poses)
        success = 0
        failed = 0

        for i, pose in enumerate(self.poses):
            if self._stop:
                self.log.emit("Batch cancelled.")
                break

            while self._paused and not self._stop:
                self.msleep(300)

            self.progress.emit(i, total)
            filename = pose["filename"]
            output_path = self.output_dir / filename

            if output_path.exists():
                self.log.emit(f"  [{i+1}/{total}] {filename} — exists, skipping")
                success += 1
                self.pose_done.emit(pose["number"], filename, 0)
                continue

            # Step 1: Claude assembles the prompt with reference images
            self.log.emit(f"  [{i+1}/{total}] [Batch] Assembling prompt for {filename}...")
            assembly = prompt_assembler.assemble_mannequin_prompt(
                archetype=self.archetype,
                pose_metadata=pose,
                quality_tag=quality_tag,
                log_fn=lambda msg: self.log.emit(msg),
            )
            if not assembly["success"]:
                self.log.emit(f"    Prompt assembly failed: {assembly.get('error', '')}")
                failed += 1
                self.pose_failed.emit(pose["number"], filename, assembly.get("error", ""))
                continue

            prompt_text = assembly["prompt"]
            self.log.emit(f"    Prompt: {len(prompt_text)} chars (${assembly['cost']:.4f})")

            # Step 2: Image generation with references
            view = pose.get("view", "front")
            csp_ref, gpt_ref = get_dual_references(self.archetype, view)
            dual_mode = settings_manager.get("dual_reference_mode")
            if dual_mode:
                ref_images = [r for r in [csp_ref, gpt_ref] if r]
                ref_label = f"dual (CSP+GPT)"
            else:
                ref_images = [gpt_ref] if gpt_ref else ([csp_ref] if csp_ref else [])
                ref_label = "single (GPT style)"
            self.log.emit(f"    Generating via {provider.title()} (refs: {ref_label})...")

            if provider == "openai":
                result = openai_client.generate_mannequin(
                    api_key=api_key, pose_metadata=pose,
                    archetype_info=self.archetype, output_path=output_path,
                    reference_images=ref_images, quality=quality,
                    prompt_override=prompt_text)
            else:
                result = gemini_client.generate_mannequin(
                    api_key=api_key, pose_metadata=pose,
                    archetype_info=self.archetype, output_path=output_path,
                    reference_images=ref_images)

            if result["success"]:
                total_cost = assembly["cost"] + result.get("cost", 0)
                self.log.emit(f"    OK (${total_cost:.4f})")
                success += 1
                self.pose_done.emit(pose["number"], filename, total_cost)
            else:
                self.log.emit(f"    FAILED: {result['error'][:150]}")
                failed += 1
                self.pose_failed.emit(pose["number"], filename, result["error"])

        self.progress.emit(total, total)
        self.finished_batch.emit(success, failed)
