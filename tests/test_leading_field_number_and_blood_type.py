"""
Regression tests for two 2026-08-30 cleanups found on a second real photo
(Rana Rayess) after the reference-alignment fix landed:

- _strip_leading_field_number: field "2" (given name) read back "2. RANA"
  instead of "RANA" -- the crop's top edge caught the tail of the printed
  "2." a few pixels above where it landed on the reference photo. Unlike
  _strip_inline_label's widest-gap heuristic (unsafe here -- see this
  function's own docstring for why), this only strips a token that IS the
  field's own number.
- _normalize_blood_type: now also strips whitespace -- "A" and "+" can be
  detected as two separate words and rejoined with a space ("A +"), but a
  real blood type never legitimately contains one.

2026-09-07: added coverage for _normalize_blood_type_from_words -- the
field "13b" fallback used when _strip_inline_label's word-count-driven
split throws away the value entirely (a real third photo, Charbel Sfeir,
had the "13b." label fuse with the value's leading "A", itself misread as
"4", into one word "13b.4" alongside a separate "+" word -- see that
function's docstring in ocr/license_ocr.py for the full diagnosis).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.ocr_client import OcrWord
from ocr.license_ocr import (
    _CLEAN_BLOOD_TYPE_RE,
    _normalize_blood_type,
    _normalize_blood_type_from_words,
    _strip_leading_field_number,
)


class StripLeadingFieldNumberTest(unittest.TestCase):
    def test_strips_matching_leading_number_with_period(self):
        self.assertEqual(_strip_leading_field_number("2. RANA", "2"), "RANA")

    def test_strips_matching_leading_number_without_period(self):
        self.assertEqual(_strip_leading_field_number("8 BEIRUT", "8"), "BEIRUT")

    def test_leaves_multiword_value_alone_when_no_leading_number(self):
        # The exact regression this must never cause: a clean two-word
        # value (Georges' own surname) must survive completely untouched.
        self.assertEqual(_strip_leading_field_number("EL ALAM", "1"), "EL ALAM")

    def test_does_not_strip_a_different_fields_number(self):
        # A leading "3" must not be stripped from field "2"'s crop -- only
        # this field's own number is a safe match.
        self.assertEqual(_strip_leading_field_number("3. SOMETHING", "2"), "3. SOMETHING")

    def test_does_not_strip_a_number_that_is_part_of_the_value(self):
        # A value that happens to start with a number unrelated to the
        # field key (e.g. an address with a house number) must not be
        # mistaken for the field's own printed label.
        self.assertEqual(_strip_leading_field_number("221 MAIN ST", "8"), "221 MAIN ST")

    def test_empty_string_is_safe(self):
        self.assertEqual(_strip_leading_field_number("", "1"), "")


class NormalizeBloodTypeTest(unittest.TestCase):
    def test_strips_space_between_letter_and_sign(self):
        self.assertEqual(_normalize_blood_type("A +"), "A+")

    def test_converts_digit_zero_to_letter_o(self):
        self.assertEqual(_normalize_blood_type("0+"), "O+")

    def test_handles_both_together(self):
        self.assertEqual(_normalize_blood_type("0 +"), "O+")

    def test_clean_value_untouched(self):
        self.assertEqual(_normalize_blood_type("AB-"), "AB-")

    def test_fixes_plus_misread_as_lowercase_t(self):
        # 2026-09-06 real photo (Younes Hamzeh): a plainly-legible "A+" on
        # the card came back from Vision as the single word "At" (a thin
        # "+" kerned tight against the "A" apparently reads as a "t"'s
        # stem) -- _strip_inline_label correctly isolated it from the
        # "13b" label, so the fix belongs here, in the value-shape check.
        self.assertEqual(_normalize_blood_type("At"), "A+")

    def test_fixes_plus_misread_on_o_and_b_groups_too(self):
        self.assertEqual(_normalize_blood_type("Bt"), "B+")
        self.assertEqual(_normalize_blood_type("Ot"), "O+")
        self.assertEqual(_normalize_blood_type("ABt"), "AB+")

    def test_fixes_plus_misread_as_digit_one_or_letter_l(self):
        self.assertEqual(_normalize_blood_type("A1"), "A+")
        self.assertEqual(_normalize_blood_type("Al"), "A+")
        self.assertEqual(_normalize_blood_type("AI"), "A+")

    def test_genuine_minus_sign_untouched(self):
        self.assertEqual(_normalize_blood_type("A-"), "A-")

    def test_does_not_touch_a_value_that_does_not_match_the_shape(self):
        # Anything not shaped like a blood group + single trailing
        # character must be returned as-is rather than mangled further --
        # this normalizer only ever corrects a known misread, it doesn't
        # try to force garbage into a blood type.
        self.assertEqual(_normalize_blood_type("GARBAGE"), "GARBAGE")

    def test_extracts_value_from_label_and_value_merged_into_one_word(self):
        # 2026-09-06 real photo (Frederic Elias): the crop's "13b." label
        # and "O+" value came back from Vision as a SINGLE word, "136.0+"
        # ("b" misread as "6", no gap detected at all between label and
        # value) -- _strip_inline_label can't split a single word (see its
        # own docstring), so the whole polluted string reaches here. The
        # real value is always at the very end of the string.
        self.assertEqual(_normalize_blood_type("136.0+"), "O+")

    def test_extracts_value_from_merged_word_with_letter_group(self):
        self.assertEqual(_normalize_blood_type("13b.A+"), "A+")

    def test_extracts_value_combining_both_misreads(self):
        # The merged-word case AND the "+"-as-"t" case together.
        self.assertEqual(_normalize_blood_type("13b.At"), "A+")


class NormalizeBloodTypeFromWordsTest(unittest.TestCase):
    """Field "13b"'s words-based fallback -- only reached (per
    extract_license_front) when _normalize_blood_type's split-based result
    isn't already a clean, complete blood type."""

    def test_real_sfeir_photo_recovers_full_value_from_fused_label_word(self):
        # Real device data (run 20260907_195552, front_13b_words.json): the
        # printed "13b. A+" came back as exactly these two words. The "4"
        # is Vision's misread of the value's real leading "A".
        words = [
            OcrWord("13b.4", 0.89, (24, 15, 265, 89)),
            OcrWord("+", 0.745, (257, 15, 307, 86)),
        ]
        self.assertEqual(_normalize_blood_type_from_words(words), "A+")

    def test_still_works_when_label_and_value_are_cleanly_separate(self):
        words = [
            OcrWord("13b.", 0.9, (0, 0, 40, 30)),
            OcrWord("O", 0.9, (60, 0, 80, 30)),
            OcrWord("+", 0.9, (90, 0, 105, 30)),
        ]
        self.assertEqual(_normalize_blood_type_from_words(words), "O+")

    def test_still_works_on_a_single_fully_merged_word(self):
        words = [OcrWord("136.0+", 0.8, (0, 0, 100, 30))]
        self.assertEqual(_normalize_blood_type_from_words(words), "O+")

    def test_does_not_fabricate_a_value_from_pure_garbage(self):
        words = [OcrWord("XYZ", 0.5, (0, 0, 40, 30))]
        self.assertEqual(_normalize_blood_type_from_words(words), "")

    def test_empty_words_is_safe(self):
        self.assertEqual(_normalize_blood_type_from_words([]), "")

    def test_does_not_misfire_on_an_unrelated_trailing_digit(self):
        # A digit only counts as a group-letter misread immediately before
        # a genuine Rh sign -- a string ending in a plain digit with no
        # +/-/misread-Rh character after it must not match at all.
        words = [OcrWord("13b.4", 0.89, (0, 0, 40, 30))]
        self.assertEqual(_normalize_blood_type_from_words(words), "")


class CleanBloodTypeRegexTest(unittest.TestCase):
    """Guards the "is this already a complete value?" check that decides
    whether extract_license_front needs to fall back at all."""

    def test_matches_every_clean_group_and_sign_combination(self):
        for group in ("A", "B", "AB", "O"):
            for sign in ("+", "-"):
                self.assertTrue(_CLEAN_BLOOD_TYPE_RE.fullmatch(group + sign))

    def test_rejects_sign_only(self):
        self.assertFalse(_CLEAN_BLOOD_TYPE_RE.fullmatch("+"))

    def test_rejects_empty(self):
        self.assertFalse(_CLEAN_BLOOD_TYPE_RE.fullmatch(""))

    def test_rejects_leftover_label_junk(self):
        self.assertFalse(_CLEAN_BLOOD_TYPE_RE.fullmatch("13b.A+"))


if __name__ == "__main__":
    unittest.main()
