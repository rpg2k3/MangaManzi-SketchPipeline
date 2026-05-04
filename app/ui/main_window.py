"""Main tabbed window — Chat_GPT pipeline only."""

from PySide6.QtWidgets import QMainWindow, QTabWidget, QMessageBox

from app.ui.settings_tab import SettingsTab
from app.ui.chatgpt_base_tab import ChatGPTBaseTab
from app.ui.chatgpt_sketch_tab import ChatGPTSketchTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("9LivesK9 — Chat_GPT Pipeline")
        self.setMinimumSize(900, 750)
        self.resize(1050, 850)
        self._build_ui()

    def _build_ui(self):
        self.tabs = QTabWidget()

        self.chatgpt_base_tab = ChatGPTBaseTab()
        self.chatgpt_sketch_tab = ChatGPTSketchTab()
        self.settings_tab = SettingsTab()

        self.tabs.addTab(self.chatgpt_base_tab, "Base Generator")
        self.tabs.addTab(self.chatgpt_sketch_tab, "Sketch Over Base")
        self.tabs.addTab(self.settings_tab, "Settings")

        self.setCentralWidget(self.tabs)

    def _is_any_busy(self) -> bool:
        return self.chatgpt_base_tab.is_busy() or self.chatgpt_sketch_tab.is_busy()

    def closeEvent(self, event):
        if self._is_any_busy():
            reply = QMessageBox.question(
                self, "Generation in Progress",
                "A generation is in progress. Close anyway?\n"
                "(Current request will be lost.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        event.accept()
