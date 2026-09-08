"""
Persistent audit trail for the IDL app.

2026-09-07: added as part of making this a real tool a company can rely on.
Before this, the ONLY logging in the app was gated behind a hidden
environment variable (IDL_APP_DEBUG_OCR, see gui/new_idl_form.py) and even
then went to the console only -- nothing persisted, and nothing was ever
recorded during a normal (non-debug) run. That meant there was no way to
answer "who processed this document," "when was this record created,"
or "what did staff change before saving" -- all reasonable questions for
a tool that handles government ID data and produces IDP booklets with
real legal weight.

This module is always on (no env var, no opt-in) and writes structured,
one-event-per-line text to a rotating log file under the same per-machine
app-data folder the encrypted database already lives in
(%LOCALAPPDATA%\\IDL_APP\\logs\\audit.log) -- see db/storage.py's
APP_DATA_DIR. Rotates at 5MB, keeps 5 backups, so it can't grow forever
unattended on a machine nobody is watching.

Threat model / what this is NOT: this log records real field values
(names, dates, document numbers) in PLAIN TEXT, same as the existing OCR
debug-dump feature already does for crops/words when enabled. That's a
deliberate choice, not an oversight -- an audit trail that redacts the
actual before/after values isn't very useful for answering "what got
changed," and every staff member using this app already sees this data
on the ID photos themselves. It lives in the same protected app-data
folder as the encrypted database and should be treated with the same
care (i.e. this folder should not be casually copied off the machine or
attached to an email) -- unlike the database, the log file itself is NOT
encrypted at rest, since a rotating text log doesn't fit Fernet's
whole-blob model cleanly and the operational value of being able to
`type`/`tail` it during troubleshooting was judged worth more than at-
rest encryption for this particular file. Revisit if that trade-off ever
stops being acceptable (e.g. move to per-line encryption, or ship this
folder inside a full-disk-encrypted machine as the actual control).

"Who" is recorded as the OS login name (getpass.getuser()) -- this app has
no login/authentication system of its own (see the brief: single internal
machine, no multi-user story), so the Windows account name is the closest
available notion of "who" without adding a whole auth system this app
doesn't otherwise need.
"""

from __future__ import annotations

import getpass
import logging
import logging.handlers
from pathlib import Path

from db.storage import APP_DATA_DIR

LOG_DIR = APP_DATA_DIR / "logs"
LOG_PATH = LOG_DIR / "audit.log"

_MAX_BYTES = 5 * 1024 * 1024  # 5MB per file
_BACKUP_COUNT = 5  # audit.log, audit.log.1, ... audit.log.5 (~30MB total cap)

_logger = logging.getLogger("idl_app.audit")
_configured = False


def configure_audit_logging() -> None:
    """Wires up the rotating file handler. Idempotent and safe to call more
    than once (e.g. once from gui/new_idl_form.py's main(), and again from
    any standalone script/test that wants audit events) -- only attaches
    the handler the first time.

    Deliberately does not raise if the log directory can't be created or
    written (e.g. a locked-down machine) -- an audit trail that's missing
    is a real problem worth investigating, but it must never be the reason
    autofill/save itself fails for a staff member trying to get their
    actual job done. Falls back to a null handler (events are simply
    dropped) with a one-time warning on the module logger instead."""
    global _configured
    if _configured:
        return
    _configured = True

    _logger.setLevel(logging.INFO)
    _logger.propagate = False  # never spam the root/console logger with these

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
    except OSError as e:
        logging.getLogger("idl_app").warning(
            "Audit log could not be opened at %s (%s) -- audit events will not be recorded "
            "this run.", LOG_PATH, e,
        )
        handler = logging.NullHandler()

    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(handler)


def _user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - never let "who is logged in" break an audit call
        return "unknown"


def _kv(pairs: dict[str, object]) -> str:
    """Renders an event as space-separated key=value pairs, quoting any
    value containing whitespace so the line stays parseable by a simple
    split -- values here are real names/document numbers, which routinely
    contain spaces."""
    parts = []
    for key, value in pairs.items():
        text = "" if value is None else str(value)
        if not text:
            text = '""'
        elif any(c.isspace() for c in text) or '"' in text:
            text = '"' + text.replace('"', '\\"') + '"'
        parts.append(f"{key}={text}")
    return " ".join(parts)


def log_app_start() -> None:
    _logger.info(_kv({"event": "app_start", "user": _user()}))


def log_autofill_run(passport_path: str, license_front_path: str, license_back_path: str,
                      filled_count: int, flagged_count: int, errors: list[str]) -> None:
    _logger.info(_kv({
        "event": "autofill_run",
        "user": _user(),
        "passport": passport_path,
        "license_front": license_front_path,
        "license_back": license_back_path,
        "filled": filled_count,
        "flagged": flagged_count,
        "errors": "; ".join(errors) if errors else "none",
    }))


def log_autofill_failed(message: str) -> None:
    _logger.info(_kv({"event": "autofill_failed", "user": _user(), "message": message}))


def log_record_saved(record_id: int, is_update: bool, changed_fields: dict[str, tuple[str, str]]) -> None:
    """changed_fields maps field key -> (old_value, new_value) for every
    field that differs from the baseline the caller compared against (see
    gui/new_idl_form.py's _save_baseline -- either the values autofill just
    produced, or the values an existing record had when it was opened for
    editing from the Records screen). Recorded as one line per changed
    field rather than one line for the whole record so a specific
    correction (e.g. "Surname" fixed after a misread) is directly
    greppable without parsing a large blob."""
    _logger.info(_kv({
        "event": "record_saved",
        "user": _user(),
        "record_id": record_id,
        "mode": "update" if is_update else "insert",
        "changed_field_count": len(changed_fields),
    }))
    for field_key, (old_value, new_value) in changed_fields.items():
        _logger.info(_kv({
            "event": "field_corrected",
            "user": _user(),
            "record_id": record_id,
            "field": field_key,
            "old": old_value,
            "new": new_value,
        }))


def log_record_opened(record_id: int) -> None:
    _logger.info(_kv({"event": "record_opened", "user": _user(), "record_id": record_id}))


def log_print(record_id: int | None, output_path: str) -> None:
    """Logs a PREVIEW render (opened in a PDF viewer for a visual check --
    see gui/new_idl_form.py's print_preview) -- nothing physically printed
    yet. See log_print_dispatched for an actual send-to-printer event."""
    _logger.info(_kv({
        "event": "print_rendered",
        "user": _user(),
        "record_id": record_id if record_id is not None else "unsaved",
        "output_path": output_path,
    }))


def log_print_dispatched(record_id: int | None, printer_name: str, output_path: str) -> None:
    """2026-09-08: logs an actual physical print sent to a real printer
    (see printing/print_dispatch.py) -- distinct from log_print's preview
    event above, since "a page was previewed on screen" and "a real
    booklet page was consumed" are very different facts to be able to
    look up later (e.g. reconciling how many physical blank booklet pages
    should have been used against how many the audit log says were)."""
    _logger.info(_kv({
        "event": "print_dispatched",
        "user": _user(),
        "record_id": record_id if record_id is not None else "unsaved",
        "printer": printer_name,
        "output_path": output_path,
    }))


def log_print_dispatch_failed(record_id: int | None, printer_name: str, message: str) -> None:
    _logger.info(_kv({
        "event": "print_dispatch_failed",
        "user": _user(),
        "record_id": record_id if record_id is not None else "unsaved",
        "printer": printer_name,
        "message": message,
    }))
