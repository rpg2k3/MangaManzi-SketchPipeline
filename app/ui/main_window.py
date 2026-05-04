"""Main tabbed window with generation state intercepts."""

from PySide6.QtWidgets import QMainWindow, QTabWidget, QMessageBox

from app.ui.settings_tab import SettingsTab
from app.ui.mannequin_tab import MannequinTab
from app.ui.sketch_tab import SketchTab
from app.ui.library_tab import LibraryTab
from app.ui.comparison_tab import ComparisonTab
from app.ui.chatgpt_base_tab import ChatGPTBaseTab
from app.ui.chatgpt_sketch_tab import ChatGPTSketchTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("9LivesK9 Sketch Pipeline")
        self.setMinimumSize(900, 750)
        self.resize(1050, 850)
        self._build_ui()

    def _build_ui(self):
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.settings_tab = SettingsTab()
        self.mannequin_tab = MannequinTab()
        self.sketch_tab = SketchTab()
        self.library_tab = LibraryTab()
        self.comparison_tab = ComparisonTab()
        self.chatgpt_base_tab = ChatGPTBaseTab()
        self.chatgpt_sketch_tab = ChatGPTSketchTab()

        self.tabs.addTab(self.mannequin_tab, "Mannequin Generation")
        self.tabs.addTab(self.sketch_tab, "Sketch Generation")
        self.tabs.addTab(self.library_tab, "Library")
        self.tabs.addTab(self.comparison_tab, "Comparison")
        self.tabs.addTab(self.chatgpt_base_tab, "Chat_GPT — Base")
        self.tabs.addTab(self.chatgpt_sketch_tab, "Chat_GPT — Sketch")
        self.tabs.addTab(self.settings_tab, "Settings")

        self.setCentralWidget(self.tabs)

    def _on_tab_changed(self, index):
        widget = self.tabs.widget(index)
        if widget == self.library_tab:
            self.library_tab.refresh()

    def _is_any_busy(self):
        return (
            self.mannequin_tab.is_busy()
            or self.sketch_tab.is_busy()
            or self.chatgpt_base_tab.is_busy()
            or self.chatgpt_sketch_tab.is_busy()
        )

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
