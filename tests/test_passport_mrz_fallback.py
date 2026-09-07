"""
Regression tests for the 2026-08-30 (third fix, same day) MRZ fallback:
extract_passport_data used to trust _crop_mrz_band's fixed bottom-24.5%
crop unconditionally -- on a real two-page-spread passport photo (Rana
Rayess) the actual MRZ sits at roughly 58-61% down the frame, entirely
outside that band, so the fixed crop never contained it and Surname/First
Name/DOB failed outright with no fallback. _try_locate_mrz +
extract_passport_data now try the fixed band first (fast, still correct
for a normally-framed single bio-page photo) and fall back to scanning the
*whole* photo only if that comes up empty -- see passport_ocr.py's module
docstring for the full diagnosis.

Mocks ocr.passport_ocr.ocr_image_array directly (same pattern as
tests/test_pipeline_source_priority.py) rather than building real images
with real MRZ text baked in -- what's under test is the call sequence and
fallback wiring, not OCR accuracy itself (that's _extract_mrz_lines'
job, already covered elsewhere).

2026-09-06: call order and count updated for later fixes to
extract_passport_data:
- MRZ resolution now happens BEFORE bio-page extraction (not after), so a
  whole-photo rotation discovered while resolving the MRZ can be used for
  bio-page extraction too -- see ocr/passport_ocr.py's docstring and
  _try_locate_mrz_with_rotation. The fakes below now return the MRZ-band
  response on call 1 and the bio-search-region response on the LAST call,
  rather than the other way around.
- When both the fixed band AND the whole photo come back with nothing
  MRZ-shaped, three more whole-photo attempts are now made (at 90 degrees
  clockwise, 180, and 90 degrees counter-clockwise) before giving up -- see
  _ROTATION_ATTEMPTS -- so BothTiersFailTest now expects extra calls for
  those before its bio-region call.
- Bio-page extraction now independently checks whether its own crop's words
  look physically rotated (_looks_rotated_90) before trusting it (see
  _resolve_bio_words) -- if they do, up to two more OCR calls are spent
  trying 90-degree rotations before giving up. The bio-region fakes below
  use plain wide-short word boxes (not narrow-tall ones) so this module's
  tests (which are about MRZ-tier behavior, not the bio-rotation fix -- see
  tests/test_passport_rotation_fallback.py for that) don't trip this extra
  probing and can keep their call counts simple.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.ocr_client import OcrResult, OcrWord
from ocr.passport_ocr import extract_passport_data

_REAL_MRZ_TEXT = (
    "P<LBNEL<ALAM<<GEORGES<<<<<<<<<<<<<<<<<<<<<<\n"
    "LR18962688LBN9109076M3009211100145810 6<<20"
)
# extract_passport_data normalizes raw MRZ lines to exactly 44 chars
# (left-justified, "<"-padded -- see _normalize_mrz_line) before returning
# them as raw_line1/raw_line2, so the expected values here are that
# normalized form, not the raw literal above.
_EXPECTED_LINE1 = "P<LBNEL<ALAM<<GEORGES<<<<<<<<<<<<<<<<<<<<<<".ljust(44, "<")[:44]

# Plain wide-short word boxes (not narrow-tall) so _resolve_bio_words'
# _looks_rotated_90 check (see ocr/passport_ocr.py and this module's
# 2026-09-06 docstring entry) doesn't kick in and add extra calls this
# suite isn't testing for -- that mechanism has its own dedicated coverage
# in tests/test_passport_rotation_fallback.py.
_NO_BIO_WORDS = OcrResult(
    full_text="Republic of Lebanon",
    words=[
        OcrWord("Republic", 0.9, (10, 10, 60, 25)),
        OcrWord("of", 0.9, (65, 10, 80, 25)),
        OcrWord("Lebanon", 0.9, (85, 10, 140, 25)),
    ],
)


def _blank_image_file(tmp_path: Path) -> str:
    img = np.zeros((1600, 900, 3), dtype="uint8")
    p = tmp_path / "passport.png"
    cv2.imwrite(str(p), img)
    return str(p)


class FixedBandSucceedsTest(unittest.TestCase):
    """The common case: a normally-framed photo where the fast, narrow
    band already contains the MRZ -- must NOT fall back to the (slower,
    noisier) whole-photo scan when it doesn't need to."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.image_path = _blank_image_file(self.tmp_dir)
        self.call_count = 0

    def _fake_ocr(self, image, language_hints=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            return OcrResult(full_text=_REAL_MRZ_TEXT, words=[OcrWord("X", 0.9, (0, 0, 10, 10))])
        return _NO_BIO_WORDS  # bio-data-page call

    def test_only_two_ocr_calls_made(self):
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_ocr):
            result = extract_passport_data(self.image_path)
        self.assertEqual(self.call_count, 2)  # fixed MRZ band (no fallback needed) + bio region
        self.assertIsNotNone(result.mrz)
        self.assertEqual(result.raw_line1, _EXPECTED_LINE1)


class WholePhotoFallbackTest(unittest.TestCase):
    """The photo-framing case that exposed this bug: the fixed band comes
    back with no MRZ-shaped lines, so the whole photo must be tried next,
    and a real MRZ found there must be used."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.image_path = _blank_image_file(self.tmp_dir)
        self.call_count = 0

    def _fake_ocr(self, image, language_hints=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            # Fixed band: nothing MRZ-shaped in it (e.g. the MRZ was
            # framed outside this band on this photo).
            return OcrResult(full_text="RANDOM UNRELATED TEXT", words=[])
        if self.call_count == 2:
            # Whole-photo fallback: the real MRZ, found this time.
            return OcrResult(full_text=_REAL_MRZ_TEXT, words=[OcrWord("X", 0.9, (0, 0, 10, 10))])
        return _NO_BIO_WORDS  # bio-data-page call

    def test_falls_back_to_whole_photo_and_recovers_mrz(self):
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_ocr):
            result = extract_passport_data(self.image_path)
        self.assertEqual(self.call_count, 3)  # band (failed) + whole photo + bio region
        self.assertIsNotNone(result.mrz)
        self.assertEqual(result.raw_line1, _EXPECTED_LINE1)
        self.assertIsNone(result.error)


class BothTiersFailTest(unittest.TestCase):
    """Neither the fixed band, the whole photo, nor any of the three
    rotation probes contain anything MRZ-shaped -- must fail with the
    existing descriptive error, not silently or with a confusing one, and
    bio-data-page fields (extracted independently, after MRZ resolution
    gives up) must still come through."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.image_path = _blank_image_file(self.tmp_dir)
        self.call_count = 0

    def _fake_ocr(self, image, language_hints=None, **kwargs):
        self.call_count += 1
        # Calls 1-5: every MRZ attempt (fixed band, whole photo, then the
        # three rotation probes -- see _ROTATION_ATTEMPTS) comes back with
        # nothing MRZ-shaped. Call 6: the bio-search-region, tried after
        # MRZ resolution gives up entirely, finds Father's Name -- these
        # words' wide-short boxes don't look rotated (_looks_rotated_90),
        # so _resolve_bio_words trusts this crop as-is with no further
        # calls.
        if self.call_count <= 5:
            return OcrResult(full_text="RANDOM UNRELATED TEXT", words=[])
        return OcrResult(
            full_text="Father name\nSAEED",
            words=[
                OcrWord("Father", 0.9, (50, 100, 90, 112)),
                OcrWord("name", 0.9, (92, 100, 120, 112)),
                OcrWord("SAEED", 0.9, (50, 130, 100, 143)),
            ],
        )

    def test_reports_error_but_keeps_bio_fields(self):
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_ocr):
            result = extract_passport_data(self.image_path)
        self.assertEqual(self.call_count, 6)
        self.assertIsNone(result.mrz)
        self.assertIsNotNone(result.error)
        self.assertIn("Could not locate two MRZ lines", result.error)
        self.assertEqual(result.father_name.value, "SAEED")


if __name__ == "__main__":
    unittest.main()
