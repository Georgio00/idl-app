"""
The app's own version number, and simple version-string comparison used
by the update checker (updater/update_checker.py) to decide whether a
published manifest describes a newer release than what's currently
running.

CURRENT_VERSION is bumped BY HAND as part of publishing a new update --
see README.md's "Publishing an update" section. Nothing reads it
automatically from git tags, commit counts, or similar; keeping it a
single plain constant means there is exactly one place to remember to
change per release, at the cost of it being possible to forget. If a
staff-facing "what version am I running" need ever comes up, this is the
value to surface (e.g. in a Help/About dialog) -- not duplicated
anywhere else.
"""

from __future__ import annotations

CURRENT_VERSION = "1.0.0"


def parse_version(version_string: str) -> tuple[int, ...]:
    """Parses a plain "X.Y.Z" (or "X.Y", or "X") version string into a
    tuple of ints for comparison. Deliberately simple -- no pre-release
    suffixes ("-beta"), no build metadata, no leading "v" -- every
    release of this internal tool is just a plain number Georgio
    increments by hand, not a package published to a registry with
    pre-release conventions to support. Raises ValueError on anything
    else, including empty strings and non-numeric parts, so a malformed
    manifest fails loudly during update_checker's manifest parsing
    rather than comparing in some undefined way."""
    version_string = version_string.strip()
    if not version_string:
        raise ValueError("Version string is empty")
    parts = version_string.split(".")
    if not all(p.isdigit() for p in parts):
        raise ValueError(f"Not a plain X.Y.Z version string: {version_string!r}")
    return tuple(int(p) for p in parts)


def is_newer(candidate_version: str, current_version: str) -> bool:
    """True if candidate_version is a strictly newer version than
    current_version. Version strings of different lengths are zero-
    padded for the comparison, so "1.2" == "1.2.0" and "2" > "1.9.9"."""
    candidate = parse_version(candidate_version)
    current = parse_version(current_version)
    length = max(len(candidate), len(current))
    candidate = candidate + (0,) * (length - len(candidate))
    current = current + (0,) * (length - len(current))
    return candidate > current
