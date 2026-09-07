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

**OCR engine:** Tesseract (chosen — offline, no per-call cost, no ID photos
leaving the machine; trade-off is lower accuracy than a cloud OCR API,
particularly on the license's mixed Arabic/Latin fields). `pip install
pytesseract` (already in requirements.txt) only installs the *Python
wrapper* — Tesseract itself is a separate native program you need to
install on Windows:

1. Download and run the installer:
   https://github.com/UB-Mannheim/tesseract/wiki (the UB-Mannheim build is
   the standard Windows installer for Tesseract).
2. **During install, make sure the Arabic (`ara`) language pack is
   selected**, not just English — it's an optional component in the
   installer's component list, easy to miss. The license has mixed
   Arabic/Latin text and Arabic-labeled fields. Both language packs stay
   required even though the app only ever displays/stores the English
   content afterward (see `ocr/ocr_client.py`'s module docstring) — asking
   Tesseract to recognize English-only makes it force-fit every Arabic
   glyph onto the closest-looking English letter instead of skipping it,
   which is worse than recognizing the Arabic correctly and discarding it.
3. If `tesseract.exe` isn't automatically on PATH after install (default
   location: `C:\Program Files\Tesseract-OCR\tesseract.exe`), set the
   `TESSERACT_CMD` environment variable to that full path.

Verify both language packs are installed:
```bash
"C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs
```
should list both `ara` and `eng`.

The OCR call is isolated to `ocr/ocr_client.py` — swapping engines later
(e.g. to a cloud API, if offline accuracy turns out insufficient) only
touches that one file.

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
  - `ocr_client.py` — the only file that talks to Tesseract (via pytesseract).
  - `mrz_parser.py` — parses + checksum-validates passport MRZ lines (no OCR itself).
  - `passport_ocr.py` — crops the MRZ band from a passport photo, OCRs it, feeds `mrz_parser`.
  - `image_prep.py` — OpenCV card corner detection + deskew for the license photos.
  - `license_field_regions.py` — **placeholder** relative-percentage crop regions for each numbered license field. Needs calibration against real sample photos.
  - `license_ocr.py` — deskews license front/back, crops+OCRs each field region, reads the category table.
  - `license_fields.py` — field definitions + Lebanese→IDP category mapping (`categories_to_idp`).
  - `pipeline.py` — merges passport + license OCR output into the form's fields per the brief's source-priority rules.
- **`gui/`**
  - `new_idl_form.py` — the "New IDL" screen: form fields on the left, three labeled upload boxes (Passport / License Front / License Back) on the right. The Autofill button is disabled until all three are filled, then runs `ocr.pipeline` on a background thread (OCR makes ~35 individual Tesseract calls per autofill, one per cropped field region) and flags low-confidence fields in orange.
  - `image_upload_box.py` — the square upload widget: click-to-browse, drag-and-drop, thumbnail preview, Remove button. Accepts images directly or PDFs (routed through `pdf_utils.py`); either way `image_path` ends up pointing at a plain image file, so the OCR pipeline never needs to know which it was.
  - `pdf_utils.py` — thin wrapper around pdf2image (page count, single-page render, thumbnail render).
  - `pdf_page_picker.py` — the "click the right page" dialog shown when a dropped PDF has more than one page.
  - `calibration_screen.py` — click-and-drag tool to set print field positions over a real page photo, saved to `printing/layout_config.py`'s stored layout.
- **`db/`**
  - `storage.py` — local SQLite store. Records are encrypted at rest with Fernet (see the module docstring for why Fernet over SQLCipher). DB file and encryption key live in `%LOCALAPPDATA%\IDL_APP\`, never in the repo.
- **`printing/`**
  - `layout_config.py` — relative-percentage field positions for the one IDP data page + cover page. **Placeholder page size (74x105mm)** until a blank booklet is measured.
  - `print_page.py` — renders the finalized data onto a PDF sized to the page, for printing directly onto the pre-printed blank booklet.

## What's still open

- **License field region calibration.** `ocr/license_field_regions.py`'s crop
  boxes are estimates from the brief's field descriptions, not measured off
  a real card photo. Accuracy depends on tightening these against samples.
- **Real IDP page measurements.** `printing/layout_config.py` uses a
  placeholder page size; the calibration screen exists so this can be fixed
  without a code change once we have a blank booklet.
- **Printer integration.** `print_page.py` produces a PDF at the right
  physical size; actually sending it to a printer aligned with a booklet
  page already loaded in the tray is a manual/OS-print-dialog step for now.
