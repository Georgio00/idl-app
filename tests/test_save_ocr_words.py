"""
Regression test for debug_dump.save_ocr_words (added 2026-08-30 alongside
passport_ocr.py's label-anchored bio-field search) — dumps the OCR engine's
raw word list (text/confidence/box) to a JSON file when debug mode is on,
so a field that comes back empty/wrong on a real photo can be diagnosed
from real ground truth instead of guessing at another recalibration.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.debug_dump import save_ocr_words
from ocr.ocr_client import OcrWord


class SaveOcrWordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def test_writes_words_as_json(self):
        words = [
            OcrWord("Father", 0.91, (50, 100, 90, 112)),
            OcrWord("name", 0.88, (92, 100, 120, 112)),
        ]
        save_ocr_words(self.tmp_dir, "passport_02_bio_search_region", words)

        path = Path(self.tmp_dir) / "passport_02_bio_search_region_words.json"
        self.assertTrue(path.exists())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["text"], "Father")
        self.assertEqual(payload[0]["box"], [50, 100, 90, 112])

    def test_noop_when_debug_dir_is_none(self):
        # Must not raise -- this is called unconditionally from
        # extract_passport_data regardless of whether debug mode is on.
        save_ocr_words(None, "x", [OcrWord("a", 0.9, (0, 0, 1, 1))])

    def test_noop_on_empty_word_list(self):
        save_ocr_words(self.tmp_dir, "empty", [])
        path = Path(self.tmp_dir) / "empty_words.json"
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
