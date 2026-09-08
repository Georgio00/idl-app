"""
Small dialog for picking (and remembering) which physical printer the
"Print" and "Reprint" actions send finished IDL pages to — see
printing/printer_config.py and printing/print_dispatch.py.

This is a one-time-per-machine setup step (staff shouldn't need to touch
it on every print), reachable from the main form's "Printer Settings..."
button. Offers a dropdown of whatever Windows currently reports via
Get-Printer, with a manual text box as a fallback for the (hopefully rare)
case where that listing fails — see printing.printer_config.PrinterListError.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from printing.printer_config import (
    PrinterListError, get_configured_printer_name, list_available_printers, set_configured_printer_name,
)


class PrinterSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Printer Settings")
        self.resize(420, 160)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Choose the printer that has blank IDP booklet pages loaded.\n"
            "This is remembered on this machine for every Print / Reprint."
        ))

        self.printer_combo = QComboBox()
        self.printer_combo.setEditable(False)
        layout.addWidget(self.printer_combo)

        self._populate_combo()

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Or type a printer name manually:"))
        self.manual_edit = QLineEdit()
        manual_row.addWidget(self.manual_edit)
        layout.addLayout(manual_row)

        current = get_configured_printer_name()
        if current:
            index = self.printer_combo.findText(current)
            if index >= 0:
                self.printer_combo.setCurrentIndex(index)
            else:
                # Previously configured but not in today's listing (e.g.
                # temporarily offline, or the listing failed) -- don't
                # silently lose what's actually configured.
                self.manual_edit.setText(current)

        button_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_row.addStretch()
        button_row.addWidget(save_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

    def _populate_combo(self):
        try:
            printers = list_available_printers()
        except PrinterListError as e:
            self.printer_combo.setEnabled(False)
            self.printer_combo.addItem("(could not list printers -- type the name below)")
            QMessageBox.warning(
                self, "Could not list printers",
                f"{e}\n\nYou can still type the exact printer name manually below.",
            )
            return

        if not printers:
            self.printer_combo.addItem("(no printers found)")
            self.printer_combo.setEnabled(False)
            return

        self.printer_combo.addItems(printers)

    def _save(self):
        name = self.manual_edit.text().strip() or self.printer_combo.currentText().strip()
        if not name or name.startswith("("):
            QMessageBox.warning(self, "No printer selected", "Choose a printer, or type one manually.")
            return
        set_configured_printer_name(name)
        self.accept()
