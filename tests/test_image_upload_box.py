"""
Regression tests for gui/image_upload_box.py's ImageUploadBox, focused on
the 2026-09-19 click-to-preview change (see that module's docstring):
clicking an already-filled square now opens ImagePreviewDialog instead of
immediately re-opening the file browser, while an empty square (and the
Replace button, always) still opens the browser exactly as before.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from gui.image_upload_box import ImageUploadBox


def _make_temp_image(tmp_dir: Path) -> str:
    path = tmp_dir / "photo.png"
    Image.new("RGB", (200, 150), color=(10, 20, 30)).save(path)
    return str(path)


class ClickToBrowseWhenEmptyTest(unittest.TestCase):
    """Unchanged behavior: nothing to preview yet, so clicking the empty
    square still opens the file browser, same as before this feature."""

    def setUp(self):
        self.box = ImageUploadBox("Passport", "Select the passport photo page")

    def test_clicking_an_empty_square_calls_browse(self):
        with mock.patch.object(self.box, "browse") as mock_browse:
            self.box._on_square_clicked()
        mock_browse.assert_called_once()

    def test_clicking_an_empty_square_does_not_open_a_preview(self):
        # browse() is mocked too -- otherwise the real one it would
        # actually fall through to opens a real modal QFileDialog that
        # blocks this headless run waiting for a click that never comes.
        with mock.patch.object(self.box, "browse"), \
             mock.patch("gui.image_upload_box.ImagePreviewDialog") as mock_dialog_cls:
            self.box._on_square_clicked()
        mock_dialog_cls.show_preview.assert_not_called()


class ClickToPreviewWhenFilledTest(unittest.TestCase):
    """The new behavior: once a photo is set, clicking the square opens
    the full-size preview instead of the browser."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.box = ImageUploadBox("Passport", "Select the passport photo page")
        self.image_path = _make_temp_image(self.tmp_dir)
        self.box.set_image(self.image_path)

    def test_clicking_a_filled_square_opens_the_preview(self):
        with mock.patch("gui.image_upload_box.ImagePreviewDialog") as mock_dialog_cls:
            self.box._on_square_clicked()
        mock_dialog_cls.show_preview.assert_called_once_with(
            self.image_path, "Passport", parent=self.box
        )

    def test_clicking_a_filled_square_does_not_call_browse(self):
        with mock.patch.object(self.box, "browse") as mock_browse, \
             mock.patch("gui.image_upload_box.ImagePreviewDialog"):
            self.box._on_square_clicked()
        mock_browse.assert_not_called()

    def test_replace_button_still_opens_the_browser_directly(self):
        # Replace is the one dedicated way left to swap the file now that
        # clicking the square itself previews instead of browsing. Uses a
        # real button .click(), which fires through Qt's actual signal/
        # slot connection made back in __init__ -- patching self.box.browse
        # as an instance attribute would NOT be seen by that already-made
        # connection (it holds the original bound method), so the real
        # QFileDialog call underneath browse() is mocked instead, the same
        # way this project's other tests mock real modal calls rather than
        # the method that triggers them.
        with mock.patch(
            "gui.image_upload_box.QFileDialog.getOpenFileName", return_value=("", "")
        ) as mock_get_open_file_name:
            self.box.replace_btn.click()
        mock_get_open_file_name.assert_called_once()

    def test_the_preview_uses_this_box_own_title(self):
        # Generic across all three ID-photo slots -- License Front/Back
        # boxes must show THEIR OWN title, not a hardcoded "Passport".
        other_box = ImageUploadBox("Driving License — Front", "Select the driving license — FRONT")
        other_box.set_image(self.image_path)
        with mock.patch("gui.image_upload_box.ImagePreviewDialog") as mock_dialog_cls:
            other_box._on_square_clicked()
        mock_dialog_cls.show_preview.assert_called_once_with(
            self.image_path, "Driving License — Front", parent=other_box
        )

    def test_removing_the_image_reverts_to_click_to_browse(self):
        self.box.clear_image()
        with mock.patch.object(self.box, "browse") as mock_browse, \
             mock.patch("gui.image_upload_box.ImagePreviewDialog") as mock_dialog_cls:
            self.box._on_square_clicked()
        mock_browse.assert_called_once()
        mock_dialog_cls.show_preview.assert_not_called()


class ToolTipTest(unittest.TestCase):
    """Small UX nicety added alongside the click-to-preview change --
    documents intent for a sighted user hovering the square."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.box = ImageUploadBox("Passport", "Select the passport photo page")

    def test_empty_square_has_no_preview_tooltip(self):
        self.assertEqual(self.box.square.toolTip(), "")

    def test_filled_square_hints_at_the_preview(self):
        self.box.set_image(_make_temp_image(self.tmp_dir))
        self.assertIn("full-size", self.box.square.toolTip())

    def test_clearing_the_image_removes_the_tooltip(self):
        self.box.set_image(_make_temp_image(self.tmp_dir))
        self.box.clear_image()
        self.assertEqual(self.box.square.toolTip(), "")


if __name__ == "__main__":
    unittest.main()
