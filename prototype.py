#!/usr/bin/env python3
"""9LivesK9 Base Pose Library — PyQt6 Prototype (F_adult hardcoded)."""

import base64
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import openai

# --- Paths ---
APP_DIR = Path(__file__).parent
TEMPLATES_DIR = APP_DIR / "templates"
TEMPLATES_PATH = APP_DIR / "prompt_templates.json"
CSP_DIR = APP_DIR / "F_adult-(25+)" / "CSP_6ref-images"
DEFAULT_OUTPUT_DIR = Path.home() / "9LK9-App" / "output" / "F_adult"

# --- CSP reference file mapping ---
CSP_FILES = {
    "front":       CSP_DIR / "front.PNG",
    "side_L":      CSP_DIR / "side_L.PNG",
    "side_R":      CSP_DIR / "side_R.PNG",
    "back":        CSP_DIR / "back.PNG",
    "3q_front_L":  CSP_DIR / "3q_front_L.PNG",
    "3q_front_R":  CSP_DIR / "3q_front_R.PNG",
}

# F_adult head count
HEAD_COUNT = 8


# ─────────────────────────────────────────────────────────────
# Prompt assembly: safety prefix + substitutions + mandatory block
# ─────────────────────────────────────────────────────────────

def load_template_file(name):
    path = TEMPLATES_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


def load_substitutions():
    path = TEMPLATES_DIR / "prompt_substitutions.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("substitutions", [])
    return []


SAFETY_PREFIX = load_template_file("safety_prefix.txt")
SAFETY_PREFIX_STRONG = load_template_file("safety_prefix_strong.txt")
MANDATORY_BLOCK = load_template_file("mandatory_elements.txt")
SUBSTITUTIONS = load_substitutions()


def apply_substitutions(prompt_text):
    """Apply prompt_substitutions.json replacements in order, case-sensitive."""
    for sub in SUBSTITUTIONS:
        prompt_text = prompt_text.replace(sub["find"], sub["replace"])
    return prompt_text


def assemble_prompt(prompt_text, head_count=HEAD_COUNT, safety_prefix=None):
    """Assemble final prompt: safety prefix + substituted prompt + mandatory block."""
    if safety_prefix is None:
        safety_prefix = SAFETY_PREFIX

    substituted = apply_substitutions(prompt_text)
    mandatory = MANDATORY_BLOCK.replace("{HEAD_COUNT}", str(head_count))

    return f"{safety_prefix}\n\n{substituted}\n\n{mandatory}"


def count_substitution_hits(prompts):
    """Count how many prompts each substitution fires on."""
    results = []
    for sub in SUBSTITUTIONS:
        count = sum(1 for p in prompts if sub["find"] in p["prompt"])
        results.append((sub["find"], sub["replace"], count, len(prompts)))
    return results


# ─────────────────────────────────────────────────────────────
# Single image generation worker
# ─────────────────────────────────────────────────────────────

class SingleImageWorker(QThread):
    log_message = pyqtSignal(str)
    image_done = pyqtSignal(int, str, float, int, int, str)  # num, filename, cost, in_tok, out_tok, prefix_used
    image_failed = pyqtSignal(int, str, str)
    anchor_locked = pyqtSignal(str)

    def __init__(self, prompt_data, output_dir, api_key, locked_anchor_path=None):
        super().__init__()
        self.prompt_data = prompt_data
        self.output_dir = Path(output_dir)
        self.api_key = api_key
        self.locked_anchor_path = locked_anchor_path

    def resolve_references(self, ref_keys):
        paths = []
        for key in ref_keys:
            if key == "locked_anchor" and self.locked_anchor_path:
                paths.append(Path(self.locked_anchor_path))
            elif key in CSP_FILES:
                paths.append(CSP_FILES[key])
            else:
                self.log_message.emit(f"  WARNING: Unknown reference key '{key}'")
        return paths

    def run(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)

        num = self.prompt_data["number"]
        filename = self.prompt_data["filename"]
        size = self.prompt_data["size"]
        raw_prompt = self.prompt_data["prompt"]

        self.log_message.emit(f"Generating #{num}: {filename}...")
        self.log_message.emit(f"  Size: {size}  Refs: {self.prompt_data['reference_keys']}")

        ref_paths = self.resolve_references(self.prompt_data["reference_keys"])
        missing = [str(p) for p in ref_paths if not p.exists()]
        if missing:
            self.image_failed.emit(num, filename, f"Missing reference files: {missing}")
            return

        # Assemble prompt with standard safety prefix
        final_prompt = assemble_prompt(raw_prompt, HEAD_COUNT, SAFETY_PREFIX)

        result = self._call_api_with_retry(final_prompt, ref_paths, size)

        # Content-policy retry with strong prefix
        if not result["success"] and result.get("content_policy", False):
            self.log_message.emit("  Content policy rejection — retrying with strong safety prefix...")
            final_prompt_strong = assemble_prompt(raw_prompt, HEAD_COUNT, SAFETY_PREFIX_STRONG)
            result = self._call_api_with_retry(final_prompt_strong, ref_paths, size)
            if result["success"]:
                result["prefix_used"] = "strong"

        if result["success"]:
            output_path = self.output_dir / filename
            img_data = base64.b64decode(result["b64_json"])
            output_path.write_bytes(img_data)

            cost = result.get("cost", 0.20)
            prefix_used = result.get("prefix_used", "standard")
            self.log_message.emit(f"  OK: {filename}  (${cost:.2f}, prefix={prefix_used})")
            self.image_done.emit(num, filename, cost,
                                 result.get("input_tokens", 0),
                                 result.get("output_tokens", 0),
                                 prefix_used)

            if num == 1:
                self.anchor_locked.emit(str(output_path))
                self.log_message.emit(f"  LOCKED as anchor: {filename}")
        else:
            self.image_failed.emit(num, filename, result["error"])

    def _call_api_with_retry(self, prompt_text, ref_paths, size):
        client = openai.OpenAI(api_key=self.api_key)
        max_retries = 4
        backoff_times = [5, 10, 20, 40]

        for attempt in range(max_retries):
            image_files = []
            try:
                for p in ref_paths:
                    image_files.append(open(p, "rb"))

                response = client.images.edit(
                    model="gpt-image-2",
                    image=image_files,
                    prompt=prompt_text,
                    size=size,
                    quality="high",
                    n=1,
                )

                for f in image_files:
                    f.close()

                b64 = response.data[0].b64_json
                usage = getattr(response, "usage", None)
                input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
                output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
                total_tokens = input_tokens + output_tokens
                cost = total_tokens * 0.000004 if total_tokens > 0 else 0.20

                return {
                    "success": True, "b64_json": b64,
                    "input_tokens": input_tokens, "output_tokens": output_tokens,
                    "cost": cost, "prefix_used": "standard",
                }

            except openai.RateLimitError as e:
                for f in image_files:
                    f.close()
                if attempt < max_retries - 1:
                    wait = backoff_times[attempt]
                    self.log_message.emit(f"  Rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    return {"success": False, "error": f"Rate limit after {max_retries} retries: {e}"}

            except openai.APIStatusError as e:
                for f in image_files:
                    f.close()
                # Content policy detection
                err_str = str(e).lower()
                if e.status_code == 400 and ("content_policy" in err_str or "safety" in err_str or "content policy" in err_str):
                    return {"success": False, "error": f"Content policy: {e.message}", "content_policy": True}
                if e.status_code in (500, 502, 503, 504) and attempt < 2:
                    self.log_message.emit(f"  Server error {e.status_code}, retrying in 10s...")
                    time.sleep(10)
                elif e.status_code == 401:
                    return {"success": False, "error": "Invalid API key (401)"}
                elif e.status_code == 400:
                    return {"success": False, "error": f"Bad request (400): {e.message}"}
                else:
                    return {"success": False, "error": f"API error {e.status_code}: {e.message}"}

            except Exception as e:
                for f in image_files:
                    try:
                        f.close()
                    except Exception:
                        pass
                if attempt < 1:
                    self.log_message.emit(f"  Error: {e}, retrying in 10s...")
                    time.sleep(10)
                else:
                    return {"success": False, "error": str(e)}

        return {"success": False, "error": "Max retries exceeded"}


# ─────────────────────────────────────────────────────────────
# Batch worker (auto mode)
# ─────────────────────────────────────────────────────────────

class BatchWorker(QThread):
    log_message = pyqtSignal(str)
    image_done = pyqtSignal(int, str, float, int, int, str)
    image_failed = pyqtSignal(int, str, str)
    anchor_locked = pyqtSignal(str)
    batch_finished = pyqtSignal()

    def __init__(self, prompts, output_dir, api_key, locked_anchor_path=None):
        super().__init__()
        self.prompts = prompts
        self.output_dir = Path(output_dir)
        self.api_key = api_key
        self.locked_anchor_path = locked_anchor_path
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def resolve_references(self, ref_keys):
        paths = []
        for key in ref_keys:
            if key == "locked_anchor" and self.locked_anchor_path:
                paths.append(Path(self.locked_anchor_path))
            elif key in CSP_FILES:
                paths.append(CSP_FILES[key])
        return paths

    def run(self):
        client = openai.OpenAI(api_key=self.api_key)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        for prompt_data in self.prompts:
            if self._stop_requested:
                self.log_message.emit("Batch cancelled by user.")
                break

            num = prompt_data["number"]
            filename = prompt_data["filename"]
            size = prompt_data["size"]
            raw_prompt = prompt_data["prompt"]

            self.log_message.emit(f"[Auto] Generating #{num}: {filename}...")

            ref_paths = self.resolve_references(prompt_data["reference_keys"])
            missing = [str(p) for p in ref_paths if not p.exists()]
            if missing:
                self.log_message.emit(f"  FAILED: Missing refs: {missing}")
                self.image_failed.emit(num, filename, f"Missing: {missing}")
                continue

            final_prompt = assemble_prompt(raw_prompt, HEAD_COUNT, SAFETY_PREFIX)
            result = self._call_api(client, final_prompt, ref_paths, size)

            # Content-policy retry
            if not result["success"] and result.get("content_policy", False):
                self.log_message.emit("  Content policy — retrying with strong prefix...")
                final_prompt_strong = assemble_prompt(raw_prompt, HEAD_COUNT, SAFETY_PREFIX_STRONG)
                result = self._call_api(client, final_prompt_strong, ref_paths, size)
                if result["success"]:
                    result["prefix_used"] = "strong"

            if result["success"]:
                output_path = self.output_dir / filename
                img_data = base64.b64decode(result["b64_json"])
                output_path.write_bytes(img_data)
                cost = result.get("cost", 0.20)
                prefix_used = result.get("prefix_used", "standard")
                self.log_message.emit(f"  OK: {filename}  (${cost:.2f}, prefix={prefix_used})")
                self.image_done.emit(num, filename, cost,
                                     result.get("input_tokens", 0),
                                     result.get("output_tokens", 0),
                                     prefix_used)
                if num == 1:
                    self.locked_anchor_path = str(output_path)
                    self.anchor_locked.emit(str(output_path))
                    self.log_message.emit(f"  LOCKED as anchor: {filename}")
            else:
                self.log_message.emit(f"  FAILED: {result['error']}")
                self.image_failed.emit(num, filename, result["error"])

        self.batch_finished.emit()

    def _call_api(self, client, prompt_text, ref_paths, size):
        max_retries = 4
        backoff_times = [5, 10, 20, 40]
        for attempt in range(max_retries):
            image_files = []
            try:
                for p in ref_paths:
                    image_files.append(open(p, "rb"))
                response = client.images.edit(
                    model="gpt-image-2",
                    image=image_files,
                    prompt=prompt_text,
                    size=size,
                    quality="high",
                    n=1,
                )
                for f in image_files:
                    f.close()
                b64 = response.data[0].b64_json
                usage = getattr(response, "usage", None)
                input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
                output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
                total_tokens = input_tokens + output_tokens
                cost = total_tokens * 0.000004 if total_tokens > 0 else 0.20
                return {"success": True, "b64_json": b64,
                        "input_tokens": input_tokens, "output_tokens": output_tokens,
                        "cost": cost, "prefix_used": "standard"}
            except openai.RateLimitError:
                for f in image_files:
                    f.close()
                if attempt < max_retries - 1:
                    wait = backoff_times[attempt]
                    self.log_message.emit(f"  Rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    return {"success": False, "error": "Rate limit exceeded"}
            except openai.APIStatusError as e:
                for f in image_files:
                    f.close()
                err_str = str(e).lower()
                if e.status_code == 400 and ("content_policy" in err_str or "safety" in err_str or "content policy" in err_str):
                    return {"success": False, "error": f"Content policy: {e.message}", "content_policy": True}
                if e.status_code in (500, 502, 503, 504) and attempt < 2:
                    self.log_message.emit(f"  Server error {e.status_code}, retrying in 10s...")
                    time.sleep(10)
                elif e.status_code == 401:
                    return {"success": False, "error": "Invalid API key (401)"}
                else:
                    return {"success": False, "error": f"API error {e.status_code}: {e.message}"}
            except Exception as e:
                for f in image_files:
                    try:
                        f.close()
                    except Exception:
                        pass
                if attempt < 1:
                    self.log_message.emit(f"  Error: {e}, retrying...")
                    time.sleep(10)
                else:
                    return {"success": False, "error": str(e)}
        return {"success": False, "error": "Max retries exceeded"}


# ─────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("9LivesK9 Prototype")
        self.setMinimumSize(760, 800)
        self.resize(860, 900)

        self.prompts = []
        self.worker = None
        self.locked_anchor_path = None
        self.total_cost = 0.0
        self.success_count = 0
        self.fail_count = 0
        self.current_index = 0

        self._load_prompts()
        self._build_ui()
        self._scan_existing_output()
        self._update_ui()

    def _load_prompts(self):
        if TEMPLATES_PATH.exists():
            with open(TEMPLATES_PATH) as f:
                self.prompts = json.load(f)

    def _scan_existing_output(self):
        output_dir = Path(self.output_edit.text().strip())
        if not output_dir.exists():
            return
        generated = set()
        for p in self.prompts:
            if (output_dir / p["filename"]).exists():
                generated.add(p["number"])
        if generated:
            self.success_count = len(generated)
            for i, p in enumerate(self.prompts):
                if p["number"] not in generated:
                    self.current_index = i
                    break
            else:
                self.current_index = len(self.prompts)
            anchor_path = output_dir / "F_adult_front_contrapposto_classic_01.png"
            if anchor_path.exists():
                self.locked_anchor_path = str(anchor_path)
            self.log_text.append(f"Found {len(generated)} existing images in output folder.")
            if self.current_index < len(self.prompts):
                self.log_text.append(f"Resuming from prompt #{self.prompts[self.current_index]['number']}.")
            else:
                self.log_text.append("All 62 images already generated.")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)

        # --- Header ---
        header = QLabel("9LivesK9 Base Pose Library — Prototype")
        header.setFont(QFont("", 14, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        # --- API Key ---
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("API Key:"))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Paste your OpenAI API key here (sk-...)")
        env_key = os.environ.get("OPENAI_API_KEY", "")
        if env_key:
            self.api_key_edit.setText(env_key)
        self.api_key_edit.textChanged.connect(lambda: self._update_ui())
        key_row.addWidget(self.api_key_edit, 1)
        layout.addLayout(key_row)

        # --- Archetype + Output ---
        arch_row = QHBoxLayout()
        arch_row.addWidget(QLabel("Archetype:"))
        self.archetype_combo = QComboBox()
        self.archetype_combo.addItem("F_adult — Female Adult, 8 head-heights")
        self.archetype_combo.setEnabled(False)
        arch_row.addWidget(self.archetype_combo, 1)
        layout.addLayout(arch_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output:"))
        self.output_edit = QLineEdit(str(DEFAULT_OUTPUT_DIR))
        out_row.addWidget(self.output_edit, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_output)
        out_row.addWidget(browse_btn)
        layout.addLayout(out_row)

        # --- Info + Progress ---
        info_row = QHBoxLayout()
        self.info_label = QLabel()
        info_row.addWidget(self.info_label)
        info_row.addStretch()
        self.cost_label = QLabel()
        info_row.addWidget(self.cost_label)
        layout.addLayout(info_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(62)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m  (%p%)")
        layout.addWidget(self.progress_bar)

        # --- Main action buttons ---
        btn_row = QHBoxLayout()
        self.next_btn = QPushButton("Generate Next")
        self.next_btn.setMinimumHeight(45)
        self.next_btn.setFont(QFont("", 11, QFont.Weight.Bold))
        self.next_btn.setStyleSheet(
            "QPushButton:enabled { background-color: #4CAF50; color: white; }"
            "QPushButton:disabled { background-color: #ccc; }")
        self.next_btn.clicked.connect(self._on_generate_next)
        btn_row.addWidget(self.next_btn, 2)

        self.auto_btn = QPushButton("Generate All Remaining")
        self.auto_btn.setMinimumHeight(45)
        self.auto_btn.setFont(QFont("", 11, QFont.Weight.Bold))
        self.auto_btn.clicked.connect(self._on_generate_all)
        btn_row.addWidget(self.auto_btn, 2)
        layout.addLayout(btn_row)

        # --- Secondary buttons ---
        btn_row2 = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_row2.addWidget(self.cancel_btn)
        open_btn = QPushButton("Open Output Folder")
        open_btn.clicked.connect(self._on_open_folder)
        btn_row2.addWidget(open_btn)
        rescan_btn = QPushButton("Rescan Output")
        rescan_btn.clicked.connect(self._on_rescan)
        btn_row2.addWidget(rescan_btn)
        layout.addLayout(btn_row2)

        # --- Log area ---
        log_label = QLabel("Generation Log:")
        log_label.setFont(QFont("", 10, QFont.Weight.Bold))
        layout.addWidget(log_label)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Monospace", 9))
        self.log_text.setMinimumHeight(140)
        layout.addWidget(self.log_text, 1)

        # ═══════════════════════════════════════════════════
        # Regenerate Single Pose section
        # ═══════════════════════════════════════════════════
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(divider)

        regen_header = QLabel("Regenerate Single Pose")
        regen_header.setFont(QFont("", 12, QFont.Weight.Bold))
        layout.addWidget(regen_header)

        # Pose dropdown
        pose_row = QHBoxLayout()
        pose_row.addWidget(QLabel("Pose:"))
        self.pose_combo = QComboBox()
        self.pose_combo.setMinimumWidth(400)
        self.pose_combo.currentIndexChanged.connect(self._on_pose_selected)
        pose_row.addWidget(self.pose_combo, 1)
        layout.addLayout(pose_row)

        # Thumbnail + buttons
        thumb_row = QHBoxLayout()

        # Thumbnail
        thumb_col = QVBoxLayout()
        thumb_col.addWidget(QLabel("Current Output:"))
        self.thumbnail_label = QLabel("No output yet")
        self.thumbnail_label.setFixedSize(200, 300)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("border: 1px solid #aaa; background: #f0f0f0;")
        self.thumbnail_label.setScaledContents(False)
        thumb_col.addWidget(self.thumbnail_label)
        thumb_row.addLayout(thumb_col)

        # Regen buttons
        regen_col = QVBoxLayout()
        regen_col.addStretch()

        self.regen_btn = QPushButton("Regenerate This Pose")
        self.regen_btn.setMinimumHeight(40)
        self.regen_btn.setFont(QFont("", 10, QFont.Weight.Bold))
        self.regen_btn.setStyleSheet(
            "QPushButton:enabled { background-color: #FF9800; color: white; }"
            "QPushButton:disabled { background-color: #ccc; }")
        self.regen_btn.clicked.connect(self._on_regenerate)
        regen_col.addWidget(self.regen_btn)

        self.restore_btn = QPushButton("Restore Previous Version")
        self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self._on_restore)
        regen_col.addWidget(self.restore_btn)

        regen_col.addStretch()
        thumb_row.addLayout(regen_col, 1)
        layout.addLayout(thumb_row)

        # Populate pose dropdown
        self._populate_pose_combo()

        # --- Status bar ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def _populate_pose_combo(self):
        self.pose_combo.blockSignals(True)
        self.pose_combo.clear()
        output_dir = Path(self.output_edit.text().strip())
        for p in self.prompts:
            num = p["number"]
            view = p["view"].replace("_", " ").title().replace("3Q ", "3Q_")
            pose = p["pose"].replace("_", " ").title()
            exists = (output_dir / p["filename"]).exists()
            icon = "\u2713" if exists else "\u2717"
            label = f"{icon} {num:02d} — {view} — {pose}"
            self.pose_combo.addItem(label, p)
        self.pose_combo.blockSignals(False)
        if self.pose_combo.count() > 0:
            self._on_pose_selected(0)

    def _on_pose_selected(self, index):
        if index < 0 or index >= self.pose_combo.count():
            return
        prompt_data = self.pose_combo.itemData(index)
        if not prompt_data:
            return
        output_dir = Path(self.output_edit.text().strip())
        img_path = output_dir / prompt_data["filename"]
        bak_path = img_path.with_suffix(img_path.suffix + ".bak")

        if img_path.exists():
            pixmap = QPixmap(str(img_path))
            scaled = pixmap.scaled(200, 300, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            self.thumbnail_label.setPixmap(scaled)
        else:
            self.thumbnail_label.clear()
            self.thumbnail_label.setText("No output yet")

        has_key = bool(self._get_api_key())
        is_idle = self.worker is None
        self.regen_btn.setEnabled(has_key and is_idle)
        self.restore_btn.setEnabled(bak_path.exists() and is_idle)

    def _get_api_key(self):
        return self.api_key_edit.text().strip()

    def _update_ui(self):
        n = len(self.prompts)
        remaining = n - self.current_index
        self.progress_bar.setValue(self.current_index)

        next_label = f"#{self.prompts[self.current_index]['number']}" if self.current_index < n else "DONE"
        self.info_label.setText(
            f"Generated: {self.success_count}/{n}  |  "
            f"Failed: {self.fail_count}  |  Next: {next_label}")
        self.cost_label.setText(
            f"Spent: ${self.total_cost:.2f}  |  Est. remaining: ${remaining * 0.20:.2f}")

        has_key = bool(self._get_api_key())
        is_idle = self.worker is None
        has_remaining = self.current_index < n

        self.next_btn.setEnabled(has_key and is_idle and has_remaining)
        self.auto_btn.setEnabled(has_key and is_idle and has_remaining)
        self.cancel_btn.setEnabled(not is_idle)

        if has_remaining and is_idle:
            next_p = self.prompts[self.current_index]
            self.next_btn.setText(f"Generate Next: #{next_p['number']} {next_p['filename']}")
            self.auto_btn.setText(f"Generate All Remaining ({remaining})")
        elif not has_remaining:
            self.next_btn.setText("All 62 images generated!")
            self.auto_btn.setText("Done")

        if has_key:
            self.status_bar.showMessage(f"API key: set  |  {'Ready' if is_idle else 'Generating...'}")
        else:
            self.status_bar.showMessage("Enter your OpenAI API key above to begin.")

        # Update regen panel state
        idx = self.pose_combo.currentIndex()
        if idx >= 0:
            self._on_pose_selected(idx)

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", str(DEFAULT_OUTPUT_DIR))
        if folder:
            self.output_edit.setText(folder)
            self._on_rescan()

    def _on_rescan(self):
        self.success_count = 0
        self.current_index = 0
        self.locked_anchor_path = None
        self.log_text.append("\u2500" * 60)
        self._scan_existing_output()
        self._populate_pose_combo()
        self._update_ui()

    def _preflight_check(self):
        if not self._get_api_key():
            QMessageBox.critical(self, "No API Key", "Please enter your OpenAI API key.")
            return False
        missing = [k for k, v in CSP_FILES.items() if not v.exists()]
        if missing:
            QMessageBox.critical(self, "Missing References",
                f"CSP reference files not found:\n{missing}\n\nExpected in: {CSP_DIR}")
            return False
        if not self.prompts:
            QMessageBox.critical(self, "No Prompts", f"No prompts loaded from {TEMPLATES_PATH}")
            return False
        return True

    def _on_generate_next(self):
        if not self._preflight_check():
            return
        if self.current_index >= len(self.prompts):
            QMessageBox.information(self, "Done", "All 62 images have been generated!")
            return

        prompt_data = self.prompts[self.current_index]
        self.log_text.append("\u2500" * 60)
        self._start_single_worker(prompt_data, trigger="batch")

    def _on_generate_all(self):
        if not self._preflight_check():
            return
        if self.current_index >= len(self.prompts):
            QMessageBox.information(self, "Done", "All 62 images have been generated!")
            return

        remaining_prompts = self.prompts[self.current_index:]
        self.log_text.append("\u2500" * 60)
        self.log_text.append(f"Starting auto-generation of {len(remaining_prompts)} remaining images...")

        self.worker = BatchWorker(
            remaining_prompts, self.output_edit.text().strip(),
            self._get_api_key(), self.locked_anchor_path)
        self.worker.log_message.connect(self._on_log)
        self.worker.image_done.connect(self._on_image_done)
        self.worker.image_failed.connect(self._on_image_failed)
        self.worker.anchor_locked.connect(self._on_anchor_locked)
        self.worker.batch_finished.connect(self._on_batch_finished)
        self.worker.start()
        self._update_ui()

    def _start_single_worker(self, prompt_data, trigger="batch"):
        self._current_trigger = trigger
        self.worker = SingleImageWorker(
            prompt_data, self.output_edit.text().strip(),
            self._get_api_key(), self.locked_anchor_path)
        self.worker.log_message.connect(self._on_log)
        self.worker.image_done.connect(self._on_image_done)
        self.worker.image_failed.connect(self._on_image_failed)
        self.worker.anchor_locked.connect(self._on_anchor_locked)
        self.worker.finished.connect(self._on_single_finished)
        self.worker.start()
        self._update_ui()

    def _on_cancel(self):
        if not self.worker:
            return
        if isinstance(self.worker, BatchWorker):
            reply = QMessageBox.question(self, "Cancel Batch",
                "Cancel after current image finishes?")
            if reply == QMessageBox.StandardButton.Yes:
                self.worker.request_stop()

    def _on_open_folder(self):
        folder = self.output_edit.text().strip()
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            os.system(f'xdg-open "{folder}" &')

    def _on_log(self, msg):
        self.log_text.append(msg)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_image_done(self, num, filename, cost, in_tok, out_tok, prefix_used):
        self.success_count += 1
        self.current_index = max(self.current_index, num)  # advance past this prompt
        # Find proper index
        for i, p in enumerate(self.prompts):
            if p["number"] == num:
                self.current_index = max(self.current_index, i + 1)
                break
        self.total_cost += cost

        # Append to cost CSV
        output_dir = Path(self.output_edit.text().strip())
        cost_log = output_dir / "cost_log.csv"
        csv_exists = cost_log.exists()
        with open(cost_log, "a", newline="") as f:
            w = csv.writer(f)
            if not csv_exists:
                w.writerow(["timestamp", "filename", "input_tokens", "output_tokens",
                            "cost_usd", "status", "prefix_used", "trigger"])
            trigger = getattr(self, "_current_trigger", "batch")
            w.writerow([datetime.now().isoformat(), filename, in_tok, out_tok,
                        f"{cost:.4f}", "success", prefix_used, trigger])

        self._populate_pose_combo()
        self._update_ui()

    def _on_image_failed(self, num, filename, error):
        self.fail_count += 1
        # Advance past failed prompt in sequential mode
        for i, p in enumerate(self.prompts):
            if p["number"] == num:
                self.current_index = max(self.current_index, i + 1)
                break
        self.log_text.append(f"  FAILED: {error}")
        self._update_ui()

    def _on_anchor_locked(self, path):
        self.locked_anchor_path = path

    def _on_single_finished(self):
        self.worker = None
        self._update_ui()

    def _on_batch_finished(self):
        self.worker = None
        self.log_text.append("\u2500" * 60)
        self.log_text.append(
            f"Batch complete. Generated: {self.success_count}/{len(self.prompts)}  "
            f"Failed: {self.fail_count}  Cost: ${self.total_cost:.2f}")
        self._populate_pose_combo()
        self._update_ui()
        QMessageBox.information(self, "Batch Complete",
            f"Auto-generation finished.\n\n"
            f"Success: {self.success_count}\nFailed: {self.fail_count}\n"
            f"Total cost: ${self.total_cost:.2f}")

    # ─────────────────────────────────────────────
    # Regenerate Single Pose
    # ─────────────────────────────────────────────

    def _on_regenerate(self):
        if not self._preflight_check():
            return
        idx = self.pose_combo.currentIndex()
        if idx < 0:
            return
        prompt_data = self.pose_combo.itemData(idx)
        filename = prompt_data["filename"]
        output_dir = Path(self.output_edit.text().strip())
        img_path = output_dir / filename
        bak_path = img_path.with_suffix(img_path.suffix + ".bak")

        reply = QMessageBox.question(self, "Regenerate Pose",
            f"This will overwrite:\n  {filename}\n\n"
            f"The previous version will be backed up to:\n  {filename}.bak\n\n"
            f"Continue?",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Backup existing
        if img_path.exists():
            if bak_path.exists():
                bak_path.unlink()
            img_path.rename(bak_path)
            self.log_text.append(f"Backed up {filename} -> {filename}.bak")

        self.log_text.append("\u2500" * 60)
        self._current_trigger = "manual_regen"
        self._regen_prompt_data = prompt_data
        self._regen_bak_path = bak_path
        self._start_single_worker(prompt_data, trigger="manual_regen")

    def _on_restore(self):
        idx = self.pose_combo.currentIndex()
        if idx < 0:
            return
        prompt_data = self.pose_combo.itemData(idx)
        filename = prompt_data["filename"]
        output_dir = Path(self.output_edit.text().strip())
        img_path = output_dir / filename
        bak_path = img_path.with_suffix(img_path.suffix + ".bak")

        if not bak_path.exists():
            QMessageBox.warning(self, "No Backup", f"No .bak file found for {filename}.")
            return

        reply = QMessageBox.question(self, "Restore Previous",
            f"Restore the previous version of {filename}?\n"
            f"The current version will be lost.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        if reply != QMessageBox.StandardButton.Yes:
            return

        if img_path.exists():
            img_path.unlink()
        bak_path.rename(img_path)
        self.log_text.append(f"Restored {filename} from backup.")
        self._on_pose_selected(idx)

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            reply = QMessageBox.question(self, "Generation in Progress",
                "A generation is in progress. Wait for it to finish, or cancel and close?",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            # If closing during regen, try to restore backup
            if hasattr(self, "_regen_bak_path") and hasattr(self, "_regen_prompt_data"):
                bak = self._regen_bak_path
                if bak.exists():
                    output_dir = Path(self.output_edit.text().strip())
                    orig = output_dir / self._regen_prompt_data["filename"]
                    if not orig.exists():
                        bak.rename(orig)
            if isinstance(self.worker, BatchWorker):
                self.worker.request_stop()
            self.worker.wait(5000)
        event.accept()


# ─────────────────────────────────────────────────────────────
# Verification script (Task 6)
# ─────────────────────────────────────────────────────────────

def verify_prompt_assembly():
    """Print assembled prompt #1 and substitution stats. Run with --verify flag."""
    if not TEMPLATES_PATH.exists():
        print(f"ERROR: {TEMPLATES_PATH} not found")
        return

    with open(TEMPLATES_PATH) as f:
        prompts = json.load(f)

    print("=" * 70)
    print("TASK 6 VERIFICATION: Prompt Assembly")
    print("=" * 70)

    # 1. Print full assembled prompt #1
    p1 = prompts[0]
    assembled = assemble_prompt(p1["prompt"], HEAD_COUNT, SAFETY_PREFIX)

    print(f"\n--- ASSEMBLED PROMPT #{p1['number']}: {p1['filename']} ---")
    print(f"--- Total length: {len(assembled)} chars ---\n")
    print(assembled)
    print(f"\n--- END PROMPT #{p1['number']} ---\n")

    # 2. Confirm {HEAD_COUNT} replacement
    if "{HEAD_COUNT}" in assembled:
        print("ERROR: {HEAD_COUNT} placeholder was NOT replaced!")
    else:
        hc_str = str(HEAD_COUNT)
        count = assembled.count(f"marker {hc_str}")
        print(f"OK: {{HEAD_COUNT}} replaced with {HEAD_COUNT}. "
              f"Found 'marker {hc_str}' {count} times in mandatory block.")

    # 3. Substitution stats
    print(f"\n--- SUBSTITUTION STATS (across {len(prompts)} prompts) ---\n")
    stats = count_substitution_hits(prompts)
    for find, replace, count, total in stats:
        trunc_find = find[:60]
        trunc_replace = replace[:60]
        print(f"  '{trunc_find}' -> '{trunc_replace}...'")
        print(f"    Applied: {count}/{total} prompts\n")

    print("=" * 70)
    print("Verification complete. Review above, then approve before running.")
    print("=" * 70)


def main():
    if "--verify" in sys.argv:
        verify_prompt_assembly()
        return

    app = QApplication(sys.argv)
    app.setApplicationName("9LivesK9 Prototype")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
