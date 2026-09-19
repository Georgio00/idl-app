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

Also covers the 2026-09-19 "Clone as New Record" feature (CloneRecordTest)
and _persist_record/PersistRecordTest -- added the same day after Georgio
found a real client's record was never saved at all, because staff had
gone straight from Autofill to Print without clicking Save. Two changes:
Issued Document Number stopped being auto-generated (an employee must
type it in by hand, and Save/Print now refuse to proceed while it's still
blank, the same way a blank Surname already did), and Print now
auto-saves the record itself (via the same _persist_record logic Save
uses) before it sends anything to the printer, so the "forgot to click
Save" failure mode can't happen via the Print path anymore either.

Also covers two more 2026-09-19 additions, both from a second video
Georgio shared of LAA's own toolbar: "◀ Previous"/"Next ▶" record
navigation (NavigateRecordsTest, see _go_to_relative_record) and, from
the follow-up request "also add branch and name", the new
Receipt.Branch/Receipt.User fields (see the extra CloneRecordTest cases
below for how they carry over on Clone differently from each other).

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
A MagicMock's methods (self.form.storage.save_record, .update_record) are
enough to exercise _persist_record's own logic/validation without real
file I/O; PersistRecordTest configures return_value where a test needs a
specific record id back. RecordsScreen/PrinterSettingsDialog are never
opened by these tests, so they need no similar treatment.
"""

import os
import sys
import tempfile
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

from db.storage import IdlRecord
from ocr.pipeline import AutofillResult, FormField


def _record(record_id: int, **fields: str) -> IdlRecord:
    return IdlRecord(id=record_id, created_at="2026-09-19T10:00:00", fields=fields)


def _make_form(username: str | None = None) -> NewIDLForm:
    with mock.patch("gui.new_idl_form.Storage"):
        return NewIDLForm(username=username)


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
        for label in ("Received from", "Date", "Amount(LBP)", "Branch", "User"):
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
        "Receipt.Date": "10/09/2026", "Receipt.Branch": "SIN EL FIL", "Receipt.User": "ROULA",
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
        # Matches a genuinely new record: an employee must type THIS
        # transaction's own number in by hand -- see PersistRecordTest,
        # this is no longer auto-generated and Save/Print will refuse to
        # proceed while it's still blank.
        self.assertEqual(self.form.fields["Issued Document.Number"].text(), "")

    def test_issued_document_date_resets_to_today(self):
        expected = date.today().strftime("%d/%m/%Y")
        self.assertEqual(self.form.fields["Issued Document.Date"].text(), expected)

    def test_receipt_date_resets_to_blank(self):
        self.assertEqual(self.form.fields["Receipt.Date"].text(), "")

    def test_receipt_branch_carries_over(self):
        # Same office, transaction to transaction -- same reasoning as
        # Original Document.Place of Issue's DEFAULT_PLACE_OF_ISSUE.
        self.assertEqual(self.form.fields["Receipt.Branch"].text(), "SIN EL FIL")

    def test_receipt_user_does_not_carry_over_from_the_source_record(self):
        # SOURCE_FIELDS' "Receipt.User" is "ROULA" -- unlike Branch, this
        # must NOT carry over untouched, since whoever handled the
        # client's earlier visit isn't necessarily who's handling this
        # new one. self.form has no logged-in username (see _make_form),
        # so it resets to "" here -- see the next test for what happens
        # with one set.
        self.assertEqual(self.form.fields["Receipt.User"].text(), "")

    def test_receipt_user_resets_to_the_currently_logged_in_username(self):
        # 2026-09-19 (the login-system follow-up, see this module's
        # docstring): a clone is a NEW transaction, so Receipt.User
        # reflects whoever is logged in and clicking Clone right now --
        # NOT the source record's "ROULA" (a different staff member could
        # be on shift) and NOT blank (someone IS logged in this time).
        form = _make_form(username="OJEIL")
        form._clone_record(7, dict(self.SOURCE_FIELDS))
        self.assertEqual(form.fields["Receipt.User"].text(), "OJEIL")

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


class NavigateRecordsTest(unittest.TestCase):
    """Regression coverage for "◀ Previous"/"Next ▶" (added 2026-09-19,
    see _go_to_relative_record's own docstring) -- steps straight from one
    saved record to the next/previous, matching a real recording of LAA's
    own equivalent toolbar arrows Georgio shared. self.form.storage is a
    MagicMock (see this module's docstring), so list_records() must be
    given an explicit return_value per test -- records are ordered lowest
    id first (oldest/first-saved), same as _go_to_relative_record sorts
    them, so id=1 is "first" and id=3 is "last" throughout."""

    def setUp(self):
        self.form = _make_form()
        # list_records() itself returns newest-first (id DESC) in the real
        # Storage -- deliberately returned in THAT order here too, so a
        # test that only reorders and never re-sorts wouldn't silently
        # pass for the wrong reason.
        self.records = [
            _record(3, Surname="THIRD"), _record(2, Surname="SECOND"), _record(1, Surname="FIRST"),
        ]
        self.form.storage.list_records.return_value = self.records

    def test_no_saved_records_shows_a_message_and_loads_nothing(self):
        self.form.storage.list_records.return_value = []
        with mock.patch("gui.new_idl_form.QMessageBox") as mock_box:
            self.form.go_to_next_record()
        mock_box.information.assert_called_once()
        self.assertIsNone(self.form.current_record_id)

    def test_next_with_nothing_loaded_starts_at_the_first_record(self):
        self.form.go_to_next_record()
        self.assertEqual(self.form.current_record_id, 1)
        self.assertEqual(self.form.fields["Surname"].text(), "FIRST")

    def test_previous_with_nothing_loaded_starts_at_the_last_record(self):
        self.form.go_to_previous_record()
        self.assertEqual(self.form.current_record_id, 3)
        self.assertEqual(self.form.fields["Surname"].text(), "THIRD")

    def test_next_moves_to_the_next_higher_id(self):
        self.form._load_record(1, {"Surname": "FIRST"})
        self.form.go_to_next_record()
        self.assertEqual(self.form.current_record_id, 2)
        self.assertEqual(self.form.fields["Surname"].text(), "SECOND")

    def test_previous_moves_to_the_next_lower_id(self):
        self.form._load_record(3, {"Surname": "THIRD"})
        self.form.go_to_previous_record()
        self.assertEqual(self.form.current_record_id, 2)
        self.assertEqual(self.form.fields["Surname"].text(), "SECOND")

    def test_next_at_the_last_record_shows_a_message_and_does_not_move(self):
        self.form._load_record(3, {"Surname": "THIRD"})
        with mock.patch("gui.new_idl_form.QMessageBox") as mock_box:
            self.form.go_to_next_record()
        mock_box.information.assert_called_once()
        self.assertEqual(self.form.current_record_id, 3)
        self.assertEqual(self.form.fields["Surname"].text(), "THIRD")

    def test_previous_at_the_first_record_shows_a_message_and_does_not_move(self):
        self.form._load_record(1, {"Surname": "FIRST"})
        with mock.patch("gui.new_idl_form.QMessageBox") as mock_box:
            self.form.go_to_previous_record()
        mock_box.information.assert_called_once()
        self.assertEqual(self.form.current_record_id, 1)
        self.assertEqual(self.form.fields["Surname"].text(), "FIRST")

    def test_current_record_deleted_elsewhere_falls_back_to_the_first_record(self):
        # current_record_id=99 no longer exists in list_records() (e.g.
        # deleted from the Records screen in the meantime) -- rather than
        # crash on a ValueError from list.index(), falls back the same
        # way "nothing loaded" already does.
        self.form.current_record_id = 99
        self.form.go_to_next_record()
        self.assertEqual(self.form.current_record_id, 1)

    def test_navigating_switches_into_editing_mode_like_open_for_edit(self):
        # Reuses _load_record -- Save from here on must UPDATE the loaded
        # record, not insert a new one, same as opening it from the
        # Records screen would.
        self.form.go_to_next_record()
        self.assertIn("Editing IDL Record #1", self.form.title_label.text())

    def test_re_reads_storage_fresh_on_every_call_rather_than_caching(self):
        self.form.go_to_next_record()
        self.form.go_to_next_record()
        self.assertEqual(self.form.storage.list_records.call_count, 2)


class LoggedInUserFieldTest(unittest.TestCase):
    """Regression coverage for the 2026-09-19 staff login system's effect
    on Receipt.User (see this module's docstring's login-system paragraph
    and gui/login_dialog.py) -- the whole point of requiring login was so
    this field reflects who's actually logged in rather than being typed
    by hand, so these tests are really about two things: the field can't
    be edited, and it tracks self.current_username correctly through
    every place a NEW record gets started."""

    def test_field_is_read_only(self):
        form = _make_form(username="ROULA")
        self.assertTrue(form.fields["Receipt.User"].isReadOnly())

    def test_auto_fills_from_the_username_at_construction(self):
        form = _make_form(username="ROULA")
        self.assertEqual(form.fields["Receipt.User"].text(), "ROULA")

    def test_stays_blank_when_constructed_with_no_username(self):
        # Matches every pre-login-system test in this file, which
        # constructs NewIDLForm() with no username at all.
        form = _make_form()
        self.assertEqual(form.fields["Receipt.User"].text(), "")

    def test_reset_to_new_record_sets_it_to_the_current_username(self):
        form = _make_form(username="ROULA")
        form.fields["Receipt.User"].setText("")  # can't happen via the UI (read-only) -- simulates a stale value
        form.reset_to_new_record()
        self.assertEqual(form.fields["Receipt.User"].text(), "ROULA")

    def test_load_record_preserves_the_records_own_stored_user_unchanged(self):
        # The one exception: opening an OLD record for editing must keep
        # showing who originally created it, not overwrite it with
        # whoever happens to be logged in today.
        form = _make_form(username="OJEIL")
        form._load_record(1, {"Surname": "KORDAHI", "Receipt.User": "ROULA"})
        self.assertEqual(form.fields["Receipt.User"].text(), "ROULA")

    def test_read_only_styling_survives_load_record(self):
        # _load_record resets every field's style via _style_for_field --
        # confirms Receipt.User's grey read-only look isn't wiped back to
        # a normal, editable-looking white by that reset.
        from gui.new_idl_form import READ_ONLY_FIELD_STYLE

        form = _make_form(username="OJEIL")
        form._load_record(1, {"Surname": "KORDAHI", "Receipt.User": "ROULA"})
        self.assertEqual(form.fields["Receipt.User"].styleSheet(), READ_ONLY_FIELD_STYLE)


class PersistRecordTest(unittest.TestCase):
    """Regression coverage for _persist_record (added 2026-09-19, see its
    own docstring) -- the shared save logic behind both the "Save" button
    and Print's new auto-save. Two real-world facts drove this: a client's
    record was found to have never been saved at all (staff went straight
    from Autofill to Print, never clicking Save), and separately, Georgio
    wants Issued Document Number entered by an employee by hand, never
    invented by the app -- so it changed from "auto-generate if blank" to
    a hard validation stop, the same way a blank Surname already was."""

    def setUp(self):
        self.form = _make_form()
        self.form.fields["Surname"].setText("KORDAHI")
        self.form.fields["Issued Document.Number"].setText("344629")

    def test_saves_successfully_when_surname_and_issued_number_are_present(self):
        self.form.storage.save_record.return_value = 42
        with mock.patch("gui.new_idl_form.QMessageBox"):
            record_id = self.form._persist_record()
        self.assertEqual(record_id, 42)
        self.form.storage.save_record.assert_called_once()

    def test_blocks_when_surname_is_missing(self):
        self.form.fields["Surname"].setText("")
        with mock.patch("gui.new_idl_form.QMessageBox") as mock_box:
            record_id = self.form._persist_record()
        self.assertIsNone(record_id)
        self.form.storage.save_record.assert_not_called()
        mock_box.warning.assert_called_once()
        self.assertIn("Surname", mock_box.warning.call_args.args[2])

    def test_blocks_when_issued_document_number_is_missing(self):
        # The core 2026-09-19 change: this field no longer fills itself
        # in -- a blank value is now a hard stop, not a trigger to
        # auto-generate one.
        self.form.fields["Issued Document.Number"].setText("")
        with mock.patch("gui.new_idl_form.QMessageBox") as mock_box:
            record_id = self.form._persist_record()
        self.assertIsNone(record_id)
        self.form.storage.save_record.assert_not_called()
        mock_box.warning.assert_called_once()
        self.assertIn("Issued Document Number", mock_box.warning.call_args.args[2])

    def test_does_not_mutate_the_issued_document_number_field_at_all(self):
        # Old behavior used to setText() a generated serial into this
        # field as a side effect of saving -- confirms that's really gone,
        # not just that saving no longer NEEDS to do it.
        self.form._persist_record()
        self.assertEqual(self.form.fields["Issued Document.Number"].text(), "344629")

    def test_save_record_button_handler_shows_a_saved_dialog(self):
        self.form.storage.save_record.return_value = 7
        with mock.patch("gui.new_idl_form.QMessageBox") as mock_box:
            self.form.save_record()
        mock_box.information.assert_called_once()
        self.assertIn("7", mock_box.information.call_args.args[2])

    def test_save_record_button_handler_shows_nothing_on_validation_failure(self):
        self.form.fields["Issued Document.Number"].setText("")
        with mock.patch("gui.new_idl_form.QMessageBox") as mock_box:
            self.form.save_record()
        mock_box.information.assert_not_called()  # only the warning fired
        mock_box.warning.assert_called_once()

    def test_second_persist_updates_rather_than_inserts(self):
        self.form.storage.save_record.return_value = 9
        self.form._persist_record()  # first save: insert
        self.form._persist_record()  # second save on the same record: update
        self.form.storage.save_record.assert_called_once()
        self.form.storage.update_record.assert_called_once()
        args = self.form.storage.update_record.call_args.args
        self.assertEqual(args[0], 9)  # updates the id the first save returned


class PrintAutoSaveTest(unittest.TestCase):
    """Regression coverage for print_to_printer's 2026-09-19 auto-save
    (see its own docstring): clicking "Print" now persists the record via
    _persist_record BEFORE anything is sent to the printer, so a client's
    IDL can no longer go out physically printed with nothing saved to the
    database at all -- the exact real failure this whole change addresses.
    """

    def setUp(self):
        self.form = _make_form()
        self.form.fields["Surname"].setText("KORDAHI")
        self.form.fields["Issued Document.Number"].setText("344629")
        self.tmp_dir = Path(tempfile.mkdtemp())

    def _confirm_yes_patch(self, mock_box):
        # QMessageBox itself is mocked out, so QMessageBox.Yes inside
        # print_to_printer resolves to the mock's own auto-created
        # attribute -- .question must be told to return that exact
        # object back for "confirm != QMessageBox.Yes" to read as "yes".
        mock_box.question.return_value = mock_box.Yes

    def test_print_persists_the_record_before_dispatching(self):
        self.form.storage.save_record.return_value = 5
        with mock.patch("gui.new_idl_form.QMessageBox") as mock_box, \
             mock.patch("gui.new_idl_form.get_configured_printer_name", return_value="Office Printer"), \
             mock.patch("gui.new_idl_form.APP_DATA_DIR", self.tmp_dir), \
             mock.patch("printing.print_page.render_idl_data_page") as mock_render, \
             mock.patch("printing.print_dispatch.print_pdf_to_printer") as mock_print, \
             mock.patch("db.audit_log.log_print_dispatched"), \
             mock.patch("db.audit_log.log_print_dispatch_failed"):
            self._confirm_yes_patch(mock_box)
            self.form.print_to_printer()

        self.form.storage.save_record.assert_called_once()
        mock_render.assert_called_once()
        mock_print.assert_called_once()

    def test_print_does_not_dispatch_when_issued_document_number_is_missing(self):
        # The real scenario this whole feature addresses: Print must not
        # be able to silently skip past a record with nothing to save.
        self.form.fields["Issued Document.Number"].setText("")
        with mock.patch("gui.new_idl_form.QMessageBox") as mock_box, \
             mock.patch("gui.new_idl_form.get_configured_printer_name", return_value="Office Printer"), \
             mock.patch("gui.new_idl_form.APP_DATA_DIR", self.tmp_dir), \
             mock.patch("printing.print_page.render_idl_data_page") as mock_render, \
             mock.patch("printing.print_dispatch.print_pdf_to_printer") as mock_print:
            self._confirm_yes_patch(mock_box)
            self.form.print_to_printer()

        self.form.storage.save_record.assert_not_called()
        mock_render.assert_not_called()
        mock_print.assert_not_called()

    def test_print_still_requires_a_configured_printer_before_anything_else(self):
        # No printer configured must stop things before even the confirm
        # dialog -- and, notably, before persisting -- same as before this
        # change (nothing about auto-save should short-circuit this check).
        with mock.patch("gui.new_idl_form.QMessageBox") as mock_box, \
             mock.patch("gui.new_idl_form.get_configured_printer_name", return_value=""):
            self.form.print_to_printer()

        self.form.storage.save_record.assert_not_called()
        mock_box.question.assert_not_called()

    def test_declining_the_confirm_dialog_does_not_persist(self):
        with mock.patch("gui.new_idl_form.QMessageBox") as mock_box, \
             mock.patch("gui.new_idl_form.get_configured_printer_name", return_value="Office Printer"):
            mock_box.question.return_value = mock_box.No
            self.form.print_to_printer()

        self.form.storage.save_record.assert_not_called()


class MainLoginWiringTest(unittest.TestCase):
    """Regression coverage for main()'s 2026-09-19 login wiring (see this
    module's docstring's login-system paragraph) -- confirms the actual
    ordering promise: the main window must never be constructed (let
    alone shown) without a logged-in username, and a successful login's
    storage/username must be exactly what NewIDLForm receives, not a
    second, separate Storage(). QApplication itself is mocked out here
    too -- a real one can't be constructed a second time in the same
    process (this test module's own module-level `_app` already is one),
    so main() must never be called for real, only against replaced
    collaborators."""

    def test_cancelled_login_exits_without_ever_constructing_the_main_window(self):
        # sys.exit is given a real SystemExit side effect -- a plain mock
        # wouldn't actually stop main()'s execution the way the real
        # sys.exit(0) does, which would let it fall through to
        # constructing NewIDLForm(username=None) and defeat the point of
        # this test.
        with mock.patch("gui.new_idl_form.QApplication"), \
             mock.patch("gui.new_idl_form.Storage") as mock_storage_cls, \
             mock.patch("gui.new_idl_form.run_login", return_value=None) as mock_run_login, \
             mock.patch("gui.new_idl_form.NewIDLForm") as mock_form_cls, \
             mock.patch("gui.new_idl_form.sys.exit", side_effect=SystemExit) as mock_exit, \
             mock.patch("gui.new_idl_form.configure_audit_logging"), \
             mock.patch("gui.new_idl_form.log_app_start"):
            from gui.new_idl_form import main
            with self.assertRaises(SystemExit):
                main()

        mock_run_login.assert_called_once_with(mock_storage_cls.return_value)
        mock_form_cls.assert_not_called()
        mock_exit.assert_called_once_with(0)

    def test_successful_login_constructs_the_main_window_with_that_storage_and_username(self):
        with mock.patch("gui.new_idl_form.QApplication"), \
             mock.patch("gui.new_idl_form.Storage") as mock_storage_cls, \
             mock.patch("gui.new_idl_form.run_login", return_value="ROULA"), \
             mock.patch("gui.new_idl_form.NewIDLForm") as mock_form_cls, \
             mock.patch("gui.new_idl_form.sys.exit"), \
             mock.patch("gui.new_idl_form.configure_audit_logging"), \
             mock.patch("gui.new_idl_form.log_app_start"):
            from gui.new_idl_form import main
            main()

        mock_form_cls.assert_called_once_with(storage=mock_storage_cls.return_value, username="ROULA")
        mock_form_cls.return_value.show.assert_called_once()


if __name__ == "__main__":
    unittest.main()
