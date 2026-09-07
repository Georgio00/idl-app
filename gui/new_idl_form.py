"""
"New IDL" data entry screen — deliberately mirrors LAA's own field layout
(Surname, First Name, Father's Name, ... Original Document, Issued Document,
Receipt) so staff already trained on LAA don't have to relearn anything.

The one addition over LAA: three labeled photo upload boxes (Passport,
License Front, License Back) and an Autofill button that runs the OCR
pipeline (ocr.pipeline) once all three are filled, populating every field
it can, leaving Phone/Email/Issued-Document-Number blank for manual entry,
and flagging (in orange) any field whose OCR confidence or checksum was low
so staff know exactly what to double check before saving.

2026-09-07: added "Find / Reprint Record..." (see gui/records_screen.py)
and "New" — the app previously had no way back to a record once Save was
clicked, so a reprint or a post-save correction meant opening the
encrypted SQLite file by hand. Opening a record from that screen switches
this form into an editing mode (self.current_record_id set, title bar
shows which record) where Save UPDATES that row instead of inserting a
new one; "New" resets back to a blank insert-a-new-record state. Every
autofill run, record save (with a field-by-field before/after diff), and
print is now also recorded to a persistent audit log regardless of the
IDL_APP_DEBUG_OCR flag below — see db/audit_log.py.
"""

import logging
import os
import sys
from datetime import date

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QLabel, QGroupBox, QMessageBox, QProgressDialog,
    QScrollArea, QFrame,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.audit_log import (
    configure_audit_logging, log_app_start, log_autofill_failed, log_autofill_run,
    log_record_opened, log_record_saved,
)
from db.storage import APP_DATA_DIR, Storage
from gui.image_upload_box import ImageUploadBox
from gui.records_screen import RecordsScreen
from ocr.pipeline import run_autofill_pipeline
from ocr.ocr_client import OcrError

# Set IDL_APP_DEBUG_OCR=1 before launching to save every cropped OCR region
# (and log its raw text) to %LOCALAPPDATA%\IDL_APP\debug\<timestamp>\ for
# diagnosing crop-position/calibration issues — see ocr/debug_dump.py.
# Off by default: the crops are cut straight from real ID photos (names,
# DOB, license numbers), so writing them to disk shouldn't happen silently.
DEBUG_OCR = os.environ.get("IDL_APP_DEBUG_OCR", "").strip().lower() in ("1", "true", "yes")

FLAG_STYLE = "background-color: #fff3cd; border: 1px solid #e0a800; color: #000;"
NORMAL_STYLE = ""


class AutofillWorker(QThread):
    """Runs the OCR pipeline off the UI thread — a single autofill makes
    ~35 individual Vision API calls (one per cropped field region across
    the license front/back), which would otherwise freeze the window for
    the whole duration."""
    succeeded = Signal(object)  # AutofillResult
    failed = Signal(str)

    def __init__(self, passport_path, license_front_path, license_back_path):
        super().__init__()
        self.passport_path = passport_path
        self.license_front_path = license_front_path
        self.license_back_path = license_back_path

    def run(self):
        try:
            result = run_autofill_pipeline(
                self.passport_path, self.license_front_path, self.license_back_path,
                debug=DEBUG_OCR,
            )
            self.succeeded.emit(result)
        except OcrError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001 - surface any unexpected failure to the user, not a crash
            self.failed.emit(f"Unexpected error during autofill: {e}")


class NewIDLForm(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("New IDL — Auto-fill")
        self.resize(880, 780)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        # --- Top bar: save/cancel, matching LAA's Save/Cancel row
        # 2026-09-07: added "Find / Reprint Record..." and "New" — the app
        # used to have no way back to a record once Save was clicked (see
        # gui/records_screen.py's docstring). "New" resets the form back to
        # a blank, insert-a-new-record state after a record has been
        # opened for editing — without it there'd be no way to start a
        # fresh IDL without restarting the whole app.
        top_bar = QHBoxLayout()
        self.records_btn = QPushButton("Find / Reprint Record...")
        self.records_btn.clicked.connect(self.open_records_screen)
        self.new_btn = QPushButton("New")
        self.new_btn.clicked.connect(self.reset_to_new_record)
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save_record)
        self.print_btn = QPushButton("Print Preview")
        self.print_btn.clicked.connect(self.print_preview)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.close)
        top_bar.addWidget(self.records_btn)
        top_bar.addStretch()
        top_bar.addWidget(self.new_btn)
        top_bar.addWidget(self.save_btn)
        top_bar.addWidget(self.print_btn)
        top_bar.addWidget(self.cancel_btn)
        outer.addLayout(top_bar)

        self.title_label = QLabel("Creating New IDL")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #1a5fb4;")
        outer.addWidget(self.title_label)

        columns = QHBoxLayout()
        outer.addLayout(columns)

        # --- Left column: the form fields, now wrapped in a scroll area
        # (2026-08-27) so the whole field stack (Personal details + Original
        # Document + Issued Document + Receipt) is reachable by scrolling
        # instead of getting clipped/pushed off the bottom on a smaller
        # screen or a shrunk window -- previously this was a bare QVBoxLayout
        # added straight into `columns`, which meant the window's minimum
        # height was however tall all four group boxes stacked actually are,
        # with no way to see anything below that on a short display.
        #
        # 2026-09-01: the right column (ID Photos) turned out to have the
        # same problem, just easier to miss since it "should" be short and
        # fixed-size -- three photo thumbnails plus title/Replace/Remove
        # rows do add up to more height than some real windows have to
        # give, and without its own scroll area a plain QVBoxLayout
        # doesn't clip cleanly in that case, it *squeezes* every child
        # toward its minimum size, which visually read as each box's
        # Remove button getting pushed up to overlap the photo above it.
        # Now wrapped in its own QScrollArea (upload_scroll below), same
        # fix as the left column: the three boxes always render at their
        # full natural size and the panel scrolls instead of compressing
        # them. The Autofill button stays outside the scroll area (added
        # to right_column directly, after upload_box_group) so it's always
        # visible without scrolling, same as Save/Print/Cancel up top.
        left_widget = QWidget()
        left_column = QVBoxLayout(left_widget)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_widget)
        # 2026-09-01: briefly tried forcing the vertical scrollbar always
        # visible (Qt.ScrollBarAlwaysOn) so it'd be an unmistakable
        # affordance rather than something to discover by trial and error
        # -- reverted on request (Georgio wanted the look kept exactly as
        # it was). Scrolling itself was already available either way: this
        # QScrollArea (added 2026-08-27, see comment above) scrolls via
        # mouse wheel and its default "as needed" scrollbar regardless of
        # this policy setting -- that part needed no change, just this
        # cosmetic one reverted.
        columns.addWidget(left_scroll, stretch=2)

        # --- Personal details (matches LAA's top field group)
        personal_box = QGroupBox()
        personal_form = QFormLayout()
        self.fields = {}
        for label in [
            "Surname", "First Name", "Father's Name", "Mother's Name",
            "Place of B.", "Date of B.", "Address", "Phone", "Email", "Blood Type",
        ]:
            edit = QLineEdit()
            self.fields[label] = edit
            personal_form.addRow(label + ":", edit)
        personal_box.setLayout(personal_form)
        left_column.addWidget(personal_box)

        # --- Original Document group
        orig_box = QGroupBox("Original Document")
        orig_form = QFormLayout()
        for label in ["Number", "Date", "Place of Issue", "Category", "Expiry Date"]:
            edit = QLineEdit()
            self.fields[f"Original Document.{label}"] = edit
            orig_form.addRow(label + ":", edit)
        orig_box.setLayout(orig_form)
        left_column.addWidget(orig_box)

        # --- Issued Document group
        issued_box = QGroupBox("Issued Document")
        issued_form = QFormLayout()
        for label in ["Number", "Date", "Signature"]:
            edit = QLineEdit()
            self.fields[f"Issued Document.{label}"] = edit
            issued_form.addRow(label + ":", edit)
        issued_box.setLayout(issued_form)
        left_column.addWidget(issued_box)

        # --- Receipt group
        receipt_box = QGroupBox("Receipt")
        receipt_form = QFormLayout()
        for label in ["Received from", "Date", "Amount(LBP)"]:
            edit = QLineEdit()
            self.fields[f"Receipt.{label}"] = edit
            receipt_form.addRow(label + ":", edit)
        receipt_box.setLayout(receipt_form)
        left_column.addWidget(receipt_box)

        left_column.addStretch()

        # --- Right column: the three labeled upload boxes + Autofill button
        right_column = QVBoxLayout()
        columns.addLayout(right_column, stretch=1)

        upload_box_group = QGroupBox("ID Photos")
        upload_box_group_layout = QVBoxLayout(upload_box_group)
        upload_box_group_layout.setContentsMargins(0, 0, 0, 0)

        # The three ImageUploadBox widgets live inside their own scroll
        # area (not directly in upload_box_group_layout) as a fallback
        # safety net on an unusually short window -- but the actual goal
        # (2026-09-01, on request) is for all three to be visible with NO
        # scrolling needed in the first place: UPLOAD_BOX_SQUARE_SIZE below
        # is small enough that three stacked boxes plus title/Replace/
        # Remove rows fit inside the panel's typical visible height, so
        # this scroll area normally sits there doing nothing (no
        # scrollbar shown) and only actually engages on a genuinely
        # cramped window, rather than being the everyday way to reach the
        # third photo.
        upload_scroll = QScrollArea()
        upload_scroll.setWidgetResizable(True)
        upload_scroll.setFrameShape(QFrame.NoFrame)  # avoid a double border inside the QGroupBox
        upload_box_group_layout.addWidget(upload_scroll)

        upload_box_widget = QWidget()
        upload_box_layout = QVBoxLayout(upload_box_widget)
        upload_box_layout.setSpacing(10)
        upload_scroll.setWidget(upload_box_widget)

        # 130: bumped up from 100 on request ("make them a bit bigger") --
        # still comfortably fits all three at this window's default size
        # (880x780, no scrolling: verified content height 626px against a
        # ~658px viewport) while staying well short of 150 (the
        # ImageUploadBox default), which needed scrolling even at 780.
        UPLOAD_BOX_SQUARE_SIZE = 130
        self.passport_box = ImageUploadBox(
            "Passport", "Select the passport photo page", square_size=UPLOAD_BOX_SQUARE_SIZE)
        self.license_front_box = ImageUploadBox(
            "Driving License — Front", "Select the driving license — FRONT", square_size=UPLOAD_BOX_SQUARE_SIZE)
        self.license_back_box = ImageUploadBox(
            "Driving License — Back", "Select the driving license — BACK", square_size=UPLOAD_BOX_SQUARE_SIZE)
        for box in (self.passport_box, self.license_front_box, self.license_back_box):
            box.changed.connect(self._update_autofill_enabled)
            upload_box_layout.addWidget(box)
        upload_box_layout.addStretch()

        # stretch=1 here (found while shrinking the boxes to fit without
        # scrolling, 2026-09-01): without it, upload_box_group only ever
        # got its plain sizeHint height from this QVBoxLayout, and the
        # addStretch() below claimed the rest of the window's real spare
        # height as blank space beneath the Autofill button instead -- so
        # the ID Photos panel's own QScrollArea (see above) was working
        # off a cramped viewport and needing to scroll even when the
        # window plainly had the room. Giving the group the stretch
        # instead means it actually expands to fill the column, and only
        # its own content size decides whether scrolling is ever needed.
        right_column.addWidget(upload_box_group, stretch=1)

        self.autofill_btn = QPushButton("Autofill")
        self.autofill_btn.setEnabled(False)
        self.autofill_btn.clicked.connect(self.run_autofill)
        right_column.addWidget(self.autofill_btn)

        # Default the "Issued Document.Date" to today, same as LAA appears to do.
        # (zero-padded %d/%m/%Y, not %-d/%-m — the "-" no-pad flag is Unix-only
        # and raises ValueError on Windows, which is this app's target platform)
        self.fields["Issued Document.Date"].setText(date.today().strftime("%d/%m/%Y"))

        self._worker = None
        self._progress = None
        self.storage = Storage()

        # 2026-09-07: track which saved record (if any) the form currently
        # represents, and a snapshot of the last "known good" values to
        # diff against at save time — see save_record's docstring and
        # db/audit_log.log_record_saved. None/None means "this is a brand
        # new, never-saved record": self.current_record_id is set the
        # first time it's saved (further Saves in the same session then
        # update that row instead of inserting a new one each time) or
        # immediately when a record is opened from the Records screen.
        self.current_record_id: int | None = None
        self._save_baseline: dict[str, str] | None = None

    def _update_autofill_enabled(self):
        all_filled = all(
            box.image_path
            for box in (self.passport_box, self.license_front_box, self.license_back_box)
        )
        self.autofill_btn.setEnabled(all_filled)

    def set_field(self, key: str, value: str, flagged: bool = False):
        if key not in self.fields:
            return
        edit = self.fields[key]
        edit.setText(value or "")
        edit.setStyleSheet(FLAG_STYLE if flagged else NORMAL_STYLE)

    def save_record(self):
        """Inserts a new record the first time this form saves, then
        UPDATES that same row on every subsequent Save in this session
        (see self.current_record_id) — including when the record being
        edited was opened from the Records screen. Before this 2026-09-07
        change, every Save was an INSERT, so re-saving an already-saved
        record (the exact "staff notices a typo and fixes it" case the
        Records screen exists for) would have silently created a
        duplicate row instead of correcting the original.

        Also logs a full audit trail entry: which fields actually changed
        since the last known-good snapshot (self._save_baseline — either
        the values Autofill just produced, or the values this record had
        when it was opened for editing), not just "a save happened". See
        db/audit_log.log_record_saved."""
        if not self.fields["Issued Document.Number"].text().strip():
            self.fields["Issued Document.Number"].setText(self.storage.next_issued_document_number())

        values = {key: edit.text() for key, edit in self.fields.items()}
        if not values["Surname"].strip():
            QMessageBox.warning(self, "Missing data", "Surname is required before saving.")
            return

        changed_fields: dict[str, tuple[str, str]] = {}
        if self._save_baseline is not None:
            for key, new_value in values.items():
                old_value = self._save_baseline.get(key, "")
                if old_value != new_value:
                    changed_fields[key] = (old_value, new_value)

        is_update = self.current_record_id is not None
        if is_update:
            self.storage.update_record(self.current_record_id, values)
            record_id = self.current_record_id
        else:
            record_id = self.storage.save_record(values)
            self.current_record_id = record_id

        self._save_baseline = dict(values)
        log_record_saved(record_id, is_update, changed_fields)

        QMessageBox.information(self, "Saved", f"IDL record #{record_id} saved.")

    def open_records_screen(self):
        dialog = RecordsScreen(self.storage, parent=self)
        dialog.record_opened.connect(self._load_record)
        dialog.exec()

    def _load_record(self, record_id: int, fields: dict):
        """Populates the form from a previously saved record (see
        gui/records_screen.py) and switches into "editing this record"
        mode: Save from here on updates row `record_id` instead of
        inserting a new one, and _save_baseline is reset to these values
        so the next Save's audit entry reflects only what actually gets
        corrected during THIS editing session, not the original
        autofill-vs-saved diff from whenever the record was first
        created."""
        for key, edit in self.fields.items():
            edit.setText(fields.get(key, ""))
            edit.setStyleSheet(NORMAL_STYLE)
        self.current_record_id = record_id
        self._save_baseline = dict(fields)
        self.title_label.setText(f"Editing IDL Record #{record_id}")
        log_record_opened(record_id)

    def reset_to_new_record(self):
        """Clears the form back to a blank, insert-a-new-record state.
        Needed once a record can be opened for editing (see _load_record)
        — otherwise there would be no way to start a genuinely new IDL
        afterward short of restarting the app."""
        for key, edit in self.fields.items():
            edit.setText("")
            edit.setStyleSheet(NORMAL_STYLE)
        for box in (self.passport_box, self.license_front_box, self.license_back_box):
            box.clear_image()
        self.fields["Issued Document.Date"].setText(date.today().strftime("%d/%m/%Y"))
        self.current_record_id = None
        self._save_baseline = None
        self.title_label.setText("Creating New IDL")

    def print_preview(self):
        """Renders whatever is currently in the form onto the print-layout
        PDF (see printing/print_page.py) and opens it, so staff can check
        the positions calibrated in gui/calibration_screen.py actually line
        up before printing onto a real physical IDP booklet page. Uses the
        live field text regardless of whether the record has been saved --
        this is a preview/alignment check, not the final print action."""
        from db.audit_log import log_print
        from printing.print_page import render_idl_data_page

        plain_values = {key: edit.text() for key, edit in self.fields.items()}

        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        output_path = str(APP_DATA_DIR / "print_preview.pdf")
        try:
            render_idl_data_page(plain_values, output_path)
        except Exception as e:  # noqa: BLE001 - surface any failure rather than a silent no-op
            QMessageBox.critical(self, "Print preview failed", f"Could not generate the print PDF: {e}")
            return

        log_print(self.current_record_id, output_path)
        os.startfile(output_path)  # Windows-only -- matches this app's target platform

    def run_autofill(self):
        passport_path = self.passport_box.image_path
        license_front_path = self.license_front_box.image_path
        license_back_path = self.license_back_box.image_path
        if not (passport_path and license_front_path and license_back_path):
            # Shouldn't happen — the button is disabled until all three are
            # filled — but guard rather than run the pipeline on a missing image.
            QMessageBox.warning(self, "Missing photos", "Upload all three photos before running Autofill.")
            return

        self.autofill_btn.setEnabled(False)
        self._progress = QProgressDialog("Reading ID photos (OCR)...", None, 0, 0, self)
        self._progress.setWindowTitle("Autofill")
        self._progress.setCancelButton(None)
        self._progress.setMinimumDuration(0)
        self._progress.show()

        self._worker = AutofillWorker(passport_path, license_front_path, license_back_path)
        self._worker.succeeded.connect(self._on_autofill_succeeded)
        self._worker.failed.connect(self._on_autofill_failed)
        self._worker.finished.connect(self._on_autofill_finished)
        self._worker.start()

    def _on_autofill_finished(self):
        self.autofill_btn.setEnabled(True)
        if self._progress:
            self._progress.close()
            self._progress = None

    def _on_autofill_succeeded(self, result):
        fields = result.fields
        flagged_count = 0
        for key, form_field in fields.items():
            if not form_field.value and not form_field.flagged:
                continue  # never-autofilled fields (Phone, Email, Receipt.*, ...) - leave untouched
            self.set_field(key, form_field.value, flagged=form_field.flagged)
            if form_field.flagged:
                flagged_count += 1

        filled_count = sum(1 for f in fields.values() if f.value)

        # 2026-09-07: snapshot what autofill just produced as the baseline
        # save_record diffs against — every currently-populated field, not
        # just the ones this run touched, so a value left over from a
        # prior manual edit/loaded record still gets a correct before/after
        # in the audit log rather than looking like a fresh autofill value.
        self._save_baseline = {key: edit.text() for key, edit in self.fields.items()}
        log_autofill_run(
            self.passport_box.image_path, self.license_front_box.image_path,
            self.license_back_box.image_path, filled_count, flagged_count, result.errors,
        )

        if result.errors:
            # Don't let a real failure ("Tesseract not found", "Arabic
            # language pack missing") hide behind a vague "flagged in
            # orange" summary — every affected field's flagged/empty state
            # is a symptom of one of these, so show the actual cause.
            QMessageBox.warning(
                self, "Autofill completed with errors",
                f"Autofilled {filled_count} field(s), {flagged_count} flagged for review.\n\n"
                "The following problem(s) prevented some fields from being read at all "
                "(rather than just being low-confidence) — fix these and re-run Autofill:\n\n"
                + "\n\n".join(f"• {e}" for e in result.errors)
            )
            return

        QMessageBox.information(
            self, "Autofill complete",
            f"Autofilled {filled_count} field(s).\n\n"
            f"{flagged_count} field(s) are flagged in orange — please double-check "
            "those against the photos before saving."
        )

    def _on_autofill_failed(self, message: str):
        log_autofill_failed(message)
        QMessageBox.critical(self, "Autofill failed", message)


def main():
    configure_audit_logging()
    log_app_start()
    if DEBUG_OCR:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    window = NewIDLForm()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
