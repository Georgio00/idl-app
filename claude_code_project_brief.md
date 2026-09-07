# Project: IDL Auto-Fill Desktop App

## Context

We are a company that issues **International Driving Permits (IDPs)** —
also called IDLs — under the 1949 Geneva Convention format. We currently
use an existing Windows desktop app called **LAA** to manage this process,
but we only have the compiled app (no source code), so this is a **new,
separate desktop application built from scratch** that mirrors part of
LAA's functionality and adds automation LAA doesn't have.

## Goal

Build a Windows desktop app that:
1. Takes **3 photos as input**: 2 images of a Lebanese driving license
   (front + back) and 1 image of a passport photo page.
2. **Extracts data automatically (OCR)** from those photos.
3. **Auto-fills a data entry form** ("New IDL") with the extracted data,
   mirroring an existing internal app's field layout exactly (see below),
   so staff already trained on the old app need no retraining.
4. Lets staff **review and correct** any field before saving (OCR is not
   perfect — flag low-confidence fields, never silently trust a bad read).
5. **Prints the finalized data directly onto a pre-printed blank physical
   IDP booklet page** at precise coordinates (we own real IDP booklets;
   this is not generating a new document design, it's printing onto
   existing blank pre-printed pages).

This is an **internal company tool**, used by our own staff only — not a
public-facing app. No integration with the old LAA app is needed or
possible (we don't have access to modify it or its database).

## Users

Internal staff only, one company location, one Windows desktop machine
(not a multi-user/networked deployment for now — but don't over-narrow
the architecture if a lightweight local DB naturally makes multi-machine
easy later).

## Data sources (inputs)

### 1. Passport
Standard ICAO 9303 passport with an MRZ (Machine Readable Zone) — two
44-character lines at the bottom of the photo page, in this format:
```
P<LBNEL<ALAM<<GEORGES<<<<<<<<<<<<<<<<<<<<<<
LR18962688LBN9109076M3009211100145810 6<<20
```
The MRZ has built-in checksums — parse and validate them so a bad OCR
read is *detected*, not silently trusted. This yields: surname, given
names, passport number, nationality, date of birth, sex, expiry date.

### 2. Lebanese driving license (front + back)
Standardized layout, same numbered fields on every license:

**Front:**
| Field # | Meaning |
|---|---|
| 1 | Surname |
| 2 | Given name |
| 3 | Date & place of birth |
| 4a | Issue date |
| 4b | Expiry date |
| 4c | Issuing authority |
| 5 | License number |
| 7 | Holder signature |
| 8 | Place of residence |
| 13a | Nationality |
| 13b | Blood type |
| 13c | Father's name |
| 13d | Mother's name |
| 15 | Sex |

**Back:** a category table — rows for A1, A, B1, B, C1, C, CE, D1, D,
agricultural vehicles, construction equipment — each with issue date (col
10) and expiry date (col 11) filled in *only* for categories the holder
actually holds (blank rows = not licensed for that category).

Because the layout is standardized, prefer **region-based extraction**
(detect the card's 4 corners, deskew, crop each numbered field's known
region, then OCR each region individually) over OCR-then-guess on the
whole image — much higher accuracy for a fixed layout like this.

## Category mapping: Lebanese license → IDP

The IDP only has 5 broad category boxes (A/B/C/D/E) on its data page.
Map Lebanese categories to IDP boxes like this:

| Lebanese | IDP |
|---|---|
| A1, A | A (motorcycles) |
| B1, B | B (cars) |
| C1, C, CE | C (trucks) |
| D1, D | D (buses) |
| agricultural / construction equipment | *(no IDP equivalent — omit)* |

Only categories with a **filled-in date** on the back of the license
count as "held" — blank rows are not licensed.

## Output form fields ("New IDL" screen)

Must match this existing field layout exactly (mirrors LAA):

- Surname, First Name, Father's Name, Mother's Name, Place of B., Date of
  B., Address, Phone, Email, Blood Type
- **Original Document** group: Number, Date, Place of Issue, Category,
  Expiry Date *(this is the driving license's own details)*
- **Issued Document** group: Number, Date, Signature *(this is the new
  IDP being created — Number is app-generated, Date defaults to today,
  Signature stays manual/physical)*
- **Receipt** group: Received from, Date, Amount (LBP) *(manual,
  business-side, not from any ID document)*

Field source mapping:
- Phone, Email, Issued Document.Number, Issued Document.Signature,
  Receipt.* → **never auto-filled**, always manual entry.
- Mother's Name → passport only (not on the license).
- Father's Name → prefer license field 13c, fallback to passport.
- Everything else → prefer license, fallback to passport where both
  have it.

## Output: printing onto the physical IDP booklet

The IDP is a small multi-language booklet (1949 Geneva Convention
format). Only **one page** needs data printed on it — the rest are
pre-printed translation/legend pages. That page has:
- Fields 1–5: Surname, Given name(s), Nationality, Date of birth, Place
  of birth/residence
- A category grid (A/B/C/D/E) — mark the boxes per the mapping above
- Permit No. and issue Date
- The booklet's cover page also needs: place of issue, "valid from" date
  (signature stays manual)

**We do not yet have exact page dimensions or a blank template scan.**
Build the print-coordinate system as **relative percentages of the page**
(not hardcoded absolute pixel/mm values), with a small **calibration
screen** (click-and-drag field boxes over a photo of the page) so exact
positions can be tuned later without a code change, once we get a blank
booklet to measure precisely. Use ~74×105mm as a placeholder page size
for now.

It's always this **single template** — no multi-template system needed,
just a well-isolated layout config for this one page.

## Technical decisions made / open

- **Platform:** Windows desktop app.
- **OCR engine:** not yet chosen. Needs to handle mixed Arabic/Latin
  text well. Cloud options (Google Cloud Vision, Azure Document
  Intelligence) are more accurate; an offline option (Tesseract +
  Arabic trained data) exists if these documents must never leave the
  machine — confirm this constraint before hardcoding a cloud
  dependency, and keep the OCR call behind a clean interface so the
  engine can be swapped later regardless.
- **Storage:** local database for saved records (this is government ID
  data — encryption at rest matters even for an internal single-machine
  tool). SQLite with encryption (e.g. SQLCipher) is a reasonable
  default unless there's a reason to prefer something else.
- **No LAA integration** — this is a fully independent app.

## A prior prototype exists

A rough scaffold was already sketched (Python + PySide6) with:
- A working, tested MRZ parser with checksum validation
  (`ocr/mrz_parser.py`)
- A field-mapping/category-mapping module for the license
  (`ocr/license_fields.py`)
- A skeleton "New IDL" form UI matching the field layout above
  (`gui/new_idl_form.py`), with an autofill button stubbed pending OCR
  engine choice

Treat this as a rough starting reference, not a locked-in architecture —
feel free to restructure as you see fit, but the MRZ parsing logic and
field mapping tables in it are already validated against real sample
documents and worth reusing or porting rather than redoing from
scratch.

## What to do first

1. Confirm the OCR engine choice (ask if the offline-vs-cloud data
   question hasn't been answered yet — it changes the architecture).
2. Set up the project (language/framework — Python+PySide6 is a
   reasonable default matching the existing scaffold, but flag if you'd
   recommend otherwise for a Windows desktop OCR app).
3. Build the OCR pipeline end-to-end for one document type first
   (passport MRZ is the most reliable place to start — checksums make
   correctness verifiable), then the license.
4. Build the review/edit form, then the print/calibration step last,
   since it's the most blocked on missing physical measurements.
