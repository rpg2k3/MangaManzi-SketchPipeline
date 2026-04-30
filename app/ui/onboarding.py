"""First-run API key onboarding wizard — three providers, fail-soft validation."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QGroupBox, QFormLayout,
)
from PySide6.QtGui import QFont

from app import keyring_store
from app.api import claude_client, gemini_client, openai_client

_ICONS = {
    "ok": "\u2705",
    "invalid": "\u274C",
    "rate_limited": "\u26A0\uFE0F",
    "warning": "\u26A0\uFE0F",
    "error": "\u2753",
    "untested": "\u2B55",
}


def _key_format_ok(key: str, provider: str) -> bool:
    key = key.strip()
    if not key:
        return False
    if provider == "anthropic":
        return key.startswith("sk-ant-") and len(key) > 20
    if provider == "google":
        return key.startswith("AIza") and len(key) >= 30
    if provider == "openai":
        return key.startswith("sk-") and len(key) > 20
    return len(key) > 10


class OnboardingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("9LivesK9 — API Key Setup")
        self.setMinimumWidth(620)
        self.setModal(True)
        self._statuses = {"anthropic": "untested", "openai": "untested", "google": "untested"}
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
            "Enter your API keys. OpenAI + Anthropic are required.\n"
            "Google/Gemini is optional (legacy). Testing is optional."
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        layout.addWidget(sub)

        # Lane assignments (read-only info)
        lane_label = QLabel(
            "Lane assignments:  "
            "Mannequin bases \u2192 OpenAI (gpt-image-1)  |  "
            "Sketch overlay \u2192 OpenAI (gpt-image-1)  |  "
            "Prompt brain \u2192 Claude Haiku"
        )
        lane_label.setStyleSheet("color: #555; font-style: italic;")
        lane_label.setWordWrap(True)
        layout.addWidget(lane_label)

        # --- OpenAI ---
        og = QGroupBox("OpenAI (gpt-image-1 — mannequin base generation)")
        of = QFormLayout(og)
        self.openai_edit = QLineEdit()
        self.openai_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_edit.setPlaceholderText("sk-proj-...")
        self.openai_edit.textChanged.connect(self._on_key_changed)
        of.addRow("API Key:", self.openai_edit)
        orow = QHBoxLayout()
        self.openai_test_btn = QPushButton("Test Connection")
        self.openai_test_btn.clicked.connect(self._test_openai)
        orow.addWidget(self.openai_test_btn)
        self.openai_status_label = QLabel(f"{_ICONS['untested']} Untested")
        orow.addWidget(self.openai_status_label, 1)
        of.addRow(orow)
        layout.addWidget(og)

        # --- Anthropic ---
        ag = QGroupBox("Anthropic (Claude Haiku — prompt brain)")
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

        # --- Google (optional, legacy) ---
        gg = QGroupBox("Google Gemini (optional — legacy experimentation only)")
        gf = QFormLayout(gg)
        self.google_edit = QLineEdit()
        self.google_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.google_edit.setPlaceholderText("AIzaSy...")
        self.google_edit.textChanged.connect(self._on_key_changed)
        gf.addRow("API Key:", self.google_edit)
        grow = QHBoxLayout()
        self.google_test_btn = QPushButton("Test Connection")
        self.google_test_btn.clicked.connect(self._test_google)
        grow.addWidget(self.google_test_btn)
        self.google_status_label = QLabel(f"{_ICONS['untested']} Untested")
        grow.addWidget(self.google_status_label, 1)
        gf.addRow(grow)
        layout.addWidget(gg)

        # --- Continue ---
        self.continue_btn = QPushButton("Continue")
        self.continue_btn.setMinimumHeight(40)
        self.continue_btn.setFont(QFont("", 12, QFont.Weight.Bold))
        self.continue_btn.setEnabled(False)
        self.continue_btn.clicked.connect(self._on_continue)
        layout.addWidget(self.continue_btn)

    def _load_existing(self):
        ak = keyring_store.get_anthropic_key()
        gk = keyring_store.get_google_key()
        ok = keyring_store.get_openai_key()
        if ak:
            self.anthropic_edit.setText(ak)
        if gk:
            self.google_edit.setText(gk)
        if ok:
            self.openai_edit.setText(ok)

    def _on_key_changed(self):
        a_ok = _key_format_ok(self.anthropic_edit.text(), "anthropic")
        o_ok = _key_format_ok(self.openai_edit.text(), "openai")
        # Google key is optional (legacy Gemini lane)
        self.continue_btn.setEnabled(a_ok and o_ok)

    def _set_status(self, provider, status, message):
        icon = _ICONS.get(status, _ICONS["error"])
        labels = {
            "anthropic": self.anthropic_status_label,
            "google": self.google_status_label,
            "openai": self.openai_status_label,
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
        status, msg = test_fn(key)
        self._set_status(provider, status, msg)

    def _test_openai(self):
        self._test_provider("openai", self.openai_edit, openai_client.test_connection)

    def _test_anthropic(self):
        self._test_provider("anthropic", self.anthropic_edit, claude_client.test_connection)

    def _test_google(self):
        self._test_provider("google", self.google_edit, gemini_client.test_connection)

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
                "Proceed anyway?\n"
                "(Recommended: try a single-pose generation first.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes)
            if reply != QMessageBox.StandardButton.Yes:
                return

        keyring_store.set_openai_key(self.openai_edit.text().strip())
        keyring_store.set_anthropic_key(self.anthropic_edit.text().strip())
        keyring_store.set_google_key(self.google_edit.text().strip())
        self.accept()
