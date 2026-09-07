"""
Regression test that extract_license_front wires field "8" (place of
residence, printed only in Arabic) to keep_arabic=True on its OCR call —
see tests/test_ocr_keep_arabic.py for the underlying ocr_client bug this
depends on (Arabic-script stripping ran unconditionally and deleted the
entire result for an Arabic-only field).

2026-08-23: _KEEP_ARABIC_FIELDS grew beyond just "8" — the inline-label
rework (see license_ocr.py's module docstring) found the same
delete-the-real-value bug hitting "3" (dob + place of birth), "4c"
(issuing authority), "13c"/"13d" (father's/mother's name): all four have
real Arabic *value* content, not just stray label/decoration text, so
Arabic-script stripping was deleting their actual answer before
_strip_inline_label ever got to run. This test was written when "8" was
the only member and asserted that literally; updated to check membership
against the real _KEEP_ARABIC_FIELDS set instead of hardcoding "8" as the
only one, so it stays correct as that set evolves rather than needing a
hand update every time it does — while still catching the original bug
class (a field that should NOT have Arabic-content requesting it
anyway, or vice versa).

Mocks ocr.license_ocr.ocr_image_array and deskew_card, matching the style
used in tests/test_pipeline_error_handling.py, so no real Tesseract
install or sample photo is needed.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.license_field_regions import FRONT_FIELD_REGIONS
from ocr.license_ocr import _KEEP_ARABIC_FIELDS, extract_license_front
from ocr.ocr_client import OcrResult, OcrWord


class AddressFieldKeepsArabicTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        import cv2

        self.tmp_dir = Path(tempfile.mkdtemp())
        self.front_path = str(self.tmp_dir / "front.png")
        cv2.imwrite(self.front_path, np.zeros((638, 1011, 3), dtype="uint8"))

    def test_field_8_ocr_call_requests_keep_arabic(self):
        def fake_ocr(image, language_hints=None, char_whitelist=None, psm_fallback=True, keep_arabic=False, psm=None):
            # 2026-09-06: field "8" is now read back from `words` (see
            # license_ocr._words_to_text / rebuild_text_from_words), not
            # `full_text` -- the word list here must carry the same text
            # the old full_text-only fake asserted, or this test would be
            # exercising a path this field no longer actually uses.
            text = "ADDR" if not keep_arabic else "بيروت"
            return OcrResult(full_text=text, words=[OcrWord(text, 0.9, (0, 0, 40, 20))])

        def recording_ocr(image, language_hints=None, char_whitelist=None, psm_fallback=True, keep_arabic=False, psm=None):
            return fake_ocr(image, language_hints, char_whitelist, psm_fallback, keep_arabic)

        with mock.patch("ocr.license_ocr.ocr_image_array", side_effect=recording_ocr) as mocked, \
             mock.patch("ocr.license_ocr.deskew_card", return_value=np.zeros((638, 1011, 3), dtype="uint8")):
            result = extract_license_front(self.front_path)

        field_8_call = next(c for c in mocked.call_args_list if c.kwargs.get("keep_arabic"))
        self.assertIsNotNone(field_8_call, "expected at least one OCR call with keep_arabic=True (field 8)")

        self.assertEqual(result.fields["8"].value, "بيروت")

        # Every field's OCR call must have requested keep_arabic if and
        # only if that field key is in _KEEP_ARABIC_FIELDS -- catches both
        # a field wrongly left off (its real Arabic value would get
        # deleted) and a field wrongly added (Arabic decoration/label text
        # would leak into a Latin-only field's result).
        calls_by_field = dict(zip(FRONT_FIELD_REGIONS.keys(), mocked.call_args_list))
        self.assertEqual(set(calls_by_field), set(FRONT_FIELD_REGIONS),
                          "expected one OCR call per front-of-card field")
        for key, call in calls_by_field.items():
            expected = key in _KEEP_ARABIC_FIELDS
            self.assertEqual(call.kwargs.get("keep_arabic", False), expected,
                              f"field {key!r}: keep_arabic should be {expected} "
                              f"(key in _KEEP_ARABIC_FIELDS: {expected})")


class AddressFieldRealDuplicateGlyphTest(unittest.TestCase):
    """2026-09-06 real photo (Younes Hamzeh): field "8" surfaced as
    Arabic text with a spurious trailing "00" -- Vision returned both "8"
    (the real field-number digit, confidence 0.986) and "00" (confidence
    0.554) for two boxes overlapping at ~85% IoU, the same glyph read two
    conflicting ways. ocr_client._dedupe_overlapping_words (see that
    module's tests) drops the low-confidence duplicate; this test locks in
    that the fix actually reaches the surfaced Address value end to end,
    going through the real (unmocked) ocr_client.ocr_image_array /
    _run_vision path via a faked Vision client response, same style as
    tests/test_license_inline_label_strip.py's OcrCropInlineFieldIntegrationTest."""

    def setUp(self):
        import tempfile
        import cv2

        self.tmp_dir = Path(tempfile.mkdtemp())
        self.front_path = str(self.tmp_dir / "front.png")
        cv2.imwrite(self.front_path, np.zeros((638, 1011, 3), dtype="uint8"))

    def test_duplicate_glyph_does_not_leak_into_address_value(self):
        from tests.vision_fakes import make_response

        # Exact real word/box/confidence data from front_8_words.json
        # (Younes Hamzeh, run 20260906_191304).
        response = make_response(
            full_text="8\n00\nالبترون",
            word_specs=[
                ("8", 0.986, (65, 70, 104, 119)),
                ("00", 0.554, (69, 71, 103, 119)),
                ("البترون", 0.966, (218, 55, 436, 119)),
            ],
        )
        fake_client = mock.MagicMock()
        fake_client.document_text_detection.return_value = response

        with mock.patch("ocr.ocr_client._get_client", return_value=fake_client), \
             mock.patch("ocr.license_ocr.deskew_card", return_value=np.zeros((638, 1011, 3), dtype="uint8")):
            result = extract_license_front(self.front_path)

        self.assertEqual(result.fields["8"].value, "البترون")
        self.assertNotIn("00", result.fields["8"].value)


if __name__ == "__main__":
    unittest.main()
