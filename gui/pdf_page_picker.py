"""
Page picker shown when a multi-page PDF is dropped into an upload box.

A scanned batch could have the relevant document on any page (e.g. the
passport photo page on page 2, not page 1) — this never guesses which page
is right, it always makes the user click the correct thumbnail.
"""

from __future__ import annotations

from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QGridLayout, QLabel, QMessageBox, QScrollArea, QVBoxLayout, QWidget,
)

from gui.pdf_utils import PdfError, render_all_thumbnails

_COLUMNS = 4
_THUMB_SIZE = (110, 140)


class _PageThumb(QLabel):
    clicked = Signal(int)

    def __init__(self, page_number: int, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.page_number = page_number
        self.setPixmap(pixmap)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("border: 2px solid #ccc; border-radius: 4px; padding: 2px;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.page_number)
        super().mousePressEvent(event)


class PdfPagePickerDialog(QDialog):
    def __init__(self, pdf_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select a page")
        self.resize(540, 440)
        self.selected_page: int | None = None
        self._load_error = False

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("This PDF has multiple pages — click the one to use:"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)
        scroll.setWidget(container)
        layout.addWidget(scroll)

        try:
            thumbnails = render_all_thumbnails(pdf_path)
        except PdfError as e:
            self._load_error = True
            QMessageBox.critical(self, "PDF error", str(e))
            return

        for i, pil_image in enumerate(thumbnails):
            qimage = ImageQt(pil_image)
            pixmap = QPixmap.fromImage(qimage).scaled(
                *_THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            cell_widget = QWidget()
            cell_layout = QVBoxLayout(cell_widget)
            thumb = _PageThumb(i + 1, pixmap)
            thumb.clicked.connect(self._on_page_clicked)
            cell_layout.addWidget(thumb, alignment=Qt.AlignCenter)
            page_label = QLabel(f"Page {i + 1}")
            page_label.setAlignment(Qt.AlignCenter)
            cell_layout.addWidget(page_label)
            grid.addWidget(cell_widget, i // _COLUMNS, i % _COLUMNS)

    def _on_page_clicked(self, page_number: int):
        self.selected_page = page_number
        self.accept()

    @staticmethod
    def pick_page(pdf_path: str, parent=None) -> int | None:
        """Returns the 1-based page number the user picked, or None if they
        cancelled (or the PDF couldn't be rendered at all)."""
        dlg = PdfPagePickerDialog(pdf_path, parent)
        if dlg._load_error:
            return None
        if dlg.exec() == QDialog.Accepted:
            return dlg.selected_page
        return None
