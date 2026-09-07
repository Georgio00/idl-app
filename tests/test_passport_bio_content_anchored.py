"""
Regression tests for the 2026-09-01 content-anchored fallback tier: on a
third real photo (Talal Issa), Vision detected almost none of the bio-page
LABELS at all within BIO_SEARCH_REGION -- not "Father name", not "Place of
birth", not even "First name"/"Nationality" (what the 2026-08-30 positional
fallback relies on). Only the field VALUES read, each on its own line, in
a consistent order: given name, father's name, nationality, place of
birth -- the same order confirmed on the Rana Rayess photo, just with more
labels missing. So this tier anchors on CONTENT instead of any label text:
the given name (already known independently from the checksum-backed MRZ)
and the nationality value ("LEBANESE", printed in bold on every Lebanese
passport and read at high confidence on every real sample so far).

REAL_BIO_WORDS below is the exact text/confidence/box data captured from
passport_02_bio_search_region_words.json on Talal Issa's real debug run
(2026-09-01) -- pinned regression data, not synthetic.
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
    _extract_bio_field,
    _extract_father_name_anchored,
    _extract_place_of_birth_anchored,
    _find_nationality_line,
    _select_value_lines_skip_leading_label,
    extract_passport_data,
)


def _w(text, x0, y0, x1, y1, conf):
    return OcrWord(text=text, confidence=conf, box=(x0, y0, x1, y1))


# Exact real data from passport_02_bio_search_region_words.json (Talal
# Issa, run 20260901_160039). No "Father", "Place", "First", or
# "Nationality" label word appears anywhere in this real dump -- only the
# header and the field values themselves.
REAL_BIO_WORDS = [
    _w("Republic", 70, 521, 141, 537, 0.97),
    _w("of", 144, 521, 160, 537, 0.976),
    _w("Lebanon", 164, 521, 231, 537, 0.963),
    _w("/", 233, 521, 244, 537, 0.495),
    _w("République", 246, 521, 332, 537, 0.874),
    _w("Libanaise", 337, 521, 413, 537, 0.896),
    _w("TALAL", 235, 643, 276, 660, 0.99),
    _w("RE", 387, 545, 413, 564, 0.759),
    _w("LR22", 446, 561, 480, 572, 0.972),
    _w("028504", 582, 560, 631, 572, 0.906),
    _w("MTANIOS", 235, 693, 294, 709, 0.986),
    _w("LEBANESEL", 233, 723, 325, 742, 0.901),
    _w("170", 401, 728, 428, 741, 0.861),
    _w("ANDAKT", 231, 760, 288, 773, 0.959),
    _w("PC", 293, 760, 308, 773, 0.488),
]


class RealPhotoRegressionTest(unittest.TestCase):
    def test_no_label_words_present_at_all(self):
        # Sanity check on the fixture: confirms this really is the
        # near-total-label-loss case, not something else.
        for kw in ("father", "place", "first", "national"):
            self.assertTrue(
                all(kw not in w.text.lower() for w in REAL_BIO_WORDS),
                f"expected no word containing {kw!r} in this fixture",
            )

    def test_direct_search_finds_nothing_for_father_name(self):
        result = _extract_bio_field(REAL_BIO_WORDS, "father", "father_name")
        self.assertEqual(result.value, "")

    def test_direct_search_finds_nothing_for_place_of_birth(self):
        result = _extract_bio_field(REAL_BIO_WORDS, "place", "place_of_birth")
        self.assertEqual(result.value, "")

    def test_nationality_anchor_found_despite_ocr_merge_noise(self):
        # Real Vision output merged the nationality value with a stray
        # leading character of whatever follows ("LEBANESEL", not
        # "LEBANESE") -- must still match as a substring.
        line = _find_nationality_line(REAL_BIO_WORDS)
        self.assertIsNotNone(line)
        self.assertTrue(any("LEBANESE" in w.text for w in line))

    def test_father_name_anchored_recovers_mtanios(self):
        result = _extract_father_name_anchored(REAL_BIO_WORDS, "TALAL")
        self.assertIsNotNone(result)
        self.assertEqual(result.value, "MTANIOS")
        self.assertFalse(result.flagged)

    def test_place_of_birth_anchored_recovers_andakt(self):
        result = _extract_place_of_birth_anchored(REAL_BIO_WORDS)
        self.assertIsNotNone(result)
        self.assertEqual(result.value, "ANDAKT")
        self.assertFalse(result.flagged)

    def test_place_of_birth_excludes_low_confidence_noise_fragment(self):
        # "PC" (conf 0.488) sits on the same real line as ANDAKT -- must
        # be filtered out, same low-confidence-noise handling as the
        # 08-30 fix.
        result = _extract_place_of_birth_anchored(REAL_BIO_WORDS)
        self.assertNotIn("PC", result.value)


class EndToEndOnRealPhotoDataTest(unittest.TestCase):
    """Exercises extract_passport_data itself (not just the isolated
    helpers above) with Talal Issa's real bio words and a matching MRZ, to
    pin the actual fallback-tier wiring: father_name's content-anchored
    tier only runs after the MRZ is available (it needs the given name),
    while place_of_birth's runs immediately since it doesn't."""

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
            # MRZ band: a real, checksum-valid TD3 pair with TALAL as the
            # given name, matching REAL_BIO_WORDS' "TALAL".
            mrz_text = (
                "P<LBNISSA<<TALAL<<<<<<<<<<<<<<<<<<<<<<<<<<<<\n"
                "LR22028504LBN8001015M3005015123456780123456"
            )
            return OcrResult(full_text=mrz_text, words=[OcrWord("X", 0.9, (0, 0, 10, 10))])
        return OcrResult(full_text="", words=REAL_BIO_WORDS)  # bio region

    def test_both_fields_resolve_via_content_anchored_fallback(self):
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_ocr):
            result = extract_passport_data(self.image_path)
        self.assertEqual(result.father_name.value, "MTANIOS")
        self.assertEqual(result.place_of_birth.value, "ANDAKT")


class FatherNameAnchoredEdgeCasesTest(unittest.TestCase):
    def test_returns_none_when_given_name_is_empty(self):
        self.assertIsNone(_extract_father_name_anchored(REAL_BIO_WORDS, ""))

    def test_returns_none_when_given_name_not_found_in_words(self):
        self.assertIsNone(_extract_father_name_anchored(REAL_BIO_WORDS, "NOTPRESENT"))

    def test_returns_none_when_nationality_anchor_missing(self):
        words = [w for w in REAL_BIO_WORDS if "LEBANESE" not in w.text]
        self.assertIsNone(_extract_father_name_anchored(words, "TALAL"))


class PlaceOfBirthAnchoredEdgeCasesTest(unittest.TestCase):
    def test_returns_none_when_nationality_anchor_missing(self):
        words = [w for w in REAL_BIO_WORDS if "LEBANESE" not in w.text]
        self.assertIsNone(_extract_place_of_birth_anchored(words))


class SelectValueLinesSkipLeadingLabelTest(unittest.TestCase):
    def test_skips_a_leading_label_line(self):
        lines = [
            [_w("Place", 0, 0, 10, 10, 0.9), _w("of", 12, 0, 20, 10, 0.9), _w("birth", 22, 0, 40, 10, 0.9)],
            [_w("HEMLAYA", 0, 20, 40, 30, 0.9)],
        ]
        self.assertEqual(_select_value_lines_skip_leading_label(lines), [lines[1]])

    def test_stops_at_a_trailing_label_line(self):
        lines = [
            [_w("HEMLAYA", 0, 0, 40, 10, 0.9)],
            [_w("date", 0, 20, 20, 30, 0.9)],
        ]
        self.assertEqual(_select_value_lines_skip_leading_label(lines), [lines[0]])

    def test_all_label_lines_yields_nothing(self):
        lines = [[_w("Place", 0, 0, 10, 10, 0.9)]]
        self.assertEqual(_select_value_lines_skip_leading_label(lines), [])


if __name__ == "__main__":
    unittest.main()
