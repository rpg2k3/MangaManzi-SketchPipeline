"""Read-only LoRA registry tab."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import loras

_HEADERS = ["Name", "PixAI Model ID", "Weight", "Base Model", "Stage", "Status", "Triggers"]


class LoRAsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel("LoRA Registry")
        header.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(header)

        sub = QLabel(
            "Read-only. 9k9base is locked-in production. Sketch + per-character LoRAs "
            "are registered programmatically (app.loras.register) once their PixAI "
            "model IDs are available."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(sub)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(len(_HEADERS) - 1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        layout.addWidget(refresh_btn)

    def refresh(self):
        registry = loras.all_loras()
        self.table.setRowCount(len(registry))
        for row, name in enumerate(sorted(registry)):
            l = registry[name]
            status = "LOCKED" if l.locked else "PENDING" if "TBD" in l.pixai_model_id else "ACTIVE"
            cells = [
                l.name,
                l.pixai_model_id,
                f"{l.weight:.2f}",
                l.base_model,
                str(l.used_in_stage),
                status,
                l.trigger_words,
            ]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if col == 5 and status == "LOCKED":
                    item.setForeground(Qt.GlobalColor.darkGreen)
                elif col == 5 and status == "PENDING":
                    item.setForeground(Qt.GlobalColor.darkYellow)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
