"""
Regression tests for the 2026-09-06 label-disambiguation fix
(_find_label_line's confirm_keyword), found on a real photo (Frederic
Elias) via the usual method (pulling the real per-word OCR dump).

Root cause: "place" matches BOTH the real "Place of birth" label AND an
unrelated "Place and Number of Registry" line that prints higher up the
same bio page -- _find_label_line always took the topmost match, so the
wrong one won. On an earlier real photo (Younes Hamzeh) this happened to
be harmless because the wrong match's value band came up empty, falling
through to a working fallback tier by accident. On this photo it was not
harmless: the wrong match's value band contained real (if garbled) text
("25", "fession"), so a confidently wrong, UNFLAGGED "25 fession" went out
as Place of B. instead of falling through to any fallback at all.

REAL_BIO_WORDS below is the exact text/confidence/box data captured from
passport_02_bio_search_region_words.json on this photo's actual debug run
(2026-09-06).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.ocr_client import OcrWord
from ocr.passport_ocr import _extract_bio_field, _find_label_line


def _w(text, x0, y0, x1, y1, conf):
    return OcrWord(text=text, confidence=conf, box=(x0, y0, x1, y1))


# Exact real data from passport_02_bio_search_region_words.json (Frederic
# Elias, run 20260906_202630) -- trimmed to the words relevant to this bug
# (the unrelated top-of-page "Place and Number of Registry" block, and the
# real "Place of birth" label near the bottom, with nothing readable below
# it in this photo's crop).
REAL_BIO_WORDS = [
    _w("Place", 528, 65, 566, 87, 0.73),      # unrelated: "Place and Number of Registry"
    _w("Number", 601, 65, 658, 87, 0.722),
    _w("Registry", 465, 65, 524, 87, 0.583),
    _w("and", 570, 65, 596, 87, 0.506),
    _w("of", 539, 210, 553, 231, 0.95),        # unrelated block further down, different label
    _w("25", 520, 95, 546, 112, 0.929),        # garbled value sitting below the WRONG "Place"
    _w("fession", 490, 120, 541, 136, 0.765),
    _w("ELIAS", 246, 513, 301, 528, 0.991),
    _w("First", 245, 535, 280, 549, 0.851),
    _w("FREDERIC", 247, 583, 341, 600, 0.991),
    _w("Father", 250, 608, 294, 620, 0.986),
    _w("ZIAD", 247, 654, 291, 668, 0.984),
    _w("Nationality", 247, 676, 326, 690, 0.893),
    _w("LEBANESE", 248, 696, 346, 713, 0.963),
    _w("Place", 248, 716, 289, 727, 0.957),   # the REAL "Place of birth" label
    _w("of", 289, 715, 306, 727, 0.928),
    _w("Date", 458, 673, 493, 687, 0.96),      # right-column, unrelated field at similar height
    _w("of", 497, 673, 513, 687, 0.932),
    _w("birth", 514, 673, 550, 687, 0.939),
]


class LabelDisambiguationRealPhotoTest(unittest.TestCase):
    def test_unconfirmed_search_picks_the_wrong_topmost_place(self):
        # Sanity check on the fixture: confirms the plain (unconfirmed)
        # search really does pick the wrong, higher-up "Place" -- otherwise
        # this test wouldn't be exercising the real failure mode.
        line = _find_label_line(REAL_BIO_WORDS, "place")
        self.assertEqual(min(w.box[1] for w in line), 65)

    def test_confirmed_search_requires_birth_on_the_same_line(self):
        # "birth" only appears on the SAME line as the real "Place of
        # birth" label's own words in a well-cropped photo -- here it
        # doesn't even reach that far (see module docstring), so a
        # confirmed search must come back empty rather than accept either
        # "Place" match.
        line = _find_label_line(REAL_BIO_WORDS, "place", confirm_keyword="birth")
        self.assertIsNone(line)

    def test_direct_place_of_birth_extraction_no_longer_returns_garbage(self):
        # End to end: _extract_bio_field must not surface "25 fession"
        # (or anything containing it) once "birth" is required to confirm
        # the label match.
        result = _extract_bio_field(REAL_BIO_WORDS, "place", "place_of_birth", confirm_keyword="birth")
        self.assertEqual(result.value, "")
        self.assertTrue(result.flagged)
        self.assertNotIn("fession", result.value)


class FindLabelLineConfirmKeywordTest(unittest.TestCase):
    def test_confirm_keyword_none_keeps_old_behavior(self):
        # Every other caller (father/first/national/lebanese searches)
        # doesn't pass confirm_keyword -- must behave exactly as before.
        words = [_w("Father", 50, 100, 90, 112, 0.9), _w("name", 92, 100, 120, 112, 0.9)]
        line = _find_label_line(words, "father")
        self.assertEqual({w.text for w in line}, {"Father", "name"})

    def test_confirm_keyword_skips_an_unconfirmed_earlier_match(self):
        words = [
            _w("Place", 0, 0, 40, 12, 0.9),     # earlier match, no "birth" nearby
            _w("Number", 45, 0, 90, 12, 0.9),
            _w("Place", 0, 100, 40, 112, 0.9),  # later match, confirmed
            _w("of", 45, 100, 60, 112, 0.9),
            _w("birth", 65, 100, 100, 112, 0.9),
        ]
        line = _find_label_line(words, "place", confirm_keyword="birth")
        self.assertIsNotNone(line)
        self.assertEqual(min(w.box[1] for w in line), 100)

    def test_confirm_keyword_returns_none_when_nothing_confirms(self):
        words = [_w("Place", 0, 0, 40, 12, 0.9), _w("Number", 45, 0, 90, 12, 0.9)]
        self.assertIsNone(_find_label_line(words, "place", confirm_keyword="birth"))


if __name__ == "__main__":
    unittest.main()
