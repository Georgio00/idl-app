"""
Regression test for packaging/find_sqlite3_dll.py (added 2026-09-10).

Locks in the fix for a real deployment failure: the built app crashed on
a second PC with "ImportError: DLL load failed while importing _sqlite3"
because PyInstaller's automatic dependency scan missed sqlite3.dll when
the build's base Python was an Anaconda install (Library\\bin\\sqlite3.dll)
rather than a plain python.org one (DLLs\\sqlite3.dll). These tests use
real temporary directories (not mocks) so they actually exercise
Path.is_file() against a real filesystem, the same check the spec file
relies on at build time.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))

from find_sqlite3_dll import Sqlite3DllNotFoundError, find_sqlite3_dll


class FindSqlite3DllTest(unittest.TestCase):
    def setUp(self):
        self.base_prefix = Path(tempfile.mkdtemp())

    def test_finds_it_in_the_plain_python_org_layout(self):
        dlls_dir = self.base_prefix / "DLLs"
        dlls_dir.mkdir()
        expected = dlls_dir / "sqlite3.dll"
        expected.write_bytes(b"fake dll")

        self.assertEqual(find_sqlite3_dll(self.base_prefix), expected)

    def test_finds_it_in_the_anaconda_layout(self):
        # This is the layout that actually broke the real build --
        # Georgio's .venv was created from anaconda3\python.exe, and
        # Anaconda puts sqlite3.dll here, not under DLLs\.
        library_bin = self.base_prefix / "Library" / "bin"
        library_bin.mkdir(parents=True)
        expected = library_bin / "sqlite3.dll"
        expected.write_bytes(b"fake dll")

        self.assertEqual(find_sqlite3_dll(self.base_prefix), expected)

    def test_finds_it_directly_under_base_prefix_as_a_last_resort(self):
        expected = self.base_prefix / "sqlite3.dll"
        expected.write_bytes(b"fake dll")

        self.assertEqual(find_sqlite3_dll(self.base_prefix), expected)

    def test_prefers_the_python_org_layout_when_multiple_exist(self):
        dlls_dir = self.base_prefix / "DLLs"
        dlls_dir.mkdir()
        preferred = dlls_dir / "sqlite3.dll"
        preferred.write_bytes(b"fake dll")

        library_bin = self.base_prefix / "Library" / "bin"
        library_bin.mkdir(parents=True)
        (library_bin / "sqlite3.dll").write_bytes(b"fake dll")

        self.assertEqual(find_sqlite3_dll(self.base_prefix), preferred)

    def test_raises_a_clear_error_with_no_dll_anywhere(self):
        with self.assertRaises(Sqlite3DllNotFoundError) as ctx:
            find_sqlite3_dll(self.base_prefix)

        message = str(ctx.exception)
        self.assertIn("sqlite3.dll", message)
        self.assertIn(str(self.base_prefix), message)

    def test_accepts_a_string_path_not_just_a_path_object(self):
        # sys.base_prefix is a plain str, not a Path -- the real caller
        # in idl_app.spec passes it straight through.
        dlls_dir = self.base_prefix / "DLLs"
        dlls_dir.mkdir()
        expected = dlls_dir / "sqlite3.dll"
        expected.write_bytes(b"fake dll")

        self.assertEqual(find_sqlite3_dll(str(self.base_prefix)), expected)


if __name__ == "__main__":
    unittest.main()
