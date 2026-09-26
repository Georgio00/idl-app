"""
Regression tests for printing/receipt_page.py (added 2026-09-26, see that
module's docstring) -- the "Cash Receipt" PDF behind the New IDL form's
"View Receipt"/"Print Receipt" buttons.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from printing.receipt_page import receipt_values_from_form_fields, render_receipt, render_receipt_from_form_fields


class ReceiptValuesFromFormFieldsTest(unittest.TestCase):
    def test_maps_every_expected_key(self):
        form_fields = {
            "Receipt.Number": "000123",
            "Receipt.Date": "26/9/2026",
            "Receipt.Received from": "KARIM KOREDAHI",
            "Issued Document.Number": "344629",
            "Receipt.Amount(LBP)": "5000000",
        }
        values = receipt_values_from_form_fields(form_fields)
        self.assertEqual(values, {
            "receipt_number": "000123",
            "date": "26/9/2026",
            "received_from": "KARIM KOREDAHI",
            "issued_no": "344629",
            "amount": "5000000",
        })

    def test_missing_keys_default_to_empty_string_rather_than_crashing(self):
        values = receipt_values_from_form_fields({})
        self.assertEqual(values, {
            "receipt_number": "",
            "date": "",
            "received_from": "",
            "issued_no": "",
            "amount": "",
        })

    def test_accepts_field_read_objects_not_just_plain_strings(self):
        # A saved IdlRecord's .fields are plain strings (see db/storage.py),
        # but this must also work called with a live OCR FieldRead-like
        # object (has a .value attribute) -- same v() unwrap pattern
        # printing/print_page.py's values_from_form_fields already relies on.
        class _FakeFieldRead:
            def __init__(self, value):
                self.value = value

        form_fields = {"Receipt.Received from": _FakeFieldRead("KARIM KOREDAHI")}
        values = receipt_values_from_form_fields(form_fields)
        self.assertEqual(values["received_from"], "KARIM KOREDAHI")


class RenderReceiptTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def test_produces_a_non_empty_pdf_file(self):
        output_path = str(self.tmp_dir / "receipt.pdf")
        render_receipt({
            "receipt_number": "000123", "date": "26/9/2026",
            "received_from": "KARIM KOREDAHI", "issued_no": "344629", "amount": "5000000",
        }, output_path)
        self.assertTrue(Path(output_path).exists())
        self.assertGreater(Path(output_path).stat().st_size, 0)

    def test_renders_even_with_every_value_blank(self):
        # A staff member might click "View Receipt" before filling
        # anything in -- this must never crash, same "never a silent
        # exception, but also never a hard crash on empty data" spirit as
        # printing/print_page.py's own field handling.
        output_path = str(self.tmp_dir / "receipt_blank.pdf")
        render_receipt({}, output_path)
        self.assertTrue(Path(output_path).exists())

    def test_skips_the_logo_gracefully_when_the_asset_file_is_missing(self):
        # See assets/README.md -- the real logo hadn't been provided as of
        # this feature's initial build, so this is the actual code path
        # every render currently takes, not just a hypothetical one.
        with mock.patch("printing.receipt_page._LOGO_PATH") as mock_path:
            mock_path.exists.return_value = False
            output_path = str(self.tmp_dir / "receipt_no_logo.pdf")
            render_receipt({"received_from": "KARIM KOREDAHI"}, output_path)
        self.assertTrue(Path(output_path).exists())

    def test_render_receipt_from_form_fields_end_to_end(self):
        output_path = str(self.tmp_dir / "receipt_from_form.pdf")
        render_receipt_from_form_fields({
            "Receipt.Number": "000123", "Receipt.Date": "26/9/2026",
            "Receipt.Received from": "KARIM KOREDAHI",
            "Issued Document.Number": "344629", "Receipt.Amount(LBP)": "5000000",
        }, output_path)
        self.assertTrue(Path(output_path).exists())


if __name__ == "__main__":
    unittest.main()
