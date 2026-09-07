"""
Regression tests for the 2026-08-23 license autofill rework: fields whose
printed label sits inline with the value ("13b" blood type and friends —
see ocr/license_ocr.py's INLINE_LABEL_FIELDS) switched from a tight pixel
crop that had to land exactly between label and value, to a generous crop
plus programmatic label-stripping. This was the fix for the recurring
"13b" bug (recalibrated three times, kept drifting back: "13b 0+" read as
"130 OF", later "13b 4", then blank once a narrower whitelist was tried) —
these tests lock in the fix at the levels that actually broke it in
practice: the pure splitting logic (_strip_inline_label) and the
whitelist/config dict's own internal consistency.

2026-08-24: ocr_client.py switched from Tesseract to Google Cloud Vision
(see that module's docstring). This dropped two whole classes of test that
used to live in this file: OcrCropConfigStringTest and
TessdataPrefixConfigTest, which existed specifically to catch a Windows-
only pytesseract config-string-quoting bug ("Unexpected error during
autofill: No closing quotation") — that bug class is structurally
impossible now, since there's no config string or shlex parsing anywhere
in the Vision call path. OcrCropInlineFieldIntegrationTest below is
rewritten to mock the Vision client (see tests/vision_fakes.py) instead of
pytesseract.image_to_data, and no longer asserts anything about
language/psm/whitelist reaching a config string, since char_whitelist and
psm are now inert on this call path (see ocr_client.ocr_image_array's
docstring) — what it still verifies is the part that's still real:
language_hints reaching the Vision call, and _strip_inline_label still
correctly separating the label from the value out of a Vision-shaped word
list.

2026-09-07: added OnWordsCallbackIntegrationTest -- covers _ocr_crop's new
on_words hook (see its docstring), the piece extract_license_front uses to
capture field "13b"'s raw words for _normalize_blood_type_from_words'
fallback (see tests/test_leading_field_number_and_blood_type.py for that
function's own coverage, using the real Charbel Sfeir word data that
motivated it) without changing _ocr_crop's return type.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.license_field_regions import FRONT_FIELD_REGIONS
from ocr.license_ocr import (
    INLINE_LABEL_FIELDS,
    _CLEAN_BLOOD_TYPE_RE,
    _KEEP_ARABIC_FIELDS,
    _normalize_blood_type,
    _normalize_blood_type_from_words,
    _ocr_crop,
    _strip_inline_label,
)
from ocr.ocr_client import OcrWord
from tests.vision_fakes import make_response


def _word(text, x0, x1, y0=0, y1=10):
    return OcrWord(text=text, confidence=0.9, box=(x0, y0, x1, y1))


class StripInlineLabelTest(unittest.TestCase):
    def test_strips_clean_two_word_label_value_pair(self):
        # The confirmed real-world case: "13b" label, then "O+" value with
        # an 11px gap between them (see license_ocr.py's module docstring).
        words = [_word("13b", 55, 138), _word("O+", 232, 317)]
        self.assertEqual(_strip_inline_label(words), "O+")

    def test_strips_garbled_label_regardless_of_content(self):
        # The split must not depend on recognizing what the label word
        # actually says -- confirmed in practice, Tesseract has misread
        # "13b" as "13d", "4b" as "@", "13a" as "18".
        words = [_word("@#$", 55, 138), _word("07/09/2041", 232, 480)]
        self.assertEqual(_strip_inline_label(words), "07/09/2041")

    def test_keeps_multi_word_value_together_after_split(self):
        # "4c" (issuing authority): label, then a multi-word Arabic phrase.
        # Internal value-word gaps must stay smaller than the label/value
        # gap or this incorrectly chops the value too.
        words = [
            _word("4c-label", 100, 140),   # gap to next: 40px
            _word("CGCV", 180, 249),       # gap to next: 8px
            _word("word2", 257, 299),      # gap to next: 9px
            _word("word3", 308, 343),
        ]
        self.assertEqual(_strip_inline_label(words), "CGCV word2 word3")

    def test_picks_widest_gap_not_first_gap(self):
        # If OCR splits the label itself into fragments with small internal
        # gaps, the split must land at the (larger) label-to-value gap, not
        # at the first gap it happens to see.
        words = [
            _word("1", 50, 60),     # gap to next: 3px (label fragment)
            _word("3b", 63, 90),    # gap to next: 30px (real label/value gap)
            _word("O+", 120, 160),
        ]
        self.assertEqual(_strip_inline_label(words), "O+")

    def test_single_word_returned_unchanged(self):
        # Nothing to split against -- can't safely guess a boundary, so
        # this must not silently drop data.
        self.assertEqual(_strip_inline_label([_word("LICENSEVALUE", 10, 90)]), "LICENSEVALUE")

    def test_empty_list_returns_empty_string(self):
        self.assertEqual(_strip_inline_label([]), "")


class InlineLabelFieldsConfigTest(unittest.TestCase):
    def test_blood_type_whitelist_covers_all_valid_blood_types(self):
        # A/B/AB/O crossed with +/- is every blood type that can legally
        # appear on this field -- a whitelist that's missing one of these
        # would silently make that blood type unreadable rather than just
        # low-confidence, which is a worse failure mode than not
        # whitelisting at all.
        whitelist = INLINE_LABEL_FIELDS["13b"]
        self.assertIsNotNone(whitelist)
        for blood_type in ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"):
            for ch in blood_type:
                self.assertIn(ch, whitelist, f"{ch!r} (from {blood_type!r}) missing from 13b's whitelist")

    def test_whitelisted_fields_are_not_in_keep_arabic(self):
        # A field with a Latin/digit-only whitelist can never produce
        # Arabic output in the first place -- keep_arabic on top of that
        # would be a contradictory, dead configuration.
        for key, whitelist in INLINE_LABEL_FIELDS.items():
            if whitelist is not None:
                self.assertNotIn(key, _KEEP_ARABIC_FIELDS,
                                  f"{key!r} is whitelisted (Latin-only) but also in _KEEP_ARABIC_FIELDS")

    def test_mixed_or_arabic_content_fields_are_not_whitelisted(self):
        # Fields with real Arabic content must keep the general ar+eng
        # read -- whitelisting them to a Latin alphabet would make the
        # Arabic content flat-out unrecognizable, not just low-confidence.
        for key in ("3", "4c", "13a", "13c", "13d"):
            self.assertIsNone(INLINE_LABEL_FIELDS[key], f"{key!r} should not be whitelisted (can contain Arabic)")

    def test_arabic_value_fields_are_in_keep_arabic(self):
        # "3" (place of birth), "4c", "13c", "13d" have real Arabic VALUE
        # content (not just stray label/decoration text) -- without
        # keep_arabic, ocr_client's unconditional Arabic-stripping deletes
        # the actual answer before _strip_inline_label ever sees it
        # (confirmed in practice: "13c" read back as just "13", "13d" as
        # just "13d" -- the label digits with the real name gone).
        for key in ("3", "4c", "13c", "13d"):
            self.assertIn(key, _KEEP_ARABIC_FIELDS, f"{key!r} has Arabic value content and needs keep_arabic")


class OcrCropInlineFieldIntegrationTest(unittest.TestCase):
    """Drives _ocr_crop through a mocked Vision client response shaped
    like the real "13b" crop (see license_ocr.py's module docstring
    measurements — same label/value text and relative positions as the
    original Tesseract-era measurement, just expressed as a Vision-shaped
    response now, see tests/vision_fakes.py), to lock in the full call
    chain end to end: language_hints and label-stripping threading
    through correctly together, not just each piece in isolation."""

    def test_blood_type_field_reads_clean_value_end_to_end(self):
        import numpy as np

        response = make_response(
            full_text="13b O+",
            word_specs=[("13b", 0.68, (55, 27, 138, 100)), ("O+", 0.59, (232, 27, 317, 96))],
        )
        img = np.zeros((26, 97, 3), dtype="uint8")

        fake_client = mock.MagicMock()
        fake_client.document_text_detection.return_value = response

        with mock.patch("ocr.ocr_client._get_client", return_value=fake_client):
            whitelist = INLINE_LABEL_FIELDS["13b"]
            read = _ocr_crop(img, (0.0, 0.0, 1.0, 1.0), "front_13b", None, None,
                              char_whitelist=whitelist, psm=6, strip_inline_label=True,
                              language_hints=["en"])

        self.assertEqual(read.value, "O+")
        # Confirms the language override actually reached Vision as
        # ["en"] only, not ["ar", "en"] -- INLINE_LABEL_FIELDS' whitelisted
        # fields have no Arabic content, and this override predates the
        # Vision switch (kept because it's still a reasonable, harmless
        # hint for a known-Latin field even though Vision's OCR quality
        # made it far less load-bearing than it was for Tesseract).
        image_context = fake_client.document_text_detection.call_args.kwargs["image_context"]
        self.assertEqual(list(image_context.language_hints), ["en"])

    def test_every_inline_field_key_exists_in_front_field_regions(self):
        # INLINE_LABEL_FIELDS and FRONT_FIELD_REGIONS must stay in sync --
        # a typo'd or removed key here would silently fall through to
        # extract_license_front's non-inline branch instead of erroring.
        for key in INLINE_LABEL_FIELDS:
            self.assertIn(key, FRONT_FIELD_REGIONS, f"{key!r} in INLINE_LABEL_FIELDS but not FRONT_FIELD_REGIONS")


class OnWordsCallbackIntegrationTest(unittest.TestCase):
    """Drives the real Charbel Sfeir "13b" crop data through _ocr_crop's
    on_words hook plus the same normalize-then-fallback decision
    extract_license_front makes, to lock in the wiring between them (not
    just each piece in isolation)."""

    def test_fused_label_and_value_word_recovers_full_blood_type(self):
        import numpy as np

        # Real device data (run 20260907_195552): the crop OCR'd to
        # exactly these two words -- "13b.4" (label fused with the value's
        # real leading "A", misread as "4") and "+" (the Rh sign).
        response = make_response(
            full_text="13b.4 +",
            word_specs=[("13b.4", 0.89, (24, 15, 265, 89)), ("+", 0.745, (257, 15, 307, 86))],
        )
        img = np.zeros((100, 300, 3), dtype="uint8")

        fake_client = mock.MagicMock()
        fake_client.document_text_detection.return_value = response

        captured_words: list[OcrWord] = []
        with mock.patch("ocr.ocr_client._get_client", return_value=fake_client):
            whitelist = INLINE_LABEL_FIELDS["13b"]
            read = _ocr_crop(img, (0.0, 0.0, 1.0, 1.0), "front_13b", None, None,
                              char_whitelist=whitelist, psm=6, strip_inline_label=True,
                              language_hints=["en"], on_words=captured_words.extend)

        # _strip_inline_label alone still only recovers the Rh sign --
        # this locks in that the bug is real at this layer too, not just
        # in the pure-function tests.
        self.assertEqual(read.value, "+")
        self.assertEqual([w.text for w in captured_words], ["13b.4", "+"])

        # The same decision extract_license_front makes: normalize first,
        # fall back only if that isn't already a clean, complete value.
        final_value = _normalize_blood_type(read.value)
        if not final_value or not _CLEAN_BLOOD_TYPE_RE.fullmatch(final_value):
            fallback_value = _normalize_blood_type_from_words(captured_words)
            if fallback_value:
                final_value = fallback_value
        self.assertEqual(final_value, "A+")

    def test_clean_crop_does_not_need_the_fallback(self):
        import numpy as np

        response = make_response(
            full_text="13b O+",
            word_specs=[("13b", 0.68, (55, 27, 138, 100)), ("O+", 0.59, (232, 27, 317, 96))],
        )
        img = np.zeros((26, 97, 3), dtype="uint8")

        fake_client = mock.MagicMock()
        fake_client.document_text_detection.return_value = response

        captured_words: list[OcrWord] = []
        with mock.patch("ocr.ocr_client._get_client", return_value=fake_client):
            whitelist = INLINE_LABEL_FIELDS["13b"]
            read = _ocr_crop(img, (0.0, 0.0, 1.0, 1.0), "front_13b", None, None,
                              char_whitelist=whitelist, psm=6, strip_inline_label=True,
                              language_hints=["en"], on_words=captured_words.extend)

        final_value = _normalize_blood_type(read.value)
        self.assertTrue(_CLEAN_BLOOD_TYPE_RE.fullmatch(final_value))
        self.assertEqual(final_value, "O+")


if __name__ == "__main__":
    unittest.main()
