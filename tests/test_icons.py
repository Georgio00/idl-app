"""
Regression tests for gui/icons.py -- added 2026-09-26 ("add icons like
the ones in the image i gave you", after Georgio's close-up photos of
LAA's own screen). These don't try to pixel-match LAA's own artwork (this
app has no license to that); they check the things that would actually
break the feature: every documented icon kind renders as a real,
non-empty, non-blank icon, an unknown kind fails loudly instead of
silently returning something blank, and two different colors of the same
kind actually produce different pixels (proving `color` is really wired
into the drawing, not just accepted and ignored).

Run headless via QT_QPA_PLATFORM=offscreen, same as every other gui/ test.
"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from gui.icons import BLUE, GREEN, NEUTRAL, _DRAW_FUNCS, make_icon


def _pixel_data(icon: QIcon) -> bytes:
    pixmap = icon.pixmap(22, 22)
    image = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    ptr = image.constBits()
    return bytes(ptr)


class MakeIconTest(unittest.TestCase):
    def test_every_documented_kind_produces_a_non_null_icon(self):
        for kind in _DRAW_FUNCS:
            icon = make_icon(kind, BLUE)
            self.assertFalse(icon.isNull(), kind)

    def test_every_documented_kind_actually_paints_something(self):
        # A bug that left a draw function doing nothing (e.g. painter.end()
        # called before drawing, or a typo'd early return) would still
        # produce a non-null QIcon -- it'd just be fully transparent.
        # Check real, non-transparent pixels exist.
        for kind in _DRAW_FUNCS:
            data = _pixel_data(make_icon(kind, BLUE))
            alpha_bytes = data[3::4]
            self.assertTrue(any(a > 0 for a in alpha_bytes), f"{kind} painted nothing")

    def test_unknown_kind_raises_rather_than_returning_a_blank_icon(self):
        with self.assertRaises(ValueError):
            make_icon("not-a-real-kind", BLUE)

    def test_different_colors_produce_different_pixels(self):
        blue_icon = make_icon("printer", BLUE)
        green_icon = make_icon("printer", GREEN)
        self.assertNotEqual(_pixel_data(blue_icon), _pixel_data(green_icon))

    def test_neutral_color_constant_is_a_valid_color_string(self):
        # Guards NEUTRAL/BLUE/GREEN staying valid QColor-parseable strings
        # (a typo'd hex code would otherwise only surface once a button
        # using it happened to be constructed).
        for color in (BLUE, GREEN, NEUTRAL):
            icon = make_icon("eye", color)
            self.assertFalse(icon.isNull(), color)


if __name__ == "__main__":
    unittest.main()
