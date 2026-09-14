"""
Regression tests for gui/new_idl_form.py's 2026-09-14 changes (on request):

  1. The personal-details group is trimmed to just Surname, First Name,
     Father's Name, Place of B., Date of B. -- Mother's Name, Address,
     Phone, Email, Blood Type are gone from the screen entirely.
  2. "Original Document.Place of Issue" defaults to "CGCV".
  3. "Receipt.Received from" auto-fills live from Surname + First Name as
     either is typed, unless staff have typed something else into it by
     hand -- see _sync_received_from_name's docstring in new_idl_form.py
     for the exact rule.

These instantiate the REAL NewIDLForm widget (not a mock of it) against a
real, isolated QApplication, run headless via QT_QPA_PLATFORM=offscreen --
there is no display in this environment and none is needed to exercise
plain field wiring/signal logic. Storage is replaced with a MagicMock
(patched into gui.new_idl_form.Storage before construction) rather than a
real Storage(): NewIDLForm.__init__ hardcodes a no-argument `Storage()`
call, and Storage's own db_path/key_path defaults are bound at
db/storage.py's import time, so patching db.storage.DEFAULT_DB_PATH after
the fact would NOT reach that already-bound default -- the only way to
keep these tests from touching a real machine's saved records is to
replace the Storage class itself at the point new_idl_form.py imports it.
Nothing here calls save/load, so a MagicMock is sufficient and avoids
real file I/O entirely. RecordsScreen/PrinterSettingsDialog are never
opened by these tests, so they need no similar treatment.
"""

import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

# A single QApplication for the whole process -- Qt only allows one, and
# creating it lazily here (rather than per-test) matches how every real
# entry point (gui/new_idl_form.py's main()) does it too.
_app = QApplication.instance() or QApplication([])

with mock.patch("gui.new_idl_form.Storage"):
    from gui.new_idl_form import DEFAULT_PLACE_OF_ISSUE, NewIDLForm


def _make_form() -> NewIDLForm:
    with mock.patch("gui.new_idl_form.Storage"):
        return NewIDLForm()


class PersonalFieldsTrimmedTest(unittest.TestCase):
    def setUp(self):
        self.form = _make_form()

    def test_kept_fields_are_present(self):
        for label in ("Surname", "First Name", "Father's Name", "Place of B.", "Date of B."):
            self.assertIn(label, self.form.fields)

    def test_dropped_fields_are_absent(self):
        for label in ("Mother's Name", "Address", "Phone", "Email", "Blood Type"):
            self.assertNotIn(label, self.form.fields)

    def test_original_and_issued_document_groups_are_untouched(self):
        for label in ("Number", "Date", "Place of Issue", "Category", "Expiry Date"):
            self.assertIn(f"Original Document.{label}", self.form.fields)
        for label in ("Number", "Date", "Signature"):
            self.assertIn(f"Issued Document.{label}", self.form.fields)
        for label in ("Received from", "Date", "Amount(LBP)"):
            self.assertIn(f"Receipt.{label}", self.form.fields)


class PlaceOfIssueDefaultTest(unittest.TestCase):
    def test_defaults_to_cgcv_on_construction(self):
        form = _make_form()
        self.assertEqual(DEFAULT_PLACE_OF_ISSUE, "CGCV")
        self.assertEqual(form.fields["Original Document.Place of Issue"].text(), "CGCV")

    def test_still_a_plain_editable_field_not_locked(self):
        form = _make_form()
        field = form.fields["Original Document.Place of Issue"]
        self.assertTrue(field.isEnabled())
        self.assertFalse(field.isReadOnly())
        field.setText("SOMEWHERE ELSE")
        self.assertEqual(field.text(), "SOMEWHERE ELSE")

    def test_issued_document_date_still_defaults_to_today(self):
        # Not part of this change, but touched the same init code path --
        # worth pinning down so a future edit near it can't silently break
        # this pre-existing default without a test noticing.
        form = _make_form()
        expected = date.today().strftime("%d/%m/%Y")
        self.assertEqual(form.fields["Issued Document.Date"].text(), expected)


class ReceivedFromLiveSyncTest(unittest.TestCase):
    def setUp(self):
        self.form = _make_form()
        self.received_from = self.form.fields["Receipt.Received from"]

    def test_syncs_from_surname_alone(self):
        self.form.fields["Surname"].setText("KORDAHI")
        self.assertEqual(self.received_from.text(), "KORDAHI")

    def test_syncs_from_first_name_alone(self):
        self.form.fields["First Name"].setText("KARIM")
        self.assertEqual(self.received_from.text(), "KARIM")

    def test_syncs_as_first_name_then_surname_order(self):
        # Matches LAA's own convention (screenshot: "Received from: KARIM
        # KORDAHI" for Surname=KORDAHI, First Name=KARIM) -- First Name
        # before Surname, not the other way around.
        self.form.fields["Surname"].setText("KORDAHI")
        self.form.fields["First Name"].setText("KARIM")
        self.assertEqual(self.received_from.text(), "KARIM KORDAHI")

    def test_keeps_following_further_edits(self):
        self.form.fields["Surname"].setText("KORDAHI")
        self.form.fields["First Name"].setText("KARIM")
        self.form.fields["Surname"].setText("KHOURY")
        self.assertEqual(self.received_from.text(), "KARIM KHOURY")

    def test_manual_override_is_not_clobbered_by_a_later_name_edit(self):
        self.form.fields["Surname"].setText("KORDAHI")
        self.form.fields["First Name"].setText("KARIM")
        self.received_from.setText("PAID BY COMPANY XYZ")

        self.form.fields["Surname"].setText("KHOURY")

        self.assertEqual(self.received_from.text(), "PAID BY COMPANY XYZ")

    def test_sync_resumes_once_received_from_is_cleared_back_to_empty(self):
        self.form.fields["Surname"].setText("KORDAHI")
        self.form.fields["First Name"].setText("KARIM")
        self.received_from.setText("PAID BY COMPANY XYZ")
        self.received_from.setText("")  # staff clears it back out by hand

        self.form.fields["Surname"].setText("KHOURY")

        self.assertEqual(self.received_from.text(), "KARIM KHOURY")

    def test_empty_names_produce_empty_received_from_not_a_stray_space(self):
        self.form.fields["Surname"].setText("KORDAHI")
        self.form.fields["Surname"].setText("")
        self.assertEqual(self.received_from.text(), "")


class ResetToNewRecordTest(unittest.TestCase):
    def setUp(self):
        self.form = _make_form()

    def test_restores_place_of_issue_default(self):
        self.form.fields["Original Document.Place of Issue"].setText("SOMEWHERE ELSE")
        self.form.reset_to_new_record()
        self.assertEqual(self.form.fields["Original Document.Place of Issue"].text(), "CGCV")

    def test_clears_received_from_and_its_sync_tracker(self):
        self.form.fields["Surname"].setText("KORDAHI")
        self.form.fields["First Name"].setText("KARIM")
        self.assertEqual(self.form.fields["Receipt.Received from"].text(), "KARIM KORDAHI")

        self.form.reset_to_new_record()

        self.assertEqual(self.form.fields["Receipt.Received from"].text(), "")
        self.assertEqual(self.form._receipt_received_from_auto, "")

    def test_sync_still_works_correctly_for_the_next_record_after_reset(self):
        self.form.fields["Surname"].setText("KORDAHI")
        self.form.fields["First Name"].setText("KARIM")
        self.form.reset_to_new_record()

        self.form.fields["Surname"].setText("KHOURY")
        self.form.fields["First Name"].setText("RITA")

        self.assertEqual(self.form.fields["Receipt.Received from"].text(), "RITA KHOURY")

    def test_a_record_loaded_after_reset_is_not_overwritten_by_a_stale_auto_value(self):
        # Regression guard for the "does reset leave a stray auto-value
        # that could clobber the next loaded record" concern raised while
        # implementing this -- see _sync_received_from_name's docstring.
        self.form.fields["Surname"].setText("KORDAHI")
        self.form.fields["First Name"].setText("KARIM")
        self.form.reset_to_new_record()

        self.form._load_record(1, {
            "Surname": "KHOURY", "First Name": "RITA",
            "Receipt.Received from": "PAID BY COMPANY XYZ",
        })

        self.assertEqual(self.form.fields["Receipt.Received from"].text(), "PAID BY COMPANY XYZ")


if __name__ == "__main__":
    unittest.main()
