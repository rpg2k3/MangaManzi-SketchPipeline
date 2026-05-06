"""Settings tab — Anthropic + PixAI keys, cumulative spend."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGroupBox, QFormLayout, QMessageBox,
)

from app import keyring_store
from app.cost_logger import get_cumulative_spend
from app.claude import extraction as claude_client
from app.pixai import client as pixai_client

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

        kg = QGroupBox("API Keys")
        kf = QFormLayout(kg)

        for provider, label in [("anthropic", "Anthropic"), ("pixai", "PixAI")]:
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
            kf.addRow(btn_row)

        clear_btn = QPushButton("Clear All Keys")
        clear_btn.clicked.connect(self._clear_keys)
        kf.addRow(clear_btn)
        layout.addWidget(kg)

        sg = QGroupBox("Cumulative Spend")
        sf = QFormLayout(sg)
        self.spend_label = QLabel()
        sf.addRow(self.spend_label)
        rb = QPushButton("Refresh Spend")
        rb.clicked.connect(self._refresh_spend)
        sf.addRow(rb)
        layout.addWidget(sg)

        layout.addStretch()

    def refresh(self):
        self.anthropic_label.setText(keyring_store.mask_key(keyring_store.get_anthropic_key()))
        self.pixai_label.setText(keyring_store.mask_key(keyring_store.get_pixai_key()))
        self._refresh_spend()

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

    def _test_key(self, provider):
        key_fns = {
            "anthropic": (keyring_store.get_anthropic_key, claude_client.test_connection),
            "pixai": (keyring_store.get_pixai_key, pixai_client.test_connection),
        }
        get_fn, test_fn = key_fns[provider]
        key = get_fn()
        if not key:
            self._set_status(provider, "untested", "Key not set.")
            return
        self._set_status(provider, "untested", "Testing...")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        try:
            if provider == "anthropic":
                status, msg = test_fn(key, bypass_cache=True)
            else:
                status, msg = test_fn(key)
        except Exception as e:
            status, msg = "error", str(e)[:100]
        self._set_status(provider, status, msg)

    def _clear_keys(self):
        reply = QMessageBox.question(self, "Clear Keys",
            "Remove all API keys from secure storage?")
        if reply == QMessageBox.StandardButton.Yes:
            keyring_store.clear_all()
            for p in ("anthropic", "pixai"):
                self._set_status(p, "untested", "Cleared")
            self.refresh()
