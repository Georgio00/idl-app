"""
Checks a OneDrive-hosted update manifest for a version of the app newer
than the one currently running -- see updater/onedrive.py for how that
manifest is actually fetched without any embedded credential, and
README.md's "Publishing an update" section for how Georgio publishes one.

check_for_update() is designed to NEVER raise and NEVER block the app
for more than `timeout` seconds: no internet, an expired share link, a
malformed manifest, or OneDrive simply being down should all just mean
"no update found right now" -- the same way one low-confidence OCR field
doesn't crash the whole Autofill run elsewhere in this app, this feature
must never be the reason staff think the app itself is broken.
"""

from __future__ import annotations

import json
import logging
from typing import NamedTuple, Optional

from updater.onedrive import OneDriveDownloadError, fetch_onedrive_share_text
from updater.version import is_newer

logger = logging.getLogger("idl_app.updater")

# The ONE fixed, permanent link Georgio sets up once: a OneDrive "Anyone
# with the link can view" share of a single small version.json file that
# he overwrites in place (re-uploads over the same file -- not deleted
# and re-shared, which would change the link) each time he publishes a
# new version. Empty by default: the update check silently does nothing
# until this is actually configured, so a build with no manifest set up
# yet behaves exactly as if this feature doesn't exist, rather than
# erroring on every launch. Set this once real link is created -- see
# README.md's "Publishing an update" section.
#
# 2026-09-11: set to the real, permanent share link for
# OneDrive/"IDL App Updates"/version.json ("Anyone with the link" /
# "Can view"), created live via screen control on Georgio's PC. The
# version.json file itself is still EMPTY at this point (0 KB) -- it
# will be filled in with real {"version", "download_share_url",
# "sha256", "notes"} JSON the first time Georgio actually publishes an
# update (see README.md's "Publishing an update" section). Until then,
# check_for_update() fetches empty text, parse_update_manifest() raises
# ManifestError (invalid JSON), and check_for_update() catches that and
# returns None per its module docstring -- so shipping this URL now,
# before there's anything to update to, is safe: the app just silently
# finds no update, exactly as if the feature weren't configured yet.
# Still NOT verified end-to-end against a real download (see
# updater/__init__.py) -- this sandbox has no network path to
# api.onedrive.com to test the fetch itself (outbound proxy blocks that
# host entirely), only a real Windows run can confirm it.
UPDATE_MANIFEST_URL = "https://1drv.ms/u/c/d4f489e11d6fefb6/IQBKXifcfde-SL7ENakcThOKAblQmMhfFhgQNcOZchaS8sM?e=4PJime"


class UpdateManifest(NamedTuple):
    version: str
    download_share_url: str
    sha256: str
    notes: str


class ManifestError(RuntimeError):
    """The manifest was fetched but isn't valid JSON, or is missing a
    required field."""


def parse_update_manifest(raw_json: str) -> UpdateManifest:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise ManifestError(f"Update manifest is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ManifestError("Update manifest JSON must be an object")

    missing = [k for k in ("version", "download_share_url", "sha256") if k not in data]
    if missing:
        raise ManifestError(f"Update manifest is missing required field(s): {', '.join(missing)}")

    return UpdateManifest(
        version=str(data["version"]),
        download_share_url=str(data["download_share_url"]),
        sha256=str(data["sha256"]),
        notes=str(data.get("notes", "")),
    )


def check_for_update(
    current_version: str,
    manifest_url: str = UPDATE_MANIFEST_URL,
    timeout: float = 5.0,
) -> Optional[UpdateManifest]:
    """Returns the manifest if it describes a version newer than
    current_version, else None -- including when the check itself fails
    for any reason at all (see module docstring: this must never raise
    or meaningfully block app startup)."""
    if not manifest_url:
        return None
    try:
        raw = fetch_onedrive_share_text(manifest_url, timeout=timeout)
        manifest = parse_update_manifest(raw)
    except (OneDriveDownloadError, ManifestError) as e:
        logger.info("Update check skipped: %s", e)
        return None
    except Exception as e:  # noqa: BLE001 - never let an update check crash the app
        logger.info("Update check skipped due to an unexpected error: %s", e)
        return None

    try:
        newer = is_newer(manifest.version, current_version)
    except ValueError as e:
        logger.info("Update check skipped: manifest version is malformed (%s)", e)
        return None

    return manifest if newer else None
