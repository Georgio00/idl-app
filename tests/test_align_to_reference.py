"""
Regression tests for the 2026-08-30 fine-alignment step (see
image_prep.align_to_reference's module note and license_ocr.py's matching
history entry): after deskew_card's 4-corner warp, align the result onto a
saved reference photo via ORB feature matching + homography, correcting the
residual small scale/rotation/translation error a 4-corner warp alone can
leave — confirmed on a real second photo (Rana Rayess) to be enough to
shift a field's read a full row off from where it should be.

Uses the real reference photos bundled at ocr/reference_templates/ (real
printed ID cards have plenty of texture for ORB to key off — ratcheting a
synthetic test image up to the same feature density would just reinvent a
worse copy of what's already sitting there) rather than synthetic images.
"""

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.image_prep import align_to_reference

_REFERENCE_DIR = Path(__file__).resolve().parent.parent / "ocr" / "reference_templates"
_FRONT_REFERENCE_PATH = _REFERENCE_DIR / "license_front.png"
_BACK_REFERENCE_PATH = _REFERENCE_DIR / "license_back.png"


def _perturb(image: np.ndarray, angle_deg: float, scale: float, dx: float, dy: float) -> np.ndarray:
    """Applies a small affine transform to simulate the kind of residual
    misalignment a real photo's deskew can leave (see module docstring) —
    not a huge distortion, just enough to move field text a few percent of
    the card's size, roughly matching what was confirmed on a real photo."""
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, scale)
    matrix[0, 2] += dx
    matrix[1, 2] += dy
    return cv2.warpAffine(image, matrix, (w, h), borderValue=(200, 200, 200))


@unittest.skipUnless(_FRONT_REFERENCE_PATH.exists(), "reference template not present")
class AlignFrontCardTest(unittest.TestCase):
    def setUp(self):
        self.reference = cv2.imread(str(_FRONT_REFERENCE_PATH))

    def test_alignment_meaningfully_reduces_pixel_error(self):
        perturbed = _perturb(self.reference, angle_deg=3.0, scale=0.97, dx=15, dy=-10)
        aligned = align_to_reference(perturbed, self.reference)

        diff_before = cv2.absdiff(perturbed, self.reference).mean()
        diff_after = cv2.absdiff(aligned, self.reference).mean()
        # Not requiring pixel-perfect (JPEG-ish resampling noise is
        # expected) — just that alignment substantially closes the gap a
        # plausible real-world residual misalignment introduces.
        self.assertLess(diff_after, diff_before * 0.5)

    def test_output_matches_reference_size(self):
        perturbed = _perturb(self.reference, angle_deg=-2.0, scale=1.02, dx=-8, dy=12)
        aligned = align_to_reference(perturbed, self.reference)
        self.assertEqual(aligned.shape, self.reference.shape)

    def test_falls_back_unchanged_on_featureless_image(self):
        blank = np.full_like(self.reference, 128)
        result = align_to_reference(blank, self.reference)
        self.assertTrue(np.array_equal(result, blank))


@unittest.skipUnless(_BACK_REFERENCE_PATH.exists(), "reference template not present")
class AlignBackCardTest(unittest.TestCase):
    def test_alignment_meaningfully_reduces_pixel_error(self):
        reference = cv2.imread(str(_BACK_REFERENCE_PATH))
        perturbed = _perturb(reference, angle_deg=-2.0, scale=1.02, dx=-8, dy=12)
        aligned = align_to_reference(perturbed, reference)

        diff_before = cv2.absdiff(perturbed, reference).mean()
        diff_after = cv2.absdiff(aligned, reference).mean()
        self.assertLess(diff_after, diff_before * 0.5)


if __name__ == "__main__":
    unittest.main()
