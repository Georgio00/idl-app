# PyInstaller spec for the IDL Auto-fill App.
#
# 2026-09-07: added so a non-technical staff member can eventually run a
# real installed .exe instead of a terminal command. Before this, "running
# the app" meant opening a terminal, installing a specific Python version,
# a pinned PySide6 build, and (per README.md) poppler binaries -- a real
# barrier for anyone who isn't the person who built it.
#
# MUST BE BUILT ON WINDOWS. PyInstaller bundles the interpreter and native
# extensions for whatever OS it runs ON, not whatever OS you tell it to
# target -- there is no cross-compiling a Windows .exe from this repo's
# Linux dev/CI environment. Build this on the same kind of Windows machine
# the app will actually run on (see README.md's "Setup" section for the
# Python version and PySide6 pin that machine also needs).
#
# Build (from the project root, in the project's .venv, with PyInstaller
# installed -- `pip install pyinstaller`):
#
#     pyinstaller packaging\idl_app.spec --distpath dist --workpath build
#
# Output: dist\IDL_App\IDL_App.exe plus its bundled dependencies in the
# same folder -- copy or zip the whole dist\IDL_App\ folder to distribute
# it, not just the .exe alone (onedir mode, not onefile: a onefile build
# would work too, but unpacks itself to a temp folder on every launch,
# which is slower and makes crash diagnostics harder to reason about for
# an internal tool that isn't trying to hide how it's built).
#
# What this does NOT solve, on purpose:
#
# - Google Cloud Vision credentials. The service-account JSON that
#   authorizes OCR calls (see ocr/ocr_client.py's docstring and
#   GOOGLE_APPLICATION_CREDENTIALS) is a live credential and must never be
#   baked into a built executable -- anyone who received the .exe would
#   receive the credential too. Staff still need a one-time setup step
#   after installing: set GOOGLE_APPLICATION_CREDENTIALS to point at that
#   machine's own credentials file. See README.md's "Google Cloud Vision
#   setup" section.
# - Tesseract / poppler / SumatraPDF binaries. poppler (PDF upload
#   support, see gui/pdf_utils.py) and SumatraPDF (direct-to-printer
#   printing, see printing/print_dispatch.py, added 2026-09-08) are both
#   real runtime dependencies that are separate native programs this app
#   shells out to -- PyInstaller can't bundle a program it doesn't know
#   exists. Both still need their own one-time install per README.md's
#   Setup / Printing setup sections. Tesseract itself is no longer needed
#   at all (see ocr/ocr_client.py's 2026-08-24 docstring entry -- OCR
#   moved to Google Cloud Vision) even though README.md's older sections
#   still describe installing it.
#
# 2026-09-10: db/storage.py's sqlite3 usage crashed on a machine that
# wasn't the one that built the .exe -- "ImportError: DLL load failed
# while importing _sqlite3: The specified module could not be found."
# Root cause: _sqlite3.pyd (the Python C-extension wrapper) dynamically
# loads a separate sqlite3.dll (the actual SQLite engine), and on this
# project's build machine that DLL lives under the base Anaconda install
# (.venv\pyvenv.cfg's "home" -- Georgio's .venv was created from
# anaconda3\python.exe) at anaconda3\Library\bin\sqlite3.dll, NOT
# alongside python.exe the way a plain python.org install would lay it
# out. PyInstaller's automatic dependency scan didn't find it there, so
# it silently built a .exe that only worked on the machine that already
# happened to have that exact DLL on its PATH -- worked on the build
# machine, broke on every other machine. Fixed below via
# find_sqlite3_dll.py, which locates it relative to sys.base_prefix (the
# venv's base interpreter, whatever that turns out to be on whoever's
# machine builds this) instead of hardcoding Georgio's anaconda3 path,
# and fails the BUILD loudly if it's not found, rather than producing
# another silently-broken .exe. See tests/test_find_sqlite3_dll.py.

import sys
from pathlib import Path

block_cipher = None

PROJECT_ROOT = Path(SPECPATH).resolve().parent

sys.path.insert(0, str(PROJECT_ROOT / "packaging"))
from find_sqlite3_dll import find_sqlite3_dll  # noqa: E402

_SQLITE3_DLL = find_sqlite3_dll(sys.base_prefix)

a = Analysis(
    [str(PROJECT_ROOT / "gui" / "new_idl_form.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[
        (str(_SQLITE3_DLL), "."),
    ],
    datas=[
        # License field-region reference photos (ocr/license_ocr.py's
        # _load_reference_cards reads these by path relative to the
        # module file, which PyInstaller relocates -- they must be listed
        # explicitly or the built .exe silently loses the fine-alignment
        # step, see image_prep.align_to_reference's docstring for why
        # that step matters for accuracy).
        (str(PROJECT_ROOT / "ocr" / "reference_templates"), "ocr/reference_templates"),
    ],
    hiddenimports=[
        # google-cloud-vision's gRPC transport and PySide6's platform
        # plugins are both commonly missed by PyInstaller's static import
        # scan -- listed explicitly rather than discovered by trial and
        # error on a real build machine.
        "grpc",
        "google.cloud.vision_v1",
        "PySide6.QtSvg",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="IDL_App",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # a GUI app -- no console window on launch
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="IDL_App",
)
