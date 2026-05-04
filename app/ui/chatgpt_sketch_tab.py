"""Chat_GPT — Sketch Over Base tab.

Two image upload slots: base mannequin + character reference sheet.
Both go to OpenAI gpt-image-1 with a fixed line-art-over-blue instruction.
Result shown in-app with a save button.
"""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QGroupBox, QMessageBox, QTextEdit, QScrollArea, QSizePolicy,
)

from app.workers.chatgpt_sketch_worker import ChatGPTSketchWorker
from app.keyring_store import get_openai_key

APP_DIR = Path(__file__).parent.parent.parent
DEFAULT_OUTPUT_DIR = APP_DIR / "output" / "chat_gpt_sketches"

IMAGE_FILTER = "Image (*.png *.jpg *.jpeg *.webp)"


class _UploadSlot(QGroupBox):
    """One labelled image slot with a Browse button and small thumbnail."""

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

    def set_enabled(self, on: bool):
        self.browse_btn.setEnabled(on)


class ChatGPTSketchTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: ChatGPTSketchWorker | None = None
        self.last_image_bytes: bytes = b""
        self._build_ui()
        self._update_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header = QLabel("Chat_GPT — Sketch Over Base")
        header.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(header)

        sub = QLabel("Black ink line art over the blue base. A4 landscape, print friendly.")
        sub.setStyleSheet("color: #666;")
        layout.addWidget(sub)

        slots = QHBoxLayout()
        self.base_slot = _UploadSlot("Image 1 — Base mannequin")
        self.char_slot = _UploadSlot("Image 2 — Character reference sheet")
        slots.addWidget(self.base_slot, 1)
        slots.addWidget(self.char_slot, 1)
        layout.addLayout(slots)

        # Actions
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

        # Preview
        self.preview_label = QLabel("Sketch result will appear here.")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            "QLabel{background:#fafafa;border:1px dashed #ccc;color:#999;padding:8px;}")
        self.preview_label.setMinimumHeight(320)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview_label)
        layout.addWidget(scroll, 1)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Monospace", 9))
        self.log.setMaximumHeight(120)
        layout.addWidget(self.log)

    # ─── State ───

    def is_busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _update_ui(self):
        busy = self.is_busy()
        keys_ok = bool(get_openai_key())
        ready = bool(self.base_slot.path) and bool(self.char_slot.path) and keys_ok
        self.generate_btn.setEnabled(ready and not busy)
        self.save_btn.setEnabled(bool(self.last_image_bytes) and not busy)
        self.base_slot.set_enabled(not busy)
        self.char_slot.set_enabled(not busy)

        if not keys_ok:
            self.generate_btn.setToolTip("OpenAI key required. Configure in Settings tab.")
        elif not ready:
            self.generate_btn.setToolTip("Select both a base image and a character reference.")
        else:
            self.generate_btn.setToolTip("")

    # ─── Generate ───

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
            character_image_path=self.char_slot.path)
        self.worker.log.connect(self._on_log)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_finished)
        self._update_ui()
        self.worker.start()

    def _on_log(self, msg: str):
        self.log.append(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_done(self, image_bytes: bytes, cost: float):
        self.last_image_bytes = image_bytes
        pix = QPixmap()
        if pix.loadFromData(image_bytes, "PNG"):
            self.preview_label.setPixmap(
                pix.scaled(self.preview_label.width(),
                           self.preview_label.height(),
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation))
            self.preview_label.setText("")
        else:
            self.preview_label.setText("(could not decode image)")
        self.log.append(f"--- cost: ${cost:.4f} ---")

    def _on_failed(self, err: str):
        QMessageBox.warning(self, "Sketch Failed", err)
        self.preview_label.setText("Sketch failed — see log below.")

    def _on_finished(self):
        self.worker = None
        self._update_ui()

    # ─── Save ───

    def _on_save(self):
        if not self.last_image_bytes:
            return
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suggested = DEFAULT_OUTPUT_DIR / f"sketch_{ts}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Sketch", str(suggested), "PNG Image (*.png)")
        if not path:
            return
        Path(path).write_bytes(self.last_image_bytes)
        self.log.append(f"Saved → {path}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.last_image_bytes:
            pix = QPixmap()
            if pix.loadFromData(self.last_image_bytes, "PNG"):
                self.preview_label.setPixmap(
                    pix.scaled(self.preview_label.width(),
                               self.preview_label.height(),
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))
