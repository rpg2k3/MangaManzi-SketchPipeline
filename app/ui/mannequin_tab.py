"""Mannequin Generation tab — batch-only workflow with pose selection."""

import json
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QProgressBar, QTextEdit, QMessageBox,
)
from PySide6.QtGui import QFont

from app.state import GenerationState
from app.workers.mannequin_worker import MannequinWorker
from app.keyring_store import get_openai_key, get_google_key
from app import settings_manager
from app.archetype_scanner import scan_archetypes, OUTPUT_DIR
from app.knowledge_loader import knowledge_files_present

APP_DIR = Path(__file__).parent.parent.parent
POSE_LIBRARY_PATH = APP_DIR / "data" / "pose_library.json"


class MannequinTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pose_data = {}
        self.archetypes = []
        self.batch_worker = None
        self.state = GenerationState.IDLE
        self.total_cost = 0.0
        self.success_count = 0
        self.fail_count = 0
        self._load_pose_data()
        self._build_ui()
        self._refresh_archetypes()
        self._update_ui()

    def _load_pose_data(self):
        if POSE_LIBRARY_PATH.exists():
            self.pose_data = json.loads(POSE_LIBRARY_PATH.read_text())

    def _get_all_poses(self):
        return self.pose_data.get("poses", [])

    def _current_archetype(self):
        idx = self.archetype_combo.currentIndex()
        if 0 <= idx < len(self.archetypes):
            return self.archetypes[idx]
        return None

    def _output_dir(self):
        arch = self._current_archetype()
        if arch:
            return arch.get("output_dir", OUTPUT_DIR / arch["folder_name"])
        return OUTPUT_DIR / "unknown"

    def _has_image_key(self):
        provider = settings_manager.get_mannequin_provider()
        return bool(get_openai_key()) if provider == "openai" else bool(get_google_key())

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header = QLabel("Mannequin Base Generation")
        header.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(header)

        # Archetype selector
        arow = QHBoxLayout()
        arow.addWidget(QLabel("Archetype:"))
        self.archetype_combo = QComboBox()
        self.archetype_combo.setMinimumWidth(350)
        self.archetype_combo.currentIndexChanged.connect(self._on_archetype_changed)
        arow.addWidget(self.archetype_combo, 1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_archetypes)
        arow.addWidget(refresh_btn)
        open_btn = QPushButton("Open Refs")
        open_btn.clicked.connect(self._open_refs_folder)
        arow.addWidget(open_btn)
        layout.addLayout(arow)

        # Reference status
        self.ref_status_label = QLabel()
        self.ref_status_label.setWordWrap(True)
        layout.addWidget(self.ref_status_label)

        # Info + progress
        self.info_label = QLabel()
        layout.addWidget(self.info_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m  (%p%)")
        layout.addWidget(self.progress_bar)

        # Batch controls
        batch_row = QHBoxLayout()
        self.next_btn = QPushButton("Generate Next")
        self.next_btn.setMinimumHeight(40)
        self.next_btn.setFont(QFont("", 11, QFont.Weight.Bold))
        self.next_btn.setStyleSheet("QPushButton:enabled{background:#4CAF50;color:white}")
        self.next_btn.clicked.connect(self._on_next)
        batch_row.addWidget(self.next_btn, 1)

        self.auto_btn = QPushButton("Start Auto-Generation")
        self.auto_btn.setMinimumHeight(40)
        self.auto_btn.setFont(QFont("", 11, QFont.Weight.Bold))
        self.auto_btn.clicked.connect(self._on_auto)
        batch_row.addWidget(self.auto_btn, 1)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._on_pause)
        batch_row.addWidget(self.pause_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        batch_row.addWidget(self.cancel_btn)
        layout.addLayout(batch_row)

        # Log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Monospace", 9))
        layout.addWidget(self.log, 1)

    # ─── Archetype management ───

    def _refresh_archetypes(self):
        self.archetypes = scan_archetypes()
        self.archetype_combo.blockSignals(True)
        self.archetype_combo.clear()
        for arch in self.archetypes:
            if arch["complete"]:
                icon = "\u2713"
            else:
                icon = f"\u26A0 CSP {arch['csp_count']}/6, GPT {arch['gpt_count']}/6"
            label = f"{icon} {arch['folder_name']} \u2014 {arch['label']} ({arch['age']}, {arch['head_count']} heads)"
            self.archetype_combo.addItem(label)
        self.archetype_combo.blockSignals(False)
        if self.archetypes:
            self.archetype_combo.setCurrentIndex(0)
        self._on_archetype_changed()

    def _on_archetype_changed(self):
        arch = self._current_archetype()
        if not arch:
            self.ref_status_label.setText("No archetypes found. Add folders to bases/csp_tvd/ and bases/gpt_tvd/")
            return
        csp = arch.get("csp_references", {})
        gpt = arch.get("gpt_references", {})
        csp_icons = " ".join("\u2713" if v in csp else "\u274C" for v in ["front", "back", "side_L", "side_R", "3q_front_L", "3q_front_R"])
        gpt_icons = " ".join("\u2713" if v in gpt else "\u274C" for v in ["front", "back", "side_L", "side_R", "3q_front_L", "3q_front_R"])
        self.ref_status_label.setText(
            f"CSP Anatomy: {arch['csp_count']}/6 [{csp_icons}]  |  "
            f"GPT Style: {arch['gpt_count']}/6 [{gpt_icons}]  |  "
            f"Status: {arch['status']}")
        self._update_ui()

    def _open_refs_folder(self):
        arch = self._current_archetype()
        if arch:
            os.system(f'xdg-open "{arch["csp_dir"]}" &')

    # ─── UI state ───

    def _update_ui(self):
        poses = self._get_all_poses()
        output_dir = self._output_dir()
        existing = sum(1 for p in poses if (output_dir / p["filename"]).exists())
        total = len(poses)
        remaining = total - existing

        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(existing)

        provider = settings_manager.get_mannequin_provider()
        quality = settings_manager.get_openai_quality()
        est = settings_manager.estimate_mannequin_cost(remaining)
        self.info_label.setText(
            f"Poses: {total}  |  Generated: {existing}/{total}  |  "
            f"Failed: {self.fail_count}  |  "
            f"Provider: {provider.title()} ({quality})  |  "
            f"Est: ${est:.2f}")

        idle = self.state == GenerationState.IDLE
        paused = self.state == GenerationState.PAUSED
        arch = self._current_archetype()
        knowledge_ok, _ = knowledge_files_present()
        can_gen = bool(arch and arch.get("complete") and self._has_image_key() and knowledge_ok)

        self.next_btn.setEnabled(bool((idle or paused) and can_gen and remaining > 0))
        self.auto_btn.setEnabled(bool(idle and can_gen and remaining > 0))
        self.cancel_btn.setEnabled(not idle)
        self.pause_btn.setEnabled(self.state == GenerationState.GENERATING)
        self.archetype_combo.setEnabled(idle)

        if not knowledge_ok:
            self.next_btn.setToolTip("Master prompt knowledge files missing. Check Settings tab.")
            self.auto_btn.setToolTip("Master prompt knowledge files missing. Check Settings tab.")
        else:
            self.next_btn.setToolTip("")
            self.auto_btn.setToolTip("")

        if paused:
            self.pause_btn.setText("Resume")
            self.pause_btn.setEnabled(True)
        else:
            self.pause_btn.setText("Pause")

    # ─── Batch generation ───

    def _get_remaining_poses(self):
        output_dir = self._output_dir()
        return [p for p in self._get_all_poses() if not (output_dir / p["filename"]).exists()]

    def _on_next(self):
        remaining = self._get_remaining_poses()
        if not remaining:
            QMessageBox.information(self, "Done", "All poses generated!")
            return
        self._start_batch([remaining[0]])

    def _on_auto(self):
        remaining = self._get_remaining_poses()
        if not remaining:
            QMessageBox.information(self, "Done", "All poses generated!")
            return

        arch = self._current_archetype()
        total = len(remaining)
        provider = settings_manager.get_mannequin_provider()
        model = settings_manager.get_mannequin_model()
        quality = settings_manager.get_openai_quality()
        est = settings_manager.estimate_mannequin_cost(total)
        quality_line = f" (quality: {quality})" if provider == "openai" else ""
        csp_ok = f"{arch['csp_count']}/6 \u2713" if arch['csp_count'] == 6 else f"{arch['csp_count']}/6 \u26A0"
        gpt_ok = f"{arch['gpt_count']}/6 \u2713" if arch['gpt_count'] == 6 else f"{arch['gpt_count']}/6 \u26A0"

        reply = QMessageBox.question(
            self, "Start Auto-Generation",
            f"About to generate {total} mannequin images for {arch['folder_name']}.\n\n"
            f"Anatomy reference: CSP layer ({csp_ok})\n"
            f"Style reference:   GPT layer ({gpt_ok})\n"
            f"Provider: {provider.title()} {model}{quality_line}\n"
            f"Estimated cost: ${est:.2f}\n\n"
            f"Output folder: {self._output_dir()}\n\n"
            f"Proceed?",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Yes)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._start_batch(remaining)

    def _start_batch(self, poses):
        arch = self._current_archetype()
        if not arch:
            return
        output_dir = self._output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)

        self.batch_worker = MannequinWorker(
            poses=poses, archetype=arch, output_dir=output_dir)
        self.batch_worker.log.connect(self._on_log)
        self.batch_worker.pose_done.connect(self._on_pose_done)
        self.batch_worker.pose_failed.connect(self._on_pose_failed)
        self.batch_worker.progress.connect(lambda c, t: None)
        self.batch_worker.finished_batch.connect(self._on_finished)
        self.state = GenerationState.GENERATING
        self._update_ui()
        self.batch_worker.start()

    def _on_pause(self):
        if self.state == GenerationState.GENERATING and self.batch_worker:
            self.batch_worker.set_paused(True)
            self.state = GenerationState.PAUSED
            self.log.append("\u2500" * 40 + " PAUSED")
            self._update_ui()
        elif self.state == GenerationState.PAUSED and self.batch_worker:
            self.batch_worker.set_paused(False)
            self.state = GenerationState.GENERATING
            self.log.append("\u2500" * 40 + " RESUMED")
            self._update_ui()

    def _on_cancel(self):
        if self.batch_worker:
            self.batch_worker.request_stop()

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

    def _on_finished(self, success, failed):
        self.state = GenerationState.IDLE
        self.batch_worker = None
        self.log.append(f"{'─'*50}\nBatch done: {success} OK, {failed} failed, ${self.total_cost:.4f}")
        self._update_ui()

    def is_busy(self):
        return self.state != GenerationState.IDLE
