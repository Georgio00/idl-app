@echo off
REM Builds the IDL App into a distributable folder (dist\IDL_App\) AND
REM creates a Desktop / Start Menu shortcut for it, so the end result of
REM running this one script is a double-click icon -- not a terminal
REM command you have to re-type every time.
REM
REM Normally you don't run this file directly -- double-click
REM Update_and_Install.bat at the project root instead, which also syncs
REM the code and creates the .venv first if needed, then calls this file.
REM This file can still be run on its own (e.g. `packaging\build_installer.bat`
REM from a terminal) as long as .venv already exists at the project root
REM (see README.md's Setup section) -- see idl_app.spec's own header
REM comment for why the build itself can't be done from a Linux machine.
REM
REM Usage:
REM     packaging\build_installer.bat

setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo No .venv found at the project root ^(%cd%^).
    echo Double-click Update_and_Install.bat instead -- it creates .venv
    echo automatically. Or manually: py -3.12 -m venv .venv, then
    echo .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

".venv\Scripts\python.exe" -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo Installing PyInstaller into .venv ...
    ".venv\Scripts\python.exe" -m pip install pyinstaller
    if errorlevel 1 (
        echo Could not install PyInstaller -- check your internet connection
        echo and try again.
        exit /b 1
    )
)

echo Building IDL_App ...
".venv\Scripts\python.exe" -m PyInstaller packaging\idl_app.spec --distpath dist --workpath build --noconfirm
if errorlevel 1 (
    echo Build failed -- see the PyInstaller output above.
    exit /b 1
)

echo.
echo Build done. The app is at dist\IDL_App\IDL_App.exe
echo Copy or zip the WHOLE dist\IDL_App\ folder to distribute it -- the
echo .exe alone is missing its bundled dependencies.
echo.
echo Creating a Desktop and Start Menu shortcut ...
powershell -ExecutionPolicy Bypass -File packaging\create_shortcuts.ps1
if errorlevel 1 (
    echo Shortcut creation failed -- see the PowerShell output above.
    echo The app itself still built fine at dist\IDL_App\IDL_App.exe;
    echo you can launch that .exe directly, or re-run
    echo packaging\create_shortcuts.ps1 once the issue above is fixed.
    exit /b 1
)

echo.
echo Before using it, this machine still needs (one-time, per machine):
echo   1. Poppler installed and on PATH (PDF upload support -- see README.md)
echo   2. GOOGLE_APPLICATION_CREDENTIALS set to a valid service-account key
echo      (OCR -- see README.md's Google Cloud Vision setup section).
echo      Use setx (not set) so it's still set after a reboot/logoff, and
echo      log off and back on once after setting it so double-clicking the
echo      new desktop icon picks it up too, not just terminal windows.
echo   3. SumatraPDF installed (direct-to-printer Print/Reprint -- see
echo      README.md's Printing setup section), and a printer picked via
echo      the app's own "Printer Settings..." button

endlocal
