"""Main tabbed window — Beta workspace.

Tabs: Generate (default), Sheets, LoRAs, Settings.
Generate is the default landing tab so the studio flow is one click away.
"""

from PySide6.QtWidgets import QMainWindow, QMessageBox, QTabWidget

from app.ui.generate_tab import GenerateTab
from app.ui.loras_tab import LoRAsTab
from app.ui.settings_tab import SettingsTab
from app.ui.sheets_tab import SheetsTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("9LivesK9 Sketch Pipeline")
        self.setMinimumSize(1100, 800)
        self.resize(1300, 920)
        self._build_ui()

    def _build_ui(self):
        self.tabs = QTabWidget()

        self.generate_tab = GenerateTab()
        self.sheets_tab = SheetsTab()
        self.loras_tab = LoRAsTab()
        self.settings_tab = SettingsTab()

        self.tabs.addTab(self.generate_tab, "Generate")
        self.tabs.addTab(self.sheets_tab, "Sheets")
        self.tabs.addTab(self.loras_tab, "LoRAs")
        self.tabs.addTab(self.settings_tab, "Settings")

        self.sheets_tab.sheet_saved.connect(lambda _: self.generate_tab.refresh_sheet_list())
        self.sheets_tab.sheet_deleted.connect(lambda _: self.generate_tab.refresh_sheet_list())

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

    def _on_tab_changed(self, index: int):
        widget = self.tabs.widget(index)
        if widget is self.loras_tab:
            self.loras_tab.refresh()
        elif widget is self.generate_tab:
            self.generate_tab.refresh_sheet_list()
        elif widget is self.sheets_tab:
            self.sheets_tab.refresh_list()

    def closeEvent(self, event):
        worker = getattr(self.generate_tab, "_worker", None)
        if worker is not None and worker.isRunning():
            reply = QMessageBox.question(
                self, "Pipeline running",
                "A generation is in progress. Close anyway?\n"
                "(Current PixAI request will be lost.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        event.accept()
