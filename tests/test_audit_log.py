"""
Regression tests for db/audit_log.py -- the persistent, always-on audit
trail added 2026-09-07 (see that module's docstring for why: previously
the only logging in this app was gated behind a hidden environment
variable and never persisted anywhere).

Each test points the module at a temporary log file (never the real
%LOCALAPPDATA%\\IDL_APP\\logs\\audit.log) by monkeypatching LOG_DIR/
LOG_PATH and resetting the module's "already configured" flag first --
configure_audit_logging() is deliberately idempotent in production (safe
to call from multiple entry points), which means tests need to force it
to re-run against a fresh path rather than relying on its normal
call-once behavior.
"""

import logging
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import audit_log


class AuditLogTestCase(unittest.TestCase):
    """Base class: points the module at an isolated temp log file for the
    duration of each test and restores its real state afterward."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.log_path = self.tmp_dir / "audit.log"

        self._orig_log_dir = audit_log.LOG_DIR
        self._orig_log_path = audit_log.LOG_PATH
        self._orig_configured = audit_log._configured
        self._orig_handlers = list(audit_log._logger.handlers)

        audit_log.LOG_DIR = self.tmp_dir
        audit_log.LOG_PATH = self.log_path
        audit_log._configured = False
        audit_log._logger.handlers = []

        audit_log.configure_audit_logging()

    def tearDown(self):
        for handler in audit_log._logger.handlers:
            handler.close()
        audit_log.LOG_DIR = self._orig_log_dir
        audit_log.LOG_PATH = self._orig_log_path
        audit_log._configured = self._orig_configured
        audit_log._logger.handlers = self._orig_handlers

    def _read_log(self) -> str:
        for handler in audit_log._logger.handlers:
            handler.flush()
        return self.log_path.read_text() if self.log_path.exists() else ""


class ConfigureAuditLoggingTest(AuditLogTestCase):
    def test_creates_the_log_directory_and_file(self):
        audit_log.log_app_start()
        self.assertTrue(self.log_path.exists())

    def test_is_idempotent_and_does_not_duplicate_handlers(self):
        handler_count_before = len(audit_log._logger.handlers)
        audit_log.configure_audit_logging()  # second call, should be a no-op
        self.assertEqual(len(audit_log._logger.handlers), handler_count_before)

    def test_does_not_propagate_to_the_root_logger(self):
        # This is a plain-text audit trail meant for its own file, not
        # console spam mixed in with everything else the app logs.
        self.assertFalse(audit_log._logger.propagate)


class LogEventFormatTest(AuditLogTestCase):
    def test_autofill_run_logs_all_fields(self):
        audit_log.log_autofill_run("/p.jpg", "/lf.jpg", "/lb.jpg", filled_count=10, flagged_count=3, errors=[])
        content = self._read_log()
        self.assertIn("event=autofill_run", content)
        self.assertIn("filled=10", content)
        self.assertIn("flagged=3", content)
        self.assertIn("errors=none", content)

    def test_autofill_run_logs_errors_when_present(self):
        audit_log.log_autofill_run("/p.jpg", "/lf.jpg", "/lb.jpg", 0, 0, ["Vision credentials missing"])
        self.assertIn("Vision credentials missing", self._read_log())

    def test_record_saved_logs_summary_and_one_line_per_changed_field(self):
        audit_log.log_record_saved(
            record_id=42, is_update=True,
            changed_fields={"Surname": ("ELALAM", "EL ALAM"), "Place of B.": ("", "BEIRUT")},
        )
        content = self._read_log()
        self.assertIn("event=record_saved", content)
        self.assertIn("record_id=42", content)
        self.assertIn("mode=update", content)
        self.assertIn("changed_field_count=2", content)
        self.assertIn("event=field_corrected", content)
        self.assertIn("field=Surname", content)
        self.assertIn("old=ELALAM", content)
        # A value containing a space must be quoted so the line stays
        # parseable by a simple whitespace split.
        self.assertIn('new="EL ALAM"', content)

    def test_record_saved_insert_mode(self):
        audit_log.log_record_saved(record_id=1, is_update=False, changed_fields={})
        self.assertIn("mode=insert", self._read_log())

    def test_no_field_corrected_lines_when_nothing_changed(self):
        audit_log.log_record_saved(record_id=1, is_update=True, changed_fields={})
        content = self._read_log()
        self.assertIn("changed_field_count=0", content)
        self.assertNotIn("field_corrected", content)

    def test_empty_value_is_rendered_as_explicit_empty_quotes_not_dropped(self):
        audit_log.log_record_saved(record_id=1, is_update=True, changed_fields={"Phone": ("", "71000000")})
        content = self._read_log()
        self.assertIn('old=""', content)

    def test_print_logs_unsaved_when_no_record_id(self):
        audit_log.log_print(None, "/tmp/preview.pdf")
        content = self._read_log()
        self.assertIn("event=print_rendered", content)
        self.assertIn("record_id=unsaved", content)

    def test_print_logs_the_record_id_when_present(self):
        audit_log.log_print(7, "/tmp/reprint_record_7.pdf")
        self.assertIn("record_id=7", self._read_log())

    def test_every_line_has_a_timestamp_prefix(self):
        audit_log.log_app_start()
        first_line = self._read_log().splitlines()[0]
        # "%Y-%m-%d %H:%M:%S event=..." -- just check it starts with a
        # plausible date, not the exact format (that's logging's job).
        self.assertRegex(first_line, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} event=")


if __name__ == "__main__":
    unittest.main()
