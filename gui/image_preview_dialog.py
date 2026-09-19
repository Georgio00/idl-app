"""
Full-size image preview, opened by clicking an already-filled
ImageUploadBox square (see that module) -- added 2026-09-19 at Georgio's
request, so a staff member can actually compare the tiny autofilled-field
values on the New IDL form against the source photo/scan itself, rather
than squinting at a ~110px thumbnail to judge whether OCR read it right.

Deliberately generic (title + image_path in, nothing about which of the
three ID-photo slots it came from) so it works the same for the Passport,
License Front, and License Back boxes without any per-field special
casing -- and for any future ImageUploadBox caller too.

Scales the image DOWN to fit comfortably within the available screen
space (never up past its own real pixel size -- that would just blur a
already-small source photo further, the opposite of what this is for),
and puts it in a QScrollArea so a photo that's still larger than the
screen after that scaling stays fully reachable by scrolling rather than
silently clipping.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
)

# Fallback used when no screen geometry is available at all (e.g. this
# module's own headless/offscreen unit tests) -- generous enough to show a
# typical document photo at a useful size without relying on QScreen.
_FALLBACK_MAX_SIZE = (1000, 800)

# Preview never claims more than this fraction of the available screen —
# leaves the underlying New IDL form visibly framed behind it and avoids
# the dialog itself feeling like a jarring full screen takeover.
_SCREEN_FRACTION = 0.85


class ImagePreviewDialog(QDialog):
    def __init__(self, image_path: str, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)

        layout = QVBoxLayout(self)

        pixmap = QPixmap(image_path)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignCenter)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignCenter)

        if pixmap.isNull():
            # Same "leave it as-is rather than crash" tolerance
            # ImageUploadBox._set_from_image_file already has for an
            # unreadable file — this dialog only ever opens for a path
            # ImageUploadBox already accepted, but the underlying file
            # could still have been moved/deleted since.
            image_label.setText("This image could not be loaded.")
        else:
            max_width, max_height = self._max_display_size()
            if pixmap.width() > max_width or pixmap.height() > max_height:
                pixmap = pixmap.scaled(
                    max_width, max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
            image_label.setPixmap(pixmap)

        scroll.setWidget(image_label)
        layout.addWidget(scroll)

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self.resize(min(pixmap.width() + 60, _FALLBACK_MAX_SIZE[0] + 200),
                    min(pixmap.height() + 100, _FALLBACK_MAX_SIZE[1] + 200))

    @staticmethod
    def _max_display_size() -> tuple[int, int]:
        """The largest the image is allowed to display at, in pixels —
        derived from the actual screen so this works sensibly on any
        monitor, falling back to a fixed generous size when no screen is
        available at all (headless tests; conceivably a real machine with
        an unusual display setup)."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return _FALLBACK_MAX_SIZE
        geometry = screen.availableGeometry()
        if geometry.width() <= 0 or geometry.height() <= 0:
            return _FALLBACK_MAX_SIZE
        return (
            max(int(geometry.width() * _SCREEN_FRACTION), 1),
            max(int(geometry.height() * _SCREEN_FRACTION), 1),
        )

    @staticmethod
    def show_preview(image_path: str, title: str, parent=None):
        """Convenience entry point mirroring PdfPagePickerDialog.pick_page's
        pattern elsewhere in this package — builds and shows the dialog in
        one call so callers (ImageUploadBox) don't need to import QDialog
        just to invoke exec()."""
        dialog = ImagePreviewDialog(image_path, title, parent=parent)
        dialog.exec()
