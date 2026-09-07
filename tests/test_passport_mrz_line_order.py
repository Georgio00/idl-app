"""
Regression tests for the 2026-09-06 (later same day) MRZ line-order fix.

Root cause, found on a fifth real photo (Karim Ayass) -- this one not a
raw camera photo of the physical passport but a phone screenshot of a
PDF-viewer app (CamScanner) displaying it: Surname came back as
"73270LBN0405111M26112841000222809" and First Name as "62", both clearly
fragments of the MRZ's own digit line, not a name. _extract_mrz_lines
assumes OCR's full_text always lists line1 (names) before line2 (digits/
checksums) -- true on every photo seen before this one -- and this photo
broke that assumption, so parse_td3 got the two lines swapped.

LINE1/LINE2 below are the exact real MRZ lines transcribed directly off
this photo (passport_00_full_photo.png, run 20260906_205654) and verified
against the parser itself: parse_td3(LINE1, LINE2) comes back fully
checksum-valid (passport number, DOB, and expiry all check out, and the
parsed DOB/expiry match the photo's own printed dates), which is strong
confirmation the transcription is correct, not just plausible-looking.
Feeding them in swapped through parse_td3 reproduces the exact garbled
production values character-for-character -- confirmed via
test_swapped_order_reproduces_the_exact_reported_bug below -- which is
what actually proves this was the real root cause, not a guess.
"""

import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.mrz_parser import parse_td3
from ocr.ocr_client import OcrResult, OcrWord
from ocr.passport_ocr import _resolve_mrz_line_order, extract_passport_data

# Real data, Karim Ayass's photo, transcribed and checksum-verified (see
# module docstring).
LINE1 = "P<LBNAYASS<<KARIM<<<<<<<<<<<<<<<<<<<<<<<<<<"
LINE2 = "LR24773270LBN0405111M26112841000222809<<<<62"

# The exact garbled values seen in production, reproduced by feeding LINE2
# into parse_td3's line1 parameter (i.e. the swap this fix corrects).
_GARBLED_SURNAME = "73270LBN0405111M26112841000222809"
_GARBLED_GIVEN_NAMES = "62"

_NO_BIO_WORDS = OcrResult(full_text="", words=[])


class SwapReproductionTest(unittest.TestCase):
    """Proves the diagnosis before testing the fix: feeding the two real
    MRZ lines in swapped order produces the *exact* garbled values seen in
    production, not just something vaguely wrong."""

    def test_correct_order_parses_cleanly(self):
        result = parse_td3(LINE1, LINE2)
        self.assertTrue(result.valid)
        self.assertEqual(result.surname, "AYASS")
        self.assertEqual(result.given_names, "KARIM")
        self.assertEqual(result.date_of_birth, "11/05/2004")
        self.assertEqual(result.expiry_date, "28/11/2026")

    def test_swapped_order_reproduces_the_exact_reported_bug(self):
        result = parse_td3(LINE2, LINE1)
        self.assertEqual(result.surname, _GARBLED_SURNAME)
        self.assertEqual(result.given_names, _GARBLED_GIVEN_NAMES)


class ResolveMrzLineOrderTest(unittest.TestCase):
    def test_correct_order_is_left_alone(self):
        self.assertEqual(_resolve_mrz_line_order(LINE1, LINE2), (LINE1, LINE2))

    def test_swapped_order_is_corrected(self):
        self.assertEqual(_resolve_mrz_line_order(LINE2, LINE1), (LINE1, LINE2))

    def test_both_orders_invalid_keeps_the_original(self):
        # No checksum signal either way -- must not "fix" a swap that was
        # never actually there, and must not raise.
        garbage_a = "P<XXXNOTREAL<<NOBODY<<<<<<<<<<<<<<<<<<<<<<<"
        garbage_b = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        self.assertEqual(_resolve_mrz_line_order(garbage_a, garbage_b), (garbage_a, garbage_b))


def _blank_image_file(tmp_path: Path) -> str:
    img = np.zeros((1600, 900, 3), dtype="uint8")
    p = tmp_path / "passport.png"
    cv2.imwrite(str(p), img)
    return str(p)


class EndToEndSwapCorrectionTest(unittest.TestCase):
    """extract_passport_data itself, with OCR mocked to return the two
    real lines in swapped order (as it did in production) -- must still
    come out with the real name, not the garbled digits."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.image_path = _blank_image_file(self.tmp_dir)
        self.call_count = 0

    def _fake_ocr(self, image, language_hints=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            return _NO_BIO_WORDS  # bio-data-page call
        # Fixed MRZ band: the two real lines, swapped (line2 before line1)
        # -- reproducing what actually happened on this photo.
        swapped_text = f"{LINE2}\n{LINE1}"
        return OcrResult(full_text=swapped_text, words=[OcrWord("X", 0.9, (0, 0, 10, 10))])

    def test_surname_and_first_name_are_not_garbled(self):
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_ocr):
            result = extract_passport_data(self.image_path)
        self.assertIsNotNone(result.mrz)
        self.assertEqual(result.mrz.surname, "AYASS")
        self.assertEqual(result.mrz.given_names, "KARIM")
        self.assertNotIn(_GARBLED_SURNAME, result.mrz.surname)

    def test_raw_lines_reported_back_are_also_corrected(self):
        # raw_line1/raw_line2 are shown to callers/logs -- they must agree
        # with the parsed MRZResult, not still reflect the pre-correction
        # (swapped) order.
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_ocr):
            result = extract_passport_data(self.image_path)
        self.assertTrue(result.raw_line1.startswith("P<LBNAYASS"))
        self.assertTrue(result.raw_line2.startswith("LR24773270LBN"))


if __name__ == "__main__":
    unittest.main()
