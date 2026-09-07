"""
Calibration screen: load a photo of the real IDP page (once we have one),
pick a field from the dropdown, click-and-drag a box over where that field
should print, repeat for every field, then Save — writes the boxes back to
printing/layout_config.py's stored layout (as fractions of the image, so it
stays correct regardless of the final page's exact mm dimensions).

This lets positions be tuned without a code change, per the brief, since we
don't have exact page measurements yet.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from printing.layout_config import DEFAULT_DATA_PAGE_LAYOUT, load_layout, save_layout


class CalibrationCanvas(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.pixmap_orig: QPixmap | None = None
        self.boxes: dict[str, QRect] = {}  # field_key -> rect in widget coords
        self.active_field: str | None = None
        self._drag_start = None
        self._drag_current = None
        self.setMinimumSize(300, 400)
        self.setStyleSheet("background-color: #222;")

    def load_image(self, path: str):
        self.pixmap_orig = QPixmap(path)
        self.setPixmap(self.pixmap_orig.scaled(self.width(), self.height(), Qt.KeepAspectRatio))
        self.update()

    def set_boxes_from_fractions(self, fractions: dict[str, tuple[float, float, float, float]]):
        if not self.pixmap_orig:
            return
        pm = self.pixmap()
        w, h = pm.width(), pm.height()
        self.boxes = {
            key: QRect(int(x * w), int(y * h), int(bw * w), int(bh * h))
            for key, (x, y, bw, bh) in fractions.items()
        }
        self.update()

    def boxes_as_fractions(self) -> dict[str, tuple[float, float, float, float]]:
        pm = self.pixmap()
        if not pm or pm.width() == 0:
            return {}
        w, h = pm.width(), pm.height()
        return {
            key: (rect.x() / w, rect.y() / h, rect.width() / w, rect.height() / h)
            for key, rect in self.boxes.items()
        }

    def mousePressEvent(self, event):
        if self.active_field is None:
            return
        self._drag_start = event.position().toPoint()
        self._drag_current = self._drag_start

    def mouseMoveEvent(self, event):
        if self._drag_start is None:
            return
        self._drag_current = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_start is None or self.active_field is None:
            return
        rect = QRect(self._drag_start, event.position().toPoint()).normalized()
        if rect.width() > 3 and rect.height() > 3:
            self.boxes[self.active_field] = rect
        self._drag_start = None
        self._drag_current = None
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        for key, rect in self.boxes.items():
            color = QColor("#00c853") if key != self.active_field else QColor("#ffab00")
            painter.setPen(QPen(color, 2))
            painter.drawRect(rect)
            painter.drawText(rect.topLeft().x(), max(rect.topLeft().y() - 4, 10), key)
        if self._drag_start and self._drag_current:
            painter.setPen(QPen(QColor("#2979ff"), 2, Qt.DashLine))
            painter.drawRect(QRect(self._drag_start, self._drag_current).normalized())


class CalibrationScreen(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IDP Print Layout Calibration")
        self.resize(700, 900)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        top_bar = QHBoxLayout()
        self.load_photo_btn = QPushButton("Load Page Photo...")
        self.load_photo_btn.clicked.connect(self.load_photo)
        self.field_combo = QComboBox()
        self.field_combo.addItems(sorted(DEFAULT_DATA_PAGE_LAYOUT.keys()))
        self.field_combo.currentTextChanged.connect(self.on_field_selected)
        self.save_btn = QPushButton("Save Layout")
        self.save_btn.clicked.connect(self.save)
        top_bar.addWidget(self.load_photo_btn)
        top_bar.addWidget(QLabel("Field:"))
        top_bar.addWidget(self.field_combo)
        top_bar.addStretch()
        top_bar.addWidget(self.save_btn)
        outer.addLayout(top_bar)

        outer.addWidget(QLabel(
            "1. Load a photo of the real IDP data page. "
            "2. Pick a field. 3. Click-drag a box where it should print. Repeat, then Save."
        ))

        self.canvas = CalibrationCanvas()
        outer.addWidget(self.canvas)

        self.canvas.active_field = self.field_combo.currentText()

        layout = load_layout()
        self.canvas.set_boxes_from_fractions({k: tuple(v) for k, v in layout["data_page"].items()})

    def on_field_selected(self, key: str):
        self.canvas.active_field = key
        self.canvas.update()

    def load_photo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select a photo of the IDP data page",
                                               filter="Images (*.jpg *.jpeg *.png)")
        if not path:
            return
        self.canvas.load_image(path)
        layout = load_layout()
        self.canvas.set_boxes_from_fractions({k: tuple(v) for k, v in layout["data_page"].items()})

    def save(self):
        if not self.canvas.pixmap_orig:
            QMessageBox.warning(self, "No photo loaded", "Load a page photo first so boxes can be measured against it.")
            return
        layout = load_layout()
        layout["data_page"] = {k: list(v) for k, v in self.canvas.boxes_as_fractions().items()}
        save_layout(layout)
        QMessageBox.information(self, "Saved", "Print layout saved.")


def main():
    app = QApplication(sys.argv)
    window = CalibrationScreen()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
