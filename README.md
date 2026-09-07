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

## Running

```bash
py -3.12 gui/new_idl_form.py         # main "New IDL" form
py -3.12 gui/calibration_screen.py   # print-layout calibration tool
```

Both need a display — they won't run headless. (For headless smoke-testing
imports only, set `QT_QPA_PLATFORM=offscreen` first.)

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
  - `new_idl_form.py` — the "New IDL" screen: form fields on the left, three labeled upload boxes (Passport / License Front / License Back) on the right, plus "Find / Reprint Record...", "New", Save, and Print Preview. The Autofill button is disabled until all three photos are filled, then runs `ocr.pipeline` on a background thread and flags low-confidence fields in orange.
  - `records_screen.py` — searchable dialog listing every saved record; Open loads one back into the main form for editing/re-saving (Save then updates that row instead of inserting a new one), Reprint re-renders its print PDF directly.
  - `image_upload_box.py` — the square upload widget: click-to-browse, drag-and-drop, thumbnail preview, Remove button. Accepts images directly or PDFs (routed through `pdf_utils.py`); either way `image_path` ends up pointing at a plain image file, so the OCR pipeline never needs to know which it was.
  - `pdf_utils.py` — thin wrapper around pdf2image (page count, single-page render, thumbnail render).
  - `pdf_page_picker.py` — the "click the right page" dialog shown when a dropped PDF has more than one page.
  - `calibration_screen.py` — click-and-drag tool to set print field positions over a real page photo, saved to `printing/layout_config.py`'s stored layout.
- **`db/`**
  - `storage.py` — local SQLite store. Records are encrypted at rest with Fernet (see the module docstring for why Fernet over SQLCipher). DB file and encryption key live in `%LOCALAPPDATA%\IDL_APP\`, never in the repo.
  - `audit_log.py` — always-on, persistent audit trail (app starts, autofill runs, record saves with a before/after diff of corrected fields, prints) at `%LOCALAPPDATA%\IDL_APP\logs\audit.log`. See the module docstring for what it records and its (deliberate) plain-text-at-rest trade-off.
- **`printing/`**
  - `layout_config.py` — relative-percentage field positions for the one IDP data page + cover page. **Placeholder page size (74x105mm)** until a blank booklet is measured.
  - `print_page.py` — renders the finalized data onto a PDF sized to the page, for printing directly onto the pre-printed blank booklet.
- **`packaging/`**
  - `idl_app.spec` / `build_installer.bat` — PyInstaller packaging so the app can eventually be run as a real installed `.exe` rather than a terminal command. Must be built on Windows — see the spec file's own header comment.
- **`tests/`** — 234 tests as of 2026-09-07: the OCR pipeline (the original, largest suite), plus `test_storage.py`, `test_audit_log.py`, and `test_records_screen_matching.py` covering the database and audit-log layers. `gui/`'s interactive dialogs are verified with manual headless Qt smoke tests rather than automated click-throughs — run with `python -m unittest discover -s tests`.

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
- **Real IDP page measurements.** `printing/layout_config.py` uses a
  placeholder page size; the calibration screen exists so this can be fixed
  without a code change once we have a blank booklet.
- **Printer integration.** `print_page.py` produces a PDF at the right
  physical size; actually sending it to a printer aligned with a booklet
  page already loaded in the tray is a manual/OS-print-dialog step for now.
  (Next up, per the current project plan.)
- **The Google Cloud Vision data-handling decision above** — flagged, not
  resolved. Needs an explicit answer from whoever owns that call before
  this handles real applicants' documents at volume.
- **No multi-user/authentication story.** Fine for the current one-
  machine, one-location deployment (per the brief); "who did this" in the
  audit log is only ever the Windows account name, not a real login.
