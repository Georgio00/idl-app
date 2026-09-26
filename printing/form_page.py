"""
Renders the "Application for I D L" PDF -- added 2026-09-26 after Georgio
photographed the actual paper form (a printed record for KORDAHI KARIM)
and asked to add "Print Form"/"View Form", the third pair from LAA's own
screen alongside "Print/View Licence" (this app's existing Print Preview/
Print) and "Print/View Receipt" (printing/receipt_page.py).

Like the Cash Receipt and unlike printing/print_page.py's booklet-page
render, this draws the ENTIRE page -- title, every label, both section
dividers, everything -- rather than overlaying data onto a pre-printed
physical page, since the photographed form is a plain, self-contained
sheet of paper with no special pre-printed stock involved.

Layout, read directly off the photograph:

1. "Application for I D L" -- bold, underlined, centered title.
2. A personal-details block, NO section header, one label per line:
   Surname, First Name, Father's Name, Mother's Name, Place of B.,
   Date of B., Address, Phone, Email, Blood Type. Georgio's own New IDL
   form only collects Surname/First Name/Father's Name/Place of B./
   Date of B. (see gui/new_idl_form.py's docstring, "2026-09-14") --
   Mother's Name/Address/Phone/Email/Blood Type are simply not
   collected, so they render as blank labels here, exactly as they do on
   the photographed original itself (that real KORDAHI record has them
   blank too -- confirmed directly from the photo, not an assumption).
3. A hatched divider line (a row of "/" characters, matching the
   photograph exactly rather than a plain rule).
4. "ORIGINAL DOCUMENT" -- bold, centered section header, then Number/Date
   paired on one row (see _draw_paired_row), then Place of Issue,
   Category, Expiry Date each on their own line.
5. Another hatched divider.
6. "ISSUED DOCUMENT" -- same header style, then Number/Date paired on one
   row. No Signature field is part of this section on the original --
   see point 7.
7. "Signature:" -- a bare label with a blank line after it, same
   "label only, nothing to actually sign in a PDF" treatment
   printing/receipt_page.py's _draw_signature already uses.

No Receipt fields anywhere on this page -- confirmed directly from the
photograph, which ends at Issued Document + Signature. The Cash Receipt
(printing/receipt_page.py) is a genuinely separate document.

Page size: A4 portrait, same placeholder-but-reasonable default
printing/receipt_page.py's docstring already explains for a plain-paper
office document -- worth confirming once a real printed copy can be
measured directly, same caveat as that module's.
"""

from __future__ import annotations

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

_TITLE = "Application for I D L"
_MARGIN = 20 * mm
_LINE_HEIGHT = 7 * mm
_NAVY = (0.10, 0.16, 0.32)

# Personal-details labels, in the exact order the photographed form shows
# them -- see module docstring point 2 for which of these this app's own
# New IDL form actually collects a value for (the rest always render
# blank, matching the real photographed record).
_PERSONAL_FIELDS = [
    ("Surname:", "surname"),
    ("First Name:", "first_name"),
    ("Father's Name:", "father_name"),
    ("Mother's Name:", "mother_name"),
    ("Place of B.:", "place_of_birth"),
    ("Date of B.:", "date_of_birth"),
    ("Address:", "address"),
    ("Phone:", "phone"),
    ("Email:", "email"),
    ("Blood Type:", "blood_type"),
]


def _draw_title(c: canvas.Canvas, page_w: float, y: float) -> float:
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(page_w / 2, y, _TITLE)
    title_width = c.stringWidth(_TITLE, "Helvetica-Bold", 15)
    underline_y = y - 2
    c.line(page_w / 2 - title_width / 2, underline_y, page_w / 2 + title_width / 2, underline_y)
    return y - 14 * mm


def _draw_labeled_line(c: canvas.Canvas, x: float, y: float, label: str, value: str) -> None:
    c.setFont("Helvetica", 10)
    c.drawString(x, y, label)
    label_width = c.stringWidth(label + "  ", "Helvetica", 10)
    if value:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + label_width, y, value)


def _draw_personal_section(c: canvas.Canvas, y: float, values: dict) -> float:
    for label, key in _PERSONAL_FIELDS:
        _draw_labeled_line(c, _MARGIN, y, label, values.get(key, ""))
        y -= _LINE_HEIGHT
    return y


def _draw_divider(c: canvas.Canvas, page_w: float, y: float) -> float:
    # A row of "/" characters, matching the hatched divider line on the
    # photographed original (see module docstring point 3) rather than a
    # plain horizontal rule.
    c.setFont("Helvetica", 8)
    slash_width = c.stringWidth("/", "Helvetica", 8)
    count = max(1, int((page_w - 2 * _MARGIN) / slash_width))
    c.drawString(_MARGIN, y, "/" * count)
    return y - 10 * mm


def _draw_section_header(c: canvas.Canvas, page_w: float, y: float, title: str) -> float:
    c.setFillColorRGB(*_NAVY)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(page_w / 2, y, title)
    c.setFillColorRGB(0, 0, 0)
    return y - 9 * mm


def _draw_paired_row(c: canvas.Canvas, y: float, number_value: str, date_value: str) -> float:
    _draw_labeled_line(c, _MARGIN, y, "Number:", number_value)
    _draw_labeled_line(c, _MARGIN + 70 * mm, y, "Date:", date_value)
    return y - _LINE_HEIGHT


def _draw_original_document_section(c: canvas.Canvas, page_w: float, y: float, values: dict) -> float:
    y = _draw_section_header(c, page_w, y, "ORIGINAL DOCUMENT")
    y = _draw_paired_row(c, y, values.get("orig_number", ""), values.get("orig_date", ""))
    _draw_labeled_line(c, _MARGIN, y, "Place of Issue:", values.get("orig_place_of_issue", ""))
    y -= _LINE_HEIGHT
    _draw_labeled_line(c, _MARGIN, y, "Category:", values.get("orig_category", ""))
    y -= _LINE_HEIGHT
    _draw_labeled_line(c, _MARGIN, y, "Expiry Date:", values.get("orig_expiry_date", ""))
    y -= _LINE_HEIGHT
    return y


def _draw_issued_document_section(c: canvas.Canvas, page_w: float, y: float, values: dict) -> float:
    y = _draw_section_header(c, page_w, y, "ISSUED DOCUMENT")
    y = _draw_paired_row(c, y, values.get("issued_number", ""), values.get("issued_date", ""))
    return y


def _draw_signature(c: canvas.Canvas, y: float) -> None:
    c.setFont("Helvetica", 10)
    c.drawString(_MARGIN, y, "Signature:")


def render_form(values: dict, output_path: str) -> None:
    """values keys: see form_values_from_form_fields for how the New IDL
    form's field dict maps onto these (surname, first_name, father_name,
    mother_name, place_of_birth, date_of_birth, address, phone, email,
    blood_type, orig_number, orig_date, orig_place_of_issue,
    orig_category, orig_expiry_date, issued_number, issued_date). Any
    missing key renders as a blank value rather than raising, same
    "never crash on incomplete data" contract as render_receipt."""
    page_w, page_h = A4
    c = canvas.Canvas(output_path, pagesize=A4)

    y = page_h - _MARGIN
    y = _draw_title(c, page_w, y)
    y = _draw_personal_section(c, y, values)
    y = _draw_divider(c, page_w, y)
    y = _draw_original_document_section(c, page_w, y, values)
    y = _draw_divider(c, page_w, y)
    y = _draw_issued_document_section(c, page_w, y, values)
    y -= 12 * mm
    _draw_signature(c, y)

    c.showPage()
    c.save()


def form_values_from_form_fields(form_fields: dict) -> dict:
    """Maps the New IDL form's field dict to render_form's value keys --
    same v() unwrap-a-FieldRead-or-plain-string helper printing/
    print_page.py's values_from_form_fields and printing/receipt_page.py's
    receipt_values_from_form_fields already use. Mother's Name/Address/
    Phone/Email/Blood Type have no corresponding key in form_fields at all
    (see this module's docstring point 2) -- .get returns None for those,
    and v() turns that into "" the same as any other missing key."""
    def v(key):
        f = form_fields.get(key)
        return f.value if hasattr(f, "value") else (f or "")

    return {
        "surname": v("Surname"),
        "first_name": v("First Name"),
        "father_name": v("Father's Name"),
        "mother_name": v("Mother's Name"),
        "place_of_birth": v("Place of B."),
        "date_of_birth": v("Date of B."),
        "address": v("Address"),
        "phone": v("Phone"),
        "email": v("Email"),
        "blood_type": v("Blood Type"),
        "orig_number": v("Original Document.Number"),
        "orig_date": v("Original Document.Date"),
        "orig_place_of_issue": v("Original Document.Place of Issue"),
        "orig_category": v("Original Document.Category"),
        "orig_expiry_date": v("Original Document.Expiry Date"),
        "issued_number": v("Issued Document.Number"),
        "issued_date": v("Issued Document.Date"),
    }


def render_form_from_form_fields(field_values: dict, output_path: str) -> None:
    """Shared entry point mirroring printing/receipt_page.py's
    render_receipt_from_form_fields -- callers (gui/new_idl_form.py's
    view_form/print_form_to_printer) pass the raw form field dict straight
    through rather than pre-mapping it themselves."""
    values = form_values_from_form_fields(field_values)
    render_form(values, output_path)
