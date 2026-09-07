"""
2026-08-24: this file used to test Tesseract's PSM-retry behavior (see git
history) — Tesseract's default page segmentation sometimes found *no*
text block at all on a small/sparse crop, so ocr_client retried once with
a more eager page-segmentation mode, except for callers (the license back
category table) that needed "found nothing" to stay a trusted, meaningful
signal rather than risk the retry fabricating text from blank-cell paper
texture. That entire mechanism was specific to Tesseract's page-
segmentation-mode concept, which Vision has no equivalent of — see
ocr_client.py's module docstring: ocr_image_array's psm_fallback and psm
parameters are now accepted purely for interface compatibility with
license_ocr.py's existing calls, and are ignored.

What's still worth guarding, and what these tests now check instead:
1. psm_fallback/psm being passed at all (by license_ocr.py's back-category
   calls, which still pass psm_fallback=False) must not raise or change
   behavior — the interface-compatibility promise actually holds.
2. The underlying real-world property the old mechanism protected —
   "a crop with nothing OCR-able on it comes back as a genuinely empty
   OcrResult, not fabricated text" — still holds under Vision, just via a
   different mechanism (there's no separate retry pass to fabricate
   anything from; Vision's single call either finds text or doesn't).

These tests mock the Google Cloud Vision client (see tests/vision_fakes.py)
rather than pytesseract, following ocr_client.py's engine switch.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr import ocr_client
from tests.vision_fakes import empty_response, make_response

_ONE_WORD_RESPONSE = make_response(full_text="GEORGES", word_specs=[("GEORGES", 0.55, (5, 8, 85, 28))])


def _tiny_image():
    return np.full((25, 96, 3), 240, dtype="uint8")


class PsmParamsAreAcceptedButIgnoredTest(unittest.TestCase):
    """psm_fallback and psm must remain valid kwargs (license_ocr.py still
    passes them — see INLINE_LABEL_FIELDS and extract_license_back) but
    must have no effect on the Vision call or its result: one call is
    made either way, with the same outcome."""

    def setUp(self):
        self.fake_client = mock.MagicMock()
        self.fake_client.document_text_detection.return_value = _ONE_WORD_RESPONSE
        self._patch = mock.patch("ocr.ocr_client._get_client", return_value=self.fake_client)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_psm_fallback_true_default_makes_exactly_one_call(self):
        result = ocr_client.ocr_image_array(_tiny_image(), language_hints=["en"])
        self.assertEqual(self.fake_client.document_text_detection.call_count, 1)
        self.assertEqual(result.full_text, "GEORGES")

    def test_psm_fallback_false_still_makes_exactly_one_call_same_result(self):
        # This is the flag license_ocr.extract_license_back passes for the
        # back-category date cells — must behave identically to the
        # default under Vision, not raise or change what's returned.
        result = ocr_client.ocr_image_array(_tiny_image(), language_hints=["en"], psm_fallback=False)
        self.assertEqual(self.fake_client.document_text_detection.call_count, 1)
        self.assertEqual(result.full_text, "GEORGES")

    def test_explicit_psm_value_is_accepted_without_error(self):
        # This is what license_ocr.py's INLINE_LABEL_FIELDS callers pass
        # (psm=6) — must not raise just because Vision has nothing to do
        # with it.
        result = ocr_client.ocr_image_array(_tiny_image(), language_hints=["en"], psm=6)
        self.assertEqual(result.full_text, "GEORGES")


class EmptyCropStaysEmptyTest(unittest.TestCase):
    """The property the old PSM-retry mechanism protected for the license
    back category table (see license_ocr.extract_license_back): a crop
    with nothing OCR-able on it must come back as a genuinely empty
    OcrResult, regardless of psm_fallback, rather than something
    fabricating non-empty text from a blank cell."""

    def setUp(self):
        self.fake_client = mock.MagicMock()
        self.fake_client.document_text_detection.return_value = empty_response()
        self._patch = mock.patch("ocr.ocr_client._get_client", return_value=self.fake_client)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_empty_response_stays_empty_regardless_of_psm_fallback(self):
        for psm_fallback in (True, False):
            with self.subTest(psm_fallback=psm_fallback):
                result = ocr_client.ocr_image_array(_tiny_image(), language_hints=["en"], psm_fallback=psm_fallback)
                self.assertEqual(result.full_text, "")
                self.assertEqual(result.words, [])
                # Exactly one call each time -- no hidden retry mechanism
                # left over that could turn this into fabricated text.
        self.assertEqual(self.fake_client.document_text_detection.call_count, 2)


if __name__ == "__main__":
    unittest.main()
