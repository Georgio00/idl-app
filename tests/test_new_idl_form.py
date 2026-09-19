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
  4. Autofill never overwrites "Original Document.Place of Issue" with
     whatever OCR actually read off the physical license (field 4c) --
     found in real use: a real license prints the code plus its Arabic
     name together (e.g. "CGCV السير إدارة"), and applying that raw text was
     defeating the CGCV default on every single Autofill run. See
     NEVER_AUTOFILLED_FIELDS in new_idl_form.py.

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
    from gui.new_idl_form import DEFAULT_PLACE_OF_ISSUE, NEVER_AUTOFILLED_FIELDS, NORMAL_STYLE, NewIDLForm

from ocr.pipeline import AutofillResult, FormField


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


def _fake_autofill_result(**field_values: str) -> AutofillResult:
    """Builds a minimal AutofillResult the way ocr/pipeline.py would,
    covering only the keys a test actually cares about (all non-flagged,
    real-value fields) -- good enough to drive _on_autofill_succeeded
    without needing a real OCR run."""
    return AutofillResult(
        fields={key: FormField(value, False, "license") for key, value in field_values.items()},
        errors=[],
    )


class AutofillNeverOverwritesPlaceOfIssueTest(unittest.TestCase):
    """Regression coverage for a real bug hit in production use: a real
    Lebanese license prints its issuing-authority field (4c) as the code
    plus its Arabic name together, e.g. "CGCV السير إدارة" -- and applying
    that raw OCR text was overwriting the CGCV default on every single
    Autofill run. See NEVER_AUTOFILLED_FIELDS in new_idl_form.py."""

    def setUp(self):
        self.form = _make_form()
        # _on_autofill_succeeded ends with a real QMessageBox.information(...)
        # -- a MODAL call that blocks on a click that will never come in a
        # headless test run. Patched out for every test in this class so
        # calling _on_autofill_succeeded doesn't hang the test suite.
        patcher = mock.patch("gui.new_idl_form.QMessageBox")
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_place_of_issue_key_is_in_the_never_autofilled_set(self):
        self.assertIn("Original Document.Place of Issue", NEVER_AUTOFILLED_FIELDS)

    def test_autofill_result_with_real_printed_bilingual_text_does_not_overwrite_cgcv(self):
        result = _fake_autofill_result(**{
            "Surname": "SFEIR",
            "Original Document.Place of Issue": "CGCV السير إدارة",
        })

        self.form._on_autofill_succeeded(result)

        self.assertEqual(self.form.fields["Original Document.Place of Issue"].text(), "CGCV")
        # Confirms the skip is specific to Place of Issue, not a blanket
        # "autofill did nothing" failure -- Surname should still apply.
        self.assertEqual(self.form.fields["Surname"].text(), "SFEIR")

    def test_a_manual_override_of_place_of_issue_also_survives_autofill(self):
        self.form.fields["Original Document.Place of Issue"].setText("BEIRUT")
        result = _fake_autofill_result(**{
            "Original Document.Place of Issue": "CGCV السير إدارة",
        })

        self.form._on_autofill_succeeded(result)

        self.assertEqual(self.form.fields["Original Document.Place of Issue"].text(), "BEIRUT")

    def test_filled_count_passed_to_the_audit_log_excludes_place_of_issue(self):
        result = _fake_autofill_result(**{
            "Surname": "SFEIR",
            "First Name": "CHARBEL",
            "Original Document.Place of Issue": "CGCV السير إدارة",
        })

        with mock.patch("gui.new_idl_form.log_autofill_run") as log_mock:
            self.form._on_autofill_succeeded(result)

        # Surname + First Name = 2 -- Place of Issue must not add a 3rd,
        # since it was never actually applied to the screen.
        self.assertEqual(log_mock.call_args.args[3], 2)


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


class CloneRecordTest(unittest.TestCase):
    """Regression coverage for _clone_record (added 2026-09-19, see its own
    docstring) -- a returning client's prior record is reused to start a
    brand new IDL, per a real recording of LAA's own equivalent Georgio
    shared. The one thing every test here ultimately guards against is the
    same real risk: a returning client's Clone silently overwriting their
    PREVIOUS visit's saved record instead of creating a new one."""

    SOURCE_FIELDS = {
        "Surname": "KORDAHI", "First Name": "KARIM", "Father's Name": "KAMAL",
        "Place of B.": "JBEIL", "Date of B.": "16/09/1981",
        "Original Document.Number": "1512683", "Original Document.Date": "18/11/1999",
        "Original Document.Place of Issue": "CGCV", "Original Document.Category": "B",
        "Original Document.Expiry Date": "18/11/2031",
        "Issued Document.Number": "344629", "Issued Document.Date": "10/09/2026",
        "Receipt.Received from": "KARIM KORDAHI", "Receipt.Amount(LBP)": "5000000",
        "Receipt.Date": "10/09/2026",
    }

    def setUp(self):
        self.form = _make_form()
        self.form._clone_record(7, dict(self.SOURCE_FIELDS))

    def test_personal_fields_carry_over(self):
        for key in ("Surname", "First Name", "Father's Name", "Place of B.", "Date of B."):
            self.assertEqual(self.form.fields[key].text(), self.SOURCE_FIELDS[key])

    def test_original_document_fields_carry_over_unchanged(self):
        # The whole point: the physical original license didn't change,
        # so none of its details should reset just because this is a new
        # transaction for the same client.
        for key in ("Number", "Date", "Place of Issue", "Category", "Expiry Date"):
            full_key = f"Original Document.{key}"
            self.assertEqual(self.form.fields[full_key].text(), self.SOURCE_FIELDS[full_key])

    def test_receipt_received_from_and_amount_carry_over(self):
        self.assertEqual(self.form.fields["Receipt.Received from"].text(), "KARIM KORDAHI")
        self.assertEqual(self.form.fields["Receipt.Amount(LBP)"].text(), "5000000")

    def test_issued_document_number_resets_to_blank(self):
        # Matches a genuinely new record: save_record() auto-generates a
        # fresh serial for a blank Issued Document Number at Save time.
        self.assertEqual(self.form.fields["Issued Document.Number"].text(), "")

    def test_issued_document_date_resets_to_today(self):
        expected = date.today().strftime("%d/%m/%Y")
        self.assertEqual(self.form.fields["Issued Document.Date"].text(), expected)

    def test_receipt_date_resets_to_blank(self):
        self.assertEqual(self.form.fields["Receipt.Date"].text(), "")

    def test_current_record_id_stays_none_so_save_inserts_not_updates(self):
        # The core safety property: Save after a Clone must INSERT a new
        # row, never UPDATE the source record (source_record_id=7).
        self.assertIsNone(self.form.current_record_id)

    def test_save_baseline_resets_to_none_like_a_genuinely_new_record(self):
        self.assertIsNone(self.form._save_baseline)

    def test_title_label_mentions_the_source_record_id(self):
        self.assertIn("7", self.form.title_label.text())
        self.assertIn("Creating New IDL", self.form.title_label.text())

    def test_photo_upload_boxes_are_cleared(self):
        form = _make_form()
        form.passport_box.image_path = "/fake/passport.jpg"
        form.license_front_box.image_path = "/fake/front.jpg"
        form.license_back_box.image_path = "/fake/back.jpg"

        form._clone_record(7, dict(self.SOURCE_FIELDS))

        for box in (form.passport_box, form.license_front_box, form.license_back_box):
            self.assertIsNone(box.image_path)

    def test_logs_the_source_record_id(self):
        form = _make_form()
        with mock.patch("gui.new_idl_form.log_record_cloned") as log_mock:
            form._clone_record(7, dict(self.SOURCE_FIELDS))
        log_mock.assert_called_once_with(7)

    def test_a_manually_overridden_received_from_is_not_clobbered_by_a_later_name_edit(self):
        # Same "not overwritten by a stale auto value" rule
        # ResetToNewRecordTest already pins down for _load_record: when
        # the source record's "Receipt.Received from" is a genuine manual
        # override (someone other than the applicant picked up/paid for a
        # past document -- not just "{First Name} {Surname}"), a later
        # Surname/First Name edit on the clone must not silently blow that
        # override away. (When the source value instead already equals
        # what the live sync would compute anyway -- the common case, see
        # test_receipt_received_from_and_amount_carry_over -- continuing
        # to live-sync it is correct, not a bug: there's nothing to
        # distinguish it from a fresh sync-produced value.)
        form = _make_form()
        fields = dict(self.SOURCE_FIELDS)
        fields["Receipt.Received from"] = "PAID BY COMPANY XYZ"
        form._clone_record(7, fields)

        form.fields["Surname"].setText("DIFFERENT")

        self.assertEqual(form.fields["Receipt.Received from"].text(), "PAID BY COMPANY XYZ")

    def test_clears_field_flag_styling_from_the_source_record(self):
        # A field left flagged (orange) on the source record must not
        # visually carry that flag over into the new record.
        self.form.set_field("Surname", "KORDAHI", flagged=True)
        self.form._clone_record(7, dict(self.SOURCE_FIELDS))
        self.assertEqual(self.form.fields["Surname"].styleSheet(), NORMAL_STYLE)


if __name__ == "__main__":
    unittest.main()
