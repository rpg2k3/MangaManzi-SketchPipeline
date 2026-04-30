"""Library tab — browse generated mannequins, references, and character sketches.
Includes per-file regeneration for generated content (not references).
"""

import json
import os
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QListWidget, QListWidgetItem, QSplitter,
    QLineEdit, QMessageBox, QFrame,
)
from PySide6.QtGui import QFont, QPixmap

from app.archetype_scanner import scan_archetypes, OUTPUT_DIR, BASES_CSP_DIR, BASES_GPT_DIR
from app.workers.single_mannequin_worker import SingleMannequinWorker
from app import settings_manager

APP_DIR = Path(__file__).parent.parent.parent
CHARACTERS_DIR = APP_DIR / "characters"
POSE_LIBRARY_PATH = APP_DIR / "data" / "pose_library.json"

# Content type metadata
CONTENT_TYPES = {
    "mannequins": {"label": "Generated Mannequins", "icon": "\U0001F5BC", "readonly": False},
    "csp": {"label": "Reference: CSP Anatomy", "icon": "\U0001F4D0", "readonly": True},
    "gpt": {"label": "Reference: GPT Style", "icon": "\u2728", "readonly": True},
    "sketches": {"label": "Character Sketches", "icon": "\u270F\uFE0F", "readonly": False},
}


class LibraryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.regen_worker = None
        self._pose_data = {}
        self._archetypes = []
        self._load_pose_data()
        self._build_ui()
        self.refresh()

    def _load_pose_data(self):
        if POSE_LIBRARY_PATH.exists():
            self._pose_data = json.loads(POSE_LIBRARY_PATH.read_text())

    def _build_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel("Library Browser")
        header.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(header)

        # Source selector row
        srow = QHBoxLayout()
        srow.addWidget(QLabel("Browse:"))
        self.source_combo = QComboBox()
        for key, meta in CONTENT_TYPES.items():
            self.source_combo.addItem(f"{meta['icon']} {meta['label']}", key)
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        srow.addWidget(self.source_combo, 1)

        srow.addWidget(QLabel("Archetype:"))
        self.arch_combo = QComboBox()
        self.arch_combo.currentIndexChanged.connect(self._load_files)
        srow.addWidget(self.arch_combo, 1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        srow.addWidget(refresh_btn)
        layout.addLayout(srow)

        # Filter + sort
        frow = QHBoxLayout()
        frow.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Type to filter...")
        self.filter_edit.textChanged.connect(self._apply_filter)
        frow.addWidget(self.filter_edit, 1)
        frow.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Filename \u2191", "Date Modified \u2193", "Pose Category"])
        self.sort_combo.currentIndexChanged.connect(self._load_files)
        frow.addWidget(self.sort_combo)
        layout.addLayout(frow)

        # Source info
        self.source_info = QLabel("")
        self.source_info.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.source_info)

        # Splitter: list + preview
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.file_list = QListWidget()
        self.file_list.currentItemChanged.connect(self._on_file_selected)
        splitter.addWidget(self.file_list)

        # Preview panel
        preview = QWidget()
        pl = QVBoxLayout(preview)

        self.preview_label = QLabel("Select an image")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(300, 400)
        self.preview_label.setStyleSheet("border: 1px solid #ccc; background: #f5f5f5;")
        pl.addWidget(self.preview_label)

        self.path_label = QLabel("")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_label.setWordWrap(True)
        pl.addWidget(self.path_label)

        self.file_info_label = QLabel("")
        self.file_info_label.setStyleSheet("color: #555;")
        pl.addWidget(self.file_info_label)

        # Action buttons
        btn_row = QHBoxLayout()
        self.regen_btn = QPushButton("Regenerate This Pose")
        self.regen_btn.setMinimumHeight(35)
        self.regen_btn.setFont(QFont("", 10, QFont.Weight.Bold))
        self.regen_btn.setStyleSheet(
            "QPushButton:enabled{background:#FF9800;color:white}"
            "QPushButton:disabled{background:#ccc}")
        self.regen_btn.setEnabled(False)
        self.regen_btn.clicked.connect(self._on_regenerate)
        btn_row.addWidget(self.regen_btn)

        self.restore_btn = QPushButton("Restore Previous")
        self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self._on_restore)
        btn_row.addWidget(self.restore_btn)

        open_btn = QPushButton("Open Folder")
        open_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(open_btn)

        copy_btn = QPushButton("Copy Path")
        copy_btn.clicked.connect(self._copy_path)
        btn_row.addWidget(copy_btn)
        pl.addLayout(btn_row)

        splitter.addWidget(preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

    # ─── Data loading ───

    def refresh(self):
        self._archetypes = scan_archetypes()
        self._refresh_arch_combo()
        self._load_files()

    def _refresh_arch_combo(self):
        self.arch_combo.blockSignals(True)
        current = self.arch_combo.currentData()
        self.arch_combo.clear()

        source = self.source_combo.currentData() or "mannequins"

        if source == "sketches":
            # List character folders
            if CHARACTERS_DIR.exists():
                for d in sorted(CHARACTERS_DIR.iterdir()):
                    if d.is_dir() and (d / "sketches").exists():
                        self.arch_combo.addItem(d.name, str(d / "sketches"))
        else:
            for arch in self._archetypes:
                self.arch_combo.addItem(arch["folder_name"], arch["folder_name"])

        # Restore selection
        for i in range(self.arch_combo.count()):
            if self.arch_combo.itemData(i) == current:
                self.arch_combo.setCurrentIndex(i)
                break
        self.arch_combo.blockSignals(False)

    def _get_scan_dir(self) -> Path | None:
        source = self.source_combo.currentData() or "mannequins"
        arch_data = self.arch_combo.currentData()
        if not arch_data:
            return None

        if source == "mannequins":
            return OUTPUT_DIR / arch_data
        elif source == "csp":
            return BASES_CSP_DIR / arch_data
        elif source == "gpt":
            return BASES_GPT_DIR / arch_data
        elif source == "sketches":
            return Path(arch_data)
        return None

    def _on_source_changed(self):
        self._refresh_arch_combo()
        self._load_files()

    def _load_files(self):
        self.file_list.clear()
        self.preview_label.clear()
        self.preview_label.setText("Select an image")
        self.path_label.setText("")
        self.file_info_label.setText("")
        self.regen_btn.setEnabled(False)
        self.restore_btn.setEnabled(False)

        scan_dir = self._get_scan_dir()
        source = self.source_combo.currentData() or "mannequins"
        meta = CONTENT_TYPES.get(source, {})

        if not scan_dir or not scan_dir.exists():
            if source == "mannequins":
                self.source_info.setText("No mannequins generated yet. Use the Mannequin Generation tab.")
            elif source == "csp":
                self.source_info.setText(f"No CSP references found at {BASES_CSP_DIR}")
            elif source == "gpt":
                self.source_info.setText(f"No GPT references found at {BASES_GPT_DIR}")
            elif source == "sketches":
                self.source_info.setText("No character sketches found.")
            return

        # Collect files
        files = list(scan_dir.glob("*.png")) + list(scan_dir.glob("*.PNG"))
        # Exclude _previous/ subfolder
        files = [f for f in files if "_previous" not in str(f)]

        # Sort
        sort_mode = self.sort_combo.currentIndex()
        if sort_mode == 1:  # Date modified desc
            files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        elif sort_mode == 2:  # Pose category
            files.sort(key=lambda f: self._get_pose_category(f.stem))
        else:
            files.sort()

        icon_char = meta.get("icon", "")
        for img_path in files:
            item = QListWidgetItem(f"{icon_char} {img_path.name}")
            item.setData(Qt.ItemDataRole.UserRole, str(img_path))
            self.file_list.addItem(item)

        self.source_info.setText(f"Browsing: {meta.get('label', source)} — {len(files)} files in {scan_dir}")
        self._apply_filter()

    def _get_pose_category(self, stem: str) -> str:
        for p in self._pose_data.get("poses", []):
            if p.get("filename", "").replace(".png", "") == stem:
                return p.get("category", "zzz")
        return "zzz"

    def _apply_filter(self):
        text = self.filter_edit.text().lower()
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            item.setHidden(text not in item.text().lower())

    # ─── Preview + actions ───

    def _on_file_selected(self, current, previous):
        if not current:
            return
        path_str = current.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        path = Path(path_str)

        if path.exists():
            pixmap = QPixmap(str(path))
            scaled = pixmap.scaled(400, 550, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            self.preview_label.setPixmap(scaled)
            self.path_label.setText(str(path))

            # File info
            stat = path.stat()
            from datetime import datetime
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            size_kb = stat.st_size / 1024
            self.file_info_label.setText(f"Modified: {mtime}  |  Size: {size_kb:.0f} KB")
        else:
            self.preview_label.clear()
            self.preview_label.setText("File not found")
            self.path_label.setText(str(path))
            self.file_info_label.setText("")

        # Enable/disable action buttons based on content type
        source = self.source_combo.currentData() or "mannequins"
        is_readonly = CONTENT_TYPES.get(source, {}).get("readonly", True)
        regen_busy = self.regen_worker is not None and self.regen_worker.isRunning()

        self.regen_btn.setEnabled(not is_readonly and not regen_busy and path.exists())
        if is_readonly:
            self.regen_btn.setToolTip("Reference files are read-only")
        else:
            self.regen_btn.setToolTip("")

        prev_path = path.parent / "_previous" / path.name
        self.restore_btn.setEnabled(not is_readonly and prev_path.exists() and not regen_busy)

    def _open_folder(self):
        text = self.path_label.text()
        if text:
            folder = str(Path(text).parent)
            os.system(f'xdg-open "{folder}" &')

    def _copy_path(self):
        from PySide6.QtWidgets import QApplication
        text = self.path_label.text()
        if text:
            QApplication.clipboard().setText(text)

    # ─── Regeneration ───

    def _on_regenerate(self):
        path_str = self.path_label.text()
        if not path_str:
            return
        path = Path(path_str)
        source = self.source_combo.currentData() or "mannequins"

        if source == "mannequins":
            self._regen_mannequin(path)
        elif source == "sketches":
            QMessageBox.information(self, "Not Yet", "Sketch regeneration from Library coming soon.")

    def _regen_mannequin(self, path: Path):
        # Find matching pose and archetype
        filename = path.name
        pose = None
        for p in self._pose_data.get("poses", []):
            if p["filename"] == filename:
                pose = p
                break
        if not pose:
            QMessageBox.warning(self, "Unknown Pose", f"Cannot find pose data for {filename}")
            return

        arch_name = self.arch_combo.currentData()
        arch = None
        for a in self._archetypes:
            if a["folder_name"] == arch_name:
                arch = a
                break
        if not arch or not arch["complete"]:
            QMessageBox.warning(self, "Incomplete Archetype", "Both reference layers required.")
            return

        reply = QMessageBox.question(
            self, "Regenerate Pose",
            f"Regenerate {filename}?\n\nPrevious version will be backed up to _previous/.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Backup
        prev_dir = path.parent / "_previous"
        if path.exists():
            prev_dir.mkdir(parents=True, exist_ok=True)
            prev_path = prev_dir / filename
            if prev_path.exists():
                prev_path.unlink()
            shutil.copy2(path, prev_path)
            path.unlink()

        self.regen_worker = SingleMannequinWorker(
            pose=pose, archetype=arch, output_dir=path.parent)
        self.regen_worker.done.connect(self._on_regen_done)
        self.regen_worker.failed.connect(self._on_regen_failed)
        self.regen_worker.start()

        self.regen_btn.setEnabled(False)
        self.file_info_label.setText("Regenerating...")

    def _on_regen_done(self, num, filename, cost):
        self.regen_worker = None
        self.file_info_label.setText(f"Regenerated (${cost:.4f})")
        self._load_files()

    def _on_regen_failed(self, num, filename, error):
        self.regen_worker = None
        # Restore backup
        path = Path(self.path_label.text())
        prev_path = path.parent / "_previous" / path.name
        if prev_path.exists() and not path.exists():
            shutil.copy2(prev_path, path)
        self.file_info_label.setText(f"Failed: {error[:80]}")
        self._load_files()

    def _on_restore(self):
        path_str = self.path_label.text()
        if not path_str:
            return
        path = Path(path_str)
        prev_path = path.parent / "_previous" / path.name

        if not prev_path.exists():
            return

        reply = QMessageBox.question(
            self, "Restore Previous",
            f"Restore previous version of {path.name}?\nCurrent version will be lost.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        if reply != QMessageBox.StandardButton.Yes:
            return

        if path.exists():
            temp = path.with_suffix(".tmp")
            path.rename(temp)
            prev_path.rename(path)
            temp.rename(prev_path)
        else:
            prev_path.rename(path)

        self._load_files()
