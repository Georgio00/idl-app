"""
Regression tests for db/storage.py.

2026-09-07: added as part of making this a real company tool -- until now
the database layer (the only place saved IDL records actually live) had
ZERO automated test coverage; every one of this project's ~200 existing
tests exercises the OCR pipeline exclusively. These tests use a temporary
db/key path per test (never the real %LOCALAPPDATA%\\IDL_APP\\ location)
so they can't ever touch or corrupt a real machine's saved records.

Covers update_record specifically (new this same day, for the Records
screen's Open-then-Save-again flow) since a bug there would silently
either corrupt a real record or create an untracked duplicate -- exactly
the failure mode the Records screen was built to eliminate.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.storage import Storage


def _make_storage(tmp_dir: Path) -> Storage:
    return Storage(db_path=tmp_dir / "test.db", key_path=tmp_dir / "test.key")


class SaveAndGetRecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.storage = _make_storage(self.tmp_dir)

    def test_saved_record_round_trips_exactly(self):
        fields = {"Surname": "EL ALAM", "First Name": "GEORGES"}
        record_id = self.storage.save_record(fields)
        record = self.storage.get_record(record_id)
        self.assertEqual(record.fields, fields)

    def test_unknown_id_returns_none(self):
        self.assertIsNone(self.storage.get_record(999))

    def test_records_are_encrypted_at_rest(self):
        # The whole point of Fernet-encrypting each record (see the module
        # docstring): the raw .db file must never contain a saved name in
        # plain, greppable text.
        record_id = self.storage.save_record({"Surname": "VERYDISTINCTIVESURNAME"})
        self.assertIsNotNone(record_id)
        raw_bytes = (self.tmp_dir / "test.db").read_bytes()
        self.assertNotIn(b"VERYDISTINCTIVESURNAME", raw_bytes)

    def test_next_issued_document_number_increments(self):
        first = self.storage.next_issued_document_number()
        second = self.storage.next_issued_document_number()
        self.assertNotEqual(first, second)


class ListRecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.storage = _make_storage(self.tmp_dir)

    def test_lists_newest_first(self):
        first_id = self.storage.save_record({"Surname": "FIRST"})
        second_id = self.storage.save_record({"Surname": "SECOND"})
        records = self.storage.list_records()
        self.assertEqual([r.id for r in records], [second_id, first_id])

    def test_empty_database_returns_empty_list(self):
        self.assertEqual(self.storage.list_records(), [])


class UpdateRecordTest(unittest.TestCase):
    """2026-09-07: the Records screen's core safety property -- re-saving
    an opened record must correct that same row, never create a second
    one (the exact bug this whole feature exists to fix, see
    gui/new_idl_form.py's save_record docstring)."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.storage = _make_storage(self.tmp_dir)

    def test_update_changes_the_same_row_not_a_new_one(self):
        record_id = self.storage.save_record({"Surname": "ELALAM"})
        self.storage.update_record(record_id, {"Surname": "EL ALAM"})

        records = self.storage.list_records()
        self.assertEqual(len(records), 1, "update_record must not create a second row")
        self.assertEqual(records[0].id, record_id)
        self.assertEqual(records[0].fields["Surname"], "EL ALAM")

    def test_update_unknown_id_raises_rather_than_silently_no_opping(self):
        with self.assertRaises(ValueError):
            self.storage.update_record(999, {"Surname": "GHOST"})

    def test_update_preserves_created_at(self):
        record_id = self.storage.save_record({"Surname": "ELALAM"})
        original_created_at = self.storage.get_record(record_id).created_at
        self.storage.update_record(record_id, {"Surname": "EL ALAM"})
        self.assertEqual(self.storage.get_record(record_id).created_at, original_created_at)


if __name__ == "__main__":
    unittest.main()
