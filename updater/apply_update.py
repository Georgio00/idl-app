"""
Downloads, verifies, and installs an update described by an
UpdateManifest (see updater/update_checker.py), then relaunches the app.

The tricky part: a running Windows .exe cannot safely overwrite its own
DLLs while they are loaded (see IDL_App.exe's _internal\\*.dll -- these
are memory-mapped into the running process the whole time it's open).
The standard way around this is to never overwrite anything live from
inside the running app at all: extract the new version to a separate
staging folder first (completely safe -- nothing live is touched), then
hand off to a small generated batch script that waits for THIS process
to fully exit, swaps the folders, and relaunches the new .exe -- by
which point the old .exe's files are no longer open by anything. The
running app's only job is to kick that script off as a detached process
(so it survives after this process exits) and then quit.

NOT YET VERIFIED end-to-end on a real Windows machine -- this project is
built and tested from a Linux sandbox (see packaging/idl_app.spec's own
header comment for why nothing Windows-native can be run from here).
tests/test_apply_update.py covers everything that doesn't require
Windows itself: hash verification, safe zip extraction (including a
zip-slip / path-traversal attempt), and the exact generated swap script.
Georgio: please run one full update cycle on THIS laptop (bump
CURRENT_VERSION, publish it per README.md's "Publishing an update"
section, and let a locally-running build update itself) before trusting
this against a company machine with real work in progress.
"""

from __future__ import annotations

import subprocess
import tempfile
import zipfile
from pathlib import Path

from updater.onedrive import OneDriveDownloadError, download_onedrive_share, sha256_of_file
from updater.update_checker import UpdateManifest

# Windows-only subprocess flags -- referencing subprocess.DETACHED_PROCESS
# directly would raise AttributeError when this module is merely
# imported/tested on a non-Windows machine (this whole project is
# developed from a Linux sandbox). Falls back to 0 (no special flags)
# anywhere else, which only ever matters for running this module's tests.
_DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


class UpdateApplyError(RuntimeError):
    """Covers every way applying a downloaded update can fail: the
    download itself, a hash mismatch (corrupted or tampered download),
    or an unreadable/unsafe zip -- all raised before anything belonging
    to the currently-running, working install is touched."""


def download_and_verify(manifest: UpdateManifest, dest_zip_path: Path) -> None:
    """Downloads the update zip and checks it against the manifest's
    sha256. Catches a partial/corrupted download -- a real risk over a
    plain HTTPS GET with no resume support for a multi-megabyte file --
    and, to whatever extent a hash hosted next to the file it describes
    can, a tampered one. Raises UpdateApplyError rather than proceeding
    on any mismatch, and removes the bad file rather than leaving it
    around to be mistaken for a good download later."""
    dest_zip_path = Path(dest_zip_path)
    try:
        download_onedrive_share(manifest.download_share_url, dest_zip_path)
    except OneDriveDownloadError as e:
        raise UpdateApplyError(f"Could not download the update: {e}") from e

    actual_hash = sha256_of_file(dest_zip_path)
    if actual_hash.lower() != manifest.sha256.strip().lower():
        dest_zip_path.unlink(missing_ok=True)
        raise UpdateApplyError(
            "Downloaded update failed its integrity check (sha256 mismatch) -- "
            "the download may have been interrupted or corrupted. Not installing it."
        )


def _safe_extract_all(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    """zipfile.extractall() historically could be tricked by a malicious
    zip entry's own path (e.g. "../../whatever", a "zip-slip" attack)
    into writing outside dest_dir; modern CPython mitigates the worst of
    this but it's cheap and worth doing explicitly ourselves rather than
    depending on exactly which stdlib version is running -- refuse ANY
    entry whose resolved path would land outside dest_dir before
    extracting anything at all, rather than trusting a zip that ultimately
    arrived over a plain link with no code signing."""
    dest_dir = dest_dir.resolve()
    for member in zf.infolist():
        member_path = (dest_dir / member.filename).resolve()
        if member_path != dest_dir and dest_dir not in member_path.parents:
            raise UpdateApplyError(
                f"Refusing to extract update: unsafe path in zip entry {member.filename!r}"
            )
    zf.extractall(dest_dir)


def extract_to_staging(zip_path: Path, staging_dir: Path) -> None:
    """Extracts the update zip into staging_dir, which must not already
    exist. This never touches the live install -- a failure here (a
    corrupt zip, a full disk, an unsafe path inside the zip) leaves the
    currently-running app completely untouched and still working."""
    zip_path = Path(zip_path)
    staging_dir = Path(staging_dir)
    if staging_dir.exists():
        raise UpdateApplyError(f"Staging folder already exists: {staging_dir}")

    staging_dir.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract_all(zf, staging_dir)
    except zipfile.BadZipFile as e:
        raise UpdateApplyError(f"Downloaded update is not a valid zip file: {e}") from e


def _resolve_app_root(staging_dir: Path) -> Path:
    """If the zip's contents are a single top-level folder (e.g.
    IDL_App\\..., matching what right-click -> "Compress to ZIP file" on
    the IDL_App folder itself produces -- see README.md's "Publishing an
    update" section for how Georgio is expected to build the zip), use
    that folder's contents directly rather than nesting the app one
    level deeper than the install directory expects. Otherwise assumes
    the zip's top level already IS the app folder's contents."""
    entries = list(staging_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return staging_dir


def build_swap_script(install_dir: Path, staged_app_dir: Path, exe_name: str, script_path: Path) -> str:
    """Writes (and returns the text of) a batch script that: waits a
    moment for this process to fully release its files after exiting,
    moves the current install out of the way, moves the staged new
    version into its place, relaunches the new .exe, then cleans up the
    old version and deletes itself. Runs as a separate, detached process
    precisely because the currently-running .exe cannot safely replace
    its own open files -- see this module's docstring."""
    install_dir = Path(install_dir)
    staged_app_dir = Path(staged_app_dir)
    old_backup_dir = install_dir.parent / f"{install_dir.name}_old_update"

    script = (
        "@echo off\r\n"
        "REM Auto-generated by updater/apply_update.py -- swaps in a new\r\n"
        "REM version of the app once the currently-running one has fully\r\n"
        "REM exited, relaunches it, then deletes itself.\r\n"
        "setlocal\r\n"
        f'set "INSTALL_DIR={install_dir}"\r\n'
        f'set "STAGED_DIR={staged_app_dir}"\r\n'
        f'set "OLD_DIR={old_backup_dir}"\r\n'
        f'set "EXE_NAME={exe_name}"\r\n'
        "\r\n"
        "REM Give the app a moment to fully release its files after exiting.\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        "\r\n"
        'if exist "%OLD_DIR%" rmdir /s /q "%OLD_DIR%"\r\n'
        'move "%INSTALL_DIR%" "%OLD_DIR%" >nul\r\n'
        'move "%STAGED_DIR%" "%INSTALL_DIR%" >nul\r\n'
        "\r\n"
        'start "" "%INSTALL_DIR%\\%EXE_NAME%"\r\n'
        "\r\n"
        'rmdir /s /q "%OLD_DIR%"\r\n'
        'del "%~f0"\r\n'
    )
    script_path = Path(script_path)
    script_path.write_text(script, encoding="utf-8")
    return script


def apply_update_and_restart(manifest: UpdateManifest, install_dir: Path, exe_name: str = "IDL_App.exe") -> None:
    """The real entry point, called from the GUI once staff confirm the
    "Update available" prompt. Downloads, verifies, and stages the new
    version, writes the swap script, and launches it detached. The
    caller (gui/new_idl_form.py) is responsible for quitting the app
    right after this returns -- the swap script is waiting for exactly
    that to happen, and won't move anything until this process is gone."""
    work_dir = Path(tempfile.mkdtemp(prefix="idl_app_update_"))
    zip_path = work_dir / "update.zip"
    staging_dir = work_dir / "staged"

    download_and_verify(manifest, zip_path)
    extract_to_staging(zip_path, staging_dir)
    staged_app_dir = _resolve_app_root(staging_dir)

    script_path = work_dir / "apply_update.bat"
    build_swap_script(Path(install_dir), staged_app_dir, exe_name, script_path)

    subprocess.Popen(
        ["cmd", "/c", str(script_path)],
        creationflags=_DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
