"""
Regression tests for printing/printer_config.py (added 2026-09-08 for
direct-to-printer Print/Reprint -- see printing/print_dispatch.py).

Each test points PRINTER_CONFIG_PATH at a temporary file (never the real
%LOCALAPPDATA%\\IDL_APP\\printer_config.json) by monkeypatching the
module attribute -- same pattern as tests/test_audit_log.py uses for
db/audit_log.py's LOG_PATH.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from printing import printer_config


class ConfiguredPrinterNameTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self._orig_path = printer_config.PRINTER_CONFIG_PATH
        printer_config.PRINTER_CONFIG_PATH = self.tmp_dir / "printer_config.json"

    def tearDown(self):
        printer_config.PRINTER_CONFIG_PATH = self._orig_path

    def test_returns_none_when_never_configured(self):
        self.assertIsNone(printer_config.get_configured_printer_name())

    def test_round_trips_a_saved_name(self):
        printer_config.set_configured_printer_name("Booklet Tray Printer")
        self.assertEqual(printer_config.get_configured_printer_name(), "Booklet Tray Printer")

    def test_overwriting_replaces_the_previous_value(self):
        printer_config.set_configured_printer_name("Old Printer")
        printer_config.set_configured_printer_name("New Printer")
        self.assertEqual(printer_config.get_configured_printer_name(), "New Printer")

    def test_corrupt_file_returns_none_rather_than_raising(self):
        printer_config.PRINTER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        printer_config.PRINTER_CONFIG_PATH.write_text("not valid json{{{", encoding="utf-8")
        self.assertIsNone(printer_config.get_configured_printer_name())

    def test_empty_string_name_treated_as_unconfigured(self):
        printer_config.set_configured_printer_name("")
        self.assertIsNone(printer_config.get_configured_printer_name())


class PrinterPurposeTest(unittest.TestCase):
    """2026-09-26: booklet vs receipt are independent settings (see this
    module's docstring note) -- added alongside "Print Receipt"."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self._orig_path = printer_config.PRINTER_CONFIG_PATH
        printer_config.PRINTER_CONFIG_PATH = self.tmp_dir / "printer_config.json"

    def tearDown(self):
        printer_config.PRINTER_CONFIG_PATH = self._orig_path

    def test_booklet_is_the_default_purpose(self):
        printer_config.set_configured_printer_name("Booklet Tray Printer")
        self.assertEqual(
            printer_config.get_configured_printer_name(purpose="booklet"),
            printer_config.get_configured_printer_name(),
        )

    def test_receipt_purpose_starts_unconfigured_even_when_booklet_is_set(self):
        printer_config.set_configured_printer_name("Booklet Tray Printer", purpose="booklet")
        self.assertIsNone(printer_config.get_configured_printer_name(purpose="receipt"))

    def test_setting_receipt_does_not_clobber_booklet(self):
        printer_config.set_configured_printer_name("Booklet Tray Printer", purpose="booklet")
        printer_config.set_configured_printer_name("Front Desk Printer", purpose="receipt")
        self.assertEqual(printer_config.get_configured_printer_name(purpose="booklet"), "Booklet Tray Printer")
        self.assertEqual(printer_config.get_configured_printer_name(purpose="receipt"), "Front Desk Printer")

    def test_setting_booklet_does_not_clobber_an_already_set_receipt(self):
        printer_config.set_configured_printer_name("Front Desk Printer", purpose="receipt")
        printer_config.set_configured_printer_name("Booklet Tray Printer", purpose="booklet")
        self.assertEqual(printer_config.get_configured_printer_name(purpose="receipt"), "Front Desk Printer")
        self.assertEqual(printer_config.get_configured_printer_name(purpose="booklet"), "Booklet Tray Printer")

    def test_overwriting_one_purpose_only_replaces_that_purpose(self):
        printer_config.set_configured_printer_name("Front Desk Printer", purpose="receipt")
        printer_config.set_configured_printer_name("Back Office Printer", purpose="receipt")
        self.assertEqual(printer_config.get_configured_printer_name(purpose="receipt"), "Back Office Printer")

    def test_unknown_purpose_raises(self):
        with self.assertRaises(ValueError):
            printer_config.get_configured_printer_name(purpose="fax")
        with self.assertRaises(ValueError):
            printer_config.set_configured_printer_name("Something", purpose="fax")


class ListAvailablePrintersTest(unittest.TestCase):
    def test_parses_one_printer_per_line(self):
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="Printer A\nPrinter B\n", stderr="")
        with mock.patch("subprocess.run", return_value=fake_result):
            printers = printer_config.list_available_printers()
        self.assertEqual(printers, ["Printer A", "Printer B"])

    def test_strips_blank_lines(self):
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="Printer A\n\n\nPrinter B\n", stderr="")
        with mock.patch("subprocess.run", return_value=fake_result):
            printers = printer_config.list_available_printers()
        self.assertEqual(printers, ["Printer A", "Printer B"])

    def test_no_printers_installed_returns_empty_list_not_an_error(self):
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with mock.patch("subprocess.run", return_value=fake_result):
            self.assertEqual(printer_config.list_available_printers(), [])

    def test_missing_powershell_raises_printer_list_error(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError()):
            with self.assertRaises(printer_config.PrinterListError):
                printer_config.list_available_printers()

    def test_timeout_raises_printer_list_error(self):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="powershell", timeout=10)):
            with self.assertRaises(printer_config.PrinterListError):
                printer_config.list_available_printers()

    def test_powershell_failure_raises_printer_list_error_with_detail(self):
        error = subprocess.CalledProcessError(returncode=1, cmd="powershell", stderr="Get-Printer : access denied")
        with mock.patch("subprocess.run", side_effect=error):
            with self.assertRaises(printer_config.PrinterListError) as ctx:
                printer_config.list_available_printers()
        self.assertIn("access denied", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
