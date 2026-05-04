"""Chat_GPT — Base Mannequin Generator tab.

Three modes (sub-tabs):
  1. Single   — pick archetype + view + pose from taxonomy, generate one.
  2. Batch    — multi-select views/poses for one archetype, generate all,
                with progress, cost tracker, pause/resume, per-item retry.
  3. Custom   — archetype + view + free-text pose description.

In all three modes Claude (claude-sonnet-4-20250514) expands inputs into
the full 9LivesK9 prompt before OpenAI gpt-image-1 renders the image.
"""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QPlainTextEdit, QTextEdit, QFileDialog, QGroupBox, QMessageBox,
    QScrollArea, QSizePolicy, QTabWidget, QCheckBox, QProgressBar,
    QListWidget, QListWidgetItem, QFrame,
)

from app.api.chatgpt_prompt_engineer import ARCHETYPES, VIEWS
from app.api import chatgpt_pose_taxonomy
from app.workers.chatgpt_base_worker import ChatGPTBaseWorker
from app.workers.chatgpt_batch_worker import ChatGPTBatchWorker
from app.keyring_store import get_anthropic_key, get_openai_key
from app import settings_manager

APP_DIR = Path(__file__).parent.parent.parent


def _default_output_dir() -> Path:
    """Pull the configured base output folder from settings, with a fallback."""
    custom = settings_manager.get("chatgpt_output_dir")
    if custom:
        return Path(custom)
    return APP_DIR / "output" / "chat_gpt_base"


# ─────────────────────────────────────────────────────────────────────
# Shared single-image preview panel (used by Single + Custom modes)
# ─────────────────────────────────────────────────────────────────────

class _SinglePreviewPanel(QWidget):
    """Generate button + preview + save button + log. Hosts a base-worker run."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: ChatGPTBaseWorker | None = None
        self.last_image_bytes: bytes = b""
        self.last_prompt: str = ""
        self.last_filename_hint: str = "base"
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        arow = QHBoxLayout()
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setMinimumHeight(36)
        self.generate_btn.setFont(QFont("", 11, QFont.Weight.Bold))
        self.generate_btn.setStyleSheet(
            "QPushButton:enabled{background:#2563eb;color:white}")
        arow.addWidget(self.generate_btn, 1)

        self.save_btn = QPushButton("Save Image…")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save)
        arow.addWidget(self.save_btn)
        layout.addLayout(arow)

        self.preview_label = QLabel("Generated image will appear here.")
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

    def start(self, archetype: str, view: str, pose_description: str,
              orientation: str, filename_hint: str):
        if self.is_busy():
            return
        self.last_image_bytes = b""
        self.last_prompt = ""
        self.last_filename_hint = filename_hint
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText("Generating… Claude → gpt-image-1")
        self.save_btn.setEnabled(False)

        self.worker = ChatGPTBaseWorker(
            archetype=archetype, view=view,
            pose_description=pose_description, orientation=orientation)
        self.worker.log.connect(self._append_log)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _append_log(self, msg: str):
        self.log.append(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_done(self, image_bytes: bytes, prompt_text: str, cost: float):
        self.last_image_bytes = image_bytes
        self.last_prompt = prompt_text
        pix = QPixmap()
        if pix.loadFromData(image_bytes, "PNG"):
            self.preview_label.setPixmap(self._scaled(pix))
            self.preview_label.setText("")
        else:
            self.preview_label.setText("(could not decode image)")
        self._append_log(f"--- engineered prompt ({len(prompt_text)} chars) ---")
        self._append_log(prompt_text)
        self._append_log(f"--- total cost: ${cost:.4f} ---")
        self.save_btn.setEnabled(True)

    def _on_failed(self, err: str):
        QMessageBox.warning(self, "Generation Failed", err)
        self.preview_label.setText("Generation failed — see log.")

    def _on_finished(self):
        self.worker = None

    def _on_save(self):
        if not self.last_image_bytes:
            return
        out_dir = _default_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suggested = out_dir / f"{self.last_filename_hint}_{ts}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Base Image", str(suggested), "PNG Image (*.png)")
        if not path:
            return
        Path(path).write_bytes(self.last_image_bytes)
        self._append_log(f"Saved → {path}")

    def _scaled(self, pix: QPixmap) -> QPixmap:
        return pix.scaled(
            self.preview_label.width(), self.preview_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.last_image_bytes:
            pix = QPixmap()
            if pix.loadFromData(self.last_image_bytes, "PNG"):
                self.preview_label.setPixmap(self._scaled(pix))


# ─────────────────────────────────────────────────────────────────────
# Mode 1 — Single Generate
# ─────────────────────────────────────────────────────────────────────

class _SingleMode(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.preview.generate_btn.clicked.connect(self._on_generate)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QGroupBox("Single Generate")
        gl = QVBoxLayout(controls)

        gl.addLayout(self._row("Archetype:", self._make_archetype_combo()))
        gl.addLayout(self._row("View:", self._make_view_combo()))
        gl.addLayout(self._row("Pose:", self._make_pose_combo()))

        self.pose_help = QLabel("")
        self.pose_help.setStyleSheet("color:#666;")
        self.pose_help.setWordWrap(True)
        gl.addWidget(self.pose_help)

        self.pose_combo.currentIndexChanged.connect(self._update_help)
        self._update_help()

        layout.addWidget(controls)
        self.preview = _SinglePreviewPanel()
        layout.addWidget(self.preview, 1)

    def _row(self, label_text: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        lab = QLabel(label_text)
        lab.setMinimumWidth(80)
        row.addWidget(lab)
        row.addWidget(widget, 1)
        return row

    def _make_archetype_combo(self) -> QComboBox:
        self.archetype_combo = QComboBox()
        for key, meta in ARCHETYPES.items():
            self.archetype_combo.addItem(f"{meta['label']} — {meta['heads']} heads", key)
        return self.archetype_combo

    def _make_view_combo(self) -> QComboBox:
        self.view_combo = QComboBox()
        for key, desc in VIEWS.items():
            self.view_combo.addItem(f"{key}", key)
        return self.view_combo

    def _make_pose_combo(self) -> QComboBox:
        self.pose_combo = QComboBox()
        last_cat = None
        for entry in chatgpt_pose_taxonomy.list_unique_poses():
            cat = entry["category"]
            if cat != last_cat:
                # Insert a non-selectable category header
                self.pose_combo.addItem(f"── {cat} ──", None)
                idx = self.pose_combo.count() - 1
                self.pose_combo.model().item(idx).setEnabled(False)
                last_cat = cat
            self.pose_combo.addItem(entry["pose"], entry)
        # default to first selectable item
        for i in range(self.pose_combo.count()):
            if self.pose_combo.itemData(i) is not None:
                self.pose_combo.setCurrentIndex(i)
                break
        return self.pose_combo

    def _update_help(self):
        entry = self.pose_combo.currentData()
        if isinstance(entry, dict):
            self.pose_help.setText(entry.get("description", ""))
        else:
            self.pose_help.setText("")

    def is_busy(self) -> bool:
        return self.preview.is_busy()

    def _on_generate(self):
        if self.is_busy():
            return
        if not (get_anthropic_key() and get_openai_key()):
            QMessageBox.warning(self, "Missing API keys",
                                "Anthropic and OpenAI keys are required. Configure in Settings tab.")
            return
        entry = self.pose_combo.currentData()
        if not isinstance(entry, dict):
            QMessageBox.information(self, "Pick a pose", "Please pick a pose.")
            return
        archetype = self.archetype_combo.currentData()
        view = self.view_combo.currentData()
        pose_desc = entry.get("description") or entry["pose"].replace("_", " ")
        hint = f"{archetype}_{view}_{entry['pose']}"
        self.preview.start(archetype, view, pose_desc, "auto", hint)


# ─────────────────────────────────────────────────────────────────────
# Mode 2 — Batch Generate (LoRA dataset builder)
# ─────────────────────────────────────────────────────────────────────

class _BatchMode(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: ChatGPTBatchWorker | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Archetype
        arow = QHBoxLayout()
        arow.addWidget(QLabel("Archetype:"))
        self.archetype_combo = QComboBox()
        for key, meta in ARCHETYPES.items():
            self.archetype_combo.addItem(f"{meta['label']} — {meta['heads']} heads", key)
        arow.addWidget(self.archetype_combo, 1)
        layout.addLayout(arow)

        # View checklist
        view_box = QGroupBox("Views (8) — uncheck to skip")
        vl = QHBoxLayout(view_box)
        self.view_checks: dict[str, QCheckBox] = {}
        for key in VIEWS.keys():
            cb = QCheckBox(key)
            cb.setChecked(True)
            cb.stateChanged.connect(self._update_count)
            self.view_checks[key] = cb
            vl.addWidget(cb)
        vl.addStretch(1)
        layout.addWidget(view_box)

        # Pose checklist
        pose_box = QGroupBox("Poses — uncheck to skip")
        pl = QVBoxLayout(pose_box)
        toggle_row = QHBoxLayout()
        check_all = QPushButton("Check all")
        check_all.clicked.connect(lambda: self._set_all_poses(True))
        toggle_row.addWidget(check_all)
        uncheck_all = QPushButton("Uncheck all")
        uncheck_all.clicked.connect(lambda: self._set_all_poses(False))
        toggle_row.addWidget(uncheck_all)
        toggle_row.addStretch(1)
        pl.addLayout(toggle_row)

        self.pose_list = QListWidget()
        self.pose_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        last_cat = None
        for entry in chatgpt_pose_taxonomy.list_unique_poses():
            cat = entry["category"]
            if cat != last_cat:
                header = QListWidgetItem(f"── {cat} ──")
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                f = header.font()
                f.setBold(True)
                header.setFont(f)
                self.pose_list.addItem(header)
                last_cat = cat
            item = QListWidgetItem(f"{entry['pose']}    —  {entry['description']}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.pose_list.addItem(item)
        self.pose_list.itemChanged.connect(lambda *_: self._update_count())
        self.pose_list.setMinimumHeight(220)
        pl.addWidget(self.pose_list)
        layout.addWidget(pose_box, 1)

        # Action row
        arow2 = QHBoxLayout()
        self.generate_btn = QPushButton("Generate All")
        self.generate_btn.setMinimumHeight(36)
        self.generate_btn.setFont(QFont("", 11, QFont.Weight.Bold))
        self.generate_btn.setStyleSheet(
            "QPushButton:enabled{background:#16a34a;color:white}")
        self.generate_btn.clicked.connect(self._on_generate)
        arow2.addWidget(self.generate_btn, 1)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._on_pause)
        arow2.addWidget(self.pause_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        arow2.addWidget(self.cancel_btn)
        layout.addLayout(arow2)

        # Progress + cost + count
        srow = QHBoxLayout()
        self.count_label = QLabel("")
        srow.addWidget(self.count_label)
        srow.addStretch(1)
        self.cost_label = QLabel("Cost: $0.0000")
        srow.addWidget(self.cost_label)
        layout.addLayout(srow)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m  (%p%)")
        layout.addWidget(self.progress_bar)

        # Failures list with retry
        fail_box = QGroupBox("Failures (click filename to retry)")
        fl = QVBoxLayout(fail_box)
        self.failure_list = QListWidget()
        self.failure_list.setMaximumHeight(110)
        self.failure_list.itemDoubleClicked.connect(self._on_retry_clicked)
        fl.addWidget(self.failure_list)
        layout.addWidget(fail_box)

        # Log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Monospace", 9))
        self.log.setMaximumHeight(140)
        layout.addWidget(self.log)

        self._update_count()

    # ─── Helpers ───

    def _selected_views(self) -> list[str]:
        return [k for k, cb in self.view_checks.items() if cb.isChecked()]

    def _selected_poses(self) -> list[dict]:
        out: list[dict] = []
        for i in range(self.pose_list.count()):
            item = self.pose_list.item(i)
            entry = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(entry, dict) and item.checkState() == Qt.CheckState.Checked:
                out.append(entry)
        return out

    def _set_all_poses(self, on: bool):
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for i in range(self.pose_list.count()):
            item = self.pose_list.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(state)

    def _update_count(self):
        v = len(self._selected_views())
        p = len(self._selected_poses())
        total = v * p
        self.progress_bar.setMaximum(max(total, 1))
        quality = settings_manager.get_openai_quality()
        per = settings_manager.OPENAI_PRICING.get(quality, 0.042) + 0.005
        est = total * per
        self.count_label.setText(
            f"{v} view(s) × {p} pose(s) = {total} image(s).  Est: ${est:.2f} (q={quality})")

    # ─── Generation ───

    def is_busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _on_generate(self):
        if self.is_busy():
            return
        if not (get_anthropic_key() and get_openai_key()):
            QMessageBox.warning(self, "Missing API keys",
                                "Anthropic and OpenAI keys are required. Configure in Settings tab.")
            return
        archetype = self.archetype_combo.currentData()
        views = self._selected_views()
        poses = self._selected_poses()
        if not views or not poses:
            QMessageBox.information(self, "Pick something",
                                    "Select at least one view and one pose.")
            return

        total = len(views) * len(poses)
        quality = settings_manager.get_openai_quality()
        per = settings_manager.OPENAI_PRICING.get(quality, 0.042) + 0.005
        est = total * per
        out_dir = _default_output_dir() / archetype

        reply = QMessageBox.question(
            self, "Start batch",
            f"Generate {total} images for {archetype}?\n\n"
            f"  Views:    {len(views)}\n"
            f"  Poses:    {len(poses)}\n"
            f"  Quality:  {quality}\n"
            f"  Estimate: ${est:.2f}\n\n"
            f"  Output:   {out_dir}\n\n"
            f"Files that already exist will be skipped.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Ok)
        if reply != QMessageBox.StandardButton.Ok:
            return

        self._start_worker(archetype, views, poses, out_dir)

    def _start_worker(self, archetype: str, views: list[str], poses: list[dict],
                      out_dir: Path):
        self.failure_list.clear()
        self.log.clear()
        self.cost_label.setText("Cost: $0.0000")
        self.progress_bar.setMaximum(len(views) * len(poses) or 1)
        self.progress_bar.setValue(0)

        self.worker = ChatGPTBatchWorker(
            archetype=archetype, views=views, poses=poses, output_dir=out_dir)
        self.worker.log.connect(self._append_log)
        self.worker.progress.connect(self._on_progress)
        self.worker.item_done.connect(self._on_item_done)
        self.worker.item_failed.connect(self._on_item_failed)
        self.worker.finished_batch.connect(self._on_finished)
        self.worker.finished.connect(self._on_thread_finished)
        self._set_running_state(True)
        self._running_total_cost = 0.0
        self._running_archetype = archetype
        self._running_out_dir = out_dir
        self.worker.start()

    def _set_running_state(self, running: bool):
        self.generate_btn.setEnabled(not running)
        self.pause_btn.setEnabled(running)
        self.cancel_btn.setEnabled(running)
        self.archetype_combo.setEnabled(not running)
        for cb in self.view_checks.values():
            cb.setEnabled(not running)
        self.pose_list.setEnabled(not running)
        self.pause_btn.setText("Pause")

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

    def _append_log(self, msg: str):
        self.log.append(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_progress(self, current: int, total: int):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(current)

    def _on_item_done(self, filename: str, cost: float):
        self._running_total_cost += cost
        self.cost_label.setText(f"Cost: ${self._running_total_cost:.4f}")

    def _on_item_failed(self, filename: str, view: str, pose_slug: str, error: str):
        item = QListWidgetItem(f"{filename}   ←  {error[:80]}")
        item.setData(Qt.ItemDataRole.UserRole, {"filename": filename,
                                                "view": view, "pose": pose_slug,
                                                "error": error})
        self.failure_list.addItem(item)

    def _on_retry_clicked(self, item: QListWidgetItem):
        if self.is_busy():
            QMessageBox.information(self, "Busy", "Wait for the current run to finish.")
            return
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        view = data.get("view")
        pose_slug = data.get("pose")
        if not view or not pose_slug:
            return
        # find pose entry
        entry = next(
            (p for p in chatgpt_pose_taxonomy.list_unique_poses() if p["pose"] == pose_slug),
            {"pose": pose_slug, "category": "", "description": pose_slug.replace("_", " ")},
        )
        # remove this row from the failure list and re-run as a 1-item batch
        row = self.failure_list.row(item)
        self.failure_list.takeItem(row)
        self._start_worker(self._running_archetype, [view], [entry], self._running_out_dir)

    def _on_finished(self, success: int, failed: int, total_cost: float):
        self._append_log(
            f"─── batch done: {success} OK, {failed} failed, ${total_cost:.4f} ───")

    def _on_thread_finished(self):
        self.worker = None
        self._set_running_state(False)


# ─────────────────────────────────────────────────────────────────────
# Mode 3 — Custom Pose
# ─────────────────────────────────────────────────────────────────────

class _CustomMode(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.preview.generate_btn.clicked.connect(self._on_generate)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QGroupBox("Custom Pose")
        gl = QVBoxLayout(controls)

        arow = QHBoxLayout()
        arow.addWidget(QLabel("Archetype:"))
        self.archetype_combo = QComboBox()
        for key, meta in ARCHETYPES.items():
            self.archetype_combo.addItem(f"{meta['label']} — {meta['heads']} heads", key)
        arow.addWidget(self.archetype_combo, 1)
        gl.addLayout(arow)

        vrow = QHBoxLayout()
        vrow.addWidget(QLabel("View:"))
        self.view_combo = QComboBox()
        for key, desc in VIEWS.items():
            self.view_combo.addItem(key, key)
        vrow.addWidget(self.view_combo, 1)
        gl.addLayout(vrow)

        orow = QHBoxLayout()
        orow.addWidget(QLabel("Orientation:"))
        self.orientation_combo = QComboBox()
        self.orientation_combo.addItem("auto (Claude decides)", "auto")
        self.orientation_combo.addItem("portrait (1024×1536)", "portrait")
        self.orientation_combo.addItem("landscape (1536×1024)", "landscape")
        orow.addWidget(self.orientation_combo, 1)
        gl.addLayout(orow)

        gl.addWidget(QLabel("Pose description (plain English):"))
        self.pose_edit = QPlainTextEdit()
        self.pose_edit.setPlaceholderText(
            "e.g. contrapposto, weight on right leg, left arm raised holding a sword")
        self.pose_edit.setFixedHeight(80)
        gl.addWidget(self.pose_edit)

        layout.addWidget(controls)
        self.preview = _SinglePreviewPanel()
        layout.addWidget(self.preview, 1)

    def is_busy(self) -> bool:
        return self.preview.is_busy()

    def _on_generate(self):
        if self.is_busy():
            return
        if not (get_anthropic_key() and get_openai_key()):
            QMessageBox.warning(self, "Missing API keys",
                                "Anthropic and OpenAI keys are required. Configure in Settings tab.")
            return
        pose = self.pose_edit.toPlainText().strip()
        if not pose:
            QMessageBox.information(self, "Pose missing",
                                    "Enter a plain-English pose description.")
            return
        archetype = self.archetype_combo.currentData()
        view = self.view_combo.currentData()
        orientation = self.orientation_combo.currentData()
        hint = f"{archetype}_{view}_custom"
        self.preview.start(archetype, view, pose, orientation, hint)


# ─────────────────────────────────────────────────────────────────────
# Outer tab — combines the three modes
# ─────────────────────────────────────────────────────────────────────

class ChatGPTBaseTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header = QLabel("Chat_GPT — Base Mannequin Generator")
        header.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(header)

        sub = QLabel("Claude engineers the 9LivesK9 prompt. OpenAI gpt-image-1 renders.")
        sub.setStyleSheet("color: #666;")
        layout.addWidget(sub)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        self.modes = QTabWidget()
        self.single_mode = _SingleMode()
        self.batch_mode = _BatchMode()
        self.custom_mode = _CustomMode()
        self.modes.addTab(self.single_mode, "1. Single")
        self.modes.addTab(self.batch_mode, "2. Batch (LoRA dataset)")
        self.modes.addTab(self.custom_mode, "3. Custom Pose")
        layout.addWidget(self.modes, 1)

    def is_busy(self) -> bool:
        return (self.single_mode.is_busy()
                or self.batch_mode.is_busy()
                or self.custom_mode.is_busy())
