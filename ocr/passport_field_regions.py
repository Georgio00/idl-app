"""
Field region config for the passport's printed bio-data page — the area
above the MRZ band that passport_ocr.py's MRZ crop (see
passport_ocr._crop_mrz_band, bottom ~24.5% of the photo) doesn't cover.

2026-08-30: replaced the old per-field fixed-fraction BIO_FIELD_REGIONS
dict (two tight (x0,y0,x1,y1) boxes, one for father's name and one for
place of birth) with a single generous BIO_SEARCH_REGION. Full history of
why is kept below for context, but the short version: a fixed fraction of
the *photo* only lands on the right spot for the one specific photo's
framing/zoom it was measured from — confirmed broken twice now on real
photos from different people (see the 2026-08-27 and 2026-08-30 entries
below), most recently on a second person's passport photo where BOTH
fields read completely different, unrelated page text (the page's own
header, and a nearby "Nationality" label) despite the fractions having
already been re-tuned once against real debug crops in between.

The passport isn't run through image_prep's card-corner-detect-and-deskew
step (see below for why), so unlike the license's field regions — which
stay correct across any photo because they're fractions of a canonically
deskewed card, not the raw photo — a passport bio-data field's position
as a fraction of the raw photo genuinely shifts with how the photo was
framed. No amount of recalibrating against one more sample photo fixes
that; the fraction only ever describes that one sample.

The fix: don't trust a fixed position at all. BIO_SEARCH_REGION only has
to be generous enough to contain both target fields' printed labels
somewhere inside it — passport_ocr.py then finds each field's actual
label ("Father name", "Place of birth") by text search over that region's
OCR output, and reads the value from the words positioned in the band
directly below the label's own detected bounding box (see
passport_ocr.py's module docstring and _extract_bio_field for the full
mechanism). That position is relative to the label's own detected size
and location, which scales with the photo's framing/zoom the same way the
label text itself does — so this generalizes across differently-framed
photos in a way a fixed fraction structurally cannot.

BIO_SEARCH_REGION itself only needs to comfortably contain the personal-
data block between the portrait photo and the MRZ band — it does not need
per-field precision, which is the whole point: it can afford to be
generous without the previous downside of a generous crop (a label
bleeding into the read), because label text search does the precision
work instead of a tight pixel boundary. Covers the full photo width
(framing margins vary photo to photo, and the fields are not reliably
centered) and roughly y 0.15-0.83 (starts well above where the data block
was seen to begin on any real sample so far; see the 2026-09-06 entry
below for why the bottom edge is 0.83, not flush against
_crop_mrz_band's own start).

2026-09-06: bottom edge extended from 0.755 to 0.83 after a fourth real
photo (Frederic Elias) showed place_of_birth's value line itself sitting
just past the old boundary. Measured directly off this photo's debug
crop/word dump: the photo is 921x1203; the real "Place of birth" label's
words landed at y=716-727 *inside* the 0.15-0.755 crop (i.e. right at its
728px-tall bottom edge), and the value below it ("RMEICH", confirmed
against the raw photo) sits at full-photo y=923-948 — entirely outside
the old 908px cutoff (0.755*1203), so it was never even OCR'd, let alone
read. 0.83*1203=~998 comfortably clears it (~50px margin) while staying
short of this photo's own MRZ line (~y=1050, 0.873) by a similar margin.

This does mean the region can now overlap _crop_mrz_band's own start
(0.755) on some photos, which the region's own comment used to rule out
by design — deliberately dropped rather than preserved once real evidence
showed it wasn't actually load-bearing: a real photo from a different
person (Rana Rayess, see the 2026-08-30 history below) already had its
actual MRZ line fall *inside* the old 0.15-0.755 region (that person's
photo has the MRZ around 58-61% down the frame, comfortably under 0.755),
and it caused no corruption at all — passport_ocr.py's label/keyword
searches ("father", "place", "first", "national", "lebanese") don't match
MRZ text, and every value band it reads is sized relative to a label's
own height (a handful of line-heights), not to how much of the crop is
left below it, so MRZ text sitting far below the actual bio-page labels
never entered any field's candidate window. Confirmed by re-reading that
photo's own saved word dump rather than assumed. Extending the region
further in the same direction carries the same, already-proven-harmless
risk — not a new one.

--- History (why the region moved from fixed-fraction to search-based) ---

Calibrated 2026-08-23 against a real sample passport bio-data page scan
(Georges El Alam) — cropped to isolate just the bio-data page, a
percentage grid overlaid, and each field's real position read off it
directly, the same process used for license_field_regions.py. Also
confirmed on that sample: the passport DOES print "Father name" as a
labeled field (Arabic + Latin, e.g. "SAID") right below "First name" —
the project brief's field list for the MRZ doesn't include it because
it's genuinely not IN the MRZ, but it is on the printed page, same as
place of birth.

2026-08-27: the two-page-spread-derived fractions above turned out to be
badly wrong against Georgio's real single-page "Passport" photo (a
straight-on shot of just the bio-data page, framed with some background
margin around the physical page — not the tightly-cropped, differently-
proportioned two-page scan the original numbers were measured from).
Confirmed in production: place_of_birth was reading "on / République
Libanaise Code" — that's the page's own header text ("Republic of
Lebanon / République Libanaise..."), meaning the old y-fraction (0.517)
was landing barely a fifth of the way down the page instead of over
halfway down where the actual value sits. First recalibration pass (y=
0.385-0.475 / 0.545-0.590) was still wrong in the same direction, just
less badly: confirmed via the actual debug crops (passport_father_name.png
/ passport_place_of_birth.png) that the box's top edge was still catching
the tail end of the printed label line ("Father name SAID" was the read —
the crop included both the label and the value), and place_of_birth's box
was so short it cut off almost immediately after the label, catching only
the first couple of pixels of "RMEICH" before the box ended ("Place of
birth/35" — the "35" was OCR noise from those clipped pixels, not a real
read). Second recalibration pass was measured directly off those two
debug crop images instead of a percentage grid over the full photo — a
strictly more reliable method since it shows exactly what's being read
right now rather than an independent estimate — and produced fractions
that read Georgio's own photo correctly (never independently
re-confirmed before the issue below was found, though).

2026-08-30: tested against a real photo from a second person (Rana
Rayess) and confirmed BOTH fields broke again, in the exact same
"catching unrelated page text" way as the 2026-08-27 bug — father_name
read "on République Libanaii" (the page header again) and place_of_birth
read "WAKED Nationality" (a nearby label, not the value). Root-caused as
the structural issue described above, not a one-more-recalibration
problem: this photo was framed differently (different margin/zoom) from
either of the two samples the fixed fractions were tuned against, and
there is no fixed fraction that is correct for every framing. Replaced
the fixed per-field fractions with BIO_SEARCH_REGION + label text search
(see passport_ocr.py) so the next differently-framed photo doesn't need
another recalibration pass at all.
"""

# Fractions of the full passport photo (0,0)=top-left, (1,1)=bottom-right.
# Generously covers the personal-data block between the portrait photo and
# the MRZ band (see module docstring) — passport_ocr.py locates each
# field's actual position inside this region by searching for its printed
# label, rather than trusting a fixed position within it.
BIO_SEARCH_REGION: tuple[float, float, float, float] = (0.0, 0.15, 1.0, 0.83)
