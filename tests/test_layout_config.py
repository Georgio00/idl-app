"""
Regression test locking in the real, measured IDP data page size
(2026-09-09: 7cm x 10.5cm, given directly by Georgio) — guards against
this accidentally drifting back toward the old 74x105mm placeholder in a
future edit, since a wrong page size silently mis-scales every field
position on a real printed page rather than failing loudly.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from printing import layout_config
from printing.layout_config import COVER_SIZE_MM, PAGE_SIZE_MM, load_layout


class RealPageSizeTest(unittest.TestCase):
    def test_data_page_size_is_the_real_measurement_not_the_old_placeholder(self):
        self.assertEqual(PAGE_SIZE_MM, (70.0, 105.0))
        self.assertNotEqual(PAGE_SIZE_MM, (74.0, 105.0), "reverted to the old placeholder guess")

    def test_cover_page_size_mirrors_the_data_page(self):
        # Assumed, not independently measured -- see layout_config.py's
        # module docstring. This test only guards against the two drifting
        # apart silently, not against the assumption itself being wrong.
        self.assertEqual(COVER_SIZE_MM, PAGE_SIZE_MM)


class LoadLayoutFallbackTest(unittest.TestCase):
    """Points LAYOUT_PATH at a guaranteed-nonexistent temp path for the
    duration of this test, so the result is deterministic regardless of
    whether the machine actually running this suite has a real
    %LOCALAPPDATA%\\IDL_APP\\print_layout.json override on disk (e.g. from
    a prior calibration_screen run, which -- by load_layout's own design
    -- would otherwise win over these defaults entirely)."""

    def setUp(self):
        self._orig_layout_path = layout_config.LAYOUT_PATH
        layout_config.LAYOUT_PATH = Path(tempfile.mkdtemp()) / "no_such_print_layout.json"

    def tearDown(self):
        layout_config.LAYOUT_PATH = self._orig_layout_path

    def test_falls_back_to_the_real_page_size_when_no_override_file_exists(self):
        layout = load_layout()
        self.assertEqual(tuple(layout["page_size_mm"]), (70.0, 105.0))
        self.assertEqual(tuple(layout["cover_size_mm"]), (70.0, 105.0))


if __name__ == "__main__":
    unittest.main()
