"""Regression tests for updater/version.py (added 2026-09-11)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from updater.version import is_newer, parse_version


class ParseVersionTest(unittest.TestCase):
    def test_parses_a_three_part_version(self):
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))

    def test_parses_a_one_part_version(self):
        self.assertEqual(parse_version("7"), (7,))

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(parse_version("  1.2.3  "), (1, 2, 3))

    def test_rejects_empty_string(self):
        with self.assertRaises(ValueError):
            parse_version("")

    def test_rejects_a_leading_v(self):
        with self.assertRaises(ValueError):
            parse_version("v1.2.3")

    def test_rejects_a_pre_release_suffix(self):
        with self.assertRaises(ValueError):
            parse_version("1.2.3-beta")

    def test_rejects_non_numeric_junk(self):
        with self.assertRaises(ValueError):
            parse_version("not.a.version")


class IsNewerTest(unittest.TestCase):
    def test_higher_patch_is_newer(self):
        self.assertTrue(is_newer("1.0.1", "1.0.0"))

    def test_higher_minor_is_newer(self):
        self.assertTrue(is_newer("1.1.0", "1.0.9"))

    def test_higher_major_is_newer(self):
        self.assertTrue(is_newer("2.0.0", "1.9.9"))

    def test_equal_versions_are_not_newer(self):
        self.assertFalse(is_newer("1.0.0", "1.0.0"))

    def test_lower_version_is_not_newer(self):
        self.assertFalse(is_newer("1.0.0", "1.0.1"))

    def test_shorter_version_strings_are_zero_padded(self):
        self.assertFalse(is_newer("1.2", "1.2.0"))
        self.assertTrue(is_newer("1.3", "1.2.9"))

    def test_malformed_candidate_raises_rather_than_silently_comparing(self):
        with self.assertRaises(ValueError):
            is_newer("not-a-version", "1.0.0")


if __name__ == "__main__":
    unittest.main()
