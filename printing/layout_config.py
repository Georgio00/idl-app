"""
Print layout for the one IDP booklet page (and cover page) that gets data
printed on it. Positions are stored as FRACTIONS of the page (0.0-1.0), not
absolute mm/px, per the brief — we don't have exact page dimensions yet, and
percentages stay correct once we do, or if the placeholder size turns out
wrong. PAGE_SIZE_MM is a placeholder (~74x105mm, roughly IDP booklet size)
to use until a blank booklet is measured with a ruler — swap it out once
that measurement exists; the fractions below don't depend on it being right,
only the absolute font/paper scale of the rendered PDF does.

2026-08-27: DEFAULT_DATA_PAGE_LAYOUT below is calibrated directly against a
real sample IDP data page photo Georgio provided (a filled example page —
"ZAMAN" / "AKIL ABED AL WAHED M AKIL" / "SYRIA" / etc. — used only to see
where the pre-printed numbered fields 1-5, the A-E category grid, and the
No./Dated line physically sit, not as real data). Measured the same way as
ocr/passport_field_regions.py: the photo upscaled 2x with a pixel grid
overlaid, each field's value column (excluding the "1"/"2"/... labels
which are presumably part of the blank template itself) read off directly.
Two caveats worth knowing if positions drift on a differently-framed real
page: (1) the photo was taken at a slight angle (not perfectly overhead),
so these fractions are a best-fit axis-aligned approximation of a mildly
trapezoidal page, not a perspective-corrected measurement; (2) the photo's
left edge cut off the physical page's own left edge/spine, so x=0 here is
an approximation of the true page-left, not a confirmed measurement — if
real prints land slightly right of the ruled lines, nudge every x fraction
left a bit first before re-measuring from scratch.

No calibration-screen step is required to use this — these values are the
defaults `load_layout()` falls back to whenever `print_layout.json` (see
below) doesn't exist, so printing works out of the box against this one
template. gui/calibration_screen.py still exists as an optional manual
touch-up tool (drag boxes over a page photo, Save writes `print_layout.json`
which then overrides these defaults) but nothing in the normal print flow
requires running it.
"""

from __future__ import annotations

import json
from pathlib import Path

from db.storage import APP_DATA_DIR

LAYOUT_PATH = APP_DATA_DIR / "print_layout.json"

# Placeholder page size in mm — replace once a blank booklet is measured.
PAGE_SIZE_MM = (74.0, 105.0)
COVER_SIZE_MM = (74.0, 105.0)

# Each entry: (x, y, w, h) as fractions of the page, top-left origin.
# The category grid entries (A/B/C/D/E) are small boxes that get an "X" or
# checkmark drawn in them, not text.
DEFAULT_DATA_PAGE_LAYOUT: dict[str, tuple[float, float, float, float]] = {
    "surname":            (0.161, 0.078, 0.644, 0.037),
    "given_names":        (0.161, 0.127, 0.644, 0.033),
    "nationality":        (0.161, 0.181, 0.241, 0.033),
    "date_of_birth":      (0.161, 0.231, 0.322, 0.035),
    "place_of_birth":     (0.161, 0.275, 0.644, 0.034),
    "permit_number":      (0.310, 0.920, 0.184, 0.038),
    "issue_date":         (0.701, 0.920, 0.259, 0.038),
    "category_A":         (0.184, 0.316, 0.126, 0.092),
    "category_B":         (0.184, 0.408, 0.126, 0.091),
    "category_C":         (0.184, 0.499, 0.126, 0.092),
    "category_D":         (0.184, 0.591, 0.126, 0.091),
    "category_E":         (0.184, 0.682, 0.126, 0.092),
}

DEFAULT_COVER_PAGE_LAYOUT: dict[str, tuple[float, float, float, float]] = {
    "place_of_issue": (0.10, 0.60, 0.80, 0.06),
    "valid_from":     (0.10, 0.68, 0.80, 0.06),
    # signature stays manual/physical — no field here
}


def load_layout() -> dict:
    if LAYOUT_PATH.exists():
        return json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    return {
        "page_size_mm": list(PAGE_SIZE_MM),
        "cover_size_mm": list(COVER_SIZE_MM),
        "data_page": {k: list(v) for k, v in DEFAULT_DATA_PAGE_LAYOUT.items()},
        "cover_page": {k: list(v) for k, v in DEFAULT_COVER_PAGE_LAYOUT.items()},
    }


def save_layout(layout: dict) -> None:
    LAYOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAYOUT_PATH.write_text(json.dumps(layout, indent=2), encoding="utf-8")
