"""
Regression tests for printing/print_dispatch.py (added 2026-09-08).

Every test here mocks subprocess.run / the filesystem -- there is no real
printer or SumatraPDF install available in this environment (or in this
repo's CI, if one exists), so these tests only verify: the right command
gets built, and every documented failure mode raises PrintDispatchError
with a useful message instead of leaking a raw subprocess exception or
failing silently. See print_dispatch.py's module docstring: the actual
first real print to a physical printer still needs to be watched in
person on a real Windows machine before this is trusted for a real
booklet page -- these tests can't and don't substitute for that.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from printing import print_dispatch


class FindSumatraExeTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self._orig_environ = dict(__import__("os").environ)

    def tearDown(self):
        import os
        os.environ.clear()
        os.environ.update(self._orig_environ)

    def test_env_var_wins_when_set_to_a_real_file(self):
        import os

        fake_exe = self.tmp_dir / "SumatraPDF.exe"
        fake_exe.write_bytes(b"")
        os.environ[print_dispatch.SUMATRA_PATH_ENV_VAR] = str(fake_exe)
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(print_dispatch.find_sumatra_exe(), str(fake_exe))

    def test_env_var_pointing_at_a_nonexistent_file_is_ignored(self):
        import os

        os.environ[print_dispatch.SUMATRA_PATH_ENV_VAR] = str(self.tmp_dir / "does_not_exist.exe")
        with mock.patch("shutil.which", return_value=None), \
             mock.patch("os.path.isfile", side_effect=lambda p: p == "on_path.exe"):
            # No env var file, no PATH hit either in this branch -- falls through to None.
            result = print_dispatch.find_sumatra_exe()
        self.assertIsNone(result)

    def test_falls_back_to_shutil_which(self):
        import os

        os.environ.pop(print_dispatch.SUMATRA_PATH_ENV_VAR, None)
        with mock.patch("shutil.which", return_value=r"C:\Tools\SumatraPDF.exe"):
            self.assertEqual(print_dispatch.find_sumatra_exe(), r"C:\Tools\SumatraPDF.exe")

    def test_returns_none_when_nowhere_to_be_found(self):
        import os

        os.environ.pop(print_dispatch.SUMATRA_PATH_ENV_VAR, None)
        with mock.patch("shutil.which", return_value=None), \
             mock.patch("os.path.isfile", return_value=False):
            self.assertIsNone(print_dispatch.find_sumatra_exe())


class PrintPdfToPrinterTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.pdf_path = self.tmp_dir / "output.pdf"
        self.pdf_path.write_bytes(b"%PDF-fake")

    def test_raises_when_no_printer_name_given(self):
        with self.assertRaises(print_dispatch.PrintDispatchError):
            print_dispatch.print_pdf_to_printer(str(self.pdf_path), "")

    def test_raises_when_pdf_does_not_exist(self):
        with self.assertRaises(print_dispatch.PrintDispatchError):
            print_dispatch.print_pdf_to_printer(str(self.tmp_dir / "missing.pdf"), "Some Printer")

    def test_raises_a_clear_error_when_sumatra_is_not_found(self):
        with mock.patch("printing.print_dispatch.find_sumatra_exe", return_value=None):
            with self.assertRaises(print_dispatch.PrintDispatchError) as ctx:
                print_dispatch.print_pdf_to_printer(str(self.pdf_path), "Some Printer")
        self.assertIn("SumatraPDF", str(ctx.exception))

    def test_success_calls_sumatra_with_the_expected_arguments(self):
        fake_sumatra = r"C:\Tools\SumatraPDF.exe"
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with mock.patch("printing.print_dispatch.find_sumatra_exe", return_value=fake_sumatra), \
             mock.patch("subprocess.run", return_value=fake_result) as run_mock:
            print_dispatch.print_pdf_to_printer(str(self.pdf_path), "Booklet Tray Printer")

        args = run_mock.call_args.args[0]
        self.assertEqual(args[0], fake_sumatra)
        self.assertIn("-print-to", args)
        self.assertIn("Booklet Tray Printer", args)
        self.assertIn("-silent", args)
        self.assertIn(str(self.pdf_path), args)

    def test_forces_portrait_so_the_printer_cannot_auto_rotate_to_landscape(self):
        # 2026-09-29: every page this app renders is portrait-shaped (see
        # print_page.py/receipt_page.py/form_page.py); without an explicit
        # -print-settings, SumatraPDF may auto-rotate 90 degrees based on
        # the target printer's own default paper orientation, which is
        # what Georgio saw happen on a real booklet printer.
        fake_sumatra = r"C:\Tools\SumatraPDF.exe"
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with mock.patch("printing.print_dispatch.find_sumatra_exe", return_value=fake_sumatra), \
             mock.patch("subprocess.run", return_value=fake_result) as run_mock:
            print_dispatch.print_pdf_to_printer(str(self.pdf_path), "Booklet Tray Printer")

        args = run_mock.call_args.args[0]
        self.assertIn("-print-settings", args)
        settings_index = args.index("-print-settings")
        self.assertEqual(args[settings_index + 1], "portrait")

    def test_timeout_raises_print_dispatch_error(self):
        with mock.patch("printing.print_dispatch.find_sumatra_exe", return_value="sumatra.exe"), \
             mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="sumatra", timeout=60)):
            with self.assertRaises(print_dispatch.PrintDispatchError) as ctx:
                print_dispatch.print_pdf_to_printer(str(self.pdf_path), "Some Printer")
        self.assertIn("timed out", str(ctx.exception))

    def test_sumatra_failure_raises_print_dispatch_error_with_detail(self):
        error = subprocess.CalledProcessError(returncode=1, cmd="sumatra", stderr="Printer not found")
        with mock.patch("printing.print_dispatch.find_sumatra_exe", return_value="sumatra.exe"), \
             mock.patch("subprocess.run", side_effect=error):
            with self.assertRaises(print_dispatch.PrintDispatchError) as ctx:
                print_dispatch.print_pdf_to_printer(str(self.pdf_path), "Some Printer")
        self.assertIn("Printer not found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
