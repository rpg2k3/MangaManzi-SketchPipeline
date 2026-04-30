"""Sketch Generation tab — batch-only workflow (regen moved to Library tab)."""

import json
import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QProgressBar, QTextEdit, QFileDialog,
    QMessageBox, QGroupBox, QLineEdit, QPlainTextEdit,
)
from PySide6.QtGui import QFont

from app.state import GenerationState
from app.workers.extraction_worker import ExtractionWorker
from app.workers.sketch_worker import SketchWorker
from app.keyring_store import get_anthropic_key, get_openai_key, get_google_key
from app import settings_manager
from app.archetype_scanner import OUTPUT_DIR, BASES_CSP_DIR, BASES_GPT_DIR

APP_DIR = Path(__file__).parent.parent.parent
POSE_LIBRARY_PATH = APP_DIR / "data" / "pose_library.json"
CHARACTERS_DIR = APP_DIR / "characters"


class SketchTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pose_data = {}
        self.character_json = None
        self.character_sheet_path = None
        self.extraction_worker = None
        self.sketch_worker = None
        self.state = GenerationState.IDLE
        self.total_cost = 0
        self.success_count = 0
        self.fail_count = 0
        self._load_pose_data()
        self._build_ui()
        self._update_ui()

    def _load_pose_data(self):
        if POSE_LIBRARY_PATH.exists():
            self.pose_data = json.loads(POSE_LIBRARY_PATH.read_text())

    def _get_poses(self):
        return self.pose_data.get("poses", [])

    def _char_id(self):
        return self.character_json.get("character_id", "unknown") if self.character_json else "unknown"

    def _output_dir(self):
        return CHARACTERS_DIR / self._char_id() / "sketches"

    def _mannequin_dir(self):
        key = self.archetype_combo.currentData() or "F_adult-(25+)"
        return OUTPUT_DIR / key

    def _sketch_filename(self, pose):
        return f"{self._char_id()}_{pose['filename']}"

    def _has_image_key(self):
        provider = settings_manager.get_sketch_provider()
        return bool(get_openai_key()) if provider == "openai" else bool(get_google_key())

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header = QLabel("Sketch Generation")
        header.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(header)

        # 1. Character Upload
        ug = QGroupBox("1. Upload Character Sheet")
        ul = QVBoxLayout(ug)
        urow = QHBoxLayout()
        self.sheet_path_label = QLabel("No file selected")
        urow.addWidget(self.sheet_path_label, 1)
        upload_btn = QPushButton("Browse...")
        upload_btn.clicked.connect(self._on_browse_sheet)
        urow.addWidget(upload_btn)
        ul.addLayout(urow)

        idrow = QHBoxLayout()
        idrow.addWidget(QLabel("Character ID:"))
        self.char_id_edit = QLineEdit()
        self.char_id_edit.setPlaceholderText("snake_case_name")
        idrow.addWidget(self.char_id_edit, 1)
        ul.addLayout(idrow)

        self.extract_btn = QPushButton("Extract Character (Claude Haiku)")
        self.extract_btn.setMinimumHeight(35)
        self.extract_btn.clicked.connect(self._on_extract)
        ul.addWidget(self.extract_btn)

        self.json_toggle = QPushButton("Show Extracted JSON")
        self.json_toggle.setCheckable(True)
        self.json_toggle.clicked.connect(self._toggle_json)
        ul.addWidget(self.json_toggle)

        self.json_edit = QPlainTextEdit()
        self.json_edit.setFont(QFont("Monospace", 9))
        self.json_edit.setMaximumHeight(200)
        self.json_edit.setVisible(False)
        ul.addWidget(self.json_edit)

        self.save_json_btn = QPushButton("Save Edited JSON")
        self.save_json_btn.setVisible(False)
        self.save_json_btn.clicked.connect(self._save_json_edits)
        ul.addWidget(self.save_json_btn)

        self.extract_status = QLabel("")
        ul.addWidget(self.extract_status)
        layout.addWidget(ug)

        # 2. Generate Sketches
        sg = QGroupBox("2. Generate Sketches")
        sl = QVBoxLayout(sg)

        arow = QHBoxLayout()
        arow.addWidget(QLabel("Archetype:"))
        self.archetype_combo = QComboBox()
        # Populate from output folders (generated mannequins)
        if OUTPUT_DIR.exists():
            for d in sorted(OUTPUT_DIR.iterdir()):
                if d.is_dir():
                    self.archetype_combo.addItem(d.name, d.name)
        arow.addWidget(self.archetype_combo, 1)
        sl.addLayout(arow)

        self.sketch_info = QLabel()
        sl.addWidget(self.sketch_info)

        self.sketch_progress = QProgressBar()
        self.sketch_progress.setTextVisible(True)
        self.sketch_progress.setFormat("%v / %m  (%p%)")
        sl.addWidget(self.sketch_progress)

        brow = QHBoxLayout()
        self.sketch_next_btn = QPushButton("Generate Next Sketch")
        self.sketch_next_btn.setMinimumHeight(40)
        self.sketch_next_btn.setFont(QFont("", 11, QFont.Weight.Bold))
        self.sketch_next_btn.setStyleSheet("QPushButton:enabled{background:#4CAF50;color:white}")
        self.sketch_next_btn.clicked.connect(self._on_sketch_next)
        brow.addWidget(self.sketch_next_btn, 1)

        self.sketch_auto_btn = QPushButton("Start Auto-Generation")
        self.sketch_auto_btn.setMinimumHeight(40)
        self.sketch_auto_btn.setFont(QFont("", 11, QFont.Weight.Bold))
        self.sketch_auto_btn.clicked.connect(self._on_sketch_auto)
        brow.addWidget(self.sketch_auto_btn, 1)

        self.sketch_pause_btn = QPushButton("Pause")
        self.sketch_pause_btn.setEnabled(False)
        self.sketch_pause_btn.clicked.connect(self._on_sketch_pause)
        brow.addWidget(self.sketch_pause_btn)

        self.sketch_cancel_btn = QPushButton("Cancel")
        self.sketch_cancel_btn.setEnabled(False)
        self.sketch_cancel_btn.clicked.connect(self._on_sketch_cancel)
        brow.addWidget(self.sketch_cancel_btn)
        sl.addLayout(brow)
        layout.addWidget(sg)

        # Log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Monospace", 9))
        layout.addWidget(self.log, 1)

    # ─── UI state ───

    def _update_ui(self):
        has_character = self.character_json is not None
        idle = self.state == GenerationState.IDLE
        paused = self.state == GenerationState.PAUSED

        self.extract_btn.setEnabled(
            self.character_sheet_path is not None and idle and bool(get_anthropic_key()))

        poses = self._get_poses()
        char_id = self._char_id() if has_character else "?"
        output_dir = self._output_dir()
        existing = sum(1 for p in poses
                       if (output_dir / self._sketch_filename(p)).exists()) if has_character else 0

        total = len(poses)
        remaining = total - existing
        self.sketch_progress.setMaximum(total)
        self.sketch_progress.setValue(existing)

        provider = settings_manager.get_sketch_provider()
        est = settings_manager.estimate_sketch_cost(remaining)
        self.sketch_info.setText(
            f"Poses: {total}  |  Character: {char_id}  |  "
            f"Generated: {existing}/{total}  |  "
            f"Provider: {provider.title()}  |  Est: ${est:.2f}")

        has_key = bool(self._has_image_key()) and bool(get_anthropic_key())
        can_sketch = has_character and has_key and (idle or paused) and remaining > 0

        self.sketch_next_btn.setEnabled(bool(can_sketch))
        self.sketch_auto_btn.setEnabled(bool(has_character and has_key and idle and remaining > 0))
        self.sketch_cancel_btn.setEnabled(not idle)
        self.sketch_pause_btn.setEnabled(self.state == GenerationState.GENERATING)

        if paused:
            self.sketch_pause_btn.setText("Resume")
            self.sketch_pause_btn.setEnabled(True)
        else:
            self.sketch_pause_btn.setText("Pause")

    # ─── Character extraction ───

    def _on_browse_sheet(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Character Sheet", "",
                                              "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.character_sheet_path = Path(path)
            self.sheet_path_label.setText(self.character_sheet_path.name)
            self._update_ui()

    def _on_extract(self):
        if not self.character_sheet_path:
            return
        char_id = self.char_id_edit.text().strip() or ""
        self.extract_status.setText("Extracting...")
        self.extract_btn.setEnabled(False)
        self.extraction_worker = ExtractionWorker(self.character_sheet_path, char_id)
        self.extraction_worker.log.connect(self._on_log)
        self.extraction_worker.done.connect(self._on_extraction_done)
        self.extraction_worker.failed.connect(self._on_extraction_failed)
        self.extraction_worker.start()

    def _on_extraction_done(self, result):
        self.character_json = result["data"]
        self.extraction_worker = None
        self.json_edit.setPlainText(json.dumps(self.character_json, indent=2))
        self.json_edit.setVisible(True)
        self.save_json_btn.setVisible(True)
        self.json_toggle.setChecked(True)

        char_id = self.character_json.get("character_id", "unknown")
        if char_id != "unknown":
            self.char_id_edit.setText(char_id)
        char_dir = CHARACTERS_DIR / char_id
        char_dir.mkdir(parents=True, exist_ok=True)
        (char_dir / "extracted.json").write_text(json.dumps(self.character_json, indent=2))

        if self.character_sheet_path:
            dest = char_dir / f"source_sheet{self.character_sheet_path.suffix}"
            if not dest.exists():
                shutil.copy2(self.character_sheet_path, dest)

        conf = self.character_json.get("extraction_confidence", "?")
        self.extract_status.setText(f"Extraction complete (confidence: {conf}). Cost: ${result['cost']:.4f}")
        self._update_ui()

    def _on_extraction_failed(self, error):
        self.extraction_worker = None
        self.extract_status.setText(f"Failed: {error}")
        self._update_ui()

    def _toggle_json(self):
        vis = self.json_toggle.isChecked()
        self.json_edit.setVisible(vis)
        self.save_json_btn.setVisible(vis and self.character_json is not None)
        self.json_toggle.setText("Hide Extracted JSON" if vis else "Show Extracted JSON")

    def _save_json_edits(self):
        try:
            self.character_json = json.loads(self.json_edit.toPlainText())
            char_id = self.character_json.get("character_id", "unknown")
            char_dir = CHARACTERS_DIR / char_id
            char_dir.mkdir(parents=True, exist_ok=True)
            (char_dir / "extracted.json").write_text(json.dumps(self.character_json, indent=2))
            self.extract_status.setText("JSON saved.")
            self._update_ui()
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, "Invalid JSON", f"Could not parse:\n{e}")

    # ─── Batch sketch generation ───

    def _get_remaining_poses(self):
        if not self.character_json:
            return []
        output_dir = self._output_dir()
        return [p for p in self._get_poses()
                if not (output_dir / self._sketch_filename(p)).exists()]

    def _on_sketch_next(self):
        remaining = self._get_remaining_poses()
        if not remaining:
            QMessageBox.information(self, "Done", "All sketches generated!")
            return
        self._start_sketch_batch([remaining[0]])

    def _on_sketch_auto(self):
        remaining = self._get_remaining_poses()
        if not remaining:
            QMessageBox.information(self, "Done", "All sketches generated!")
            return

        total = len(remaining)
        provider = settings_manager.get_sketch_provider()
        model = settings_manager.get_sketch_model()
        quality = settings_manager.get_openai_quality()
        est = settings_manager.estimate_sketch_cost(total)
        quality_line = f" (quality: {quality})" if provider == "openai" else ""

        reply = QMessageBox.question(
            self, "Start Sketch Generation",
            f"About to generate {total} character sketches.\n\n"
            f"Character: {self._char_id()}\n"
            f"Archetype: {self.archetype_combo.currentData() or '?'}\n"
            f"Provider: {provider.title()} {model}{quality_line}\n"
            f"Estimated cost: ${est:.2f}\n\n"
            f"Proceed?",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Yes)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._start_sketch_batch(remaining)

    def _start_sketch_batch(self, poses):
        output_dir = self._output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        sheet = self.character_sheet_path or (CHARACTERS_DIR / self._char_id() / "source_sheet.png")

        self.sketch_worker = SketchWorker(
            poses=poses, character_json=self.character_json,
            character_sheet_path=sheet,
            mannequin_dir=self._mannequin_dir(),
            output_dir=output_dir)
        self.sketch_worker.log.connect(self._on_log)
        self.sketch_worker.pose_done.connect(self._on_pose_done)
        self.sketch_worker.pose_failed.connect(self._on_pose_failed)
        self.sketch_worker.progress.connect(lambda c, t: None)
        self.sketch_worker.finished_batch.connect(self._on_batch_finished)
        self.state = GenerationState.GENERATING
        self._update_ui()
        self.sketch_worker.start()

    def _on_sketch_pause(self):
        if self.state == GenerationState.GENERATING and self.sketch_worker:
            self.sketch_worker.set_paused(True)
            self.state = GenerationState.PAUSED
            self.log.append("\u2500" * 40 + " PAUSED")
            self._update_ui()
        elif self.state == GenerationState.PAUSED and self.sketch_worker:
            self.sketch_worker.set_paused(False)
            self.state = GenerationState.GENERATING
            self.log.append("\u2500" * 40 + " RESUMED")
            self._update_ui()

    def _on_sketch_cancel(self):
        if self.sketch_worker:
            self.sketch_worker.request_stop()

    def _on_log(self, msg):
        self.log.append(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_pose_done(self, num, filename, cost):
        self.success_count += 1
        self.total_cost += cost
        self._update_ui()

    def _on_pose_failed(self, num, filename, error):
        self.fail_count += 1
        self._update_ui()

    def _on_batch_finished(self, success, failed):
        self.state = GenerationState.IDLE
        self.sketch_worker = None
        self.log.append(f"{'─'*50}\nSketch batch: {success} OK, {failed} failed, ${self.total_cost:.4f}")
        self._update_ui()

    def is_busy(self):
        return self.state != GenerationState.IDLE
