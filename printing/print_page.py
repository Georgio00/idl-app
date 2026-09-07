"""
Renders the finalized IDL data onto a PDF sized to match the physical IDP
booklet page, positioned per printing.layout_config's relative-percentage
field boxes. The PDF is meant to be printed directly onto the pre-printed
blank booklet page (loaded into the printer tray) — this does not draw any
of the booklet's own design, only the variable data.

Category boxes (A-E) get an "X" drawn in them for held categories; everything
else is text.
"""

from __future__ import annotations

from reportlab.lib.pagesizes import portrait
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from printing.layout_config import load_layout

_FIELD_FONT = ("Helvetica", 9)
_MARK_FONT = ("Helvetica-Bold", 10)


def _draw_fields(c: canvas.Canvas, page_w_mm: float, page_h_mm: float, layout_fields: dict, values: dict):
    for key, box in layout_fields.items():
        if key not in values or not values[key]:
            continue
        x, y, w, h = box  # fractions, top-left origin
        # PDF origin is bottom-left, so flip y.
        px = x * page_w_mm * mm
        py = (1 - y - h) * page_h_mm * mm

        if key.startswith("category_"):
            c.setFont(*_MARK_FONT)
            c.drawCentredString(px + (w * page_w_mm * mm) / 2, py + 2, "X")
        else:
            c.setFont(*_FIELD_FONT)
            c.drawString(px, py + 2, str(values[key]))


def render_data_page(values: dict, output_path: str, layout: dict | None = None):
    """values keys match printing.layout_config.DEFAULT_DATA_PAGE_LAYOUT
    (surname, given_names, nationality, date_of_birth, place_of_birth,
    permit_number, issue_date, category_A..category_E as any truthy value
    to mark them held)."""
    layout = layout or load_layout()
    page_w_mm, page_h_mm = layout["page_size_mm"]
    c = canvas.Canvas(output_path, pagesize=(page_w_mm * mm, page_h_mm * mm))
    _draw_fields(c, page_w_mm, page_h_mm, layout["data_page"], values)
    c.showPage()
    c.save()


def render_cover_page(values: dict, output_path: str, layout: dict | None = None):
    """values keys: place_of_issue, valid_from."""
    layout = layout or load_layout()
    page_w_mm, page_h_mm = layout["cover_size_mm"]
    c = canvas.Canvas(output_path, pagesize=(page_w_mm * mm, page_h_mm * mm))
    _draw_fields(c, page_w_mm, page_h_mm, layout["cover_page"], values)
    c.showPage()
    c.save()


def values_from_form_fields(form_fields: dict, held_idp_categories: set[str]) -> dict:
    """Maps the New IDL form's field dict to the print-layout's field keys."""
    def v(key):
        f = form_fields.get(key)
        return f.value if hasattr(f, "value") else (f or "")

    values = {
        "surname": v("Surname"),
        "given_names": v("First Name"),
        "nationality": "",  # not currently captured as its own form field
        "date_of_birth": v("Date of B."),
        "place_of_birth": v("Place of B."),
        "permit_number": v("Issued Document.Number"),
        "issue_date": v("Issued Document.Date"),
    }
    for cat in ("A", "B", "C", "D", "E"):
        values[f"category_{cat}"] = "X" if cat in held_idp_categories else ""
    return values
