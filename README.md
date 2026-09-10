# IDL Auto-fill App

Internal desktop tool that takes 3 ID documents (passport photo page, Lebanese
driving license front + back — either photographed or scanned as a PDF),
OCRs them, auto-fills the "New IDL" data entry form (mirroring the existing
LAA app's field layout), and — once we have exact physical measurements —
prints the finalized data onto a blank IDP booklet page. See
[claude_code_project_brief.md](claude_code_project_brief.md) for the full spec.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Python 3.10+ required** (the code uses `X | None` union-type syntax).
On this machine, `py -3.12` is the version to use — `py -3.9` (the default
`python` alias) is too old and will raise `TypeError` on import.

**OCR engine: Google Cloud Vision (current, since 2026-08-24).** This
section used to describe an earlier, fully-offline Tesseract setup —
that engine is no longer what the code actually calls (see
`ocr/ocr_client.py`'s module docstring for the full switch history and
why: real-world accuracy and Windows-specific Tesseract config bugs kept
costing debugging time). The practical difference this makes for setup
and for the company:

- **Every scanned ID photo (passport bio page, driving license front/
  back) is sent to Google's servers for OCR.** This is real government ID
  data. If offline-only processing is a hard requirement for this
  company, that needs to be raised and decided explicitly before this
  goes into production use — it was flagged as an open question in the
  original project brief and was never formally answered before the
  engine switch shipped.
- It requires a live internet connection, a Google Cloud project with the
  **Vision API enabled and billing set up**, and a per-document API cost
  at real usage volume (a single autofill run makes ~20-35 separate
  Vision calls — one per cropped field region across the passport and
  both sides of the license).
- **One-time setup, per machine that runs the app:**
  1. In Google Cloud Console: create (or use an existing) project, enable
     the **Cloud Vision API**, and create a service-account key (JSON) with
     permission to call it.
  2. Save that JSON file somewhere OUTSIDE this repo (e.g.
     `C:\Users\<you>\AppData\Local\IDL_APP\credentials\vision-key.json`) —
     it's a live credential; never commit it, and `.gitignore` already
     excludes a top-level `credentials/` folder as a reminder.
  3. Set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable to that
     file's full path (System Properties → Environment Variables on
     Windows, or `setx GOOGLE_APPLICATION_CREDENTIALS "C:\path\to\key.json"`
     from a terminal, then restart the terminal/app for it to take effect).
  4. Verify: launching the app and running Autofill should no longer show
     an error mentioning `GOOGLE_APPLICATION_CREDENTIALS` — see
     `ocr/ocr_client.py`'s `_get_client` for the exact error text this
     produces when it's missing or invalid.

Tesseract itself is **no longer required** to run the app, despite
`pytesseract` and the Arabic language-pack instructions this file used to
lead with — those only matter now if this project is ever deliberately
moved back to an offline engine.

The OCR call is isolated to `ocr/ocr_client.py` — swapping engines again
later only touches that one file.

**PDF upload support:** each of the three upload boxes also accepts a PDF
(a scanned document, not just a photographed one). `pip install pdf2image`
(already in requirements.txt) only installs the *Python wrapper* again —
like Tesseract, the actual PDF rendering is done by a separate native
program, **poppler**, which pdf2image just shells out to:

1. Download poppler for Windows (prebuilt binaries):
   https://github.com/oschwartz10612/poppler-windows/releases — grab the
   latest release zip.
2. Extract it somewhere permanent (e.g. `C:\poppler`), then add its
   `Library\bin` subfolder to your PATH (e.g. `C:\poppler\Library\bin`) so
   `pdftoppm.exe`/`pdfinfo.exe` are found. Restart any open terminal/the app
   after changing PATH.
3. Verify: `pdftoppm -v` should print a version, not "command not found".

If a PDF fails to load in the app, the error message will mention poppler —
that's this dependency, not a bug in the PDF itself.

**Printing setup (2026-09-08):** the "Print" button (and the Records
screen's "Reprint") send a page directly to a specific printer, silently —
no dialog, no PDF viewer popping up. This is separate from "Print
Preview", which still just opens the PDF so staff can check it visually
and needs no extra setup.

Sending directly to a printer needs **SumatraPDF**, a small free portable
PDF tool, installed on the machine (see `printing/print_dispatch.py`'s
module docstring for why this particular tool):

1. Download it from the official site: https://www.sumatrapdfreader.org/download-free-pdf-reader
   — the plain installer is fine, or the portable .exe if you'd rather not
   install anything.
2. If it doesn't end up on PATH and isn't in one of the usual
   `C:\Program Files\SumatraPDF\` locations, set the
   `IDL_APP_SUMATRA_PATH` environment variable to its full `.exe` path
   (same pattern as the old `TESSERACT_CMD` override).
3. In the app, click **"Printer Settings..."** and pick (or type) the
   name of the printer that has blank IDP booklet pages loaded. This is
   saved per machine — staff don't need to set it again after that.

**This has not yet been verified against a real printer** — it was built
and tested with the actual print call mocked out, from a machine with no
printer attached at all. The first real print needs to be watched in
person to confirm SumatraPDF's silent-print flags behave as documented
against your actual printer driver.

The page SIZE is now real (7cm x 10.5cm, measured 2026-09-09 — see
`printing/layout_config.py`'s docstring), but the field POSITIONS on that
page are still calibrated from an unrelated filled example page photo, not
a blank booklet (see "What's still open" below) — so print output will be
sized correctly but the individual fields may not land exactly where the
pre-printed template expects until that's separately verified against a
real blank page.

## Running

**Day-to-day (staff, no terminal):** double-click the "IDL App" icon on the
Desktop or Start Menu. See "Installing as a real app" right below for how
that icon gets created — it's a one-time setup step per machine, then it's
just a normal double-click app from then on.

**For development** (editing code, running from source):

```bash
py -3.12 gui/new_idl_form.py         # main "New IDL" form
py -3.12 gui/calibration_screen.py   # print-layout calibration tool
```

Both need a display — they won't run headless. (For headless smoke-testing
imports only, set `QT_QPA_PLATFORM=offscreen` first.)

### Installing as a real app (desktop icon, zero terminal typing)

This turns the app into a normal installed Windows program with a
double-click icon — the whole point being that after this one-time setup,
nobody ever has to open a terminal, activate a `.venv`, or type a command
to use it again.

1. In the project's root folder, find **`Update_and_Install.bat`** and
   double-click it. That's the only step — you never type anything into
   the black window that opens; it drives itself and tells you when it's
   done. It:
   - syncs the latest code (from the update bundle Claude drops in the
     project folder, or `git pull` if there's no bundle to sync from),
   - creates the project's `.venv` the first time only (a few minutes;
     instant every time after, since it's already there),
   - builds `dist\IDL_App\IDL_App.exe`, and
   - creates/refreshes the "IDL App" shortcut on the Desktop and Start
     Menu (via `packaging\create_shortcuts.ps1`).
2. From then on: double-click the "IDL App" desktop icon to open the app
   itself. No terminal, no typed command, no `.venv` to activate.

This is also how you pick up a new version later: whenever Claude pushes
an update into this folder, double-click `Update_and_Install.bat` again —
same one step, no re-typing anything — and it rebuilds and re-points the
same desktop icon at the new version.

(`packaging\build_installer.bat` still exists underneath and can be run
directly from a terminal if you prefer — see that file — but
`Update_and_Install.bat` is the normal path and needs nothing typed.)

This machine still needs the one-time dependencies listed in Setup
(Poppler, `GOOGLE_APPLICATION_CREDENTIALS`, SumatraPDF) regardless of
whether the app is launched from source or from the installed `.exe` —
the install script prints a reminder of these at the end. One catch
specific to the desktop icon: `GOOGLE_APPLICATION_CREDENTIALS` must be set
with `setx` (or via System Properties), not the terminal-only `set` — and
you need to log off and back on once after setting it, otherwise
double-clicking the icon (via Explorer, which doesn't see a plain `set`)
won't have the credential even though a terminal launched separately
would.

### Setting up a second device via USB (no rebuild needed there)

When another PC needs to run the app for real — processing real documents
and printing, not just viewing it — copy the already-built app over by USB
instead of rebuilding from source on that machine. Python, `.venv`, git,
and GitHub login are not needed on the new PC at all; the built app
already has everything it needs.

1. On a machine that already has `dist\IDL_App\` built (see "Installing
   as a real app" above), copy the whole `dist\IDL_App` folder onto a USB
   drive — the folder, not just the `.exe`, since it's missing its
   bundled dependencies without the rest of the folder.
2. Separately copy the Google Cloud Vision credentials JSON onto the USB,
   as its own file, not inside the `IDL_App` folder. It's a live
   credential — keep the drive secure while it's carrying it, and wipe it
   afterward if you won't reuse it for another transfer.
3. On the new PC: copy `IDL_App` from the USB to that PC (Desktop is
   fine). Right-click `IDL_App.exe` → **Send to → Desktop (create
   shortcut)** for a double-click icon — a normal Windows action, no
   script needed.
4. Copy the credentials file to a permanent spot on the new PC (e.g.
   `%LOCALAPPDATA%\IDL_APP\credentials\vision-key.json`), set
   `GOOGLE_APPLICATION_CREDENTIALS` to that path via System Properties →
   Environment Variables, then log off and back on once.
5. Install Poppler and SumatraPDF on the new PC — same one-time installers
   as the Setup / Printing setup sections above. Normal downloaded
   installers, unrelated to this app's own code.
6. Open the app once on the new PC and use "Printer Settings..." to pick
   that PC's printer.

**Important — each machine keeps its own separate records.** The
encrypted database, audit log, printer choice, and any saved print-layout
override all live under `%LOCALAPPDATA%\IDL_APP\` **on that one PC** —
copying the app via USB does not copy or share any of this. A record
saved on one device will not show up on the other; if staff need to look
up or reprint something saved on a different device than the one they're
using, they'd need to go to the device it was actually saved on. If both
devices should eventually share one list of records instead of each
keeping its own, that needs networked/shared storage in place of today's
per-machine SQLite file — a real design change, not something this USB
setup covers, worth flagging to whoever owns this decision at the company
before staff come to rely on cross-device lookups that don't actually
exist yet.

**Note on the dev machine used to build this:** two separate PySide6 DLL
issues showed up and are both worth knowing about if you hit
`ImportError: DLL load failed while importing QtWidgets` (or `QtCore`):
1. The system-wide Anaconda Python has both PyQt5 and PySide6 installed,
   and their Qt DLLs collide. Use the project's own `.venv` (see Setup)
   rather than the Anaconda environment.
2. Even in a clean `.venv`, PySide6 6.11.1 failed to load at all
   (`WinError 127`, reproduced loading `Qt6Core.dll` directly via `ctypes`,
   survived a VC++ redistributable reinstall + reboot). PySide6 6.7.3
   loads fine on the same machine — `requirements.txt` pins to 6.7.3.
   If setting up fresh elsewhere and hitting the same error, try pinning
   or unpinning that version.

## Project layout

- **`Update_and_Install.bat`** (project root) — the normal way to install or update the app: double-click it, no terminal typing. See "Installing as a real app" above.
- **`ocr/`** — OCR pipeline.
  - `ocr_client.py` — the only file that talks to Google Cloud Vision.
  - `mrz_parser.py` — parses + checksum-validates passport MRZ lines (no OCR itself).
  - `passport_ocr.py` — crops the MRZ band from a passport photo, OCRs it, feeds `mrz_parser`.
  - `image_prep.py` — OpenCV card corner detection + deskew for the license photos.
  - `license_field_regions.py` — relative-percentage crop regions for each numbered license field, calibrated against real sample photos (see the module docstring) but still tuned-for-the-samples-seen-so-far rather than guaranteed universal — worth re-verifying against a broader, varied batch of real cards before trusting it at full production volume.
  - `license_ocr.py` — deskews license front/back, crops+OCRs each field region, reads the category table.
  - `license_fields.py` — field definitions + Lebanese→IDP category mapping (`categories_to_idp`).
  - `pipeline.py` — merges passport + license OCR output into the form's fields per the brief's source-priority rules.
- **`gui/`**
  - `new_idl_form.py` — the "New IDL" screen: form fields on the left, three labeled upload boxes (Passport / License Front / License Back) on the right, plus "Find / Reprint Record...", "Printer Settings...", "New", Save, Print Preview, and Print. The Autofill button is disabled until all three photos are filled, then runs `ocr.pipeline` on a background thread and flags low-confidence fields in orange.
  - `records_screen.py` — searchable dialog listing every saved record; Open loads one back into the main form for editing/re-saving (Save then updates that row instead of inserting a new one), Reprint sends it directly to the configured printer.
  - `printer_settings_dialog.py` — pick (or type) which installed printer gets used by Print / Reprint; saved per machine via `printing/printer_config.py`.
  - `image_upload_box.py` — the square upload widget: click-to-browse, drag-and-drop, thumbnail preview, Remove button. Accepts images directly or PDFs (routed through `pdf_utils.py`); either way `image_path` ends up pointing at a plain image file, so the OCR pipeline never needs to know which it was.
  - `pdf_utils.py` — thin wrapper around pdf2image (page count, single-page render, thumbnail render).
  - `pdf_page_picker.py` — the "click the right page" dialog shown when a dropped PDF has more than one page.
  - `calibration_screen.py` — click-and-drag tool to set print field positions over a real page photo, saved to `printing/layout_config.py`'s stored layout.
- **`db/`**
  - `storage.py` — local SQLite store. Records are encrypted at rest with Fernet (see the module docstring for why Fernet over SQLCipher). DB file and encryption key live in `%LOCALAPPDATA%\IDL_APP\`, never in the repo.
  - `audit_log.py` — always-on, persistent audit trail (app starts, autofill runs, record saves with a before/after diff of corrected fields, previews, and real prints — success and failure) at `%LOCALAPPDATA%\IDL_APP\logs\audit.log`. See the module docstring for what it records and its (deliberate) plain-text-at-rest trade-off.
- **`printing/`**
  - `layout_config.py` — relative-percentage field positions for the one IDP data page + cover page. **Page size is real (70x105mm)**; field positions are still calibrated from an example photo, not a blank booklet.
  - `print_page.py` — renders the finalized data onto a PDF sized to the page.
  - `print_dispatch.py` — sends a rendered PDF straight to a named printer, silently, via SumatraPDF's CLI (see README's Printing setup section). **Not yet verified against a real printer.**
  - `printer_config.py` — remembers which printer is configured on this machine; lists Windows' installed printers via PowerShell.
- **`packaging/`**
  - `idl_app.spec` / `build_installer.bat` — PyInstaller packaging so the app runs as a real installed `.exe` rather than a terminal command. Must be built on Windows — see the spec file's own header comment.
  - `find_sqlite3_dll.py` — locates the SQLite engine DLL the built app needs at runtime, so it gets bundled automatically regardless of whether the build machine's Python is a plain python.org install or an Anaconda one (these two lay it out differently — see the module docstring for the real deployment failure this fixes, 2026-09-10).
  - `create_shortcuts.ps1` — creates the Desktop/Start Menu "IDL App" icon pointing at the built `.exe`; run automatically by `build_installer.bat`, or standalone if you just need to re-create the shortcuts (e.g. after moving the `dist\IDL_App\` folder).
- **`tests/`** — 234+ tests: the OCR pipeline (the original, largest suite), plus `test_storage.py`, `test_audit_log.py`, `test_records_screen_matching.py`, and `test_print_dispatch.py`/`test_printer_config.py` covering the database, audit-log, and print-dispatch layers (the last of these with the actual print call mocked — see `print_dispatch.py`'s docstring). `gui/`'s interactive dialogs are verified with manual headless Qt smoke tests rather than automated click-throughs — run with `python -m unittest discover -s tests`.

## Version control

This project is now a git repository (added 2026-09-07 — before that, it
was a folder of loose files on one machine with no history and no
rollback). If you're setting this up on a machine that doesn't have the
repo yet, see the git bundle and adoption steps that came with that
change, or ask whoever has the current repo for a normal `git clone`/
`git remote add` instead once this is pushed somewhere shared (e.g. a
private GitHub/GitLab repo) — that's the natural next step so history
doesn't depend on any one machine either.

## What's still open

- **License field region calibration at broader scale.** Calibrated
  against real samples, but only a handful of them so far — worth testing
  against a larger, more varied batch (different printers/scanners/
  lighting) before trusting it across every applicant.
- **Real IDP field-position calibration.** The page SIZE is now real
  (70x105mm, 2026-09-09), but `DEFAULT_DATA_PAGE_LAYOUT`'s field
  positions are still calibrated from an unrelated filled example page
  photo, not a blank booklet — `gui/calibration_screen.py` exists so this
  can be fixed without a code change once a blank booklet page is
  available to print a test page onto and check.
- **Real-printer verification (2026-09-08).** `print_dispatch.py` now
  sends directly to a configured printer via SumatraPDF (see the Printing
  setup section above) instead of relying on a manual OS print dialog —
  but this was built and unit-tested with the print call mocked, from a
  machine with no printer attached. Needs a real first print, watched in
  person, to confirm SumatraPDF's flags behave as documented against the
  actual printer/driver, before it's trusted for a real booklet page. Also
  still blocked on the page-size measurement above for the printed
  *positions* to be correct even once dispatch itself is confirmed working.
- **The Google Cloud Vision data-handling decision above** — flagged, not
  resolved. Needs an explicit answer from whoever owns that call before
  this handles real applicants' documents at volume.
- **No multi-user/authentication story.** Fine for the current one-
  machine, one-location deployment (per the brief); "who did this" in the
  audit log is only ever the Windows account name, not a real login.
