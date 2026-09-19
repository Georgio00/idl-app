"""
"Manage Staff Accounts..." — add, remove, reset the password for, or
toggle admin access on a staff login account (see gui/login_dialog.py and
db/storage.py's staff_users table). Reachable from the main form's
toolbar, but ADMIN-ONLY: gui/new_idl_form.py hides the button entirely
for a non-admin account and refuses to open this dialog even if called
directly (see that module's docstring's is_admin paragraph) — this is
the ONLY way to add an account after the very first one (which
LoginDialog's bootstrap mode creates on a fresh install, always as an
admin), so restricting who can reach it is what actually controls who
can ever create or remove a staff login.

2026-09-19 (later the same day this whole login system shipped): Georgio
asked who should be able to manage staff accounts -- originally any
logged-in account could, which turned out to be more open than wanted.
Every username in the list below shows "(admin)" next to it when that
flag is set, and "Toggle Admin" flips it for the selected account.
db/storage.py's set_admin/delete_user both refuse to demote or remove
the LAST remaining admin (raising ValueError, caught here and shown as a
plain warning) -- without that guard, a single click here could lock
every account, including whoever's using this dialog right now, out of
ever managing staff again.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout,
)

from db.storage import Storage


class ManageUsersDialog(QDialog):
    def __init__(self, storage: Storage, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.setWindowTitle("Manage Staff Accounts")
        self.resize(380, 340)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Staff accounts that can log in to this app:"))

        self.user_list = QListWidget()
        layout.addWidget(self.user_list)
        self._reload_users()

        button_row = QHBoxLayout()
        self.add_btn = QPushButton("Add Account...")
        self.add_btn.clicked.connect(self._add_user)
        self.change_password_btn = QPushButton("Change Password...")
        self.change_password_btn.clicked.connect(self._change_password)
        self.toggle_admin_btn = QPushButton("Toggle Admin")
        self.toggle_admin_btn.setToolTip(
            "Grant or revoke access to this \"Manage Staff Accounts...\" screen "
            "for the selected account."
        )
        self.toggle_admin_btn.clicked.connect(self._toggle_admin)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_user)
        button_row.addWidget(self.add_btn)
        button_row.addWidget(self.change_password_btn)
        button_row.addWidget(self.toggle_admin_btn)
        button_row.addWidget(self.remove_btn)
        layout.addLayout(button_row)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    def _reload_users(self):
        self.user_list.clear()
        for username, is_admin in self.storage.list_users():
            label = f"{username} (admin)" if is_admin else username
            item = QListWidgetItem(label)
            # The list DISPLAYS "username (admin)", but every action below
            # needs the raw username back -- stored as the item's own data
            # rather than parsed back out of that display string.
            item.setData(Qt.UserRole, username)
            self.user_list.addItem(item)

    def _selected_username(self) -> str | None:
        item = self.user_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _add_user(self):
        username, ok = QInputDialog.getText(self, "Add Staff Account", "Username:")
        if not ok or not username.strip():
            return
        password, ok = QInputDialog.getText(
            self, "Add Staff Account", f"Password for {username.strip()!r}:", QLineEdit.Password
        )
        if not ok:
            return
        make_admin = QMessageBox.question(
            self, "Admin access",
            f"Should {username.strip()!r} be able to open \"Manage Staff Accounts...\" "
            "(add/remove accounts, reset passwords)?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes
        try:
            self.storage.create_user(username, password, is_admin=make_admin)
        except ValueError as e:
            QMessageBox.warning(self, "Could not add account", str(e))
            return
        self._reload_users()

    def _change_password(self):
        username = self._selected_username()
        if username is None:
            QMessageBox.information(self, "No selection", "Select a staff account first.")
            return
        password, ok = QInputDialog.getText(
            self, "Change Password", f"New password for {username!r}:", QLineEdit.Password
        )
        if not ok:
            return
        try:
            self.storage.change_password(username, password)
        except ValueError as e:
            QMessageBox.warning(self, "Could not change password", str(e))
            return
        QMessageBox.information(self, "Password changed", f"{username}'s password was updated.")

    def _toggle_admin(self):
        username = self._selected_username()
        if username is None:
            QMessageBox.information(self, "No selection", "Select a staff account first.")
            return
        currently_admin = self.storage.is_admin(username)
        try:
            self.storage.set_admin(username, not currently_admin)
        except ValueError as e:
            # The last-remaining-admin guard (see db/storage.py's
            # set_admin) lands here -- shown as a plain warning, not
            # allowed to silently no-op or crash.
            QMessageBox.warning(self, "Could not change admin access", str(e))
            return
        self._reload_users()

    def _remove_user(self):
        username = self._selected_username()
        if username is None:
            QMessageBox.information(self, "No selection", "Select a staff account first.")
            return
        confirm = QMessageBox.question(
            self, "Remove staff account",
            f"Remove {username!r}? They will no longer be able to log in.\n\n"
            "This does not change any IDL records they already created.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self.storage.delete_user(username)
        except ValueError as e:
            # Same last-remaining-admin guard as _toggle_admin, from
            # db/storage.py's delete_user this time.
            QMessageBox.warning(self, "Could not remove account", str(e))
            return
        self._reload_users()
