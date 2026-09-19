"""
A labeled, square drag-and-drop image upload widget used for the three ID
photo slots (Passport / License Front / License Back) on the "New IDL" form.

Each box is unambiguous about what goes in it (unlike the old single
"Autofill from ID Photos..." button that opened one multi-file picker with
no indication of which file was which) — clicking or dropping onto the
Passport box can only ever set the passport image, etc.

Also accepts PDFs (scanned documents, not just photos): a PDF page gets
rendered to a temp PNG (see pdf_utils.py) which becomes `image_path` —
everything downstream (the OCR pipeline, the thumbnail preview) only ever
sees that rendered image and has no idea the source was a PDF.

2026-09-01: added an explicit "Replace" button next to "Remove" (previously
the only way to swap a photo was Remove, then click the now-empty square
again to re-browse) and gave the Replace/Remove row its own fixed minimum
height so it can't get visually squeezed into overlapping the photo above
it on a short window — see ImageUploadBox.__init__ and
new_idl_form.py's matching QScrollArea fix for the ID Photos panel, which
addresses the actual cause of the squeeze rather than just this symptom.

2026-09-19: clicking an already-filled square now opens a full-size
preview (gui/image_preview_dialog.py) instead of immediately re-opening
the file browser — Georgio's request, so a staff member can actually
compare the New IDL form's autofilled field values against the source
photo/scan at a readable size, rather than judging OCR accuracy off a
~110px thumbnail. Browsing for a new file is still one click away via the
Replace button, which keeps calling self.browse() directly and is
unaffected by this change; the square's click-to-browse behavior is also
unchanged for as long as no image is set yet (there's nothing to preview).
"""

from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from db.storage import APP_DATA_DIR
from gui.image_preview_dialog import ImagePreviewDialog
from gui.pdf_page_picker import PdfPagePickerDialog
from gui.pdf_utils import PdfError, get_page_count, render_page

IMAGE_FILTER = "Images and PDFs (*.jpg *.jpeg *.png *.pdf)"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".pdf")
PDF_RENDER_TMP_DIR = APP_DATA_DIR / "pdf_render_tmp"

_EMPTY_STYLE = """
    QLabel {
        border: 2px dashed #9aa5b1;
        border-radius: 8px;
        background-color: #f8f9fa;
        color: #6c757d;
    }
"""
_FILLED_STYLE = """
    QLabel {
        border: 2px solid #1a5fb4;
        border-radius: 8px;
        background-color: #ffffff;
    }
"""
_DRAG_HOVER_STYLE = """
    QLabel {
        border: 2px dashed #1a5fb4;
        border-radius: 8px;
        background-color: #e7f0fd;
        color: #1a5fb4;
    }
"""


class _DropSquare(QLabel):
    """The clickable/droppable square itself — just the image area, no
    title or remove button (those live in the wrapping ImageUploadBox)."""

    file_chosen = Signal(str)
    clicked = Signal()

    def __init__(self, size: int = 150, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setWordWrap(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(_EMPTY_STYLE)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self._first_valid_path(event.mimeData().urls()):
            event.acceptProposedAction()
            self.setStyleSheet(_DRAG_HOVER_STYLE)

    def dragLeaveEvent(self, event):
        self.setStyleSheet(_FILLED_STYLE if self.pixmap() else _EMPTY_STYLE)

    def dropEvent(self, event):
        path = self._first_valid_path(event.mimeData().urls())
        self.setStyleSheet(_FILLED_STYLE if self.pixmap() else _EMPTY_STYLE)
        if path:
            self.file_chosen.emit(path)
            event.acceptProposedAction()

    @staticmethod
    def _first_valid_path(urls) -> str | None:
        for url in urls:
            path = url.toLocalFile()
            if path.lower().endswith(IMAGE_EXTENSIONS):
                return path
        return None


class ImageUploadBox(QWidget):
    """Title + square upload area + Replace/Remove buttons, for one of the
    three ID photo slots. `image_path` is None until a file is chosen;
    `changed` fires whenever it's set or cleared, so the parent form can
    enable/disable the Autofill button once all three boxes are filled.

    Both buttons only appear once a photo is set (see _set_placeholder):
    clicking the empty square itself already opens the file browser
    (self.browse, same as Replace), so there's nothing to replace or
    remove yet. Replace re-opens that same browser rather than requiring
    Remove-then-click-square-again — a 2026-09-01 addition alongside a
    layout fix for the Remove-button row (see __init__)."""

    changed = Signal()

    def __init__(self, title: str, dialog_caption: str, square_size: int = 150, parent=None):
        super().__init__(parent)
        self.title = title
        self.dialog_caption = dialog_caption
        self.image_path: str | None = None
        # Set only when image_path points at a PNG we rendered from a PDF
        # ourselves (never the user's own file) — safe to delete on replace/clear.
        self._temp_render_path: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # square_size defaults to the original 150px but new_idl_form.py
        # passes a smaller value (2026-09-01) for the three ID-photo boxes
        # specifically -- Georgio wants to see all three at once without
        # having to scroll the ID Photos panel, and three 150px boxes plus
        # their title/Replace/Remove rows don't all fit in that panel's
        # typical visible height. Configurable rather than just shrinking
        # _DropSquare's own default so any other future caller of this
        # widget can still get full-size thumbnails.
        self.square = _DropSquare(size=square_size)
        self.square.clicked.connect(self._on_square_clicked)
        self.square.file_chosen.connect(self.set_image)
        layout.addWidget(self.square, alignment=Qt.AlignCenter)

        # Replace/Remove sit in their own fixed-height row *below* the
        # square, never on top of it — 2026-09-01: on a window shorter
        # than the three stacked boxes' natural height, the old version of
        # this row (no minimum height of its own) could get squeezed down
        # by its QVBoxLayout almost to nothing, which visually read as the
        # "Remove" text sitting right on top of the photo's bottom edge
        # instead of clearly below it. Giving the row an explicit minimum
        # height means it always keeps its own space; the actual fix for
        # the squeeze itself is wrapping the three boxes in a QScrollArea
        # (see new_idl_form.py) so the window running short on height
        # scrolls instead of compressing every box's rows toward zero.
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addStretch()

        self.replace_btn = QPushButton("Replace")
        self.replace_btn.setFlat(True)
        self.replace_btn.setCursor(Qt.PointingHandCursor)
        self.replace_btn.setStyleSheet("color: #1a5fb4;")
        self.replace_btn.setVisible(False)
        self.replace_btn.clicked.connect(self.browse)
        action_row.addWidget(self.replace_btn)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setFlat(True)
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.setStyleSheet("color: #c62828;")
        self.remove_btn.setVisible(False)
        self.remove_btn.clicked.connect(self.clear_image)
        action_row.addWidget(self.remove_btn)

        action_row.addStretch()
        action_row_widget = QWidget()
        action_row_widget.setLayout(action_row)
        action_row_widget.setMinimumHeight(28)
        layout.addWidget(action_row_widget)

        self._set_placeholder()

    def _set_placeholder(self):
        self.square.setPixmap(QPixmap())
        self.square.setText("\U0001F4F7\n\nClick to upload\nor drag && drop")
        self.square.setStyleSheet(_EMPTY_STYLE)
        self.square.setToolTip("")
        self.replace_btn.setVisible(False)
        self.remove_btn.setVisible(False)

    def _on_square_clicked(self):
        """Once a photo is set, clicking the square opens a full-size
        preview (see this module's 2026-09-19 docstring note) instead of
        re-opening the file browser — Replace is the dedicated way to swap
        the file now. Before a photo is set there's nothing to preview, so
        the click still opens the browser, same as it always has."""
        if self.image_path:
            ImagePreviewDialog.show_preview(self.image_path, self.title, parent=self)
        else:
            self.browse()

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, self.dialog_caption, filter=IMAGE_FILTER)
        if path:
            self.set_image(path)

    def set_image(self, path: str):
        if path.lower().endswith(".pdf"):
            self._set_from_pdf(path)
        else:
            self._set_from_image_file(path)

    def _set_from_pdf(self, pdf_path: str):
        try:
            page_count = get_page_count(pdf_path)
        except PdfError as e:
            QMessageBox.critical(self, "PDF error", str(e))
            return

        if page_count > 1:
            page_number = PdfPagePickerDialog.pick_page(pdf_path, parent=self)
            if page_number is None:
                return  # user cancelled the picker, or it couldn't render
        else:
            page_number = 1

        try:
            pil_image = render_page(pdf_path, page_number, dpi=200)
        except PdfError as e:
            QMessageBox.critical(self, "PDF error", str(e))
            return

        rendered_path = self._save_temp_render(pil_image)
        self._set_from_image_file(rendered_path)

    def _save_temp_render(self, pil_image) -> str:
        self._cleanup_temp_render()
        PDF_RENDER_TMP_DIR.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(suffix=".png", dir=str(PDF_RENDER_TMP_DIR))
        os.close(fd)
        pil_image.save(path, "PNG")
        self._temp_render_path = path
        return path

    def _cleanup_temp_render(self):
        if self._temp_render_path and os.path.exists(self._temp_render_path):
            try:
                os.remove(self._temp_render_path)
            except OSError:
                pass  # best-effort cleanup; a leftover temp file isn't worth failing over
        self._temp_render_path = None

    def _set_from_image_file(self, path: str):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return  # not a readable image; leave the box as-is
        # If this new image isn't the temp render we just made (i.e. it's a
        # plain photo upload), the previous PDF render, if any, is now
        # orphaned — clean it up rather than leaking it.
        if path != self._temp_render_path:
            self._cleanup_temp_render()
        self.image_path = path
        scaled = pixmap.scaled(
            self.square.width() - 8, self.square.height() - 8,
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self.square.setText("")
        self.square.setPixmap(scaled)
        self.square.setStyleSheet(_FILLED_STYLE)
        self.square.setToolTip("Click to view full-size")
        self.replace_btn.setVisible(True)
        self.remove_btn.setVisible(True)
        self.changed.emit()

    def clear_image(self):
        self._cleanup_temp_render()
        self.image_path = None
        self._set_placeholder()
        self.changed.emit()
