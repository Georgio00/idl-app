"""
Regression test for a real bug hit against real license photos: the
place-of-residence field (front "8"), printed only in Arabic, came back
completely blank on every read — not low-confidence, an actual empty
string — even though IDL_APP_DEBUG_OCR=1 crops showed clearly legible
Arabic text.

Root cause: ocr_client always ran the recognized text through
_strip_arabic() before returning it (see that function's docstring —
every other license/passport field is Latin-script, with Arabic only ever
bleeding in as noise to discard). Field "8" has no Latin content at all,
so stripping Arabic from its result stripped the entire (correct) OCR
result down to nothing.

Fix: ocr_image_array (and friends) take a keep_arabic flag that skips the
stripping step, and license_ocr._ocr_crop threads it through for exactly
field "8" (ocr.license_ocr._KEEP_ARABIC_FIELDS).

2026-08-24: rewritten to mock the Google Cloud Vision client (see
tests/vision_fakes.py) instead of pytesseract.image_to_data, following
ocr_client.py's switch from Tesseract to Vision — the keep_arabic
behavior itself is engine-agnostic (_strip_arabic is a pure string
function applied the same way regardless of which engine produced the
text), so only the mocking layer changes here, not what's being verified.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr import ocr_client
from tests.vision_fakes import make_response

# A single Arabic word ("بيروت" - Beirut), as Vision's response would
# structure it: one word, Arabic-script text.
_ARABIC_WORD_RESPONSE = make_response(full_text="بيروت", word_specs=[("بيروت", 0.72, (5, 8, 65, 26))])


def _tiny_image():
    return np.full((40, 140, 3), 240, dtype="uint8")


class KeepArabicTest(unittest.TestCase):
    def setUp(self):
        self.fake_client = mock.MagicMock()
        self.fake_client.document_text_detection.return_value = _ARABIC_WORD_RESPONSE
        self._patch = mock.patch("ocr.ocr_client._get_client", return_value=self.fake_client)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_default_strips_arabic_to_blank(self):
        result = ocr_client.ocr_image_array(_tiny_image(), language_hints=["ar", "en"])

        self.assertEqual(result.full_text, "")
        self.assertEqual(result.words, [])

    def test_keep_arabic_preserves_arabic_only_text(self):
        result = ocr_client.ocr_image_array(_tiny_image(), language_hints=["ar", "en"], keep_arabic=True)

        self.assertEqual(result.full_text, "بيروت")
        self.assertEqual(len(result.words), 1)
        self.assertEqual(result.words[0].text, "بيروت")


if __name__ == "__main__":
    unittest.main()
