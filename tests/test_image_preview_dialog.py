"""
Regression tests for gui/image_preview_dialog.py's ImagePreviewDialog
(added 2026-09-19, see gui/image_upload_box.py's matching docstring note)
-- opened by clicking an already-filled ID-photo square on the New IDL
form so a staff member can compare the autofilled field values against
the actual source photo at a readable size.

Run headless via QT_QPA_PLATFORM=offscreen, same pattern as every other
GUI test in this project. QGuiApplication.primaryScreen() typically
returns None under the offscreen platform, which is itself real coverage
of this module's screen-unavailable fallback path (_FALLBACK_MAX_SIZE) --
not a workaround needed just for testing.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from gui.image_preview_dialog import ImagePreviewDialog


def _make_temp_image(tmp_dir: Path, size=(400, 300)) -> str:
    path = tmp_dir / "photo.png"
    Image.new("RGB", size, color=(120, 140, 160)).save(path)
    return str(path)


class ImagePreviewDialogTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def test_window_title_is_the_box_title(self):
        image_path = _make_temp_image(self.tmp_dir)
        dialog = ImagePreviewDialog(image_path, "Passport")
        self.assertEqual(dialog.windowTitle(), "Passport")

    def test_a_readable_image_is_shown_in_the_label(self):
        image_path = _make_temp_image(self.tmp_dir)
        dialog = ImagePreviewDialog(image_path, "Passport")
        from PySide6.QtWidgets import QScrollArea
        scroll_area = dialog.findChildren(QScrollArea)[0]
        image_label = scroll_area.widget()
        self.assertFalse(image_label.pixmap().isNull())

    def test_an_unreadable_path_shows_a_message_instead_of_crashing(self):
        missing_path = str(self.tmp_dir / "does_not_exist.png")
        dialog = ImagePreviewDialog(missing_path, "Passport")
        from PySide6.QtWidgets import QScrollArea
        scroll_area = dialog.findChildren(QScrollArea)[0]
        image_label = scroll_area.widget()
        self.assertTrue(image_label.pixmap() is None or image_label.pixmap().isNull())
        self.assertIn("could not be loaded", image_label.text())

    def test_a_small_image_is_not_scaled_up_past_its_own_size(self):
        # The whole point is to make small thumbnails readable, but that
        # shouldn't mean blowing up an already-small source photo past its
        # real resolution and making it blurrier, not clearer.
        image_path = _make_temp_image(self.tmp_dir, size=(80, 60))
        dialog = ImagePreviewDialog(image_path, "Passport")
        from PySide6.QtWidgets import QScrollArea
        scroll_area = dialog.findChildren(QScrollArea)[0]
        image_label = scroll_area.widget()
        pixmap = image_label.pixmap()
        self.assertLessEqual(pixmap.width(), 80)
        self.assertLessEqual(pixmap.height(), 60)

    def test_a_large_image_is_scaled_down_to_fit(self):
        image_path = _make_temp_image(self.tmp_dir, size=(5000, 4000))
        dialog = ImagePreviewDialog(image_path, "Passport")
        from PySide6.QtWidgets import QScrollArea
        scroll_area = dialog.findChildren(QScrollArea)[0]
        image_label = scroll_area.widget()
        pixmap = image_label.pixmap()
        self.assertLess(pixmap.width(), 5000)
        self.assertLess(pixmap.height(), 4000)

    def test_max_display_size_falls_back_when_no_screen_is_available(self):
        # Under QT_QPA_PLATFORM=offscreen there typically is no real
        # screen, so this also exercises the actual fallback path, not
        # just a mocked one -- but mock it explicitly too so the test
        # doesn't depend on that platform detail holding forever.
        from unittest import mock
        with mock.patch(
            "gui.image_preview_dialog.QGuiApplication.primaryScreen", return_value=None
        ):
            size = ImagePreviewDialog._max_display_size()
        from gui.image_preview_dialog import _FALLBACK_MAX_SIZE
        self.assertEqual(size, _FALLBACK_MAX_SIZE)


if __name__ == "__main__":
    unittest.main()
