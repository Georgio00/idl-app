"""
Regression tests for gui/printer_settings_dialog.py's PrinterSettingsDialog
-- extended 2026-09-26 (see that module's docstring) with a SECOND,
independent printer choice for cash receipts alongside the original
booklet-page one, for the new "Print Receipt" feature
(printing/receipt_page.py, gui/new_idl_form.py), and later the same day
with a THIRD for "Print Form" (printing/form_page.py).

Uses a temporary PRINTER_CONFIG_PATH (never the real machine's config),
same pattern tests/test_printer_config.py already uses, and mocks
list_available_printers so these never actually shell out to PowerShell.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from printing import printer_config
from gui.printer_settings_dialog import PrinterSettingsDialog


class PrinterSettingsDialogTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self._orig_path = printer_config.PRINTER_CONFIG_PATH
        printer_config.PRINTER_CONFIG_PATH = self.tmp_dir / "printer_config.json"
        self._printers_patch = mock.patch(
            "gui.printer_settings_dialog.list_available_printers",
            return_value=["Booklet Tray Printer", "Front Desk Printer"],
        )
        self._printers_patch.start()

    def tearDown(self):
        self._printers_patch.stop()
        printer_config.PRINTER_CONFIG_PATH = self._orig_path

    def test_has_three_independent_printer_choices(self):
        dialog = PrinterSettingsDialog()
        self.assertEqual(dialog.booklet_choice.purpose, "booklet")
        self.assertEqual(dialog.receipt_choice.purpose, "receipt")
        self.assertEqual(dialog.form_choice.purpose, "form")

    def test_saving_sets_all_three_purposes_independently(self):
        dialog = PrinterSettingsDialog()
        dialog.booklet_choice.combo.setCurrentText("Booklet Tray Printer")
        dialog.receipt_choice.combo.setCurrentText("Front Desk Printer")
        dialog.form_choice.combo.setCurrentText("Front Desk Printer")
        dialog._save()

        self.assertEqual(printer_config.get_configured_printer_name(purpose="booklet"), "Booklet Tray Printer")
        self.assertEqual(printer_config.get_configured_printer_name(purpose="receipt"), "Front Desk Printer")
        self.assertEqual(printer_config.get_configured_printer_name(purpose="form"), "Front Desk Printer")

    def test_manual_entry_takes_precedence_over_the_combo(self):
        dialog = PrinterSettingsDialog()
        dialog.receipt_choice.manual_edit.setText("Some Other Printer")
        dialog._save()

        self.assertEqual(printer_config.get_configured_printer_name(purpose="receipt"), "Some Other Printer")

    def test_leaving_receipt_and_form_blank_does_not_block_saving_booklet(self):
        # Each purpose is independently optional -- see PrinterSettingsDialog._save.
        dialog = PrinterSettingsDialog()
        dialog.booklet_choice.combo.setCurrentText("Booklet Tray Printer")
        dialog.receipt_choice.combo.setCurrentIndex(-1)
        dialog.receipt_choice.manual_edit.setText("")
        dialog.form_choice.combo.setCurrentIndex(-1)
        dialog.form_choice.manual_edit.setText("")
        dialog._save()

        self.assertEqual(printer_config.get_configured_printer_name(purpose="booklet"), "Booklet Tray Printer")
        self.assertIsNone(printer_config.get_configured_printer_name(purpose="receipt"))
        self.assertIsNone(printer_config.get_configured_printer_name(purpose="form"))

    def test_an_existing_receipt_printer_is_preselected_on_reopen(self):
        printer_config.set_configured_printer_name("Front Desk Printer", purpose="receipt")
        dialog = PrinterSettingsDialog()
        self.assertEqual(dialog.receipt_choice.combo.currentText(), "Front Desk Printer")

    def test_a_previously_configured_printer_not_in_todays_listing_goes_to_manual_edit(self):
        printer_config.set_configured_printer_name("Retired Printer", purpose="receipt")
        dialog = PrinterSettingsDialog()
        self.assertEqual(dialog.receipt_choice.manual_edit.text(), "Retired Printer")

    def test_an_existing_form_printer_is_preselected_on_reopen(self):
        printer_config.set_configured_printer_name("Front Desk Printer", purpose="form")
        dialog = PrinterSettingsDialog()
        self.assertEqual(dialog.form_choice.combo.currentText(), "Front Desk Printer")

    def test_manual_entry_takes_precedence_for_form_too(self):
        dialog = PrinterSettingsDialog()
        dialog.form_choice.manual_edit.setText("Some Other Printer")
        dialog._save()

        self.assertEqual(printer_config.get_configured_printer_name(purpose="form"), "Some Other Printer")


if __name__ == "__main__":
    unittest.main()
