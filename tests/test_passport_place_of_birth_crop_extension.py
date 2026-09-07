"""
End-to-end regression test for the 2026-09-06 BIO_SEARCH_REGION widening
(see passport_field_regions.py and test_passport_bio_search_region_bounds.py).

REAL_BIO_WORDS below is the same real Frederic Elias data used in
test_passport_bio_label_disambiguation.py (from
passport_02_bio_search_region_words.json) -- with the pre-fix 0.755 bottom
edge, Vision never even saw the printed place-of-birth VALUE ("RMEICH"),
so no amount of label-matching logic could have found it; that's the bug
the wider crop (0.83) fixes.

There's no way to re-run real OCR against the *widened* crop from this
test suite (no image fixtures/network access here) -- that still needs a
real on-device run to fully confirm. What this test CAN do, and does, is
add one extra synthetic word standing in for "RMEICH" at the exact
position it was measured to occupy on the real photo (pixel-verified
against the raw photo image: full-photo y=921-937, converted to this
crop's local coordinates by subtracting the region's known 180px top
offset -- see the constants below), and confirm the *existing* extraction
tiers (unchanged by this fix -- only the crop size changed) correctly
pick it up. This at least proves the fallback logic is ready to use the
word the wider crop should now let Vision actually detect, rather than
just hoping the crop change alone is sufficient.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.ocr_client import OcrWord
from ocr.passport_ocr import _extract_bio_field, _extract_place_of_birth_anchored


def _w(text, x0, y0, x1, y1, conf):
    return OcrWord(text=text, confidence=conf, box=(x0, y0, x1, y1))


# Exact real data from passport_02_bio_search_region_words.json (Frederic
# Elias, run 20260906_202630) -- the full word list this time (not
# trimmed), since _extract_place_of_birth_anchored needs the real
# "Nationality"/"LEBANESE" anchor words too.
REAL_BIO_WORDS = [
    _w("1999", 549, 693, 597, 709, 0.993),
    _w("ELIAS", 246, 513, 301, 528, 0.991),
    _w("FREDERIC", 247, 583, 341, 600, 0.991),
    _w("Lebanon", 141, 401, 242, 425, 0.989),
    _w("JULIETTE", 465, 36, 546, 55, 0.988),
    _w("Republic", 0, 401, 105, 424, 0.988),
    _w("Father", 250, 608, 294, 620, 0.986),
    _w("04", 516, 693, 541, 709, 0.985),
    _w("ZIAD", 247, 654, 291, 668, 0.984),
    _w("LR2348750", 552, 461, 664, 475, 0.98),
    _w("13", 486, 693, 510, 710, 0.972),
    _w("of", 111, 401, 137, 423, 0.965),
    _w("LEBANESE", 248, 696, 346, 713, 0.963),
    _w("Date", 458, 673, 493, 687, 0.96),
    _w("Place", 248, 716, 289, 727, 0.957),
    _w("République", 265, 401, 396, 425, 0.951),
    _w("of", 539, 210, 553, 231, 0.95),
    _w("Passeport", 5, 498, 99, 514, 0.949),
    _w("ABOUEZZI", 553, 35, 647, 54, 0.949),
    _w("Passport", 5, 516, 86, 531, 0.943),
    _w("Libanaise", 403, 402, 513, 426, 0.941),
    _w("birth", 514, 673, 550, 687, 0.939),
    _w("of", 497, 673, 513, 687, 0.932),
    _w("KZ6580", 747, 460, 824, 475, 0.931),
    _w("25", 520, 95, 546, 112, 0.929),
    _w("of", 289, 715, 306, 727, 0.928),
    _w("RL", 472, 436, 513, 464, 0.927),
    _w("Nationality", 247, 676, 326, 690, 0.893),
    _w("/", 659, 65, 669, 87, 0.876),
    _w("First", 245, 535, 280, 549, 0.851),
    _w("/", 248, 402, 260, 424, 0.837),
    _w("/", 605, 210, 614, 231, 0.781),
    _w("fession", 490, 120, 541, 136, 0.765),
    _w("Place", 528, 65, 566, 87, 0.73),
    _w("Number", 601, 65, 658, 87, 0.722),
    _w("/", 518, 403, 530, 425, 0.709),
    _w("bearer", 558, 210, 602, 231, 0.647),
    _w("nat", 298, 608, 321, 620, 0.594),
    _w("Registry", 465, 65, 524, 87, 0.583),
    _w("www", 553, 403, 651, 427, 0.528),
    _w("Signature", 467, 210, 534, 231, 0.514),
    _w("and", 570, 65, 596, 87, 0.506),
    _w("c", 602, 674, 615, 688, 0.494),
]

# Real position, pixel-measured directly off the raw photo (row-darkness
# scan over passport_00_full_photo.png, column band x=245-345): "RMEICH"
# occupies full-photo y=921-937. The bio crop's top edge is
# int(0.15 * 1203) = 180, so in this crop's local coordinate system (what
# every OcrWord box above is already expressed in) that's y=741-757.
# x-range estimated from the visible photo against neighbouring
# same-column fields' own measured widths (e.g. "ZIAD" 247-291, "FREDERIC"
# 247-341) -- not pixel-exact, but well within the column-restriction
# logic's tolerance either way.
_RMEICH_WORD = _w("RMEICH", 247, 741, 315, 757, 0.95)


class PlaceOfBirthCropExtensionTest(unittest.TestCase):
    def test_without_the_value_word_anchored_extraction_finds_nothing(self):
        # Documents the actual pre-fix bug: even the content-anchored
        # fallback (which doesn't need "birth" to have been read at all)
        # comes back empty, because the word simply isn't in the data --
        # the old 0.755 crop cut it off before OCR ever saw it.
        result = _extract_place_of_birth_anchored(REAL_BIO_WORDS)
        self.assertIsNone(result)

    def test_direct_label_search_still_does_not_confirm_on_this_photo(self):
        # Unchanged by the crop fix: this photo's "Place of birth" label
        # line never got its "birth" word read by Vision at all (only
        # "Place"/"of"), so the confirm_keyword tier correctly stays empty
        # regardless of what the wider crop adds below it -- the extra
        # value word doesn't retroactively fix a different, already-
        # understood limitation (see test_passport_bio_label_disambiguation.py).
        words = REAL_BIO_WORDS + [_RMEICH_WORD]
        result = _extract_bio_field(words, "place", "place_of_birth", confirm_keyword="birth")
        self.assertEqual(result.value, "")

    def test_with_the_value_word_present_anchored_extraction_recovers_rmeich(self):
        # The actual fix under test: once the wider BIO_SEARCH_REGION lets
        # Vision see the value line at all (simulated here by adding the
        # one real-position word back in), the *existing*, already-shipped
        # content-anchored fallback (anchors on "LEBANESE", reads the band
        # below it -- no logic changes needed) picks it up correctly.
        words = REAL_BIO_WORDS + [_RMEICH_WORD]
        result = _extract_place_of_birth_anchored(words)
        self.assertIsNotNone(result)
        self.assertEqual(result.value, "RMEICH")

    def test_full_tier_order_ends_up_with_rmeich_not_empty(self):
        # Mirrors extract_passport_data's actual call order: try the direct
        # label search first, fall back to the content-anchored tier only
        # if that came back empty.
        words = REAL_BIO_WORDS + [_RMEICH_WORD]
        place_of_birth = _extract_bio_field(words, "place", "place_of_birth", confirm_keyword="birth")
        if not place_of_birth.value:
            anchored = _extract_place_of_birth_anchored(words)
            if anchored is not None:
                place_of_birth = anchored
        self.assertEqual(place_of_birth.value, "RMEICH")


if __name__ == "__main__":
    unittest.main()
