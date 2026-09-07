"""
Regression tests for two more real-photo bugs found on a seventh real
photo (Marie Claude El Kareh, 2026-09-06) -- a married woman's passport,
photographed as a two-page spread where the OTHER page (an amendments page
printing "Husband Full Name", "Husband Nationality", "Mother Full Name",
"Registry Place and Number", "Profession") sits above the real bio page in
the frame.

REAL_BIO_WORDS is the exact data from this run's
passport_02_bio_search_region_words.json (full list, not trimmed -- both
bugs need the other page's real content present to reproduce).

Bug 1 -- place_of_birth came back as "NADIA ISHAK" (the MOTHER's name,
unflagged): _find_nationality_line always takes the topmost "lebanese"
match, and this photo has TWO -- the real one (Nationality: LEBANESE, on
the actual bio page) and the husband's ("Husband Nationality: LEBANESE",
on the other page, which happens to sit higher up in the frame). The wrong
one won, and _extract_place_of_birth_anchored read the band below it,
landing on "Mother Full Name / NADIA ISHAK" instead. Fixed with
_restrict_to_bio_page: cut everything above the bio page's own "Republic
of Lebanon / République Libanaise" header line (always the first line on
the real bio page, confirmed across every real photo seen so far), which
removes the other page's content wholesale before any field search runs,
regardless of what that other page happens to say.

Bug 2 -- separately, even after restricting to the real bio page,
place_of_birth's direct label search still found the value ("CHIAH") but
with an unrelated line ("Authority" / "Major General Abbas Ibrahim", a
different column at a similar page height) merged into the same
candidate set -- _is_label_like_line then flagged the whole merged line as
a label (it contains "authority") and _select_value_lines discarded it,
value and all. Root cause: _restrict_to_anchor_column's column-gap
tolerance (6x a word's own height) was looser than the real gap between
the two columns on this photo's tighter field grid. Fixed by lowering the
multiplier to 3x -- confirmed via the full test suite that this doesn't
regress any earlier real photo's legitimate same-value word spacing.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.ocr_client import OcrWord
from ocr.passport_ocr import (
    _extract_bio_field,
    _extract_father_name_anchored,
    _extract_place_of_birth_anchored,
    _find_nationality_line,
    _restrict_to_bio_page,
)


def _w(text, x0, y0, x1, y1, conf):
    return OcrWord(text=text, confidence=conf, box=(x0, y0, x1, y1))


# Real data, Marie Claude El Kareh's photo (passport_02_bio_search_region_words.json,
# run 20260906_211941). Both pages' content, as actually OCR'd.
REAL_BIO_WORDS = [
    # -- The OTHER page (amendments/registry page), sits ABOVE the real
    # bio page in this photo's framing.
    _w("Full", 420, 13, 440, 27, 0.736),
    _w("Name", 442, 13, 472, 28, 0.572),
    _w("Husband", 374, 11, 417, 27, 0.402),
    _w("Husband", 377, 70, 420, 86, 0.785),
    _w("Nationality", 424, 71, 477, 87, 0.806),
    _w("SAMIR", 375, 52, 420, 63, 0.991),
    _w("HILAL", 433, 52, 473, 63, 0.981),
    _w("LEBANESE", 377, 88, 449, 105, 0.985),
    _w("Mother", 377, 106, 414, 119, 0.977),
    _w("Full", 416, 106, 434, 119, 0.863),
    _w("Name", 439, 106, 469, 119, 0.971),
    _w("NADIA", 379, 149, 423, 160, 0.992),
    _w("ISHAK", 427, 149, 469, 160, 0.992),
    _w("Registry", 379, 169, 421, 184, 0.772),
    _w("Place", 424, 169, 450, 184, 0.858),
    _w("and", 456, 169, 474, 184, 0.963),
    _w("Number", 480, 169, 518, 184, 0.781),
    _w("628", 432, 188, 460, 204, 0.807),
    _w("Profession", 378, 210, 435, 220, 0.949),
    _w("Signature", 381, 274, 429, 293, 0.882),
    _w("of", 434, 274, 443, 292, 0.975),
    _w("bearer", 446, 273, 479, 292, 0.924),
    # -- The real bio page, starting with its own header line.
    _w("Republic", 19, 426, 102, 445, 0.973),
    _w("of", 108, 426, 128, 443, 0.99),
    _w("Lebanon", 131, 425, 210, 443, 0.989),
    _w("République", 229, 423, 328, 442, 0.974),
    _w("Libanaise", 334, 422, 418, 441, 0.977),
    _w("EL", 224, 503, 242, 517, 0.978),
    _w("KAREH", 247, 502, 299, 516, 0.992),
    _w("First", 224, 518, 249, 535, 0.919),
    _w("name", 252, 516, 284, 533, 0.965),
    _w("MARIE", 224, 558, 273, 574, 0.992),
    _w("CLAUDE", 278, 556, 338, 572, 0.994),
    _w("Father", 225, 573, 264, 598, 0.707),
    _w("game", 264, 572, 296, 597, 0.688),
    _w("TANIOS", 225, 614, 282, 631, 0.987),
    _w("Nationality", 228, 632, 289, 652, 0.82),
    _w("LEBANESE", 226, 647, 307, 669, 0.975),
    _w("Place", 227, 666, 258, 685, 0.899),
    _w("of", 261, 666, 275, 683, 0.973),
    _w("birth", 276, 665, 304, 683, 0.907),
    _w("CHIAH", 226, 684, 275, 710, 0.965),
    _w("Essuance", 228, 708, 278, 731, 0.817),
    _w("date", 281, 707, 307, 728, 0.966),
    _w("01.02.2023", 228, 725, 320, 743, 0.971),
    _w("Expiry", 229, 743, 264, 762, 0.737),
    _w("date", 266, 742, 292, 761, 0.989),
    _w("31.01.2033", 229, 760, 322, 779, 0.96),
    _w("Date", 395, 625, 422, 643, 0.957),
    _w("of", 425, 625, 437, 642, 0.902),
    _w("birth", 439, 625, 465, 642, 0.958),
    _w("01.12.1952", 419, 643, 508, 660, 0.97),
    _w("Sex", 587, 623, 611, 635, 0.962),
    _w("F", 589, 639, 608, 658, 0.972),
    _w("Authority", 407, 700, 460, 723, 0.791),
    _w("Major", 538, 700, 574, 717, 0.947),
    _w("Genel", 574, 698, 623, 716, 0.823),
    _w("Abbas", 623, 697, 662, 714, 0.936),
]


class RestrictToBioPageTest(unittest.TestCase):
    def test_removes_the_other_pages_content(self):
        restricted = _restrict_to_bio_page(REAL_BIO_WORDS)
        texts = {w.text for w in restricted}
        for other_page_word in ("SAMIR", "HILAL", "NADIA", "ISHAK", "Husband", "Registry", "Profession"):
            self.assertNotIn(other_page_word, texts)

    def test_keeps_the_real_bio_page_content(self):
        restricted = _restrict_to_bio_page(REAL_BIO_WORDS)
        texts = {w.text for w in restricted}
        for real_word in ("KAREH", "MARIE", "CLAUDE", "TANIOS", "CHIAH"):
            self.assertIn(real_word, texts)

    def test_unrestricted_when_header_is_missing(self):
        # Fail-open: if this photo's header never got read at all, don't
        # cut anything -- same behavior as before this fix.
        words_without_header = [w for w in REAL_BIO_WORDS if w.text.lower() not in ("republic", "lebanon")]
        restricted = _restrict_to_bio_page(words_without_header)
        self.assertEqual(len(restricted), len(words_without_header))


class NationalityAnchorPicksTheHolderNotTheHusbandTest(unittest.TestCase):
    def test_unrestricted_search_picks_the_wrong_lebanese(self):
        # Sanity check on the fixture: without restriction, the husband's
        # "LEBANESE" (higher up the page) wins -- otherwise this test
        # wouldn't be exercising the real failure mode.
        line = _find_nationality_line(REAL_BIO_WORDS)
        self.assertEqual(min(w.box[1] for w in line), 88)

    def test_restricted_search_picks_the_real_one(self):
        restricted = _restrict_to_bio_page(REAL_BIO_WORDS)
        line = _find_nationality_line(restricted)
        self.assertEqual(min(w.box[1] for w in line), 647)


class PlaceOfBirthOtherPageBleedTest(unittest.TestCase):
    def test_direct_search_recovers_chiah_not_nadia_ishak(self):
        restricted = _restrict_to_bio_page(REAL_BIO_WORDS)
        result = _extract_bio_field(restricted, "place", "place_of_birth", confirm_keyword="birth")
        self.assertEqual(result.value, "CHIAH")

    def test_anchored_fallback_also_recovers_chiah(self):
        restricted = _restrict_to_bio_page(REAL_BIO_WORDS)
        result = _extract_place_of_birth_anchored(restricted)
        self.assertIsNotNone(result)
        self.assertEqual(result.value, "CHIAH")

    def test_does_not_return_the_mothers_name(self):
        restricted = _restrict_to_bio_page(REAL_BIO_WORDS)
        result = _extract_place_of_birth_anchored(restricted)
        self.assertIsNotNone(result)
        self.assertNotIn("NADIA", result.value)
        self.assertNotIn("ISHAK", result.value)


class FatherNameOtherPageBleedTest(unittest.TestCase):
    def test_direct_search_recovers_tanios(self):
        restricted = _restrict_to_bio_page(REAL_BIO_WORDS)
        result = _extract_bio_field(restricted, "father", "father_name")
        self.assertEqual(result.value, "TANIOS")

    def test_anchored_fallback_also_recovers_tanios(self):
        restricted = _restrict_to_bio_page(REAL_BIO_WORDS)
        result = _extract_father_name_anchored(restricted, "MARIE")
        self.assertIsNotNone(result)
        self.assertEqual(result.value, "TANIOS")


if __name__ == "__main__":
    unittest.main()
