"""Background thread for single mannequin regeneration (Claude prompt + provider-configurable)."""

from pathlib import Path
from PySide6.QtCore import QThread, Signal

from app.api import openai_client, gemini_client, prompt_assembler
from app.keyring_store import get_openai_key, get_google_key
from app import settings_manager
from app.archetype_scanner import get_dual_references


class SingleMannequinWorker(QThread):
    log = Signal(str)
    done = Signal(int, str, float)
    failed = Signal(int, str, str)

    def __init__(self, pose, archetype, output_dir):
        super().__init__()
        self.pose = pose
        self.archetype = archetype
        self.output_dir = Path(output_dir)

    def run(self):
        provider = settings_manager.get_mannequin_provider()
        quality = settings_manager.get_openai_quality()
        quality_tag = settings_manager.get("mannequin_quality_tag") or ""

        if provider == "openai":
            api_key = get_openai_key()
        else:
            api_key = get_google_key()
        if not api_key:
            self.failed.emit(self.pose["number"], self.pose["filename"],
                             f"{provider.title()} API key not set.")
            return

        filename = self.pose["filename"]
        output_path = self.output_dir / filename

        # Step 1: Claude prompt assembly
        self.log.emit(f"[Manual] Assembling prompt for #{self.pose['number']}: {filename}...")
        assembly = prompt_assembler.assemble_mannequin_prompt(
            archetype=self.archetype,
            pose_metadata=self.pose,
            quality_tag=quality_tag,
            log_fn=lambda msg: self.log.emit(msg),
        )
        if not assembly["success"]:
            self.log.emit(f"[Manual] Prompt failed: {assembly.get('error', '')}")
            self.failed.emit(self.pose["number"], filename, assembly.get("error", ""))
            return

        prompt_text = assembly["prompt"]
        self.log.emit(f"[Manual] Prompt: {len(prompt_text)} chars")

        # Step 2: Image generation with references
        view = self.pose.get("view", "front")
        csp_ref, gpt_ref = get_dual_references(self.archetype, view)
        dual_mode = settings_manager.get("dual_reference_mode")
        if dual_mode:
            ref_images = [r for r in [csp_ref, gpt_ref] if r]
            ref_label = "dual (CSP+GPT)"
        else:
            ref_images = [gpt_ref] if gpt_ref else ([csp_ref] if csp_ref else [])
            ref_label = "single (GPT style)"
        self.log.emit(f"[Manual] Generating via {provider.title()} (refs: {ref_label})...")

        if provider == "openai":
            result = openai_client.generate_mannequin(
                api_key=api_key, pose_metadata=self.pose,
                archetype_info=self.archetype, output_path=output_path,
                reference_images=ref_images, quality=quality,
                prompt_override=prompt_text)
        else:
            result = gemini_client.generate_mannequin(
                api_key=api_key, pose_metadata=self.pose,
                archetype_info=self.archetype, output_path=output_path,
                reference_images=ref_images)

        if result["success"]:
            cost = assembly["cost"] + result.get("cost", 0)
            self.log.emit(f"[Manual] OK: {filename} (${cost:.4f})")
            self.done.emit(self.pose["number"], filename, cost)
        else:
            self.log.emit(f"[Manual] FAILED: {result['error'][:150]}")
            self.failed.emit(self.pose["number"], filename, result["error"])
