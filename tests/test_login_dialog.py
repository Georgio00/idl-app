"""
Regression tests for gui/login_dialog.py's LoginDialog (added 2026-09-19,
see that module's docstring) -- shown once at app startup, before
gui/new_idl_form.py's main window ever opens, per a real recording of
LAA's own login screen Georgio shared.

Uses a REAL, temporary-file db.storage.Storage (never a MagicMock) --
unlike tests/test_new_idl_form.py, the whole point of these tests is to
exercise real password verification end to end, so mocking Storage out
would test nothing. Run headless via QT_QPA_PLATFORM=offscreen, same
pattern as every other GUI test in this project.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QDialog

_app = QApplication.instance() or QApplication([])

from db.storage import Storage
from gui.login_dialog import LoginDialog, run_login


def _make_storage(tmp_dir: Path) -> Storage:
    return Storage(db_path=tmp_dir / "test.db", key_path=tmp_dir / "test.key")


class BootstrapModeTest(unittest.TestCase):
    """No staff accounts exist yet -- LoginDialog must offer to CREATE
    the first one rather than ask for credentials nobody could have."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.storage = _make_storage(self.tmp_dir)
        self.dialog = LoginDialog(self.storage)

    def test_bootstrap_mode_is_detected_when_no_accounts_exist(self):
        self.assertTrue(self.dialog._bootstrap)

    def test_asks_for_a_confirm_password_field(self):
        self.assertTrue(hasattr(self.dialog, "confirm_edit"))

    def test_creating_the_first_account_logs_straight_in(self):
        self.dialog.username_edit.setText("ROULA")
        self.dialog.password_edit.setText("hunter2")
        self.dialog.confirm_edit.setText("hunter2")

        self.dialog._submit()

        self.assertEqual(self.dialog.result(), QDialog.Accepted)
        self.assertEqual(self.dialog.username, "ROULA")
        self.assertEqual(self.storage.user_count(), 1)
        self.assertTrue(self.storage.verify_user("ROULA", "hunter2"))

    def test_mismatched_confirm_password_blocks_submission(self):
        self.dialog.username_edit.setText("ROULA")
        self.dialog.password_edit.setText("hunter2")
        self.dialog.confirm_edit.setText("something-else")

        # A real QMessageBox.warning() is modal -- mocked out here (and
        # in every other test below whose path shows one) so it doesn't
        # block this headless run waiting for a click that never comes.
        with mock.patch("gui.login_dialog.QMessageBox") as mock_box:
            self.dialog._submit()
        mock_box.warning.assert_called_once()

        self.assertNotEqual(self.dialog.result(), QDialog.Accepted)
        self.assertEqual(self.storage.user_count(), 0)

    def test_blank_username_blocks_submission(self):
        self.dialog.password_edit.setText("hunter2")
        self.dialog.confirm_edit.setText("hunter2")

        with mock.patch("gui.login_dialog.QMessageBox"):
            self.dialog._submit()

        self.assertEqual(self.storage.user_count(), 0)


class NormalLoginModeTest(unittest.TestCase):
    """An account already exists -- LoginDialog must ask for
    username/password and verify against the real stored account."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.storage = _make_storage(self.tmp_dir)
        self.storage.create_user("ROULA", "hunter2")
        self.dialog = LoginDialog(self.storage)

    def test_normal_mode_is_used_once_an_account_exists(self):
        self.assertFalse(self.dialog._bootstrap)

    def test_does_not_expose_a_confirm_password_field(self):
        self.assertFalse(hasattr(self.dialog, "confirm_edit"))

    def test_correct_credentials_log_in(self):
        self.dialog.username_edit.setText("ROULA")
        self.dialog.password_edit.setText("hunter2")

        self.dialog._submit()

        self.assertEqual(self.dialog.result(), QDialog.Accepted)
        self.assertEqual(self.dialog.username, "ROULA")

    def test_wrong_password_does_not_log_in(self):
        self.dialog.username_edit.setText("ROULA")
        self.dialog.password_edit.setText("wrong-password")

        with mock.patch("gui.login_dialog.QMessageBox"):
            self.dialog._submit()

        self.assertNotEqual(self.dialog.result(), QDialog.Accepted)
        self.assertIsNone(self.dialog.username)

    def test_wrong_password_clears_the_password_field(self):
        # So a mistyped password isn't just left sitting there visibly
        # wrong-looking (or, worse, easy to resubmit unchanged by
        # accident).
        self.dialog.username_edit.setText("ROULA")
        self.dialog.password_edit.setText("wrong-password")

        with mock.patch("gui.login_dialog.QMessageBox"):
            self.dialog._submit()

        self.assertEqual(self.dialog.password_edit.text(), "")

    def test_unknown_username_does_not_log_in(self):
        self.dialog.username_edit.setText("NOBODY")
        self.dialog.password_edit.setText("hunter2")

        with mock.patch("gui.login_dialog.QMessageBox"):
            self.dialog._submit()

        self.assertNotEqual(self.dialog.result(), QDialog.Accepted)

    def test_login_is_case_insensitive_on_username(self):
        self.dialog.username_edit.setText("roula")
        self.dialog.password_edit.setText("hunter2")

        self.dialog._submit()

        self.assertEqual(self.dialog.result(), QDialog.Accepted)


class RunLoginHelperTest(unittest.TestCase):
    """run_login (used by gui/new_idl_form.py's main()) is a thin wrapper
    around LoginDialog.exec() -- exercised here with LoginDialog itself
    replaced by a stand-in whose exec()/username are controlled directly,
    since a real modal exec() blocks on an event loop this headless test
    has no way to drive from outside."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.storage = _make_storage(self.tmp_dir)

    def test_returns_the_username_when_the_dialog_is_accepted(self):
        fake_dialog = mock.Mock()
        fake_dialog.exec.return_value = QDialog.Accepted
        fake_dialog.username = "ROULA"
        with mock.patch("gui.login_dialog.LoginDialog", return_value=fake_dialog) as mock_cls:
            result = run_login(self.storage)

        mock_cls.assert_called_once_with(self.storage, parent=None)
        self.assertEqual(result, "ROULA")

    def test_returns_none_when_the_dialog_is_rejected(self):
        fake_dialog = mock.Mock()
        fake_dialog.exec.return_value = QDialog.Rejected
        fake_dialog.username = None
        with mock.patch("gui.login_dialog.LoginDialog", return_value=fake_dialog):
            result = run_login(self.storage)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
