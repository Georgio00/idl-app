"""
Regression tests for gui/manage_users_dialog.py's ManageUsersDialog (added
2026-09-19, see that module's docstring) -- the only way to add a staff
login account after the very first one, which gui/login_dialog.py's
LoginDialog creates itself on a fresh install.

Also covers the same day's later admin-flag follow-up (Georgio asking who
should be able to reach this dialog at all): the "(admin)" list display,
"Toggle Admin", and the last-remaining-admin guard from db/storage.py's
set_admin/delete_user surfacing here as a plain warning rather than a
crash or a silent no-op.

Uses a REAL, temporary-file db.storage.Storage (same reasoning as
tests/test_login_dialog.py: the point is to exercise real account
creation/removal, not a mock's bookkeeping). QInputDialog and QMessageBox
are mocked per test since both are real modal calls that would otherwise
block headless test runs waiting for a click that never comes -- this
now includes _add_user's own QMessageBox.question (the "should this be an
admin?" prompt), not just the confirm/warning dialogs from before.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QLineEdit

_app = QApplication.instance() or QApplication([])

from db.storage import Storage
from gui.manage_users_dialog import ManageUsersDialog


def _make_storage(tmp_dir: Path) -> Storage:
    return Storage(db_path=tmp_dir / "test.db", key_path=tmp_dir / "test.key")


class ManageUsersDialogTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.storage = _make_storage(self.tmp_dir)
        self.storage.create_user("ROULA", "roula-password")
        self.dialog = ManageUsersDialog(self.storage)

    def test_lists_existing_usernames_on_open(self):
        items = [self.dialog.user_list.item(i).text() for i in range(self.dialog.user_list.count())]
        self.assertEqual(items, ["ROULA"])

    def test_add_user_creates_a_non_admin_account_by_default(self):
        with mock.patch(
            "gui.manage_users_dialog.QInputDialog.getText",
            side_effect=[("OJEIL", True), ("ojeil-password", True)],
        ), mock.patch("gui.manage_users_dialog.QMessageBox") as mock_box:
            mock_box.question.return_value = mock_box.No  # "make this an admin?" -- declined
            self.dialog._add_user()

        self.assertTrue(self.storage.verify_user("OJEIL", "ojeil-password"))
        self.assertFalse(self.storage.is_admin("OJEIL"))
        items = [self.dialog.user_list.item(i).text() for i in range(self.dialog.user_list.count())]
        self.assertIn("OJEIL", items)

    def test_add_user_can_be_made_an_admin(self):
        with mock.patch(
            "gui.manage_users_dialog.QInputDialog.getText",
            side_effect=[("OJEIL", True), ("ojeil-password", True)],
        ), mock.patch("gui.manage_users_dialog.QMessageBox") as mock_box:
            mock_box.question.return_value = mock_box.Yes  # "make this an admin?" -- accepted
            self.dialog._add_user()

        self.assertTrue(self.storage.is_admin("OJEIL"))
        items = [self.dialog.user_list.item(i).text() for i in range(self.dialog.user_list.count())]
        self.assertIn("OJEIL (admin)", items)

    def test_cancelling_the_username_prompt_adds_nothing(self):
        with mock.patch("gui.manage_users_dialog.QInputDialog.getText", return_value=("", False)):
            self.dialog._add_user()
        self.assertEqual(self.storage.user_count(), 1)

    def test_duplicate_username_shows_a_warning_and_does_not_crash(self):
        with mock.patch(
            "gui.manage_users_dialog.QInputDialog.getText",
            side_effect=[("ROULA", True), ("different-password", True)],
        ), mock.patch("gui.manage_users_dialog.QMessageBox") as mock_box:
            self.dialog._add_user()

        mock_box.warning.assert_called_once()
        self.assertEqual(self.storage.user_count(), 1)

    def test_change_password_updates_the_selected_account(self):
        self.dialog.user_list.setCurrentRow(0)
        with mock.patch(
            "gui.manage_users_dialog.QInputDialog.getText", return_value=("new-password", True)
        ), mock.patch("gui.manage_users_dialog.QMessageBox"):
            self.dialog._change_password()

        self.assertTrue(self.storage.verify_user("ROULA", "new-password"))
        self.assertFalse(self.storage.verify_user("ROULA", "roula-password"))

    def test_change_password_with_no_selection_shows_a_message(self):
        with mock.patch("gui.manage_users_dialog.QMessageBox") as mock_box:
            self.dialog._change_password()
        mock_box.information.assert_called_once()

    def test_remove_user_deletes_after_confirmation(self):
        self.dialog.user_list.setCurrentRow(0)
        with mock.patch("gui.manage_users_dialog.QMessageBox") as mock_box:
            mock_box.question.return_value = mock_box.Yes
            self.dialog._remove_user()

        self.assertEqual(self.storage.user_count(), 0)
        items = [self.dialog.user_list.item(i).text() for i in range(self.dialog.user_list.count())]
        self.assertNotIn("ROULA", items)

    def test_declining_the_confirmation_keeps_the_account(self):
        self.dialog.user_list.setCurrentRow(0)
        with mock.patch("gui.manage_users_dialog.QMessageBox") as mock_box:
            mock_box.question.return_value = mock_box.No
            self.dialog._remove_user()

        self.assertEqual(self.storage.user_count(), 1)

    def test_remove_user_with_no_selection_shows_a_message(self):
        dialog = ManageUsersDialog(self.storage)  # fresh dialog, nothing selected
        with mock.patch("gui.manage_users_dialog.QMessageBox") as mock_box:
            dialog._remove_user()
        mock_box.information.assert_called_once()


class AdminFlagTest(unittest.TestCase):
    """Regression coverage for the same-day admin-flag follow-up (see this
    module's docstring) -- "Toggle Admin" and the last-remaining-admin
    guards from db/storage.py's set_admin/delete_user."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.storage = _make_storage(self.tmp_dir)
        self.storage.create_user("ROULA", "roula-password", is_admin=True)
        self.dialog = ManageUsersDialog(self.storage)

    def test_admin_accounts_are_labeled_in_the_list(self):
        items = [self.dialog.user_list.item(i).text() for i in range(self.dialog.user_list.count())]
        self.assertEqual(items, ["ROULA (admin)"])

    def test_toggle_admin_grants_admin_to_a_non_admin_account(self):
        self.storage.create_user("OJEIL", "ojeil-password")  # not an admin
        self.dialog._reload_users()
        self.dialog.user_list.setCurrentRow(0)  # alphabetical -- OJEIL sorts before ROULA
        self.assertEqual(self.dialog._selected_username(), "OJEIL")

        self.dialog._toggle_admin()

        self.assertTrue(self.storage.is_admin("OJEIL"))

    def test_toggle_admin_refuses_to_demote_the_last_remaining_admin(self):
        self.dialog.user_list.setCurrentRow(0)  # ROULA, the only (and only admin) account
        with mock.patch("gui.manage_users_dialog.QMessageBox") as mock_box:
            self.dialog._toggle_admin()

        mock_box.warning.assert_called_once()
        self.assertTrue(self.storage.is_admin("ROULA"))  # unchanged

    def test_toggle_admin_can_demote_when_another_admin_exists(self):
        self.storage.create_user("OJEIL", "ojeil-password", is_admin=True)
        self.dialog._reload_users()
        self.dialog.user_list.setCurrentRow(1)  # ROULA, alphabetically after OJEIL

        self.dialog._toggle_admin()

        self.assertFalse(self.storage.is_admin("ROULA"))
        self.assertTrue(self.storage.is_admin("OJEIL"))  # untouched

    def test_toggle_admin_with_no_selection_shows_a_message(self):
        dialog = ManageUsersDialog(self.storage)  # fresh dialog, nothing selected
        with mock.patch("gui.manage_users_dialog.QMessageBox") as mock_box:
            dialog._toggle_admin()
        mock_box.information.assert_called_once()

    def test_remove_user_refuses_to_delete_the_last_remaining_admin(self):
        self.dialog.user_list.setCurrentRow(0)  # ROULA, the only (and only admin) account
        with mock.patch("gui.manage_users_dialog.QMessageBox") as mock_box:
            mock_box.question.return_value = mock_box.Yes
            self.dialog._remove_user()

        mock_box.warning.assert_called_once()
        self.assertEqual(self.storage.user_count(), 1)  # ROULA was NOT removed

    def test_remove_user_succeeds_when_another_admin_exists(self):
        self.storage.create_user("OJEIL", "ojeil-password", is_admin=True)
        self.dialog._reload_users()
        self.dialog.user_list.setCurrentRow(1)  # ROULA, alphabetically after OJEIL

        with mock.patch("gui.manage_users_dialog.QMessageBox") as mock_box:
            mock_box.question.return_value = mock_box.Yes
            self.dialog._remove_user()

        self.assertEqual(self.storage.user_count(), 1)
        self.assertTrue(self.storage.is_admin("OJEIL"))


if __name__ == "__main__":
    unittest.main()
