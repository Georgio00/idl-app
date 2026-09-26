"""
Regression tests for printing/form_page.py (added 2026-09-26, see that
module's docstring) -- the "Application for I D L" PDF behind the New IDL
form's "View Form"/"Print Form" buttons.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from printing.form_page import form_values_from_form_fields, render_form, render_form_from_form_fields


class FormValuesFromFormFieldsTest(unittest.TestCase):
    def test_maps_every_expected_key_from_the_new_idl_forms_own_field_names(self):
        form_fields = {
            "Surname": "KORDAHI",
            "First Name": "KARIM",
            "Father's Name": "KAMAL",
            "Place of B.": "JBEIL",
            "Date of B.": "16/09/1981",
            "Original Document.Number": "1512683",
            "Original Document.Date": "18/11/1999",
            "Original Document.Place of Issue": "DEK",
            "Original Document.Category": "B",
            "Original Document.Expiry Date": "18/11/2031",
            "Issued Document.Number": "344629",
            "Issued Document.Date": "10/9/2026",
        }
        values = form_values_from_form_fields(form_fields)
        self.assertEqual(values["surname"], "KORDAHI")
        self.assertEqual(values["first_name"], "KARIM")
        self.assertEqual(values["father_name"], "KAMAL")
        self.assertEqual(values["place_of_birth"], "JBEIL")
        self.assertEqual(values["date_of_birth"], "16/09/1981")
        self.assertEqual(values["orig_number"], "1512683")
        self.assertEqual(values["orig_date"], "18/11/1999")
        self.assertEqual(values["orig_place_of_issue"], "DEK")
        self.assertEqual(values["orig_category"], "B")
        self.assertEqual(values["orig_expiry_date"], "18/11/2031")
        self.assertEqual(values["issued_number"], "344629")
        self.assertEqual(values["issued_date"], "10/9/2026")

    def test_fields_the_new_idl_form_does_not_collect_default_to_blank(self):
        # Mother's Name/Address/Phone/Email/Blood Type have no key in
        # form_fields at all (gui/new_idl_form.py's Personal details group
        # was trimmed 2026-09-14) -- must render blank, not raise.
        values = form_values_from_form_fields({"Surname": "KORDAHI"})
        for key in ("mother_name", "address", "phone", "email", "blood_type"):
            self.assertEqual(values[key], "")

    def test_missing_keys_default_to_empty_string_rather_than_crashing(self):
        values = form_values_from_form_fields({})
        self.assertTrue(all(v == "" for v in values.values()))

    def test_accepts_field_read_objects_not_just_plain_strings(self):
        class _FakeFieldRead:
            def __init__(self, value):
                self.value = value

        form_fields = {"Surname": _FakeFieldRead("KORDAHI")}
        values = form_values_from_form_fields(form_fields)
        self.assertEqual(values["surname"], "KORDAHI")


class RenderFormTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def test_produces_a_non_empty_pdf_file(self):
        output_path = str(self.tmp_dir / "form.pdf")
        render_form({"surname": "KORDAHI", "first_name": "KARIM"}, output_path)
        self.assertTrue(Path(output_path).exists())
        self.assertGreater(Path(output_path).stat().st_size, 0)

    def test_renders_even_with_every_value_blank(self):
        # A staff member might click "View Form" before filling anything
        # in -- must never crash, same contract as render_receipt.
        output_path = str(self.tmp_dir / "form_blank.pdf")
        render_form({}, output_path)
        self.assertTrue(Path(output_path).exists())

    def test_render_form_from_form_fields_end_to_end(self):
        output_path = str(self.tmp_dir / "form_from_fields.pdf")
        render_form_from_form_fields({
            "Surname": "KORDAHI", "First Name": "KARIM", "Father's Name": "KAMAL",
            "Place of B.": "JBEIL", "Date of B.": "16/09/1981",
            "Original Document.Number": "1512683", "Original Document.Date": "18/11/1999",
            "Original Document.Place of Issue": "DEK", "Original Document.Category": "B",
            "Original Document.Expiry Date": "18/11/2031",
            "Issued Document.Number": "344629", "Issued Document.Date": "10/9/2026",
        }, output_path)
        self.assertTrue(Path(output_path).exists())


if __name__ == "__main__":
    unittest.main()
