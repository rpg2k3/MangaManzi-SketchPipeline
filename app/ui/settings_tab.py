"""Settings tab — lane config, API keys, file locations, cumulative spend."""

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGroupBox, QFormLayout, QMessageBox, QComboBox,
    QPlainTextEdit, QFileDialog, QLineEdit,
)
from PySide6.QtGui import QFont

from app import keyring_store, settings_manager
from app.cost_logger import get_cumulative_spend, LOGS_DIR
from app.api import claude_client, gemini_client, openai_client

APP_DIR = Path(__file__).parent.parent.parent

_ICONS = {
    "ok": "\u2705", "invalid": "\u274C", "rate_limited": "\u26A0\uFE0F",
    "warning": "\u26A0\uFE0F", "error": "\u2753", "untested": "\u2B55",
}


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Lane Configuration ──
        lg = QGroupBox("Lane Configuration")
        lf = QFormLayout(lg)

        # Mannequin provider
        self.mannequin_provider_combo = QComboBox()
        self.mannequin_provider_combo.addItem("OpenAI \u2014 gpt-image-1", "openai")
        self.mannequin_provider_combo.addItem("Gemini \u2014 gemini-2.5-flash-image", "gemini")
        self.mannequin_provider_combo.currentIndexChanged.connect(self._on_mannequin_provider_changed)
        lf.addRow("Mannequin Bases:", self.mannequin_provider_combo)

        # Sketch provider
        self.sketch_provider_combo = QComboBox()
        self.sketch_provider_combo.addItem("Gemini \u2014 gemini-2.5-flash-image", "gemini")
        self.sketch_provider_combo.addItem("OpenAI \u2014 gpt-image-1", "openai")
        self.sketch_provider_combo.currentIndexChanged.connect(self._on_sketch_provider_changed)
        lf.addRow("Sketch Overlay:", self.sketch_provider_combo)

        # OpenAI quality
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("low  \u2014  ~$0.011/image", "low")
        self.quality_combo.addItem("medium  \u2014  ~$0.042/image", "medium")
        self.quality_combo.addItem("high  \u2014  ~$0.167/image", "high")
        self.quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        lf.addRow("OpenAI Quality:", self.quality_combo)

        # Locked lanes (read-only)
        lf.addRow("Character Extraction:", QLabel("Anthropic \u2014 claude-haiku-4-5-20251001 (locked)"))
        lf.addRow("Prompt Assembly:", QLabel("Anthropic \u2014 claude-haiku-4-5-20251001 (locked)"))

        # Info banner
        self.lane_info_label = QLabel("")
        self.lane_info_label.setStyleSheet("color: #0066CC; font-style: italic;")
        self.lane_info_label.setWordWrap(True)
        lf.addRow(self.lane_info_label)

        layout.addWidget(lg)

        # ── API Keys ──
        kg = QGroupBox("API Keys")
        kf = QFormLayout(kg)

        for provider, label in [("openai", "OpenAI"), ("anthropic", "Anthropic"), ("google", "Google")]:
            row = QHBoxLayout()
            key_label = QLabel()
            setattr(self, f"{provider}_label", key_label)
            row.addWidget(key_label, 1)
            status_label = QLabel(f"{_ICONS['untested']} Untested")
            setattr(self, f"{provider}_status_label", status_label)
            row.addWidget(status_label)
            kf.addRow(f"{label}:", row)

            btn_row = QHBoxLayout()
            edit_btn = QPushButton("Edit Key")
            edit_btn.clicked.connect(self._edit_keys)
            btn_row.addWidget(edit_btn)
            test_btn = QPushButton("Test")
            test_btn.clicked.connect(lambda checked, p=provider: self._test_key(p))
            btn_row.addWidget(test_btn)
            force_btn = QPushButton("Force Re-test")
            force_btn.clicked.connect(lambda checked, p=provider: self._test_key(p, bypass=True))
            btn_row.addWidget(force_btn)
            kf.addRow(btn_row)

        clear_btn = QPushButton("Clear All Keys")
        clear_btn.clicked.connect(self._clear_keys)
        kf.addRow(clear_btn)
        layout.addWidget(kg)

        # ── File Locations ──
        flg = QGroupBox("File Locations")
        flf = QFormLayout(flg)

        out_row = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText(str(APP_DIR / "output" / "chat_gpt_base"))
        out_row.addWidget(self.output_dir_edit, 1)
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self._on_browse_output)
        out_row.addWidget(out_browse)
        out_save = QPushButton("Save")
        out_save.clicked.connect(self._on_save_output)
        out_row.addWidget(out_save)
        flf.addRow("Chat_GPT output folder:", out_row)

        log_row = QHBoxLayout()
        self.cost_log_label = QLabel(str(LOGS_DIR))
        self.cost_log_label.setStyleSheet("color:#444;")
        log_row.addWidget(self.cost_log_label, 1)
        log_open = QPushButton("Open Folder")
        log_open.clicked.connect(self._on_open_cost_log_folder)
        log_row.addWidget(log_open)
        flf.addRow("Cost log location:", log_row)

        layout.addWidget(flg)

        # ── Spend ──
        sg = QGroupBox("Cumulative Spend")
        sf = QFormLayout(sg)
        self.spend_label = QLabel()
        sf.addRow(self.spend_label)
        rb = QPushButton("Refresh Spend")
        rb.clicked.connect(self._refresh_spend)
        sf.addRow(rb)
        layout.addWidget(sg)

        # ── Quality Tags ──
        tg = QGroupBox("Quality Tags (prepended to prompts)")
        tf = QFormLayout(tg)

        self.mannequin_tag_edit = QPlainTextEdit()
        self.mannequin_tag_edit.setMaximumHeight(60)
        self.mannequin_tag_edit.setFont(QFont("Monospace", 9))
        tf.addRow("Mannequin:", self.mannequin_tag_edit)

        self.sketch_tag_edit = QPlainTextEdit()
        self.sketch_tag_edit.setMaximumHeight(60)
        self.sketch_tag_edit.setFont(QFont("Monospace", 9))
        tf.addRow("Sketch:", self.sketch_tag_edit)

        save_tags_btn = QPushButton("Save Quality Tags")
        save_tags_btn.clicked.connect(self._save_tags)
        tf.addRow(save_tags_btn)

        layout.addWidget(tg)

        # ── Master Prompt Knowledge ──
        kg = QGroupBox("Master Prompt Knowledge")
        kfl = QFormLayout(kg)

        self.spec_status_label = QLabel()
        self.spec_status_label.setWordWrap(True)
        kfl.addRow("Spec file:", self.spec_status_label)

        self.instr_status_label = QLabel()
        self.instr_status_label.setWordWrap(True)
        kfl.addRow("Instructions:", self.instr_status_label)

        kbtn_row = QHBoxLayout()
        open_know_btn = QPushButton("Open Knowledge Folder")
        open_know_btn.clicked.connect(self._open_knowledge_folder)
        kbtn_row.addWidget(open_know_btn)
        reload_know_btn = QPushButton("Reload Knowledge Files")
        reload_know_btn.clicked.connect(self._reload_knowledge)
        kbtn_row.addWidget(reload_know_btn)
        kfl.addRow(kbtn_row)

        layout.addWidget(kg)

        layout.addStretch()

    def refresh(self):
        self._set_combo(self.mannequin_provider_combo, settings_manager.get_mannequin_provider())
        self._set_combo(self.sketch_provider_combo, settings_manager.get_sketch_provider())
        self._set_combo(self.quality_combo, settings_manager.get_openai_quality())

        # Quality tags
        self.mannequin_tag_edit.setPlainText(settings_manager.get("mannequin_quality_tag") or "")
        self.sketch_tag_edit.setPlainText(settings_manager.get("sketch_quality_tag") or "")

        # Knowledge file status
        self._refresh_knowledge_status()

        # Keys
        self.openai_label.setText(keyring_store.mask_key(keyring_store.get_openai_key()))
        self.anthropic_label.setText(keyring_store.mask_key(keyring_store.get_anthropic_key()))
        self.google_label.setText(keyring_store.mask_key(keyring_store.get_google_key()))

        # File locations
        self.output_dir_edit.setText(settings_manager.get("chatgpt_output_dir") or "")

        self._refresh_spend()
        self.lane_info_label.setText("")

    def _set_combo(self, combo, value):
        combo.blockSignals(True)
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                break
        combo.blockSignals(False)

    def _on_mannequin_provider_changed(self):
        val = self.mannequin_provider_combo.currentData()
        settings_manager.set_value("mannequin_provider", val)
        model = settings_manager.PROVIDER_MODELS.get(val, val)
        self.lane_info_label.setText(
            f"Mannequin provider changed to {val.title()} ({model}). "
            f"New generations will use this provider. Existing files unaffected.")

    def _on_sketch_provider_changed(self):
        val = self.sketch_provider_combo.currentData()
        settings_manager.set_value("sketch_provider", val)
        model = settings_manager.PROVIDER_MODELS.get(val, val)
        self.lane_info_label.setText(
            f"Sketch provider changed to {val.title()} ({model}). "
            f"New generations will use this provider. Existing files unaffected.")

    def _on_quality_changed(self):
        val = self.quality_combo.currentData()
        settings_manager.set_value("openai_quality", val)
        price = settings_manager.OPENAI_PRICING.get(val, 0.042)
        self.lane_info_label.setText(
            f"OpenAI quality set to {val} (~${price:.3f}/image). "
            f"Affects both lanes when OpenAI is the selected provider.")

    def _save_tags(self):
        settings_manager.set_value("mannequin_quality_tag", self.mannequin_tag_edit.toPlainText().strip())
        settings_manager.set_value("sketch_quality_tag", self.sketch_tag_edit.toPlainText().strip())
        self.lane_info_label.setText("Quality tags saved.")

    def _on_browse_output(self):
        start = self.output_dir_edit.text().strip() or str(APP_DIR / "output")
        path = QFileDialog.getExistingDirectory(self, "Select Chat_GPT output folder", start)
        if path:
            self.output_dir_edit.setText(path)

    def _on_save_output(self):
        path = self.output_dir_edit.text().strip()
        settings_manager.set_value("chatgpt_output_dir", path)
        self.lane_info_label.setText(
            f"Chat_GPT output folder set to: {path or '(default)'}")

    def _on_open_cost_log_folder(self):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        os.system(f'xdg-open "{LOGS_DIR}" &')

    def _refresh_spend(self):
        spend = get_cumulative_spend()
        lines = []
        total = 0
        for provider, amount in sorted(spend.items()):
            lines.append(f"  {provider}: ${amount:.4f}")
            total += amount
        if lines:
            lines.append(f"\n  Total: ${total:.4f}")
            self.spend_label.setText("\n".join(lines))
        else:
            self.spend_label.setText("No API calls logged yet.")

    def _set_status(self, provider, status, msg):
        icon = _ICONS.get(status, _ICONS["error"])
        getattr(self, f"{provider}_status_label").setText(f"{icon} {msg}")

    def _edit_keys(self):
        from app.ui.onboarding import OnboardingDialog
        dlg = OnboardingDialog(self)
        dlg.exec()
        self.refresh()

    def _test_key(self, provider, bypass=False):
        key_fns = {
            "openai": (keyring_store.get_openai_key, openai_client.test_connection),
            "anthropic": (keyring_store.get_anthropic_key, claude_client.test_connection),
            "google": (keyring_store.get_google_key, gemini_client.test_connection),
        }
        get_fn, test_fn = key_fns[provider]
        key = get_fn()
        if not key:
            self._set_status(provider, "untested", "Key not set.")
            return
        self._set_status(provider, "untested", "Testing...")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        status, msg = test_fn(key, bypass_cache=bypass)
        self._set_status(provider, status, msg)

    def _clear_keys(self):
        reply = QMessageBox.question(self, "Clear Keys",
            "Remove all API keys from secure storage?")
        if reply == QMessageBox.StandardButton.Yes:
            keyring_store.clear_all()
            for p in ("openai", "anthropic", "google"):
                self._set_status(p, "untested", "Cleared")
            self.refresh()

    # ── Knowledge files ──

    def _refresh_knowledge_status(self):
        from app.knowledge_loader import get_spec_info, get_instructions_info, SPEC_FILE, INSTRUCTIONS_FILE

        spec = get_spec_info()
        instr = get_instructions_info()

        if spec["exists"]:
            self.spec_status_label.setText(
                f"\u2705 Loaded ({spec['size']:,} chars, modified: {spec['mtime_str']})\n"
                f"{SPEC_FILE}")
        else:
            self.spec_status_label.setText(
                f"\u274C MISSING: {SPEC_FILE}\n"
                f"Mannequin generation will fail until this file is restored.")

        if instr["exists"]:
            self.instr_status_label.setText(
                f"\u2705 Loaded ({instr['size']:,} chars, modified: {instr['mtime_str']})\n"
                f"{INSTRUCTIONS_FILE}")
        else:
            self.instr_status_label.setText(
                f"\u274C MISSING: {INSTRUCTIONS_FILE}\n"
                f"Mannequin generation will fail until this file is restored.")

    def _open_knowledge_folder(self):
        from app.knowledge_loader import KNOWLEDGE_DIR
        import os
        if KNOWLEDGE_DIR.exists():
            os.system(f'xdg-open "{KNOWLEDGE_DIR}" &')

    def _reload_knowledge(self):
        from app.knowledge_loader import force_reload
        reloaded = force_reload()
        self._refresh_knowledge_status()
        self.lane_info_label.setText(f"Reloaded: {', '.join(reloaded) if reloaded else 'no files found'}")
