"""
Regression tests for the 2026-09-19 layout/sizing change to
gui/new_idl_form.py: Georgio sent a screenshot of LAA's own screen and
asked for "the same page layout" (Number/Date, and Amount(LBP)/Date, each
PAIRED on one row -- LAA does this, our old QFormLayout-per-group couldn't)
plus "make the words bigger and everything bigger" (BASE_STYLESHEET).

These check the two structural things a visual screenshot review can't
pin down for the future: that Number/Date and Amount(LBP)/Date really do
share a grid row (not just look close together by coincidence of spacing),
and that the bigger-text stylesheet is actually wired onto the window
(not just present as an unused module constant). Also covers the same
day's later "also add branch and name" request: Receipt.Branch/
Receipt.User are paired on their own row the same way. Run headless via
QT_QPA_PLATFORM=offscreen, same as tests/test_new_idl_form.py -- see that
file's own docstring for why Storage is mocked and QMessageBox isn't
needed here (nothing in these tests triggers one).

2026-09-26 (later the same day): ToolbarLayoutTest covers the top-bar
overflow fix -- splitting the old single flat top_bar into
top_bar_left/top_bar_right and flipping the body columns' stretch ratio
so the button-holding right side is wider than the field-holding left
side (see new_idl_form.py's docstring's "later the same day" entry and
_LEFT_COLUMN_STRETCH/_RIGHT_COLUMN_STRETCH).
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QGridLayout

_app = QApplication.instance() or QApplication([])

with mock.patch("gui.new_idl_form.Storage"):
    from gui.new_idl_form import (
        BASE_STYLESHEET,
        _LEFT_COLUMN_STRETCH,
        _RIGHT_COLUMN_STRETCH,
        NewIDLForm,
    )


def _make_form() -> NewIDLForm:
    with mock.patch("gui.new_idl_form.Storage"):
        return NewIDLForm()


def _grid_row(edit) -> int:
    """Looks up which grid row a field's QLineEdit sits on, by asking its
    parent QGroupBox's own layout (a QGridLayout since this change) where
    that widget landed -- the only way to check "same row" from outside
    __init__, since orig_box/issued_box/receipt_box are local variables
    there, not kept as attributes."""
    layout = edit.parentWidget().layout()
    assert isinstance(layout, QGridLayout), f"expected a QGridLayout, got {type(layout)}"
    index = layout.indexOf(edit)
    row, _col, _rowspan, _colspan = layout.getItemPosition(index)
    return row


class PairedRowLayoutTest(unittest.TestCase):
    def setUp(self):
        self.form = _make_form()

    def test_original_document_number_and_date_share_a_row(self):
        number = self.form.fields["Original Document.Number"]
        date = self.form.fields["Original Document.Date"]
        self.assertEqual(_grid_row(number), _grid_row(date))

    def test_original_document_other_fields_each_get_their_own_row(self):
        rows = {
            key: _grid_row(self.form.fields[f"Original Document.{key}"])
            for key in ("Place of Issue", "Category", "Expiry Date")
        }
        # All three distinct from each other...
        self.assertEqual(len(set(rows.values())), 3, rows)
        # ...and distinct from the Number/Date row.
        number_row = _grid_row(self.form.fields["Original Document.Number"])
        self.assertNotIn(number_row, rows.values())

    def test_issued_document_number_and_date_share_a_row(self):
        number = self.form.fields["Issued Document.Number"]
        date = self.form.fields["Issued Document.Date"]
        self.assertEqual(_grid_row(number), _grid_row(date))

    def test_issued_document_signature_gets_its_own_row(self):
        number_row = _grid_row(self.form.fields["Issued Document.Number"])
        signature_row = _grid_row(self.form.fields["Issued Document.Signature"])
        self.assertNotEqual(number_row, signature_row)

    def test_receipt_amount_and_date_share_a_row(self):
        amount = self.form.fields["Receipt.Amount(LBP)"]
        date = self.form.fields["Receipt.Date"]
        self.assertEqual(_grid_row(amount), _grid_row(date))

    def test_receipt_received_from_gets_its_own_row(self):
        received_from_row = _grid_row(self.form.fields["Receipt.Received from"])
        amount_row = _grid_row(self.form.fields["Receipt.Amount(LBP)"])
        self.assertNotEqual(received_from_row, amount_row)

    def test_receipt_branch_and_user_share_a_row(self):
        # 2026-09-19 ("also add branch and name"): LAA's own screen shows
        # these two at the bottom of the Receipt group -- paired here the
        # same way Number/Date and Amount/Date already are.
        branch = self.form.fields["Receipt.Branch"]
        user = self.form.fields["Receipt.User"]
        self.assertEqual(_grid_row(branch), _grid_row(user))

    def test_receipt_branch_user_row_is_distinct_from_amount_date_row(self):
        branch_row = _grid_row(self.form.fields["Receipt.Branch"])
        amount_row = _grid_row(self.form.fields["Receipt.Amount(LBP)"])
        self.assertNotEqual(branch_row, amount_row)

    def test_receipt_number_gets_its_own_row(self):
        # 2026-09-26 ("Print Receipt"): "No." sits above Received from,
        # on its own row -- not paired with anything, since there's no
        # natural second field to pair it with the way Amount/Date and
        # Branch/User are.
        number_row = _grid_row(self.form.fields["Receipt.Number"])
        received_from_row = _grid_row(self.form.fields["Receipt.Received from"])
        amount_row = _grid_row(self.form.fields["Receipt.Amount(LBP)"])
        branch_row = _grid_row(self.form.fields["Receipt.Branch"])
        self.assertNotIn(number_row, (received_from_row, amount_row, branch_row))

    def test_personal_details_fields_are_not_on_a_grid_at_all(self):
        # Personal details deliberately stayed a plain QFormLayout (one
        # field per row, same as before) -- only Original Document/Issued
        # Document/Receipt switched to QGridLayout for row-pairing.
        surname = self.form.fields["Surname"]
        self.assertNotIsInstance(surname.parentWidget().layout(), QGridLayout)


class ToolbarLayoutTest(unittest.TestCase):
    """2026-09-26 ("fix the layout of the upper part of the app / make the
    left side less smaller in width and use the right part for the
    buttons we have"): Print Receipt was getting cut off at the window's
    right edge -- the top bar was one flat QHBoxLayout with every button
    in sequence, and the body columns were left-heavy (stretch 2:1)
    despite Georgio's reference photos of LAA's own screen showing a
    narrower field panel and a wider button panel. See new_idl_form.py's
    docstring and _LEFT_COLUMN_STRETCH/_RIGHT_COLUMN_STRETCH.
    """

    def setUp(self):
        self.form = _make_form()

    def test_body_columns_are_wider_on_the_right_than_the_left(self):
        # Old layout was left=2/right=1 (left side wider) -- the reference
        # photos show the opposite. This is the change that actually fixes
        # the overflow: the button-holding side now has more room.
        left = _LEFT_COLUMN_STRETCH
        right = _RIGHT_COLUMN_STRETCH
        self.assertGreater(right, left)

    def test_record_navigation_buttons_share_a_layout_distinct_from_the_output_buttons(self):
        # records_btn/prev/next/new/save (record browsing+CRUD) should be
        # in one toolbar group, separate from the print/view/settings
        # buttons -- not all one flat top_bar the way it used to be.
        nav_group = self.form.records_btn.parentWidget()
        output_group = self.form.print_btn.parentWidget()
        # Both buttons still live in the same top-level central widget
        # (there's only one QWidget tree), so what actually distinguishes
        # "different toolbar group" is which QLayout each button's geometry
        # is managed by, not a different parent widget. Compare via each
        # layout the buttons were added to instead.
        nav_layout = self.form.records_btn.parentWidget().layout()
        # A QPushButton added to a QHBoxLayout doesn't expose that layout
        # directly, so instead check the buttons the reference groups say
        # must be split are not reachable from one another's immediate
        # sibling widget list at the same index -- simplest robust check:
        # walk every top-level QHBoxLayout under central widget's outer
        # QVBoxLayout and confirm records_btn/print_btn end up in two
        # different ones.
        outer = self.form.centralWidget().layout()
        top_bar_row = outer.itemAt(0).layout()
        self.assertIsNotNone(top_bar_row)
        left_layout = top_bar_row.itemAt(0).layout()
        right_layout = top_bar_row.itemAt(2).layout()

        def _widgets_in(layout):
            widgets = []
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item.widget() is not None:
                    widgets.append(item.widget())
            return widgets

        self.assertIn(self.form.records_btn, _widgets_in(left_layout))
        self.assertIn(self.form.prev_record_btn, _widgets_in(left_layout))
        self.assertIn(self.form.next_record_btn, _widgets_in(left_layout))
        self.assertIn(self.form.new_btn, _widgets_in(left_layout))
        self.assertIn(self.form.save_btn, _widgets_in(left_layout))

        self.assertIn(self.form.printer_settings_btn, _widgets_in(right_layout))
        self.assertIn(self.form.manage_users_btn, _widgets_in(right_layout))
        self.assertIn(self.form.print_preview_btn, _widgets_in(right_layout))
        self.assertIn(self.form.print_btn, _widgets_in(right_layout))
        self.assertIn(self.form.view_receipt_btn, _widgets_in(right_layout))
        self.assertIn(self.form.print_receipt_btn, _widgets_in(right_layout))
        self.assertIn(self.form.view_form_btn, _widgets_in(right_layout))
        self.assertIn(self.form.print_form_btn, _widgets_in(right_layout))

        del nav_group, output_group, nav_layout  # only used to document intent above

    def test_top_bar_row_uses_the_same_stretch_ratio_as_the_body_columns(self):
        # The whole point of splitting top_bar into two groups was so it
        # visually lines up with the body columns underneath -- assert the
        # stretch factors actually match, not just that they're "close".
        outer = self.form.centralWidget().layout()
        top_bar_row = outer.itemAt(0).layout()
        self.assertEqual(top_bar_row.stretch(0), _LEFT_COLUMN_STRETCH)
        self.assertEqual(top_bar_row.stretch(2), _RIGHT_COLUMN_STRETCH)

        columns = outer.itemAt(2).layout()
        self.assertEqual(columns.stretch(0), _LEFT_COLUMN_STRETCH)
        self.assertEqual(columns.stretch(2), _RIGHT_COLUMN_STRETCH)

    def test_no_button_was_dropped_or_duplicated_by_the_regrouping(self):
        outer = self.form.centralWidget().layout()
        top_bar_row = outer.itemAt(0).layout()
        left_layout = top_bar_row.itemAt(0).layout()
        right_layout = top_bar_row.itemAt(2).layout()

        def _widgets_in(layout):
            widgets = []
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item.widget() is not None:
                    widgets.append(item.widget())
            return widgets

        all_buttons = _widgets_in(left_layout) + _widgets_in(right_layout)
        expected = [
            self.form.records_btn,
            self.form.prev_record_btn,
            self.form.next_record_btn,
            self.form.new_btn,
            self.form.save_btn,
            self.form.printer_settings_btn,
            self.form.manage_users_btn,
            self.form.print_preview_btn,
            self.form.print_btn,
            self.form.view_receipt_btn,
            self.form.print_receipt_btn,
            self.form.view_form_btn,
            self.form.print_form_btn,
        ]
        self.assertEqual(len(all_buttons), len(expected))
        self.assertCountEqual(all_buttons, expected)


class ToolbarIconsTest(unittest.TestCase):
    """2026-09-26 ("add icons like the ones in the image i gave you"):
    every toolbar button should now carry a non-null icon -- see
    gui/icons.py and new_idl_form.py's docstring's _TOOLBAR_ICONS mapping.
    """

    def setUp(self):
        self.form = _make_form()

    def test_every_toolbar_button_has_a_non_null_icon(self):
        buttons = [
            self.form.records_btn,
            self.form.prev_record_btn,
            self.form.next_record_btn,
            self.form.new_btn,
            self.form.save_btn,
            self.form.printer_settings_btn,
            self.form.manage_users_btn,
            self.form.print_preview_btn,
            self.form.print_btn,
            self.form.view_receipt_btn,
            self.form.print_receipt_btn,
            self.form.view_form_btn,
            self.form.print_form_btn,
        ]
        for button in buttons:
            self.assertFalse(button.icon().isNull(), button.text())

    def test_receipt_buttons_share_the_same_icon_color_as_each_other(self):
        # Georgio's reference photo colors Print Receipt/View Receipt the
        # same green -- both are printer/eye pictograms of the same
        # color, so their rendered pixmaps' non-transparent pixels should
        # be the same color even though the pictogram shape differs.
        from PySide6.QtGui import QImage

        def _opaque_pixel_colors(button):
            image = button.icon().pixmap(18, 18).toImage().convertToFormat(QImage.Format_RGBA8888)
            colors = set()
            for y in range(image.height()):
                for x in range(image.width()):
                    pixel = image.pixelColor(x, y)
                    if pixel.alpha() > 200:
                        colors.add((pixel.red(), pixel.green(), pixel.blue()))
            return colors

        receipt_colors = _opaque_pixel_colors(self.form.view_receipt_btn) | _opaque_pixel_colors(
            self.form.print_receipt_btn
        )
        print_colors = _opaque_pixel_colors(self.form.print_btn)
        # Green (receipt family) and blue (licence/print family) shouldn't
        # overlap in their fully-opaque colors.
        self.assertTrue(receipt_colors, "view/print receipt icons painted nothing opaque")
        self.assertTrue(print_colors, "print icon painted nothing opaque")
        self.assertEqual(receipt_colors & print_colors, set())

    def test_form_buttons_are_a_third_distinct_color_from_receipt_and_print(self):
        # 2026-09-26 ("print form option and view form"): Form is a THIRD
        # family (red in the reference photos), distinct from both Receipt
        # (green) and Licence/Print (blue).
        from PySide6.QtGui import QImage

        def _opaque_pixel_colors(button):
            image = button.icon().pixmap(18, 18).toImage().convertToFormat(QImage.Format_RGBA8888)
            colors = set()
            for y in range(image.height()):
                for x in range(image.width()):
                    pixel = image.pixelColor(x, y)
                    if pixel.alpha() > 200:
                        colors.add((pixel.red(), pixel.green(), pixel.blue()))
            return colors

        form_colors = _opaque_pixel_colors(self.form.view_form_btn) | _opaque_pixel_colors(self.form.print_form_btn)
        receipt_colors = _opaque_pixel_colors(self.form.view_receipt_btn) | _opaque_pixel_colors(
            self.form.print_receipt_btn
        )
        print_colors = _opaque_pixel_colors(self.form.print_btn)

        self.assertTrue(form_colors, "view/print form icons painted nothing opaque")
        self.assertEqual(form_colors & receipt_colors, set())
        self.assertEqual(form_colors & print_colors, set())


class BiggerEverythingStylesheetTest(unittest.TestCase):
    def test_base_stylesheet_raises_field_and_button_font_size(self):
        self.assertIn("font-size: 13pt", BASE_STYLESHEET)

    def test_base_stylesheet_is_actually_applied_to_the_window(self):
        form = _make_form()
        # setCentralWidget's argument is what setStyleSheet was called on
        # in __init__ -- check the real central widget, not just that the
        # constant exists somewhere in the module.
        self.assertEqual(form.centralWidget().styleSheet(), BASE_STYLESHEET)

    def test_window_default_size_grew_to_match(self):
        form = _make_form()
        # Old default was 880x780 -- pin down that it's genuinely bigger
        # now, not just that BASE_STYLESHEET exists.
        self.assertGreater(form.size().width(), 880)
        self.assertGreater(form.size().height(), 780)


if __name__ == "__main__":
    unittest.main()
