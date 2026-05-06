"""Character Sheets — list + editor."""

import json
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import sheets
from app.ui.taxonomy import ARCHETYPES, archetype_head_count


_SLUG = re.compile(r"[^a-z0-9_]+")


def _slugify(name: str) -> str:
    return _SLUG.sub("_", name.lower().replace("-", "_").replace(" ", "_")).strip("_") or "untitled"


class SheetsTab(QWidget):
    sheet_saved = Signal(str)
    sheet_deleted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_id: str | None = None
        self._loaded_sheet: dict | None = None
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        outer = QHBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        # ── Left panel: list ──
        left = QWidget()
        ll = QVBoxLayout(left)

        h = QLabel("Sheets")
        h.setFont(QFont("", 12, QFont.Weight.Bold))
        ll.addWidget(h)

        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        ll.addWidget(self.list_widget, 1)

        new_btn = QPushButton("+ New Sheet")
        new_btn.clicked.connect(self._on_new_sheet)
        ll.addWidget(new_btn)

        splitter.addWidget(left)

        # ── Right panel: editor ──
        right = QWidget()
        rl = QVBoxLayout(right)

        self.editor_header = QLabel("(no sheet selected)")
        self.editor_header.setFont(QFont("", 14, QFont.Weight.Bold))
        rl.addWidget(self.editor_header)

        # Identity
        identity = QGroupBox("Identity")
        idf = QFormLayout(identity)
        self.id_label = QLabel("—")
        self.id_label.setStyleSheet("color: #666; font-family: monospace;")
        idf.addRow("ID:", self.id_label)
        self.name_edit = QLineEdit()
        idf.addRow("Name:", self.name_edit)
        self.archetype_combo = QComboBox()
        for code, label, _ in ARCHETYPES:
            self.archetype_combo.addItem(label, code)
        idf.addRow("Archetype:", self.archetype_combo)
        rl.addWidget(identity)

        # Character LoRA
        lora_group = QGroupBox("Character LoRA")
        lf = QFormLayout(lora_group)
        lora_note = QLabel(
            "Character LoRA is optional. Sheets without a LoRA can still drive "
            "Stage 3 generation using prompt composition alone."
        )
        lora_note.setStyleSheet("color: #888; font-style: italic;")
        lora_note.setWordWrap(True)
        lf.addRow(lora_note)

        self.linked_lora_edit = QLineEdit()
        self.linked_lora_edit.setPlaceholderText("PixAI model ID (or leave blank)")
        self.linked_lora_edit.textChanged.connect(self._on_linked_lora_changed)
        lf.addRow("linkedLoraId:", self.linked_lora_edit)
        self.trigger_words_edit = QLineEdit()
        self.trigger_words_edit.setPlaceholderText("comma-separated trigger words")
        lf.addRow("triggerWords:", self.trigger_words_edit)

        weight_row = QHBoxLayout()
        self.lora_weight_slider = QSlider(Qt.Orientation.Horizontal)
        self.lora_weight_slider.setMinimum(0)
        self.lora_weight_slider.setMaximum(200)
        self.lora_weight_slider.setValue(100)
        self.lora_weight_slider.setTickInterval(25)
        self.lora_weight_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.lora_weight_value = QLabel("1.00")
        self.lora_weight_value.setMinimumWidth(40)
        self.lora_weight_slider.valueChanged.connect(
            lambda v: self.lora_weight_value.setText(f"{v / 100:.2f}")
        )
        weight_row.addWidget(self.lora_weight_slider, 1)
        weight_row.addWidget(self.lora_weight_value)
        lf.addRow("loraWeight:", weight_row)
        rl.addWidget(lora_group)

        # Design notes
        notes_group = QGroupBox("Design Notes")
        nf = QVBoxLayout(notes_group)
        self.design_notes_edit = QPlainTextEdit()
        self.design_notes_edit.setPlaceholderText(
            "Personality, height vs other characters, lore, voice, etc."
        )
        nf.addWidget(self.design_notes_edit)
        rl.addWidget(notes_group)

        # Outfit variants
        self.outfit_list, outfit_group = self._build_string_list(
            "Outfit Variants",
            placeholder="e.g. formal, travel, combat",
            on_add=self._on_add_outfit,
        )
        rl.addWidget(outfit_group)

        # Continuity rules
        self.rules_list, rules_group = self._build_string_list(
            "Continuity Rules",
            placeholder="e.g. cat ears must remain pointed",
            on_add=self._on_add_rule,
        )
        rl.addWidget(rules_group)

        # Learned drifts (read-only)
        learned_group = QGroupBox("Learned Drifts (auto-populated)")
        learnf = QVBoxLayout(learned_group)
        self.learned_list = QListWidget()
        self.learned_list.setMaximumHeight(120)
        learnf.addWidget(self.learned_list)
        rl.addWidget(learned_group)

        # Save / Delete
        actions = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.save_btn.setMinimumHeight(32)
        self.save_btn.clicked.connect(self._on_save)
        actions.addWidget(self.save_btn)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._on_delete)
        actions.addWidget(self.delete_btn)
        rl.addLayout(actions)

        rl.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([220, 800])

        self._set_editor_enabled(False)

    def _build_string_list(self, title: str, *, placeholder: str, on_add):
        group = QGroupBox(title)
        v = QVBoxLayout(group)
        list_widget = QListWidget()
        list_widget.setMaximumHeight(120)
        v.addWidget(list_widget)

        row = QHBoxLayout()
        add_btn = QPushButton("Add…")
        add_btn.clicked.connect(on_add)
        row.addWidget(add_btn)
        rm_btn = QPushButton("Remove Selected")
        rm_btn.clicked.connect(lambda: self._remove_selected(list_widget))
        row.addWidget(rm_btn)
        row.addStretch()
        v.addLayout(row)
        return list_widget, group

    # ── List handling ──

    def refresh_list(self):
        current = self._current_id
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for sid in sheets.list_ids():
            QListWidgetItem(sid, self.list_widget)
        self.list_widget.blockSignals(False)
        if current:
            for i in range(self.list_widget.count()):
                if self.list_widget.item(i).text() == current:
                    self.list_widget.setCurrentRow(i)
                    return
        if not sheets.list_ids():
            self._set_editor_enabled(False)
            self.editor_header.setText("(no sheets — click '+ New Sheet')")

    def _on_selection_changed(self):
        items = self.list_widget.selectedItems()
        if not items:
            self._current_id = None
            self._set_editor_enabled(False)
            self.editor_header.setText("(no sheet selected)")
            return
        sid = items[0].text()
        self._load_into_editor(sid)

    def _load_into_editor(self, sheet_id: str):
        try:
            sheet = sheets.load(sheet_id)
        except Exception as e:
            QMessageBox.warning(self, "Load failed", str(e))
            return
        self._current_id = sheet_id
        self._loaded_sheet = sheet
        self.editor_header.setText(sheet.get("name") or sheet_id)
        self.id_label.setText(sheet_id)
        self.name_edit.setText(sheet.get("name") or "")

        archetype = sheet.get("archetype")
        idx = next((i for i, (code, _, _) in enumerate(ARCHETYPES) if code == archetype), 0)
        self.archetype_combo.setCurrentIndex(idx)

        self.linked_lora_edit.setText(sheet.get("linkedLoraId") or "")
        self.trigger_words_edit.setText(sheet.get("triggerWords") or "")
        weight = float(sheet.get("loraWeight") or 1.0)
        self.lora_weight_slider.setValue(int(round(weight * 100)))
        self.lora_weight_value.setText(f"{weight:.2f}")
        self.design_notes_edit.setPlainText(sheet.get("designNotes") or "")
        self._on_linked_lora_changed()  # sync slider/triggerWords enabled state

        self._fill_list(self.outfit_list, sheet.get("outfitVariants") or [])
        self._fill_list(self.rules_list, sheet.get("continuityRules") or [])

        self.learned_list.clear()
        for d in sheet.get("learnedDrifts") or []:
            aspect = d.get("aspect", "?")
            count = d.get("scene_count", "?")
            QListWidgetItem(f"{aspect} (seen in {count} scenes)", self.learned_list)

        self._set_editor_enabled(True)

    def _fill_list(self, widget: QListWidget, items: list):
        widget.clear()
        for item in items:
            display = item if isinstance(item, str) else json.dumps(item)
            QListWidgetItem(display, widget)

    def _set_editor_enabled(self, enabled: bool):
        for w in (
            self.name_edit, self.archetype_combo, self.linked_lora_edit,
            self.trigger_words_edit, self.lora_weight_slider, self.design_notes_edit,
            self.outfit_list, self.rules_list,
            self.save_btn, self.delete_btn,
        ):
            w.setEnabled(enabled)

    # ── LoRA-section enabled state ──

    def _on_linked_lora_changed(self):
        has_lora = bool(self.linked_lora_edit.text().strip())
        self.trigger_words_edit.setEnabled(has_lora)
        self.lora_weight_slider.setEnabled(has_lora)
        self.lora_weight_value.setEnabled(has_lora)

    # ── Actions ──

    def _on_new_sheet(self):
        name, ok = QInputDialog.getText(self, "New Sheet", "Character name:")
        if not ok or not name.strip():
            return
        cid = _slugify(name)
        if sheets.exists(cid):
            QMessageBox.warning(self, "Sheet exists",
                                f"A sheet named '{cid}' already exists.")
            return
        new_sheet = sheets.upgrade_sheet({
            "id": cid,
            "character_id": cid,
            "name": name.strip(),
            "archetype": ARCHETYPES[0][0],
            "head_count": ARCHETYPES[0][2],
        })
        sheets.save(new_sheet)
        self.sheet_saved.emit(cid)
        self.refresh_list()
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).text() == cid:
                self.list_widget.setCurrentRow(i)
                break

    def _on_add_outfit(self):
        text, ok = QInputDialog.getText(self, "Add Outfit Variant", "Variant name:")
        if ok and text.strip():
            QListWidgetItem(text.strip(), self.outfit_list)

    def _on_add_rule(self):
        text, ok = QInputDialog.getText(self, "Add Continuity Rule", "Rule:")
        if ok and text.strip():
            QListWidgetItem(text.strip(), self.rules_list)

    def _remove_selected(self, widget: QListWidget):
        for item in widget.selectedItems():
            widget.takeItem(widget.row(item))

    def _on_save(self):
        if not self._current_id or self._loaded_sheet is None:
            return
        linked = self.linked_lora_edit.text().strip()
        triggers = self.trigger_words_edit.text().strip()
        if linked and not triggers:
            QMessageBox.warning(
                self, "Triggers required",
                "When linkedLoraId is set, triggerWords must also be provided "
                "(the LoRA needs them to activate at generation time).",
            )
            return

        sheet = dict(self._loaded_sheet)
        sheet["id"] = self._current_id
        sheet["character_id"] = self._current_id
        sheet["name"] = self.name_edit.text().strip()
        archetype_code = self.archetype_combo.currentData()
        sheet["archetype"] = archetype_code
        sheet["head_count"] = archetype_head_count(archetype_code)
        sheet["linkedLoraId"] = linked or None
        sheet["triggerWords"] = triggers or None
        sheet["loraWeight"] = self.lora_weight_slider.value() / 100.0
        sheet["designNotes"] = self.design_notes_edit.toPlainText().strip()
        sheet["outfitVariants"] = [
            self.outfit_list.item(i).text() for i in range(self.outfit_list.count())
        ]
        sheet["continuityRules"] = [
            self.rules_list.item(i).text() for i in range(self.rules_list.count())
        ]
        try:
            sheets.save(sheet)
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return
        self._loaded_sheet = sheet
        self.editor_header.setText(sheet["name"] or self._current_id)
        self.sheet_saved.emit(self._current_id)
        QMessageBox.information(self, "Saved", f"Sheet '{self._current_id}' saved.")

    def _on_delete(self):
        if not self._current_id:
            return
        reply = QMessageBox.question(
            self, "Delete Sheet",
            f"Delete sheet '{self._current_id}'? This removes data/sheets/{self._current_id}.json.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        sheets.delete(self._current_id)
        sid = self._current_id
        self._current_id = None
        self._loaded_sheet = None
        self.sheet_deleted.emit(sid)
        self.refresh_list()
