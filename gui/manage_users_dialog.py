"""
"Manage Staff Accounts..." — add, remove, or reset the password for a
staff login account (see gui/login_dialog.py and db/storage.py's
staff_users table). Reachable from the main form's toolbar once someone's
already logged in; this is the ONLY way to add an account after the very
first one (which LoginDialog's bootstrap mode creates on a fresh install)
— without it, there'd be no way to onboard a new staff member short of
editing the database by hand.

Deliberately no separate "admin" role or permission tier: this is a
single-office internal tool with a handful of staff (see db/storage.py's
own docstring on why field-level Fernet encryption, not SQLCipher, was
already judged proportionate at this app's scale) — anyone logged in can
manage accounts, the same way anyone logged in can already edit any
saved record.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QVBoxLayout,
)

from db.storage import Storage


class ManageUsersDialog(QDialog):
    def __init__(self, storage: Storage, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.setWindowTitle("Manage Staff Accounts")
        self.resize(380, 320)

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
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_user)
        button_row.addWidget(self.add_btn)
        button_row.addWidget(self.change_password_btn)
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
        self.user_list.addItems(self.storage.list_usernames())

    def _selected_username(self) -> str | None:
        item = self.user_list.currentItem()
        return item.text() if item is not None else None

    def _add_user(self):
        username, ok = QInputDialog.getText(self, "Add Staff Account", "Username:")
        if not ok or not username.strip():
            return
        password, ok = QInputDialog.getText(
            self, "Add Staff Account", f"Password for {username.strip()!r}:", QLineEdit.Password
        )
        if not ok:
            return
        try:
            self.storage.create_user(username, password)
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
        self.storage.delete_user(username)
        self._reload_users()
