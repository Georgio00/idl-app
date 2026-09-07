"""
Orchestrates the end-to-end autofill: runs passport + license OCR, then
merges the results into the "New IDL" form fields per the source-priority
rules in the project brief (license preferred, passport as fallback where
both carry a field; a few fields are single-source or always manual).

This is the one place that decides *which* extracted value wins for each
form field — the individual OCR modules (passport_ocr, license_ocr) just
extract what's on each document, they don't know about the form.
"""

from __future__ import annotations

from dataclasses import dataclass

from ocr.debug_dump import new_debug_dir
from ocr.license_fields import categories_to_idp
from ocr.license_ocr import LicenseFrontResult, extract_license_back, extract_license_front
from ocr.passport_ocr import extract_passport_data

# Fields that are truly never on any ID document — always manual, per the brief.
NEVER_AUTOFILLED = {
    "Phone", "Email",
    "Issued Document.Number", "Issued Document.Signature",
    "Receipt.Received from", "Receipt.Date", "Receipt.Amount(LBP)",
}


class PipelineError(RuntimeError):
    pass


@dataclass
class FormField:
    value: str
    flagged: bool
    source: str  # "license", "passport", "generated", or "" if not autofilled


@dataclass
class AutofillResult:
    fields: dict[str, FormField]
    # Document-level failures (e.g. "Tesseract binary not found", "language
    # pack 'ara' not installed") that would otherwise vanish silently —
    # every field on the affected document still comes back flagged/empty
    # (so the UI behavior is the same either way), but this is *why*, shown
    # to the user instead of discarded. Empty list = no errors.
    errors: list[str]


def _license_field(front: LicenseFrontResult, key: str) -> tuple[str, bool]:
    read = front.fields.get(key)
    if read is None:
        return "", True
    return read.value, read.flagged


def run_autofill_pipeline(
    passport_path: str, license_front_path: str, license_back_path: str,
    debug: bool = False,
) -> AutofillResult:
    """Runs OCR on all three photos and returns the form fields plus any
    document-level errors encountered along the way.

    debug=True saves every cropped region (and the deskewed full card) to a
    fresh timestamped folder under %LOCALAPPDATA%\\IDL_APP\\debug\\, and logs
    each region's raw OCR text — for diagnosing whether a bad autofill is a
    cropping problem (wrong part of the image) or an OCR problem (right
    crop, but nothing/garbage read from it). See ocr/debug_dump.py.
    """
    debug_dir = new_debug_dir() if debug else None

    passport = extract_passport_data(passport_path, debug_dir=debug_dir)
    front = extract_license_front(license_front_path, debug_dir=debug_dir)
    back = extract_license_back(license_back_path, debug_dir=debug_dir)

    errors: list[str] = []
    if passport.error:
        errors.append(f"Passport: {passport.error}")
    if front.error:
        errors.append(f"License front: {front.error}")
    if back.error:
        errors.append(f"License back: {back.error}")

    result: dict[str, FormField] = {}

    def set_from_license_or_passport(form_key: str, license_key: str, passport_value: str | None, passport_ok: bool):
        lic_value, lic_flagged = _license_field(front, license_key)
        if lic_value:
            result[form_key] = FormField(lic_value, lic_flagged, "license")
        elif passport_value:
            result[form_key] = FormField(passport_value, not passport_ok, "passport")
        else:
            result[form_key] = FormField("", True, "")

    def set_from_passport_or_license(form_key: str, passport_value: str, passport_flagged: bool, license_key: str):
        """Same idea as set_from_license_or_passport but with source
        priority flipped: passport preferred, license as a flagged
        fallback. Used for Surname/First Name/Father's Name/Place of
        B. — per Georgio (2026-08-23), license reads for these have shown
        up wrong *and unflagged* often enough (the given-name/surname
        crops especially) that the passport should win whenever it has a
        usable read: MRZ (checksum-backed, see names_flagged for the
        name-specific caveat) for Surname/First Name, the bio-data-page
        crops (see passport_field_regions.py) for Father's Name/Place of
        B. The license remains the source when the passport has nothing
        (e.g. bio-data-page crop unreadable, or MRZ failed to parse)."""
        if passport_value:
            result[form_key] = FormField(passport_value, passport_flagged, "passport")
        else:
            lic_value, lic_flagged = _license_field(front, license_key)
            if lic_value:
                result[form_key] = FormField(lic_value, lic_flagged, "license")
            else:
                result[form_key] = FormField("", True, "")

    mrz = passport.mrz

    set_from_passport_or_license("Surname", mrz.surname if mrz else "", passport.names_flagged, "1")
    set_from_passport_or_license("First Name", mrz.given_names if mrz else "", passport.names_flagged, "2")

    # Father's name: passport's bio-data page preferred (see
    # passport_field_regions.py — UNCALIBRATED placeholder crop as of
    # 2026-08-23, verify against real photos), license field 13c as
    # fallback. Note the license's 13c is Arabic-only on a real Lebanese
    # license (no printed Latin transliteration), so a license-sourced
    # fallback here will typically still need manual Latin transliteration
    # even when it reads cleanly.
    set_from_passport_or_license("Father's Name", passport.father_name.value, passport.father_name.flagged, "13c")

    # Mother's name: per the brief this is passport-only, but the passport's
    # MRZ has no mother's-name field, and no bio-data-page region has been
    # added for it (unlike father's name/place of birth) — left
    # blank/flagged rather than silently pulling from the license's field
    # 13d, since the brief marks that source invalid.
    result["Mother's Name"] = FormField("", True, "")

    # Date of birth: passport MRZ is checksum-validated (dob_valid, unlike
    # the name fields, so names_flagged's extra confidence gate isn't
    # needed here), so prefer it, with the license's combined "3" field
    # (DOB + place, not split apart) as a flagged fallback if the MRZ
    # read failed.
    if mrz and mrz.date_of_birth and mrz.dob_valid:
        result["Date of B."] = FormField(mrz.date_of_birth, False, "passport")
    else:
        dob3_value, dob3_flagged = _license_field(front, "3")
        result["Date of B."] = FormField(dob3_value, True, "license" if dob3_value else "")

    # Place of birth: passport's bio-data page preferred (see
    # passport_field_regions.py — same UNCALIBRATED-placeholder caveat as
    # father's name above). Falls back to the license's combined field
    # "3" (DOB + place together, unparsed) if the passport crop didn't
    # read anything — always flag that fallback regardless of its own
    # confidence, since it's mixing two facts into one unparsed string.
    if passport.place_of_birth.value:
        result["Place of B."] = FormField(passport.place_of_birth.value, passport.place_of_birth.flagged, "passport")
    else:
        place_value, _ = _license_field(front, "3")
        result["Place of B."] = FormField(place_value, True, "license" if place_value else "")

    addr_value, addr_flagged = _license_field(front, "8")
    result["Address"] = FormField(addr_value, addr_flagged, "license" if addr_value else "")

    blood_value, blood_flagged = _license_field(front, "13b")
    result["Blood Type"] = FormField(blood_value, blood_flagged, "license" if blood_value else "")

    # Original Document group = the driving license's own details.
    num_value, num_flagged = _license_field(front, "5")
    result["Original Document.Number"] = FormField(num_value, num_flagged, "license" if num_value else "")

    date_value, date_flagged = _license_field(front, "4a")
    result["Original Document.Date"] = FormField(date_value, date_flagged, "license" if date_value else "")

    issuer_value, issuer_flagged = _license_field(front, "4c")
    result["Original Document.Place of Issue"] = FormField(issuer_value, issuer_flagged, "license" if issuer_value else "")

    expiry_value, expiry_flagged = _license_field(front, "4b")
    result["Original Document.Expiry Date"] = FormField(expiry_value, expiry_flagged, "license" if expiry_value else "")

    if back.error:
        result["Original Document.Category"] = FormField("", True, "")
    else:
        idp_boxes = categories_to_idp(back.held_categories)
        cat_str = ", ".join(sorted(idp_boxes)) if idp_boxes else ""
        # Flag if no categories were detected at all — more likely a misread
        # than a genuinely uncategorized license.
        result["Original Document.Category"] = FormField(cat_str, not idp_boxes or back.deskew_failed, "license")

    for key in NEVER_AUTOFILLED:
        result[key] = FormField("", False, "")

    return AutofillResult(fields=result, errors=errors)
