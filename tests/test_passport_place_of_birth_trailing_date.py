"""
Regression test for the 2026-09-19 trailing-date bug (see passport_ocr.py's
module docstring, same date): the very Younes Hamzeh photo whose "ace of
EL BATROUN" label-truncation bug was fixed on 2026-09-06 turned out, once
that fix held, to have a SECOND, previously-unnoticed symptom -- Place of
B. surfaced as "EL BATROUN 26:07 2022" in the real app, a genuine
production screenshot Georgio sent. The trailing "26:07 2022" is some
other printed date on the bio page (not the real date of birth, which is
read separately off the MRZ), landing unlabeled in the value band below
"Place of birth" and getting joined onto the real value as a second line.

Word positions below are synthetic but built to the same scale/column
reasoning _value_band_below and _restrict_to_anchor_column actually use
(a label line, a value line directly below it in the same column, and a
further line still within the generous band) -- not a copy of any single
real photo's exact pixel dump, since the point is to prove the general
fix (_is_date_like_line) rather than pin the test to one sample's exact
coordinates, per the project's standing rule against hardcoding fixes (or
their tests) to a single photo.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.ocr_client import OcrWord
from ocr.passport_ocr import _extract_bio_field, _is_date_like_line


def _w(text, x0, y0, x1, y1, conf=0.95):
    return OcrWord(text=text, confidence=conf, box=(x0, y0, x1, y1))


# "Place of birth" label line, e.g. y=700-712.
_LABEL_WORDS = [
    _w("Place", 250, 700, 290, 712),
    _w("of", 295, 700, 305, 712),
    _w("birth", 310, 700, 350, 712),
]

# The real value, directly below the label, same column.
_VALUE_WORDS = [
    _w("EL", 250, 720, 270, 732),
    _w("BATROUN", 275, 720, 340, 732),
]

# An unlabeled date -- some other printed field on the bio page (issuance
# or expiry date, not date of birth) whose own label wasn't read by Vision
# at all, still within the generous value band below "Place of birth" and
# in the same column.
_TRAILING_DATE_WORDS = [
    _w("26:07", 250, 745, 290, 757),
    _w("2022", 295, 745, 330, 757),
]


class IsDateLikeLineTest(unittest.TestCase):
    """Unit coverage for the new helper itself."""

    def test_a_pure_digit_and_punctuation_line_is_date_like(self):
        self.assertTrue(_is_date_like_line(_TRAILING_DATE_WORDS))

    def test_a_slash_formatted_date_is_date_like(self):
        self.assertTrue(_is_date_like_line([_w("03/02/1956", 0, 0, 10, 10)]))

    def test_a_real_place_name_is_not_date_like(self):
        self.assertFalse(_is_date_like_line(_VALUE_WORDS))

    def test_a_real_label_line_is_not_date_like(self):
        self.assertFalse(_is_date_like_line(_LABEL_WORDS))

    def test_an_empty_line_is_not_date_like(self):
        self.assertFalse(_is_date_like_line([]))


class PlaceOfBirthTrailingDateTest(unittest.TestCase):
    def test_trailing_unlabeled_date_is_not_absorbed_into_place_of_birth(self):
        words = _LABEL_WORDS + _VALUE_WORDS + _TRAILING_DATE_WORDS
        result = _extract_bio_field(words, "place", "place_of_birth", confirm_keyword="birth")
        self.assertEqual(result.value, "EL BATROUN")

    def test_without_the_fix_scenario_a_normal_second_value_line_still_works(self):
        # Guards against an overly-broad fix: a LEGITIMATE second value
        # line (e.g. an Arabic line above the Latin one, or a genuinely
        # wrapped name) must still be kept as long as it contains letters
        # -- only a purely numeric/punctuation line should be rejected.
        second_line_words = [_w("RIVERSIDE", 250, 745, 340, 757)]
        words = _LABEL_WORDS + _VALUE_WORDS + second_line_words
        result = _extract_bio_field(words, "place", "place_of_birth", confirm_keyword="birth")
        self.assertEqual(result.value, "EL BATROUN RIVERSIDE")

    def test_a_date_immediately_below_the_label_with_no_real_value_yields_empty(self):
        # Edge case: if the date-like line were somehow the very FIRST
        # line in the band (no real value line before it at all), the
        # field should come back empty/flagged rather than surfacing the
        # date itself as if it were the place -- not the production
        # scenario reported, but worth locking down given how close the
        # code paths are.
        words = _LABEL_WORDS + _TRAILING_DATE_WORDS
        result = _extract_bio_field(words, "place", "place_of_birth", confirm_keyword="birth")
        self.assertEqual(result.value, "")
        self.assertTrue(result.flagged)


if __name__ == "__main__":
    unittest.main()
