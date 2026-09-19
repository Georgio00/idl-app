"""
Regression tests for gui/records_screen.py's 2026-09-19 "Clone as New
Record" button (see that module's docstring): Georgio shared a video of
LAA's own equivalent -- a returning client's driving license number is
searched, then LAA's "Clone" starts a brand new IDL prefilled with that
client's details, distinct from "Open for Edit" (which would instead
UPDATE the old record) and "Reprint" (which doesn't create anything).

Unlike tests/test_records_screen_matching.py (which deliberately avoided
instantiating RecordsScreen itself, predating this project's later
headless-Qt testing pattern), these DO instantiate the real dialog,
headless via QT_QPA_PLATFORM=offscreen -- the same pattern
tests/test_new_idl_form.py established for gui/new_idl_form.py. A plain
stand-in object (not a MagicMock) stands in for Storage here since
RecordsScreen only ever calls .list_records() on it, never anything
Storage-specific enough to need mocking's stricter isolation.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QDialog

_app = QApplication.instance() or QApplication([])

from db.storage import IdlRecord
from gui.records_screen import RecordsScreen


class _StubStorage:
    """Stands in for db.storage.Storage: RecordsScreen only ever calls
    list_records() on whatever it's given."""

    def __init__(self, records: list[IdlRecord]):
        self._records = records

    def list_records(self) -> list[IdlRecord]:
        return list(self._records)


def _sample_record(record_id=7) -> IdlRecord:
    return IdlRecord(
        id=record_id, created_at="2026-09-07T10:00:00",
        fields={
            "Surname": "KORDAHI", "First Name": "KARIM", "Father's Name": "KAMAL",
            "Place of B.": "JBEIL", "Date of B.": "16/09/1981",
            "Original Document.Number": "1512683", "Original Document.Date": "18/11/1999",
            "Original Document.Place of Issue": "CGCV", "Original Document.Category": "B",
            "Original Document.Expiry Date": "18/11/2031",
            "Issued Document.Number": "344629", "Issued Document.Date": "10/09/2026",
            "Receipt.Received from": "KARIM KORDAHI", "Receipt.Amount(LBP)": "5000000",
            "Receipt.Date": "10/09/2026",
        },
    )


def _make_dialog(records: list[IdlRecord]) -> RecordsScreen:
    return RecordsScreen(_StubStorage(records))


class CloneButtonTest(unittest.TestCase):
    def setUp(self):
        self.record = _sample_record()
        self.dialog = _make_dialog([self.record])
        self.dialog.table.selectRow(0)

    def test_clone_button_exists_alongside_open_and_reprint(self):
        self.assertEqual(self.dialog.clone_btn.text(), "Clone as New Record")

    def test_clicking_clone_emits_record_cloned_with_source_id_and_fields(self):
        received = []
        self.dialog.record_cloned.connect(lambda rid, fields: received.append((rid, fields)))

        self.dialog._clone_selected()

        self.assertEqual(len(received), 1)
        rid, fields = received[0]
        self.assertEqual(rid, self.record.id)
        self.assertEqual(fields, self.record.fields)

    def test_clone_does_not_emit_record_opened(self):
        # Cloning and opening-for-edit must stay distinct signals -- a
        # listener wired only to record_opened (like the real
        # NewIDLForm._load_record) must never fire on a Clone.
        opened = []
        self.dialog.record_opened.connect(lambda rid, fields: opened.append(rid))

        self.dialog._clone_selected()

        self.assertEqual(opened, [])

    def test_clone_closes_the_dialog_with_accepted_result(self):
        self.dialog._clone_selected()
        self.assertEqual(self.dialog.result(), QDialog.Accepted)

    def test_clone_with_no_selection_shows_a_message_and_emits_nothing(self):
        dialog = _make_dialog([self.record])  # fresh dialog, nothing selected
        received = []
        dialog.record_cloned.connect(lambda rid, fields: received.append(rid))

        with mock.patch("gui.records_screen.QMessageBox") as mock_box:
            dialog._clone_selected()

        mock_box.information.assert_called_once()
        self.assertEqual(received, [])


if __name__ == "__main__":
    unittest.main()
