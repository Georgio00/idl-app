"""
Sends a finished IDL page PDF directly to a specific printer, silently --
no OS print dialog, no PDF viewer window popping up. This is what the
"Print" button (gui/new_idl_form.py) and the Records screen's "Reprint"
button (gui/records_screen.py) call; "Print Preview" is separate and
unchanged (it still just opens the PDF for a visual check, see
printing/print_page.py and new_idl_form.print_preview) -- printing for
real should always be a deliberate, distinct action from previewing.

2026-09-08: added because the company has one printer/tray specifically
loaded with the pre-printed blank IDP booklet pages -- staff need a single
button that sends straight there, not "open a PDF viewer, then manually
pick File > Print, then manually pick the right printer" every single
time (easy to fat-finger the wrong printer when a booklet page, not
scratch paper, is what's about to get printed on).

Uses SumatraPDF's command-line silent-print mode (`-print-to <printer>
-silent`) rather than any pure-Python approach: reportlab (which already
renders the PDF, see print_page.py) has no printer-dispatch capability of
its own, and PDF-to-a-named-Windows-printer without a dialog is
genuinely not something the Python standard library or any already-used
dependency here does. SumatraPDF is a small, free, portable .exe built
exactly for this kind of scripted use (no installer required, single
file) and its `-print-to`/`-silent` flags are a well-established pattern
for this. This is the same category of dependency as poppler (see
README.md's PDF upload support section) -- a separate native program this
module shells out to, not a pip package, and needs its own one-time setup
per machine (see README.md's Printing setup section).

NOT YET VERIFIED against a real physical printer -- this was built and
unit-tested (with subprocess mocked, see tests/test_print_dispatch.py)
from an environment with no printer to test against at all. The first
real print to the actual dedicated printer/tray needs to be watched in
person before trusting this for real booklet pages.
"""

from __future__ import annotations

import os
import shutil
import subprocess

# Same pattern as the old TESSERACT_CMD override (see README.md's git
# history) -- lets a machine where SumatraPDF isn't on PATH or isn't in
# one of the default install locations point straight at the .exe without
# a code change.
SUMATRA_PATH_ENV_VAR = "IDL_APP_SUMATRA_PATH"

_DEFAULT_SEARCH_PATHS = (
    r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
    r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
    r"C:\Users\{user}\AppData\Local\SumatraPDF\SumatraPDF.exe",
)


class PrintDispatchError(RuntimeError):
    """Raised when a real print could not be sent -- SumatraPDF missing,
    the printer name not recognized by Windows, or the print process
    itself failing. Callers (see gui/new_idl_form.py, gui/records_screen.py)
    must surface this to staff rather than silently treating "nothing
    printed" as success -- a booklet page that should exist but doesn't is
    a real operational problem, not a background detail."""


def find_sumatra_exe() -> str | None:
    """Checks IDL_APP_SUMATRA_PATH, then PATH itself, then the common
    Windows install locations, in that order. Returns None (never raises)
    if it can't be found anywhere -- callers decide how to react (see
    print_pdf_to_printer, which turns a None here into a clear
    PrintDispatchError with setup instructions rather than a bare
    FileNotFoundError from a failed subprocess call)."""
    env_path = os.environ.get(SUMATRA_PATH_ENV_VAR, "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path

    on_path = shutil.which("SumatraPDF") or shutil.which("SumatraPDF.exe")
    if on_path:
        return on_path

    username = os.environ.get("USERNAME", "")
    for candidate in _DEFAULT_SEARCH_PATHS:
        path = candidate.format(user=username) if "{user}" in candidate else candidate
        if os.path.isfile(path):
            return path

    return None


def print_pdf_to_printer(pdf_path: str, printer_name: str, timeout_seconds: float = 60.0) -> None:
    """Sends pdf_path to printer_name silently via SumatraPDF, waiting for
    the print job to actually be handed off (`-exit-when-done`) before
    returning, so a caller's success/failure branch reflects reality
    rather than a print that's still queued or that silently failed after
    this function already returned."""
    if not printer_name:
        raise PrintDispatchError(
            "No printer is configured yet. Set one via Printer Settings before printing."
        )
    if not os.path.isfile(pdf_path):
        raise PrintDispatchError(f"PDF to print does not exist: {pdf_path}")

    sumatra_path = find_sumatra_exe()
    if sumatra_path is None:
        raise PrintDispatchError(
            "SumatraPDF was not found -- it's required to send a page directly to a printer "
            "(see README.md's Printing setup section). Install it, or set the "
            f"{SUMATRA_PATH_ENV_VAR} environment variable to its full .exe path."
        )

    try:
        subprocess.run(
            [sumatra_path, "-print-to", printer_name, "-silent", "-exit-when-done", pdf_path],
            capture_output=True, text=True, timeout=timeout_seconds, check=True,
        )
    except subprocess.TimeoutExpired as e:
        raise PrintDispatchError(
            f"Printing to {printer_name!r} timed out after {timeout_seconds:.0f}s -- "
            "check the printer is on and not out of paper/jammed."
        ) from e
    except subprocess.CalledProcessError as e:
        detail = e.stderr.strip() if e.stderr else f"exit code {e.returncode}"
        raise PrintDispatchError(f"SumatraPDF could not print to {printer_name!r}: {detail}") from e
