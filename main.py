#!/usr/bin/env python3
"""9LivesK9 Sketch Pipeline — entry point."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication

from app.keyring_store import get_anthropic_key, get_pixai_key
from app.ui.onboarding import OnboardingDialog
from app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("9LivesK9 Sketch Pipeline")

    if not (get_anthropic_key() and get_pixai_key()):
        dlg = OnboardingDialog()
        if dlg.exec() == 0:
            sys.exit(0)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
