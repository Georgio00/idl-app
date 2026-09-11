"""
Regression tests for updater/apply_update.py (added 2026-09-11).

Real zip files and real temp directories are used throughout (not
mocked) for the extraction/hashing/staging logic, since that's ordinary
Python file handling that runs identically on this Linux sandbox as it
would on the real Windows target -- only the OneDrive download and the
final subprocess.Popen (launching the generated Windows batch script)
are mocked, since those genuinely can't run here. See
updater/apply_update.py's module docstring for what is and isn't
verified by this file.
"""

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from updater.onedrive import OneDriveDownloadError
from updater.update_checker import UpdateManifest
from updater.apply_update import (
    UpdateApplyError,
    apply_update_and_restart,
    build_swap_script,
    download_and_verify,
    extract_to_staging,
)


def _make_manifest(sha256: str, download_share_url: str = "https://1drv.ms/x") -> UpdateManifest:
    return UpdateManifest(version="9.9.9", download_share_url=download_share_url, sha256=sha256, notes="")


class DownloadAndVerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.dest = self.tmp_dir / "update.zip"

    def test_accepts_a_download_matching_its_hash(self):
        content = b"fake zip bytes"

        def fake_download(share_url, dest_path):
            Path(dest_path).write_bytes(content)

        import hashlib
        real_hash = hashlib.sha256(content).hexdigest()
        manifest = _make_manifest(sha256=real_hash)

        with mock.patch("updater.apply_update.download_onedrive_share", side_effect=fake_download):
            download_and_verify(manifest, self.dest)

        self.assertEqual(self.dest.read_bytes(), content)

    def test_rejects_a_download_with_the_wrong_hash(self):
        def fake_download(share_url, dest_path):
            Path(dest_path).write_bytes(b"actual content")

        manifest = _make_manifest(sha256="0" * 64)  # deliberately wrong

        with mock.patch("updater.apply_update.download_onedrive_share", side_effect=fake_download):
            with self.assertRaises(UpdateApplyError):
                download_and_verify(manifest, self.dest)

        self.assertFalse(self.dest.exists(), "the bad download should be removed, not left behind")

    def test_hash_comparison_is_case_insensitive(self):
        content = b"fake zip bytes"
        import hashlib
        real_hash_upper = hashlib.sha256(content).hexdigest().upper()

        def fake_download(share_url, dest_path):
            Path(dest_path).write_bytes(content)

        manifest = _make_manifest(sha256=real_hash_upper)
        with mock.patch("updater.apply_update.download_onedrive_share", side_effect=fake_download):
            download_and_verify(manifest, self.dest)  # should not raise

    def test_download_failure_raises_update_apply_error(self):
        manifest = _make_manifest(sha256="irrelevant")
        with mock.patch(
            "updater.apply_update.download_onedrive_share",
            side_effect=OneDriveDownloadError("no internet"),
        ):
            with self.assertRaises(UpdateApplyError):
                download_and_verify(manifest, self.dest)


class ExtractToStagingTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def _make_zip(self, entries: dict) -> Path:
        zip_path = self.tmp_dir / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for name, content in entries.items():
                zf.writestr(name, content)
        return zip_path

    def test_extracts_files_with_correct_content(self):
        zip_path = self._make_zip({
            "IDL_App/IDL_App.exe": b"fake exe bytes",
            "IDL_App/_internal/sqlite3.dll": b"fake dll bytes",
        })
        staging_dir = self.tmp_dir / "staged"

        extract_to_staging(zip_path, staging_dir)

        self.assertEqual((staging_dir / "IDL_App" / "IDL_App.exe").read_bytes(), b"fake exe bytes")
        self.assertEqual(
            (staging_dir / "IDL_App" / "_internal" / "sqlite3.dll").read_bytes(), b"fake dll bytes"
        )

    def test_refuses_to_extract_into_an_existing_staging_dir(self):
        zip_path = self._make_zip({"a.txt": b"x"})
        staging_dir = self.tmp_dir / "already_here"
        staging_dir.mkdir()

        with self.assertRaises(UpdateApplyError):
            extract_to_staging(zip_path, staging_dir)

    def test_bad_zip_file_raises_update_apply_error(self):
        not_a_zip = self.tmp_dir / "not_a_zip.zip"
        not_a_zip.write_bytes(b"this is not a zip file")
        staging_dir = self.tmp_dir / "staged"

        with self.assertRaises(UpdateApplyError):
            extract_to_staging(not_a_zip, staging_dir)

    def test_refuses_a_path_traversal_entry(self):
        # A "zip-slip" attempt: an entry whose name climbs out of the
        # intended extraction directory. Modern zipfile partially guards
        # against this itself, but apply_update.py adds its own explicit
        # check (see _safe_extract_all) rather than depending on exactly
        # which stdlib version's mitigation is in effect.
        zip_path = self.tmp_dir / "evil.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../../evil.txt", b"pwned")
        staging_dir = self.tmp_dir / "staged_evil"

        with self.assertRaises(UpdateApplyError):
            extract_to_staging(zip_path, staging_dir)

        # Nothing should have escaped to the parent directories.
        self.assertFalse((self.tmp_dir.parent.parent / "evil.txt").exists())


class BuildSwapScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def test_script_references_all_the_right_paths(self):
        install_dir = self.tmp_dir / "IDL_App"
        staged_dir = self.tmp_dir / "staged" / "IDL_App"
        script_path = self.tmp_dir / "apply_update.bat"

        script_text = build_swap_script(install_dir, staged_dir, "IDL_App.exe", script_path)

        self.assertIn(str(install_dir), script_text)
        self.assertIn(str(staged_dir), script_text)
        self.assertIn("IDL_App.exe", script_text)
        self.assertIn("move", script_text.lower())
        self.assertIn("start", script_text.lower())
        self.assertTrue(script_path.exists())
        # Compare raw bytes, not read_text() -- text-mode reading applies
        # universal-newline translation (collapsing the script's
        # deliberate \r\n line endings to \n), which would make this
        # comparison fail for a reason that has nothing to do with
        # whether the file's actual content is correct.
        self.assertEqual(script_path.read_bytes().decode("utf-8"), script_text)

    def test_script_deletes_itself_at_the_end(self):
        script_text = build_swap_script(
            self.tmp_dir / "IDL_App", self.tmp_dir / "staged", "IDL_App.exe", self.tmp_dir / "apply.bat"
        )
        self.assertIn("del \"%~f0\"", script_text)


class ApplyUpdateAndRestartTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.install_dir = self.tmp_dir / "IDL_App"
        self.install_dir.mkdir()
        (self.install_dir / "IDL_App.exe").write_bytes(b"old exe")

    def _make_update_zip(self) -> tuple[Path, str]:
        import hashlib
        zip_bytes_path = self.tmp_dir / "source_update.zip"
        with zipfile.ZipFile(zip_bytes_path, "w") as zf:
            # Wrapped in a single top-level "IDL_App" folder, matching
            # what "Compress to ZIP file" on the IDL_App folder itself
            # produces -- see _resolve_app_root's docstring.
            zf.writestr("IDL_App/IDL_App.exe", b"new exe bytes")
            zf.writestr("IDL_App/_internal/sqlite3.dll", b"new dll bytes")
        digest = hashlib.sha256(zip_bytes_path.read_bytes()).hexdigest()
        return zip_bytes_path, digest

    def test_full_pipeline_stages_the_update_and_launches_the_swap_script(self):
        source_zip, digest = self._make_update_zip()
        manifest = _make_manifest(sha256=digest)

        def fake_download(share_url, dest_path):
            Path(dest_path).write_bytes(source_zip.read_bytes())

        with mock.patch("updater.apply_update.download_onedrive_share", side_effect=fake_download), \
             mock.patch("subprocess.Popen") as popen_mock:
            apply_update_and_restart(manifest, self.install_dir, "IDL_App.exe")

        popen_mock.assert_called_once()
        launched_command = popen_mock.call_args.args[0]
        self.assertEqual(launched_command[0], "cmd")
        script_path = Path(launched_command[2])
        self.assertTrue(script_path.exists())

        script_text = script_path.read_text(encoding="utf-8")
        # The single top-level "IDL_App" folder inside the zip should have
        # been unwrapped, so the swap script's staged path points at the
        # folder that directly CONTAINS IDL_App.exe, not one level above it.
        self.assertIn(str(script_path.parent / "staged" / "IDL_App"), script_text)
        self.assertIn(str(self.install_dir), script_text)

    def test_hash_mismatch_prevents_any_swap_script_from_being_launched(self):
        source_zip, _real_digest = self._make_update_zip()
        manifest = _make_manifest(sha256="0" * 64)  # wrong on purpose

        def fake_download(share_url, dest_path):
            Path(dest_path).write_bytes(source_zip.read_bytes())

        with mock.patch("updater.apply_update.download_onedrive_share", side_effect=fake_download), \
             mock.patch("subprocess.Popen") as popen_mock:
            with self.assertRaises(UpdateApplyError):
                apply_update_and_restart(manifest, self.install_dir, "IDL_App.exe")

        popen_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
