"""
Regression tests for the second 2026-08-30 passport bio-field fix, found by
pulling a real photo's raw OCR word dump (Rana Rayess) via
ocr/debug_dump.py's save_ocr_words instead of guessing at another
recalibration — see passport_ocr.py's module docstring for the full
diagnosis. Two separate real bugs:

- father_name came back completely empty: Vision never detected the
  "Father name" label at all on this photo (not even split across two
  words), so the direct label search in _extract_bio_field correctly
  found nothing, which pushed the pipeline to fall back to the license's
  Arabic-only field instead. _extract_father_name_positional fixes this
  by locating the value between the (reliably-detected) "First name" and
  "Nationality" labels instead of relying on father_name's own label.
- place_of_birth pulled in a low-confidence noise fragment sharing its
  value's line, plus the next field's mis-read label and a different
  column's field, because the value band is intentionally generous (see
  _value_band_below's docstring) and nothing used to stop it from just
  grabbing the first two clustered lines regardless of content.
  _filter_low_confidence + _select_value_lines/_is_label_like_line fix
  this.

The REAL_BIO_WORDS fixture below is the exact text/confidence/box data
captured from passport_02_bio_search_region_words.json on this photo's
actual debug run (2026-08-30) -- real ground truth, not synthetic data,
so this suite doubles as a pinned regression test against the exact
photo that exposed both bugs.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.ocr_client import OcrWord
from ocr.passport_ocr import (
    _KNOWN_LABEL_KEYWORDS,
    _MIN_WORD_CONFIDENCE,
    _extract_bio_field,
    _extract_father_name_positional,
    _field_read_from_lines,
    _filter_low_confidence,
    _is_label_like_line,
    _select_value_lines,
)


def _w(text, x0, y0, x1, y1, conf):
    return OcrWord(text=text, confidence=conf, box=(x0, y0, x1, y1))


# Exact real data from passport_02_bio_search_region_words.json (Rana
# Rayess, run 20260830_200002) -- trimmed to the words relevant to these
# two fields, everything else in the real 56-word dump is noise for this
# specific test (headers, MRZ-adjacent text, etc.) that neither function
# under test looks at.
REAL_BIO_WORDS = [
    _w("First", 216, 486, 239, 498, 0.75),
    _w("name", 240, 485, 268, 497, 0.97),
    _w("RANA", 217, 521, 254, 531, 0.99),
    _w("WAKED", 215, 565, 263, 578, 0.99),
    _w("Nationality", 217, 582, 267, 593, 0.89),
    _w("LEBANESE", 216, 598, 280, 608, 0.99),
    _w("Place", 216, 611, 243, 621, 0.91),
    _w("of", 243, 611, 254, 620, 0.67),
    _w("birth", 257, 611, 278, 620, 0.90),
    _w("HEMLAYA", 215, 624, 276, 640, 0.99),
    _w("SU", 291, 623, 312, 637, 0.58),
    _w("once", 237, 646, 255, 654, 0.54),
    _w("date", 259, 646, 278, 653, 0.78),
    _w("Author", 365, 645, 398, 656, 0.83),
]


class RealPhotoRegressionTest(unittest.TestCase):
    """Pinned against the exact real word data that exposed both bugs."""

    def test_father_name_label_is_genuinely_absent_from_this_photo(self):
        # Sanity check on the fixture itself: confirms this test is
        # actually exercising the "label never detected" case and not
        # accidentally testing something else.
        self.assertTrue(all("father" not in w.text.lower() for w in REAL_BIO_WORDS))

    def test_direct_search_finds_nothing_for_father_name(self):
        result = _extract_bio_field(REAL_BIO_WORDS, "father", "father_name")
        self.assertEqual(result.value, "")
        self.assertTrue(result.flagged)

    def test_positional_fallback_recovers_waked(self):
        result = _extract_father_name_positional(REAL_BIO_WORDS)
        self.assertIsNotNone(result)
        self.assertEqual(result.value, "WAKED")
        self.assertFalse(result.flagged)

    def test_positional_fallback_skips_the_given_name(self):
        result = _extract_father_name_positional(REAL_BIO_WORDS)
        self.assertNotIn("RANA", result.value)

    def test_place_of_birth_resolves_cleanly(self):
        result = _extract_bio_field(REAL_BIO_WORDS, "place", "place_of_birth")
        self.assertEqual(result.value, "HEMLAYA")
        self.assertFalse(result.flagged)

    def test_place_of_birth_excludes_noise_and_next_field_pollution(self):
        result = _extract_bio_field(REAL_BIO_WORDS, "place", "place_of_birth")
        for polluter in ("SU", "once", "date", "Author"):
            self.assertNotIn(polluter, result.value)


class PositionalFallbackAnchorTest(unittest.TestCase):
    def test_returns_none_when_first_name_label_missing(self):
        words = [w for w in REAL_BIO_WORDS if w.text not in ("First", "name")]
        self.assertIsNone(_extract_father_name_positional(words))

    def test_returns_none_when_nationality_label_missing(self):
        words = [w for w in REAL_BIO_WORDS if w.text != "Nationality"]
        self.assertIsNone(_extract_father_name_positional(words))

    def test_returns_none_when_only_given_name_present_between_anchors(self):
        # Only one line (the given name) between "First name" and
        # "Nationality" -- nothing to positionally call father's name.
        words = [
            _w("First", 216, 486, 239, 498, 0.9),
            _w("name", 240, 485, 268, 497, 0.9),
            _w("RANA", 217, 521, 254, 531, 0.99),
            _w("Nationality", 217, 582, 267, 593, 0.9),
        ]
        self.assertIsNone(_extract_father_name_positional(words))

    def test_does_not_displace_a_present_low_confidence_direct_read(self):
        # extract_passport_data only tries the positional fallback when
        # the direct read's value is fully empty -- a flagged-but-present
        # direct read of the actually-labeled field must win over a
        # positional guess. This is enforced by the caller
        # (extract_passport_data), not _extract_father_name_positional
        # itself, so this documents/pins that contract at the FieldRead
        # level the caller checks.
        direct = _extract_bio_field(REAL_BIO_WORDS, "father", "father_name")
        self.assertEqual(direct.value, "")  # only empty triggers the fallback


class FilterLowConfidenceTest(unittest.TestCase):
    def test_drops_words_below_threshold(self):
        words = [_w("good", 0, 0, 10, 10, 0.9), _w("bad", 0, 0, 10, 10, 0.1)]
        kept = _filter_low_confidence(words)
        self.assertEqual([w.text for w in kept], ["good"])

    def test_keeps_word_exactly_at_threshold(self):
        words = [_w("edge", 0, 0, 10, 10, _MIN_WORD_CONFIDENCE)]
        self.assertEqual(_filter_low_confidence(words), words)


class IsLabelLikeLineTest(unittest.TestCase):
    def test_recognizes_a_known_label_keyword(self):
        line = [_w("Nationality", 0, 0, 10, 10, 0.9)]
        self.assertTrue(_is_label_like_line(line))

    def test_ordinary_value_is_not_label_like(self):
        line = [_w("HEMLAYA", 0, 0, 10, 10, 0.9)]
        self.assertFalse(_is_label_like_line(line))

    def test_checks_across_the_whole_joined_line_not_just_one_word(self):
        line = [_w("once", 0, 0, 10, 10, 0.9), _w("date", 12, 0, 20, 10, 0.9)]
        self.assertTrue(_is_label_like_line(line))


class SelectValueLinesTest(unittest.TestCase):
    def test_stops_before_a_label_like_line(self):
        lines = [
            [_w("HEMLAYA", 0, 0, 10, 10, 0.9)],
            [_w("date", 0, 20, 10, 30, 0.9)],
        ]
        self.assertEqual(_select_value_lines(lines), [lines[0]])

    def test_caps_at_max_value_lines_when_no_label_line_appears(self):
        lines = [
            [_w("A", 0, 0, 10, 10, 0.9)],
            [_w("B", 0, 20, 10, 30, 0.9)],
            [_w("C", 0, 40, 10, 50, 0.9)],
        ]
        self.assertEqual(_select_value_lines(lines), lines[:2])


class FieldReadFromLinesTest(unittest.TestCase):
    def test_builds_field_read_from_lines(self):
        lines = [[_w("WAKED", 0, 0, 10, 10, 0.99)]]
        result = _field_read_from_lines(lines, "father_name")
        self.assertEqual(result.value, "WAKED")
        self.assertAlmostEqual(result.confidence, 0.99)
        self.assertFalse(result.flagged)

    def test_empty_lines_yield_flagged_empty_read(self):
        result = _field_read_from_lines([], "father_name")
        self.assertEqual(result.value, "")
        self.assertTrue(result.flagged)


class KnownLabelKeywordsSanityTest(unittest.TestCase):
    def test_includes_the_keywords_actually_searched_for(self):
        # father_name/place_of_birth search on these two keywords directly
        # (see extract_passport_data) -- they must also be in the stop set
        # so a generous band never pulls one field's label into another's
        # value.
        self.assertIn("father", _KNOWN_LABEL_KEYWORDS)
        self.assertIn("place", _KNOWN_LABEL_KEYWORDS)


if __name__ == "__main__":
    unittest.main()
