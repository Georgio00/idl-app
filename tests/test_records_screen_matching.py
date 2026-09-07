"""
Regression tests for gui/records_screen.py's _matches() search filter --
the pure, GUI-free piece of the Records screen (see that module's
docstring). Deliberately does not instantiate RecordsScreen itself: doing
so needs a live QApplication/offscreen Qt platform, which the rest of
this project's test suite has never needed since every other test targets
non-GUI logic -- the actual dialog (search box, table, Open/Reprint
wiring) was verified with a manual headless smoke test instead (see the
git history around 2026-09-07's "records lookup screen" change).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.storage import IdlRecord
from gui.records_screen import _matches


def _record(record_id=1, created_at="2026-09-07T10:00:00", **fields) -> IdlRecord:
    return IdlRecord(id=record_id, created_at=created_at, fields=fields)


class MatchesTest(unittest.TestCase):
    def test_empty_search_matches_everything(self):
        self.assertTrue(_matches(_record(**{"Surname": "SFEIR"}), ""))

    def test_matches_a_field_value_case_insensitively(self):
        record = _record(**{"Surname": "SFEIR", "First Name": "CHARBEL"})
        self.assertTrue(_matches(record, "sfeir"))
        self.assertTrue(_matches(record, "SFEIR"))
        self.assertTrue(_matches(record, "charbel"))

    def test_matches_a_partial_value(self):
        record = _record(**{"Original Document.Number": "641312"})
        self.assertTrue(_matches(record, "6413"))

    def test_matches_the_record_id(self):
        record = _record(record_id=42, **{"Surname": "SFEIR"})
        self.assertTrue(_matches(record, "42"))

    def test_matches_the_created_at_timestamp(self):
        record = _record(created_at="2026-09-07T10:00:00", **{"Surname": "SFEIR"})
        self.assertTrue(_matches(record, "2026-09-07"))

    def test_no_match_returns_false(self):
        record = _record(**{"Surname": "SFEIR"})
        self.assertFalse(_matches(record, "nonexistent"))

    def test_does_not_crash_on_a_record_with_empty_field_values(self):
        record = _record(**{"Surname": "", "Phone": ""})
        self.assertFalse(_matches(record, "anything"))
        self.assertTrue(_matches(record, ""))


if __name__ == "__main__":
    unittest.main()
