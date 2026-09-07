"""
MRZ (Machine Readable Zone) parser for TD3-format passports (ICAO 9303).
Lebanese passports, like almost all passports worldwide, use this format:
two 44-character lines at the bottom of the biodata page.

This does NOT do OCR itself — it takes the two text lines (already read by
whatever OCR engine we plug in) and turns them into validated, structured
fields. The checksums built into the MRZ let us detect OCR mistakes: if a
character was misread, the checksum usually won't match, so we know to flag
that field for manual review instead of silently trusting a bad read.
"""

from dataclasses import dataclass, asdict
from datetime import date


_WEIGHTS = [7, 3, 1]

_CHAR_VALUES = {c: i for i, c in enumerate("0123456789")}
_CHAR_VALUES.update({c: i + 10 for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")})
_CHAR_VALUES["<"] = 0


def _char_value(c: str) -> int:
    return _CHAR_VALUES.get(c, 0)


def _check_digit(data: str) -> int:
    total = 0
    for i, c in enumerate(data):
        total += _char_value(c) * _WEIGHTS[i % 3]
    return total % 10


def _parse_mrz_date(raw: str) -> str | None:
    """MRZ dates are YYMMDD. We can't know the century for certain from the
    field alone, so for date of birth we assume 1900s/2000s based on a
    reasonable cutoff, and for expiry we assume 2000s+ (passports don't
    have 100 year validity)."""
    if len(raw) != 6 or not raw.isdigit():
        return None
    yy, mm, dd = int(raw[0:2]), int(raw[2:4]), int(raw[4:6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None
    return f"{yy:02d}{mm:02d}{dd:02d}"  # caller resolves century


def _resolve_dob_year(yy: int) -> int:
    current_yy = date.today().year % 100
    # Birth years: if yy is plausibly in the future as a birth year, it's 1900s
    return 1900 + yy if yy > current_yy else 2000 + yy


def _resolve_expiry_year(yy: int) -> int:
    # Expiry dates are always in the future relative to issuance; passports
    # issued pre-2000 with 2000s expiry are extremely rare in current use.
    return 2000 + yy


@dataclass
class MRZResult:
    valid: bool
    surname: str
    given_names: str
    document_type: str
    issuing_country: str
    passport_number: str
    passport_number_valid: bool
    nationality: str
    date_of_birth: str | None
    dob_valid: bool
    sex: str
    expiry_date: str | None
    expiry_valid: bool
    personal_number: str
    warnings: list


def parse_td3(line1: str, line2: str) -> MRZResult:
    warnings = []

    line1 = line1.strip().upper().ljust(44, "<")[:44]
    line2 = line2.strip().upper().ljust(44, "<")[:44]

    document_type = line1[0:2].replace("<", "")
    issuing_country = line1[2:5]

    names_field = line1[5:44]
    if "<<" in names_field:
        surname_raw, given_raw = names_field.split("<<", 1)
    else:
        surname_raw, given_raw = names_field, ""
    surname = surname_raw.replace("<", " ").strip()
    given_names = given_raw.replace("<", " ").strip()

    passport_number = line2[0:9].replace("<", "")
    passport_check = line2[9]
    passport_number_valid = _check_digit(line2[0:9]) == int(passport_check) if passport_check.isdigit() else False
    if not passport_number_valid:
        warnings.append("Passport number checksum failed — re-check the OCR read of line 2, positions 1-9.")

    nationality = line2[10:13]

    dob_raw = line2[13:19]
    dob_check = line2[19]
    dob_valid = dob_raw.isdigit() and dob_check.isdigit() and _check_digit(dob_raw) == int(dob_check)
    dob_parsed = _parse_mrz_date(dob_raw)
    date_of_birth = None
    if dob_parsed:
        yy, mm, dd = int(dob_parsed[0:2]), int(dob_parsed[2:4]), int(dob_parsed[4:6])
        year = _resolve_dob_year(yy)
        date_of_birth = f"{dd:02d}/{mm:02d}/{year}"
    if not dob_valid:
        warnings.append("Date of birth checksum failed — verify against the printed date on the passport.")

    sex = line2[20]

    expiry_raw = line2[21:27]
    expiry_check = line2[27]
    expiry_valid = expiry_raw.isdigit() and expiry_check.isdigit() and _check_digit(expiry_raw) == int(expiry_check)
    expiry_parsed = _parse_mrz_date(expiry_raw)
    expiry_date = None
    if expiry_parsed:
        yy, mm, dd = int(expiry_parsed[0:2]), int(expiry_parsed[2:4]), int(expiry_parsed[4:6])
        year = _resolve_expiry_year(yy)
        expiry_date = f"{dd:02d}/{mm:02d}/{year}"
    if not expiry_valid:
        warnings.append("Expiry date checksum failed — verify against the printed date on the passport.")

    personal_number = line2[28:42].replace("<", "")

    overall_valid = passport_number_valid and dob_valid and expiry_valid

    return MRZResult(
        valid=overall_valid,
        surname=surname,
        given_names=given_names,
        document_type=document_type,
        issuing_country=issuing_country,
        passport_number=passport_number,
        passport_number_valid=passport_number_valid,
        nationality=nationality,
        date_of_birth=date_of_birth,
        dob_valid=dob_valid,
        sex=sex,
        expiry_date=expiry_date,
        expiry_valid=expiry_valid,
        personal_number=personal_number,
        warnings=warnings,
    )


if __name__ == "__main__":
    # Sanity test using the sample passport MRZ lines provided during
    # requirements gathering (Georges El Alam's passport). Note: this text
    # was transcribed by eye from a photo for this test, not read by a real
    # OCR engine, so a checksum failure here just means the transcription
    # (or the assumed line break) is slightly off — the parser logic itself
    # is what's being validated, not this particular scan.
    line1 = "P<LBNEL<ALAM<<GEORGES<<<<<<<<<<<<<<<<<<<<<<"
    line2 = "LR18962688LBN9109076M3009211100145810 6<<20"

    result = parse_td3(line1, line2)
    import json
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
