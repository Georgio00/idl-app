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
    from gui.new_idl_form import BASE_STYLESHEET, NewIDLForm


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
