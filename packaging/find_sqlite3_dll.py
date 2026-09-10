"""
Locates the SQLite engine DLL a built app's _sqlite3.pyd needs at runtime.

Pulled out of packaging/idl_app.spec into its own plain module so this
logic has a regression test (tests/test_find_sqlite3_dll.py) -- .spec
files aren't otherwise unit-testable.

Background (2026-09-10): the built app crashed on a machine other than
the one that built it -- "ImportError: DLL load failed while importing
_sqlite3: The specified module could not be found." _sqlite3.pyd (the
Python C-extension wrapper db/storage.py's sqlite3 import pulls in)
dynamically loads a *separate* sqlite3.dll (the actual SQLite engine) at
runtime. On this project's build machine, the project's .venv was
created from an Anaconda Python (see .venv\\pyvenv.cfg's "home"), and
Anaconda lays that DLL out at anaconda3\\Library\\bin\\sqlite3.dll --
not next to python.exe the way a plain python.org install would
(DLLs\\sqlite3.dll). PyInstaller's automatic dependency scan didn't find
it in the Anaconda location, so it silently produced a .exe that only
happened to work on the one machine that already had that exact DLL on
its PATH -- built fine, worked on the build machine, crashed everywhere
else with no hint at build time that anything was wrong.
"""

from __future__ import annotations

from pathlib import Path


class Sqlite3DllNotFoundError(RuntimeError):
    """Raised when no sqlite3.dll can be found under the given base Python
    install. Meant to fail a build loudly and immediately, rather than
    producing another .exe that only works on the machine that built it."""


def find_sqlite3_dll(base_prefix: Path | str) -> Path:
    """`base_prefix` should be `sys.base_prefix` -- the *base* Python
    install that created the currently running venv, not `sys.prefix`
    (the venv itself, which never contains this DLL). Checks, in order:
    the standard python.org layout (`DLLs/sqlite3.dll`), the Anaconda/
    conda layout (`Library/bin/sqlite3.dll`), and the base folder itself
    -- covering every layout seen in this project so far without
    hardcoding any one person's install path.
    """
    base_prefix = Path(base_prefix)
    candidates = [
        base_prefix / "DLLs" / "sqlite3.dll",
        base_prefix / "Library" / "bin" / "sqlite3.dll",
        base_prefix / "sqlite3.dll",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    searched = "\n  ".join(str(c) for c in candidates)
    raise Sqlite3DllNotFoundError(
        "Could not find sqlite3.dll for the Python running this build "
        f"(base install: {base_prefix}). Looked in:\n  {searched}\n"
        "db/storage.py needs Python's sqlite3 module, which needs this "
        "DLL at runtime -- without it the built .exe will crash on any "
        "machine other than one that happens to already have this exact "
        "DLL on its PATH (see this module's docstring for how that was "
        "first discovered). Find sqlite3.dll under your base Python "
        "install and either move it to one of the paths above, or extend "
        "the candidates list in this function."
    )
