@echo off
REM Builds the IDL App into a distributable folder (dist\IDL_App\).
REM Run this FROM THE PROJECT ROOT, on Windows, inside the project's
REM .venv (see README.md's Setup section) -- see idl_app.spec's own
REM header comment for why this can't be done from a Linux machine.
REM
REM Usage:
REM     packaging\build_installer.bat

setlocal

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo PyInstaller is not installed in this environment.
    echo Run: pip install pyinstaller
    exit /b 1
)

echo Building IDL_App ...
pyinstaller packaging\idl_app.spec --distpath dist --workpath build --noconfirm
if errorlevel 1 (
    echo Build failed -- see the PyInstaller output above.
    exit /b 1
)

echo.
echo Done. The app is at dist\IDL_App\IDL_App.exe
echo Copy or zip the WHOLE dist\IDL_App\ folder to distribute it -- the
echo .exe alone is missing its bundled dependencies.
echo.
echo Before running it on a new machine, that machine still needs:
echo   1. Poppler installed and on PATH (PDF upload support -- see README.md)
echo   2. GOOGLE_APPLICATION_CREDENTIALS set to a valid service-account key
echo      (OCR -- see README.md's Google Cloud Vision setup section)
echo   3. SumatraPDF installed (direct-to-printer Print/Reprint -- see
echo      README.md's Printing setup section), and a printer picked via
echo      the app's own "Printer Settings..." button

endlocal
