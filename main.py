#!/usr/bin/env python3
"""9LivesK9 Sketch Pipeline — entry point."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication

from app.keyring_store import get_anthropic_key, get_openai_key
from app.ui.onboarding import OnboardingDialog
from app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("9LivesK9 Sketch Pipeline")

    # Production lanes require Anthropic (prompt brain) + OpenAI (image generation)
    # Google/Gemini key is optional (legacy experimentation only)
    has_required_keys = bool(get_anthropic_key()) and bool(get_openai_key())

    if not has_required_keys:
        dlg = OnboardingDialog()
        if dlg.exec() == 0:
            sys.exit(0)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
