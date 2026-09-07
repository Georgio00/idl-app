"""
Regression tests for the 2026-08-23 source-priority change: Surname, First
Name, Father's Name, Place of B., and Date of B. should be sourced from the
passport (MRZ for the first two + DOB, the bio-data-page crops for father's
name/place of birth) whenever the passport has a usable read, with the
license only as a flagged fallback — the reverse of the original
license-first priority for Surname/First Name/Father's Name/Place of B.

Also covers the names_flagged safety net: TD3's name field has no checksum,
so a checksum-valid MRZ (passport number/DOB/expiry all correct) can still
have a garbled surname/given-names read. This must come through flagged,
not silently trusted just because mrz.valid is True.

License-side OCR mocks accept char_whitelist/psm_fallback/keep_arabic
kwargs (unused here) since ocr.license_ocr._ocr_crop always passes them —
see tests/test_ocr_keep_arabic.py and tests/test_license_address_field.py
for the license-side keep_arabic behavior itself.

2026-08-30: passport-side mocks updated for the bio-field extraction
rework (see ocr/passport_ocr.py) — extract_passport_data now calls
ocr_image_array twice, not three times: once over the whole
BIO_SEARCH_REGION (returning both father's name and place of birth's
label+value words together, found by label search), then once for the
MRZ band. The fake father's-name/place-of-birth words below carry real
pixel-scale boxes (not the placeholder (0,0,10,10) the old 3-call mocks
used) since the label-search/value-band logic is now geometry-driven —
a zero-size box would make every word land in the same spot and break
the line-clustering it depends on.

2026-09-06: call order swapped again (still two calls) by the rotation-
fallback fix (see ocr/passport_ocr.py's _try_locate_mrz_with_rotation and
extract_passport_data) — MRZ resolution (including a possible whole-photo
rotation) now happens BEFORE bio-page extraction, not after, so a
whole-photo-rotated passport's bio-page fields get read from the same
corrected orientation the MRZ was found in rather than the original one.
The fakes below are updated so call 1 is the MRZ band (which succeeds
immediately on every real-MRZ-text fixture here, so no whole-photo or
rotation calls are needed) and call 2 is the bio-search-region.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.ocr_client import OcrResult, OcrWord
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


class PassportPreferredOverLicenseTest(unittest.TestCase):
    """Passport and license both read successfully, but with DIFFERENT
    values for Surname/First Name/Father's Name/Place of B. — the passport's
    value must win for all four, per Georgio's 2026-08-23 request."""

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.passport_path, self.front_path, self.back_path = _blank_image_files(self.tmp_dir)

    def _fake_passport_ocr(self, image, language_hints=None, **kwargs):
        # extract_passport_data calls this twice: once for the MRZ band
        # (call 1, succeeds immediately here so no whole-photo/rotation
        # calls are needed), then once over the whole BIO_SEARCH_REGION
        # (both father's-name and place-of-birth labels + values, found by
        # label search) — see this module's 2026-09-06 docstring entry.
        self._passport_call_count = getattr(self, "_passport_call_count", 0) + 1
        if self._passport_call_count == 1:
            return OcrResult(full_text=_REAL_MRZ_TEXT, words=[OcrWord(w, 0.9, (0, 0, 10, 10)) for w in "XX"])
        words = [
            OcrWord("Father", 0.9, (50, 100, 90, 112)),
            OcrWord("name", 0.9, (92, 100, 120, 112)),
            OcrWord("SAEED", 0.9, (50, 130, 100, 143)),
            OcrWord("Place", 0.9, (50, 300, 90, 312)),
            OcrWord("of", 0.9, (92, 300, 105, 312)),
            OcrWord("birth", 0.9, (107, 300, 140, 312)),
            OcrWord("RMEICH", 0.9, (50, 330, 110, 343)),
        ]
        return OcrResult(full_text="Father name\nSAEED\nPlace of birth\nRMEICH", words=words)

    def _fake_license_ocr(self, image, language_hints=None, char_whitelist=None, psm_fallback=True, psm=None,
                           keep_arabic=False):
        return OcrResult(full_text="LICENSEGARBAGE", words=[OcrWord("LICENSEGARBAGE", 0.9, (0, 0, 10, 10))])

    def test_passport_wins_for_all_four_fields(self):
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_passport_ocr), \
             mock.patch("ocr.license_ocr.ocr_image_array", side_effect=self._fake_license_ocr), \
             mock.patch("ocr.license_ocr.deskew_card", return_value=np.zeros((638, 1011, 3), dtype="uint8")):
            result = run_autofill_pipeline(self.passport_path, self.front_path, self.back_path)

        self.assertEqual(result.fields["Surname"].value, "EL ALAM")
        self.assertEqual(result.fields["Surname"].source, "passport")
        self.assertEqual(result.fields["First Name"].value, "GEORGES")
        self.assertEqual(result.fields["First Name"].source, "passport")
        self.assertEqual(result.fields["Father's Name"].value, "SAEED")
        self.assertEqual(result.fields["Father's Name"].source, "passport")
        self.assertEqual(result.fields["Place of B."].value, "RMEICH")
        self.assertEqual(result.fields["Place of B."].source, "passport")
        # None of these should be silently swapped for the license's
        # "LICENSEGARBAGE" value just because the license also read something.
        for key in ("Surname", "First Name", "Father's Name", "Place of B."):
            self.assertNotEqual(result.fields[key].value, "LICENSEGARBAGE")


class LicenseFallbackWhenPassportEmptyTest(unittest.TestCase):
    """When the passport's bio-data-page crop reads nothing at all, the
    license must still be used as a fallback rather than leaving the field
    blank — the priority flip shouldn't regress the "always try to fill
    something" behavior."""

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.passport_path, self.front_path, self.back_path = _blank_image_files(self.tmp_dir)

    def _fake_passport_ocr(self, image, language_hints=None, **kwargs):
        # Call 1: the MRZ band, succeeds immediately. Call 2: the
        # bio-search-region OCR finds nothing at all (no labels, so both
        # fields' label search comes up empty).
        self._passport_call_count = getattr(self, "_passport_call_count", 0) + 1
        if self._passport_call_count == 1:
            return OcrResult(full_text=_REAL_MRZ_TEXT, words=[OcrWord("X", 0.9, (0, 0, 10, 10))])
        return OcrResult(full_text="", words=[])  # blank bio-search-region read

    def _fake_license_ocr(self, image, language_hints=None, char_whitelist=None, psm_fallback=True, psm=None,
                           keep_arabic=False):
        return OcrResult(full_text="LICENSEVALUE", words=[OcrWord("LICENSEVALUE", 0.9, (0, 0, 10, 10))])

    def test_father_name_and_place_of_birth_fall_back_to_license(self):
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_passport_ocr), \
             mock.patch("ocr.license_ocr.ocr_image_array", side_effect=self._fake_license_ocr), \
             mock.patch("ocr.license_ocr.deskew_card", return_value=np.zeros((638, 1011, 3), dtype="uint8")):
            result = run_autofill_pipeline(self.passport_path, self.front_path, self.back_path)

        self.assertEqual(result.fields["Father's Name"].value, "LICENSEVALUE")
        self.assertEqual(result.fields["Father's Name"].source, "license")
        self.assertEqual(result.fields["Place of B."].value, "LICENSEVALUE")
        self.assertEqual(result.fields["Place of B."].source, "license")
        # The license fallback for Place of B. must always be flagged (it's
        # an unparsed DOB+place field), regardless of the license OCR's own
        # confidence.
        self.assertTrue(result.fields["Place of B."].flagged)


class CheckedsumValidButGarbledNameTest(unittest.TestCase):
    """A real failure mode found in production debug data: the MRZ's
    checksummed fields (passport number, DOB, expiry) all read correctly,
    but the (checksum-free) name portion of line 1 was garbled by low-
    quality OCR. mrz.valid is True in this situation, but Surname/First
    Name must still come through flagged rather than silently trusted."""

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.passport_path, self.front_path, self.back_path = _blank_image_files(self.tmp_dir)

    def _fake_passport_ocr(self, image, language_hints=None, **kwargs):
        self._passport_call_count = getattr(self, "_passport_call_count", 0) + 1
        if self._passport_call_count == 1:
            # Real MRZ text, but tag every word with a low confidence to
            # simulate the low-quality-crop scenario from the real debug log
            # (average_confidence()=0.25) even though the text itself, once
            # parsed, happens to pass every checksum.
            words = [OcrWord(w, 0.2, (0, 0, 10, 10)) for w in _REAL_MRZ_TEXT.split()]
            return OcrResult(full_text=_REAL_MRZ_TEXT, words=words)
        return OcrResult(full_text="", words=[])  # blank bio-search-region read

    def _fake_license_ocr(self, image, language_hints=None, char_whitelist=None, psm_fallback=True, psm=None,
                           keep_arabic=False):
        return OcrResult(full_text="", words=[])  # license unreadable too

    def test_surname_and_first_name_flagged_despite_valid_checksum(self):
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_passport_ocr), \
             mock.patch("ocr.license_ocr.ocr_image_array", side_effect=self._fake_license_ocr), \
             mock.patch("ocr.license_ocr.deskew_card", return_value=np.zeros((638, 1011, 3), dtype="uint8")):
            result = run_autofill_pipeline(self.passport_path, self.front_path, self.back_path)

        self.assertEqual(result.fields["Surname"].value, "EL ALAM")
        self.assertTrue(result.fields["Surname"].flagged, "low OCR confidence must flag the name even though checksums passed")
        self.assertEqual(result.fields["First Name"].value, "GEORGES")
        self.assertTrue(result.fields["First Name"].flagged)


if __name__ == "__main__":
    unittest.main()
