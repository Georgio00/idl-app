"""
FlowLayout -- a QLayout that lays its children left-to-right and wraps to a
new line whenever the next child would run past the available width,
rather than letting them overflow past the window's edge.

Added 2026-09-26 as the real fix for the New IDL toolbar overflow bug:
splitting the toolbar into top_bar_left/top_bar_right (see
new_idl_form.py's docstring, "later the same day") fixed the PROPORTIONS
but not the underlying bug -- a plain QHBoxLayout never wraps, so on a
real screen narrower (or a window smaller) than the sum of every button's
width, the last button(s) still got visually cut off at the window's
right edge exactly as before, just moved to wherever the row happened to
run out of room. Georgio confirmed this by screenshotting his own machine
after pulling that fix: "Print Receipt" was still clipped.

A QHBoxLayout can't be told to wrap -- Qt has no built-in flowing layout,
this is a well-known gap generally solved with a small custom QLayout
subclass (the algorithm here is the standard one: lay out items along a
line, and whenever the next item wouldn't fit, start a new line one
line-height down). Using this instead of QHBoxLayout for the toolbar
groups means the toolbar always fits SOME window/screen width -- narrow
screens get more rows instead of clipped buttons -- rather than only
working correctly on whatever screen happened to be used for testing.
This is the general fix: it doesn't assume any particular screen size,
button count, or button label length.
"""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy, QStyle


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, h_spacing=-1, v_spacing=-1):
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self):
        item = self.takeAt(0)
        while item is not None:
            item = self.takeAt(0)

    def addItem(self, item):
        self._items.append(item)

    def horizontalSpacing(self):
        if self._h_spacing >= 0:
            return self._h_spacing
        return self._smart_spacing(QStyle.PM_LayoutHorizontalSpacing)

    def verticalSpacing(self):
        if self._v_spacing >= 0:
            return self._v_spacing
        return self._smart_spacing(QStyle.PM_LayoutVerticalSpacing)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        size += QSize(left + right, top + bottom)
        return size

    def _smart_spacing(self, pm):
        parent = self.parent()
        if parent is None:
            return -1
        if parent.isWidgetType():
            style = parent.style()
            return style.pixelMetric(pm, None, parent)
        return parent.spacing()

    def _do_layout(self, rect, test_only):
        left, top, right, bottom = self.getContentsMargins()
        effective_rect = rect.adjusted(left, top, -right, -bottom)
        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0

        for item in self._items:
            widget = item.widget()
            space_x = self.horizontalSpacing()
            if space_x == -1:
                space_x = widget.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Horizontal
                )
            space_y = self.verticalSpacing()
            if space_y == -1:
                space_y = widget.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Vertical
                )

            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective_rect.right() and line_height > 0:
                x = effective_rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y() + bottom
