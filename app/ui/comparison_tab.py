"""Comparison tab — side-by-side image viewer with overlay opacity and dimension awareness."""

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QSlider, QSplitter,
)
from PySide6.QtGui import QFont, QPixmap, QPainter, QImage

APP_DIR = Path(__file__).parent.parent.parent
BASES_DIR = APP_DIR / "bases"
CHARACTERS_DIR = APP_DIR / "characters"


class ComparisonTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_a_path = None
        self.image_b_path = None
        self.pixmap_a = None
        self.pixmap_b = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel("Image Comparison (A/B Overlay)")
        header.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(header)

        # ── File selectors ──
        frow = QHBoxLayout()

        # Image A controls
        self.a_btn = QPushButton("Load Image A...")
        self.a_btn.clicked.connect(lambda: self._load_image("A"))
        frow.addWidget(self.a_btn)
        a_quick = QPushButton("Mannequin...")
        a_quick.setToolTip("Quick-load from bases/")
        a_quick.clicked.connect(lambda: self._quick_load("A", "mannequin"))
        frow.addWidget(a_quick)
        self.a_label = QLabel("(none)")
        frow.addWidget(self.a_label, 1)
        self.a_dims = QLabel("")
        frow.addWidget(self.a_dims)

        # Swap button
        swap_btn = QPushButton("\u2194 Swap")
        swap_btn.clicked.connect(self._swap_images)
        frow.addWidget(swap_btn)

        # Image B controls
        self.b_btn = QPushButton("Load Image B...")
        self.b_btn.clicked.connect(lambda: self._load_image("B"))
        frow.addWidget(self.b_btn)
        b_quick = QPushButton("Sketch...")
        b_quick.setToolTip("Quick-load from characters/*/sketches/")
        b_quick.clicked.connect(lambda: self._quick_load("B", "sketch"))
        frow.addWidget(b_quick)
        self.b_label = QLabel("(none)")
        frow.addWidget(self.b_label, 1)
        self.b_dims = QLabel("")
        frow.addWidget(self.b_dims)

        layout.addLayout(frow)

        # Mismatch warning
        self.mismatch_warning = QLabel("")
        self.mismatch_warning.setStyleSheet(
            "background: #FFF3CD; color: #856404; padding: 4px; border-radius: 3px;")
        self.mismatch_warning.setWordWrap(True)
        self.mismatch_warning.setVisible(False)
        layout.addWidget(self.mismatch_warning)

        # Opacity slider
        srow = QHBoxLayout()
        srow.addWidget(QLabel("A"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setMinimum(0)
        self.opacity_slider.setMaximum(100)
        self.opacity_slider.setValue(50)
        self.opacity_slider.valueChanged.connect(self._update_overlay)
        srow.addWidget(self.opacity_slider, 1)
        srow.addWidget(QLabel("B"))
        self.opacity_label = QLabel("50%")
        srow.addWidget(self.opacity_label)
        layout.addLayout(srow)

        # Side-by-side + overlay
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.view_a = QLabel("Image A")
        self.view_a.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view_a.setMinimumSize(250, 350)
        self.view_a.setStyleSheet("border: 1px solid #ccc; background: white;")
        splitter.addWidget(self.view_a)

        self.view_overlay = QLabel("Overlay")
        self.view_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view_overlay.setMinimumSize(250, 350)
        self.view_overlay.setStyleSheet("border: 1px solid #ccc; background: white;")
        splitter.addWidget(self.view_overlay)

        self.view_b = QLabel("Image B")
        self.view_b.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view_b.setMinimumSize(250, 350)
        self.view_b.setStyleSheet("border: 1px solid #ccc; background: white;")
        splitter.addWidget(self.view_b)

        layout.addWidget(splitter, 1)

    def _load_image(self, which, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, f"Select Image {which}", "",
                "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        self._set_image(which, path)

    def _quick_load(self, which, kind):
        if kind == "mannequin":
            start_dir = str(BASES_DIR)
        else:
            start_dir = str(CHARACTERS_DIR)
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select {kind.title()} Image", start_dir,
            "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self._set_image(which, path)

    def _set_image(self, which, path):
        pixmap = QPixmap(path)
        w, h = pixmap.width(), pixmap.height()
        dim_text = f"{w}\u00D7{h}"
        name = Path(path).name

        scaled = pixmap.scaled(400, 550, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)

        if which == "A":
            self.image_a_path = path
            self.pixmap_a = pixmap
            self.a_label.setText(name)
            self.a_dims.setText(dim_text)
            self.view_a.setPixmap(scaled)
        else:
            self.image_b_path = path
            self.pixmap_b = pixmap
            self.b_label.setText(name)
            self.b_dims.setText(dim_text)
            self.view_b.setPixmap(scaled)

        self._check_mismatch()
        self._update_overlay()

    def _swap_images(self):
        a_path, b_path = self.image_a_path, self.image_b_path
        a_pix, b_pix = self.pixmap_a, self.pixmap_b
        self.image_a_path = b_path
        self.image_b_path = a_path
        self.pixmap_a = b_pix
        self.pixmap_b = a_pix

        # Swap labels
        a_name = self.a_label.text()
        b_name = self.b_label.text()
        a_dim = self.a_dims.text()
        b_dim = self.b_dims.text()
        self.a_label.setText(b_name)
        self.b_label.setText(a_name)
        self.a_dims.setText(b_dim)
        self.b_dims.setText(a_dim)

        # Swap view pixmaps
        if self.pixmap_a:
            self.view_a.setPixmap(self.pixmap_a.scaled(
                400, 550, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self.view_a.clear()
            self.view_a.setText("Image A")
        if self.pixmap_b:
            self.view_b.setPixmap(self.pixmap_b.scaled(
                400, 550, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self.view_b.clear()
            self.view_b.setText("Image B")

        self._check_mismatch()
        self._update_overlay()

    def _check_mismatch(self):
        if not self.pixmap_a or not self.pixmap_b:
            self.mismatch_warning.setVisible(False)
            self._color_dims(None)
            return

        ratio_a = self.pixmap_a.width() / self.pixmap_a.height()
        ratio_b = self.pixmap_b.width() / self.pixmap_b.height()
        match = abs(ratio_a - ratio_b) < 0.05

        self._color_dims(match)

        if not match:
            self.mismatch_warning.setText(
                f"\u26A0 Aspect ratios differ \u2014 "
                f"A: {self.pixmap_a.width()}\u00D7{self.pixmap_a.height()} "
                f"({ratio_a:.2f}), "
                f"B: {self.pixmap_b.width()}\u00D7{self.pixmap_b.height()} "
                f"({ratio_b:.2f}). "
                f"Overlay may be misleading.")
            self.mismatch_warning.setVisible(True)
        else:
            self.mismatch_warning.setVisible(False)

    def _color_dims(self, match):
        if match is None:
            self.a_dims.setStyleSheet("color: #666;")
            self.b_dims.setStyleSheet("color: #666;")
        elif match:
            self.a_dims.setStyleSheet("color: #2E7D32; font-weight: bold;")
            self.b_dims.setStyleSheet("color: #2E7D32; font-weight: bold;")
        else:
            self.a_dims.setStyleSheet("color: #C62828; font-weight: bold;")
            self.b_dims.setStyleSheet("color: #C62828; font-weight: bold;")

    def _update_overlay(self):
        opacity_b = self.opacity_slider.value() / 100.0
        self.opacity_label.setText(f"{self.opacity_slider.value()}%")

        if not self.pixmap_a or not self.pixmap_b:
            return

        canvas_w = max(self.pixmap_a.width(), self.pixmap_b.width())
        canvas_h = max(self.pixmap_a.height(), self.pixmap_b.height())
        canvas_size = QSize(canvas_w, canvas_h)

        img_a = self.pixmap_a.toImage().scaled(
            canvas_size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        img_b = self.pixmap_b.toImage().scaled(
            canvas_size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)

        result = QImage(canvas_size, QImage.Format.Format_ARGB32)
        result.fill(Qt.GlobalColor.white)

        a_x = (canvas_w - img_a.width()) // 2
        a_y = (canvas_h - img_a.height()) // 2
        b_x = (canvas_w - img_b.width()) // 2
        b_y = (canvas_h - img_b.height()) // 2

        painter = QPainter(result)
        painter.setOpacity(1.0 - opacity_b)
        painter.drawImage(a_x, a_y, img_a)
        painter.setOpacity(opacity_b)
        painter.drawImage(b_x, b_y, img_b)
        painter.end()

        overlay_pixmap = QPixmap.fromImage(result)
        scaled = overlay_pixmap.scaled(400, 550, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
        self.view_overlay.setPixmap(scaled)
