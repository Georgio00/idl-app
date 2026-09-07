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
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from cryptography.fernet import Fernet

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
        self._conn.commit()

    def next_issued_document_number(self) -> str:
        cur = self._conn.execute("SELECT next_number FROM issued_number_sequence WHERE id = 1")
        (n,) = cur.fetchone()
        self._conn.execute(
            "UPDATE issued_number_sequence SET next_number = ? WHERE id = 1", (n + 1,)
        )
        self._conn.commit()
        return f"IDL-{n:06d}"

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

    def close(self):
        self._conn.close()
