"""
Regression tests for the 2026-08-30 passport bio-field extraction rework:
father's name / place of birth are now found by searching a single OCR
pass over BIO_SEARCH_REGION for each field's printed label, then reading
the words below it — instead of trusting a fixed fraction of the photo to
land on the right spot (see passport_ocr.py's module docstring and
passport_field_regions.py's history for why the old approach kept
breaking on differently-framed real photos).

All words below are synthetic (x0, y0, x1, y1) pixel boxes, not real OCR
output, but scaled to roughly the real proportions measured off actual
debug crops in the 2026-08-23/27 recalibration passes: a label line ~12px
tall, a value line starting a few px below it.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.ocr_client import OcrWord
from ocr.passport_ocr import (
    BIO_LOW_CONFIDENCE_THRESHOLD,
    _cluster_into_lines,
    _extract_bio_field,
    _find_label_line,
    _value_band_below,
)


def _w(text, x0, y0, x1, y1, conf=0.9):
    return OcrWord(text=text, confidence=conf, box=(x0, y0, x1, y1))


class FindLabelLineTest(unittest.TestCase):
    def test_finds_label_by_case_insensitive_keyword(self):
        words = [_w("Father", 50, 100, 90, 112), _w("name", 92, 100, 120, 112)]
        line = _find_label_line(words, "father")
        self.assertIsNotNone(line)
        self.assertEqual({w.text for w in line}, {"Father", "name"})

    def test_returns_none_when_keyword_absent(self):
        words = [_w("Nationality", 50, 100, 150, 112)]
        self.assertIsNone(_find_label_line(words, "father"))

    def test_does_not_match_unrelated_header_text(self):
        # The exact real-world failure this rework fixes: header text like
        # "Republic of Lebanon" must never be mistaken for a field label.
        words = [
            _w("Republic", 20, 30, 100, 45),
            _w("of", 102, 30, 115, 45),
            _w("Lebanon", 117, 30, 180, 45),
            _w("Father", 50, 100, 90, 112),
            _w("name", 92, 100, 120, 112),
        ]
        line = _find_label_line(words, "father")
        self.assertEqual({w.text for w in line}, {"Father", "name"})

    def test_finds_label_split_across_two_words(self):
        # 2026-08-30 regression: a real photo (Rana Rayess) came back with
        # father_name entirely empty -- one plausible cause is the OCR
        # engine splitting "Father" itself into two tokens (e.g. over a
        # busy security-pattern background) so no single detected word
        # contains "father" as a substring. Must still find it via the
        # adjacent-word concatenation fallback.
        words = [
            _w("Fa", 50, 100, 66, 112),
            _w("ther", 68, 100, 90, 112),
            _w("name", 92, 100, 120, 112),
        ]
        line = _find_label_line(words, "father")
        self.assertIsNotNone(line)
        self.assertIn("Fa", {w.text for w in line})

    def test_does_not_false_positive_on_unrelated_adjacent_words(self):
        words = [
            _w("Place", 50, 100, 90, 112),
            _w("of", 92, 100, 105, 112),
            _w("birth", 107, 100, 140, 112),
        ]
        self.assertIsNone(_find_label_line(words, "father"))

    def test_picks_topmost_match_first(self):
        words = [
            _w("Place", 50, 300, 90, 312),  # a second, lower occurrence
            _w("Place", 50, 100, 90, 112),  # the real label, higher up
        ]
        line = _find_label_line(words, "place")
        self.assertEqual(min(w.box[1] for w in line), 100)


class ClusterIntoLinesTest(unittest.TestCase):
    def test_groups_words_on_same_row_into_one_line(self):
        words = [_w("Father", 50, 100, 90, 112), _w("name", 92, 102, 120, 114)]
        lines = _cluster_into_lines(words)
        self.assertEqual(len(lines), 1)
        self.assertEqual([w.text for w in lines[0]], ["Father", "name"])

    def test_separates_distinct_rows(self):
        words = [_w("SAID", 50, 130, 90, 143), _w("Nationality", 50, 190, 150, 202)]
        lines = _cluster_into_lines(words)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0][0].text, "SAID")
        self.assertEqual(lines[1][0].text, "Nationality")


class ValueBandBelowTest(unittest.TestCase):
    def setUp(self):
        self.label_line = [_w("Father", 50, 100, 90, 112), _w("name", 92, 100, 120, 112)]

    def test_excludes_words_above_the_label(self):
        above = _w("First name", 50, 60, 130, 72)
        below = _w("SAID", 50, 130, 90, 143)
        band = _value_band_below([above, below], self.label_line)
        self.assertEqual([w.text for w in band], ["SAID"])

    def test_excludes_words_far_left_of_the_label(self):
        far_left = _w("noise", 0, 130, 10, 143)
        value = _w("SAID", 50, 130, 90, 143)
        band = _value_band_below([far_left, value], self.label_line)
        self.assertEqual([w.text for w in band], ["SAID"])

    def test_excludes_words_far_below_the_band(self):
        # label height here is 12px, band extends 6x below -> 184.
        far_below = _w("unrelated", 50, 400, 120, 415)
        value = _w("SAID", 50, 130, 90, 143)
        band = _value_band_below([far_below, value], self.label_line)
        self.assertEqual([w.text for w in band], ["SAID"])


class ExtractBioFieldTest(unittest.TestCase):
    def test_reads_value_below_label(self):
        words = [
            _w("Father", 50, 100, 90, 112),
            _w("name", 92, 100, 120, 112),
            _w("SAID", 50, 130, 90, 143, conf=0.95),
        ]
        result = _extract_bio_field(words, "father", "father_name")
        self.assertEqual(result.value, "SAID")
        self.assertFalse(result.flagged)

    def test_flags_and_empties_when_label_not_found(self):
        words = [_w("Nationality", 50, 100, 150, 112)]
        result = _extract_bio_field(words, "father", "father_name")
        self.assertEqual(result.value, "")
        self.assertTrue(result.flagged)
        self.assertEqual(result.confidence, 0.0)

    def test_flags_low_confidence_read(self):
        words = [
            _w("Place", 50, 100, 90, 112),
            _w("SOMEPLACE", 50, 130, 130, 143, conf=0.2),
        ]
        result = _extract_bio_field(words, "place", "place_of_birth")
        self.assertLess(result.confidence, BIO_LOW_CONFIDENCE_THRESHOLD)
        self.assertTrue(result.flagged)

    def test_stops_at_two_lines_and_skips_a_third(self):
        # The next field's own label sitting inside the generous band
        # must not get pulled into this field's value.
        words = [
            _w("Father", 50, 100, 90, 112),
            _w("name", 92, 100, 120, 112),
            _w("SAID", 50, 130, 90, 143),          # value line 1
            _w("EXTRA", 50, 155, 100, 168),         # value line 2 (still kept)
            _w("Nationality", 50, 178, 150, 190),   # 3rd line: must be dropped
        ]
        result = _extract_bio_field(words, "father", "father_name")
        self.assertIn("SAID", result.value)
        self.assertIn("EXTRA", result.value)
        self.assertNotIn("Nationality", result.value)

    def test_two_fields_resolve_independently_from_shared_word_list(self):
        # Mirrors the real regression: one OCR pass over the whole
        # BIO_SEARCH_REGION, both fields' labels/values present alongside
        # unrelated header text, each field must resolve to its own value
        # only.
        words = [
            _w("Republic", 20, 30, 100, 45),
            _w("of", 102, 30, 115, 45),
            _w("Lebanon", 117, 30, 180, 45),
            _w("Father", 50, 200, 90, 212),
            _w("name", 92, 200, 120, 212),
            _w("SAID", 50, 230, 90, 243, conf=0.9),
            _w("Place", 50, 400, 90, 412),
            _w("of", 92, 400, 105, 412),
            _w("birth", 107, 400, 140, 412),
            _w("RMEICH", 50, 430, 110, 443, conf=0.9),
        ]
        father = _extract_bio_field(words, "father", "father_name")
        place = _extract_bio_field(words, "place", "place_of_birth")
        self.assertEqual(father.value, "SAID")
        self.assertEqual(place.value, "RMEICH")


if __name__ == "__main__":
    unittest.main()
