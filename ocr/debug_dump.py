"""
Debug instrumentation for the OCR pipeline: saves every cropped region to
disk and logs the raw OCR text per region (even when empty), so a bad
result can be diagnosed as "crop landed on the wrong part of the image" vs.
"crop was fine but OCR read nothing" without guessing.

Off by default (debug_dir=None everywhere) — the license_field_regions.py
crop boxes are placeholders pending calibration against real photos, so
this is meant to be turned on for exactly that calibration work, not left
running in normal use.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import cv2

logger = logging.getLogger("ocr.debug")


def new_debug_dir(base_dir: str | Path | None = None) -> str:
    """Creates (and returns the path to) a fresh timestamped debug folder,
    so repeated runs while tuning crop coordinates don't overwrite each
    other and can be compared side by side."""
    from db.storage import APP_DATA_DIR

    base = Path(base_dir) if base_dir else APP_DATA_DIR / "debug"
    debug_dir = base / datetime.now().strftime("%Y%m%d_%H%M%S")
    debug_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Debug output for this autofill run: %s", debug_dir)
    return str(debug_dir)


def save_crop(debug_dir: str | None, name: str, image) -> None:
    """Saves a cropped (or full deskewed) image to debug_dir/<name>.png.
    No-op if debug_dir is None (i.e. debug mode isn't on) or the image is
    empty (a zero-size crop, which is itself worth knowing about — that
    gets logged separately by the caller, not here)."""
    if not debug_dir or image is None or image.size == 0:
        return
    path = os.path.join(debug_dir, f"{name}.png")
    cv2.imwrite(path, image)


def log_ocr_result(label: str, raw_text: str, confidence: float, flagged: bool) -> None:
    """Logs every OCR attempt's raw text, even when empty — an empty read
    with a confidence of 0.0 usually means the crop landed on blank space
    or off the card; an empty read with reasonable confidence, or garbled
    text, more often means the crop is on the right area but the OCR
    language/orientation/DPI is off."""
    logger.info(
        "OCR region %-20s conf=%.2f flagged=%-5s text=%r",
        label, confidence, flagged, raw_text,
    )


def save_ocr_words(debug_dir: str | None, name: str, words) -> None:
    """Dumps every detected word's raw text/confidence/pixel box to
    debug_dir/<name>_words.json. No-op if debug_dir is None.

    2026-08-30: added for passport_ocr.py's label-anchored bio-field
    search (see that module's docstring) — log_ocr_result only records the
    *final* resolved text per field, which is enough to see THAT a field
    came back empty but not WHY (label not found at all vs. found but the
    value band came up empty vs. found the wrong line). This is real
    ground truth straight from the OCR engine's own word list, the same
    thing _find_label_line/_value_band_below actually operate on — sidesteps
    needing another guess-and-recalibrate round trip when a field misreads
    on a new photo."""
    if not debug_dir or not words:
        return
    import json

    path = os.path.join(debug_dir, f"{name}_words.json")
    payload = [{"text": w.text, "confidence": round(w.confidence, 3), "box": list(w.box)} for w in words]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
