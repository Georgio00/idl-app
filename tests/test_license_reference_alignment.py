"""
Regression tests for the 2026-08-30 reference-alignment wiring in
license_ocr.py (see that module's matching docstring entry and
image_prep.align_to_reference): extract_license_front/back should run
align_to_reference against the bundled reference photo after a successful
deskew, skip it entirely when deskew_card failed (an un-deskewed raw photo
isn't in the right coordinate frame for a reference-based correction to make
sense of), and degrade silently — not crash, not skip OCR — if the
reference images aren't there at all.

Mocks ocr.license_ocr.ocr_image_array and deskew_card, matching the style
used in tests/test_license_address_field.py, so no real photo or Vision
credentials are needed. align_to_reference itself is mocked here too (its
own real-feature-matching behavior is covered by
tests/test_align_to_reference.py) so these tests only check the wiring:
*whether* it's called, and with what.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ocr.license_ocr as license_ocr
from ocr.ocr_client import OcrResult, OcrWord


def _fake_ocr(image, language_hints=None, char_whitelist=None, psm_fallback=True, keep_arabic=False, psm=None):
    return OcrResult(full_text="x", words=[OcrWord("x", 0.9, (0, 0, 1, 1))])


class ReferenceAlignmentWiringTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        import cv2

        self.tmp_dir = Path(tempfile.mkdtemp())
        self.front_path = str(self.tmp_dir / "front.png")
        self.back_path = str(self.tmp_dir / "back.png")
        cv2.imwrite(self.front_path, np.zeros((638, 1011, 3), dtype="uint8"))
        cv2.imwrite(self.back_path, np.zeros((638, 1011, 3), dtype="uint8"))
        # Reset the module-level lazy-load cache before each test so one
        # test's mocked reference dir doesn't leak into the next.
        license_ocr._reference_loaded = False
        license_ocr._reference_front = None
        license_ocr._reference_back = None

    def tearDown(self):
        license_ocr._reference_loaded = False
        license_ocr._reference_front = None
        license_ocr._reference_back = None

    def test_aligns_against_front_reference_after_successful_deskew(self):
        deskewed = np.zeros((638, 1011, 3), dtype="uint8")
        reference = np.ones((638, 1011, 3), dtype="uint8")
        with mock.patch("ocr.license_ocr.ocr_image_array", side_effect=_fake_ocr), \
             mock.patch("ocr.license_ocr.deskew_card", return_value=deskewed), \
             mock.patch.object(license_ocr, "_reference_front", reference), \
             mock.patch.object(license_ocr, "_reference_loaded", True), \
             mock.patch("ocr.license_ocr.align_to_reference") as mocked_align:
            mocked_align.return_value = deskewed
            license_ocr.extract_license_front(self.front_path)

        mocked_align.assert_called_once()
        called_card, called_reference = mocked_align.call_args[0]
        self.assertTrue(np.array_equal(called_card, deskewed))
        self.assertTrue(np.array_equal(called_reference, reference))

    def test_skips_alignment_when_deskew_failed(self):
        with mock.patch("ocr.license_ocr.ocr_image_array", side_effect=_fake_ocr), \
             mock.patch("ocr.license_ocr.deskew_card", return_value=None), \
             mock.patch("ocr.license_ocr.align_to_reference") as mocked_align:
            license_ocr.extract_license_front(self.front_path)

        mocked_align.assert_not_called()

    def test_missing_reference_files_degrade_silently(self):
        deskewed = np.zeros((638, 1011, 3), dtype="uint8")
        with mock.patch("ocr.license_ocr.ocr_image_array", side_effect=_fake_ocr), \
             mock.patch("ocr.license_ocr.deskew_card", return_value=deskewed), \
             mock.patch("ocr.license_ocr._REFERENCE_DIR", Path("/nonexistent/path")), \
             mock.patch("ocr.license_ocr.align_to_reference") as mocked_align:
            result = license_ocr.extract_license_front(self.front_path)

        mocked_align.assert_not_called()
        self.assertIsNone(result.error)

    def test_reference_cards_loaded_only_once(self):
        deskewed = np.zeros((638, 1011, 3), dtype="uint8")
        with mock.patch("ocr.license_ocr.ocr_image_array", side_effect=_fake_ocr), \
             mock.patch("ocr.license_ocr.deskew_card", return_value=deskewed), \
             mock.patch("ocr.license_ocr.align_to_reference", return_value=deskewed), \
             mock.patch("ocr.license_ocr._load_reference_cards", wraps=license_ocr._load_reference_cards) as mocked_load:
            license_ocr.extract_license_front(self.front_path)
            license_ocr.extract_license_front(self.front_path)

        # _load_reference_cards is called on every extract (cheap early-out
        # via _reference_loaded), but the underlying cv2.imread of the
        # actual reference files must only have happened once -- confirmed
        # indirectly here by both calls resolving to the exact same cached
        # ndarray object, not two freshly re-read ones.
        self.assertEqual(mocked_load.call_count, 2)
        first_front_ref = license_ocr._reference_front
        license_ocr.extract_license_front(self.front_path)
        self.assertIs(license_ocr._reference_front, first_front_ref)


if __name__ == "__main__":
    unittest.main()
