"""
Regression tests for the 2026-09-14 fix to license fields "4a" (issue date)
and "4b" (expiry date): per Georgio, a date field must never show letters.

Root cause (see ocr/license_ocr.py's _normalize_date_field docstring and
INLINE_LABEL_FIELDS' 2026-08-27 note): these two fields' "0123456789/"
whitelist has been INERT ever since the engine switched to Google Cloud
Vision (no character-whitelist concept), so nothing was actually stopping a
letter/digit lookalike from reaching the screen. Confirmed in real use (a
photo of Charbel Sfeir's license, reported via screenshot): the expiry date
came back "DB / 09 / 2024" -- almost certainly "08/09/2024" with "0"->"D"
and "8"->"B" misread, the same shape of error _normalize_blood_type already
corrects for on field "13b" (see tests/test_leading_field_number_and_blood_type.py),
just applied to dates instead of blood types.

This file covers three levels, same structure as the blood-type tests:
  1. _normalize_date_field in isolation (pure string -> string correction).
  2. _CLEAN_DATE_RE in isolation (the "is this a complete, trustworthy date
     now?" check extract_license_front uses to decide whether to flag).
  3. extract_license_front's wiring for "4a"/"4b" end to end, with _ocr_crop
     mocked (matching the style of tests/test_license_reference_alignment.py)
     so the real per-field OCR call chain is stood in for a controlled
     FieldRead, and only the post-processing this fix added is exercised.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ocr.license_ocr as license_ocr
from ocr.license_ocr import _CLEAN_DATE_RE, FieldRead, _normalize_date_field


class NormalizeDateFieldTest(unittest.TestCase):
    def test_real_sfeir_expiry_date_misread_is_corrected(self):
        # The exact string reported in production: "0"->"D", "8"->"B".
        self.assertEqual(_normalize_date_field("DB / 09 / 2024"), "08/09/2024")

    def test_collapses_whitespace_around_slashes(self):
        self.assertEqual(_normalize_date_field("08 / 09 / 2024"), "08/09/2024")

    def test_clean_value_is_untouched(self):
        self.assertEqual(_normalize_date_field("08/09/2024"), "08/09/2024")

    def test_converts_letter_o_and_uppercase_q_to_zero(self):
        self.assertEqual(_normalize_date_field("O8/O9/2Q24"), "08/09/2024")

    def test_converts_i_l_lowercase_and_uppercase_to_one(self):
        self.assertEqual(_normalize_date_field("Il/12/2020"), "11/12/2020")

    def test_converts_s_to_five_and_g_to_six_and_t_to_seven(self):
        self.assertEqual(_normalize_date_field("S/G/T024"), "5/6/7024")

    def test_converts_z_to_two(self):
        self.assertEqual(_normalize_date_field("Z2/01/2020"), "22/01/2020")

    def test_leading_and_trailing_whitespace_is_stripped(self):
        self.assertEqual(_normalize_date_field("  08/09/2024  "), "08/09/2024")

    def test_empty_string_is_safe(self):
        self.assertEqual(_normalize_date_field(""), "")

    def test_character_with_no_known_lookalike_mapping_passes_through(self):
        # No entry for "X" -- must be left as-is rather than dropped, so
        # the caller's _CLEAN_DATE_RE check can still see (and flag) it.
        self.assertEqual(_normalize_date_field("X8/09/2024"), "X8/09/2024")


class CleanDateRegexTest(unittest.TestCase):
    def test_matches_two_digit_day_month_four_digit_year(self):
        self.assertTrue(_CLEAN_DATE_RE.fullmatch("08/09/2024"))

    def test_matches_single_digit_day_or_month(self):
        self.assertTrue(_CLEAN_DATE_RE.fullmatch("8/9/2024"))

    def test_rejects_a_surviving_letter(self):
        self.assertFalse(_CLEAN_DATE_RE.fullmatch("X8/09/2024"))

    def test_rejects_empty(self):
        self.assertFalse(_CLEAN_DATE_RE.fullmatch(""))

    def test_rejects_missing_year(self):
        self.assertFalse(_CLEAN_DATE_RE.fullmatch("08/09"))

    def test_rejects_two_digit_year(self):
        self.assertFalse(_CLEAN_DATE_RE.fullmatch("08/09/24"))


class ExtractLicenseFrontDateWiringTest(unittest.TestCase):
    """Drives the real extract_license_front loop (deskew/alignment mocked
    the same way tests/test_license_reference_alignment.py does; _ocr_crop
    itself replaced with a controllable fake keyed by its `label` argument,
    e.g. "front_4b") to confirm the normalize-then-flag wiring this fix
    added actually runs for fields "4a"/"4b" and leaves every other field's
    handling (including "13b"'s own, separate normalization) untouched."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.front_path = str(self.tmp_dir / "front.png")
        cv2.imwrite(self.front_path, np.zeros((638, 1011, 3), dtype="uint8"))
        license_ocr._reference_loaded = False
        license_ocr._reference_front = None
        license_ocr._reference_back = None

    def tearDown(self):
        license_ocr._reference_loaded = False
        license_ocr._reference_front = None
        license_ocr._reference_back = None

    def _run_front(self, overrides: dict[str, FieldRead]):
        """overrides maps an _ocr_crop `label` (e.g. "front_4b") to the
        FieldRead it should return; every other label gets a bland,
        unflagged empty read so the fields this test isn't about don't
        trip any of their own special-case branches."""
        def fake_ocr_crop(card_image, region, label, debug_dir=None, errors=None, **kwargs):
            return overrides.get(label, FieldRead(value="", confidence=0.9, flagged=False))

        with mock.patch("ocr.license_ocr.deskew_card", return_value=np.zeros((638, 1011, 3), dtype="uint8")), \
             mock.patch("ocr.license_ocr._ocr_crop", side_effect=fake_ocr_crop):
            return license_ocr.extract_license_front(self.front_path)

    def test_real_sfeir_expiry_date_is_corrected_and_left_unflagged(self):
        result = self._run_front({"front_4b": FieldRead("DB / 09 / 2024", 0.9, False)})
        self.assertEqual(result.fields["4b"].value, "08/09/2024")
        self.assertFalse(result.fields["4b"].flagged)

    def test_issue_date_field_4a_gets_the_same_treatment(self):
        result = self._run_front({"front_4a": FieldRead("OB/O1/2O2O", 0.9, False)})
        self.assertEqual(result.fields["4a"].value, "08/01/2020")
        self.assertFalse(result.fields["4a"].flagged)

    def test_already_clean_date_is_untouched_and_unflagged(self):
        result = self._run_front({"front_4b": FieldRead("08/09/2024", 0.85, False)})
        self.assertEqual(result.fields["4b"].value, "08/09/2024")
        self.assertFalse(result.fields["4b"].flagged)

    def test_a_character_with_no_known_lookalike_gets_flagged_not_hidden(self):
        # "X" has no entry in _DATE_LETTER_MISREAD_TO_DIGIT -- per Georgio's
        # rule ("no way to be letters"), this must never be shown to staff
        # as if it were a trustworthy date; it gets flagged for manual
        # review instead, same as any other low-confidence field.
        result = self._run_front({"front_4b": FieldRead("X8/09/2024", 0.9, False)})
        self.assertEqual(result.fields["4b"].value, "X8/09/2024")
        self.assertTrue(result.fields["4b"].flagged)

    def test_empty_read_is_not_flagged_by_this_check_alone(self):
        # An empty value is already flagged upstream by _ocr_crop itself
        # (see its own "flagged = ... or not text" logic) -- this fix's
        # check must not additionally misfire on emptiness in a way that
        # would be misleading if _ocr_crop's own flag were ever False.
        result = self._run_front({"front_4b": FieldRead("", 0.9, False)})
        self.assertEqual(result.fields["4b"].value, "")
        self.assertFalse(result.fields["4b"].flagged)

    def test_blood_type_field_13b_is_unaffected_by_this_change(self):
        # "13b" must keep going through _normalize_blood_type, not the new
        # date path -- confirms the two branches stay mutually exclusive.
        result = self._run_front({"front_13b": FieldRead("0+", 0.9, False)})
        self.assertEqual(result.fields["13b"].value, "O+")


if __name__ == "__main__":
    unittest.main()
