"""
License pipeline: deskew the front/back card photos, fine-align them onto a
saved reference photo, crop each numbered field's region, OCR each crop
individually, and (for the back) work out which categories the holder
actually holds from the category table.

2026-08-30: added a fine-alignment step (see image_prep.align_to_reference)
between deskew_card and field cropping — a real second photo (Rana Rayess)
confirmed that deskew_card's 4-corner warp alone can leave a small residual
misalignment (a couple of fields read a full row off from where they should,
while others on the same card read fine — not the total-garbage failure
mode the rotation fix and card-detection failures produce), because
FRONT_FIELD_REGIONS/BACK_CATEGORY_ROWS were measured as fractions of one
specific deskewed photo, and a new photo's deskew only has to be the same
*size* as that one, not pixel-identical. Aligning every new deskew onto that
same reference photo (via ORB feature matching + homography, see
image_prep.py) before cropping fields removes that gap: the fractions below
now describe the same real pixels they were calibrated from again, not just
a same-sized rectangle. Falls back to the un-aligned deskew (silently) if
the reference images are missing or a photo doesn't have enough matchable
detail — never blocks or degrades below the pre-2026-08-30 behavior.

2026-08-24: ocr_client.py (the module this file calls for the actual OCR)
switched engines from Tesseract to Google Cloud Vision — see that
module's docstring. This file's INLINE_LABEL_FIELDS/_strip_inline_label
mechanism, described in detail below, was built and tuned against
Tesseract and is kept unchanged: the generous-crop + programmatic
label-strip approach is still needed (Vision's crop still contains the
printed field-number label alongside the value, same as before) and still
works the same way regardless of engine. The one thing that's now inert
is INLINE_LABEL_FIELDS' char_whitelist values — Vision has no character-
whitelist concept, so ocr_client.ocr_image_array accepts and ignores that
argument (see its docstring). They're left in place rather than removed:
harmless as-is, and they'd need restoring immediately if this ever reverts
to a whitelist-capable engine.

2026-08-23: front-of-card field extraction changed from "crop a tight box
that (hopefully) contains only the value" to "crop a generous box that
safely contains the label AND the value, then strip the label out of the
OCR'd words programmatically" for the fields whose printed label sits
inline with the value (see INLINE_LABEL_FIELDS and
license_field_regions.py's module docstring for which fields and why).
This replaced hand-tuning the crop's pixel boundary to land exactly
between label and value, which kept drifting back under small skew/zoom
differences between photos — recalibrated three times for "13b" alone
(2026-08-20, then twice more on 2026-08-23), and the last of those tight
attempts, re-verified against a live OCR call rather than just eyeballed,
still misread "O+" as "04" or came back blank once a whitelist was added.

Measurement method for the new regions and INLINE_LABEL_FIELDS'
whitelists, and everything below this paragraph: all Tesseract-era
findings, kept as history for why the crop regions and
INLINE_LABEL_FIELDS look the way they do — not current engine behavior.
Against a real sample license (Georges El Alam, IDL_APP_DEBUG_OCR=1 debug
dump), each field's label+value ink was measured directly off the
deskewed card image (pixel column/row thresholding, not eyeballing), then
re-verified by actually running this module's OCR call against the
resulting crop and confirming the stripped output matched the card.
Several things fell out of that verification pass that are worth
recording since they're not obvious from the code alone:

- A char_whitelist needed --psm 6 (assume a single uniform block of text)
  to keep the label and value as separate detected words under
  Tesseract — confirmed: under psm 7 (single line), a whitelisted crop's
  words came back merged into one token with the space silently dropped
  ("13b" + "O+" -> one "13bO+"), which breaks _strip_inline_label below.
  This separation came from Tesseract's own layout segmentation, not from
  anything in the whitelist — see the next point.
- The whitelist had to include every character that can appear in EITHER
  the label or the value, not just the value's own alphabet — a blood-type
  whitelist of just "ABO+-" (no digits) came back completely empty on a
  real crop, because the crop's leftover label fragments had nothing in
  the allowed set for Tesseract to fall back to. INLINE_LABEL_FIELDS'
  "13b" whitelist still includes the label's own digits/letter for this
  reason (harmless now that it's unused — see the 2026-08-24 note above).
- A whitelist value must never contain a space. An earlier version of
  this fix whitelisted a trailing space too, reasoning that Tesseract
  needed it whitelisted to keep label and value as separate words — that
  reasoning was wrong (word separation was the PSM 6 point above, not a
  whitelist concern) and the attempt to make it work by quoting the
  whitelist in ocr_client's config string broke autofill outright on a
  real Windows run ("Unexpected error during autofill: No closing
  quotation") — a Windows-specific limitation in how pytesseract parsed
  its config string, which no quoting or escaping from this side could
  work around, and one of the concrete reasons this app moved off
  Tesseract entirely (see ocr_client.py's docstring).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from ocr.debug_dump import log_ocr_result, save_crop, save_ocr_words
from ocr.image_prep import align_to_reference, crop_region, deskew_card
from ocr.license_field_regions import (
    BACK_CATEGORY_ROWS,
    FRONT_FIELD_REGIONS,
    ROW_EXPIRY_DATE_SPLIT,
    ROW_ISSUE_DATE_SPLIT,
)
from ocr.ocr_client import OcrError, OcrWord, ocr_image_array

logger = logging.getLogger("ocr.license")

# 2026-08-30: reference photos (Georges El Alam's own deskewed card, the one
# every fraction in license_field_regions.py was actually measured against)
# used to fine-align each new photo's deskewed card before cropping fields —
# see image_prep.align_to_reference's module note for the full rationale.
# Loaded lazily and cached (imread'd once, not per autofill run); missing
# files are a silent no-op fallback (extract_license_front/back below skip
# the alignment step entirely), not an error — this is an extra correction
# on top of deskew_card, never a requirement for autofill to work at all.
_REFERENCE_DIR = Path(__file__).resolve().parent / "reference_templates"
_reference_front = None
_reference_back = None
_reference_loaded = False


def _load_reference_cards() -> None:
    global _reference_front, _reference_back, _reference_loaded
    if _reference_loaded:
        return
    _reference_loaded = True
    front_path = _REFERENCE_DIR / "license_front.png"
    back_path = _REFERENCE_DIR / "license_back.png"
    if front_path.exists():
        _reference_front = cv2.imread(str(front_path))
    if back_path.exists():
        _reference_back = cv2.imread(str(back_path))

# Below this average per-field OCR confidence, flag the field for manual
# review instead of trusting the read silently. Lower than the 0.75 used
# when this ran on Google Vision — Tesseract's confidence scores run
# noticeably lower even on correct reads, especially on the small,
# sometimes-rotated field crops here and on mixed Arabic/Latin text,
# so the old Vision-tuned bar would flag almost everything.
LOW_CONFIDENCE_THRESHOLD = 0.60

# Place of residence (field "8") is printed only in Arabic script, with no
# Latin content at all — unlike every other license field, where Arabic is
# recognized (for accuracy) but then discarded because the surfaced value
# is always Latin. ocr_client._strip_arabic runs unconditionally otherwise,
# which for this field meant deleting the entire correct OCR result, not
# just corrupting it: the field came back blank on every real photo. Field
# keys, not label text, so this only ever applies to the fields listed here.
#
# Extended 2026-08-23 to cover the INLINE_LABEL_FIELDS entries whose actual
# printed VALUE (not just stray label/decoration text) is itself Arabic:
# "3" (dob + place of birth -- the place is Arabic), "4c" (issuing
# authority -- an Arabic phrase), "13c"/"13d" (father's/mother's name,
# Arabic only). Missing this for those four meant _strip_arabic deleted the
# real value before _strip_inline_label ever saw it, leaving only leftover
# label fragments (confirmed: "13c" read back as "13", "13d" as "13d" --
# the label digits with the actual name gone). "13a" and "13b" deliberately
# stay OFF this list: "13a" prints nationality in both scripts and the New
# IDL form is Latin-only anyway, so discarding the Arabic half early is the
# desired behavior (same convention as passport_ocr._prefer_latin), and
# "13b" (blood type) never has Arabic content to begin with.
_KEEP_ARABIC_FIELDS: frozenset[str] = frozenset({"3", "4c", "8", "13c", "13d"})

# Front-of-card fields whose printed label sits inline with the value
# (space-separated on the same baseline) rather than on its own line above
# it — see license_field_regions.py's module docstring for the full
# rationale. These get the generous-crop + label-strip treatment in
# _ocr_crop below instead of the old tight-box-only-contains-the-value
# approach, and are OCR'd with an explicit --psm 6 (see module docstring).
#
# A non-None value is a Tesseract character whitelist restricting
# recognition to exactly the characters that can appear in that field's
# label *and* value combined (see module docstring for why the label's
# characters have to be included too) — set only for fields provably never
# anything but Latin digits/letters/symbols on this card template. None
# means "this field can have real Arabic content, don't whitelist it."
# ("13b" replaces the older, narrower _CHAR_WHITELISTS approach that only
# whitelisted the value's own alphabet — see module docstring for why that
# came back empty on a real crop.)
INLINE_LABEL_FIELDS: dict[str, str | None] = {
    "3": None,                         # dob + place of birth — place is Arabic
    "4a": "0123456789/",               # issue date
    "4b": "0123456789/",               # expiry date
    "4c": None,                        # issuing authority — Arabic phrase
    "5": "0123456789",                 # license number — added 2026-08-27,
                                        # see license_field_regions.py's
                                        # matching 2026-08-27 note for why.
    "13a": None,                       # nationality — printed in Arabic + Latin
    "13b": "0123456789ABOb+-",         # blood type: A/B/O +/- plus the label's
                                        # own "13b" digits/letter (see module
                                        # docstring — a whitelist missing the
                                        # label's characters read back empty).
                                        # No space — see module docstring's
                                        # last point; ocr_client rejects one.
    "13c": None,                       # father's name — Arabic only
    "13d": None,                       # mother's name — Arabic only
}

# 2026-08-27: Vision has no character-whitelist concept (INLINE_LABEL_FIELDS'
# whitelist values are inert under it, see that dict's docstring), so
# there's no way to *forbid* Vision from reading the blood-type field's "O"
# as the digit "0" -- the two are the same glyph in most fonts, and a real
# blood type can never legitimately contain a digit (only A/B/AB/O + "+"/
# "-"), so any "0" that survives label-stripping on this field is always a
# misread letter O, never a genuine zero. Confirmed in practice: a real
# "O+" card came back as literal "0+" (zero) on a live Vision read even
# though the value was correctly isolated from the "13b" label -- the crop/
# split logic was right, only the character identity was wrong.
#
# 2026-08-30: also strips whitespace -- Vision detects "A" and "+" as two
# separate words when there's normal kerning/font gap between them, and
# _strip_inline_label rejoins surviving words with a space, so a real "A+"
# was coming back as "A +". A blood type never legitimately contains a
# space, so removing all whitespace here is always safe.
#
# 2026-09-06: also fixes a "+"-as-letter misread. Confirmed on a real photo
# (Younes Hamzeh) whose card plainly reads "A+" under _strip_inline_label
# correctly isolating the value from the "13b" label -- the crop/split
# logic was right, but Vision itself read the two characters as the single
# word "At" (confidence 0.835): a "+" kerned tight against the preceding
# letter, with a thin enough crossbar, apparently reads as a lowercase "t"'s
# stem to Vision's model. A real blood type is always exactly A/B/AB/O
# followed by +/- and nothing else, so once a value already matches that
# shape except for its very last character, that character is far more
# likely this same kind of misread than a genuinely different (and
# nonsensical) blood type -- OCR has no reason to fabricate a
# plausible-looking-but-wrong blood-type string on its own.
#
# 2026-09-06 (same day, a harder version): a second real photo (Frederic
# Elias) came back with the WHOLE crop -- "13b." label and "O+" value --
# read as a single Vision word, "136.0+" (the "b" misread as "6", no space
# detected between the label and the value at all). With only one word,
# _strip_inline_label has nothing to split on (see its own docstring: a
# single word is returned untouched, since guessing a split point with no
# gap to measure would be unsafe in general) and passes the whole polluted
# string through. Since the label always comes BEFORE the value on this
# field and a real value is always exactly a blood-group letter plus a
# sign, searching for that shape anchored to the END of the string (via
# re.search + a trailing $, not re.match against the whole string) finds
# and extracts just the real value regardless of what leftover label
# garbage precedes it -- "136.0+" becomes "136.O+" after the 0->O pass
# above, and the search below then pulls "O+" back out of it. Every
# previously-clean case (a value with nothing ahead of it) still matches
# the same way, since the pattern only cares about what the string ends
# with.
_BLOOD_GROUP_RE = re.compile(r"(AB|A|B|O)([+\-tT1lI!])$")
_RH_MISREAD_TO_SIGN = {"t": "+", "T": "+", "1": "+", "l": "+", "I": "+", "!": "+"}


def _normalize_blood_type(text: str) -> str:
    text = text.replace("0", "O").replace(" ", "")
    match = _BLOOD_GROUP_RE.search(text)
    if not match:
        return text
    group, rh = match.groups()
    return group + _RH_MISREAD_TO_SIGN.get(rh, rh)


# 2026-09-07: a third real photo (Charbel Sfeir) exposed a variant of the
# 2026-09-06 "136.0+" case just above, but split across TWO detected words
# instead of merged into one: "13b.4" (the "13b." label fused with the
# value's real leading letter, itself misread as the digit "4") and "+" (the
# Rh sign, its own word). _strip_inline_label's "split at the single widest
# gap" heuristic (see its docstring) has, with only two words, exactly one
# possible gap to choose from and confidently treats it as the label/value
# boundary -- so it discards the ENTIRE first word, "13b.4", as pure label
# text, even though it ends with the value's real leading character. (The
# two words' boxes even overlap by a few pixels here, 257 < 265 -- this is
# what it looks like when Vision reads the label and the value's first
# glyph as touching rather than genuinely spaced.)
#
# Loosening _strip_inline_label itself isn't safe: it's shared by every
# other INLINE_LABEL_FIELDS entry, where the label reliably stays its own
# separate token, and this file has no other real evidence of a fused
# label+value word for any of those. Instead, field "13b" gets its own
# fallback, tried only when the split-then-normalize result ISN'T already a
# clean, complete blood type: re-derive the text by concatenating every
# detected word's characters in left-to-right order -- sidestepping the
# split entirely -- and search THAT for a trailing blood-group pattern,
# this time also accepting "4" in the group-letter position, on the same
# reasoning the "0"->"O" fix above already relies on: a real blood type
# never legitimately contains a digit, so any digit found immediately
# before the Rh sign is always a misread letter, never a genuine value.
# Every previously-fixed case above (the "0"+"space"+"t"+"136.0+" ones)
# already produces a clean, complete result straight out of
# _normalize_blood_type, so this fallback never triggers for them --
# confirmed by tracing each one by hand against _CLEAN_BLOOD_TYPE_RE below.
_GROUP_MISREAD_TO_LETTER = {"4": "A"}
_CLEAN_BLOOD_TYPE_RE = re.compile(r"^(AB|A|B|O)[+\-]$")
_BLOOD_GROUP_WITH_MISREADS_RE = re.compile(
    r"(AB|A|B|O|" + "|".join(_GROUP_MISREAD_TO_LETTER) + r")([+\-tT1lI!])$"
)


def _normalize_blood_type_from_words(words: list[OcrWord]) -> str:
    """Field "13b" fallback described above -- ignores _strip_inline_label's
    split entirely and searches the whole crop's text (every detected word,
    left to right, no separator) for a trailing blood-group pattern that
    also tolerates a "4"->"A" misread immediately before the Rh sign."""
    joined = "".join(w.text for w in sorted(words, key=lambda w: w.box[0]))
    joined = joined.replace("0", "O").replace(" ", "")
    match = _BLOOD_GROUP_WITH_MISREADS_RE.search(joined)
    if not match:
        return ""
    group, rh = match.groups()
    group = _GROUP_MISREAD_TO_LETTER.get(group, group)
    return group + _RH_MISREAD_TO_SIGN.get(rh, rh)


# "1"/"2"/"8" are the fields whose printed label sits on its OWN line above
# the value (see FRONT_FIELD_REGIONS's module comment) rather than inline
# with it -- normally that means the tight crop already excludes the label
# entirely, no stripping needed. 2026-08-30: confirmed on a second real
# photo (Rana Rayess, after the reference-alignment fix) that this isn't
# always true -- field "2" read back "2. RANA" instead of "RANA", the
# region's top edge catching the tail of the printed "2." a few pixels
# above where it landed on the reference photo.
#
# Deliberately NOT using _strip_inline_label's widest-gap heuristic here:
# that assumes the value itself is a single token, which breaks the first
# time it isn't -- Georges' own surname is two words ("EL", "ALAM"), and
# the widest gap in that crop (if no label token is even present) would
# fall *between* them, silently discarding "EL". Instead, only strip a
# leading token that is exactly this field's own printed number (e.g. "2"
# or "2.") -- never touches real multi-word name content, and is a no-op
# whenever the crop is clean (already true for "1" on this same photo).
_LEADING_FIELD_NUMBER_FIELDS: frozenset[str] = frozenset({"1", "2", "8"})
_LEADING_FIELD_NUMBER_RE = re.compile(r"^\s*(\d+[a-zA-Z]?)\.?\s+")


def _strip_leading_field_number(text: str, field_key: str) -> str:
    match = _LEADING_FIELD_NUMBER_RE.match(text)
    if match and match.group(1) == field_key:
        return text[match.end():].strip()
    return text


# 2026-09-14: fields "4a" (issue date) and "4b" (expiry date) have the
# identical inert-whitelist problem "13b" had before _normalize_blood_type
# existed -- INLINE_LABEL_FIELDS' "0123456789/" whitelist for these two
# fields (see that dict's docstring) is inert under Vision (no character-
# whitelist concept), so nothing actually stops a letter/digit lookalike
# from surviving into the field's text. Confirmed in real use (Charbel
# Sfeir photo, IDL_APP_DEBUG_OCR dump): the expiry date read back as
# "DB / 09 / 2024" -- almost certainly "08/09/2024" misread the same
# direction _normalize_blood_type already corrects for "13b" ("0"<->letter
# lookalikes), just with "0"->"D" and "8"->"B" instead of "0"->"O". Per
# Georgio (2026-09-14): a date field must never contain letters -- there is
# no such thing as a genuine letter in a DD/MM/YYYY date printed on this
# license, so any letter that survives OCR is always a misread digit, never
# a genuine character. Known lookalikes are corrected via the mapping
# below; if what's left still isn't a clean D+/M+/Y+ shape (either an
# unmapped character, or digits missing/extra), extract_license_front flags
# the field instead of silently showing something wrong -- same "correct
# what's confidently a known misread, flag what isn't" split as "13b".
_DATE_FIELDS: frozenset[str] = frozenset({"4a", "4b"})
_DATE_LETTER_MISREAD_TO_DIGIT = {
    "D": "0", "O": "0", "o": "0", "Q": "0",
    "I": "1", "l": "1", "i": "1",
    "Z": "2", "z": "2",
    "B": "8",
    "S": "5", "s": "5",
    "G": "6",
    "T": "7",
}
_CLEAN_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def _normalize_date_field(text: str) -> str:
    """Corrects known digit/letter lookalikes (see
    _DATE_LETTER_MISREAD_TO_DIGIT above) in a DD/MM/YYYY-formatted license
    date field, and collapses whitespace around the slashes the same way a
    generous inline-label crop can leave some (e.g. "DB / 09 / 2024") --
    same rationale as _normalize_blood_type's own whitespace strip. Does
    NOT itself flag/validate the result -- extract_license_front checks it
    against _CLEAN_DATE_RE and flags the field when it still isn't a clean
    date, the same two-step pattern "13b" uses with _CLEAN_BLOOD_TYPE_RE."""
    text = re.sub(r"\s*/\s*", "/", text.strip())
    return "".join(_DATE_LETTER_MISREAD_TO_DIGIT.get(ch, ch) for ch in text)


def _words_to_text(words: list[OcrWord]) -> str:
    """Joins OCR words back into text ourselves (grouping into lines by
    vertical proximity, left-to-right within each line, top-to-bottom
    across lines) instead of trusting Vision's own full_text
    reconstruction. Used only for _LEADING_FIELD_NUMBER_FIELDS: those are
    exactly the fields ocr_client._dedupe_overlapping_words was added for
    (see that module's 2026-09-06 docstring entry — a real photo's field
    "8" got a spurious duplicate "00" word from the same glyph as its "8"
    label), and that dedup only touches the `words` list, not Vision's own
    `full_text` string, which is built from Vision's internal word list,
    not this module's — so a caller that keeps reading `full_text` would
    never see the benefit of it. Kept as a separate, narrowly-applied
    helper (not swapped in for every field) since Vision's own text
    reconstruction is likely better-tuned for fields this module doesn't
    need to defend against this specific artifact for."""
    if not words:
        return ""
    lines: list[list[OcrWord]] = []
    for w in sorted(words, key=lambda w: w.box[1]):
        cy = (w.box[1] + w.box[3]) / 2
        for line in lines:
            top = min(x.box[1] for x in line)
            bottom = max(x.box[3] for x in line)
            if top - 4 <= cy <= bottom + 4:
                line.append(w)
                break
        else:
            lines.append([w])
    lines.sort(key=lambda line: min(w.box[1] for w in line))
    return " ".join(
        " ".join(w.text for w in sorted(line, key=lambda w: w.box[0]))
        for line in lines
    )


def _strip_inline_label(words: list[OcrWord]) -> str:
    """For an INLINE_LABEL_FIELDS crop (label + value on one baseline),
    finds the label programmatically instead of depending on the crop's
    pixel boundary to have excluded it: sort the detected words left to
    right, split at the single widest horizontal gap between consecutive
    words, and keep only what comes after it.

    This works even when OCR misreads the label into pure garbage — seen
    repeatedly in practice ("13b" misread as "13d", "4b" misread as "@",
    "13a" misread as "18") — because the split never depends on
    recognizing what the label word actually says, only on where the
    widest gap in the line falls. The label is reliably the most isolated
    token: real value content (a date, a name, "O+") has normal
    letter/word spacing between its own words, which every real-card
    measurement here found narrower than the deliberate gap printed
    between a field's label and its value.

    Falls back to returning everything (label included) when there's only
    0-1 detected words to split — can't safely guess a split point, and
    this is never worse than the field's pre-2026-08-23 behavior."""
    if not words:
        return ""
    ordered = sorted(words, key=lambda w: w.box[0])
    if len(ordered) == 1:
        return ordered[0].text
    gaps = [(ordered[i + 1].box[0] - ordered[i].box[2], i) for i in range(len(ordered) - 1)]
    _, split_at = max(gaps)
    return " ".join(w.text for w in ordered[split_at + 1:])


@dataclass
class FieldRead:
    value: str
    confidence: float
    flagged: bool


@dataclass
class LicenseFrontResult:
    fields: dict[str, FieldRead] = field(default_factory=dict)
    deskew_failed: bool = False
    error: str | None = None


@dataclass
class LicenseBackResult:
    held_categories: list[str] = field(default_factory=list)
    category_dates: dict[str, dict[str, str]] = field(default_factory=dict)  # cat -> {issue, expiry}
    deskew_failed: bool = False
    error: str | None = None


def _ocr_crop(card_image, region, label: str, debug_dir: str | None = None,
               errors: list[str] | None = None, char_whitelist: str | None = None,
               psm_fallback: bool = True, keep_arabic: bool = False,
               psm: int | None = None, strip_inline_label: bool = False,
               language_hints: list[str] | None = None,
               rebuild_text_from_words: bool = False,
               on_words: Callable[[list[OcrWord]], None] | None = None) -> FieldRead:
    """OCRs one cropped field region. Never raises OcrError — a failure here
    (e.g. Vision credentials missing/invalid, no network) is caught and
    turned into a flagged-empty field for just this one region, with the
    message appended to `errors` (deduplicated) so the caller can surface it
    at the document level instead of it vanishing silently. Previously this
    *did* propagate, which meant one failing field aborted every remaining
    field on that side of the license — the very first OCR call failing
    (back when this ran on Tesseract, e.g. because the Arabic language pack
    wasn't installed) meant literally every front-of-license field came
    back blank, with no indication why.

    psm/strip_inline_label/language_hints are set by callers using
    INLINE_LABEL_FIELDS (see that dict's docstring) — psm forces --psm 6 up
    front (required whenever char_whitelist is set for one of these
    fields, see module docstring), strip_inline_label runs the OCR'd words
    through _strip_inline_label instead of taking the crop's full text
    as-is, and language_hints overrides the default ["ar", "en"] for a
    whitelisted field with no Arabic content at all — confirmed against a
    real crop that ar+eng still misreads a whitelisted pure-digit date
    ("20/05/2021" came back "7 1") where the identical crop with
    language_hints=["en"] read it correctly at 95% confidence; a
    whitelist alone does not substitute for picking the right language
    model. All default to "off"/None so every other caller (back-of-card
    category cells, and front fields not in INLINE_LABEL_FIELDS) keeps its
    original behavior unchanged.

    rebuild_text_from_words is set by callers using
    _LEADING_FIELD_NUMBER_FIELDS — see _words_to_text's docstring for why
    those specifically need text rebuilt from the (deduplicated) word list
    rather than taken from Vision's own full_text.

    on_words, if given, is called with the raw detected word list as soon
    as OCR succeeds (before any label-stripping/rebuilding), letting a
    caller capture the words for its own post-processing without changing
    this function's return type — used by field "13b" (see
    _normalize_blood_type_from_words) to fall back to a different
    label/value split than _strip_inline_label's when that one comes back
    incomplete."""
    crop = crop_region(card_image, region)
    save_crop(debug_dir, label, crop)
    if crop.size == 0:
        log_ocr_result(label, "", 0.0, True)
        return FieldRead(value="", confidence=0.0, flagged=True)

    try:
        result = ocr_image_array(crop, language_hints=language_hints or ["ar", "en"],
                                  char_whitelist=char_whitelist,
                                  psm_fallback=psm_fallback, keep_arabic=keep_arabic, psm=psm)
    except OcrError as e:
        logger.warning("OCR failed for region %s: %s", label, e)
        log_ocr_result(label, f"<OCR ERROR: {e}>", 0.0, True)
        if errors is not None and str(e) not in errors:
            errors.append(str(e))
        return FieldRead(value="", confidence=0.0, flagged=True)

    # 2026-09-03: dump the raw per-word OCR result (text/confidence/box),
    # same as passport_ocr.py's save_ocr_words -- log_ocr_result below only
    # records the *final* text (post label-strip), which is enough to see
    # THAT a field misread but not WHY (label-strip split at the wrong gap
    # vs. the OCR itself dropping/misreading a character). Real ground
    # truth beats guessing, same rationale as the passport-side fix.
    save_ocr_words(debug_dir, label, result.words)
    if on_words is not None:
        on_words(result.words)

    if strip_inline_label:
        text = _strip_inline_label(result.words)
    elif rebuild_text_from_words:
        text = _words_to_text(result.words)
    else:
        text = result.full_text.strip().replace("\n", " ")
    conf = result.average_confidence()
    flagged = conf < LOW_CONFIDENCE_THRESHOLD or not text
    log_ocr_result(label, result.full_text, conf, flagged)
    return FieldRead(value=text, confidence=conf, flagged=flagged)


def extract_license_front(image_path: str, debug_dir: str | None = None) -> LicenseFrontResult:
    image = cv2.imread(image_path)
    if image is None:
        return LicenseFrontResult(error=f"Could not read image: {image_path}")

    card = deskew_card(image)
    deskew_failed = card is None
    if card is None:
        # Fall back to the raw photo — lower accuracy, but still attempt it
        # rather than failing outright, and every field gets flagged since
        # crop regions won't align precisely against an un-deskewed photo.
        card = image
    save_crop(debug_dir, "front_00_deskewed_full_card" if not deskew_failed else "front_00_RAW_deskew_failed", card)

    if not deskew_failed:
        _load_reference_cards()
        if _reference_front is not None:
            card = align_to_reference(card, _reference_front)
            save_crop(debug_dir, "front_00b_aligned_to_reference", card)

    fields: dict[str, FieldRead] = {}
    errors: list[str] = []
    for key, region in FRONT_FIELD_REGIONS.items():
        keep_arabic = key in _KEEP_ARABIC_FIELDS
        if key in INLINE_LABEL_FIELDS:
            whitelist = INLINE_LABEL_FIELDS[key]
            # A whitelisted field never has real Arabic content (see
            # INLINE_LABEL_FIELDS' docstring) -- restrict recognition to
            # English only, not just the whitelist, for that field. See
            # _ocr_crop's language_hints note for why the whitelist alone
            # isn't enough.
            captured_words: list[OcrWord] = []
            read = _ocr_crop(card, region, f"front_{key}", debug_dir, errors,
                              char_whitelist=whitelist, psm=6 if whitelist is not None else None,
                              strip_inline_label=True, keep_arabic=keep_arabic,
                              language_hints=["en"] if whitelist is not None else None,
                              on_words=captured_words.extend if key == "13b" else None)
            if key == "13b":
                if read.value:
                    read.value = _normalize_blood_type(read.value)
                # The split-then-normalize result above can come back
                # incomplete (e.g. just the Rh sign) when the label fused
                # with the value's first character in the same OCR word --
                # see _normalize_blood_type_from_words' docstring. Only
                # fall back when it's genuinely needed: every case that
                # already resolves cleanly here is left untouched.
                if not read.value or not _CLEAN_BLOOD_TYPE_RE.fullmatch(read.value):
                    fallback_value = _normalize_blood_type_from_words(captured_words)
                    if fallback_value:
                        read.value = fallback_value
            elif key in _DATE_FIELDS:
                if read.value:
                    read.value = _normalize_date_field(read.value)
                if read.value and not _CLEAN_DATE_RE.fullmatch(read.value):
                    # Not a clean DD/MM/YYYY shape even after correcting
                    # known letter->digit lookalikes -- per Georgio, a date
                    # must never show letters, so this is surfaced to staff
                    # for manual review rather than displayed as-is.
                    read.flagged = True
        else:
            read = _ocr_crop(card, region, f"front_{key}", debug_dir, errors, keep_arabic=keep_arabic,
                              rebuild_text_from_words=key in _LEADING_FIELD_NUMBER_FIELDS)
            if key in _LEADING_FIELD_NUMBER_FIELDS and read.value:
                read.value = _strip_leading_field_number(read.value, key)
        if deskew_failed:
            read.flagged = True
        fields[key] = read

    return LicenseFrontResult(fields=fields, deskew_failed=deskew_failed, error="; ".join(errors) or None)


def _sub_region(row_region, split):
    x0, y0, x1, y1 = row_region
    row_w = x1 - x0
    return (x0 + split[0] * row_w, y0, x0 + split[1] * row_w, y1)


def extract_license_back(image_path: str, debug_dir: str | None = None) -> LicenseBackResult:
    image = cv2.imread(image_path)
    if image is None:
        return LicenseBackResult(error=f"Could not read image: {image_path}")

    card = deskew_card(image)
    deskew_failed = card is None
    if card is None:
        card = image
    save_crop(debug_dir, "back_00_deskewed_full_card" if not deskew_failed else "back_00_RAW_deskew_failed", card)

    if not deskew_failed:
        _load_reference_cards()
        if _reference_back is not None:
            card = align_to_reference(card, _reference_back)
            save_crop(debug_dir, "back_00b_aligned_to_reference", card)

    held_categories = []
    category_dates: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for cat, row_region in BACK_CATEGORY_ROWS.items():
        issue_region = _sub_region(row_region, ROW_ISSUE_DATE_SPLIT)
        expiry_region = _sub_region(row_region, ROW_EXPIRY_DATE_SPLIT)
        # psm_fallback=False: a row counts as "held" only if it actually
        # has a date filled in — blank rows (no OCR text at all) are
        # categories the holder is not licensed for, per the brief. That
        # makes "zero OCR text" itself the trusted signal here, unlike a
        # free-form name field where it just means the read failed — so
        # the PSM 6 fallback (which reads harder and can turn a truly
        # blank cell's paper texture into fabricated low-confidence text)
        # must stay off, or a genuinely-not-held category could get
        # spuriously marked "held".
        issue_read = _ocr_crop(card, issue_region, f"back_{cat}_issue", debug_dir, errors,
                                psm_fallback=False)
        expiry_read = _ocr_crop(card, expiry_region, f"back_{cat}_expiry", debug_dir, errors,
                                 psm_fallback=False)
        if issue_read.value or expiry_read.value:
            held_categories.append(cat)
            category_dates[cat] = {"issue": issue_read.value, "expiry": expiry_read.value}

    return LicenseBackResult(held_categories=held_categories, category_dates=category_dates,
                              deskew_failed=deskew_failed, error="; ".join(errors) or None)
