"""
Regression tests for the 2026-08-23 passport bio-data-page work:
- _prefer_latin: father_name/place_of_birth are printed on the passport in
  BOTH Arabic and Latin script (see passport_field_regions.py) — the New
  IDL form is Latin-only, so the Arabic portion (and bidi marks) must be
  stripped from the OCR'd text, but a text that's ONLY Arabic (nothing
  else survived stripping) must fall back to the original rather than
  going blank.
- _crop_mrz_band: calibrated 2026-08-23 against a real sample passport —
  the original placeholder (bottom 22%) cut off the tops of the MRZ's
  first line just enough to break OCR; this locks in the corrected 24.5%
  boundary so it doesn't silently drift back.
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.passport_ocr import _crop_mrz_band, _prefer_latin


class PreferLatinTest(unittest.TestCase):
    def test_strips_arabic_leaving_latin(self):
        self.assertEqual(_prefer_latin("سعىد SAID"), "SAID")

    def test_strips_bidi_marks_too(self):
        self.assertEqual(_prefer_latin("SAID‎"), "SAID")

    def test_only_arabic_falls_back_to_original(self):
        # Nothing Latin survives stripping — better to show the raw
        # Arabic read than an empty field.
        arabic_only = "سعيد"
        self.assertEqual(_prefer_latin(arabic_only), arabic_only)

    def test_pure_latin_untouched(self):
        self.assertEqual(_prefer_latin("RMEICH"), "RMEICH")

    def test_collapses_whitespace_left_behind_by_stripping(self):
        self.assertEqual(_prefer_latin("ذ 2   RMEICH"), "2 RMEICH")


class MrzBandCropTest(unittest.TestCase):
    def test_crop_starts_at_calibrated_fraction(self):
        img = np.zeros((1000, 500, 3), dtype="uint8")
        band = _crop_mrz_band(img)
        # 24.5% of 1000 = 755 -> band height should be 1000-755 = 245
        self.assertEqual(band.shape[0], 245)
        self.assertEqual(band.shape[1], 500)


if __name__ == "__main__":
    unittest.main()
