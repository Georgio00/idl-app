"""
Field region config for the Lebanese driving license, front and back.

Each region is (x0, y0, x1, y1) as FRACTIONS of the deskewed card image
(see image_prep.CARD_SIZE) — not absolute pixels — so the same config works
regardless of source photo resolution, matching the relative-percentage
approach used for the IDP print layout.

Calibrated 2026-08-20 against a real sample license (Georges El Alam) via
ocr/debug_dump.py's debug output (IDL_APP_DEBUG_OCR=1) — the deskewed full
card was inspected directly (a percentage grid was overlaid on the saved
front_00_deskewed_full_card.png / a color-corrected back deskew, and each
field's real position read off it), not guessed from the field layout
description alone, which is what the original placeholder values were.

These should still be treated as tuned-for-one-sample, not
guaranteed-universal: font size/position can vary slightly between
printings of the same license template, and a different card's photo
angle/crop could shift the deskewed card enough to need re-tuning. If
autofill drifts again, re-run with IDL_APP_DEBUG_OCR=1 (see
gui/new_idl_form.py), inspect the saved front_00_deskewed_full_card.png /
back deskew, and adjust the fractions below the same way — there is no
separate ocr/calibrate_license.py tool; the debug dump + manual
measurement against the deskewed image is the calibration process.

"13b" (blood type) went through two more narrow-tightening passes on
2026-08-23 (0.79 -> 0.804 x0) chasing the same "label bleeds into the
value" bug, and even the second pass was still fragile: re-verified
against a live OCR run rather than just a visual crop, that tight box
still misread the value outright ("O+" came back "04", or blank once a
character whitelist was added) — a couple of pixels either way changed
what a crop this small reads as. Same day, this was replaced for "3",
"4a", "4b", "4c", "13a", "13b", "13c", "13d" with a different strategy:
size the crop generously instead of tightly, and strip the label out of
the OCR'd text programmatically. See the comment below and
ocr.license_ocr's module docstring for the full rationale — the short
version is that a *tight* box has to land exactly between label and value
to keep the label out, and that boundary kept drifting under small
skew/zoom differences between photos; a generous box that's merely wide
enough to contain both, combined with finding the label by its position
in the OCR output rather than by pixel geometry, doesn't have that
failure mode.
"""

# Front of card. Keys match ocr.license_fields.LICENSE_FRONT_FIELDS.
#
# "3", "4a", "4b", "4c", "5", "13a", "13b", "13c", "13d" are sized generously
# on purpose (see module docstring): all nine print their field-number label
# inline with the value, space-separated on the same baseline (unlike
# "1"/"2"/"8", whose label sits on its own line above the value, or "15",
# which sits hard against the photo/rosette artwork and needs a different
# fix not attempted here) — ocr.license_ocr._strip_inline_label finds the
# label in the OCR'd words from these crops and strips it, so the crop only
# needs to safely contain both label and value, not exclude the label
# itself.
#
# 2026-08-27: "5" (license number) added to this group — Georgio reported
# real reads coming back as "5 2031935" (the field-number label "5" glued
# onto the actual number by a space, same failure shape as every other
# field in this list before it got the generous-crop + label-strip
# treatment). The crop region below was already generous enough to contain
# both label and value (that's exactly why the label was showing up in the
# output) — see ocr.license_ocr.INLINE_LABEL_FIELDS for the other half of
# this fix (adding "5" there is what actually turns strip-the-label on;
# this file only defines *where* to crop, not *how* to parse what's in it).
FRONT_FIELD_REGIONS: dict[str, tuple[float, float, float, float]] = {
    "1":   (0.33, 0.24,  0.62, 0.32),    # surname
    "2":   (0.33, 0.32,  0.62, 0.40),    # given name
    "3":   (0.356, 0.415, 0.628, 0.476), # dob + place of birth (generous, label-stripped)
    "4a":  (0.354, 0.481, 0.559, 0.538), # issue date (generous, label-stripped)
    "4b":  (0.359, 0.542, 0.623, 0.602), # expiry date (generous, label-stripped)
    "4c":  (0.358, 0.602, 0.653, 0.647), # issuing authority (generous, label-stripped)
    "5":   (0.72, 0.14,  0.99, 0.22),    # license number (generous, label-stripped as of 2026-08-27)
    "8":   (0.35, 0.765, 0.60, 0.83),    # place of residence
    "13a": (0.361, 0.647, 0.678, 0.718), # nationality (generous, label-stripped)
    "13b": (0.748, 0.647, 0.847, 0.697), # blood type (generous, label-stripped)
    "13c": (0.363, 0.723, 0.488, 0.776), # father's name (generous, label-stripped)
    "13d": (0.749, 0.697, 0.935, 0.757), # mother's name (generous, label-stripped)
    "15":  (0.75, 0.595, 0.92, 0.655),   # sex
}

# Back of card: one row per category, each with an issue-date cell and an
# expiry-date cell. A row is "held" if its date cells are non-blank.
# x-range covers just the "11." (expiry) and "10." (issue) columns of the
# printed table — excludes the "12." restrictions column to the left and
# the "9." category/icon column to the right, neither of which is needed.
BACK_CATEGORY_ROWS: dict[str, tuple[float, float, float, float]] = {
    "A1":                     (0.38, 0.115, 0.655, 0.165),
    "A":                      (0.38, 0.165, 0.655, 0.215),
    "B1":                     (0.38, 0.215, 0.655, 0.265),
    "B":                      (0.38, 0.265, 0.655, 0.315),
    "C1":                     (0.38, 0.315, 0.655, 0.365),
    "C":                      (0.38, 0.365, 0.655, 0.415),
    "CE":                     (0.38, 0.415, 0.655, 0.465),
    "D1":                     (0.38, 0.465, 0.655, 0.515),
    "D":                      (0.38, 0.515, 0.655, 0.565),
    "agricultural_vehicles":  (0.38, 0.565, 0.655, 0.615),
    "construction_equipment": (0.38, 0.615, 0.655, 0.665),
}

# Within a category row, the printed table reads (left to right): "12."
# restrictions | "11." expiry date | "10." issue date | "9." category —
# i.e. EXPIRY is the left half of our row region (which starts at the "11."
# column) and ISSUE is the right half, not the other way around. Split
# measured directly off the printed column divider line (at ~54.7% of the
# row region's width), not assumed to be a clean 50/50 midpoint.
ROW_EXPIRY_DATE_SPLIT = (0.0, 0.547)
ROW_ISSUE_DATE_SPLIT = (0.547, 1.0)