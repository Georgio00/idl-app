"""
EasyOCR-backed OCR client — an alternate engine to ocr_client.py's
Tesseract backend, used specifically for the passport (see
passport_ocr.py). Returns the exact same OcrResult/OcrWord/OcrError
shapes as ocr_client.py, so nothing downstream of the OCR call needs to
know or care which engine actually produced them.

Why a second engine, and why only for the passport: real-world testing
(2026-08-23, against an actual sample passport bio-data page) found
Tesseract cannot read text over the passport's anti-counterfeiting
guilloche security pattern at all — the pattern's contrast is close
enough to the ink that simple thresholding (Otsu, adaptive, blur+Otsu, at
several blur radii) can't separate them, and Tesseract came back either
empty or garbage on every affected field (the MRZ's name line, father's
name, place of birth). EasyOCR — a deep-learning engine trained on messy
real-world photos rather than clean scans — read the exact same crops
correctly and with high confidence (surname/given-names came back exact
and checksum-valid; father's name and place of birth came back exact at
0.97 confidence).

This does NOT replace ocr_client.py for the license: on the license's
much smaller field crops (the source license photo's card region was
only ~750x460px to begin with in real testing — already below what the
current deskew target upsamples to, so there's no extra real detail to
recover), EasyOCR did not outperform Tesseract in the same testing
session — worse, in fact, on a couple of fields. license_ocr.py continues
using ocr_client.py/Tesseract unchanged.

Trade-off: EasyOCR is dramatically slower on CPU than Tesseract — roughly
1-12 seconds per crop in testing here (Tesseract: a fraction of a
second). Total passport OCR (MRZ band + 2 bio-data crops) went from
near-instant to roughly 15-25 seconds. This already runs off the UI
thread (see gui/new_idl_form.py's AutofillWorker), so it won't freeze the
window, but the progress dialog will be up noticeably longer than before
— worth knowing so it doesn't look hung.

Setup required beyond ocr_client.py's Tesseract install: `pip install
easyocr` (pulls in PyTorch as a dependency — a large install, several
hundred MB). No separate language-pack install step like Tesseract's
Arabic pack: model weights download automatically on first use (to
~/.EasyOCR by default, or %USERPROFILE%\\.EasyOCR on Windows) and are
cached for offline reuse after that — the first autofill run on a fresh
machine will be slower and needs network access once; every run after is
fully offline, same as Tesseract.
"""

from __future__ import annotations

from ocr.ocr_client import OcrError, OcrResult, OcrWord

# One EasyOCR Reader per language combination actually requested, created
# lazily on first use and reused for the lifetime of the process — each
# Reader construction loads real model weights and costs real time
# (several seconds), so this must not happen per-call.
_readers: dict[tuple[str, ...], object] = {}


def _get_reader(language_hints: list[str] | None):
    langs = tuple(sorted(set(language_hints or ["ar", "en"])))
    reader = _readers.get(langs)
    if reader is not None:
        return reader

    try:
        import easyocr
    except ImportError as e:
        raise OcrError("easyocr is not installed. Run: pip install easyocr") from e

    try:
        reader = easyocr.Reader(list(langs), gpu=False, verbose=False)
    except Exception as e:  # noqa: BLE001 - any init failure (e.g. model download failed, no network on first run) surfaces as OcrError, not a crash
        raise OcrError(f"Failed to initialize EasyOCR reader for languages {langs}: {e}") from e

    _readers[langs] = reader
    return reader


def ocr_image_array(image, language_hints: list[str] | None = None) -> OcrResult:
    """Runs EasyOCR on an in-memory image (BGR, as returned by
    cv2.imread/crop_region — EasyOCR accepts BGR numpy arrays directly,
    same convention as ocr_client.py's Tesseract path)."""
    reader = _get_reader(language_hints)
    try:
        detections = reader.readtext(image)
    except Exception as e:  # noqa: BLE001 - surface any read failure as OcrError, not a crash
        raise OcrError(f"EasyOCR read failed: {e}") from e

    words: list[OcrWord] = []
    text_parts: list[str] = []
    for box, text, conf in detections:
        text = text.strip()
        if not text:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        words.append(OcrWord(
            text=text,
            confidence=max(0.0, min(1.0, float(conf))),
            box=(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
        ))
        text_parts.append(text)

    return OcrResult(full_text="\n".join(text_parts), words=words)
