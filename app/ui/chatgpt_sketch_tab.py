"""Chat_GPT — Sketch Over Base tab.

Three modes (sub-tabs):
  1. Single   — base + character → one sketch.
  2. Batch    — folder of bases + one character → folder of sketches,
                with progress, pause/resume/cancel, retry, cost tracker.
  3. Freeform — description (+ optional character ref) → one illustration.

In Single + Batch the gpt-image-1 line-art-over-blue instruction is sent
verbatim. In Freeform, Claude expands the user's plain-English brief into
a full gpt-image-1 line-art prompt before sending.
"""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QGroupBox, QMessageBox, QTextEdit, QScrollArea, QSizePolicy, QComboBox,
    QTabWidget, QFrame, QPlainTextEdit, QProgressBar, QListWidget,
    QListWidgetItem,
)

from app.workers.chatgpt_sketch_worker import ChatGPTSketchWorker
from app.workers.chatgpt_sketch_batch_worker import (
    ChatGPTSketchBatchWorker, list_base_files, output_filename_for,
)
from app.workers.chatgpt_freeform_worker import ChatGPTFreeformWorker
from app.api.chatgpt_prompt_engineer import (
    ARCHETYPES, GENDERS, is_neutral_archetype,
)
from app.ui.chatgpt_base_tab import _GenderSelector
from app.keyring_store import get_anthropic_key, get_openai_key
from app import settings_manager

APP_DIR = Path(__file__).parent.parent.parent
SKETCH_OUTPUT_DIR = APP_DIR / "output" / "chat_gpt_sketches"
IMAGE_FILTER = "Image (*.png *.jpg *.jpeg *.webp)"


# ─────────────────────────────────────────────────────────────────────
# Shared widgets
# ─────────────────────────────────────────────────────────────────────

class _UploadSlot(QGroupBox):
    """One labelled image slot with a Browse button and small thumbnail."""

    path_changed = Signal()

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.path: Path | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.path_label = QLabel("(no file selected)")
        self.path_label.setStyleSheet("color:#666;")
        row.addWidget(self.path_label, 1)
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._on_browse)
        row.addWidget(self.browse_btn)
        layout.addLayout(row)

        self.thumb = QLabel("(no preview)")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setMinimumHeight(140)
        self.thumb.setStyleSheet(
            "QLabel{background:#fafafa;border:1px dashed #ccc;color:#999;padding:6px;}")
        layout.addWidget(self.thumb)

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select image", str(Path.home()), IMAGE_FILTER)
        if path:
            self.set_path(Path(path))

    def set_path(self, path: Path):
        self.path = path
        self.path_label.setText(path.name)
        pix = QPixmap(str(path))
        if not pix.isNull():
            self.thumb.setPixmap(
                pix.scaled(self.thumb.width(), self.thumb.height(),
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation))
            self.thumb.setText("")
        else:
            self.thumb.setText("(could not preview)")
        self.path_changed.emit()

    def set_enabled(self, on: bool):
        self.browse_btn.setEnabled(on)


def _make_orientation_combo(allow_auto: bool) -> QComboBox:
    combo = QComboBox()
    if allow_auto:
        combo.addItem("auto (read base aspect)", "auto")
    combo.addItem("portrait (1024×1536)", "portrait")
    combo.addItem("landscape (1536×1024)", "landscape")
    return combo


def _scaled_to(label: QLabel, image_bytes: bytes) -> QPixmap | None:
    pix = QPixmap()
    if not pix.loadFromData(image_bytes, "PNG"):
        return None
    return pix.scaled(label.width(), label.height(),
                      Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


# ─────────────────────────────────────────────────────────────────────
# Mode 1 — Single
# ─────────────────────────────────────────────────────────────────────

class _SingleMode(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: ChatGPTSketchWorker | None = None
        self.last_image_bytes: bytes = b""
        self._build_ui()
        self._update_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        slots = QHBoxLayout()
        self.base_slot = _UploadSlot("Image 1 — Base mannequin")
        self.char_slot = _UploadSlot("Image 2 — Character reference sheet")
        self.base_slot.path_changed.connect(self._update_ui)
        self.char_slot.path_changed.connect(self._update_ui)
        slots.addWidget(self.base_slot, 1)
        slots.addWidget(self.char_slot, 1)
        layout.addLayout(slots)

        orow = QHBoxLayout()
        orow.addWidget(QLabel("Orientation:"))
        self.orientation_combo = _make_orientation_combo(allow_auto=True)
        orow.addWidget(self.orientation_combo, 1)
        layout.addLayout(orow)

        # Archetype + gender — bake proportion rules into the prompt the
        # same way Batch mode does. Logic mirrored from _BatchMode.
        arch_row = QHBoxLayout()
        arch_row.addWidget(QLabel("Archetype:"))
        self.archetype_combo = QComboBox()
        for key, meta in ARCHETYPES.items():
            self.archetype_combo.addItem(
                f"{meta['label']} — {meta['heads']} heads", key)
        arch_row.addWidget(self.archetype_combo, 1)
        layout.addLayout(arch_row)

        gender_row = QHBoxLayout()
        gender_row.addWidget(QLabel("Gender:"))
        self.gender = _GenderSelector()
        gender_row.addWidget(self.gender, 1)
        layout.addLayout(gender_row)

        self.context_label = QLabel("")
        self.context_label.setStyleSheet("color:#0369a1;font-weight:bold;")
        layout.addWidget(self.context_label)

        self.archetype_combo.currentIndexChanged.connect(self._sync_gender_lock)
        self.archetype_combo.currentIndexChanged.connect(self._update_context_label)
        self.gender.changed.connect(self._update_context_label)
        self._sync_gender_lock()
        self._update_context_label()

        arow = QHBoxLayout()
        self.generate_btn = QPushButton("Sketch Character Over Base")
        self.generate_btn.setMinimumHeight(38)
        self.generate_btn.setFont(QFont("", 11, QFont.Weight.Bold))
        self.generate_btn.setStyleSheet(
            "QPushButton:enabled{background:#2563eb;color:white}")
        self.generate_btn.clicked.connect(self._on_generate)
        arow.addWidget(self.generate_btn, 1)
        self.save_btn = QPushButton("Save Image…")
        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.setEnabled(False)
        arow.addWidget(self.save_btn)
        layout.addLayout(arow)

        self.preview_label = QLabel("Sketch result will appear here.")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            "QLabel{background:#fafafa;border:1px dashed #ccc;color:#999;padding:8px;}")
        self.preview_label.setMinimumHeight(280)
        self.preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview_label)
        layout.addWidget(scroll, 1)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Monospace", 9))
        self.log.setMaximumHeight(120)
        layout.addWidget(self.log)

    def is_busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _sync_gender_lock(self):
        archetype = self.archetype_combo.currentData()
        self.gender.set_archetype_locked(is_neutral_archetype(archetype))
        self._update_context_label()

    def _update_context_label(self):
        archetype = self.archetype_combo.currentData()
        if not archetype:
            self.context_label.setText("")
            return
        meta = ARCHETYPES[archetype]
        if is_neutral_archetype(archetype):
            descriptor = f"N_{archetype} (neutral)"
        else:
            prefix = GENDERS[self.gender.value()]["filename_prefix"]
            descriptor = f"{prefix}_{archetype}"
        heads = meta["heads"]
        heads_str = f"{int(heads)}" if heads == int(heads) else f"{heads}"
        self.context_label.setText(
            f"Applying: {descriptor} proportions ({heads_str} heads)")

    def _update_ui(self):
        busy = self.is_busy()
        keys_ok = bool(get_openai_key())
        ready = bool(self.base_slot.path) and bool(self.char_slot.path) and keys_ok
        self.generate_btn.setEnabled(ready and not busy)
        self.save_btn.setEnabled(bool(self.last_image_bytes) and not busy)
        self.base_slot.set_enabled(not busy)
        self.char_slot.set_enabled(not busy)
        self.orientation_combo.setEnabled(not busy)
        self.archetype_combo.setEnabled(not busy)
        self.gender.set_busy_locked(busy)

        if not keys_ok:
            self.generate_btn.setToolTip("OpenAI key required. Configure in Settings tab.")
        elif not ready:
            self.generate_btn.setToolTip("Select both a base image and a character reference.")
        else:
            self.generate_btn.setToolTip("")

    def _on_generate(self):
        if self.is_busy():
            return
        if not (self.base_slot.path and self.char_slot.path):
            QMessageBox.information(
                self, "Missing files",
                "Please select both a base mannequin and a character reference image.")
            return

        self.preview_label.setText("Generating… gpt-image-1")
        self.preview_label.setPixmap(QPixmap())
        self.last_image_bytes = b""

        self.worker = ChatGPTSketchWorker(
            base_image_path=self.base_slot.path,
            character_image_path=self.char_slot.path,
            orientation=self.orientation_combo.currentData(),
            archetype=self.archetype_combo.currentData(),
            gender=self.gender.value())
        self.worker.log.connect(self._append_log)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_finished)
        self._update_ui()
        self.worker.start()

    def _append_log(self, msg: str):
        self.log.append(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_done(self, image_bytes: bytes, cost: float):
        self.last_image_bytes = image_bytes
        scaled = _scaled_to(self.preview_label, image_bytes)
        if scaled:
            self.preview_label.setPixmap(scaled)
            self.preview_label.setText("")
        else:
            self.preview_label.setText("(could not decode image)")
        self._append_log(f"--- cost: ${cost:.4f} ---")

    def _on_failed(self, err: str):
        QMessageBox.warning(self, "Sketch Failed", err)
        self.preview_label.setText("Sketch failed — see log.")

    def _on_finished(self):
        self.worker = None
        self._update_ui()

    def _on_save(self):
        if not self.last_image_bytes:
            return
        SKETCH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suggested = SKETCH_OUTPUT_DIR / f"sketch_{ts}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Sketch", str(suggested), "PNG Image (*.png)")
        if not path:
            return
        Path(path).write_bytes(self.last_image_bytes)
        self._append_log(f"Saved → {path}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.last_image_bytes:
            scaled = _scaled_to(self.preview_label, self.last_image_bytes)
            if scaled:
                self.preview_label.setPixmap(scaled)


# ─────────────────────────────────────────────────────────────────────
# Mode 2 — Batch
# ─────────────────────────────────────────────────────────────────────

class _BatchMode(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: ChatGPTSketchBatchWorker | None = None
        self._running_total_cost = 0.0
        self._build_ui()
        self._update_count()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Base folder selector + proportion-context summary
        bg = QGroupBox("Base mannequin folder")
        bl = QVBoxLayout(bg)
        brow = QHBoxLayout()
        self.base_dir_label = QLabel("(no folder selected)")
        self.base_dir_label.setStyleSheet("color:#666;")
        brow.addWidget(self.base_dir_label, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse_dir)
        brow.addWidget(browse_btn)
        bl.addLayout(brow)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#444;")
        bl.addWidget(self.count_label)
        self.context_label = QLabel("")
        self.context_label.setStyleSheet("color:#0369a1;font-weight:bold;")
        bl.addWidget(self.context_label)
        layout.addWidget(bg)
        self.base_dir: Path | None = None

        # Character reference (single image, applied to every base in the batch)
        self.char_slot = _UploadSlot(
            "Character reference sheet (used for every base in the batch)")
        self.char_slot.path_changed.connect(self._update_ui)
        layout.addWidget(self.char_slot)

        orow = QHBoxLayout()
        orow.addWidget(QLabel("Orientation:"))
        self.orientation_combo = _make_orientation_combo(allow_auto=True)
        orow.addWidget(self.orientation_combo, 1)
        self.orientation_combo.currentIndexChanged.connect(self._update_count)
        layout.addLayout(orow)

        # Archetype + gender — bake proportion rules into every prompt
        arch_row = QHBoxLayout()
        arch_row.addWidget(QLabel("Archetype:"))
        self.archetype_combo = QComboBox()
        for key, meta in ARCHETYPES.items():
            self.archetype_combo.addItem(
                f"{meta['label']} — {meta['heads']} heads", key)
        arch_row.addWidget(self.archetype_combo, 1)
        layout.addLayout(arch_row)

        gender_row = QHBoxLayout()
        gender_row.addWidget(QLabel("Gender:"))
        self.gender = _GenderSelector()
        gender_row.addWidget(self.gender, 1)
        layout.addLayout(gender_row)

        self.archetype_combo.currentIndexChanged.connect(self._sync_gender_lock)
        self.archetype_combo.currentIndexChanged.connect(self._update_context_label)
        self.gender.changed.connect(self._update_context_label)
        self._sync_gender_lock()
        self._update_context_label()

        arow = QHBoxLayout()
        self.start_btn = QPushButton("Start Batch")
        self.start_btn.setMinimumHeight(38)
        self.start_btn.setFont(QFont("", 11, QFont.Weight.Bold))
        self.start_btn.setStyleSheet(
            "QPushButton:enabled{background:#16a34a;color:white}")
        self.start_btn.clicked.connect(self._on_start)
        arow.addWidget(self.start_btn, 1)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._on_pause)
        arow.addWidget(self.pause_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        arow.addWidget(self.cancel_btn)
        layout.addLayout(arow)

        srow = QHBoxLayout()
        self.cost_label = QLabel("Cost: $0.0000")
        srow.addWidget(self.cost_label)
        srow.addStretch(1)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color:#444;")
        srow.addWidget(self.progress_label)
        layout.addLayout(srow)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m  (%p%)")
        layout.addWidget(self.progress_bar)

        # Failure list with retry on double-click
        fail_box = QGroupBox("Failures (double-click to retry)")
        fl = QVBoxLayout(fail_box)
        self.failure_list = QListWidget()
        self.failure_list.setMaximumHeight(110)
        self.failure_list.itemDoubleClicked.connect(self._on_retry_clicked)
        fl.addWidget(self.failure_list)
        layout.addWidget(fail_box)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Monospace", 9))
        self.log.setMaximumHeight(160)
        layout.addWidget(self.log, 1)

    def is_busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _sync_gender_lock(self):
        archetype = self.archetype_combo.currentData()
        self.gender.set_archetype_locked(is_neutral_archetype(archetype))
        self._update_context_label()

    def _update_context_label(self):
        archetype = self.archetype_combo.currentData()
        if not archetype:
            self.context_label.setText("")
            return
        meta = ARCHETYPES[archetype]
        if is_neutral_archetype(archetype):
            descriptor = f"N_{archetype} (neutral)"
        else:
            prefix = GENDERS[self.gender.value()]["filename_prefix"]
            descriptor = f"{prefix}_{archetype}"
        heads = meta["heads"]
        heads_str = f"{int(heads)}" if heads == int(heads) else f"{heads}"
        self.context_label.setText(
            f"Batch will apply: {descriptor} proportions ({heads_str} heads)")

    def _on_browse_dir(self):
        start = str(self.base_dir) if self.base_dir else str(Path.home())
        path = QFileDialog.getExistingDirectory(
            self, "Select base mannequin folder", start)
        if path:
            self.base_dir = Path(path)
            self.base_dir_label.setText(str(self.base_dir))
            self._update_count()
            self._update_ui()

    def _update_count(self):
        files = list_base_files(self.base_dir) if self.base_dir else []
        n = len(files)
        quality = settings_manager.get_openai_quality()
        per = settings_manager.OPENAI_PRICING.get(quality, 0.042)
        est = n * per
        self.count_label.setText(
            f"{n} image file(s) found.  Est. cost: ${est:.2f} (q={quality})")
        self.progress_bar.setMaximum(max(n, 1))
        self.progress_bar.setValue(0)

    def _update_ui(self):
        busy = self.is_busy()
        keys_ok = bool(get_openai_key())
        ready = bool(self.base_dir) and bool(self.char_slot.path) and keys_ok
        self.start_btn.setEnabled(ready and not busy)
        self.pause_btn.setEnabled(busy)
        self.cancel_btn.setEnabled(busy)
        self.char_slot.set_enabled(not busy)
        self.orientation_combo.setEnabled(not busy)
        self.archetype_combo.setEnabled(not busy)
        self.gender.set_busy_locked(busy)
        self.pause_btn.setText("Pause")

        if not keys_ok:
            self.start_btn.setToolTip("OpenAI key required. Configure in Settings tab.")
        elif not self.base_dir:
            self.start_btn.setToolTip("Pick a folder of base mannequin images.")
        elif not self.char_slot.path:
            self.start_btn.setToolTip("Pick a character reference sheet.")
        else:
            self.start_btn.setToolTip("")

    def _append_log(self, msg: str):
        self.log.append(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_start(self):
        if self.is_busy():
            return
        if not (self.base_dir and self.char_slot.path):
            QMessageBox.information(self, "Missing inputs",
                                    "Pick a folder and a character reference.")
            return
        bases = list_base_files(self.base_dir)
        if not bases:
            QMessageBox.information(self, "No images",
                                    f"No image files found in:\n{self.base_dir}")
            return

        quality = settings_manager.get_openai_quality()
        per = settings_manager.OPENAI_PRICING.get(quality, 0.042)
        est = len(bases) * per
        out_dir = SKETCH_OUTPUT_DIR
        archetype = self.archetype_combo.currentData()
        gender = self.gender.value()
        arch_meta = ARCHETYPES[archetype]

        reply = QMessageBox.question(
            self, "Start sketch batch",
            f"Sketch {len(bases)} base(s) over "
            f"{self.char_slot.path.name}?\n\n"
            f"  Archetype:   {arch_meta['label']} ({arch_meta['heads']} heads)\n"
            f"  Gender:      {'neutral' if is_neutral_archetype(archetype) else gender}\n"
            f"  Orientation: {self.orientation_combo.currentData()}\n"
            f"  Quality:     {quality}\n"
            f"  Estimate:    ${est:.2f}\n\n"
            f"  Output:      {out_dir}\n\n"
            f"Files that already exist will be skipped.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Ok)
        if reply != QMessageBox.StandardButton.Ok:
            return

        self._start_worker(self.base_dir, self.char_slot.path,
                           self.orientation_combo.currentData(), out_dir,
                           total=len(bases),
                           archetype=archetype, gender=gender)

    def _start_worker(self, base_dir: Path, char_path: Path, orientation: str,
                      out_dir: Path, total: int,
                      archetype: str, gender: str):
        self.failure_list.clear()
        self.log.clear()
        self.cost_label.setText("Cost: $0.0000")
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"0 / {total}")
        self._running_total_cost = 0.0
        self._running_base_dir = base_dir
        self._running_char_path = char_path
        self._running_orientation = orientation
        self._running_out_dir = out_dir
        self._running_archetype = archetype
        self._running_gender = gender

        self.worker = ChatGPTSketchBatchWorker(
            base_dir=base_dir, character_image_path=char_path,
            orientation=orientation, output_dir=out_dir,
            archetype=archetype, gender=gender)
        self._running_timestamp = self.worker.timestamp
        self.worker.log.connect(self._append_log)
        self.worker.progress.connect(self._on_progress)
        self.worker.item_done.connect(self._on_item_done)
        self.worker.item_failed.connect(self._on_item_failed)
        self.worker.finished_batch.connect(self._on_finished)
        self.worker.finished.connect(self._on_thread_finished)
        self._update_ui()
        self.worker.start()

    def _on_progress(self, current: int, total: int):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(current)
        self.progress_label.setText(f"{current} / {total}")

    def _on_item_done(self, filename: str, cost: float):
        self._running_total_cost += cost
        self.cost_label.setText(f"Cost: ${self._running_total_cost:.4f}")

    def _on_item_failed(self, filename: str, base_path: str, error: str):
        item = QListWidgetItem(f"{filename}   ←  {error[:80]}")
        item.setData(Qt.ItemDataRole.UserRole,
                     {"filename": filename, "base_path": base_path, "error": error})
        self.failure_list.addItem(item)

    def _on_retry_clicked(self, item: QListWidgetItem):
        if self.is_busy():
            QMessageBox.information(self, "Busy", "Wait for the current run to finish.")
            return
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        base_path = Path(data.get("base_path", ""))
        if not base_path.exists():
            return
        ts = self._running_timestamp
        out = self._running_out_dir / output_filename_for(base_path, ts)
        if out.exists():
            try:
                out.unlink()
            except Exception:
                pass
        # The worker iterates the whole folder; retrying one file is more
        # complex. Cleanest fix: temporarily run the single-sketch worker
        # with the same archetype/gender context as the original batch.
        from app.workers.chatgpt_sketch_worker import ChatGPTSketchWorker as _W
        self._retry_worker = _W(
            base_image_path=base_path,
            character_image_path=self._running_char_path,
            orientation=self._running_orientation,
            archetype=self._running_archetype,
            gender=self._running_gender)
        row = self.failure_list.row(item)
        self.failure_list.takeItem(row)

        def _on_done(image_bytes, cost):
            out_path = self._running_out_dir / output_filename_for(base_path, ts)
            self._running_out_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(image_bytes)
            self._running_total_cost += cost
            self.cost_label.setText(f"Cost: ${self._running_total_cost:.4f}")
            self._append_log(f"  retry OK → {out_path.name} (${cost:.4f})")

        def _on_failed(err):
            self._append_log(f"  retry failed for {base_path.name}: {err[:160]}")
            it = QListWidgetItem(f"{base_path.name}   ←  {err[:80]}")
            it.setData(Qt.ItemDataRole.UserRole,
                       {"filename": base_path.name, "base_path": str(base_path),
                        "error": err})
            self.failure_list.addItem(it)

        self._retry_worker.log.connect(self._append_log)
        self._retry_worker.done.connect(_on_done)
        self._retry_worker.failed.connect(_on_failed)
        self._retry_worker.start()

    def _on_pause(self):
        if not self.worker:
            return
        if self.pause_btn.text() == "Pause":
            self.worker.set_paused(True)
            self.pause_btn.setText("Resume")
            self._append_log("─── PAUSED ───")
        else:
            self.worker.set_paused(False)
            self.pause_btn.setText("Pause")
            self._append_log("─── RESUMED ───")

    def _on_cancel(self):
        if self.worker:
            self.worker.request_stop()

    def _on_finished(self, success: int, failed: int, total_cost: float):
        self._append_log(
            f"─── batch done: {success} OK, {failed} failed, ${total_cost:.4f} ───")

    def _on_thread_finished(self):
        self.worker = None
        self._update_ui()


# ─────────────────────────────────────────────────────────────────────
# Mode 3 — Freeform
# ─────────────────────────────────────────────────────────────────────

class _FreeformMode(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: ChatGPTFreeformWorker | None = None
        self.last_image_bytes: bytes = b""
        self.last_prompt: str = ""
        self._build_ui()
        self._update_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Optional character ref
        self.char_slot = _UploadSlot(
            "Character reference sheet (optional — leave empty for pure text-to-image)")
        self.char_slot.path_changed.connect(self._update_ui)
        layout.addWidget(self.char_slot)

        # Description
        layout.addWidget(QLabel("Describe what you want:"))
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setPlaceholderText(
            "e.g. Faye-Lyn sitting cross-legged in a neon arcade, line art, A4 landscape")
        self.desc_edit.setFixedHeight(110)
        self.desc_edit.textChanged.connect(self._update_ui)
        layout.addWidget(self.desc_edit)

        orow = QHBoxLayout()
        orow.addWidget(QLabel("Orientation:"))
        self.orientation_combo = _make_orientation_combo(allow_auto=False)
        orow.addWidget(self.orientation_combo, 1)
        layout.addLayout(orow)

        # Archetype + gender — same controls as Single and Batch so the
        # proportion rules thread through Claude's freeform prompt.
        arch_row = QHBoxLayout()
        arch_row.addWidget(QLabel("Archetype:"))
        self.archetype_combo = QComboBox()
        for key, meta in ARCHETYPES.items():
            self.archetype_combo.addItem(
                f"{meta['label']} — {meta['heads']} heads", key)
        arch_row.addWidget(self.archetype_combo, 1)
        layout.addLayout(arch_row)

        gender_row = QHBoxLayout()
        gender_row.addWidget(QLabel("Gender:"))
        self.gender = _GenderSelector()
        gender_row.addWidget(self.gender, 1)
        layout.addLayout(gender_row)

        self.context_label = QLabel("")
        self.context_label.setStyleSheet("color:#0369a1;font-weight:bold;")
        layout.addWidget(self.context_label)

        self.archetype_combo.currentIndexChanged.connect(self._sync_gender_lock)
        self.archetype_combo.currentIndexChanged.connect(self._update_context_label)
        self.gender.changed.connect(self._update_context_label)
        self._sync_gender_lock()
        self._update_context_label()

        arow = QHBoxLayout()
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setMinimumHeight(38)
        self.generate_btn.setFont(QFont("", 11, QFont.Weight.Bold))
        self.generate_btn.setStyleSheet(
            "QPushButton:enabled{background:#2563eb;color:white}")
        self.generate_btn.clicked.connect(self._on_generate)
        arow.addWidget(self.generate_btn, 1)
        self.save_btn = QPushButton("Save Image…")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save)
        arow.addWidget(self.save_btn)
        layout.addLayout(arow)

        self.preview_label = QLabel("Output will appear here.")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            "QLabel{background:#fafafa;border:1px dashed #ccc;color:#999;padding:8px;}")
        self.preview_label.setMinimumHeight(280)
        self.preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview_label)
        layout.addWidget(scroll, 1)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Monospace", 9))
        self.log.setMaximumHeight(140)
        layout.addWidget(self.log)

    def is_busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _sync_gender_lock(self):
        archetype = self.archetype_combo.currentData()
        self.gender.set_archetype_locked(is_neutral_archetype(archetype))
        self._update_context_label()

    def _update_context_label(self):
        archetype = self.archetype_combo.currentData()
        if not archetype:
            self.context_label.setText("")
            return
        meta = ARCHETYPES[archetype]
        if is_neutral_archetype(archetype):
            descriptor = f"N_{archetype} (neutral)"
        else:
            prefix = GENDERS[self.gender.value()]["filename_prefix"]
            descriptor = f"{prefix}_{archetype}"
        heads = meta["heads"]
        heads_str = f"{int(heads)}" if heads == int(heads) else f"{heads}"
        self.context_label.setText(
            f"Applying: {descriptor} proportions ({heads_str} heads)")

    def _update_ui(self):
        busy = self.is_busy()
        keys_ok = bool(get_anthropic_key()) and bool(get_openai_key())
        ready = bool(self.desc_edit.toPlainText().strip()) and keys_ok
        self.generate_btn.setEnabled(ready and not busy)
        self.save_btn.setEnabled(bool(self.last_image_bytes) and not busy)
        self.char_slot.set_enabled(not busy)
        self.orientation_combo.setEnabled(not busy)
        self.desc_edit.setEnabled(not busy)
        self.archetype_combo.setEnabled(not busy)
        self.gender.set_busy_locked(busy)

        if not keys_ok:
            self.generate_btn.setToolTip(
                "Anthropic and OpenAI keys are required. Configure in Settings tab.")
        elif not ready:
            self.generate_btn.setToolTip("Type a description first.")
        else:
            self.generate_btn.setToolTip("")

    def _append_log(self, msg: str):
        self.log.append(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_generate(self):
        if self.is_busy():
            return
        desc = self.desc_edit.toPlainText().strip()
        if not desc:
            return
        self.preview_label.setText("Generating… Claude → gpt-image-1")
        self.preview_label.setPixmap(QPixmap())
        self.last_image_bytes = b""
        self.last_prompt = ""

        self.worker = ChatGPTFreeformWorker(
            description=desc,
            orientation=self.orientation_combo.currentData(),
            archetype=self.archetype_combo.currentData(),
            gender=self.gender.value(),
            character_image_path=self.char_slot.path)
        self.worker.log.connect(self._append_log)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_finished)
        self._update_ui()
        self.worker.start()

    def _on_done(self, image_bytes: bytes, prompt_text: str, cost: float):
        self.last_image_bytes = image_bytes
        self.last_prompt = prompt_text
        scaled = _scaled_to(self.preview_label, image_bytes)
        if scaled:
            self.preview_label.setPixmap(scaled)
            self.preview_label.setText("")
        else:
            self.preview_label.setText("(could not decode image)")
        self._append_log(f"--- engineered prompt ({len(prompt_text)} chars) ---")
        self._append_log(prompt_text)
        self._append_log(f"--- total cost: ${cost:.4f} ---")

    def _on_failed(self, err: str):
        QMessageBox.warning(self, "Generation Failed", err)
        self.preview_label.setText("Generation failed — see log.")

    def _on_finished(self):
        self.worker = None
        self._update_ui()

    def _on_save(self):
        if not self.last_image_bytes:
            return
        SKETCH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suggested = SKETCH_OUTPUT_DIR / f"freeform_{ts}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Sketch", str(suggested), "PNG Image (*.png)")
        if not path:
            return
        Path(path).write_bytes(self.last_image_bytes)
        self._append_log(f"Saved → {path}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.last_image_bytes:
            scaled = _scaled_to(self.preview_label, self.last_image_bytes)
            if scaled:
                self.preview_label.setPixmap(scaled)


# ─────────────────────────────────────────────────────────────────────
# Outer tab
# ─────────────────────────────────────────────────────────────────────

class ChatGPTSketchTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header = QLabel("Chat_GPT — Sketch Over Base")
        header.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(header)

        sub = QLabel("Black ink line art — A4 portrait or landscape, print friendly.")
        sub.setStyleSheet("color: #666;")
        layout.addWidget(sub)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        self.modes = QTabWidget()
        self.single_mode = _SingleMode()
        self.batch_mode = _BatchMode()
        self.freeform_mode = _FreeformMode()
        self.modes.addTab(self.single_mode, "1. Single")
        self.modes.addTab(self.batch_mode, "2. Batch")
        self.modes.addTab(self.freeform_mode, "3. Freeform")
        layout.addWidget(self.modes, 1)

    def is_busy(self) -> bool:
        return (self.single_mode.is_busy()
                or self.batch_mode.is_busy()
                or self.freeform_mode.is_busy())
