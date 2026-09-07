"""
PDF handling for the ID photo upload boxes: renders PDF pages to images so
scanned documents flow through the exact same OCR pipeline and thumbnail
preview as a photographed ID — nothing downstream ever needs to know a
given upload started life as a PDF.

Depends on pdf2image (pip), which itself wraps the poppler command-line
tools (pdftoppm/pdfinfo). Poppler is a separate native install on Windows,
not something pip pulls in — see README.md for the install link. This is
the same category of gotcha as the Tesseract binary in ocr/ocr_client.py.
"""

from __future__ import annotations

from PIL import Image


class PdfError(RuntimeError):
    """Raised when a PDF can't be read/rendered — most commonly because
    poppler isn't installed (see README.md)."""


def _import_pdf2image():
    try:
        import pdf2image
    except ImportError as e:
        raise PdfError("pdf2image is not installed. Run: pip install pdf2image") from e
    return pdf2image


def get_page_count(pdf_path: str) -> int:
    pdf2image = _import_pdf2image()
    try:
        info = pdf2image.pdfinfo_from_path(pdf_path)
        return int(info["Pages"])
    except Exception as e:  # noqa: BLE001 - surface as PdfError, not a raw pdf2image/poppler exception
        raise PdfError(
            f"Could not read '{pdf_path}' as a PDF (is poppler installed? see README.md): {e}"
        ) from e


def render_page(pdf_path: str, page_number: int, dpi: int = 200) -> Image.Image:
    """page_number is 1-based. dpi=200 is a reasonable balance for OCR
    quality vs. render time/memory on typical scanned-document PDFs."""
    pdf2image = _import_pdf2image()
    try:
        pages = pdf2image.convert_from_path(
            pdf_path, dpi=dpi, first_page=page_number, last_page=page_number
        )
    except Exception as e:  # noqa: BLE001
        raise PdfError(
            f"Could not render page {page_number} of '{pdf_path}' "
            f"(is poppler installed? see README.md): {e}"
        ) from e
    if not pages:
        raise PdfError(f"PDF page {page_number} did not render to an image.")
    return pages[0]


def render_all_thumbnails(pdf_path: str, dpi: int = 60) -> list[Image.Image]:
    """Low-res render of every page, for the multi-page picker dialog —
    kept cheap since a scanned ID batch is typically a handful of pages."""
    pdf2image = _import_pdf2image()
    try:
        return pdf2image.convert_from_path(pdf_path, dpi=dpi)
    except Exception as e:  # noqa: BLE001
        raise PdfError(
            f"Could not render thumbnails for '{pdf_path}' "
            f"(is poppler installed? see README.md): {e}"
        ) from e
