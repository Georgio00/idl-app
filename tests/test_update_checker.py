"""Regression tests for updater/update_checker.py (added 2026-09-11)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from updater.onedrive import OneDriveDownloadError
from updater.update_checker import ManifestError, UpdateManifest, check_for_update, parse_update_manifest


class ParseUpdateManifestTest(unittest.TestCase):
    def test_parses_a_complete_manifest(self):
        raw = (
            '{"version": "1.2.0", "download_share_url": "https://1drv.ms/x", '
            '"sha256": "abc123", "notes": "Fixes the sqlite3 crash"}'
        )
        manifest = parse_update_manifest(raw)
        self.assertEqual(manifest, UpdateManifest(
            version="1.2.0", download_share_url="https://1drv.ms/x",
            sha256="abc123", notes="Fixes the sqlite3 crash",
        ))

    def test_notes_field_is_optional(self):
        raw = '{"version": "1.2.0", "download_share_url": "https://1drv.ms/x", "sha256": "abc123"}'
        manifest = parse_update_manifest(raw)
        self.assertEqual(manifest.notes, "")

    def test_invalid_json_raises_manifest_error(self):
        with self.assertRaises(ManifestError):
            parse_update_manifest("not json at all {{{")

    def test_missing_required_field_raises_manifest_error(self):
        raw = '{"version": "1.2.0", "sha256": "abc123"}'
        with self.assertRaises(ManifestError) as ctx:
            parse_update_manifest(raw)
        self.assertIn("download_share_url", str(ctx.exception))

    def test_non_object_json_raises_manifest_error(self):
        with self.assertRaises(ManifestError):
            parse_update_manifest("[1, 2, 3]")


class CheckForUpdateTest(unittest.TestCase):
    def _manifest_json(self, version="9.9.9"):
        return (
            f'{{"version": "{version}", "download_share_url": "https://1drv.ms/x", '
            '"sha256": "abc123", "notes": ""}'
        )

    def test_returns_none_when_manifest_url_is_not_configured(self):
        # The real default (updater.update_checker.UPDATE_MANIFEST_URL) is
        # "" until Georgio sets up a real OneDrive link -- calling with an
        # explicit empty string exercises that exact "not configured yet"
        # state without needing to monkeypatch the module constant.
        with mock.patch("updater.update_checker.fetch_onedrive_share_text") as fetch_mock:
            result = check_for_update("1.0.0", manifest_url="")
        self.assertIsNone(result)
        fetch_mock.assert_not_called()

    def test_returns_manifest_when_remote_version_is_newer(self):
        with mock.patch(
            "updater.update_checker.fetch_onedrive_share_text",
            return_value=self._manifest_json("2.0.0"),
        ):
            result = check_for_update("1.0.0", manifest_url="https://1drv.ms/manifest")
        self.assertIsNotNone(result)
        self.assertEqual(result.version, "2.0.0")

    def test_returns_none_when_remote_version_is_not_newer(self):
        with mock.patch(
            "updater.update_checker.fetch_onedrive_share_text",
            return_value=self._manifest_json("1.0.0"),
        ):
            result = check_for_update("1.0.0", manifest_url="https://1drv.ms/manifest")
        self.assertIsNone(result)

    def test_returns_none_when_fetch_fails(self):
        with mock.patch(
            "updater.update_checker.fetch_onedrive_share_text",
            side_effect=OneDriveDownloadError("no internet"),
        ):
            result = check_for_update("1.0.0", manifest_url="https://1drv.ms/manifest")
        self.assertIsNone(result)

    def test_returns_none_when_manifest_json_is_malformed(self):
        with mock.patch(
            "updater.update_checker.fetch_onedrive_share_text",
            return_value="not json {{{",
        ):
            result = check_for_update("1.0.0", manifest_url="https://1drv.ms/manifest")
        self.assertIsNone(result)

    def test_returns_none_when_manifest_version_is_malformed(self):
        with mock.patch(
            "updater.update_checker.fetch_onedrive_share_text",
            return_value=self._manifest_json("not-a-version"),
        ):
            result = check_for_update("1.0.0", manifest_url="https://1drv.ms/manifest")
        self.assertIsNone(result)

    def test_never_raises_even_on_a_totally_unexpected_error(self):
        with mock.patch(
            "updater.update_checker.fetch_onedrive_share_text",
            side_effect=RuntimeError("something bizarre"),
        ):
            result = check_for_update("1.0.0", manifest_url="https://1drv.ms/manifest")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
