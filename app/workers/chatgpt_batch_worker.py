"""Batch generation worker for the Chat_GPT base generator tab.

Iterates the cartesian product of selected views × selected poses for one
archetype. For each combination: Claude prompt assembly → OpenAI image gen
→ save with 9LivesK9-style filename. Supports stop / pause / resume.
"""

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.api import chatgpt_prompt_engineer, chatgpt_image_client, chatgpt_pose_taxonomy
from app.keyring_store import get_anthropic_key, get_openai_key
from app import settings_manager


def filename_for(archetype: str, gender: str, view: str, pose_slug: str,
                 index: int = 1) -> str:
    """9LivesK9-style filename: <gender-prefix>_<archetype>_<view-slug>_<pose>_<NN>.png

    e.g. F_adult_front_contrapposto_classic_01.png (female)
         M_adult_front_contrapposto_classic_01.png (male)
    """
    view_slug = chatgpt_prompt_engineer.VIEW_LIBRARY_SLUGS.get(view, view)
    prefix = chatgpt_prompt_engineer.GENDERS.get(
        gender, {"filename_prefix": "X"})["filename_prefix"]
    return f"{prefix}_{archetype}_{view_slug}_{pose_slug}_{index:02d}.png"


class ChatGPTBatchWorker(QThread):
    log = Signal(str)
    item_started = Signal(str)                      # filename
    item_done = Signal(str, float)                  # filename, cost
    item_failed = Signal(str, str, str, str)        # filename, view, pose_slug, error
    progress = Signal(int, int)                     # current, total
    finished_batch = Signal(int, int, float)        # success, failed, total_cost

    def __init__(self, archetype: str, gender: str, views: list[str],
                 poses: list[dict], output_dir: Path, parent=None):
        """`poses` is a list of {"pose", "category", "description"} dicts."""
        super().__init__(parent)
        self.archetype = archetype
        self.gender = gender
        self.views = list(views)
        self.poses = list(poses)
        self.output_dir = Path(output_dir)
        self._stop = False
        self._paused = False

    def request_stop(self):
        self._stop = True

    def set_paused(self, paused: bool):
        self._paused = paused

    def run(self):
        anthropic_key = get_anthropic_key()
        openai_key = get_openai_key()
        if not anthropic_key:
            self.log.emit("ERROR: Anthropic API key not set.")
            self.finished_batch.emit(0, 0, 0.0)
            return
        if not openai_key:
            self.log.emit("ERROR: OpenAI API key not set.")
            self.finished_batch.emit(0, 0, 0.0)
            return

        quality = settings_manager.get_openai_quality()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        items = [(v, p) for v in self.views for p in self.poses]
        total = len(items)
        success = 0
        failed = 0
        total_cost = 0.0

        for i, (view, pose) in enumerate(items):
            if self._stop:
                self.log.emit("Batch cancelled.")
                break
            while self._paused and not self._stop:
                self.msleep(300)
            if self._stop:
                self.log.emit("Batch cancelled.")
                break

            self.progress.emit(i, total)
            pose_slug = pose["pose"]
            filename = filename_for(self.archetype, self.gender, view, pose_slug)
            output_path = self.output_dir / filename
            self.item_started.emit(filename)

            if output_path.exists():
                self.log.emit(f"  [{i+1}/{total}] {filename} — exists, skipping")
                success += 1
                self.item_done.emit(filename, 0.0)
                continue

            view_lib_slug = chatgpt_prompt_engineer.VIEW_LIBRARY_SLUGS.get(view, view)
            description = (
                chatgpt_pose_taxonomy.lookup_description(pose_slug, view_lib_slug)
                or pose.get("description")
                or pose_slug.replace("_", " ")
            )

            self.log.emit(f"  [{i+1}/{total}] {filename} — Claude...")
            engineered = chatgpt_prompt_engineer.build_base_prompt(
                api_key=anthropic_key,
                archetype=self.archetype,
                gender=self.gender,
                view=view,
                pose_description=description,
            )
            if not engineered["success"]:
                err = engineered["error"]
                self.log.emit(f"    prompt failed: {err}")
                failed += 1
                self.item_failed.emit(filename, view, pose_slug, err)
                continue

            prompt_text = engineered["prompt"]
            orientation = "landscape" if "landscape" in prompt_text.lower() else "portrait"

            self.log.emit(f"    Generating gpt-image-1 ({orientation}, q={quality})...")
            result = chatgpt_image_client.generate_base(
                api_key=openai_key, prompt=prompt_text,
                orientation=orientation, quality=quality,
            )
            if not result["success"]:
                err = result["error"]
                self.log.emit(f"    image failed: {err[:160]}")
                failed += 1
                self.item_failed.emit(filename, view, pose_slug, err)
                continue

            output_path.write_bytes(result["image_bytes"])
            cost = engineered["cost"] + result["cost"]
            total_cost += cost
            success += 1
            self.log.emit(f"    OK (${cost:.4f}; running ${total_cost:.4f})")
            self.item_done.emit(filename, cost)

        self.progress.emit(total, total)
        self.finished_batch.emit(success, failed, total_cost)
