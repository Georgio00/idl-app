"""
Staff login screen — shown once, at app startup, before the main "New IDL"
window ever opens. Added 2026-09-19 after Georgio shared a video of LAA's
own equivalent: LAA asks for a Username + Password before it opens, and
whichever staff member is logged in is what LAA's "User" field records on
every IDL from then on (see gui/new_idl_form.py's docstring and
Receipt.User) — previously our app had no accounts at all, and "User" was
a plain manually-typed field with no real attribution guarantee behind it.

Two modes, chosen automatically from db.storage.Storage.user_count():

  * Normal (accounts already exist): plain Username/Password fields and a
    "Log In" button, checked against Storage.verify_user.
  * Bootstrap (a fresh install, zero staff accounts yet — there's no one
    to log in AS): instead asks for a new Username/Password/Confirm to
    create the very first account, then logs straight into it. Without
    this, a brand new install would be locked out before any account
    could ever exist. Every account after the first is added later via
    "Manage Staff Accounts..." (see gui/manage_users_dialog.py), reachable
    from the main form once someone's already logged in.

Cancelling either mode (or closing the window) means run_login returns
None — see gui/new_idl_form.py's main(), which exits the app rather than
ever opening the main form without a logged-in user.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from db.storage import Storage


class LoginDialog(QDialog):
    def __init__(self, storage: Storage, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.username: str | None = None  # set on a successful Login/Create — see accept-path methods below
        self._bootstrap = storage.user_count() == 0

        self.setWindowTitle("Staff Login" if not self._bootstrap else "Create the First Staff Account")
        self.resize(360, 200)
        self.setModal(True)

        layout = QVBoxLayout(self)

        if self._bootstrap:
            layout.addWidget(QLabel(
                "No staff accounts exist yet on this machine.\n"
                "Create the first one to get started — you can add more later "
                "from \"Manage Staff Accounts...\"."
            ))
        else:
            layout.addWidget(QLabel("Enter your staff username and password."))

        form = QFormLayout()
        self.username_edit = QLineEdit()
        form.addRow("Username:", self.username_edit)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Password:", self.password_edit)
        if self._bootstrap:
            self.confirm_edit = QLineEdit()
            self.confirm_edit.setEchoMode(QLineEdit.Password)
            form.addRow("Confirm Password:", self.confirm_edit)
        layout.addLayout(form)

        # Enter in the last field submits, matching how every other
        # dialog/save action in this app already responds to Enter.
        last_field = self.confirm_edit if self._bootstrap else self.password_edit
        last_field.returnPressed.connect(self._submit)

        button_row = QHBoxLayout()
        # "&&" (not a bare "&") -- Qt treats a single "&" as marking the
        # next letter a keyboard mnemonic (and hides the "&" itself),
        # which read as a stray underscore before "Log" once rendered
        # rather than the literal word "and".
        submit_btn = QPushButton("Create Account && Log In" if self._bootstrap else "Log In")
        submit_btn.clicked.connect(self._submit)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_row.addStretch()
        button_row.addWidget(submit_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

        self.username_edit.setFocus()

    def _submit(self):
        if self._bootstrap:
            self._submit_bootstrap()
        else:
            self._submit_login()

    def _submit_login(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            QMessageBox.warning(self, "Missing data", "Enter both a username and a password.")
            return
        if not self.storage.verify_user(username, password):
            QMessageBox.warning(self, "Login failed", "Incorrect username or password.")
            self.password_edit.clear()
            self.password_edit.setFocus()
            return
        self.username = username
        self.accept()

    def _submit_bootstrap(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        confirm = self.confirm_edit.text()
        if not username or not password:
            QMessageBox.warning(self, "Missing data", "Enter both a username and a password.")
            return
        if password != confirm:
            QMessageBox.warning(self, "Passwords don't match", "Password and Confirm Password must match.")
            self.confirm_edit.clear()
            self.confirm_edit.setFocus()
            return
        try:
            self.storage.create_user(username, password)
        except ValueError as e:
            QMessageBox.warning(self, "Could not create account", str(e))
            return
        self.username = username
        self.accept()


def run_login(storage: Storage, parent=None) -> str | None:
    """Shows LoginDialog modally and returns the logged-in username, or
    None if the person cancelled/closed it (either mode) — see this
    module's docstring and gui/new_idl_form.py's main(), which treats
    None as "exit the app, never open the main form without a logged-in
    user"."""
    dialog = LoginDialog(storage, parent=parent)
    if dialog.exec() == QDialog.Accepted:
        return dialog.username
    return None
