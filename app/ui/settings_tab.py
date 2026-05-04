"""Settings tab — API keys, file locations, OpenAI quality, cumulative spend."""

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGroupBox, QFormLayout, QMessageBox, QComboBox,
    QFileDialog, QLineEdit,
)

from app import keyring_store, settings_manager
from app.api import key_tests
from app.cost_logger import get_cumulative_spend, LOGS_DIR

APP_DIR = Path(__file__).parent.parent.parent

_ICONS = {
    "ok": "✅", "invalid": "❌", "rate_limited": "⚠️",
    "warning": "⚠️", "error": "❓", "untested": "⭕",
}


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── API Keys ──
        kg = QGroupBox("API Keys")
        kf = QFormLayout(kg)

        for provider, label in [("openai", "OpenAI (required)"),
                                 ("anthropic", "Anthropic (required)")]:
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

        # ── OpenAI Quality ──
        qg = QGroupBox("OpenAI Quality (affects image cost + fidelity)")
        qf = QFormLayout(qg)
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("low  —  ~$0.011 / image", "low")
        self.quality_combo.addItem("medium  —  ~$0.042 / image", "medium")
        self.quality_combo.addItem("high  —  ~$0.167 / image", "high")
        self.quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        qf.addRow("Quality:", self.quality_combo)
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color:#0066CC; font-style: italic;")
        qf.addRow(self.info_label)
        layout.addWidget(qg)

        # ── Spend ──
        sg = QGroupBox("Cumulative Spend")
        sf = QFormLayout(sg)
        self.spend_label = QLabel()
        sf.addRow(self.spend_label)
        rb = QPushButton("Refresh Spend")
        rb.clicked.connect(self._refresh_spend)
        sf.addRow(rb)
        layout.addWidget(sg)

        layout.addStretch()

    # ── Refresh / state ──

    def refresh(self):
        self._set_combo(self.quality_combo, settings_manager.get_openai_quality())
        self.openai_label.setText(keyring_store.mask_key(keyring_store.get_openai_key()))
        self.anthropic_label.setText(keyring_store.mask_key(keyring_store.get_anthropic_key()))
        self.output_dir_edit.setText(settings_manager.get("chatgpt_output_dir") or "")
        self._refresh_spend()
        self.info_label.setText("")

    def _set_combo(self, combo: QComboBox, value):
        combo.blockSignals(True)
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                break
        combo.blockSignals(False)

    # ── Quality ──

    def _on_quality_changed(self):
        val = self.quality_combo.currentData()
        settings_manager.set_value("openai_quality", val)
        price = settings_manager.OPENAI_PRICING.get(val, 0.042)
        self.info_label.setText(
            f"OpenAI quality set to {val} (~${price:.3f}/image).")

    # ── File locations ──

    def _on_browse_output(self):
        start = self.output_dir_edit.text().strip() or str(APP_DIR / "output")
        path = QFileDialog.getExistingDirectory(self, "Select Chat_GPT output folder", start)
        if path:
            self.output_dir_edit.setText(path)

    def _on_save_output(self):
        path = self.output_dir_edit.text().strip()
        settings_manager.set_value("chatgpt_output_dir", path)
        self.info_label.setText(
            f"Chat_GPT output folder set to: {path or '(default)'}")

    def _on_open_cost_log_folder(self):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        os.system(f'xdg-open "{LOGS_DIR}" &')

    # ── Spend ──

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

    # ── Keys ──

    def _set_status(self, provider, status, msg):
        icon = _ICONS.get(status, _ICONS["error"])
        getattr(self, f"{provider}_status_label").setText(f"{icon} {msg}")

    def _edit_keys(self):
        from app.ui.onboarding import OnboardingDialog
        dlg = OnboardingDialog(self)
        dlg.exec()
        self.refresh()

    def _test_key(self, provider, bypass=False):
        get_fns = {
            "openai": (keyring_store.get_openai_key, key_tests.test_openai),
            "anthropic": (keyring_store.get_anthropic_key, key_tests.test_anthropic),
        }
        get_fn, test_fn = get_fns[provider]
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
            for p in ("openai", "anthropic"):
                self._set_status(p, "untested", "Cleared")
            self.refresh()
