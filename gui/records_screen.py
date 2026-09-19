"""
Records screen — search, open (for editing/re-saving), reprint, or clone a
previously saved IDL record.

2026-09-07: added because the app had no way to do any of this. Before
this screen existed, "New IDL" could only ever create a new record: there
was no path back to a record after Save, so the first time a customer
came back asking for a reprint, or staff noticed a typo after the fact,
there was genuinely nothing the app could do about it short of opening the
encrypted SQLite file by hand. This is a plain modal dialog (not a
separate always-open window) reachable from a "Find / Reprint Record..."
button on the main form, matching how LAA-style internal tools usually
structure a "browse then act" screen.

Search is a simple client-side substring filter over the already-decrypted
list_records() result (see db/storage.py's docstring on why decrypting the
whole table is fine at this app's scale) — no SQL LIKE query against the
encrypted column is possible anyway, since the fields are opaque
ciphertext at rest by design. Typing a driving license number (Original
Document.Number) into the search box finds it the same way any other
field does, since _matches() checks every field's value.

2026-09-19: added "Clone as New Record" (on request, after Georgio shared
a video of LAA's own equivalent workflow: a returning client's driving
license number is searched, then LAA's "Clone" button starts a brand new
IDL prefilled with that client's personal/original-document/receipt-payer
details, with only the Issued Document Number and Date reset for the new
transaction). This is deliberately a THIRD action distinct from both
"Open for Edit" (which UPDATES the same historical row — wrong here, since
that would silently overwrite the old visit's record) and "Reprint" (which
doesn't create anything new at all) — see gui/new_idl_form.py's
_clone_record docstring for exactly which fields carry over vs. reset.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from db.storage import IdlRecord, Storage

# Columns shown in the results table, in order: (header, field-dict key or
# None for the record's own id/created_at columns).
_COLUMNS: list[tuple[str, str | None]] = [
    ("ID", None),
    ("Created", None),
    ("Surname", "Surname"),
    ("First Name", "First Name"),
    ("Original Doc #", "Original Document.Number"),
    ("Issued Doc #", "Issued Document.Number"),
]


def _matches(record: IdlRecord, needle: str) -> bool:
    if not needle:
        return True
    needle = needle.lower()
    haystacks = [str(record.id), record.created_at]
    haystacks.extend(str(v) for v in record.fields.values())
    return any(needle in h.lower() for h in haystacks if h)


class RecordsScreen(QDialog):
    # Emitted with (record_id, fields dict) when the user picks Open —
    # the main form is responsible for loading these into itself and
    # switching into "editing an existing record" mode (see
    # gui/new_idl_form.py's _load_record).
    record_opened = Signal(int, dict)

    # Emitted with (source_record_id, fields dict) when the user picks
    # "Clone as New Record" — see gui/new_idl_form.py's _clone_record for
    # what it does with these (NOT the same as record_opened: cloning
    # starts a brand new, unsaved record rather than editing source_record_id).
    record_cloned = Signal(int, dict)

    def __init__(self, storage: Storage, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.setWindowTitle("Find / Reprint Record")
        self.resize(760, 480)

        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Name, document number, or record ID...")
        self.search_box.textChanged.connect(self._refresh_table)
        search_row.addWidget(self.search_box)
        layout.addLayout(search_row)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels([h for h, _ in _COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._open_selected)
        layout.addWidget(self.table)

        button_row = QHBoxLayout()
        self.open_btn = QPushButton("Open for Edit")
        self.open_btn.clicked.connect(self._open_selected)
        self.clone_btn = QPushButton("Clone as New Record")
        self.clone_btn.setToolTip(
            "Start a brand new IDL for a returning client, reusing this record's "
            "personal/original-document/receipt-payer details. The old record is "
            "left untouched — only the Issued Document Number and Date are reset "
            "for the new transaction."
        )
        self.clone_btn.clicked.connect(self._clone_selected)
        self.reprint_btn = QPushButton("Reprint")
        self.reprint_btn.clicked.connect(self._reprint_selected)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)
        button_row.addWidget(self.open_btn)
        button_row.addWidget(self.clone_btn)
        button_row.addWidget(self.reprint_btn)
        button_row.addStretch()
        button_row.addWidget(self.close_btn)
        layout.addLayout(button_row)

        self._all_records: list[IdlRecord] = []
        self._visible_records: list[IdlRecord] = []
        self._reload_records()

    def _reload_records(self):
        self._all_records = self.storage.list_records()
        self._refresh_table()

    def _refresh_table(self):
        needle = self.search_box.text().strip()
        self._visible_records = [r for r in self._all_records if _matches(r, needle)]

        self.table.setRowCount(len(self._visible_records))
        for row, record in enumerate(self._visible_records):
            for col, (_, field_key) in enumerate(_COLUMNS):
                if field_key is None:
                    text = str(record.id) if col == 0 else record.created_at.split("T")[0]
                else:
                    text = record.fields.get(field_key, "")
                self.table.setItem(row, col, QTableWidgetItem(text))

    def _selected_record(self) -> IdlRecord | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._visible_records):
            return None
        return self._visible_records[row]

    def _open_selected(self):
        record = self._selected_record()
        if record is None:
            QMessageBox.information(self, "No selection", "Select a record first.")
            return
        self.record_opened.emit(record.id, record.fields)
        self.accept()

    def _clone_selected(self):
        record = self._selected_record()
        if record is None:
            QMessageBox.information(self, "No selection", "Select a record first.")
            return
        self.record_cloned.emit(record.id, record.fields)
        self.accept()

    def _reprint_selected(self):
        """2026-09-08: sends straight to the configured printer (see
        printing/print_dispatch.py and printer_config.py) instead of
        opening a PDF viewer -- unlike the main form's fresh Autofill
        result, a saved record's data has already been reviewed and saved
        once, so "Reprint" reads as "print another physical copy," not
        "let me look at this again." Staff who genuinely want to just look
        at it first can still Open it into the main form and use Print
        Preview there."""
        record = self._selected_record()
        if record is None:
            QMessageBox.information(self, "No selection", "Select a record first.")
            return

        from db.audit_log import log_print_dispatch_failed, log_print_dispatched
        from db.storage import APP_DATA_DIR
        from printing.print_dispatch import print_pdf_to_printer
        from printing.print_page import render_idl_data_page
        from printing.printer_config import get_configured_printer_name

        printer_name = get_configured_printer_name()
        if not printer_name:
            QMessageBox.warning(
                self, "No printer configured",
                "Set a printer first from the main form's \"Printer Settings...\" button "
                "before reprinting.",
            )
            return

        confirm = QMessageBox.question(
            self, "Reprint to physical booklet page",
            f"This will print record #{record.id} onto a real blank IDP booklet page "
            f"loaded in \"{printer_name}\". Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        output_path = str(APP_DATA_DIR / f"reprint_record_{record.id}.pdf")
        try:
            render_idl_data_page(record.fields, output_path)
            print_pdf_to_printer(output_path, printer_name)
        except Exception as e:  # noqa: BLE001 - surface any failure (PrintDispatchError or otherwise), never a silent no-op
            log_print_dispatch_failed(record.id, printer_name, str(e))
            QMessageBox.critical(self, "Reprint failed", f"Could not print to {printer_name!r}: {e}")
            return

        log_print_dispatched(record.id, printer_name, output_path)
        QMessageBox.information(self, "Sent to printer", f"Sent to {printer_name}.")
