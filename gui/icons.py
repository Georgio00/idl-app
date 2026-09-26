"""
Small, hand-drawn toolbar icons for gui/new_idl_form.py's buttons.

2026-09-26: Georgio shared close-up photos of LAA's own screen and asked
to "add icons like the ones in the image i gave you". LAA's toolbar
color-codes its buttons by the record/output they act on -- a left group
of generic action icons (a green plus-circle for "New IDL", grey/blue
icons for Clone, Previous/Next, Edit, Delete, Search) and a right group
of colored Print/View pairs, one column per output: blue for the
licence/print-preview family (Print Licence/View Licence), green for the
receipt family (Print Receipt/View Receipt), red for the not-yet-built
form family (Print Form/View Form). Every Print button in that photo is a
printer pictogram in its column's color; every View button is an eye
pictogram in that same color.

This module reproduces that same color language and the same widely-used,
generic pictograms (a magnifying glass for search, arrows for previous/
next, a plus-circle for new, an eye for view, a printer for print, a gear
for settings, a person for user/staff accounts) -- not a copy of LAA's own
specific icon artwork, which this app has no license to redistribute, but
freshly hand-drawn shapes using the same unprotectable pictogram
vocabulary, colored the same way, so this app's own toolbar reads the
same way at a glance.

Icons are drawn in code with QPainter onto a transparent QPixmap, rather
than shipped as .svg/.png files under assets/. Reasons: it needs no entry
in packaging/idl_app.spec's `datas` and can't silently go missing from a
build the way a forgotten asset file could (see that spec's own docstring
history of exactly that failure mode for ocr/reference_templates); and
recoloring is just passing a different `color` argument, matching LAA's
own "same pictogram, different color per group" pattern exactly, with no
need for a whole extra file per color variant.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

# Reference photo's own color language (see module docstring) -- reused
# here by name so gui/new_idl_form.py's button-icon wiring reads as
# "this button belongs to the blue/green/neutral family" rather than
# repeating raw hex codes at each call site.
BLUE = "#1f6fd8"       # Licence / print-preview family (Print/View Licence)
GREEN = "#2e9e44"      # Receipt family (Print/View Receipt)
NEUTRAL = "#5a6472"    # Generic actions with no colored counterpart in
                       # the reference photo (Save, Printer Settings,
                       # Manage Staff Accounts)

_ICON_SIZE = 22


def _new_pixmap() -> QPixmap:
    pixmap = QPixmap(_ICON_SIZE, _ICON_SIZE)
    pixmap.fill(Qt.transparent)
    return pixmap


def _draw_search(painter: QPainter, color: QColor) -> None:
    painter.setPen(QPen(color, 2.2))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QRectF(3, 3, 11, 11))
    painter.drawLine(QPointF(13, 13), QPointF(19, 19))


def _draw_arrow(painter: QPainter, color: QColor, pointing_right: bool) -> None:
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    if pointing_right:
        points = [QPointF(6, 4), QPointF(18, 11), QPointF(6, 18)]
    else:
        points = [QPointF(16, 4), QPointF(4, 11), QPointF(16, 18)]
    path = QPainterPath()
    path.moveTo(points[0])
    for point in points[1:]:
        path.lineTo(point)
    path.closeSubpath()
    painter.drawPath(path)


def _draw_plus_circle(painter: QPainter, color: QColor) -> None:
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QRectF(2, 2, 18, 18))
    pen = QPen(Qt.white, 2.4)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(11, 6), QPointF(11, 16))
    painter.drawLine(QPointF(6, 11), QPointF(16, 11))


def _draw_save(painter: QPainter, color: QColor) -> None:
    pen = QPen(color, 2.0)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(QRectF(4, 3, 14, 16), 2, 2)
    painter.drawRect(QRectF(7, 3, 8, 6))
    painter.drawRect(QRectF(7, 12, 8, 7))


def _draw_gear(painter: QPainter, color: QColor) -> None:
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    center = QPointF(11, 11)
    outer_r, tooth_r = 8.5, 10.2
    teeth = 8
    path = QPainterPath()
    for i in range(teeth * 2):
        angle = math.pi * i / teeth
        r = tooth_r if i % 2 == 0 else outer_r
        point = QPointF(center.x() + r * math.cos(angle), center.y() + r * math.sin(angle))
        if i == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    painter.drawPath(path)
    painter.setBrush(Qt.white)
    painter.drawEllipse(center, 3.0, 3.0)


def _draw_person(painter: QPainter, color: QColor) -> None:
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QRectF(7, 3, 8, 8))
    path = QPainterPath()
    path.moveTo(4, 19)
    path.cubicTo(4, 13, 7, 11, 11, 11)
    path.cubicTo(15, 11, 18, 13, 18, 19)
    path.closeSubpath()
    painter.drawPath(path)


def _draw_eye(painter: QPainter, color: QColor) -> None:
    painter.setPen(QPen(color, 2.0))
    painter.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(2, 11)
    path.quadTo(11, 1, 20, 11)
    path.quadTo(11, 21, 2, 11)
    painter.drawPath(path)
    painter.setBrush(color)
    painter.drawEllipse(QPointF(11, 11), 3.2, 3.2)


def _draw_printer(painter: QPainter, color: QColor) -> None:
    pen = QPen(color, 2.0)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(QRectF(4, 8, 14, 8))
    painter.drawRect(QRectF(6.5, 3, 9, 6))
    painter.drawRect(QRectF(6.5, 15, 9, 5))


_DRAW_FUNCS = {
    "search": _draw_search,
    "prev": lambda p, c: _draw_arrow(p, c, pointing_right=False),
    "next": lambda p, c: _draw_arrow(p, c, pointing_right=True),
    "new": _draw_plus_circle,
    "save": _draw_save,
    "settings": _draw_gear,
    "user": _draw_person,
    "eye": _draw_eye,
    "printer": _draw_printer,
}


def make_icon(kind: str, color: str) -> QIcon:
    """Returns a QIcon for one of the pictograms above, tinted `color`
    (any Qt-recognized color name or "#rrggbb" string -- see BLUE/GREEN/
    NEUTRAL above). `kind` must be one of _DRAW_FUNCS' keys ("search",
    "prev", "next", "new", "save", "settings", "user", "eye", "printer").
    See this module's docstring for why these are drawn in code rather
    than loaded from files.
    """
    if kind not in _DRAW_FUNCS:
        raise ValueError(f"Unknown icon kind: {kind!r} (known: {sorted(_DRAW_FUNCS)})")
    pixmap = _new_pixmap()
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    try:
        _DRAW_FUNCS[kind](painter, QColor(color))
    finally:
        painter.end()
    return QIcon(pixmap)
