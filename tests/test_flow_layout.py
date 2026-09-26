"""
Regression tests for gui/flow_layout.py's FlowLayout -- added 2026-09-26 as
the real fix for the New IDL toolbar overflow bug (see that module's
docstring and gui/new_idl_form.py's docstring, "later the same day"):
splitting the toolbar into left/right groups fixed the proportions but a
plain QHBoxLayout still doesn't wrap, so buttons kept getting clipped at
the window's right edge on a real (narrower) screen.

These tests build a small host widget, give it a narrow fixed width, add
several buttons whose combined width doesn't fit on one line, and check
that FlowLayout actually wraps them onto more than one row (button y
positions differ) rather than pushing them past the widget's right edge.
Also checks the "no wrapping needed" case stays a single row, and that
minimumSize/heightForWidth grow sensibly rather than staying flat.

Run headless via QT_QPA_PLATFORM=offscreen, same pattern as every other
gui/ test in this project.
"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QPushButton, QWidget

_app = QApplication.instance() or QApplication([])

from gui.flow_layout import FlowLayout


def _make_host(width, button_labels):
    host = QWidget()
    layout = FlowLayout(host)
    buttons = [QPushButton(label) for label in button_labels]
    for button in buttons:
        layout.addWidget(button)
    host.resize(width, 10)
    host.show()
    _app.processEvents()
    return host, layout, buttons


class WrappingBehaviorTest(unittest.TestCase):
    def test_buttons_that_fit_on_one_line_share_the_same_row(self):
        host, layout, buttons = _make_host(2000, ["Find / Reprint Record...", "New", "Save"])
        rows = {button.geometry().y() for button in buttons}
        self.assertEqual(len(rows), 1, [b.geometry() for b in buttons])

    def test_buttons_that_do_not_fit_wrap_onto_more_than_one_row(self):
        # A host too narrow for even two of these long labels side by side
        # forces a wrap -- this is the exact failure mode from Georgio's
        # screenshot (a button running past the visible window edge).
        host, layout, buttons = _make_host(
            220,
            [
                "Find / Reprint Record...",
                "◀ Previous",
                "Next ▶",
                "New",
                "Save",
            ],
        )
        rows = {button.geometry().y() for button in buttons}
        self.assertGreater(len(rows), 1, [b.geometry() for b in buttons])

    def test_wrapped_buttons_stay_within_the_hosts_width(self):
        host, layout, buttons = _make_host(
            220,
            ["Printer Settings...", "Manage Staff Accounts...", "Print Preview", "Print",
             "View Receipt", "Print Receipt"],
        )
        for button in buttons:
            geo = button.geometry()
            self.assertLessEqual(
                geo.right(), host.width(),
                f"{button.text()!r} extends past the host width: {geo} vs host width {host.width()}",
            )

    def test_no_buttons_is_harmless(self):
        host = QWidget()
        layout = FlowLayout(host)
        host.resize(200, 10)
        host.show()
        _app.processEvents()
        self.assertEqual(layout.count(), 0)

    def test_height_for_width_grows_when_a_narrower_width_forces_more_rows(self):
        wide_host, wide_layout, _ = _make_host(2000, ["Find / Reprint Record...", "New", "Save"])
        narrow_host, narrow_layout, _ = _make_host(220, ["Find / Reprint Record...", "New", "Save"])
        wide_height = wide_layout.heightForWidth(2000)
        narrow_height = narrow_layout.heightForWidth(220)
        self.assertGreater(narrow_height, wide_height)


if __name__ == "__main__":
    unittest.main()
