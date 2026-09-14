"""
Regression tests for a real bug hit against real sample photos: autofill
reported "Autofilled 0 field(s), 13 flagged" with zero indication why. Root
cause, traced from the actual debug output (see ocr/debug_dump.py):

1. ocr/license_ocr.py's extract_license_front()/extract_license_back() each
   wrapped their whole per-field loop in one try/except OcrError, so the
   FIRST field's OCR failure (Arabic language pack missing) aborted every
   remaining field on that side of the license, not just the one that failed.
2. ocr/pipeline.py computed passport.error / front.error / back.error but
   never read them — the failure was recorded, then discarded. The GUI had
   no way to show the user *why* every field came back empty.

These tests fail against the pre-fix code and pass against the fix:
per-field isolation in license_ocr, and errors actually surfaced through
AutofillResult.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.ocr_client import OcrError, OcrResult, OcrWord
from ocr.pipeline import run_autofill_pipeline

_REAL_MRZ_TEXT = (
    "P<LBNEL<ALAM<<GEORGES<<<<<<<<<<<<<<<<<<<<<<\n"
    "LR18962688LBN9109076M3009211100145810 6<<20"
)


def _blank_image_files(tmp_path: Path) -> tuple[str, str, str]:
    img = np.zeros((638, 1011, 3), dtype="uint8")
    paths = []
    for name in ("passport.png", "front.png", "back.png"):
        p = tmp_path / name
        cv2.imwrite(str(p), img)
        paths.append(str(p))
    return tuple(paths)  # type: ignore[return-value]


class SystemicLicenseFailureTest(unittest.TestCase):
    """Simulates the actual production failure: every license OCR call
    raises (e.g. missing Arabic language pack). This should be visible to
    the user as an explicit error, not just "everything flagged"."""

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.passport_path, self.front_path, self.back_path = _blank_image_files(self.tmp_dir)

    def _fake_passport_ocr(self, image, language_hints=None, char_whitelist=None, psm_fallback=True, psm=None,
                            keep_arabic=False):
        return OcrResult(full_text=_REAL_MRZ_TEXT, words=[])

    def _always_fail_license_ocr(self, image, language_hints=None, char_whitelist=None, psm_fallback=True, psm=None,
                                  keep_arabic=False):
        raise OcrError("Tesseract language pack(s) not installed: ara. Installed: eng, osd.")

    def test_error_is_surfaced_not_swallowed(self):
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_passport_ocr), \
             mock.patch("ocr.license_ocr.ocr_image_array", side_effect=self._always_fail_license_ocr), \
             mock.patch("ocr.license_ocr.deskew_card", return_value=np.zeros((638, 1011, 3), dtype="uint8")):
            result = run_autofill_pipeline(self.passport_path, self.front_path, self.back_path)

        self.assertTrue(result.errors, "systemic OCR failure must be surfaced in AutofillResult.errors, not discarded")
        joined = " ".join(result.errors)
        self.assertIn("ara", joined)
        self.assertTrue(
            any(e.startswith("License front:") for e in result.errors),
            f"expected a 'License front: ...' error, got: {result.errors}",
        )
        self.assertTrue(
            any(e.startswith("License back:") for e in result.errors),
            f"expected a 'License back: ...' error, got: {result.errors}",
        )

    def test_passport_still_populates_despite_license_failure(self):
        """Per-document isolation: a total license OCR failure must not
        also take down the independently-successful passport extraction."""
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_passport_ocr), \
             mock.patch("ocr.license_ocr.ocr_image_array", side_effect=self._always_fail_license_ocr), \
             mock.patch("ocr.license_ocr.deskew_card", return_value=np.zeros((638, 1011, 3), dtype="uint8")):
            result = run_autofill_pipeline(self.passport_path, self.front_path, self.back_path)

        self.assertEqual(result.fields["Surname"].value, "EL ALAM")
        self.assertEqual(result.fields["First Name"].value, "GEORGES")


class PartialLicenseFailureTest(unittest.TestCase):
    """Only the FIRST license field's OCR call fails; every other field's
    OCR call succeeds normally. Before the fix, one failing field wiped out
    every field after it in iteration order — this proves that no longer
    happens."""

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.passport_path, self.front_path, self.back_path = _blank_image_files(self.tmp_dir)

    def test_only_the_failing_field_is_blank(self):
        call_count = {"n": 0}

        def flaky_ocr(image, language_hints=None, char_whitelist=None, psm_fallback=True, keep_arabic=False, psm=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OcrError("simulated transient OCR failure")
            return OcrResult(full_text="SOMEVALUE", words=[OcrWord("SOMEVALUE", 0.9, (0, 0, 10, 10))])

        with mock.patch("ocr.passport_ocr.ocr_image_array", return_value=OcrResult(full_text=_REAL_MRZ_TEXT, words=[])), \
             mock.patch("ocr.license_ocr.ocr_image_array", side_effect=flaky_ocr), \
             mock.patch("ocr.license_ocr.deskew_card", return_value=np.zeros((638, 1011, 3), dtype="uint8")):
            from ocr.license_ocr import extract_license_front
            result = extract_license_front(self.front_path)

        # FRONT_FIELD_REGIONS dict order: "1" is first, so it's the one
        # that hit the simulated failure; everything after it must still
        # have come through fine despite that first exception.
        self.assertEqual(result.fields["1"].value, "")
        self.assertTrue(result.fields["1"].flagged)
        self.assertEqual(result.fields["2"].value, "SOMEVALUE")
        self.assertFalse(result.fields["2"].flagged)
        # "4a" is a date field: since 2026-09-14 it runs through
        # _normalize_date_field regardless of what OCR returned (see
        # tests/test_date_field_normalization.py) -- "SOMEVALUE" isn't a
        # real date, but the point of this assertion is unchanged, that
        # the field was populated at all rather than left blank by the
        # cascading failure this test guards against. "S"->"5" and "O"->"0"
        # are known digit lookalikes the normalizer corrects unconditionally.
        self.assertEqual(result.fields["4a"].value, "50MEVALUE")


if __name__ == "__main__":
    unittest.main()
