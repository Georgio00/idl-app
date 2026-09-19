"""
Passport pipeline: locate the MRZ (bottom of the biodata page), OCR it, and
hand the two raw lines to mrz_parser for validated parsing. Also extracts
Father's Name and Place of Birth from the bio-data page above the MRZ (see
passport_field_regions.py) — neither is in the MRZ itself.

The MRZ is printed in a fixed monospace OCR-B font in a predictable spot (the
bottom ~24.5% of the page, see _crop_mrz_band), so we crop that band before
OCR rather than OCR-ing the whole photo — this avoids the photo/background
text confusing the read and mirrors the region-based approach used for the
license.

OCR engine: this module uses ocr.ocr_client — until 2026-08-24, it used
ocr.easyocr_client instead, deliberately different from license_ocr.py, for
a specific reason: real-world testing (2026-08-23) found ocr_client's
then-current Tesseract backend could not read text over this passport's
anti-counterfeiting security pattern at all (confirmed empty/garbage reads
even on a hand-picked, perfectly-cropped, high-resolution sample of the
affected fields, across several preprocessing attempts), while EasyOCR read
the same crops correctly and with high confidence — see
ocr/easyocr_client.py's docstring for the full comparison. Now that
ocr_client.py itself is backed by Google Cloud Vision rather than
Tesseract (see that module's docstring), the passport reads through the
same engine as the license again: Vision's document-text-detection model
is expected to handle the security pattern at least as well as EasyOCR did
(not yet re-verified against a real passport photo — if it turns out not
to, reverting this one import to ocr.easyocr_client brings back the
EasyOCR path, which is unchanged and still present). This also drops the
passport's PyTorch/EasyOCR dependency (a large, slow install) entirely.
OcrError is still imported from ocr_client either way — every engine this
module has used raises the same exception type, so callers don't need to
know which engine is in play.

2026-08-30: father's name / place of birth extraction changed from two
tight, fixed-fraction crops (one OCR call each) to one OCR call over a
single generous BIO_SEARCH_REGION (see passport_field_regions.py),
followed by finding each field's value in that result by searching for
its printed label ("Father name" / "Place of birth") and reading the
words positioned in the band below it — see _find_label_line,
_value_band_below, and _extract_bio_field below. This replaced the fixed
fractions after they broke a second time on a second real photo (see
passport_field_regions.py's history): a fixed fraction of the raw photo
only describes the one sample it was measured from, since the passport,
unlike the license, has no deskew-to-a-canonical-size step to make a
fraction framing-independent (see that module's docstring for why).
Label-anchored search sidesteps the whole class of bug: a field's
position is now found relative to its own label's detected size and
location in *this* photo, not assumed from a previous photo's proportions.

2026-08-30 (later same day): two more fixes found by pulling a real photo's
raw OCR word dump (Rana Rayess — see ocr/debug_dump.py's save_ocr_words)
instead of guessing at another recalibration:

- Father's Name came back empty (falling through to the license's
  Arabic-only field) because Vision never detected the "Father name"
  label at all on this photo — not a split-word case (_find_label_line's
  fallback above didn't help), the label text simply wasn't read. Added
  _extract_father_name_positional: when the direct label search comes up
  empty, locate the value positionally instead, using the "First name"
  and "Nationality" labels (both reliably detected) as top/bottom anchors
  — the given name's value line sits directly under "First name", and the
  father's name value sits below *that*, still above "Nationality", even
  with its own label missing.
- Place of Birth was pulling in the next field's mis-read label ("once
  date", a garbled "Issuance date") and a different column's "Author[ity]"
  field, because _value_band_below's band is intentionally generous (see
  its own docstring) and _extract_bio_field used to just blindly keep the
  first two clustered lines in it. Fixed two ways: _filter_low_confidence
  drops stray low-confidence noise words (like a "SU" fragment measured at
  conf 0.58 overlapping the real value's line) before clustering, and
  _select_value_lines now stops as soon as a line looks like a *label*
  itself (_is_label_like_line, checked against _KNOWN_LABEL_KEYWORDS)
  rather than always taking up to _MAX_VALUE_LINES regardless of content.

2026-08-30 (third fix, same day): the MRZ itself (which drives Surname,
First Name, and DOB) was still the one thing in this module trusting a
fixed fraction of the raw photo (_crop_mrz_band, bottom 24.5%) — the same
class of bug the two fixes above moved away from for the bio-page fields.
Confirmed on the same real photo: its two-page-spread framing puts the
actual MRZ at roughly 58-61% down the frame, entirely outside that band,
so the crop simply never contained it and every MRZ-derived field failed
outright. _try_locate_mrz + extract_passport_data's fixed-band-then-
whole-photo fallback fixes this the same way as the bio fields: try the
fast, narrow, calibrated path first (still correct and still the common
case for a normally-framed single-page photo), and if that finds no
MRZ-shaped lines, fall back to scanning the *whole* photo instead of
giving up — _extract_mrz_lines already knows how to pick real MRZ lines
out of a large OCR result by shape (see its own docstring), so the wider
net doesn't need new noise-filtering logic, just a wider region to apply
the existing one to.

2026-09-01: a third real photo (Talal Issa) showed a harder version of the
08-30 problem: this time Vision detected almost none of the bio-page's
printed LABELS at all within BIO_SEARCH_REGION — not "Father name", not
"Place of birth", not even "First name" or "Nationality" (the anchors
_extract_father_name_positional relies on). All that came through were
the field VALUES themselves, each on its own line, in a consistent order:
given name, then father's name, then nationality, then place of birth —
same relative order confirmed on the Rana Rayess photo too, just with
more of the labels missing this time. Label text is small, thin printed
type — apparently more fragile to OCR on some photos (lighting/angle/scan
quality) than the large, bold, high-confidence VALUES sitting right next
to it. So rather than add yet another label-based special case, this
fix stops depending on label text where it doesn't have to and anchors on
CONTENT instead, which read far more reliably on both real photos so far:
- The given name is already known independently and reliably — it's the
  checksum-backed MRZ's given_names — so _extract_father_name_anchored
  locates that exact text's line in the bio words (no label needed at
  all) and takes what's between it and the nationality value below.
- "LEBANESE" (or a name containing it, handling a merge/OCR-noise like
  Talal's "LEBANESEL") is itself a reliable anchor — every Lebanese
  passport prints it, in bold, and it read at >=0.89 confidence on every
  sample seen — so _find_nationality_line locates it directly and
  _extract_place_of_birth_anchored reads the band below it, same
  generosity/noise-filtering as the label-anchored version, just skipping
  over "Place of birth"'s own label line first if Vision happened to
  catch it (see _select_value_lines_skip_leading_label) rather than
  requiring it.
These are added as further fallback tiers (direct label search, then the
existing label-based positional fallback, then these content-anchored
ones), tried only when the earlier tiers come back empty — a normally-
printed, clearly-OCR'd photo where the labels *are* read keeps using the
faster, simpler direct search it already had.

2026-09-06: a fourth real photo (Younes Hamzeh) exposed two more issues,
found the same way as always — pulling the real per-word OCR dump (see
ocr/debug_dump.py's save_ocr_words) rather than guessing:

- Place of birth came back as "ace of EL BATROUN". Root cause: this bio
  page's "Place of birth" label partially misread as just "ace of" (the
  leading "Pl" dropped entirely, not merely low-confidence). Since "ace of"
  contains neither "place" nor "birth", _is_label_like_line didn't
  recognize it as a label and _select_value_lines_skip_leading_label kept
  it as if it were real value content instead of skipping past it.
  _is_label_like_line now also treats a word as label-like when it's a
  long-enough suffix of a known label keyword (OCR drops a word's leading
  characters far more often than its trailing ones), which generalizes to
  any similarly-truncated label rather than special-casing this one.
- Father's name still fell through to the license's Arabic-only fallback.
  Root cause, found via the same word dump: this bio page has TWO columns
  at the same page heights (a left name/nationality column, a right
  passport-number/date-of-birth column), and neither _line_cluster (used
  to pull a full label/value line out from a single matched word) nor the
  band-scanning in _extract_father_name_positional/_extract_father_name_
  anchored/_extract_place_of_birth_anchored constrained candidates to the
  same column as their anchor — only a left edge was ever enforced. A
  same-height value from the *other* column repeatedly got merged into
  "the line" or "the band", corrupting the result (concretely: the given
  name's own line picked up an unrelated left-column fragment, and the
  band between given-name and nationality picked up "Date of birth"/a
  passport-number fragment from the right column). Fixed by having
  _line_cluster only keep the horizontally-contiguous run of same-row
  words around its seed (a real gap this wide is a column jump, not
  continued label/value text), and adding the new _restrict_to_anchor_column
  helper, which applies the same contiguous-run logic to every candidate
  band this module scans before clustering it into lines.

  A same-day follow-up misdiagnosed a second, unrelated angle on this same
  bug: an early version of this fix assumed the wrong bio-page line was
  this photo's "given name" (going by which name a human would expect
  first), concluded an extra "Surname" line sat between the given-name
  anchor and Nationality, and had _extract_father_name_anchored skip a
  leading line that echoed the MRZ's surname to compensate. That was
  backwards — _find_label_line already anchors on the MRZ's *actual*
  given_names text regardless of which physical line it prints on, and
  once the column-restriction fix above was in place, the real father's-
  name line was already the very next line after that anchor, nothing to
  skip. The surname-skip didn't just fail to help: on this exact photo the
  father's own name happens to read identically to the surname (a
  realistic Arab-naming-convention coincidence — a person's family name
  and their father's personal name both being "Younes" is entirely
  plausible, not a fixture quirk), so skipping "a line that echoes the
  surname" threw away the correct answer and reintroduced the Arabic
  fallback. Reverted rather than patched further: no real photo seen so
  far actually needs a surname-skip once candidates are column-restricted.

2026-09-06 (later same day): a fifth real photo (Karim Ayass) exposed a
new failure mode entirely — this one wasn't a raw camera photo of the
physical passport at all, but a phone screenshot of a PDF-viewer app (CamScanner)
displaying it, with the app's own UI chrome (status bar, toolbar, a
"Scanned with CamScanner" watermark) framing the actual page. Surname came
back as "73270LBN0405111M26112841000222809" and First Name as "62" —
neither a name, both clearly fragments of the MRZ's own digit line. Root
cause, confirmed by feeding this exact photo's real line 2 text into
parse_td3's line1 parameter and getting character-for-character the same
garbled output: _extract_mrz_lines' assumption that OCR's full_text always
lists line1 (names) before line2 (digits) — true on every normally-framed
photo seen so far — didn't hold on this one, so the two lines were fed to
parse_td3 swapped. Fixed with _resolve_mrz_line_order: rather than add a
new positional/shape heuristic (another assumption that could break on
some future framing), it uses the MRZ's own existing checksum
self-validation to pick whichever of the two possible orderings is
actually internally consistent, trying both through parse_td3 and keeping
the one with more valid checksums. Applied right before parse_td3 is
called for real, so raw_line1/raw_line2 (shown to callers) and the parsed
MRZResult always agree with each other.

2026-09-06 (later still, same day): an eighth real photo (Richard Bou
Tayeh) turned out to be rotated a full 90 degrees from upright — the whole
photo, MRZ included, ran bottom-to-top instead of left-to-right (confirmed
by viewing the actual saved passport_00_full_photo debug image). Autofill
showed Father's Name="134" and Place of B."Lebanon of" (a garbled fragment
of the bio page's own "Republic of Lebanon" header), because neither of
the two existing MRZ tiers, nor BIO_SEARCH_REGION's fixed-fraction crop,
expect the whole frame itself to be sideways — unlike the license pipeline,
this module has no deskew-to-canonical-orientation step at all (see this
docstring's opening paragraph for why a passport's fields are read directly
off the raw photo instead of a corrected crop). Fixed by adding a third MRZ
tier, tried only when both existing 0-degree tiers (fixed band, then whole
photo) come back completely empty: scan the whole photo again at each
90-degree rotation in turn (see _try_locate_mrz_with_rotation). Tried last,
not first, so a normally-framed upright photo — still the common case —
pays no extra OCR cost. When a rotation is what actually locates the MRZ,
extract_passport_data now runs bio-page extraction (father's name, place of
birth) against that SAME corrected orientation rather than the original
raw photo — moved to after MRZ resolution in the function body for exactly
this reason, since BIO_SEARCH_REGION's fixed fraction is just as
orientation-dependent as the MRZ crop was and would otherwise keep sampling
the wrong part of a still-rotated photo even after the MRZ itself was
correctly located.

2026-09-06 (a real on-device retest showed the above wasn't the actual
fix): the rotation-probing tier above never even ran on the real photo it
was built for. Pulling this photo's real bio-search-region word dump (see
_looks_rotated_90's docstring for the full breakdown) showed Google Vision
successfully reads correct text ("RICHARD", "MILAD", the MRZ digits, etc.,
each at >=0.9 confidence) EVEN ON A PHYSICALLY SIDEWAYS PHOTO — Vision's
text recognition tolerates rotation far better than this module assumed,
so the existing whole-photo MRZ tier (tried before any rotation probing)
already succeeded on its own, without needing a rotation at all. The real
bug was narrower than first diagnosed: BIO_SEARCH_REGION's fixed-fraction
CROP still samples the wrong pixels of a physically-rotated photo no matter
how well Vision reads whatever text happens to land inside that wrong
crop, and the line-clustering logic every bio-field extraction tier relies
on (which assumes horizontal rows of text) can't make sense of words whose
real text runs vertically down the image either. Fixed with a second,
independent rotation check specific to bio-page extraction
(_resolve_bio_words): if the original orientation's bio crop doesn't
contain the bio page's own "Republic of Lebanon" header line, and most of
its words have the narrow-tall bounding-box shape that only happens when
the underlying photo is physically rotated (_looks_rotated_90 — this ratio
was the clearest, most orientation-agnostic signal in the real data, far
more reliable than trying to infer anything from field-extraction success/
failure), try the bio crop again at each 90-degree rotation and adopt
whichever one's crop actually contains the header. The whole-photo MRZ
rotation tier above is kept as further defense in depth (a future photo
might have MRZ text Vision can't read sideways even though this one's
was fine), but the bio-page fix above is what a real retest on this exact
photo actually needed.

2026-09-19: the very same Younes Hamzeh photo referenced above (the "ace of
EL BATROUN" fix) resurfaced with a different symptom once that fix held:
Place of B. came back as "EL BATROUN 26:07 2022" -- the correct place, plus
some other printed date on the bio page trailing after it (the real date of
birth is read separately and correctly off the MRZ as 03/02/1956, so this
wasn't that -- most likely the issuance or expiry date, unlabeled in the
value band because its own label line either wasn't read by Vision at all
or fell outside the band). Root cause: this trailing line contains no
substring or fuzzy suffix match against any _KNOWN_LABEL_KEYWORDS entry
(it's just digits, a colon, and a space), so _is_label_like_line returned
False for it and _select_value_lines happily kept it as this field's own
second value line, under the _MAX_VALUE_LINES cap, and _field_read_from_
lines joined both lines with a space. Fixed with a new, purely-structural
check rather than another keyword: _is_date_like_line flags a clustered
line as not-a-value whenever it contains no letters at all (only digits and
date/time punctuation). Every field these selection helpers currently serve
-- place of birth, father's name -- is inherently textual, so a legitimate
second value line for either always contains at least one letter; a line
that's pure digits/punctuation is never that, regardless of which date or
number format produced it, which generalizes past this one photo's exact
"26:07 2022" shape.

2026-09-06 (a third pass, same day -- a real retest on a DIFFERENT rotated
photo showed the second fix still wasn't right): a ninth real photo
(Charbel Sfeir) was also rotated ~90 degrees, and Place of B. still came
back as "Lebanon of" even with the header-line check above in place.
Pulling this photo's real bio-crop word dumps at every orientation
(original, 90 clockwise, 90 counter-clockwise, 180) showed why in two
separate ways: first, this photo's header word itself split as "ublic" --
not a misread, but BIO_SEARCH_REGION's crop boundary genuinely clipping the
leading "Rep" off "Republic" at this photo's particular framing, so the
correct rotation's own crop never contained a line matching the "republic"
keyword at all. Second, and more fundamentally: Vision reads "Lebanon" and
"Libanaise" as clean, correctly-recognized words in EVERY orientation
tried, including the still-sideways original -- confirming (the same
lesson as the MRZ fix above, learned a second time) that a keyword being
present doesn't mean the crop is right-side up, only that Vision managed
to recognize that word's characters regardless of orientation. Fixed by
dropping the header-keyword dependency entirely: _resolve_bio_words now
uses two purely geometric checks instead -- _looks_rotated_90 (is this
crop's content still sideways) to pick a 90-degree rotation to try, and
_bio_orientation_looks_correct (do "First name"/"Father name"/
"Nationality"/"Place of birth" -- always printed in that top-to-bottom
order on every real photo seen this session -- actually appear in that
order in this rotation) to tell the correct 90-degree direction apart from
the upside-down one, since rotating an already-sideways photo either
clockwise OR counter-clockwise produces equally normal-looking (wide,
short) word boxes, but only one direction is actually right-side up."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from ocr.debug_dump import log_ocr_result, save_crop, save_ocr_words
from ocr.image_prep import crop_region
from ocr.mrz_parser import MRZResult, parse_td3
from ocr.ocr_client import OcrError, OcrResult, OcrWord, ocr_image_array
from ocr.passport_field_regions import BIO_SEARCH_REGION

# MRZ lines are 44 chars of A-Z, 0-9, and filler "<". OCR sometimes misreads
# "<" as a space or other punctuation, so we normalize before length-checking.
_ALLOWED_CHARS = re.compile(r"[^A-Z0-9<]")

# Below this average OCR confidence for the MRZ band, don't trust a
# checksum-valid MRZ's SURNAME/GIVEN NAMES specifically. Unlike the
# passport number, date of birth, and expiry date, the TD3 name field has
# no checksum digit of its own — a badly-OCR'd name can still produce an
# overall "valid" MRZ (every *checksummed* field happened to read
# correctly) while the name portion is noise. Confirmed against a real
# sample: passport/DOB/expiry checksums all passed while the given-names
# read came back as garbage. Same bar as license_ocr.LOW_CONFIDENCE_THRESHOLD.
NAME_LOW_CONFIDENCE_THRESHOLD = 0.60

# Same bar, reused for the bio-data-page fields below (father's name,
# place of birth) — consistent with license_ocr's per-field flagging.
BIO_LOW_CONFIDENCE_THRESHOLD = 0.60


@dataclass
class FieldRead:
    value: str
    confidence: float
    flagged: bool


@dataclass
class PassportOcrResult:
    mrz: MRZResult | None
    raw_line1: str | None
    raw_line2: str | None
    error: str | None  # set if MRZ couldn't be located/read at all
    # Whether mrz.surname / mrz.given_names specifically should be
    # flagged despite mrz.valid — see NAME_LOW_CONFIDENCE_THRESHOLD above.
    # Defaults True (flag) so any early-return path (image unreadable,
    # OCR failed outright) fails safe rather than silently unflagged.
    names_flagged: bool = True
    # From the bio-data page, not the MRZ (see passport_field_regions.py).
    # Default to a flagged-empty read so early-return paths (image
    # unreadable) still give callers a usable value instead of needing a
    # None-check everywhere.
    father_name: FieldRead = field(default_factory=lambda: FieldRead("", 0.0, True))
    place_of_birth: FieldRead = field(default_factory=lambda: FieldRead("", 0.0, True))


def _crop_mrz_band(image: np.ndarray) -> np.ndarray:
    """Crops the bottom band of the passport photo where the MRZ lives.
    Calibrated 2026-08-23 against a real sample passport (see
    passport_field_regions.py's docstring for the same sample/process):
    the original placeholder (bottom 22%) cut off the tops of the
    characters on the MRZ's first line just enough that OCR either missed
    the line entirely (EasyOCR) or read it as noise (Tesseract) — moving
    the boundary up to 24.5% fully includes both MRZ lines and was
    confirmed to produce a checksum-valid parse end to end.

    2026-08-30: this is now only the *first*, fast-path attempt, not the
    only one — a differently-framed real photo (a two-page spread) put the
    real MRZ well outside this band entirely, so extract_passport_data
    falls back to scanning the whole photo (see _try_locate_mrz) when this
    band doesn't yield two valid MRZ lines. Kept as the first attempt
    rather than removed: it's faster and has far less unrelated text for
    _extract_mrz_lines to search through on the common case of a normally-
    framed single bio-page photo, where it's still exactly right."""
    h, w = image.shape[:2]
    y0 = int(h * 0.755)
    return image[y0:h, 0:w]


def _try_locate_mrz(
    image_region: np.ndarray,
    debug_dir: str | None,
    debug_name: str,
    errors: list[str],
) -> tuple[tuple[str, str], OcrResult] | None:
    """OCRs image_region and looks for two valid MRZ lines in the result
    (see _extract_mrz_lines). Returns (lines, ocr_result) on success so the
    caller can reuse the same OCR pass for names_flagged's confidence
    check, or None if OCR failed outright or no MRZ-shaped lines were
    found — either way, on None the *caller* decides whether to try a
    wider region, not this function; keeping the two tiers separate here
    is what let 2026-08-30's fixed-band-first / whole-photo-fallback
    (see extract_passport_data) reuse this same OCR-and-scan logic twice
    without duplicating it."""
    try:
        ocr_result = ocr_image_array(image_region, language_hints=["ar", "en"])
    except OcrError as e:
        if str(e) not in errors:
            errors.append(str(e))
        return None
    log_ocr_result(debug_name, ocr_result.full_text, ocr_result.average_confidence(), False)
    lines = _extract_mrz_lines(ocr_result.full_text)
    if lines is None:
        return None
    return lines, ocr_result


# Rotation codes tried, in order, by _try_locate_mrz_with_rotation when the
# MRZ can't be located at the photo's original orientation at all. Clockwise
# and counter-clockwise are both tried (not just one) since a phone or
# camera can be held either way when a photo ends up sideways, and 180 is
# tried too (upside down) — cheap to also cover and no real photo has needed
# it yet, but nothing rules it out for a future one.
_ROTATION_ATTEMPTS: tuple[tuple[str, int], ...] = (
    ("rot90cw", cv2.ROTATE_90_CLOCKWISE),
    ("rot180", cv2.ROTATE_180),
    ("rot90ccw", cv2.ROTATE_90_COUNTERCLOCKWISE),
)


def _try_locate_mrz_with_rotation(
    image: np.ndarray,
    band: np.ndarray,
    debug_dir: str | None,
    errors: list[str],
) -> tuple[np.ndarray, tuple[str, str], OcrResult] | None:
    """Tries to locate the MRZ at the photo's original orientation first —
    the fixed bottom band, then the whole photo (see _try_locate_mrz and
    extract_passport_data's history for why both of those tiers already
    exist) — and only if BOTH come back completely empty, tries the whole
    photo again at each 90/180-degree rotation in turn (_ROTATION_ATTEMPTS).

    Added 2026-09-06 after a real photo (Richard Bou Tayeh) turned out to be
    rotated a full 90 degrees from upright — the whole photo, MRZ included,
    ran bottom-to-top instead of left-to-right. Unlike the license pipeline
    (which deskews every photo to a canonical, upright crop before reading
    any field), the passport pipeline has no such step at all (see this
    module's opening docstring for why passport fields are read directly off
    the raw photo instead) — so nothing here corrected for a rotated
    whole-photo framing before this fix, and both existing 0-degree tiers
    failed outright on this photo for the same underlying reason:
    _crop_mrz_band's fixed bottom-band crop and even a full whole-photo OCR
    scan both still expect the printed MRZ lines to run left-to-right, which
    doesn't hold when the whole photo itself is sideways.

    Tried only as a last resort (after both 0-degree tiers) so a normally-
    framed upright photo — still the common case — pays no extra OCR cost:
    each rotation attempt is a full extra Vision call. Returns
    (oriented_image, lines, ocr_result) on success, where oriented_image is
    `image` itself unless a rotation was needed, in which case it's the
    rotated copy — extract_passport_data uses this returned image (not the
    original) for the bio-page extraction that follows, since a fixed-
    fraction crop like BIO_SEARCH_REGION is just as orientation-dependent as
    the MRZ crop was and would otherwise keep sampling the wrong part of a
    still-rotated photo even after the MRZ itself was correctly located.
    Returns None if no orientation at all yields two MRZ-shaped lines."""
    result = _try_locate_mrz(band, debug_dir, "passport_mrz_band", errors)
    if result is not None:
        return (image, *result)

    save_crop(debug_dir, "passport_01b_mrz_whole_photo_fallback", image)
    result = _try_locate_mrz(image, debug_dir, "passport_mrz_whole_photo", errors)
    if result is not None:
        return (image, *result)

    for name, rotation_code in _ROTATION_ATTEMPTS:
        rotated = cv2.rotate(image, rotation_code)
        save_crop(debug_dir, f"passport_01c_mrz_whole_photo_{name}", rotated)
        result = _try_locate_mrz(rotated, debug_dir, f"passport_mrz_whole_photo_{name}", errors)
        if result is not None:
            return (rotated, *result)

    return None


def _mrz_checksum_score(mrz: MRZResult) -> int:
    """How many of the MRZ's three self-checking fields (passport number,
    date of birth, expiry date) came back checksum-valid — used by
    _resolve_mrz_line_order below to tell a correctly-ordered (line1,
    line2) pair from a swapped one without any new, unverified heuristic:
    the checksums are already computed by parse_td3 for an entirely
    different reason (flagging OCR misreads), and a swapped pair almost
    never passes any of them by chance (each is a real check-digit formula
    over specific character positions, not just "looks number-shaped")."""
    return sum([mrz.passport_number_valid, mrz.dob_valid, mrz.expiry_valid])


def _resolve_mrz_line_order(line1: str, line2: str) -> tuple[str, str]:
    """TD3's two 44-char MRZ lines are always meant to be read top-to-bottom
    (line1 = document type/country/names, line2 = passport number/DOB/
    expiry/checksums) -- _extract_mrz_lines assumes whatever OCR's
    full_text listed last is line2 and the one before it is line1, which
    holds for every normally-framed photo seen so far. A real photo (Karim
    Ayass, 2026-09-06 -- a phone screenshot of a PDF-viewer app showing the
    passport, not a raw camera photo of the physical document) broke that
    assumption: the two lines came back swapped, and parse_td3 silently
    turned line2's own digit content into "Surname"/"First Name" (confirmed
    by reproducing the exact garbled production values -- "73270LBN0405111
    M26112841000222809" / "62" -- character for character by feeding this
    photo's real line2 text into parse_td3's line1 parameter).

    Rather than add a new, unverified heuristic for "which line looks like
    names vs digits" (fragile against exactly the kind of OCR noise this
    project keeps running into), this uses the MRZ format's own built-in
    self-check: try both orderings through parse_td3 and keep whichever
    produces more valid checksums (see _mrz_checksum_score) -- the correct
    order passes real checksums by construction, while a swapped pair
    passes them only by coincidence, which real testing (this fix's own
    regression test) shows essentially never happens. Ties -- including
    both orders scoring 0, e.g. a badly misread MRZ where neither ordering
    validates -- keep the original (line1, line2) order, unchanged from
    before this fix, since there's no signal here to prefer a swap."""
    forward = parse_td3(line1, line2)
    backward = parse_td3(line2, line1)
    if _mrz_checksum_score(backward) > _mrz_checksum_score(forward):
        return line2, line1
    return line1, line2


def _normalize_mrz_line(raw: str) -> str:
    line = raw.strip().upper().replace(" ", "<")
    line = _ALLOWED_CHARS.sub("<", line)
    return line.ljust(44, "<")[:44]


def _extract_mrz_lines(full_text: str) -> tuple[str, str] | None:
    candidates = []
    for raw_line in full_text.splitlines():
        if len(raw_line.strip()) < 20:
            continue
        line = _normalize_mrz_line(raw_line)
        # A real MRZ line is dense in letters/digits with only some "<"
        # fillers, unlike stray OCR noise off the rest of the page — but
        # line 1 (names) can legitimately be sparse for a short name: e.g.
        # "P<LBNEL<ALAM<<GEORGES<<<<..." (our own reference sample) has
        # only 17 non-filler characters. The >=20 line-length pre-filter
        # above already screens out most noise, so this just needs to catch
        # lines that are 20+ chars of near-total filler — not reject short
        # real names. 10 is low enough for that while still requiring
        # meaningfully MRZ-like content (document type + country + some
        # name/number, at minimum).
        if len(line.replace("<", "")) >= 10:
            candidates.append(line)

    if len(candidates) < 2:
        return None
    # The MRZ is always the last two matching lines (bottom of the page).
    return candidates[-2], candidates[-1]


# Arabic script (main block U+0600-06FF, Arabic Supplement U+0750-077F)
# plus the invisible bidi marks (U+200E/U+200F, LRM/RLM) that sometimes
# ride along with Arabic OCR output. This file is UTF-8 (Python 3
# default), so the literal range below is exactly those codepoints —
# verified with a unit test rather than trusted by eye.
_ARABIC_RE = re.compile("[؀-ۿݐ-ݿ‎‏]+")


def _prefer_latin(text: str) -> str:
    """father_name/place_of_birth are printed on the passport in BOTH
    Arabic and Latin script, stacked together in the same crop (see
    passport_field_regions.py) — but the New IDL form is Latin-only, so
    strip the Arabic portion and any stray bidi marks rather than showing
    staff a field with both scripts mashed together. Falls back to the
    untouched original text if stripping would leave nothing behind (e.g.
    only the Arabic line actually got read this time) — a raw Arabic read
    is still more useful to a bilingual staff member than an empty field,
    and it'll be flagged for review either way if confidence was low."""
    latin_only = re.sub(r"\s+", " ", _ARABIC_RE.sub(" ", text)).strip()
    return latin_only or text


def _word_center_y(w: OcrWord) -> float:
    return (w.box[1] + w.box[3]) / 2.0


def _word_height(w: OcrWord) -> float:
    return max(w.box[3] - w.box[1], 1)


def _line_cluster(words: list[OcrWord], seed: OcrWord, y_tol_frac: float = 0.6) -> list[OcrWord]:
    """Every word on the same printed line as `seed`: y-centers within
    y_tol_frac * seed's own line height of each other, AND horizontally
    contiguous with `seed` (see max_gap below). Used to recover a label's
    full line (e.g. both "Father" and "name" from "Father name") from just
    the one word that matched a keyword search — the label's true bottom
    edge is the max across the whole line, not just the one matched word's
    own box.

    2026-09-06: added the horizontal-contiguity restriction after a real
    photo (Younes Hamzeh) showed this matching text from a completely
    different column of a two-column bio-page layout, just because it
    happened to sit at the same page height — a value from the right-hand
    "Date of birth"/passport-number column landed on the exact same
    printed row as a left-hand name value and got merged into "the line"
    with it, corrupting every downstream field read anchored on that line.
    A real multi-word label's own words sit close together (normal word
    spacing); a gap this wide between consecutive same-row words is a
    column jump, not a continuation of the same label/value — so this now
    only keeps the contiguous run of same-row words starting from `seed`
    and extending outward while consecutive gaps stay under that bound,
    the same scale-relative-to-text-height reasoning already used
    elsewhere in this module (see _value_band_below)."""
    tol = _word_height(seed) * y_tol_frac
    seed_cy = _word_center_y(seed)
    same_row = sorted(
        (w for w in words if abs(_word_center_y(w) - seed_cy) <= tol),
        key=lambda w: w.box[0],
    )
    seed_idx = next(i for i, w in enumerate(same_row) if w is seed)
    max_gap = _word_height(seed) * 4
    lo = hi = seed_idx
    while lo > 0 and same_row[lo].box[0] - same_row[lo - 1].box[2] <= max_gap:
        lo -= 1
    while hi < len(same_row) - 1 and same_row[hi + 1].box[0] - same_row[hi].box[2] <= max_gap:
        hi += 1
    return same_row[lo:hi + 1]


def _find_label_line(
    words: list[OcrWord], keyword: str, confirm_keyword: str | None = None,
) -> list[OcrWord] | None:
    """Finds a printed field label by keyword (case-insensitive substring
    match against a single detected word — Vision detects "Father name" as
    two separate words, "Place of birth" as three) and returns every word
    on that same printed line (see _line_cluster). Searches in top-to-
    bottom, left-to-right order (not whatever order the OCR response
    happened to list words in) so the first match is always the topmost
    one on the page — matters if the keyword could ever appear twice.

    Falls back to checking adjacent-word concatenations (e.g. "Fa" +
    "ther" -> "father") before giving up — a real photo (Rana Rayess,
    2026-08-30) came back with father_name entirely empty despite the
    label being legible in the source photo, and an OCR engine splitting
    a short label word oddly (especially over a passport's busy security-
    pattern background) is a plausible cause a single-word match can't
    catch. Returns None if no word or adjacent pair contains the keyword
    at all.

    2026-09-06: `confirm_keyword` disambiguates a keyword that can
    genuinely match more than one printed label on the same bio page.
    Confirmed on two separate real photos (Younes Hamzeh, then Frederic
    Elias) that "place" alone matches BOTH the real "Place of birth" label
    AND an unrelated "Place and Number of Registry/Registration" line that
    happens to print higher up on the page — since this function always
    took the topmost match, that unrelated line won outright on both
    photos (on the second one, its value band wasn't even empty, so a
    confidently wrong "25 fession"-style value went out unflagged instead
    of falling through to a safer tier). When set, a candidate match only
    counts if `confirm_keyword` also appears on that same printed line
    (e.g. "birth" alongside "place") — every match that doesn't confirm is
    skipped in favor of a later (further down the page) one that does,
    rather than accepting the first hit unconditionally. Returns None,
    same as an outright miss, when no match confirms — the caller falls
    through to a content-anchored fallback tier instead of trusting a
    label match that couldn't be verified."""
    kw = keyword.lower()
    confirm = confirm_keyword.lower() if confirm_keyword else None
    ordered = sorted(words, key=lambda w: (w.box[1], w.box[0]))
    for w in ordered:
        if kw in w.text.lower():
            line = _line_cluster(words, w)
            if confirm is None or any(confirm in x.text.lower() for x in line):
                return line
    for a, b in zip(ordered, ordered[1:]):
        if kw in (a.text + b.text).lower():
            line = _line_cluster(words, a)
            if confirm is None or any(confirm in x.text.lower() for x in line):
                return line
    return None


def _cluster_into_lines(words: list[OcrWord]) -> list[list[OcrWord]]:
    """Groups words into printed lines by vertical proximity, returned
    top-to-bottom with each line's own words left-to-right."""
    if not words:
        return []
    lines: list[list[OcrWord]] = []
    for w in sorted(words, key=lambda w: w.box[1]):
        cy = _word_center_y(w)
        for line in lines:
            line_top = min(x.box[1] for x in line)
            line_bottom = max(x.box[3] for x in line)
            if line_top - 4 <= cy <= line_bottom + 4:
                line.append(w)
                break
        else:
            lines.append([w])
    lines.sort(key=lambda line: min(w.box[1] for w in line))
    for line in lines:
        line.sort(key=lambda w: w.box[0])
    return lines


def _value_band_below(words: list[OcrWord], label_line: list[OcrWord]) -> list[OcrWord]:
    """Words in the band directly below a label line, roughly left-aligned
    with it — candidates for that field's printed value. The band's size
    is derived from the label line's own height rather than a fixed pixel
    or fraction amount, so it scales automatically with the source photo's
    resolution/zoom: a differently-framed real photo changes the label's
    size and the value's distance from it by the same proportion, so a
    band defined relative to the label (not the whole image) keeps
    tracking the value correctly regardless of framing — see this module
    and passport_field_regions.py's history for the fixed-fraction
    approach this replaced and why it kept breaking on new photos.

    Sized generously (well past where the real value line(s) were measured
    to end on the one sample checked pixel-by-pixel — see
    passport_field_regions.py's 2026-08-27 history entry) since
    _extract_bio_field below only keeps the closest couple of printed
    lines out of whatever this returns, not everything in the band — the
    generosity here is a safety margin against undershooting, not a
    precision boundary."""
    label_top = min(w.box[1] for w in label_line)
    label_bottom = max(w.box[3] for w in label_line)
    label_left = min(w.box[0] for w in label_line)
    label_height = max(label_bottom - label_top, 1)

    band_top = label_bottom
    band_bottom = label_bottom + label_height * 6
    band_left = label_left - label_height * 2  # a little left slack

    return _restrict_to_anchor_column(
        [w for w in words if band_top <= _word_center_y(w) <= band_bottom and w.box[0] >= band_left],
        anchor_left=band_left,
    )


def _restrict_to_anchor_column(candidates: list[OcrWord], anchor_left: float) -> list[OcrWord]:
    """Keeps only the candidates that sit in the same horizontal column as
    the anchor (a label or a known value's own line), dropping anything
    from a visibly different column at the same page height — added
    2026-09-06 after a real photo (Younes Hamzeh) showed a right-hand-
    column field ("Date of birth", a passport-number fragment) landing at
    the same height as this field's real left-column value and getting
    swept into the same candidate set as it, corrupting the result (see
    _line_cluster's matching 2026-09-06 note for the sibling bug this same
    photo exposed). A real value's own words sit close together; a column
    jump on a printed page shows up as an unusually wide gap compared to
    that normal spacing, so this keeps the contiguous run starting at
    anchor_left and cuts off at the first gap wider than a generous
    multiple of the tallest kept word's height — scale-relative rather
    than a fixed pixel guess, same reasoning as _value_band_below's band
    sizing and _line_cluster's own gap cutoff.

    2026-09-06 (later same day): multiplier lowered from 6 to 3 after a
    seventh real photo (Marie Claude El Kareh — a two-page-spread photo
    whose bio page also has a noticeably denser field grid than earlier
    samples) showed place_of_birth's real value ("CHIAH") merged into the
    same column-restricted candidate set as an unrelated right-hand block
    ("Authority" / "Major General Abbas Ibrahim") sitting at a similar
    page height — the real gap between the two columns on this photo
    (~85px) was still narrower than 6x one of the bridging words' own
    height (~138px), so the old multiplier let it through; that polluted
    line then contained "authority" and got dropped by _is_label_like_line
    as if it were a label, discarding the real value along with it. 3x
    still comfortably covers every legitimate same-value word gap seen
    across every real photo's regression test so far (confirmed by running
    the full suite after this change), while being tight enough to catch
    this photo's tighter column spacing too."""
    ordered = sorted(candidates, key=lambda w: w.box[0])
    kept: list[OcrWord] = []
    prev_right = anchor_left
    for w in ordered:
        max_gap = _word_height(w) * 3
        if kept and w.box[0] - prev_right > max_gap:
            break
        kept.append(w)
        prev_right = max(prev_right, w.box[2])
    return kept


# A field's printed value is at most two stacked lines on this passport
# (an Arabic line, then a Latin line below it — see _prefer_latin) — capping
# to the two lines closest to the label avoids pulling in the *next*
# printed field's label too, which the generous band in _value_band_below
# would otherwise sometimes reach.
_MAX_VALUE_LINES = 2

# Below this confidence, a detected word is treated as OCR noise rather
# than real text and dropped before line-clustering — added 2026-08-30
# after a real photo's word dump (see module docstring) showed a stray
# fragment ("SU", conf 0.58) landing on the same printed line as a real
# value ("HEMLAYA") and getting pulled in as if it were part of it. Same
# bar as BIO_LOW_CONFIDENCE_THRESHOLD: a word this unreliable shouldn't be
# trusted to build a value even as part of a flagged read.
_MIN_WORD_CONFIDENCE = BIO_LOW_CONFIDENCE_THRESHOLD

# Substrings (lowercase) that mark a clustered line as *itself* a field
# label rather than a value — used by _select_value_lines to stop before
# pulling the next field's label into this field's value. Covers every
# label word this module currently searches for ("father", "place",
# "first", "national") plus neighbouring bio-page labels a generous
# _value_band_below can reach ("date" of issue, "issuance" date,
# registration "author"ity, "sex", "surname", "type", "passport" no./type,
# "expir"y, "signature"/"holder") — deliberately broad since missing one
# just re-introduces the pollution bug, while a false-positive substring
# hit inside a real value is comparatively unlikely and still recoverable
# (the field is flagged for review either way when a read looks off).
#
# 2026-09-06 (later same day): added "issuance" after a sixth real photo
# (Karim Ayass) showed place_of_birth come back as "BEYROUTH suance" --
# "date" alone (already in this set) was meant to cover "Issuance date",
# but on this photo Vision split it as two words ("suance", its own leading
# "Is" dropped -- the exact same truncation pattern _is_label_like_line's
# fuzzy-suffix check already exists for -- and "date", on a DIFFERENT
# clustered line entirely, too far below to be seen as part of the same
# label). Since "suance" alone doesn't contain "date" and the fuzzy-suffix
# check only fires against a keyword actually in this set, "issuance"
# needed to be added in its own right for that check to catch it.
_KNOWN_LABEL_KEYWORDS: frozenset[str] = frozenset({
    "father", "place", "birth", "first", "national", "date", "issuance",
    "author", "sex", "surname", "type", "passport", "expir", "signature",
    "holder", "registration", "code",
})


def _filter_low_confidence(words: list[OcrWord]) -> list[OcrWord]:
    return [w for w in words if w.confidence >= _MIN_WORD_CONFIDENCE]


# A fuzzy-matched word must be at least this long, and the keyword it's
# being compared against must be at least this much longer than it, before
# a suffix match counts as "probably that keyword, misread" rather than a
# coincidental short match — see _is_label_like_line's 2026-09-06 note.
_MIN_FUZZY_LABEL_SUFFIX_LEN = 3
_MIN_FUZZY_LABEL_DROPPED_CHARS = 2


def _is_label_like_line(line: list[OcrWord]) -> bool:
    text = " ".join(w.text for w in line).lower()
    if any(kw in text for kw in _KNOWN_LABEL_KEYWORDS):
        return True
    # 2026-09-06: catches a label whose OWN leading character(s) got
    # dropped by OCR rather than misread as something else — confirmed on
    # a real photo (Younes Hamzeh) where "Place of birth"'s label read as
    # just "ace of" (the "Pl" lost entirely), which doesn't contain
    # "place" or "birth" as a substring, so the check above missed it and
    # the label line got kept as if it were the field's own value,
    # producing "ace of EL BATROUN" as the surfaced place of birth. OCR
    # dropping a word's leading edge (a preceding label number, faint
    # first stroke, or scan-clipped corner) is a more common failure than
    # dropping its trailing edge, so a long-enough suffix match against a
    # known keyword is treated the same as finding the keyword outright —
    # generalizes to any similarly-truncated label, not just this one.
    for w in line:
        word = w.text.lower()
        if len(word) < _MIN_FUZZY_LABEL_SUFFIX_LEN:
            continue
        if any(
            len(kw) - len(word) >= _MIN_FUZZY_LABEL_DROPPED_CHARS and kw.endswith(word)
            for kw in _KNOWN_LABEL_KEYWORDS
        ):
            return True
    return False


# Matches a clustered line made up of nothing but digits and date/time
# punctuation (colons, slashes, dashes, dots) and whitespace — see
# _is_date_like_line and this module's 2026-09-19 docstring note.
_DATE_LIKE_LINE_RE = re.compile(r"^[\d\s:/.\-]+$")


def _is_date_like_line(line: list[OcrWord]) -> bool:
    """True when a clustered line has no letters at all — just digits and
    date/time punctuation, e.g. "26:07 2022" or "03/02/1956". Added
    2026-09-19 (see this module's docstring) after a real photo (Younes
    Hamzeh) showed an unlabeled printed date on the bio page get absorbed
    as a second value line for "Place of birth", producing "EL BATROUN
    26:07 2022" — that line doesn't contain any _KNOWN_LABEL_KEYWORDS
    substring, so _is_label_like_line alone doesn't stop line-selection
    before it. Every field _select_value_lines/_select_value_lines_skip_
    leading_label currently serve (place of birth, father's name) is
    inherently textual, so a legitimate value line for either always
    contains at least one letter — a purely numeric/punctuation line is
    never this field's own content, whatever date or number produced it."""
    text = "".join(w.text for w in line)
    return bool(text) and bool(_DATE_LIKE_LINE_RE.match(text))


def _select_value_lines(lines: list[list[OcrWord]]) -> list[list[OcrWord]]:
    """Keeps clustered lines top-to-bottom until _MAX_VALUE_LINES is
    reached, or a line that looks like another field's label (see
    _is_label_like_line) or a stray unlabeled date (see _is_date_like_line)
    is hit — whichever comes first. Replaces a blind `[:_MAX_VALUE_LINES]`
    slice, which had no way to tell "something that isn't actually this
    field's own value happened to land inside the generous band" apart
    from "this field's own second value line" and would happily keep the
    former."""
    selected: list[list[OcrWord]] = []
    for line in lines:
        if _is_label_like_line(line) or _is_date_like_line(line):
            break
        selected.append(line)
        if len(selected) >= _MAX_VALUE_LINES:
            break
    return selected


def _select_value_lines_skip_leading_label(lines: list[list[OcrWord]]) -> list[list[OcrWord]]:
    """Like _select_value_lines, but for windows anchored on CONTENT
    (see _extract_place_of_birth_anchored) rather than on an already-
    consumed label: the field's own label may legitimately be the FIRST
    line in such a window (e.g. "Place of birth" printed right after the
    nationality value, before the place value itself), and that case must
    be skipped over rather than treated as "the next field, stop here" —
    _select_value_lines can't tell those apart since it always treats the
    very first label-like line it sees as a stop signal. Once a real
    (non-label) line has been seen, behaves exactly like _select_value_lines
    again: a label-like line, or a stray unlabeled date-like line, past
    that point stops selection rather than being absorbed."""
    selected: list[list[OcrWord]] = []
    for line in lines:
        is_label = _is_label_like_line(line)
        if not selected:
            if is_label:
                continue
        elif is_label or _is_date_like_line(line):
            break
        selected.append(line)
        if len(selected) >= _MAX_VALUE_LINES:
            break
    return selected


def _field_read_from_lines(value_lines: list[list[OcrWord]], label: str) -> FieldRead:
    """Builds a FieldRead from already-selected value lines — the shared
    tail end of both _extract_bio_field (label found directly) and
    _extract_father_name_positional (label never detected, value located
    positionally instead) so both paths flag/normalize identically."""
    value_words = [w for line in value_lines for w in line]
    text = _prefer_latin(" ".join(" ".join(w.text for w in line) for line in value_lines))
    conf = (sum(w.confidence for w in value_words) / len(value_words)) if value_words else 0.0
    flagged = conf < BIO_LOW_CONFIDENCE_THRESHOLD or not text
    log_ocr_result(f"passport_{label}", text, conf, flagged)
    return FieldRead(value=text, confidence=conf, flagged=flagged)


def _extract_bio_field(
    words: list[OcrWord], keyword: str, label: str, confirm_keyword: str | None = None,
) -> FieldRead:
    """Finds one bio-data-page field's value by locating its printed label
    (by keyword search — see _find_label_line) and reading the words in
    the band below it, rather than trusting a fixed fraction of the photo
    to land on it. Value text is run through _prefer_latin since the field
    is printed in both Arabic and Latin but the form is Latin-only —
    usually a no-op here since ocr_image_array already discards pure-
    Arabic words by default (see ocr_client's keep_arabic), but cheap
    insurance against a mixed-script word slipping through.

    confirm_keyword is passed straight through to _find_label_line — see
    its docstring — for a keyword ambiguous enough to match more than one
    printed label on the same page."""
    label_line = _find_label_line(words, keyword, confirm_keyword)
    if label_line is None:
        log_ocr_result(f"passport_{label}", "<label not found>", 0.0, True)
        return FieldRead(value="", confidence=0.0, flagged=True)

    band_words = _filter_low_confidence(_value_band_below(words, label_line))
    value_lines = _select_value_lines(_cluster_into_lines(band_words))
    return _field_read_from_lines(value_lines, label)


def _extract_father_name_positional(words: list[OcrWord]) -> FieldRead | None:
    """Fallback for when "Father name" itself was never detected by Vision
    at all (confirmed on a real photo — Rana Rayess, 2026-08-30 — where no
    word or adjacent-word pair contained "father", so _find_label_line's
    split-word fallback couldn't help either; the label text simply wasn't
    read, even though it's legible in the source photo). Locates the value
    positionally instead: "First name" and "Nationality" are both reliably
    detected on this layout and bracket the two lines between them — the
    given name's value directly under "First name", then the father's
    name's value below that, still above "Nationality" — even when the
    father's-name label itself is missing. Returns None (not a flagged-
    empty FieldRead) when either anchor label is also missing, so the
    caller can tell "couldn't attempt this fallback" apart from "attempted
    it and found nothing" and leave the direct-search result in place."""
    first_line = _find_label_line(words, "first")
    national_line = _find_label_line(words, "national")
    if first_line is None or national_line is None:
        return None

    first_bottom = max(w.box[3] for w in first_line)
    national_top = min(w.box[1] for w in national_line)
    label_left = min(w.box[0] for w in first_line)
    label_height = max(max(w.box[3] for w in first_line) - min(w.box[1] for w in first_line), 1)
    band_left = label_left - label_height * 2

    candidates = _restrict_to_anchor_column(_filter_low_confidence([
        w for w in words
        if first_bottom <= _word_center_y(w) <= national_top and w.box[0] >= band_left
    ]), anchor_left=band_left)
    lines = _cluster_into_lines(candidates)
    # The first line in this window is the given name's own value (right
    # below "First name") — not father's name. Only what comes after it,
    # if anything, is a candidate for father's name.
    if len(lines) < 2:
        return None
    return _field_read_from_lines(_select_value_lines(lines[1:]), "father_name")


# Every Lebanese passport bio page prints this, in bold, near-guaranteed to
# read at high confidence (>=0.89 on every real sample seen so far) even
# when the surrounding field LABELS don't — see this module's 2026-09-01
# changelog entry. Kept as a substring match (not exact-equals) via
# _find_label_line so a merge/OCR-noise case like "LEBANESEL" (real data,
# Talal Issa — Vision ran the nationality value and the next line's first
# character together) still matches.
_NATIONALITY_VALUE_KEYWORD = "lebanese"


def _find_nationality_line(words: list[OcrWord]) -> list[OcrWord] | None:
    return _find_label_line(words, _NATIONALITY_VALUE_KEYWORD)


# Every Lebanese passport's actual bio-data page prints this exact header,
# in bold, as the very first line on the page — reliable across every real
# photo seen so far (see passport_field_regions.py's own calibration
# history, which used this same line to locate the bio page in the first
# place) — kept as a substring match via _find_label_line for the same
# split-word-tolerance reason as every other keyword search in this file.
_BIO_PAGE_HEADER_KEYWORD = "republic"


def _restrict_to_bio_page(words: list[OcrWord]) -> list[OcrWord]:
    """Drops every word ABOVE the real bio-data page's own header line —
    added 2026-09-06 after a seventh real photo (Marie Claude El Kareh, a
    passport belonging to a married woman) showed a two-page-spread photo
    where the OTHER page (an amendments page printing "Husband Full Name",
    "Husband Nationality", "Mother Full Name", "Registry Place and
    Number", "Profession") sits ABOVE the real bio page in the frame and
    got OCR'd into the same bio_words list. That page's own "Nationality"
    label (for the HUSBAND, not the passport holder) read at higher
    confidence and higher up the page than the real one, so
    _find_nationality_line's topmost-match rule picked it every time —
    _extract_place_of_birth_anchored then confidently returned "NADIA
    ISHAK" (the mother's name, printed right below the husband's
    nationality line on that other page) as the place of birth, unflagged.

    Rather than special-case "Husband"/"Mother Full Name" as more known
    label keywords (which would only ever cover the specific extra-page
    layouts already seen, not whatever a different passport variant prints
    on its own amendments page), this uses the one line guaranteed to
    appear on the real bio page and nowhere else: "Republic of Lebanon /
    République Libanaise" always prints as the very first line at the top
    of the actual bio page. Cutting everything above it removes any other
    page's content wholesale, regardless of what it says, the same way
    BIO_SEARCH_REGION itself is a generous region trusted to label search
    rather than a hand-tuned box. Falls back to the unrestricted word list
    if this header wasn't detected at all (rather than risk cutting real
    content on a photo where Vision simply didn't read it) — every
    extraction tier downstream already has its own safeguards for noisy
    input, so failing open here is the safer default."""
    header_line = _find_label_line(words, _BIO_PAGE_HEADER_KEYWORD)
    if header_line is None:
        return words
    header_bottom = max(w.box[3] for w in header_line)
    return [w for w in words if w.box[1] >= header_bottom]


# A real word's bounding box is normally WIDER than it is tall for
# multi-character Latin-script text (a horizontal run of characters). A
# word this much TALLER than it is wide is a strong, orientation-agnostic
# sign that the physical photo itself is rotated roughly 90 degrees --
# see _looks_rotated_90's docstring for the real evidence behind this.
_ROTATED_WORD_ASPECT_THRESHOLD = 1.3
_MIN_WORD_LEN_FOR_ROTATION_CHECK = 3
_MIN_ROTATED_WORD_FRACTION = 0.6


def _looks_rotated_90(words: list[OcrWord]) -> bool:
    """True if most of `words`' own bounding boxes are narrow-and-tall
    rather than the normal wide-and-short shape a horizontal run of Latin
    characters produces -- i.e. the PHYSICAL PHOTO looks rotated roughly 90
    degrees, independent of whether Vision could still read the text.

    Added 2026-09-06 after an initial version of the rotation fix (probing
    for the MRZ at 90/180/270 degrees only when the existing 0-degree MRZ
    tiers failed outright) turned out not to fix the real photo it was
    built for (Richard Bou Tayeh) at all: pulling this photo's real
    bio-search-region word dump showed Google Vision successfully read
    correct text ("RICHARD", "MILAD", "BOU TAYEH", the MRZ digits, etc.,
    every one at >=0.9 confidence) EVEN THOUGH THE WHOLE PHOTO WAS ROTATED
    90 DEGREES -- Vision's text recognition tolerates arbitrary rotation
    far better than this module assumed, so the existing whole-photo MRZ
    tier (already tried before any rotation probing) succeeded on its own
    and the rotation-probing tier never even ran. The bug wasn't "the MRZ
    can't be found on a rotated photo" at all -- it was that
    BIO_SEARCH_REGION's fixed-fraction CROP still samples the wrong pixels
    of a physically-rotated photo no matter how well Vision reads whatever
    text happens to land inside that wrong crop, and none of the
    downstream line-clustering logic (which assumes horizontal rows) can
    make sense of words whose real text runs vertically down the image
    either. Confirmed via that same word dump: every multi-character word
    had a narrow, tall box (e.g. "RICHARD" 18px wide x 91px tall, ratio
    ~5.1; the whole MRZ line 2, read as one token, was 50px wide x 819px
    tall) -- Vision reports each word's bounding box in the image's actual
    pixel geometry even when it recognizes the rotated characters
    correctly, so this ratio is a reliable, orientation-tolerant signal
    that doesn't depend on any single field's extraction having already
    failed or succeeded. See _resolve_bio_words below for how this is used
    to find and correct the rotation specifically for bio-page extraction,
    independent of whatever tier the MRZ itself resolved through."""
    candidates = [w for w in words if len(w.text) >= _MIN_WORD_LEN_FOR_ROTATION_CHECK]
    if len(candidates) < 3:
        return False
    tall_narrow = sum(
        1 for w in candidates
        if (w.box[3] - w.box[1]) > (w.box[2] - w.box[0]) * _ROTATED_WORD_ASPECT_THRESHOLD
    )
    return tall_narrow >= len(candidates) * _MIN_ROTATED_WORD_FRACTION


def _ocr_bio_region(
    image: np.ndarray, debug_dir: str | None, errors: list[str], debug_name: str,
) -> list[OcrWord]:
    """OCRs `image`'s BIO_SEARCH_REGION crop and returns the raw (not yet
    bio-page-restricted) words -- shared by _resolve_bio_words below across
    the original orientation and every rotation candidate it tries, so the
    crop/OCR/debug-dump logic isn't duplicated per candidate."""
    bio_crop = crop_region(image, BIO_SEARCH_REGION)
    save_crop(debug_dir, debug_name, bio_crop)
    try:
        words = ocr_image_array(bio_crop, language_hints=["ar", "en"]).words
        save_ocr_words(debug_dir, debug_name, words)
        return words
    except OcrError as e:
        log_ocr_result("passport_bio_search_region", f"<OCR ERROR: {e}>", 0.0, True)
        if str(e) not in errors:
            errors.append(str(e))
        return []


# Rotations tried by _resolve_bio_words when the original orientation's bio
# crop looks rotated (_looks_rotated_90). Only the two 90-degree options --
# a 180-degree rotation of an already-sideways crop is STILL sideways (a
# word's own bounding-box aspect ratio is unaffected by a 180-degree turn),
# so it could never pass _looks_rotated_90's check and isn't worth an extra
# OCR call. See _resolve_bio_words' docstring for the real-photo evidence
# behind trying exactly these two.
_BIO_ROTATION_ATTEMPTS: tuple[tuple[str, int], ...] = (
    ("rot90cw", cv2.ROTATE_90_CLOCKWISE),
    ("rot90ccw", cv2.ROTATE_90_COUNTERCLOCKWISE),
)

# On every real Lebanese-passport bio page seen this session (eight real
# photos and counting), these labels print in exactly this top-to-bottom
# order -- used by _bio_orientation_looks_correct below to tell a properly
# rotated (right-side up) crop apart from one that's merely no-longer-
# sideways but still upside down (rotated the "wrong" 90 degrees).
_ORDERED_BIO_ANCHOR_KEYWORDS: tuple[str, ...] = ("first", "father", "national", "place")


def _bio_orientation_looks_correct(words: list[OcrWord]) -> bool:
    """True if as many of _ORDERED_BIO_ANCHOR_KEYWORDS as this crop's words
    actually contain appear in the expected top-to-bottom order (by each
    matched line's own topmost y-coordinate) -- i.e. this crop's content
    really does read right-side up, not merely "not sideways anymore."

    Added 2026-09-06 after a ninth real photo (Charbel Sfeir) showed that
    _looks_rotated_90's aspect-ratio check, while correctly identifying
    THAT a photo is rotated ~90 degrees, cannot tell CLOCKWISE from
    COUNTER-CLOCKWISE: rotating an already-sideways photo either 90 degrees
    clockwise OR 90 degrees counter-clockwise turns every word's tall-narrow
    box into a wide-short one, but only ONE of those two directions is
    actually right-side up -- the other is upside down, which still
    produces wide-short boxes (a 180-degree flip doesn't change a box's own
    aspect ratio) and would pass _looks_rotated_90's check just as
    confidently as the correct direction. Confirmed against this photo's
    real word dumps: trying both 90-degree rotations, "first"/"father"/
    "national"/"place" labels read in the correct top-to-bottom order on
    the clockwise rotation (which was in fact the right one for this
    photo) and in the EXACT REVERSE order on the counter-clockwise one.

    Returns True (rather than rejecting) when fewer than two of these
    keywords are found at all -- not enough anchors to judge either way,
    and this module's many other, more targeted fallbacks (positional,
    content-anchored) are better placed to make something of a photo this
    sparsely labeled than a coin-flip rejection here would be."""
    positions = []
    for keyword in _ORDERED_BIO_ANCHOR_KEYWORDS:
        line = _find_label_line(words, keyword)
        if line is not None:
            positions.append(min(w.box[1] for w in line))
    if len(positions) < 2:
        return True
    return positions == sorted(positions)


def _resolve_bio_words(
    image: np.ndarray, debug_dir: str | None, errors: list[str],
) -> tuple[np.ndarray, list[OcrWord]]:
    """Finds the bio-page words to actually extract fields from, correcting
    for a whole-photo rotation when the original orientation's bio crop
    looks physically sideways (_looks_rotated_90).

    Added 2026-09-06 as the real fix for a whole-photo-rotated passport
    (Richard Bou Tayeh) -- see _looks_rotated_90's docstring for why probing
    for the MRZ at various rotations (this module's first attempt at fixing
    this same photo) didn't actually address the failure: Vision reads the
    MRZ fine regardless of physical rotation, so the MRZ tiers never needed
    correcting in the first place, but BIO_SEARCH_REGION's fixed-fraction
    crop still samples the wrong pixels on a rotated photo no matter how
    well Vision reads whatever it happens to catch there.

    2026-09-06 (later same day): this function's first version checked for
    the bio page's own "Republic of Lebanon" header line instead of using
    _bio_orientation_looks_correct below -- reasonable in principle (every
    real photo prints it first), but a ninth real photo (Charbel Sfeir)
    broke it two different ways at once: (1) that photo's actual header
    word split as "ublic" (BIO_SEARCH_REGION's crop boundary clipped the
    leading "Rep" off "Republic" at this photo's particular framing, not an
    OCR misread this module's existing fuzzy-label-suffix handling was ever
    meant to catch -- that mechanism is for _is_label_like_line's *stop*
    logic, not this header search), so the correct rotation's own crop
    never satisfied "found a line containing 'republic'" at all; and (2)
    even where a header WOULD have matched, Vision reads "Lebanon" and
    "Libanaise" as clean, correct words in EVERY orientation tried,
    including the still-sideways original -- a keyword being present
    doesn't mean the crop is right-side up, since Vision tolerates rotation
    for individual word recognition just as well as it did for the MRZ.
    Switched to checking _looks_rotated_90 (did this rotation stop being
    sideways) AND _bio_orientation_looks_correct (given that it's no longer
    sideways, does its content also read in the right top-to-bottom order,
    ruling out the upside-down 90-degree rotation) -- both purely
    geometric, neither dependent on any specific word having been read
    correctly at all.

    Tries, in order: the original orientation as-is if it doesn't look
    rotated; otherwise each 90-degree rotation in turn, keeping the first
    one whose words are both no-longer-sideways and correctly ordered.
    Returns (image_used, words) -- words already run through
    _restrict_to_bio_page -- falling back to the ORIGINAL orientation's
    words if neither rotation checks out, so downstream fallbacks still get
    a best-effort read rather than nothing. A photo that's rotated a pure
    180 degrees (upside down, never sideways) isn't handled by this
    mechanism at all -- _looks_rotated_90 can't detect it (a word's aspect
    ratio survives a 180-degree flip unchanged) and no real photo has shown
    this failure mode yet; if one does, it'll need a different signal than
    either check used here."""
    raw_words = _ocr_bio_region(image, debug_dir, errors, "passport_02_bio_search_region")
    if not _looks_rotated_90(raw_words):
        return image, _restrict_to_bio_page(raw_words)

    for name, rotation_code in _BIO_ROTATION_ATTEMPTS:
        rotated = cv2.rotate(image, rotation_code)
        rotated_words = _ocr_bio_region(rotated, debug_dir, errors, f"passport_02b_bio_search_region_{name}")
        if not _looks_rotated_90(rotated_words) and _bio_orientation_looks_correct(rotated_words):
            return rotated, _restrict_to_bio_page(rotated_words)

    return image, _restrict_to_bio_page(raw_words)


def _extract_father_name_anchored(words: list[OcrWord], given_name: str) -> FieldRead | None:
    """Content-anchored fallback for when NEITHER "Father name" nor "First
    name"/"Nationality" labels were detected (confirmed on a real photo —
    Talal Issa, 2026-09-01 — where almost no bio-page label text read at
    all, only the values). Locates the given name's own line by its actual
    text (already known independently and reliably from the checksum-
    backed MRZ, so no label search needed for it at all) and the
    nationality value's line by _find_nationality_line, then takes
    whatever's between them — the father's name value, on this layout,
    same as the label-based positional fallback above but anchored on
    content that reads more reliably than either field's label text.
    Returns None (not a flagged-empty read) when given_name is empty
    (e.g. the MRZ itself failed) or either anchor isn't found, so the
    caller knows this fallback couldn't be attempted at all.

    2026-09-06 history: an earlier version of this fix also accepted the
    MRZ's surname and skipped a leading line that echoed it, reasoning
    (from a real photo, Younes Hamzeh) that this bio page printed Given
    name, Surname, THEN Father's name before Nationality. That reasoning
    was built on a mislabeled assumption about which of this photo's two
    bio-page name lines was the "given name" one. Once _find_label_line
    correctly anchors on the MRZ's actual given_names value (see
    extract_passport_data — the given name and surname are not always the
    line order a human would guess from the two names alone), the real
    father's-name line turned out to be the very next line after the
    given-name anchor, with nothing genuine in between — the surname-skip
    was solving a problem that didn't exist here, and actively broke this
    exact photo instead: the real father's name happened to read the same
    text as the surname (a realistic Arab-naming-convention coincidence,
    not a fixture quirk), so skipping "a line that echoes the surname"
    discarded the correct answer. Removed rather than patched further —
    no real photo seen so far actually needs it once the column-
    restriction fix below is in place."""
    if not given_name:
        return None
    given_line = _find_label_line(words, given_name.lower())
    nationality_line = _find_nationality_line(words)
    if given_line is None or nationality_line is None:
        return None

    given_bottom = max(w.box[3] for w in given_line)
    nationality_top = min(w.box[1] for w in nationality_line)
    label_left = min(w.box[0] for w in given_line)
    label_height = max(max(w.box[3] for w in given_line) - min(w.box[1] for w in given_line), 1)
    band_left = label_left - label_height * 2

    candidates = _restrict_to_anchor_column(_filter_low_confidence([
        w for w in words
        if given_bottom <= _word_center_y(w) <= nationality_top and w.box[0] >= band_left
    ]), anchor_left=band_left)
    # 2026-09-06 (later same day): _select_value_lines_skip_leading_label,
    # not the plain _select_value_lines used elsewhere in this module --
    # see this function's own history above for why "break on the first
    # label-like line" is already the wrong call once a stray line can be
    # mistaken for a label. Confirmed on a sixth real photo (Karim Ayass):
    # this band's first line was two garbled OCR fragments ("her", "bom" --
    # noise from a bilingual label the photo didn't read cleanly), and
    # "her" happens to be a real fuzzy-suffix match for "father" (father
    # ends with "her"), so _is_label_like_line correctly-by-its-own-rules
    # flagged it as label-like. With the old break-on-label selector that
    # discarded EVERYTHING, including the real value ("FADY") sitting right
    # below it, sending father_name through to the license's Arabic-only
    # fallback for no real reason. The skip-leading variant treats that
    # first line as "the label, or something that looks enough like one to
    # not be the value" and keeps looking, the same way it already does for
    # _extract_place_of_birth_anchored below.
    value_lines = _select_value_lines_skip_leading_label(_cluster_into_lines(candidates))
    if not value_lines:
        return None
    return _field_read_from_lines(value_lines, "father_name")


def _extract_place_of_birth_anchored(words: list[OcrWord]) -> FieldRead | None:
    """Content-anchored fallback for place of birth, the mirror of
    _extract_father_name_anchored above: reads the band below the
    nationality value's own line (found by _find_nationality_line) instead
    of below a "Place of birth" label — that label may or may not appear
    as the first line in this band (see _select_value_lines_skip_leading_label),
    but either way isn't required to locate the real value below it.
    Returns None when the nationality anchor itself isn't found."""
    nationality_line = _find_nationality_line(words)
    if nationality_line is None:
        return None

    nationality_bottom = max(w.box[3] for w in nationality_line)
    label_left = min(w.box[0] for w in nationality_line)
    label_height = max(max(w.box[3] for w in nationality_line) - min(w.box[1] for w in nationality_line), 1)
    band_left = label_left - label_height * 2
    band_bottom = nationality_bottom + label_height * 6  # same generosity as _value_band_below

    candidates = _restrict_to_anchor_column(_filter_low_confidence([
        w for w in words
        if nationality_bottom <= _word_center_y(w) <= band_bottom and w.box[0] >= band_left
    ]), anchor_left=band_left)
    value_lines = _select_value_lines_skip_leading_label(_cluster_into_lines(candidates))
    if not value_lines:
        return None
    return _field_read_from_lines(value_lines, "place_of_birth")


def extract_passport_data(image_path: str, debug_dir: str | None = None) -> PassportOcrResult:
    image = cv2.imread(image_path)
    if image is None:
        return PassportOcrResult(mrz=None, raw_line1=None, raw_line2=None,
                                  error=f"Could not read image: {image_path}")

    save_crop(debug_dir, "passport_00_full_photo", image)
    band = _crop_mrz_band(image)
    save_crop(debug_dir, "passport_01_mrz_band_crop", band)

    errors: list[str] = []

    # MRZ resolution (fixed band, then whole photo, then — only if both of
    # those fail outright — whole-photo rotation probes) happens BEFORE
    # bio-page extraction below. This ordering matters: a whole-photo-
    # rotated passport (confirmed on a real photo, Richard Bou Tayeh,
    # 2026-09-06 — see _try_locate_mrz_with_rotation and this module's
    # docstring) needs bio-page extraction to run against the CORRECTED
    # orientation, not the original one, since BIO_SEARCH_REGION's fixed
    # fraction is exactly as orientation-dependent as the MRZ crop was —
    # extracting bio fields first (as this function used to) would leave
    # them reading from the wrong, still-rotated image even once the MRZ
    # itself was successfully located below.
    #
    # ["ar", "en"] here too (not just "en") even though MRZ text is always
    # A-Z/0-9/"<" — kept from before the 2026-08-24 switch to ocr_client/
    # Vision (see module docstring), where this avoided loading a second
    # cached EasyOCR reader for a language combo the bio-data fields below
    # weren't already using; testing at the time found no accuracy
    # downside from including "ar" either way, and there's no cached-
    # reader cost with Vision to begin with.
    mrz_located = _try_locate_mrz_with_rotation(image, band, debug_dir, errors)
    if mrz_located is not None:
        image, lines, ocr_result = mrz_located
        line1, line2 = lines
        # 2026-09-06: verify (and correct, if needed) which of the two
        # lines is actually line1 vs line2 before parsing -- see
        # _resolve_mrz_line_order.
        line1, line2 = _resolve_mrz_line_order(line1, line2)
        mrz = parse_td3(line1, line2)
        names_flagged = (not mrz.valid) or (ocr_result.average_confidence() < NAME_LOW_CONFIDENCE_THRESHOLD)
    else:
        errors.insert(0, "Could not locate two MRZ lines in the OCR text — check the photo crop/angle.")
        mrz = None
        line1 = line2 = None
        names_flagged = True

    # Bio-data-page fields (father's name, place of birth) are independent
    # of the MRZ read above — extract them regardless of whether the MRZ
    # itself succeeded, same per-document-isolation principle as
    # license_ocr's per-field try/except. One OCR call over the whole
    # generous BIO_SEARCH_REGION rather than one tight crop per field (see
    # module docstring and passport_field_regions.py) — _extract_bio_field
    # locates each field within that single result by searching for its
    # printed label. _resolve_bio_words starts from `image` as finalized
    # above (the original photo, or the MRZ's own rotation-corrected
    # orientation if it needed one) but independently re-checks for a
    # whole-photo rotation specific to the BIO crop — see its docstring for
    # why that's necessary even when the MRZ itself already resolved fine.
    _, bio_words = _resolve_bio_words(image, debug_dir, errors)

    # Both fields go through the same tier order: try the fast direct
    # label search first (correct and cheapest when the label actually
    # got read), then progressively less label-dependent fallbacks — only
    # when the previous tier came back fully empty, not just flagged/
    # low-confidence, since a flagged-but-present direct read of the
    # actually-labeled field is still more trustworthy than a fallback
    # guess and shouldn't be displaced by one.
    father_name = _extract_bio_field(bio_words, "father", "father_name")
    if not father_name.value:
        positional = _extract_father_name_positional(bio_words)
        if positional is not None:
            father_name = positional

    place_of_birth = _extract_bio_field(bio_words, "place", "place_of_birth", confirm_keyword="birth")
    if not place_of_birth.value:
        anchored_place = _extract_place_of_birth_anchored(bio_words)
        if anchored_place is not None:
            place_of_birth = anchored_place

    if mrz is None:
        return PassportOcrResult(mrz=None, raw_line1=None, raw_line2=None,
                                  father_name=father_name, place_of_birth=place_of_birth,
                                  error="; ".join(errors))

    if not father_name.value and mrz.given_names:
        # Last tier: anchor on the given name the MRZ just gave us (only
        # available now that the MRZ has been read) instead of on either
        # field's label text -- see _extract_father_name_anchored's
        # docstring for why this reads more reliably than the label-based
        # attempts above on some real photos.
        primary_given_name = mrz.given_names.split()[0]
        anchored_father = _extract_father_name_anchored(bio_words, primary_given_name)
        if anchored_father is not None:
            father_name = anchored_father

    return PassportOcrResult(mrz=mrz, raw_line1=line1, raw_line2=line2,
                              names_flagged=names_flagged,
                              father_name=father_name, place_of_birth=place_of_birth,
                              error="; ".join(errors) or None)
