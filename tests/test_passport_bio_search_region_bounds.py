"""
Regression tests for the 2026-09-06 BIO_SEARCH_REGION bottom-edge fix.

Root cause (real photo, Frederic Elias, 921x1203): the real "Place of
birth" label read at full-photo y=716-727 -- right at the old 0.755
boundary's 908px cutoff -- and the actual value ("RMEICH", confirmed
against the raw photo) prints at y=923-948, entirely outside the old crop.
It was never OCR'd at all, so no amount of label/keyword-search fixing in
passport_ocr.py could have found it -- the fix has to be here, in how much
of the page gets captured in the first place.

These tests don't re-run OCR (no image fixtures in this test suite) --
they encode the real pixel measurements pulled from that photo's debug
crop/word dump, plus a second real photo (Rana Rayess) used to confirm the
region can safely overlap _crop_mrz_band's own start, so a future edit to
BIO_SEARCH_REGION's bottom fraction gets caught here if it regresses
either constraint instead of silently reintroducing the bug or the (already
disproven) overlap worry.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.passport_field_regions import BIO_SEARCH_REGION

# Real measurements, Frederic Elias's photo (921x1203), 2026-09-06.
_FREDERIC_PHOTO_HEIGHT = 1203
_FREDERIC_PLACE_OF_BIRTH_VALUE_TOP = 923
_FREDERIC_PLACE_OF_BIRTH_VALUE_BOTTOM = 948
_FREDERIC_MRZ_TOP = 1050

# Real measurement, Rana Rayess's photo (720x1280), 2026-08-30 -- her MRZ
# line already falls inside the pre-fix 0.15-0.755 region (measured at
# roughly y=922-952 of 1280) and caused no corruption, which is the
# evidence this region's bottom edge is safe to extend further in the same
# direction.
_RANA_PHOTO_HEIGHT = 1280
_RANA_MRZ_TOP = 922


class BioSearchRegionBoundsTest(unittest.TestCase):
    def test_region_bottom_clears_the_real_place_of_birth_value_on_frederics_photo(self):
        bottom_px = BIO_SEARCH_REGION[3] * _FREDERIC_PHOTO_HEIGHT
        self.assertGreater(
            bottom_px, _FREDERIC_PLACE_OF_BIRTH_VALUE_BOTTOM,
            "BIO_SEARCH_REGION must extend past the real place-of-birth "
            "value line or it never gets OCR'd at all (the original bug).",
        )

    def test_region_bottom_stays_short_of_frederics_own_mrz_line(self):
        bottom_px = BIO_SEARCH_REGION[3] * _FREDERIC_PHOTO_HEIGHT
        self.assertLess(
            bottom_px, _FREDERIC_MRZ_TOP,
            "Region shouldn't be widened so far it swallows this photo's "
            "own MRZ line outright -- some margin is still worth keeping "
            "even though a partial MRZ overlap has proven harmless.",
        )

    def test_region_top_unchanged(self):
        # Sanity guard: this fix is about the bottom edge only -- the top
        # edge (0.15) has its own, separately-calibrated history.
        self.assertEqual(BIO_SEARCH_REGION[1], 0.15)

    def test_full_width_unchanged(self):
        self.assertEqual(BIO_SEARCH_REGION[0], 0.0)
        self.assertEqual(BIO_SEARCH_REGION[2], 1.0)

    def test_rana_photo_documents_that_mrz_overlap_is_within_the_new_region(self):
        # Not asserting anything about correctness here (that's covered by
        # the existing father_name/place_of_birth tests using Rana's real
        # word dump) -- just pinning down, as a fact, that the widened
        # region can legitimately include a real MRZ line on some photos,
        # so nobody re-adds a "no overlap with the MRZ band" constraint
        # here without re-checking this evidence first.
        bottom_px = BIO_SEARCH_REGION[3] * _RANA_PHOTO_HEIGHT
        self.assertGreater(bottom_px, _RANA_MRZ_TOP)


if __name__ == "__main__":
    unittest.main()
