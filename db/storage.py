"""
Local storage for saved IDL records: a single-file SQLite database with the
record data encrypted at rest.

Encryption approach: field-level encryption of the whole record (via Fernet,
from the `cryptography` package) rather than whole-database encryption via
SQLCipher. SQLCipher was the brief's suggested default, but its Windows
wheels are inconsistently available and it needs a compiled native
extension, which is a poor fit for a plain internal desktop tool with a
single small table. Fernet is pure-Python-installable, well-audited
(AES-128-CBC + HMAC), and achieves the same goal here — a stolen .db file
is unreadable without the key. If a future requirement needs the whole file
(including schema/structure) opaque, swapping to SQLCipher only touches
this module.

The encryption key is generated on first run and stored outside the repo,
in the user's local app-data folder — never commit a key file.

2026-09-19: added a "staff_users" table (plain, unencrypted columns --
usernames aren't sensitive the way IDL record data is) for the login
system added the same day, see gui/login_dialog.py. Passwords are never
stored in any recoverable form: only a PBKDF2-HMAC-SHA256 hash + its
random salt (see _hash_password below), so even a stolen .db file can't
be used to log in directly.

2026-09-19 (later the same day): added an is_admin flag to staff_users,
after Georgio asked who should be able to open "Manage Staff Accounts..."
-- originally any logged-in staff member could add/remove any account,
which turned out to be more open than wanted. Only admin accounts can
manage accounts now (see gui/new_idl_form.py and gui/manage_users_dialog.py).
The very first account (created via LoginDialog's bootstrap mode on a
fresh install) is always an admin -- otherwise a brand new install could
end up with no one able to manage staff accounts at all. See
delete_user/set_admin below for why the LAST remaining admin can't be
removed or demoted either, for the same reason.

2026-09-26: added a "receipt_number_sequence" table (see
next_receipt_number below), for the "Print Receipt"/"View Receipt"
feature added the same day (see gui/new_idl_form.py and
printing/receipt_page.py). Same plain/unencrypted, independently-queryable
treatment as issued_number_sequence above, and deliberately a SEPARATE
counter from it — the two numbers appear on two different physical
documents (the IDP booklet page vs. the cash receipt) and must never be
confused with or influence each other.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from cryptography.fernet import Fernet

# 2026-09-19: password hashing for the staff login system added the same
# day (see gui/login_dialog.py) -- PBKDF2-HMAC-SHA256 via the standard
# library rather than adding a bcrypt/argon2 dependency, since this app
# already avoids extra native-compiled packages where it can (see this
# module's own top docstring on why Fernet was chosen over SQLCipher for
# the same reason). 200,000 iterations is comfortably above OWASP's current
# minimum guidance for PBKDF2-SHA256 and still logs in in well under a
# second on ordinary hardware -- this app has a handful of staff accounts
# logging in a few times a day, not a high-throughput auth service.
_PASSWORD_HASH_ITERATIONS = 200_000


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Returns (hash_hex, salt_hex). Generates a fresh random salt when
    none is given (creating/changing a password); pass the stored salt
    back in to verify a login attempt against it."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PASSWORD_HASH_ITERATIONS)
    return digest.hex(), salt.hex()

APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "IDL_APP"
DEFAULT_DB_PATH = APP_DATA_DIR / "idl_records.db"
DEFAULT_KEY_PATH = APP_DATA_DIR / "secret.key"


def _get_or_create_key(key_path: Path = DEFAULT_KEY_PATH) -> bytes:
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        return key_path.read_bytes()
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)  # no-op permission tightening on Windows, harmless
    except OSError:
        pass
    return key


@dataclass
class IdlRecord:
    id: int | None = None
    created_at: str = ""
    fields: dict = field(default_factory=dict)  # the full "New IDL" form field dict


class Storage:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH, key_path: Path = DEFAULT_KEY_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(_get_or_create_key(key_path))
        self._conn = sqlite3.connect(str(db_path))
        self._init_schema()

    def _init_schema(self):
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS idl_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                encrypted_fields BLOB NOT NULL
            )"""
        )
        # Sequence for "Issued Document.Number" — not sensitive on its own
        # (just an incrementing serial), kept as plain SQL so it can be
        # queried/reset independently of any record's encrypted content.
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS issued_number_sequence (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                next_number INTEGER NOT NULL
            )"""
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO issued_number_sequence (id, next_number) VALUES (1, 1)"
        )
        # 2026-09-26: separate sequence for "Receipt.Number" (see
        # gui/new_idl_form.py's _ensure_receipt_number and
        # printing/receipt_page.py) -- unlike Issued Document Number
        # (which stopped being auto-generated 2026-09-19, see that field's
        # own history above), Georgio confirmed the receipt's own "No."
        # SHOULD be auto-generated, matching LAA's own screen (which has
        # no visible field for it at all -- it's assigned automatically).
        # A separate table, not a shared one with issued_number_sequence,
        # because the two are unrelated counters that must never
        # interfere with each other's numbering.
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS receipt_number_sequence (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                next_number INTEGER NOT NULL
            )"""
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO receipt_number_sequence (id, next_number) VALUES (1, 1)"
        )
        # 2026-09-19: staff login accounts (see gui/login_dialog.py) --
        # added after Georgio shared a video of LAA's own login screen,
        # whose logged-in username is what fills each record's "User"
        # field (see gui/new_idl_form.py). username is stored
        # case-insensitively-unique (COLLATE NOCASE) so "Roula" and
        # "ROULA" can't silently become two different accounts, but the
        # value is kept exactly as typed for display (not forced to
        # upper/lowercase) -- see create_user.
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS staff_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0
            )"""
        )
        # 2026-09-19: is_admin migration for an install that already ran
        # an earlier build of this same feature (CREATE TABLE IF NOT
        # EXISTS above is a no-op once the table already exists, so an
        # existing staff_users table wouldn't otherwise gain this
        # column). If exactly one account already exists, it's almost
        # certainly the one LoginDialog's bootstrap mode created before
        # is_admin existed at all -- promoted to admin here so this
        # install doesn't end up with zero admins and no way to ever open
        # "Manage Staff Accounts..." again.
        existing_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(staff_users)")}
        if "is_admin" not in existing_columns:
            self._conn.execute("ALTER TABLE staff_users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            (count,) = self._conn.execute("SELECT COUNT(*) FROM staff_users").fetchone()
            if count == 1:
                self._conn.execute("UPDATE staff_users SET is_admin = 1")
        self._conn.commit()

    def next_issued_document_number(self) -> str:
        cur = self._conn.execute("SELECT next_number FROM issued_number_sequence WHERE id = 1")
        (n,) = cur.fetchone()
        self._conn.execute(
            "UPDATE issued_number_sequence SET next_number = ? WHERE id = 1", (n + 1,)
        )
        self._conn.commit()
        return f"IDL-{n:06d}"

    def next_receipt_number(self) -> str:
        """Used by gui/new_idl_form.py's _ensure_receipt_number the first
        time a receipt is viewed/printed for a given record -- see this
        module's docstring and the receipt_number_sequence table above.
        No "IDL-" prefix (unlike next_issued_document_number): the
        printed receipt's own "No." line reads as a plain running number
        on LAA's real screen (Georgio's 2026-09-26 video), not a
        document-type-prefixed serial."""
        cur = self._conn.execute("SELECT next_number FROM receipt_number_sequence WHERE id = 1")
        (n,) = cur.fetchone()
        self._conn.execute(
            "UPDATE receipt_number_sequence SET next_number = ? WHERE id = 1", (n + 1,)
        )
        self._conn.commit()
        return f"{n:06d}"

    def save_record(self, fields: dict) -> int:
        plaintext = json.dumps(fields, ensure_ascii=False).encode("utf-8")
        encrypted = self._fernet.encrypt(plaintext)
        created_at = datetime.now().isoformat()
        cur = self._conn.execute(
            "INSERT INTO idl_records (created_at, encrypted_fields) VALUES (?, ?)",
            (created_at, encrypted),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_record(self, record_id: int) -> IdlRecord | None:
        cur = self._conn.execute(
            "SELECT id, created_at, encrypted_fields FROM idl_records WHERE id = ?", (record_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        rid, created_at, encrypted = row
        fields = json.loads(self._fernet.decrypt(encrypted).decode("utf-8"))
        return IdlRecord(id=rid, created_at=created_at, fields=fields)

    def list_records(self) -> list[IdlRecord]:
        """Decrypts every record to build the list. Fine for this app's
        scale (one company location, one machine) — if that stops being
        true, add a small set of unencrypted index columns instead."""
        cur = self._conn.execute("SELECT id, created_at, encrypted_fields FROM idl_records ORDER BY id DESC")
        records = []
        for rid, created_at, encrypted in cur.fetchall():
            fields = json.loads(self._fernet.decrypt(encrypted).decode("utf-8"))
            records.append(IdlRecord(id=rid, created_at=created_at, fields=fields))
        return records

    def update_record(self, record_id: int, fields: dict) -> None:
        """2026-09-07: added for the Records screen's Open-then-Save-again
        flow (reprints and corrections) — previously save_record's plain
        INSERT was the only write path, so re-saving an already-saved
        record silently created a SECOND row instead of correcting the
        first. Raises ValueError for an unknown id rather than silently
        no-op'ing (an UPDATE ... WHERE id=? that matches nothing looks
        successful at the SQL level but would hide a real bug — e.g. a
        stale id from a record deleted by another process)."""
        plaintext = json.dumps(fields, ensure_ascii=False).encode("utf-8")
        encrypted = self._fernet.encrypt(plaintext)
        cur = self._conn.execute(
            "UPDATE idl_records SET encrypted_fields = ? WHERE id = ?", (encrypted, record_id)
        )
        self._conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"No IDL record with id {record_id} exists")

    # -- Staff login accounts (2026-09-19, see gui/login_dialog.py) --------

    def user_count(self) -> int:
        """Used by the login flow to tell "fresh install, no accounts yet"
        (offer to create the first one) apart from "accounts exist, ask
        for a username/password" -- see gui/login_dialog.py's LoginDialog."""
        cur = self._conn.execute("SELECT COUNT(*) FROM staff_users")
        (count,) = cur.fetchone()
        return count

    def list_usernames(self) -> list[str]:
        cur = self._conn.execute("SELECT username FROM staff_users ORDER BY username COLLATE NOCASE")
        return [row[0] for row in cur.fetchall()]

    def list_users(self) -> list[tuple[str, bool]]:
        """Like list_usernames, but pairs each with its admin flag --
        used by gui/manage_users_dialog.py to show which accounts can
        manage other accounts (see this module's docstring's is_admin
        paragraph)."""
        cur = self._conn.execute(
            "SELECT username, is_admin FROM staff_users ORDER BY username COLLATE NOCASE"
        )
        return [(username, bool(is_admin)) for username, is_admin in cur.fetchall()]

    def admin_count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM staff_users WHERE is_admin = 1")
        (count,) = cur.fetchone()
        return count

    def is_admin(self, username: str) -> bool:
        """False for an unknown username too (a safe default -- callers
        like gui/new_idl_form.py use this to decide whether to show
        "Manage Staff Accounts...", and "unknown user" should never
        accidentally read as "admin")."""
        cur = self._conn.execute(
            "SELECT is_admin FROM staff_users WHERE username = ? COLLATE NOCASE", (username.strip(),)
        )
        row = cur.fetchone()
        return bool(row[0]) if row is not None else False

    def create_user(self, username: str, password: str, is_admin: bool = False) -> None:
        """Raises ValueError for a blank username/password or one that
        already exists (case-insensitively, see _init_schema) rather than
        letting sqlite3.IntegrityError leak out -- the login/manage-users
        dialogs need a message they can show directly, not a raw DB
        exception."""
        username = username.strip()
        if not username:
            raise ValueError("Username is required.")
        if not password:
            raise ValueError("Password is required.")
        password_hash, password_salt = _hash_password(password)
        try:
            self._conn.execute(
                "INSERT INTO staff_users (username, password_hash, password_salt, created_at, is_admin) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, password_hash, password_salt, datetime.now().isoformat(), int(is_admin)),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"A staff account named {username!r} already exists.") from None
        self._conn.commit()

    def set_admin(self, username: str, is_admin: bool) -> None:
        """Raises ValueError for an unknown username, same as
        change_password/delete_user, and ALSO raises ValueError rather
        than actually demoting the very last remaining admin (is_admin=False
        on that account) -- otherwise a single mistaken click could lock
        every account, including this one, out of "Manage Staff
        Accounts..." forever, with no way back in short of editing the
        database by hand."""
        username = username.strip()
        if not is_admin and self.is_admin(username) and self.admin_count() <= 1:
            raise ValueError(
                f"{username!r} is the last remaining admin -- promote another account "
                "to admin first, or this app could never be managed again."
            )
        cur = self._conn.execute(
            "UPDATE staff_users SET is_admin = ? WHERE username = ? COLLATE NOCASE",
            (int(is_admin), username),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"No staff account named {username!r} exists")

    def verify_user(self, username: str, password: str) -> bool:
        """True only for a username that exists AND a password whose hash
        (recomputed with that account's own stored salt) matches exactly
        -- never reveals which half was wrong, same as LAA's own login
        gives no hint whether the username or the password was the
        problem."""
        cur = self._conn.execute(
            "SELECT password_hash, password_salt FROM staff_users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        )
        row = cur.fetchone()
        if row is None:
            return False
        stored_hash, salt_hex = row
        candidate_hash, _ = _hash_password(password, bytes.fromhex(salt_hex))
        return secrets.compare_digest(candidate_hash, stored_hash)

    def change_password(self, username: str, new_password: str) -> None:
        if not new_password:
            raise ValueError("Password is required.")
        password_hash, password_salt = _hash_password(new_password)
        cur = self._conn.execute(
            "UPDATE staff_users SET password_hash = ?, password_salt = ? WHERE username = ? COLLATE NOCASE",
            (password_hash, password_salt, username.strip()),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"No staff account named {username!r} exists")

    def delete_user(self, username: str) -> None:
        # Same reasoning as set_admin's last-admin guard: removing the
        # only admin account would leave NO account able to open "Manage
        # Staff Accounts..." ever again.
        username = username.strip()
        if self.is_admin(username) and self.admin_count() <= 1:
            raise ValueError(
                f"{username!r} is the last remaining admin -- promote another account "
                "to admin first, or this app could never be managed again."
            )
        cur = self._conn.execute(
            "DELETE FROM staff_users WHERE username = ? COLLATE NOCASE", (username,)
        )
        self._conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"No staff account named {username!r} exists")

    def close(self):
        self._conn.close()
