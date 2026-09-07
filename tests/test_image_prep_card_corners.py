"""
Regression tests for the 2026-09-06 upper-bound area check in
find_card_corners (see ocr/image_prep.py's module-level constant
_MAX_PLAUSIBLE_CARD_AREA_FRACTION for the full diagnosis).

Root cause: a real photo (Richard Bou Tayeh's driving license, held up
against a denim shirt) produced a "successfully deskewed" front card image
that was visually indistinguishable from the raw photo itself (background
denim included), just resized to CARD_SIZE. Every field-region crop after
that read from the wrong part of the image -- e.g. Original
Document.Expiry Date (field "4b") came back "RICHARD" (the holder's own
first name, printed elsewhere on the card) and Original
Document.Number (field "5") came back blank because that crop landed
entirely off the card, on plain denim.

The debug artifacts don't retain the actual raw pre-deskew photo (only the
already-warped 1011x638 output, which is always that fixed size regardless
of whether detection was right), so the true pre-warp quad's exact
dimensions can't be recovered after the fact -- these tests instead
validate the general fix with synthetic images built the same way real
detection works: a plain background with a lighter rectangular "card"
region and added pixel noise (so Canny has real edges to find, the same as
a real photo), at controlled area fractions. This confirms the specific
mechanism (an upper area bound catches a near-full-frame false detection)
without depending on a photo this suite doesn't have -- full confirmation
that this specific photo's failure is fixed still needs a real on-device
retest.
"""

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.image_prep import find_card_corners


def _make_test_image(img_w, img_h, card_w, card_h, seed=0):
    rng = np.random.RandomState(seed)
    img = np.full((img_h, img_w, 3), (60, 80, 140), dtype="uint8")  # dark, saturated "background"
    x0, y0 = (img_w - card_w) // 2, (img_h - card_h) // 2
    cv2.rectangle(img, (x0, y0), (x0 + card_w, y0 + card_h), (230, 230, 230), -1)  # pale "card"
    noise = (rng.randn(img_h, img_w, 3) * 5).astype("int16")
    return np.clip(img.astype("int16") + noise, 0, 255).astype("uint8")


class CardCornersAreaBoundsTest(unittest.TestCase):
    def test_finds_a_legitimately_sized_card(self):
        # ~44% of the frame, clear margin all around -- the ordinary case.
        img = _make_test_image(1000, 700, 700, 440)
        self.assertIsNotNone(find_card_corners(img))

    def test_finds_a_tight_but_plausible_close_up(self):
        # ~80% of the frame -- a close-up photo, still clearly not "the
        # whole frame is the card."
        img = _make_test_image(1000, 700, 900, 620)
        self.assertIsNotNone(find_card_corners(img))

    def test_rejects_a_near_full_frame_false_detection(self):
        # ~97% of the frame -- reproduces the actual failure mode: without
        # the upper bound, this passes the *lower* area check just as
        # easily as a real card region does, and nothing else distinguishes
        # "the whole busy background" from "a card that fills the photo."
        img = _make_test_image(1000, 700, 980, 680)
        self.assertIsNone(find_card_corners(img))

    def test_upper_bound_is_generous_not_hair_trigger(self):
        # Sanity check on the threshold itself: a card at exactly the
        # boundary fraction the constant allows should still be found --
        # this is a change-detector so a future edit to the constant is a
        # deliberate choice, not an accidental tightening.
        # 90% area, safely under _MAX_PLAUSIBLE_CARD_AREA_FRACTION (0.92).
        img = _make_test_image(1000, 700, 950, 660)
        self.assertIsNotNone(find_card_corners(img))


if __name__ == "__main__":
    unittest.main()
