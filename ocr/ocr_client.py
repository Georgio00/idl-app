"""
Thin wrapper around Google Cloud Vision's OCR (document text detection).

This is the ONLY file in the codebase that should import
`google.cloud.vision`. Everything else (passport_ocr.py, license_ocr.py)
calls the functions below, which return plain-Python types (OcrWord /
OcrResult) — the same shapes this module has returned through every OCR
engine it's wrapped. That's the point: the OCR engine is swappable by only
touching this file, and it's why switching didn't require changing
passport_ocr.py, license_ocr.py, or pipeline.py at all.

2026-08-24: switched back to Google Cloud Vision, reversing the earlier
move to Tesseract. Tesseract was offline/free/private, but real-world use
kept surfacing accuracy and engine-specific problems that ate several
debugging sessions: the license's "13b" blood-type field alone needed five
separate rounds chasing its printed label bleeding into the read (crop
recalibration, then a generous-crop-plus-label-strip rework, then a
character-whitelist config-string bug in that rework that crashed autofill
outright on a real Windows run — "Unexpected error during autofill: No
closing quotation", a Windows-specific limitation in how pytesseract
parses its `config` string that no amount of quoting from this side could
work around). Separately, the passport needed a THIRD engine (see the
now-unused ocr/easyocr_client.py) purely because Tesseract could not read
text over the passport's anti-counterfeiting security pattern at all.
Vision's document-text-detection model does its own layout analysis far
more robustly than Tesseract's LSTM engine, which is what most of the
above ultimately came down to — no per-field pixel-perfect crop tuning,
no character-whitelist/page-segmentation-mode workarounds, and (expected
given Vision's general robustness, not yet re-verified against a real
passport photo) likely no need for the easyocr passport workaround either
— see passport_ocr.py's module docstring for that change.

Trade-off, the reason Tesseract was chosen over Vision in the first place:
this now requires a live internet connection, a Google Cloud project with
the Vision API enabled and billing set up, and every scanned ID photo
(passport bio page, driving license front/back) is sent to Google's
servers for processing. See README.md's Setup section for exactly what
that requires and what it costs.

char_whitelist, psm_fallback, and psm are still accepted by every function
below, purely for interface compatibility with license_ocr.py's existing
calls (see license_ocr.INLINE_LABEL_FIELDS) — Vision has no equivalent of
Tesseract's character whitelist or page-segmentation-mode concepts, so all
three are silently ignored here. license_ocr.py's generous-crop +
_strip_inline_label approach (see that module's docstring) still runs
unchanged and is still useful: Vision's crop still contains the printed
field-number label alongside the value, and _strip_inline_label finds and
discards it the same way regardless of which engine produced the words.

Both Arabic and English are always requested (language_hints defaults to
["ar", "en"], same as before) — Vision uses BCP-47 language codes
directly ("ar", "en"), unlike Tesseract's 3-letter traineddata names, so
the translation table this module used to need is gone. The unwanted
Arabic-script output is still stripped post-recognition (see _strip_arabic
below) for the same reason as before: most fields only ever surface Latin
content, with real Arabic content kept only for the fields
license_ocr._KEEP_ARABIC_FIELDS and passport_ocr's bio fields need.

2026-09-06: added _dedupe_overlapping_words, applied to every word list
this module returns. Found via a real photo's per-field word dump
(Younes Hamzeh — license field "8", see license_ocr.py's save_ocr_words
instrumentation): Vision returned BOTH "8" (confidence 0.986 — the real
pre-printed field-number glyph) and "00" (confidence 0.554) for two
bounding boxes overlapping at ~85% IoU — the same glyph on the card, read
two conflicting ways by Vision's own internal layout analysis, not two
real characters. Nothing downstream had any way to tell that apart from a
real second character sitting almost on top of the first, so the low-
confidence duplicate survived as noise appended to whatever field it
landed in. Deduplicating by bounding-box overlap (keeping only the
higher-confidence word of any pair that overlaps heavily) is engine-level,
generic behavior — applied here rather than in license_ocr.py or
passport_ocr.py specifically, since either module's word lists could hit
the same artifact on a different photo, and there's no reason a caller
should have to know to defend against it itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class OcrError(RuntimeError):
    """Raised when the OCR call fails: the google-cloud-vision package
    isn't installed, credentials are missing/invalid, there's no network,
    or the Vision API itself returns an error for the request."""


@dataclass
class OcrWord:
    text: str
    confidence: float  # 0.0-1.0
    # Bounding box as (x0, y0, x1, y1) in pixel coordinates of the image
    # that was submitted for OCR.
    box: tuple[int, int, int, int]


@dataclass
class OcrResult:
    full_text: str
    words: list[OcrWord]

    def average_confidence(self) -> float:
        if not self.words:
            return 0.0
        return sum(w.confidence for w in self.words) / len(self.words)


_DEFAULT_LANGS = ["ar", "en"]

_client = None


def _get_client():
    """Lazily constructs and caches the Vision API client for the life of
    the process. Construction does credential discovery (via the standard
    GOOGLE_APPLICATION_CREDENTIALS environment variable pointing at a
    service-account JSON key — Google's "Application Default Credentials"
    mechanism, see README.md's Setup section), which is wasteful to repeat
    per call. Stays None on failure rather than caching a broken state, so
    a credentials problem fixed mid-session (e.g. the env var set after
    the app was already running) is picked up on the next OCR call instead
    of requiring a restart."""
    global _client
    if _client is not None:
        return _client

    try:
        from google.cloud import vision
    except ImportError as e:
        raise OcrError(
            "google-cloud-vision is not installed. Run: pip install google-cloud-vision"
        ) from e

    try:
        client = vision.ImageAnnotatorClient()
    except Exception as e:  # noqa: BLE001 - credential/auth failures surface as varied
        # google.auth exception types depending on what's wrong (missing env var,
        # malformed key file, expired/revoked key) — all of them mean the same thing
        # to a caller here: OCR can't run until credentials are fixed.
        raise OcrError(
            "Could not create a Google Cloud Vision client — check that "
            "GOOGLE_APPLICATION_CREDENTIALS points at a valid service-account JSON "
            f"key file (see README.md's Setup section). Underlying error: {e}"
        ) from e

    _client = client
    return _client


# Vision's model reads small text noticeably better than Tesseract's did,
# but upscaling small crops was never shown to hurt it either — this is
# carried over unchanged from this module's Tesseract version rather than
# re-derived, since it's a generically reasonable preprocessing step. Not
# re-verified as necessary for Vision specifically; worth revisiting (with
# real before/after crops) if it turns out to make no measurable
# difference here.
_MIN_OCR_DIMENSION_PX = 120


def _preprocess_for_ocr(image):
    """Upscales small crops (see _MIN_OCR_DIMENSION_PX) and mildly
    normalizes contrast — see module docstring for why this is kept
    unchanged from the Tesseract version rather than re-tuned for Vision."""
    import cv2

    h, w = image.shape[:2]
    shorter_side = min(h, w)
    if shorter_side and shorter_side < _MIN_OCR_DIMENSION_PX:
        scale = _MIN_OCR_DIMENSION_PX / shorter_side
        image = cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # CLAHE (adaptive local contrast) rather than a single global contrast
    # stretch — handles a crop with uneven lighting (e.g. part of it in a
    # shadow) better than a single scale-the-whole-image adjustment would.
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)


def _encode_for_vision(image) -> bytes:
    """The Vision API takes raw image bytes, not a numpy array. PNG rather
    than JPEG — these are already-small field crops, so there's no
    meaningful file-size pressure, and PNG avoids compression artifacts
    that could hurt recognition on fine text."""
    import cv2

    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise OcrError("Failed to encode image for the Vision API")
    return buf.tobytes()


def _call_vision(image_bytes: bytes, language_hints: list[str]):
    from google.cloud import vision

    client = _get_client()
    vision_image = vision.Image(content=image_bytes)
    image_context = vision.ImageContext(language_hints=language_hints)
    try:
        response = client.document_text_detection(image=vision_image, image_context=image_context)
    except Exception as e:  # noqa: BLE001 - deliberately broad: network errors, auth
        # errors that only surface on the actual call (not client construction),
        # quota/rate-limit errors, and anything else the google-cloud SDK can raise
        # must all become OcrError rather than crash the whole autofill run. This
        # matters concretely here: license_ocr._ocr_crop and
        # passport_ocr._ocr_bio_field only catch OcrError and turn a failure into one
        # flagged-empty field — anything else propagates and aborts every remaining
        # field, which is exactly how a config-string bug in the old Tesseract path
        # once took down an entire autofill run instead of just the field that hit it.
        raise OcrError(f"Vision API call failed: {e}") from e

    if response.error.message:
        raise OcrError(f"Vision API error: {response.error.message}")
    return response


def _words_and_text_from_response(response) -> tuple[list[OcrWord], str]:
    """Flattens Vision's page/block/paragraph/word/symbol response
    structure into a flat word list plus the full recognized text.

    Unlike Tesseract's image_to_data (which returns one row per word and
    left this module to regroup rows into lines by block/paragraph/line
    number — see git history's _words_and_lines_from_data), Vision's
    response.full_text_annotation.text is already the correctly
    reconstructed full text, so no manual line-regrouping is needed here."""
    annotation = response.full_text_annotation
    if not annotation or not annotation.text:
        return [], ""

    words: list[OcrWord] = []
    for page in annotation.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                for word in paragraph.words:
                    text = "".join(symbol.text for symbol in word.symbols)
                    if not text:
                        continue
                    vertices = word.bounding_box.vertices
                    xs = [v.x for v in vertices]
                    ys = [v.y for v in vertices]
                    # Vision's word.confidence is already 0.0-1.0, unlike
                    # Tesseract's 0-100 scale this module used to rescale.
                    confidence = max(0.0, min(1.0, word.confidence))
                    words.append(OcrWord(text=text, confidence=confidence,
                                          box=(min(xs), min(ys), max(xs), max(ys))))

    return words, annotation.text


# Two word boxes at or above this IoU (intersection over union) are treated
# as the same physical glyph read twice rather than two adjacent real
# characters — see module docstring's 2026-09-06 entry. Real neighboring
# words/characters on a printed card or page sit side by side with little
# to no overlap; 0.5 is comfortably below the ~0.85 IoU measured on the
# real duplicate this was built from, while still well above what two
# merely-close (not overlapping) real words would ever produce.
_OVERLAP_DEDUPE_IOU_THRESHOLD = 0.5


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    iw = max(0, min(ax1, bx1) - max(ax0, bx0))
    ih = max(0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0, ax1 - ax0) * max(0, ay1 - ay0)
    area_b = max(0, bx1 - bx0) * max(0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def _dedupe_overlapping_words(words: list[OcrWord]) -> list[OcrWord]:
    """Drops a word that's really just a duplicate detection of another
    word occupying almost the same pixel box, keeping only the higher-
    confidence one of any such pair — see module docstring's 2026-09-06
    entry for the real photo this was built from. Processes words highest-
    confidence-first so the winner of any overlapping cluster is always
    the most-trusted read, regardless of which order Vision happened to
    list them in."""
    kept: list[OcrWord] = []
    for w in sorted(words, key=lambda w: -w.confidence):
        if any(_iou(w.box, k.box) >= _OVERLAP_DEDUPE_IOU_THRESHOLD for k in kept):
            continue
        kept.append(w)
    return kept


# Arabic-script Unicode ranges: Arabic (U+0600–U+06FF), Arabic Supplement
# (U+0750–U+077F), Arabic Presentation Forms-A (U+FB50–U+FDFF) and -B
# (U+FE70–U+FEFF). Both languages are requested on every Vision call (see
# module docstring), so real Arabic-script characters can end up in a read
# even though the app only ever surfaces the English/Latin content.
# Stripped here, after recognition, rather than at recognition time.
_ARABIC_CHAR_RE = re.compile(
    "[\U00000600-\U000006FF\U00000750-\U0000077F\U0000FB50-\U0000FDFF\U0000FE70-\U0000FEFF]"
)
_HORIZONTAL_WHITESPACE_RUN_RE = re.compile(r"[ \t]+")


def _strip_arabic(text: str) -> str:
    """Removes Arabic-script characters and collapses the horizontal
    whitespace gaps they leave behind (multiple spaces, or a leading/
    trailing space where an Arabic word used to sit next to the English
    text). Leaves line breaks alone — callers like
    passport_ocr._extract_mrz_lines depend on one physical line staying
    one line of full_text."""
    stripped = _ARABIC_CHAR_RE.sub("", text)
    lines = [_HORIZONTAL_WHITESPACE_RUN_RE.sub(" ", line).strip() for line in stripped.split("\n")]
    return "\n".join(lines)


def _run_vision(image, language_hints: list[str] | None, keep_arabic: bool = False) -> OcrResult:
    image = _preprocess_for_ocr(image)
    image_bytes = _encode_for_vision(image)
    langs = language_hints or _DEFAULT_LANGS
    response = _call_vision(image_bytes, langs)
    words, full_text = _words_and_text_from_response(response)
    words = _dedupe_overlapping_words(words)

    if not keep_arabic:
        full_text = _strip_arabic(full_text)
        stripped_words: list[OcrWord] = []
        for w in words:
            text = _strip_arabic(w.text)
            if text:
                stripped_words.append(OcrWord(text=text, confidence=w.confidence, box=w.box))
        words = stripped_words

    return OcrResult(full_text=full_text, words=words)


def ocr_image_bytes(image_bytes: bytes, language_hints: list[str] | None = None,
                     char_whitelist: str | None = None, psm_fallback: bool = True,
                     keep_arabic: bool = False, psm: int | None = None) -> OcrResult:
    import cv2
    import numpy as np

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise OcrError("Failed to decode image bytes for OCR")
    return _run_vision(image, language_hints, keep_arabic)


def ocr_image_path(path: str, language_hints: list[str] | None = None,
                    char_whitelist: str | None = None, psm_fallback: bool = True,
                    keep_arabic: bool = False, psm: int | None = None) -> OcrResult:
    import cv2

    image = cv2.imread(path)
    if image is None:
        raise OcrError(f"Failed to read image for OCR: {path}")
    return _run_vision(image, language_hints, keep_arabic)


def ocr_image_array(image, language_hints: list[str] | None = None,
                     char_whitelist: str | None = None, psm_fallback: bool = True,
                     keep_arabic: bool = False, psm: int | None = None) -> OcrResult:
    """Runs OCR on an in-memory image, e.g. a numpy array from OpenCV
    (BGR, as returned by cv2.imread / cv2.warpPerspective crops).

    char_whitelist, psm_fallback, and psm are accepted but ignored — see
    module docstring. They're kept as parameters purely so
    license_ocr.py's existing calls (built for the Tesseract backend, see
    license_ocr.INLINE_LABEL_FIELDS) don't need to change; Vision has no
    character-whitelist or page-segmentation-mode concept to apply them
    to.

    keep_arabic (default False): skip the post-recognition Arabic-script
    stripping (see module docstring / _strip_arabic) for a caller whose
    field is itself Arabic-only content rather than a Latin field Arabic
    might bleed into. The license's place-of-residence field (front "8")
    is printed only in Arabic — with stripping always on, that field came
    back completely blank on every read, not just inaccurate, because
    _strip_arabic deleted the entire (correct) OCR result. Every other
    caller leaves this False: they still want Arabic *recognized* during
    OCR (see module docstring) but discarded from the final text, since
    the app only ever surfaces Latin-script content elsewhere."""
    return _run_vision(image, language_hints, keep_arabic)
