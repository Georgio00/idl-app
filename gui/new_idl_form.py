"""
"New IDL" data entry screen — originally mirrored LAA's own field layout
(Surname, First Name, Father's Name, Mother's Name, ... Original Document,
Issued Document, Receipt) so staff already trained on LAA wouldn't have to
relearn anything. As of 2026-09-14 the personal-details group is trimmed
down from LAA's full set to just Surname, First Name, Father's Name,
Place of B., and Date of B. — Mother's Name/Address/Phone/Email/Blood Type
were dropped from this screen entirely (on request, to cut clutter this
company doesn't use day to day). Original Document and Issued Document
still mirror LAA's groups in full.

The one addition over LAA: three labeled photo upload boxes (Passport,
License Front, License Back) and an Autofill button that runs the OCR
pipeline (ocr.pipeline) once all three are filled, populating every field
it can, leaving Phone/Email/Issued-Document-Number blank for manual entry,
and flagging (in orange) any field whose OCR confidence or checksum was low
so staff know exactly what to double check before saving. (ocr/pipeline.py
still computes Mother's Name/Address/Blood Type internally even though this
screen has nowhere to show them anymore — see set_field's docstring for why
that's harmless rather than a bug.)

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

2026-09-14: two more small on-request changes, both about matching what
the company actually does every time rather than making staff retype it:
"Original Document.Place of Issue" now defaults to "CGCV" (every IDL this
company issues goes through the same office) — see DEFAULT_PLACE_OF_ISSUE
below — and "Receipt.Received from" auto-fills live from Surname + First
Name as they're typed, unless staff have typed something else into it by
hand — see _sync_received_from_name's docstring for exactly how that's
kept from clobbering a manual entry.

2026-09-19: Georgio sent a screenshot of LAA itself (the reference app this
form's field set was originally modeled on) and asked for "the same page
layout" plus "make the words bigger and everything bigger". Two changes:

1. Original Document's Number/Date, Issued Document's Number/Date, and
   Receipt's Amount(LBP)/Date are now each PAIRED on one row (label, field,
   label, field) instead of stacked one-per-row — this is what LAA's own
   screen actually does (confirmed directly against the screenshot) and
   what our plain QFormLayout-per-group couldn't express, since a
   QFormLayout row is always exactly one label + one field. These three
   groups switched from QFormLayout to QGridLayout for this reason —
   see _add_paired_row/_add_full_row below. (Georgio confirmed separately
   that Mother's Name/Address/Phone/Email/Blood Type, which the screenshot
   still shows as empty LAA-only rows, should STAY off this screen — that
   2026-09-14 trim wasn't being reversed, only the row-pairing was new.)
2. A form-wide stylesheet (see BASE_STYLESHEET below) raises the font size
   and field/button padding across every field, label, button, and group
   box title on this screen, plus the window's default size grew to match
   — a blanket "everything bigger" change, not field-by-field tuning.
"""

import logging
import os
import sys
from datetime import date
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGridLayout, QLineEdit, QPushButton, QLabel, QGroupBox, QMessageBox,
    QProgressDialog, QScrollArea, QFrame,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.audit_log import (
    configure_audit_logging, log_app_start, log_autofill_failed, log_autofill_run,
    log_record_cloned, log_record_opened, log_record_saved, log_update_applied,
    log_update_available, log_update_declined, log_update_failed,
)
from db.storage import APP_DATA_DIR, Storage
from gui.image_upload_box import ImageUploadBox
from gui.printer_settings_dialog import PrinterSettingsDialog
from gui.records_screen import RecordsScreen
from ocr.pipeline import run_autofill_pipeline
from ocr.ocr_client import OcrError
from printing.printer_config import get_configured_printer_name
from updater.apply_update import UpdateApplyError, apply_update_and_restart
from updater.update_checker import UpdateManifest, check_for_update
from updater.version import CURRENT_VERSION

# Set IDL_APP_DEBUG_OCR=1 before launching to save every cropped OCR region
# (and log its raw text) to %LOCALAPPDATA%\IDL_APP\debug\<timestamp>\ for
# diagnosing crop-position/calibration issues — see ocr/debug_dump.py.
# Off by default: the crops are cut straight from real ID photos (names,
# DOB, license numbers), so writing them to disk shouldn't happen silently.
DEBUG_OCR = os.environ.get("IDL_APP_DEBUG_OCR", "").strip().lower() in ("1", "true", "yes")

FLAG_STYLE = "background-color: #fff3cd; border: 1px solid #e0a800; color: #000;"
NORMAL_STYLE = ""

# 2026-09-19: "make the words bigger and everything bigger" (on request,
# comparing against a screenshot of LAA's own, larger-looking screen).
# Applied once, on the central widget, rather than field-by-field: Qt's
# stylesheet cascade means every QLineEdit/QLabel/QPushButton/QGroupBox
# under `central` (which is every widget on this whole form, including
# ones built inside ImageUploadBox — see that module's title_label, which
# only sets font-weight itself and so inherits font-size from here) picks
# this up automatically, with no per-widget font-size calls to keep in
# sync as fields get added or removed. FLAG_STYLE/NORMAL_STYLE above stay
# separate (set per-field via setStyleSheet in set_field) since Qt only
# lets a widget have one stylesheet string at a time — set_field's
# setStyleSheet call replaces this cascade's effect for that one widget,
# which is why FLAG_STYLE repeats the border/background look rather than
# just toggling a class.
BASE_STYLESHEET = """
    QWidget { font-size: 13pt; }
    QLineEdit {
        font-size: 13pt;
        padding: 6px 8px;
        min-height: 22px;
    }
    QPushButton {
        font-size: 13pt;
        padding: 7px 16px;
        min-height: 22px;
    }
    QGroupBox {
        font-size: 14pt;
        font-weight: bold;
        margin-top: 14px;
        padding-top: 12px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
    }
"""

# 2026-09-14: every IDL this company issues is through the same branch/
# office, so "Original Document.Place of Issue" is always "CGCV" in
# practice — defaulted here (still a plain editable QLineEdit, not
# locked, in case a genuine exception ever comes up) so staff don't have
# to type the same three letters on every single record. Applied both at
# form construction and by reset_to_new_record() (see below) so it comes
# back after "New" the same way Issued Document.Date's today-default does.
DEFAULT_PLACE_OF_ISSUE = "CGCV"

# 2026-09-14: found in real use the day after DEFAULT_PLACE_OF_ISSUE was
# added -- ocr/pipeline.py's "Original Document.Place of Issue" (license
# field 4c, the issuing-authority box) reads whatever is actually PRINTED
# on the physical license, which on a real Lebanese license is the code
# plus its Arabic name together (e.g. "CGCV السير إدارة"), not just the
# bare code -- and _on_autofill_succeeded below was applying that raw OCR
# text straight over the CGCV default on every Autofill run, defeating
# the whole point of the default. Fixed the same way Phone/Email/
# Issued-Document-Number are already deliberately left for manual entry
# (see this module's docstring): "Original Document.Place of Issue" is
# never written by Autofill at all, regardless of what OCR reads there --
# it stays exactly "CGCV" (or whatever staff typed over it by hand) no
# matter how many times Autofill runs on this record. ocr/pipeline.py
# still computes it internally; this is a GUI-side "never apply it" list,
# same pattern as the personal fields trimmed off this screen entirely.
NEVER_AUTOFILLED_FIELDS = {"Original Document.Place of Issue"}


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


class UpdateCheckWorker(QThread):
    """2026-09-11: runs the auto-update check (updater.update_checker) off
    the UI thread, since it makes a real network call and must never
    delay the window actually appearing on screen -- a staff member
    opening the app to process a document shouldn't wait on an update
    check that may be slow (or hanging) before they can start typing.
    Only emits update_found when there actually IS a newer version;
    silence (no signal at all) covers "no update," "check failed," and
    "already up to date" identically, since none of those need to
    interrupt anyone -- see check_for_update's own docstring for why it
    never raises."""
    update_found = Signal(object)  # UpdateManifest

    def run(self):
        manifest = check_for_update(CURRENT_VERSION)
        if manifest is not None:
            self.update_found.emit(manifest)


class NewIDLForm(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("New IDL — Auto-fill")
        # 1050x900: bumped up from 880x780 (2026-09-19) alongside
        # BASE_STYLESHEET's bigger fonts -- the old size was tuned for the
        # old, smaller field/button rendering and started needing more
        # scrolling once everything got bigger.
        self.resize(1050, 900)

        central = QWidget()
        self.setCentralWidget(central)
        central.setStyleSheet(BASE_STYLESHEET)
        outer = QVBoxLayout(central)

        # --- Top bar: save/cancel, matching LAA's Save/Cancel row
        # 2026-09-07: added "Find / Reprint Record..." and "New" — the app
        # used to have no way back to a record once Save was clicked (see
        # gui/records_screen.py's docstring). "New" resets the form back to
        # a blank, insert-a-new-record state after a record has been
        # opened for editing — without it there'd be no way to start a
        # fresh IDL without restarting the whole app.
        # 2026-09-08: added "Printer Settings..." and "Print" — "Print
        # Preview" only ever opened the PDF in a viewer for a visual check
        # (see print_preview below); there was no button that actually
        # sent a page to a physical printer at all. "Print" sends directly,
        # silently, to whichever printer is configured in Printer Settings
        # (see printing/print_dispatch.py and printer_config.py) — kept
        # deliberately separate from Print Preview so staff always get one
        # more look before a real blank booklet page gets used.
        top_bar = QHBoxLayout()
        self.records_btn = QPushButton("Find / Reprint Record...")
        self.records_btn.clicked.connect(self.open_records_screen)
        self.printer_settings_btn = QPushButton("Printer Settings...")
        self.printer_settings_btn.clicked.connect(self.open_printer_settings)
        self.new_btn = QPushButton("New")
        self.new_btn.clicked.connect(self.reset_to_new_record)
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save_record)
        self.print_preview_btn = QPushButton("Print Preview")
        self.print_preview_btn.clicked.connect(self.print_preview)
        self.print_btn = QPushButton("Print")
        self.print_btn.clicked.connect(self.print_to_printer)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.close)
        top_bar.addWidget(self.records_btn)
        top_bar.addWidget(self.printer_settings_btn)
        top_bar.addStretch()
        top_bar.addWidget(self.new_btn)
        top_bar.addWidget(self.save_btn)
        top_bar.addWidget(self.print_preview_btn)
        top_bar.addWidget(self.print_btn)
        top_bar.addWidget(self.cancel_btn)
        outer.addLayout(top_bar)

        self.title_label = QLabel("Creating New IDL")
        self.title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #1a5fb4;")
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
        # 2026-09-14: trimmed from LAA's full field set (which also has
        # Mother's Name, Address, Phone, Email, Blood Type) down to just
        # the five Georgio said the company actually needs day-to-day —
        # on request, to cut clutter on the entry screen. This is a GUI
        # change only: ocr/pipeline.py still computes Mother's Name/
        # Address/Blood Type from OCR internally (harmless, just unused),
        # and set_field() below already silently no-ops for any key that
        # isn't in self.fields, so nothing crashes when autofill tries to
        # populate a field this screen no longer has.
        personal_box = QGroupBox()
        personal_form = QFormLayout()
        self.fields = {}
        for label in ["Surname", "First Name", "Father's Name", "Place of B.", "Date of B."]:
            edit = QLineEdit()
            self.fields[label] = edit
            personal_form.addRow(label + ":", edit)
        personal_box.setLayout(personal_form)
        left_column.addWidget(personal_box)

        # --- Original Document / Issued Document / Receipt groups
        # 2026-09-19: these three switched from QFormLayout to QGridLayout
        # so Number/Date (Original + Issued Document) and Amount(LBP)/Date
        # (Receipt) can sit PAIRED on one row, matching LAA's own screen —
        # a QFormLayout row can only ever hold one label + one field, which
        # is why this couldn't be done without changing layout type. See
        # _add_paired_row/_add_full_row just below and this module's
        # docstring for the full 2026-09-19 change.
        def _add_paired_row(grid: QGridLayout, row: int, label1: str, key1: str, label2: str, key2: str):
            edit1, edit2 = QLineEdit(), QLineEdit()
            self.fields[key1] = edit1
            self.fields[key2] = edit2
            grid.addWidget(QLabel(label1 + ":"), row, 0)
            grid.addWidget(edit1, row, 1)
            grid.addWidget(QLabel(label2 + ":"), row, 2)
            grid.addWidget(edit2, row, 3)

        def _add_full_row(grid: QGridLayout, row: int, label: str, key: str):
            edit = QLineEdit()
            self.fields[key] = edit
            grid.addWidget(QLabel(label + ":"), row, 0)
            grid.addWidget(edit, row, 1, 1, 3)  # span the two value columns, same width as a paired row's two fields combined
            return edit

        def _set_value_column_stretch(grid: QGridLayout):
            # Label columns (0, 2) stay their natural (small) width; value
            # columns (1, 3) share the rest of the row's width evenly —
            # matches the screenshot's proportions, where each field takes
            # up roughly half the group's width on a paired row.
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(3, 1)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(8)

        # --- Original Document group
        orig_box = QGroupBox("Original Document")
        orig_grid = QGridLayout()
        _add_paired_row(orig_grid, 0, "Number", "Original Document.Number", "Date", "Original Document.Date")
        _add_full_row(orig_grid, 1, "Place of Issue", "Original Document.Place of Issue")
        _add_full_row(orig_grid, 2, "Category", "Original Document.Category")
        _add_full_row(orig_grid, 3, "Expiry Date", "Original Document.Expiry Date")
        _set_value_column_stretch(orig_grid)
        orig_box.setLayout(orig_grid)
        left_column.addWidget(orig_box)

        # --- Issued Document group
        issued_box = QGroupBox("Issued Document")
        issued_grid = QGridLayout()
        _add_paired_row(issued_grid, 0, "Number", "Issued Document.Number", "Date", "Issued Document.Date")
        _add_full_row(issued_grid, 1, "Signature", "Issued Document.Signature")
        _set_value_column_stretch(issued_grid)
        issued_box.setLayout(issued_grid)
        left_column.addWidget(issued_box)

        # --- Receipt group
        receipt_box = QGroupBox("Receipt")
        receipt_grid = QGridLayout()
        _add_full_row(receipt_grid, 0, "Received from", "Receipt.Received from")
        _add_paired_row(receipt_grid, 1, "Amount(LBP)", "Receipt.Amount(LBP)", "Date", "Receipt.Date")
        _set_value_column_stretch(receipt_grid)
        receipt_box.setLayout(receipt_grid)
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

        # 150 (ImageUploadBox's own default): bumped up again from 130 as
        # part of the 2026-09-19 "make everything bigger" change, now that
        # the window's default height grew from 780 to 900 to match --
        # this panel's own QScrollArea (see above) is still there as a
        # fallback if a shrunk window ever makes scrolling necessary again.
        UPLOAD_BOX_SQUARE_SIZE = 150
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
        self.fields["Original Document.Place of Issue"].setText(DEFAULT_PLACE_OF_ISSUE)

        # 2026-09-14: "Receipt.Received from" auto-fills live from
        # Surname + First Name as they're typed, so staff don't have to
        # retype the applicant's name a second time in the Receipt
        # section (on request). self._receipt_received_from_auto tracks
        # the last value THIS sync wrote, so _sync_received_from_name can
        # tell "still following the auto-generated name" apart from "staff
        # typed something else on purpose" (e.g. someone else picking up
        # the document/paying on the applicant's behalf) and only ever
        # overwrites in the first case — see that method's docstring.
        self._receipt_received_from_auto = ""
        self.fields["Surname"].textChanged.connect(self._sync_received_from_name)
        self.fields["First Name"].textChanged.connect(self._sync_received_from_name)

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

        self._update_worker = None
        self._maybe_check_for_update()

    def _maybe_check_for_update(self):
        """2026-09-11: kicks off the background auto-update check (see
        UpdateCheckWorker above and updater/update_checker.py) — only
        when running as a built .exe (sys.frozen), never when running
        from source. Applying an update means swapping the INSTALLED
        app's folder for a new one; a developer running gui/new_idl_form.py
        straight from a git checkout has no such folder to swap, and
        nagging them to "update" their own in-progress edits would just
        be confusing."""
        if not getattr(sys, "frozen", False):
            return
        self._update_worker = UpdateCheckWorker()
        self._update_worker.update_found.connect(self._on_update_available)
        self._update_worker.start()

    def _on_update_available(self, manifest: UpdateManifest):
        log_update_available(CURRENT_VERSION, manifest.version)
        notes = f"\n\n{manifest.notes}" if manifest.notes else ""
        reply = QMessageBox.question(
            self, "Update available",
            f"Version {manifest.version} is available (you're running {CURRENT_VERSION})."
            f"{notes}\n\nInstall it now? The app will close and reopen automatically "
            "once it's done — save any work first.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            log_update_declined(CURRENT_VERSION, manifest.version)
            return

        install_dir = Path(sys.executable).parent
        exe_name = Path(sys.executable).name
        try:
            apply_update_and_restart(manifest, install_dir, exe_name)
        except UpdateApplyError as e:
            log_update_failed(CURRENT_VERSION, manifest.version, str(e))
            QMessageBox.critical(
                self, "Update failed",
                f"Could not install the update: {e}\n\n"
                "The app has not been changed and will keep running normally.",
            )
            return

        log_update_applied(CURRENT_VERSION, manifest.version)
        QApplication.instance().quit()

    def _update_autofill_enabled(self):
        all_filled = all(
            box.image_path
            for box in (self.passport_box, self.license_front_box, self.license_back_box)
        )
        self.autofill_btn.setEnabled(all_filled)

    def _sync_received_from_name(self):
        """Keeps "Receipt.Received from" following "{First Name} {Surname}"
        live as either changes (2026-09-14, on request) — but only while
        the field still holds either nothing, or exactly what this method
        last wrote there itself. The moment someone types something else
        into "Received from" by hand (a different person picking up or
        paying for the document), that comparison stops matching and this
        stops touching the field until it's cleared back to empty —
        so a manual correction never gets silently overwritten by the
        next keystroke in Surname or First Name."""
        first = self.fields["First Name"].text().strip()
        surname = self.fields["Surname"].text().strip()
        computed = " ".join(part for part in (first, surname) if part)

        receipt_field = self.fields["Receipt.Received from"]
        current = receipt_field.text()
        if current == "" or current == self._receipt_received_from_auto:
            receipt_field.setText(computed)
            self._receipt_received_from_auto = computed

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
        dialog.record_cloned.connect(self._clone_record)
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

    def _clone_record(self, source_record_id: int, fields: dict):
        """Starts a brand new, unsaved IDL record prefilled from a
        previously saved one (see gui/records_screen.py's "Clone as New
        Record" and its module docstring for the real-world motivation: a
        returning client's driving license number is searched, then this
        reuses their already-known personal/original-document/receipt-
        payer details instead of retyping them). Deliberately NOT the same
        as _load_record: this must end up in a "new, unsaved record" state
        (self.current_record_id stays None, so Save INSERTs a new row
        rather than updating source_record_id) -- otherwise Save would
        silently overwrite the client's earlier visit instead of creating
        a record for this new one.

        Every field carries over from the source record EXCEPT the three
        that describe THIS transaction rather than the client or their
        original document, which reset to the same defaults a genuinely
        new record already gets: "Issued Document.Number" goes blank
        (save_record's existing "generate one if blank" behavior then
        assigns a fresh serial at Save time, same as any new record --
        see save_record), "Issued Document.Date" resets to today, and
        "Receipt.Date" goes blank (a new transaction's receipt hasn't
        been dated yet). This matches LAA's own Clone behavior exactly,
        confirmed against a real recording Georgio shared (2026-09-19).

        self._receipt_received_from_auto is deliberately NOT set explicitly
        here to the cloned "Receipt.Received from" value (same as
        _load_record already does) -- but because this loop sets every
        field via setText() in self.fields' insertion order (Surname/First
        Name land before Receipt.Received from), _sync_received_from_name
        actually runs mid-loop off Surname/First Name's own textChanged
        signal and provisionally recomputes Receipt.Received from *before*
        this method's own explicit setText() for that field overwrites it
        with the real cloned value a few iterations later. The practical
        effect (see tests/test_new_idl_form.py::CloneRecordTest): when the
        cloned value already equals "{First Name} {Surname}" (the common
        case -- the applicant received their own document), the tracker
        ends up matching it too, so the field keeps live-syncing correctly
        if staff later fix a name typo on the clone. When the source
        record's Received From was a genuine manual override (someone
        else picked up/paid, e.g. "PAID BY COMPANY XYZ"), that value can
        never equal the loop's Surname/First-Name-derived intermediate
        value, so the tracker ends up stale/mismatched and the override
        survives a later Surname/First Name edit untouched -- same
        protection _load_record already relies on for exactly this
        reason."""
        for key, edit in self.fields.items():
            edit.setText(fields.get(key, ""))
            edit.setStyleSheet(NORMAL_STYLE)
        for box in (self.passport_box, self.license_front_box, self.license_back_box):
            box.clear_image()

        self.fields["Issued Document.Number"].setText("")
        self.fields["Issued Document.Date"].setText(date.today().strftime("%d/%m/%Y"))
        self.fields["Receipt.Date"].setText("")

        self.current_record_id = None
        self._save_baseline = None
        self.title_label.setText(f"Creating New IDL (cloned from record #{source_record_id})")
        log_record_cloned(source_record_id)

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
        self.fields["Original Document.Place of Issue"].setText(DEFAULT_PLACE_OF_ISSUE)
        # Both cleared above via the loop (Surname/First Name -> "" already
        # drove Receipt.Received from back to "" through the live sync),
        # but reset the tracker explicitly too so a fresh record starts
        # with sync fully re-armed rather than relying on that as a side
        # effect.
        self._receipt_received_from_auto = ""
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

    def open_printer_settings(self):
        PrinterSettingsDialog(parent=self).exec()

    def print_to_printer(self):
        """Sends the current form's data straight to the printer configured
        in Printer Settings — no viewer window, no OS print dialog. See
        printing/print_dispatch.py's module docstring for the mechanism
        (SumatraPDF's silent CLI) and why this is deliberately a separate
        action from Print Preview above."""
        from db.audit_log import log_print_dispatch_failed, log_print_dispatched
        from printing.print_dispatch import print_pdf_to_printer
        from printing.print_page import render_idl_data_page

        printer_name = get_configured_printer_name()
        if not printer_name:
            QMessageBox.warning(
                self, "No printer configured",
                "Set a printer first via \"Printer Settings...\" before printing.",
            )
            return

        confirm = QMessageBox.question(
            self, "Print to physical booklet page",
            f"This will print onto a real blank IDP booklet page loaded in "
            f"\"{printer_name}\". Have you checked Print Preview and confirmed "
            "the data is correct?\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        plain_values = {key: edit.text() for key, edit in self.fields.items()}
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        output_path = str(APP_DATA_DIR / "print_dispatch_last.pdf")
        try:
            render_idl_data_page(plain_values, output_path)
            print_pdf_to_printer(output_path, printer_name)
        except Exception as e:  # noqa: BLE001 - surface any failure (PrintDispatchError or otherwise), never a silent no-op
            log_print_dispatch_failed(self.current_record_id, printer_name, str(e))
            QMessageBox.critical(self, "Print failed", f"Could not print to {printer_name!r}: {e}")
            return

        log_print_dispatched(self.current_record_id, printer_name, output_path)
        QMessageBox.information(self, "Sent to printer", f"Sent to {printer_name}.")

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
            if key in NEVER_AUTOFILLED_FIELDS:
                continue  # e.g. Place of Issue -- always stays DEFAULT_PLACE_OF_ISSUE, see that set's docstring
            if not form_field.value and not form_field.flagged:
                continue  # never-autofilled fields (Phone, Email, Receipt.*, ...) - leave untouched
            self.set_field(key, form_field.value, flagged=form_field.flagged)
            if form_field.flagged:
                flagged_count += 1

        # Matches the loop above: a field this run never actually applied
        # to the screen (NEVER_AUTOFILLED_FIELDS) shouldn't count toward
        # "how many fields Autofill filled in" either, or the audit log's
        # filled=N would overstate what staff actually saw change.
        filled_count = sum(1 for key, f in fields.items() if f.value and key not in NEVER_AUTOFILLED_FIELDS)

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
