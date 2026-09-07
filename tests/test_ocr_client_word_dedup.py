"""
Regression tests for ocr_client._dedupe_overlapping_words (2026-09-06),
added after a real photo (Younes Hamzeh, license field "8" / Address)
showed Vision returning two conflicting words for the same physical
glyph: "8" (confidence 0.986 -- the real pre-printed field-number digit)
and "00" (confidence 0.554) at bounding boxes overlapping ~85% IoU. The
address field then surfaced with a spurious "00" appended, since nothing
downstream had any way to tell a real second character apart from a
duplicate detection of the first one.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.ocr_client import OcrWord, _dedupe_overlapping_words, _iou


def _w(text, x0, y0, x1, y1, conf):
    return OcrWord(text=text, confidence=conf, box=(x0, y0, x1, y1))


class IouTest(unittest.TestCase):
    def test_identical_boxes_have_iou_one(self):
        self.assertAlmostEqual(_iou((0, 0, 10, 10), (0, 0, 10, 10)), 1.0)

    def test_non_overlapping_boxes_have_iou_zero(self):
        self.assertEqual(_iou((0, 0, 10, 10), (20, 20, 30, 30)), 0.0)

    def test_real_duplicate_boxes_measure_high_iou(self):
        # The exact real boxes from the "8"/"00" duplicate (Younes Hamzeh).
        iou = _iou((65, 70, 104, 119), (69, 71, 103, 119))
        self.assertGreater(iou, 0.8)


class DedupeOverlappingWordsTest(unittest.TestCase):
    def test_drops_lower_confidence_duplicate_of_the_same_glyph(self):
        # Exact real data: "8" (label digit) and "00" (spurious duplicate
        # detection of the same glyph) from the same field-8 crop.
        words = [
            _w("8", 65, 70, 104, 119, 0.986),
            _w("00", 69, 71, 103, 119, 0.554),
        ]
        kept = _dedupe_overlapping_words(words)
        self.assertEqual([w.text for w in kept], ["8"])

    def test_winner_kept_regardless_of_input_order(self):
        words = [
            _w("00", 69, 71, 103, 119, 0.554),
            _w("8", 65, 70, 104, 119, 0.986),
        ]
        kept = _dedupe_overlapping_words(words)
        self.assertEqual([w.text for w in kept], ["8"])

    def test_two_real_side_by_side_words_are_both_kept(self):
        # Normal case: two distinct adjacent words with no meaningful
        # overlap must both survive.
        words = [
            _w("13b", 39, 23, 196, 92, 0.972),
            _w("At", 223, 21, 318, 89, 0.835),
        ]
        kept = _dedupe_overlapping_words(words)
        self.assertEqual({w.text for w in kept}, {"13b", "At"})

    def test_empty_list_is_safe(self):
        self.assertEqual(_dedupe_overlapping_words([]), [])

    def test_three_way_overlap_keeps_only_the_best(self):
        words = [
            _w("A", 0, 0, 20, 20, 0.5),
            _w("B", 1, 1, 19, 19, 0.9),
            _w("C", 2, 2, 18, 18, 0.7),
        ]
        kept = _dedupe_overlapping_words(words)
        self.assertEqual([w.text for w in kept], ["B"])


if __name__ == "__main__":
    unittest.main()
