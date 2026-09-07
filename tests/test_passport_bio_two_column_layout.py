"""
Regression tests for the 2026-09-06 two-column-bio-page fix, found on a
fourth real photo (Younes Hamzeh) via the usual method (pulling the real
per-word OCR dump, see ocr/debug_dump.py's save_ocr_words, instead of
guessing at another recalibration).

REAL_BIO_WORDS below is the exact text/confidence/box data captured from
passport_02_bio_search_region_words.json on this photo's actual debug run
(2026-09-06, folder 20260906_191304) -- real ground truth, not synthetic.

IMPORTANT (and the source of a same-day follow-up bug -- see
passport_ocr.py's module docstring): this passport's MRZ parses SURNAME as
"YOUNES" and GIVEN NAMES as "HAMZEH" -- the opposite of what the two
names alone might suggest to a human reader. That's confirmed by the
actual autofill result the app produced (Surname: YOUNES, First Name:
HAMZEH), and it's what the fixtures/mocks below use -- getting this
backwards is exactly what broke the first attempt at this fix.

Two real bugs, both traced to the same root cause (this bio page prints
two columns -- a left name/nationality column and a right passport-
number/date-of-birth column -- at overlapping page heights, and nothing
used to stop a same-height word from the wrong column being swept into a
line/band it doesn't belong to):

- Place of birth came back as "ace of EL BATROUN": this photo's "Place of
  birth" label partially misread as just "ace of" (leading "Pl" dropped
  entirely, not just low-confidence), so _is_label_like_line didn't
  recognize it as a label and it got kept as if it were the value.
- Father's name fell through to the license's Arabic-only fallback:
  _extract_father_name_anchored anchors on the MRZ's given_names text
  ("HAMZEH", printed on the SECOND stacked bio-page line here, not the
  first) and scans down to the nationality value -- that band picked up
  cross-column noise ("TR", "Date of birth") that made the real
  father's-name line ("YOUNES", the third stacked line -- coincidentally
  the same text as the surname, since the family name here is also
  "Younes") look like a label line and get dropped.
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
from ocr.passport_ocr import (
    _extract_father_name_anchored,
    _extract_place_of_birth_anchored,
    _find_nationality_line,
    _is_label_like_line,
    extract_passport_data,
)


def _w(text, x0, y0, x1, y1, conf):
    return OcrWord(text=text, confidence=conf, box=(x0, y0, x1, y1))


# Exact real data from passport_02_bio_search_region_words.json (Younes
# Hamzeh, run 20260906_191304).
REAL_BIO_WORDS = [
    _w("Mo", 483, 64, 506, 76, 0.98),
    _w("Full", 538, 63, 565, 77, 0.864),
    _w("Name", 568, 63, 612, 77, 0.99),
    _w("HIND", 483, 121, 529, 139, 0.988),
    _w("MERHI", 536, 120, 599, 138, 0.977),
    _w("Place", 544, 150, 583, 169, 0.74),
    _w("and", 583, 151, 612, 168, 0.98),
    _w("Number", 613, 149, 671, 168, 0.942),
    _w("/", 671, 149, 683, 166, 0.58),
    _w("Republic", 92, 445, 178, 467, 0.993),
    _w("of", 184, 446, 204, 466, 0.99),
    _w("Lebanon", 209, 444, 292, 466, 0.989),
    _w("/", 299, 445, 309, 465, 0.588),
    _w("République", 314, 443, 425, 465, 0.956),
    _w("Libanaise", 430, 443, 525, 465, 0.989),
    _w("/", 529, 443, 540, 463, 0.654),
    _w("FO", 97, 477, 135, 498, 0.484),
    _w("Pa", 93, 528, 112, 541, 0.938),
    _w("Pass", 93, 544, 126, 556, 0.866),
    _w("18", 144, 723, 162, 737, 0.465),
    _w("YOUNES", 309, 540, 366, 556, 0.841),
    _w("HAMZEH", 300, 603, 368, 619, 0.984),
    _w("YOUNES", 297, 665, 363, 679, 0.989),
    _w("LEBANESE", 296, 704, 384, 720, 0.991),
    _w("ace", 308, 725, 332, 736, 0.966),
    _w("of", 335, 725, 350, 736, 0.984),
    _w("EL", 295, 745, 312, 761, 0.959),
    _w("BATROUN", 320, 744, 399, 760, 0.985),
    _w("Lyg", 601, 442, 707, 463, 0.375),
    _w("RL", 495, 475, 528, 495, 0.864),
    _w("Passport", 530, 475, 586, 495, 0.647),
    _w("N", 586, 475, 600, 495, 0.792),
    _w("LR2655136", 562, 498, 659, 511, 0.973),
    _w("X73955", 729, 497, 795, 511, 0.927),
    _w("Date", 482, 685, 511, 696, 0.96),
    _w("of", 515, 685, 529, 696, 0.993),
    _w("birth", 531, 685, 560, 696, 0.935),
    _w("203021956", 500, 703, 604, 719, 0.896),
    _w("TR", 935, 669, 959, 693, 0.898),
]


class IsLabelLikeLineFuzzySuffixTest(unittest.TestCase):
    def test_recognizes_truncated_place_of_birth_label(self):
        # The exact real-world fragment: "Place" misread as "ace" (leading
        # "Pl" dropped), which contains neither "place" nor "birth" as a
        # substring -- must still be recognized via the suffix match.
        line = [_w("ace", 308, 725, 332, 736, 0.966), _w("of", 335, 725, 350, 736, 0.984)]
        self.assertTrue(_is_label_like_line(line))

    def test_short_unrelated_word_is_not_flagged(self):
        # A short real value word must not accidentally match a keyword
        # suffix just for being short.
        line = [_w("EL", 295, 745, 312, 761, 0.959)]
        self.assertFalse(_is_label_like_line(line))

    def test_ordinary_value_word_still_not_label_like(self):
        line = [_w("BATROUN", 320, 744, 399, 760, 0.985)]
        self.assertFalse(_is_label_like_line(line))


class NationalityAnchorColumnTest(unittest.TestCase):
    def test_does_not_merge_cross_column_date_of_birth_value(self):
        # "203021956" (the date-of-birth value, right-hand column) sits at
        # almost the same page height as "LEBANESE" (left-hand column) --
        # confirmed real coordinates. Must not be pulled into the same
        # printed line as the nationality anchor.
        line = _find_nationality_line(REAL_BIO_WORDS)
        self.assertIsNotNone(line)
        self.assertTrue(any("LEBANESE" in w.text for w in line))
        self.assertFalse(any(w.text == "203021956" for w in line))


class PlaceOfBirthTwoColumnTest(unittest.TestCase):
    def test_recovers_clean_value_without_label_leak(self):
        result = _extract_place_of_birth_anchored(REAL_BIO_WORDS)
        self.assertIsNotNone(result)
        self.assertEqual(result.value, "EL BATROUN")

    def test_does_not_pull_in_unrelated_left_column_noise(self):
        result = _extract_place_of_birth_anchored(REAL_BIO_WORDS)
        self.assertNotIn("18", result.value)


class FatherNameTwoColumnTest(unittest.TestCase):
    def test_recovers_real_father_name_anchored_on_actual_mrz_given_name(self):
        # The MRZ's given_names is "HAMZEH" here (see module docstring) --
        # that's the real anchor, printed on the SECOND stacked bio-page
        # line, not the first. The real father's name ("YOUNES", the very
        # next line down) must win, not cross-column noise ("TR", "Date of
        # birth") that used to make that line look like a label and get
        # dropped.
        result = _extract_father_name_anchored(REAL_BIO_WORDS, "HAMZEH")
        self.assertIsNotNone(result)
        self.assertEqual(result.value, "YOUNES")

    def test_anchoring_on_the_wrong_name_finds_the_wrong_line(self):
        # Documents the failure mode a same-day follow-up fix introduced by
        # mistake: anchoring on "YOUNES" (the OTHER bio-page name line, not
        # the MRZ's actual given_names for this photo) does not raise, but
        # it is not the right call for this photo -- pinning this here so
        # a future change can't silently reintroduce anchoring on the wrong
        # MRZ field without a test noticing the mismatch.
        result = _extract_father_name_anchored(REAL_BIO_WORDS, "YOUNES")
        self.assertIsNotNone(result)
        self.assertNotEqual(result.value, "YOUNES")


class EndToEndOnRealPhotoDataTest(unittest.TestCase):
    """Exercises extract_passport_data itself with Younes Hamzeh's real bio
    words and a matching MRZ. Per the module docstring, this passport's MRZ
    really does parse surname="YOUNES", given_names="HAMZEH" -- confirmed
    against the app's actual autofill result, not assumed."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        img = np.zeros((1600, 900, 3), dtype="uint8")
        self.image_path = str(self.tmp_dir / "passport.png")
        cv2.imwrite(self.image_path, img)
        self.call_count = 0

    def _fake_ocr(self, image, language_hints=None, **kwargs):
        # 2026-09-06: MRZ resolution now happens before bio-page extraction
        # (see ocr/passport_ocr.py's docstring), so call 1 is the MRZ band
        # and call 2 is the bio region -- the reverse of this fake's order
        # before that fix.
        self.call_count += 1
        if self.call_count == 1:
            # P<LBN + surname "YOUNES" + "<<" + given names "HAMZEH".
            mrz_text = (
                "P<LBNYOUNES<<HAMZEH<<<<<<<<<<<<<<<<<<<<<<<<<\n"
                "LR2655136LBN5602031M3005015123456780123456"
            )
            return OcrResult(full_text=mrz_text, words=[OcrWord("X", 0.9, (0, 0, 10, 10))])
        return OcrResult(full_text="", words=REAL_BIO_WORDS)  # bio region

    def test_both_fields_resolve_correctly(self):
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_ocr):
            result = extract_passport_data(self.image_path)
        self.assertEqual(result.mrz.surname, "YOUNES")
        self.assertEqual(result.mrz.given_names, "HAMZEH")
        self.assertEqual(result.place_of_birth.value, "EL BATROUN")
        self.assertEqual(result.father_name.value, "YOUNES")


if __name__ == "__main__":
    unittest.main()
