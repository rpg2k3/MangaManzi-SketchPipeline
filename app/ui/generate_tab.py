"""Generate workspace — scene inputs on the left, output + critique on the right."""

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QIntValidator, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolBox,
    QVBoxLayout,
    QWidget,
)

from app import critique as critique_pkg
from app import sheets
from app.pipeline import PipelineRequest, PipelineResult
from app.ui.taxonomy import ARCHETYPES, VIEWS, archetype_label, list_poses
from app.workers.pipeline_worker import PipelineWorker

INPUTS_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "inputs"

_DRIFT_STYLE = "background-color: #c33; color: white; padding: 4px 8px; border-radius: 3px;"
_SUCCESS_STYLE = "background-color: #393; color: white; padding: 4px 8px; border-radius: 3px;"
_DELTA_STYLE = "background-color: #336; color: white; padding: 4px 8px; border-radius: 3px;"
_BADGE_BOX = "QLabel { margin: 2px; }"


def _badge(text: str, style: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(style + " " + _BADGE_BOX)
    lbl.setWordWrap(True)
    lbl.setMaximumWidth(380)
    return lbl


class GenerateTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._skeleton_path: Path | None = None
        self._depth_path: Path | None = None
        self._worker: PipelineWorker | None = None
        self._last_result: PipelineResult | None = None
        self._build_ui()
        self.refresh_sheet_list()

    # ── Build ──

    def _build_ui(self):
        outer = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([420, 700])

    def _build_left(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        h = QLabel("Generate")
        h.setFont(QFont("", 14, QFont.Weight.Bold))
        v.addWidget(h)

        # Subject — toggled by Mode (Stage 1 = archetype only; Full = sheet)
        self.subject_stage1 = QGroupBox("Subject")
        sf1 = QFormLayout(self.subject_stage1)
        self.archetype_combo = QComboBox()
        for code, label, _ in ARCHETYPES:
            self.archetype_combo.addItem(label, code)
        sf1.addRow("Archetype:", self.archetype_combo)
        v.addWidget(self.subject_stage1)

        self.subject_full = QGroupBox("Subject")
        sf2 = QFormLayout(self.subject_full)
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentIndexChanged.connect(self._on_sheet_changed)
        sf2.addRow("Sheet:", self.sheet_combo)
        self.sheet_archetype_label = QLabel("—")
        self.sheet_archetype_label.setStyleSheet("color: #666;")
        sf2.addRow("Archetype:", self.sheet_archetype_label)
        v.addWidget(self.subject_full)
        self.subject_full.setVisible(False)

        # Pose / view
        pose_group = QGroupBox("Pose")
        pf = QFormLayout(pose_group)
        self.view_combo = QComboBox()
        for view in VIEWS:
            self.view_combo.addItem(view, view)
        pf.addRow("View:", self.view_combo)
        self.pose_combo = QComboBox()
        for pose in list_poses():
            self.pose_combo.addItem(pose, pose)
        pf.addRow("Pose:", self.pose_combo)
        v.addWidget(pose_group)

        # Inputs (optional — only for pose-locking Stage 1)
        inputs = QGroupBox("Reference Images (optional — for specific poses only)")
        inputs.setToolTip(
            "Leave empty to let the LoRA generate a default contrapposto pose. "
            "Provide skeleton + depth maps only when you need a specific pose "
            "(combat, foreshortening, dynamic action, etc.)."
        )
        inf = QFormLayout(inputs)

        self.skeleton_label = QLabel("(not selected — optional)")
        self.skeleton_label.setStyleSheet("color: #888;")
        skel_row = QHBoxLayout()
        skel_row.addWidget(self.skeleton_label, 1)
        skel_btn = QPushButton("Browse…")
        skel_btn.clicked.connect(self._pick_skeleton)
        skel_row.addWidget(skel_btn)
        skel_clear = QPushButton("Clear")
        skel_clear.clicked.connect(self._clear_skeleton)
        skel_row.addWidget(skel_clear)
        inf.addRow("Skeleton (OpenPose):", skel_row)

        self.depth_label = QLabel("(not selected — optional)")
        self.depth_label.setStyleSheet("color: #888;")
        depth_row = QHBoxLayout()
        depth_row.addWidget(self.depth_label, 1)
        depth_btn = QPushButton("Browse…")
        depth_btn.clicked.connect(self._pick_depth)
        depth_row.addWidget(depth_btn)
        depth_clear = QPushButton("Clear")
        depth_clear.clicked.connect(self._clear_depth)
        depth_row.addWidget(depth_clear)
        inf.addRow("Depth map:", depth_row)
        v.addWidget(inputs)

        # Run options
        run_group = QGroupBox("Run")
        rf = QFormLayout(run_group)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Stage 1 only — base mannequin", 1)
        self.mode_combo.addItem("Full pipeline (1–4) — with critique", 4)
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        rf.addRow("Mode:", self.mode_combo)

        self.hp_checkbox = QCheckBox("Use High Priority (≈2× credit cost)")
        rf.addRow(self.hp_checkbox)

        self.seed_edit = QLineEdit()
        self.seed_edit.setPlaceholderText("(empty = random — set for reproducible runs)")
        self.seed_edit.setValidator(QIntValidator(0, 2_147_483_647))
        rf.addRow("Seed:", self.seed_edit)

        v.addWidget(run_group)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setMinimumHeight(36)
        self.generate_btn.setFont(QFont("", 11, QFont.Weight.Bold))
        self.generate_btn.clicked.connect(self._on_generate)
        v.addWidget(self.generate_btn)

        # Log
        log_group = QGroupBox("Log")
        lg = QVBoxLayout(log_group)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(140)
        self.log_view.setFont(QFont("Monospace", 9))
        lg.addWidget(self.log_view)
        v.addWidget(log_group)

        v.addStretch()
        return w

    def _build_right(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        h = QLabel("Output")
        h.setFont(QFont("", 14, QFont.Weight.Bold))
        v.addWidget(h)

        # Image preview
        preview_group = QGroupBox("Image")
        pl = QVBoxLayout(preview_group)
        self.image_stage_label = QLabel("(no output yet)")
        self.image_stage_label.setStyleSheet("color: #666; font-style: italic;")
        pl.addWidget(self.image_stage_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(360)
        self.image_label = QLabel("Run a generation to see output here.")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(QSize(384, 360))
        self.image_label.setStyleSheet("background: #222; color: #888;")
        scroll.setWidget(self.image_label)
        pl.addWidget(scroll, 1)
        v.addWidget(preview_group, 1)

        # Critique
        self.critique_group = QGroupBox("Critique")
        cl = QVBoxLayout(self.critique_group)

        self.drifts_label = QLabel("Drifts:")
        self.drifts_label.setFont(QFont("", 10, QFont.Weight.Bold))
        cl.addWidget(self.drifts_label)
        self.drifts_container = QWidget()
        self.drifts_layout = QVBoxLayout(self.drifts_container)
        self.drifts_layout.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.drifts_container)

        self.successes_label = QLabel("Successes:")
        self.successes_label.setFont(QFont("", 10, QFont.Weight.Bold))
        cl.addWidget(self.successes_label)
        self.successes_container = QWidget()
        self.successes_layout = QVBoxLayout(self.successes_container)
        self.successes_layout.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.successes_container)

        self.deltas_label = QLabel("Suggested Prompt Deltas:")
        self.deltas_label.setFont(QFont("", 10, QFont.Weight.Bold))
        cl.addWidget(self.deltas_label)
        self.deltas_container = QWidget()
        self.deltas_layout = QVBoxLayout(self.deltas_container)
        self.deltas_layout.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.deltas_container)

        v.addWidget(self.critique_group)

        # Regenerate / manual feedback
        regen = QGroupBox("Regenerate")
        rl = QVBoxLayout(regen)

        self.feedback_edit = QPlainTextEdit()
        self.feedback_edit.setPlaceholderText(
            "Optional manual feedback (e.g. 'eyes too far apart'). "
            "Merged into the next prompt with priority over auto-detected drifts."
        )
        self.feedback_edit.setMaximumHeight(70)
        rl.addWidget(self.feedback_edit)

        regen_row = QHBoxLayout()
        self.regenerate_btn = QPushButton("Regenerate with corrections")
        self.regenerate_btn.clicked.connect(self._on_regenerate)
        self.regenerate_btn.setEnabled(False)
        regen_row.addWidget(self.regenerate_btn)
        rl.addLayout(regen_row)

        v.addWidget(regen)

        # Iteration history
        history_group = QGroupBox("Iteration History")
        hl = QVBoxLayout(history_group)
        self.history_box = QToolBox()
        self.history_box.setMinimumHeight(160)
        hl.addWidget(self.history_box)
        v.addWidget(history_group, 1)

        return w

    # ── Sheet handling ──

    def refresh_sheet_list(self):
        current = self.sheet_combo.currentData()
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        for sid in sheets.list_ids():
            self.sheet_combo.addItem(sid, sid)
        self.sheet_combo.blockSignals(False)
        if current:
            for i in range(self.sheet_combo.count()):
                if self.sheet_combo.itemData(i) == current:
                    self.sheet_combo.setCurrentIndex(i)
                    break
        self._on_sheet_changed()

    def _on_sheet_changed(self):
        sid = self.sheet_combo.currentData()
        if not sid:
            self.sheet_archetype_label.setText("—")
            self._refresh_history(None, None)
            return
        try:
            sheet = sheets.load(sid)
            self.sheet_archetype_label.setText(archetype_label(sheet.get("archetype") or "?"))
            self._refresh_history(sid, None)
        except Exception:
            self.sheet_archetype_label.setText("—")

    def _on_mode_changed(self):
        is_stage1 = self.mode_combo.currentData() == 1
        self.subject_stage1.setVisible(is_stage1)
        self.subject_full.setVisible(not is_stage1)

    # ── File pickers ──

    def _pick_skeleton(self):
        start = str(INPUTS_ROOT) if INPUTS_ROOT.exists() else str(Path.cwd())
        path, _ = QFileDialog.getOpenFileName(
            self, "Select OpenPose skeleton PNG", start,
            "Images (*.png *.jpg *.jpeg)",
        )
        if path:
            self._skeleton_path = Path(path)
            self.skeleton_label.setText(path)
            self.skeleton_label.setStyleSheet("color: #ccc;")

    def _pick_depth(self):
        start = str(INPUTS_ROOT) if INPUTS_ROOT.exists() else str(Path.cwd())
        path, _ = QFileDialog.getOpenFileName(
            self, "Select depth-map PNG", start,
            "Images (*.png *.jpg *.jpeg)",
        )
        if path:
            self._depth_path = Path(path)
            self.depth_label.setText(path)
            self.depth_label.setStyleSheet("color: #ccc;")

    def _clear_skeleton(self):
        self._skeleton_path = None
        self.skeleton_label.setText("(not selected — optional)")
        self.skeleton_label.setStyleSheet("color: #888;")

    def _clear_depth(self):
        self._depth_path = None
        self.depth_label.setText("(not selected — optional)")
        self.depth_label.setStyleSheet("color: #888;")

    # ── Generate / regenerate ──

    def _on_generate(self):
        self._start_pipeline()

    def _on_regenerate(self):
        if not self._last_result or not self._last_result.scene_id:
            QMessageBox.warning(self, "Nothing to regenerate",
                                "Run a generation first.")
            return
        if self.mode_combo.currentData() == 1:
            QMessageBox.warning(
                self, "Regenerate needs full pipeline",
                "Switch Mode to 'Full pipeline' to regenerate with critique-driven corrections.",
            )
            return
        manual = self.feedback_edit.toPlainText().strip() or None
        sid = self.sheet_combo.currentData()
        scene_id = self._last_result.scene_id
        prior = critique_pkg.recent_iterations(sid, scene_id, n=3)
        prior_critiques = [
            {
                "iteration_index": p.get("iteration_index"),
                "drifts": (p.get("critique") or {}).get("drifts", []),
                "successes": (p.get("critique") or {}).get("successes", []),
                "suggestedPromptDeltas": (p.get("critique") or {}).get("suggestedPromptDeltas", []),
                "manual_feedback": p.get("manual_feedback"),
            }
            for p in prior
        ]
        self._start_pipeline(
            prior_critiques=prior_critiques,
            manual_feedback=manual,
            scene_id=scene_id,
        )

    def _start_pipeline(self, *, prior_critiques=None, manual_feedback=None, scene_id=None):
        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, "Busy", "A pipeline run is already in progress.")
            return

        max_stage = self.mode_combo.currentData()
        is_stage1 = max_stage == 1
        scene_text = "untitled scene"  # pipeline doesn't accept freeform scene text from the UI

        sheet_id: str | None = None
        archetype_code: str | None = None
        if is_stage1:
            archetype_code = self.archetype_combo.currentData()
            if not archetype_code:
                QMessageBox.warning(self, "No archetype",
                                    "Select an archetype first.")
                return
        else:
            sheet_id = self.sheet_combo.currentData()
            if not sheet_id:
                QMessageBox.warning(self, "No sheet",
                                    "Select a sheet for full-pipeline mode.")
                return

        seed_text = self.seed_edit.text().strip()
        seed_val = int(seed_text) if seed_text else None

        req = PipelineRequest(
            sheet_id=sheet_id,
            archetype=archetype_code,
            skeleton_path=self._skeleton_path,
            depth_path=self._depth_path,
            scene_description=scene_text,
            view=self.view_combo.currentData(),
            pose=self.pose_combo.currentData(),
            high_priority=self.hp_checkbox.isChecked(),
            seed=seed_val,
            max_stage=max_stage,
            prior_critiques=prior_critiques,
            scene_id=scene_id,
        )

        self._worker = PipelineWorker(req, manual_feedback=manual_feedback)
        self._worker.log.connect(self._append_log)
        self._worker.done.connect(self._on_pipeline_done)
        self._worker.failed.connect(self._on_pipeline_failed)
        self._set_buttons_running(True)
        subject_str = sheet_id or f"archetype={archetype_code}"
        self._append_log(f"▶ Launch — {subject_str} mode=stages 1–{max_stage} "
                         f"high_priority={req.high_priority} seed={seed_val}")
        self._worker.start()

    def _set_buttons_running(self, running: bool):
        self.generate_btn.setEnabled(not running)
        self.regenerate_btn.setEnabled(
            not running and self._last_result is not None
        )

    # ── Worker callbacks ──

    def _append_log(self, msg: str):
        self.log_view.appendPlainText(msg)

    def _on_pipeline_done(self, result: PipelineResult):
        self._last_result = result
        self._set_buttons_running(False)
        self._show_image(result)
        self._show_critique(result.critique)
        self._refresh_history(self.sheet_combo.currentData(), result.scene_id)

    def _on_pipeline_failed(self, message: str):
        self._set_buttons_running(False)
        self._append_log(f"✗ Failed: {message}")
        QMessageBox.critical(self, "Pipeline failed", message)

    # ── Output rendering ──

    def _show_image(self, result: PipelineResult):
        latest = (
            result.character or result.sketch or result.base
        )
        if latest is None or not latest.output_image_path or not latest.output_image_path.exists():
            self.image_label.setText("(no output)")
            self.image_stage_label.setText("(no output)")
            return
        pix = QPixmap(str(latest.output_image_path))
        if pix.isNull():
            self.image_label.setText(f"Saved to {latest.output_image_path} (preview failed)")
            return
        scaled = pix.scaledToWidth(640, Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.image_label.setMinimumSize(scaled.size())
        stage_names = {1: "Stage 1 — base mannequin", 2: "Stage 2 — sketch pass",
                       3: "Stage 3 — character"}
        self.image_stage_label.setText(
            f"{stage_names.get(latest.stage, str(latest.stage))} • "
            f"{latest.output_image_path}"
        )

    def _show_critique(self, critique: dict | None):
        for layout in (self.drifts_layout, self.successes_layout, self.deltas_layout):
            while layout.count():
                child = layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

        if not critique:
            self.critique_group.setTitle("Critique (not run — increase Mode to ≥4)")
            self.drifts_label.setVisible(False)
            self.successes_label.setVisible(False)
            self.deltas_label.setVisible(False)
            return

        self.critique_group.setTitle("Critique")
        self.drifts_label.setVisible(True)
        self.successes_label.setVisible(True)
        self.deltas_label.setVisible(True)

        for d in critique.get("drifts", []):
            severity = d.get("severity", "?")
            origin = d.get("origin", "auto")
            text = (
                f"[{severity}{' ★ manual' if origin == 'manual' else ''}] "
                f"{d.get('aspect', '?')}: expected '{d.get('expected', '?')}' / "
                f"observed '{d.get('observed', '?')}'"
            )
            self.drifts_layout.addWidget(_badge(text, _DRIFT_STYLE))

        for s in critique.get("successes", []):
            self.successes_layout.addWidget(_badge(s, _SUCCESS_STYLE))

        for d in critique.get("suggestedPromptDeltas", []):
            self.deltas_layout.addWidget(_badge(f"→ {d}", _DELTA_STYLE))

    def _refresh_history(self, sheet_id: str | None, scene_id: str | None):
        # Clear existing pages
        while self.history_box.count():
            self.history_box.removeItem(0)
        if not sheet_id:
            return
        if not scene_id:
            iters = []
        else:
            iters = critique_pkg.recent_iterations(sheet_id, scene_id, n=5)
        if not iters:
            placeholder = QLabel("(no prior iterations for this scene yet)")
            placeholder.setStyleSheet("color: #666; padding: 12px;")
            self.history_box.addItem(placeholder, "(empty)")
            return
        for it in reversed(iters):
            page = QWidget()
            pl = QVBoxLayout(page)
            ts = it.get("ts", "?")
            prompt = (it.get("prompt") or {}).get("prompts") or ""
            crit = it.get("critique") or {}
            n_drifts = len(crit.get("drifts", []))
            n_success = len(crit.get("successes", []))
            manual = it.get("manual_feedback")
            summary = QLabel(
                f"<b>{ts}</b><br>"
                f"Prompt: <code>{prompt[:200]}{'…' if len(prompt) > 200 else ''}</code><br>"
                f"Drifts: {n_drifts} · Successes: {n_success}"
                + (f"<br>Manual: <i>{manual}</i>" if manual else "")
            )
            summary.setWordWrap(True)
            pl.addWidget(summary)
            output = it.get("output_path")
            if output:
                op = QLabel(f"Output: {output}")
                op.setStyleSheet("color: #888; font-family: monospace;")
                op.setWordWrap(True)
                pl.addWidget(op)
            pl.addStretch()
            label = f"#{it.get('iteration_index', '?')} · {ts}"
            self.history_box.addItem(page, label)
