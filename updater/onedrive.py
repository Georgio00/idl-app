"""
Downloads a file from a OneDrive "anyone with the link" share, without
needing a signed-in Microsoft account or any embedded credential -- this
project deliberately never bakes a live credential into a built .exe
(see packaging/idl_app.spec's docstring re: the Google Cloud Vision
service-account key), and an update channel is no exception. The only
thing this needs is the share link itself, which carries no access to
anything else in Georgio's OneDrive -- just the one shared file/folder.

Uses the Microsoft Graph "shares" API
(https://learn.microsoft.com/en-us/onedrive/developer/rest-api/api/shares_get),
which converts any OneDrive/SharePoint sharing URL into a driveItem --
anonymously, as long as the share itself is set to "Anyone with the link"
-- and serves that item's raw bytes from .../root/content. This is
Microsoft's own documented way to fetch a shared file's content without
authenticating; it is not a scraping trick, though it is also not a
purpose-built file-hosting product, so treat it the way this project
already treats SumatraPDF/Poppler: a real, working dependency that
wasn't built for this exact job and could need revisiting if Microsoft
ever changes how the "shares" API behaves.

NOT YET VERIFIED against a real OneDrive share (no OneDrive account is
reachable from this sandbox) -- tests/test_onedrive.py covers the URL
encoding (a pure string transform, fully testable) and the download/
streaming/hashing logic against a mocked HTTP response, but the very
first real call to a real share link is still an open item. See
README.md's "Publishing an update" section.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import requests


class OneDriveDownloadError(RuntimeError):
    """Raised when a OneDrive share URL can't be resolved or downloaded --
    covers a bad/expired link, no internet, and an HTTP error from the
    Graph API, all under one error type so callers (the update checker)
    can catch a single thing and treat any of them the same way: "could
    not check for an update right now," never a crash."""


def onedrive_content_api_url(share_url: str) -> str:
    """Converts a normal OneDrive "Copy link" share URL into the
    Microsoft Graph API URL that serves that item's raw content,
    following Microsoft's documented encoding: base64url-encode the
    share URL (UTF-8), strip the "=" padding, and prefix with "u!"."""
    encoded = base64.urlsafe_b64encode(share_url.strip().encode("utf-8")).decode("ascii")
    encoded = encoded.rstrip("=")
    return f"https://api.onedrive.com/v1.0/shares/u!{encoded}/root/content"


def download_onedrive_share(share_url: str, dest_path: Path, timeout: float = 30.0) -> None:
    """Downloads the file behind a OneDrive share URL to dest_path,
    streaming so this works for a multi-megabyte app zip without holding
    the whole thing in memory at once."""
    api_url = onedrive_content_api_url(share_url)
    try:
        response = requests.get(api_url, stream=True, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException as e:
        raise OneDriveDownloadError(f"Could not download from OneDrive: {e}") from e

    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
    except OSError as e:
        raise OneDriveDownloadError(f"Could not write downloaded file to {dest_path}: {e}") from e


def fetch_onedrive_share_text(share_url: str, timeout: float = 10.0) -> str:
    """Fetches a small text/JSON file behind a OneDrive share URL
    directly into memory -- used for the update manifest, which is a few
    hundred bytes of JSON and not worth writing to disk first."""
    api_url = onedrive_content_api_url(share_url)
    try:
        response = requests.get(api_url, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException as e:
        raise OneDriveDownloadError(f"Could not fetch from OneDrive: {e}") from e
    return response.text


def sha256_of_file(path: Path) -> str:
    """Hex sha256 digest of a file's contents, computed in chunks so this
    doesn't need to load a multi-megabyte zip into memory at once."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()
