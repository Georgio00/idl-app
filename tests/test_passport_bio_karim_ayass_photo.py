"""
Regression tests for two more real-photo bugs found on a sixth real photo
(Karim Ayass, 2026-09-06) -- the same run that also exposed the MRZ
line-swap bug (see test_passport_mrz_line_order.py). This one is notable
for being a phone screenshot of a PDF-viewer app (CamScanner) showing the
passport, not a raw camera photo of the physical document -- which is also
why the widened BIO_SEARCH_REGION (see test_passport_bio_search_region_bounds.py)
now pulls in this photo's own MRZ line and a "Scanned with CamScanner"
watermark as extra noise in the bio words, alongside the real bio-page
content.

REAL_BIO_WORDS is the exact data from this run's
passport_02_bio_search_region_words.json.

Bug 1 -- place_of_birth came back as "BEYROUTH suance" (unflagged, so a
confidently wrong value went out): the real value ("BEYROUTH") is correct,
but the very next clustered line ("suance" -- "Issuance" with its leading
"Is" dropped by OCR, its own "date" word landing on a separate line too far
below to cluster with it) doesn't contain any of _KNOWN_LABEL_KEYWORDS, so
_select_value_lines didn't recognize it as the next field's label and kept
it as a second value line. Fixed by adding "issuance" to
_KNOWN_LABEL_KEYWORDS -- the existing fuzzy-suffix check (built for
exactly this "OCR dropped the label's leading characters" pattern) then
catches "suance" as a truncated match on its own.

Bug 2 -- father_name fell through to the license's Arabic-only fallback
even though the real value ("FADY") was sitting right there in the
content-anchored candidate band, because the band's first line was two
unrelated OCR-garbled fragments ("her", "bom") and "her" happens to be a
real fuzzy-suffix match for "father" ("father" ends with "her") -- so
_is_label_like_line correctly-by-its-own-rules called it label-like, and
_extract_father_name_anchored's old selector (_select_value_lines, which
*stops* at the first label-like line) discarded everything below it,
including the real value. Fixed by switching that one call site to
_select_value_lines_skip_leading_label (already used by
_extract_place_of_birth_anchored for the same "the first line might BE a
label, don't give up" reason) so it skips past that line and keeps
looking instead of bailing out.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.ocr_client import OcrWord
from ocr.passport_ocr import _extract_bio_field, _extract_father_name_anchored


def _w(text, x0, y0, x1, y1, conf):
    return OcrWord(text=text, confidence=conf, box=(x0, y0, x1, y1))


# Real data, Karim Ayass's photo (passport_02_bio_search_region_words.json,
# run 20260906_205654) -- trimmed to the words relevant to these two bugs.
REAL_BIO_WORDS = [
    _w("AYASS", 176, 467, 210, 478, 0.988),
    _w("sport", 65, 469, 90, 478, 0.906),
    _w("seport", 68, 459, 97, 468, 0.863),
    _w("Name", 177, 439, 200, 449, 0.823),
    _w("Bist", 177, 481, 193, 489, 0.565),
    _w("nome", 196, 481, 218, 488, 0.858),
    _w("KARIM", 176, 507, 210, 519, 0.986),
    _w("her", 190, 522, 203, 530, 0.694),
    _w("bom", 204, 522, 221, 530, 0.715),
    _w("FADY", 177, 547, 204, 559, 0.991),
    _w("of", 200, 587, 209, 595, 0.986),
    _w("LEBANESE", 177, 573, 229, 585, 0.982),
    _w("Place", 177, 587, 199, 595, 0.958),
    _w("birth", 211, 587, 229, 595, 0.906),
    _w(",", 229, 587, 233, 595, 0.656),
    _w("BEYROUTH", 175, 595, 232, 615, 0.932),
    _w("suance", 183, 617, 210, 623, 0.858),
    _w("29", 176, 625, 190, 635, 0.988),
    _w("11", 193, 625, 207, 634, 0.991),
    _w("2021", 210, 625, 238, 634, 0.991),
    _w("Expiry", 177, 638, 202, 647, 0.901),
    _w("date", 201, 638, 221, 647, 0.975),
    _w("11", 193, 649, 206, 658, 0.971),
    _w("28", 176, 649, 189, 659, 0.98),
    _w("2026", 210, 649, 237, 658, 0.99),
    # The photo's own MRZ line, now inside the widened bio region -- proven
    # harmless elsewhere (test_passport_bio_search_region_bounds.py), kept
    # here too so these tests reflect the real, full candidate pool.
    _w("P", 44, 692, 55, 706, 0.947),
    _w("<", 54, 691, 66, 705, 0.83),
    _w("LBNAYASS", 66, 690, 153, 706, 0.985),
    _w("<<", 152, 690, 175, 704, 0.836),
    _w("KARIM", 176, 689, 229, 704, 0.982),
    _w("<<<<<<<<<<", 231, 688, 339, 704, 0.724),
    _w("LR24773270LBN0405111M26112841000222809", 44, 712, 459, 733, 0.985),
    _w("<<<<", 460, 713, 503, 729, 0.84),
    _w("62", 503, 712, 524, 729, 0.973),
]


class PlaceOfBirthIssuanceLeakTest(unittest.TestCase):
    def test_does_not_pull_in_the_issuance_date_line(self):
        result = _extract_bio_field(REAL_BIO_WORDS, "place", "place_of_birth", confirm_keyword="birth")
        self.assertEqual(result.value, "BEYROUTH")
        self.assertNotIn("suance", result.value)

    def test_result_is_not_flagged(self):
        # A clean read of a clearly-printed value shouldn't be flagged --
        # this also guards against a future fix "solving" this by just
        # forcing flagged=True instead of actually excluding the noise.
        result = _extract_bio_field(REAL_BIO_WORDS, "place", "place_of_birth", confirm_keyword="birth")
        self.assertFalse(result.flagged)


class FatherNameFalsePositiveLabelTest(unittest.TestCase):
    def test_recovers_fady_past_the_false_positive_label_line(self):
        # "KARIM" appears twice in this data (the real given-name value at
        # y=507 and a fragment of this photo's own MRZ at y=689) --
        # _find_label_line's topmost-match rule must still land on the
        # real one, which is what anchors this whole extraction correctly.
        result = _extract_father_name_anchored(REAL_BIO_WORDS, "KARIM")
        self.assertIsNotNone(result)
        self.assertEqual(result.value, "FADY")

    def test_does_not_return_the_garbled_fragments(self):
        result = _extract_father_name_anchored(REAL_BIO_WORDS, "KARIM")
        self.assertIsNotNone(result)
        self.assertNotIn("her", result.value.lower())
        self.assertNotIn("bom", result.value.lower())


if __name__ == "__main__":
    unittest.main()
