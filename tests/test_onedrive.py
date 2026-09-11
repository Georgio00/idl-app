"""
Regression tests for updater/onedrive.py (added 2026-09-11).

Covers the URL-encoding transform (a pure string computation, checked
against a value worked out by hand so a future refactor can't silently
change the encoding without a test noticing) and the download/fetch/hash
logic against a mocked requests.get -- there is no real OneDrive account
reachable from this sandbox, so the actual Microsoft Graph "shares" API
behavior is NOT exercised here. See updater/onedrive.py's module
docstring.
"""

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from updater.onedrive import (
    OneDriveDownloadError,
    download_onedrive_share,
    fetch_onedrive_share_text,
    onedrive_content_api_url,
    sha256_of_file,
)


class OnedriveContentApiUrlTest(unittest.TestCase):
    def test_matches_a_hand_computed_encoding(self):
        share_url = "https://1drv.ms/u/s!AhExampleShareLink"
        expected_encoded = base64.urlsafe_b64encode(share_url.encode("utf-8")).decode("ascii").rstrip("=")
        expected = f"https://api.onedrive.com/v1.0/shares/u!{expected_encoded}/root/content"

        self.assertEqual(onedrive_content_api_url(share_url), expected)

    def test_strips_surrounding_whitespace_before_encoding(self):
        self.assertEqual(
            onedrive_content_api_url("  https://1drv.ms/u/s!Abc  "),
            onedrive_content_api_url("https://1drv.ms/u/s!Abc"),
        )

    def test_result_has_no_padding_characters(self):
        # "=" is not URL-safe unescaped; Microsoft's documented scheme
        # strips it, so a "=" here would mean this is silently wrong.
        self.assertNotIn("=", onedrive_content_api_url("https://1drv.ms/u/s!x"))


class DownloadOnedriveShareTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def test_writes_streamed_content_to_dest_path(self):
        fake_response = mock.Mock()
        fake_response.raise_for_status = mock.Mock()
        fake_response.iter_content = mock.Mock(return_value=[b"hello ", b"world"])

        dest = self.tmp_dir / "out.bin"
        with mock.patch("requests.get", return_value=fake_response) as get_mock:
            download_onedrive_share("https://1drv.ms/u/s!x", dest)

        self.assertEqual(dest.read_bytes(), b"hello world")
        self.assertTrue(get_mock.call_args.kwargs.get("stream"))

    def test_creates_parent_directories(self):
        fake_response = mock.Mock()
        fake_response.raise_for_status = mock.Mock()
        fake_response.iter_content = mock.Mock(return_value=[b"data"])

        dest = self.tmp_dir / "nested" / "deeper" / "out.bin"
        with mock.patch("requests.get", return_value=fake_response):
            download_onedrive_share("https://1drv.ms/u/s!x", dest)

        self.assertTrue(dest.exists())

    def test_network_failure_raises_onedrive_download_error(self):
        with mock.patch("requests.get", side_effect=requests.ConnectionError("no network")):
            with self.assertRaises(OneDriveDownloadError):
                download_onedrive_share("https://1drv.ms/u/s!x", self.tmp_dir / "out.bin")

    def test_http_error_status_raises_onedrive_download_error(self):
        fake_response = mock.Mock()
        fake_response.raise_for_status = mock.Mock(side_effect=requests.HTTPError("404"))
        with mock.patch("requests.get", return_value=fake_response):
            with self.assertRaises(OneDriveDownloadError):
                download_onedrive_share("https://1drv.ms/u/s!x", self.tmp_dir / "out.bin")


class FetchOnedriveShareTextTest(unittest.TestCase):
    def test_returns_response_text(self):
        fake_response = mock.Mock()
        fake_response.raise_for_status = mock.Mock()
        fake_response.text = '{"version": "1.2.3"}'
        with mock.patch("requests.get", return_value=fake_response):
            self.assertEqual(fetch_onedrive_share_text("https://1drv.ms/u/s!x"), '{"version": "1.2.3"}')

    def test_network_failure_raises_onedrive_download_error(self):
        with mock.patch("requests.get", side_effect=requests.Timeout("slow")):
            with self.assertRaises(OneDriveDownloadError):
                fetch_onedrive_share_text("https://1drv.ms/u/s!x")


class Sha256OfFileTest(unittest.TestCase):
    def test_matches_hashlib_computed_directly(self):
        import hashlib

        tmp_dir = Path(tempfile.mkdtemp())
        path = tmp_dir / "known.txt"
        path.write_bytes(b"hello world")

        expected = hashlib.sha256(b"hello world").hexdigest()
        self.assertEqual(sha256_of_file(path), expected)

    def test_matches_the_well_known_test_vector_for_hello_world(self):
        tmp_dir = Path(tempfile.mkdtemp())
        path = tmp_dir / "known.txt"
        path.write_bytes(b"hello world")

        self.assertEqual(
            sha256_of_file(path),
            "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
        )

    def test_different_content_gives_different_digest(self):
        tmp_dir = Path(tempfile.mkdtemp())
        path_a = tmp_dir / "a.txt"
        path_b = tmp_dir / "b.txt"
        path_a.write_bytes(b"content a")
        path_b.write_bytes(b"content b")

        self.assertNotEqual(sha256_of_file(path_a), sha256_of_file(path_b))


if __name__ == "__main__":
    unittest.main()
