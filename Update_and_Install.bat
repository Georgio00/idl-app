@echo off
REM ============================================================
REM  Double-click THIS FILE to install or update the IDL App.
REM  No terminal typing needed -- just double-click it and wait.
REM ============================================================
REM
REM Added 2026-09-10 because Georgio asked for the app to "always be
REM working" without having to run a terminal command, and then
REM specifically asked for zero terminal typing at all (not even
REM copy-pasted commands) and no separate download/USB step. This file
REM is the answer: it already lives in the project folder (delivered
REM straight into it, not something you had to fetch), and everything
REM below runs itself when you double-click it.
REM
REM What happens, each time you double-click it:
REM   1. Syncs the latest code Claude has pushed into this folder
REM      (from idl_app_repo.bundle sitting next to this file, if
REM      present -- or a plain `git pull` if it isn't).
REM   2. Creates the project's Python environment (.venv) the FIRST
REM      time only -- a few minutes, one-time. Every time after that,
REM      this step is skipped instantly because .venv already exists.
REM   3. Builds the app and creates/refreshes the "IDL App" icon on
REM      your Desktop and in the Start Menu.
REM
REM A black window shows progress while this runs -- you don't type
REM anything into it, it drives itself. It stays open at the very end
REM so you can read the final message; press any key to close it then.

setlocal
cd /d "%~dp0"

echo ============================================
echo  IDL App - Install / Update
echo ============================================
echo.

echo [1/3] Syncing latest code...
if exist "idl_app_repo.bundle" (
    git fetch idl_app_repo.bundle main >nul 2>nul
    git reset --hard FETCH_HEAD >nul 2>nul
) else (
    git pull >nul 2>nul
)

echo [2/3] Checking the Python environment...
if not exist ".venv\Scripts\python.exe" (
    echo       First-time setup -- this can take a few minutes...
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo.
        echo Could not create the Python environment. Make sure Python 3.12
        echo is installed ^(python.org^), then double-click this file again.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
) else (
    echo       Already set up -- skipping ^(no download needed^).
)

echo [3/3] Building the app and creating the desktop icon...
call packaging\build_installer.bat
if errorlevel 1 (
    echo.
    echo Something went wrong -- see the messages above.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Done. Look for the "IDL App" icon on your
echo  Desktop -- that is how you open the app
echo  from now on.
echo ============================================
echo.
pause

endlocal
