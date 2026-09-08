"""
Stores and reads which physical printer the app should send finished IDL
pages to, and lists the printers Windows currently knows about so staff
can pick one instead of typing an exact name.

2026-09-08: added because the company has a specific printer/tray dedicated
to the pre-printed blank IDP booklet pages (see printing/print_dispatch.py
for the actual send-to-printer mechanism) — the app needs to remember
which one that is, per machine, without staff re-selecting it every single
print. Stored the same way printing.layout_config's print_layout.json
already is: a small JSON file under the per-machine app-data folder (see
db/storage.py's APP_DATA_DIR), never in the repo, since "which printer" is
a fact about one physical machine's setup, not something to version.

Listing installed printers shells out to PowerShell's Get-Printer rather
than adding a pywin32 dependency for Win32 printer-enumeration APIs —
PowerShell is guaranteed present on every target Windows machine this app
runs on, so this avoids a new native/compiled dependency for something a
one-line PowerShell command already does.
"""

from __future__ import annotations

import json
import subprocess

from db.storage import APP_DATA_DIR

PRINTER_CONFIG_PATH = APP_DATA_DIR / "printer_config.json"


def get_configured_printer_name() -> str | None:
    """None means "never configured yet" — callers should prompt staff to
    set one (see gui/printer_settings_dialog.py) rather than guessing or
    silently falling back to the OS default printer, since sending a real
    IDL page to the wrong printer/tray wastes a pre-printed blank booklet
    page, which isn't like wasting a sheet of scratch paper."""
    if not PRINTER_CONFIG_PATH.exists():
        return None
    try:
        data = json.loads(PRINTER_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    name = data.get("printer_name")
    return name if name else None


def set_configured_printer_name(name: str) -> None:
    PRINTER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRINTER_CONFIG_PATH.write_text(json.dumps({"printer_name": name}), encoding="utf-8")


class PrinterListError(RuntimeError):
    """Raised when Windows' installed-printer list can't be retrieved --
    callers should fall back to letting staff type a printer name by hand
    (see gui/printer_settings_dialog.py) rather than blocking entirely."""


def list_available_printers(timeout_seconds: float = 10.0) -> list[str]:
    """Returns every printer name Windows currently has installed (both
    physical and virtual, e.g. "Microsoft Print to PDF" — filtering which
    of those is the real dedicated one is a human decision, not this
    function's job). Raises PrinterListError on any failure (PowerShell
    missing, timeout, non-Windows dev machine) rather than returning an
    empty list silently -- an empty list is also a legitimate real answer
    (a machine with zero printers installed) and the two cases must stay
    distinguishable to the caller."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Printer | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=timeout_seconds, check=True,
        )
    except FileNotFoundError as e:
        raise PrinterListError(
            "Could not run PowerShell to list printers -- this app expects to run on Windows."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise PrinterListError("Listing printers timed out.") from e
    except subprocess.CalledProcessError as e:
        raise PrinterListError(f"Get-Printer failed: {e.stderr.strip() if e.stderr else e}") from e

    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
