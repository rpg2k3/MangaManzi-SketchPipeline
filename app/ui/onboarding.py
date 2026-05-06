"""First-run API key onboarding — Anthropic + PixAI."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QGroupBox, QFormLayout,
)
from PySide6.QtGui import QFont

from app import keyring_store
from app.claude import extraction as claude_client
from app.pixai import client as pixai_client

_ICONS = {
    "ok": "✅",
    "invalid": "❌",
    "rate_limited": "⚠️",
    "warning": "⚠️",
    "error": "❓",
    "untested": "⭕",
}


def _key_format_ok(key: str, provider: str) -> bool:
    key = key.strip()
    if not key:
        return False
    if provider == "anthropic":
        return key.startswith("sk-ant-") and len(key) > 20
    if provider == "pixai":
        return len(key) >= 20
    return len(key) > 10


class OnboardingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("9LivesK9 — API Key Setup")
        self.setMinimumWidth(620)
        self.setModal(True)
        self._statuses = {"anthropic": "untested", "pixai": "untested"}
        self._build_ui()
        self._load_existing()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        header = QLabel("Welcome to 9LivesK9 Sketch Pipeline")
        header.setFont(QFont("", 16, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        sub = QLabel(
            "Two API keys are required: Anthropic (director) + PixAI (studio).\n"
            "Both are stored in your OS credential manager — never in plaintext."
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        layout.addWidget(sub)

        ag = QGroupBox("Anthropic (Claude — director / prompt brain / critique)")
        af = QFormLayout(ag)
        self.anthropic_edit = QLineEdit()
        self.anthropic_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.anthropic_edit.setPlaceholderText("sk-ant-api03-...")
        self.anthropic_edit.textChanged.connect(self._on_key_changed)
        af.addRow("API Key:", self.anthropic_edit)
        arow = QHBoxLayout()
        self.anthropic_test_btn = QPushButton("Test Connection")
        self.anthropic_test_btn.clicked.connect(self._test_anthropic)
        arow.addWidget(self.anthropic_test_btn)
        self.anthropic_status_label = QLabel(f"{_ICONS['untested']} Untested")
        arow.addWidget(self.anthropic_status_label, 1)
        af.addRow(arow)
        layout.addWidget(ag)

        pg = QGroupBox("PixAI (studio — all image generation)")
        pf = QFormLayout(pg)
        self.pixai_edit = QLineEdit()
        self.pixai_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pixai_edit.setPlaceholderText("PixAI API key (from platform.pixai.art)")
        self.pixai_edit.textChanged.connect(self._on_key_changed)
        pf.addRow("API Key:", self.pixai_edit)
        prow = QHBoxLayout()
        self.pixai_test_btn = QPushButton("Test Connection")
        self.pixai_test_btn.clicked.connect(self._test_pixai)
        prow.addWidget(self.pixai_test_btn)
        self.pixai_status_label = QLabel(f"{_ICONS['untested']} Untested")
        prow.addWidget(self.pixai_status_label, 1)
        pf.addRow(prow)
        layout.addWidget(pg)

        self.continue_btn = QPushButton("Continue")
        self.continue_btn.setMinimumHeight(40)
        self.continue_btn.setFont(QFont("", 12, QFont.Weight.Bold))
        self.continue_btn.setEnabled(False)
        self.continue_btn.clicked.connect(self._on_continue)
        layout.addWidget(self.continue_btn)

    def _load_existing(self):
        ak = keyring_store.get_anthropic_key()
        pk = keyring_store.get_pixai_key()
        if ak:
            self.anthropic_edit.setText(ak)
        if pk:
            self.pixai_edit.setText(pk)

    def _on_key_changed(self):
        a_ok = _key_format_ok(self.anthropic_edit.text(), "anthropic")
        p_ok = _key_format_ok(self.pixai_edit.text(), "pixai")
        self.continue_btn.setEnabled(a_ok and p_ok)

    def _set_status(self, provider, status, message):
        icon = _ICONS.get(status, _ICONS["error"])
        labels = {
            "anthropic": self.anthropic_status_label,
            "pixai": self.pixai_status_label,
        }
        labels[provider].setText(f"{icon} {message}")
        self._statuses[provider] = status

    def _test_provider(self, provider, key_edit, test_fn):
        key = key_edit.text().strip()
        if not key:
            self._set_status(provider, "untested", "Enter a key first.")
            return
        self._set_status(provider, "untested", "Testing...")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        try:
            status, msg = test_fn(key)
        except Exception as e:
            status, msg = "error", str(e)[:100]
        self._set_status(provider, status, msg)

    def _test_anthropic(self):
        self._test_provider("anthropic", self.anthropic_edit, claude_client.test_connection)

    def _test_pixai(self):
        self._test_provider("pixai", self.pixai_edit, pixai_client.test_connection)

    def _on_continue(self):
        has_failure = any(
            s not in ("ok", "untested") for s in self._statuses.values()
        )
        if has_failure:
            issues = [f"  - {p}: {s}" for p, s in self._statuses.items()
                      if s not in ("ok", "untested")]
            reply = QMessageBox.question(
                self, "Proceed with warnings?",
                "The following test(s) did not fully pass:\n\n"
                + "\n".join(issues) + "\n\n"
                "Test connections may fail due to rate limits that don't affect "
                "production calls.\n\n"
                "Proceed anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes)
            if reply != QMessageBox.StandardButton.Yes:
                return

        keyring_store.set_anthropic_key(self.anthropic_edit.text().strip())
        keyring_store.set_pixai_key(self.pixai_edit.text().strip())
        self.accept()
