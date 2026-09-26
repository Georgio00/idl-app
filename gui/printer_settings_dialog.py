"""
Small dialog for picking (and remembering) which physical printer the
"Print"/"Reprint" actions send finished IDL pages to — see
printing/printer_config.py and printing/print_dispatch.py.

This is a one-time-per-machine setup step (staff shouldn't need to touch
it on every print), reachable from the main form's "Printer Settings..."
button. Offers a dropdown of whatever Windows currently reports via
Get-Printer, with a manual text box as a fallback for the (hopefully rare)
case where that listing fails — see printing.printer_config.PrinterListError.

2026-09-26: added a SECOND, independent printer choice for cash receipts
(see printing/receipt_page.py, gui/new_idl_form.py's "Print Receipt") —
Georgio's video of LAA's own screen showed a separate "Print Receipt"
action, and a receipt is a complete, self-contained page meant for an
ordinary printer on plain paper, not the dedicated tray loaded with
special pre-printed IDP booklet pages. Rather than share one printer
setting between two genuinely different physical printers (risking a
booklet page wasted printing a receipt, or vice versa), this dialog now
has two sections, one per purpose (see printing.printer_config's `purpose`
param), saved together by the same Save button. Each section is
independently optional to fill in at any given time — leaving one blank
just means that purpose stays "not configured yet" (its own printer button
will prompt for it, same as before this change), not a validation error
here.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from printing.printer_config import (
    PrinterListError, get_configured_printer_name, list_available_printers, set_configured_printer_name,
)


class _PrinterChoice:
    """One purpose's combo + manual-entry row, factored out so __init__
    doesn't repeat the same five widgets/wiring twice for booklet vs
    receipt — see PrinterSettingsDialog.__init__."""

    def __init__(self, dialog: QDialog, layout: QVBoxLayout, purpose: str, description: str):
        self.purpose = purpose

        layout.addWidget(QLabel(description))

        self.combo = QComboBox()
        self.combo.setEditable(False)
        layout.addWidget(self.combo)
        self._populate_combo(dialog)

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Or type a printer name manually:"))
        self.manual_edit = QLineEdit()
        manual_row.addWidget(self.manual_edit)
        layout.addLayout(manual_row)

        current = get_configured_printer_name(purpose=self.purpose)
        if current:
            index = self.combo.findText(current)
            if index >= 0:
                self.combo.setCurrentIndex(index)
            else:
                # Previously configured but not in today's listing (e.g.
                # temporarily offline, or the listing failed) -- don't
                # silently lose what's actually configured.
                self.manual_edit.setText(current)

    def _populate_combo(self, dialog: QDialog):
        try:
            printers = list_available_printers()
        except PrinterListError as e:
            self.combo.setEnabled(False)
            self.combo.addItem("(could not list printers -- type the name below)")
            QMessageBox.warning(
                dialog, "Could not list printers",
                f"{e}\n\nYou can still type the exact printer name manually below.",
            )
            return

        if not printers:
            self.combo.addItem("(no printers found)")
            self.combo.setEnabled(False)
            return

        self.combo.addItems(printers)

    def resolved_name(self) -> str:
        """The name to save for this purpose -- manual entry wins over the
        combo when both are present, same precedence _save always used
        before this dialog had two sections."""
        return self.manual_edit.text().strip() or self.combo.currentText().strip()

    def save(self) -> None:
        set_configured_printer_name(self.resolved_name(), purpose=self.purpose)


class PrinterSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Printer Settings")
        self.resize(440, 320)

        layout = QVBoxLayout(self)

        self.booklet_choice = _PrinterChoice(
            self, layout, purpose="booklet",
            description=(
                "Choose the printer that has blank IDP booklet pages loaded.\n"
                "This is remembered on this machine for every Print / Reprint."
            ),
        )

        layout.addSpacing(12)

        self.receipt_choice = _PrinterChoice(
            self, layout, purpose="receipt",
            description=(
                "Choose the printer for cash receipts (plain paper) --\n"
                "a separate setting from the booklet printer above."
            ),
        )

        button_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_row.addStretch()
        button_row.addWidget(save_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

    def _save(self):
        # Each purpose is independently optional here -- a blank choice
        # just leaves that purpose "not configured yet" (its own printer
        # button already prompts for that when clicked), not a reason to
        # block saving the OTHER purpose someone actually did fill in.
        for choice in (self.booklet_choice, self.receipt_choice):
            name = choice.resolved_name()
            if name and name.startswith("("):
                QMessageBox.warning(
                    self, "Invalid selection",
                    "Choose a printer, or type one manually, for each printer you want to set.",
                )
                return

        for choice in (self.booklet_choice, self.receipt_choice):
            name = choice.resolved_name()
            if name and not name.startswith("("):
                choice.save()

        self.accept()
