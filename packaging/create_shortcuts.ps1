<#
Creates a Desktop shortcut and a Start Menu shortcut for the built IDL App
(dist\IDL_App\IDL_App.exe), so staff can double-click an icon to open it
instead of running a terminal command every time -- see the 2026-09-09
"make this a real app" work in README.md's Setup section.

Run this AFTER packaging\build_installer.bat has successfully produced
dist\IDL_App\IDL_App.exe (build_installer.bat now calls this script
automatically at the end -- you normally don't need to run this file
directly). Safe to re-run any time, e.g. after rebuilding a newer
version: it overwrites the existing shortcuts in place rather than
duplicating them.

Standalone usage (from the project root, in a normal PowerShell window --
no admin rights needed, since this only touches the current user's own
Desktop and Start Menu folders, not anything system-wide):

    powershell -ExecutionPolicy Bypass -File packaging\create_shortcuts.ps1

Not covered here on purpose: launching this app at Windows startup/login.
Georgio asked for a double-click desktop icon specifically, not an
auto-launching background app -- if that changes later, that's a
Startup-folder shortcut (or a Scheduled Task) added the same way, not a
change to how the app itself runs.
#>

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ExePath = Join-Path $ProjectRoot "dist\IDL_App\IDL_App.exe"
$WorkingDir = Join-Path $ProjectRoot "dist\IDL_App"

if (-not (Test-Path $ExePath)) {
    Write-Host "IDL_App.exe not found at $ExePath"
    Write-Host "Run packaging\build_installer.bat first to build it, then re-run this script."
    exit 1
}

$WshShell = New-Object -ComObject WScript.Shell

function New-AppShortcut([string]$ShortcutPath) {
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $ExePath
    $Shortcut.WorkingDirectory = $WorkingDir
    # Pulls the icon baked into IDL_App.exe itself (the PyInstaller
    # default unless idl_app.spec's EXE(icon=...) is set to a custom
    # .ico later) rather than requiring a separate icon file to ship.
    $Shortcut.IconLocation = $ExePath
    $Shortcut.Description = "IDL Auto-fill App"
    $Shortcut.Save()
}

$DesktopPath = [Environment]::GetFolderPath("Desktop")
$StartMenuPath = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"

New-AppShortcut (Join-Path $DesktopPath "IDL App.lnk")
New-AppShortcut (Join-Path $StartMenuPath "IDL App.lnk")

Write-Host ""
Write-Host "Shortcuts created:"
Write-Host "  Desktop:    $DesktopPath\IDL App.lnk"
Write-Host "  Start Menu: $StartMenuPath\IDL App.lnk"
Write-Host ""
Write-Host "Double-click either one to launch the app -- no terminal needed from now on."
