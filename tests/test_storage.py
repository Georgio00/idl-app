"""
Regression tests for db/storage.py.

2026-09-07: added as part of making this a real company tool -- until now
the database layer (the only place saved IDL records actually live) had
ZERO automated test coverage; every one of this project's ~200 existing
tests exercises the OCR pipeline exclusively. These tests use a temporary
db/key path per test (never the real %LOCALAPPDATA%\\IDL_APP\\ location)
so they can't ever touch or corrupt a real machine's saved records.

Covers update_record specifically (new this same day, for the Records
screen's Open-then-Save-again flow) since a bug there would silently
either corrupt a real record or create an untracked duplicate -- exactly
the failure mode the Records screen was built to eliminate.

Also covers the 2026-09-19 staff_users table (StaffUsersTest) added for
the login system (see gui/login_dialog.py) -- the whole point of
requiring login at all was so gui/new_idl_form.py's Receipt.User field
could stop being something anyone could type any name into, so the two
properties that matter most here are the ones a bug would silently
undermine: a wrong password must never verify, and one account's
password change/deletion must never affect another's.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.storage import Storage


def _make_storage(tmp_dir: Path) -> Storage:
    return Storage(db_path=tmp_dir / "test.db", key_path=tmp_dir / "test.key")


class SaveAndGetRecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.storage = _make_storage(self.tmp_dir)

    def test_saved_record_round_trips_exactly(self):
        fields = {"Surname": "EL ALAM", "First Name": "GEORGES"}
        record_id = self.storage.save_record(fields)
        record = self.storage.get_record(record_id)
        self.assertEqual(record.fields, fields)

    def test_unknown_id_returns_none(self):
        self.assertIsNone(self.storage.get_record(999))

    def test_records_are_encrypted_at_rest(self):
        # The whole point of Fernet-encrypting each record (see the module
        # docstring): the raw .db file must never contain a saved name in
        # plain, greppable text.
        record_id = self.storage.save_record({"Surname": "VERYDISTINCTIVESURNAME"})
        self.assertIsNotNone(record_id)
        raw_bytes = (self.tmp_dir / "test.db").read_bytes()
        self.assertNotIn(b"VERYDISTINCTIVESURNAME", raw_bytes)

    def test_next_issued_document_number_increments(self):
        first = self.storage.next_issued_document_number()
        second = self.storage.next_issued_document_number()
        self.assertNotEqual(first, second)


class ListRecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.storage = _make_storage(self.tmp_dir)

    def test_lists_newest_first(self):
        first_id = self.storage.save_record({"Surname": "FIRST"})
        second_id = self.storage.save_record({"Surname": "SECOND"})
        records = self.storage.list_records()
        self.assertEqual([r.id for r in records], [second_id, first_id])

    def test_empty_database_returns_empty_list(self):
        self.assertEqual(self.storage.list_records(), [])


class UpdateRecordTest(unittest.TestCase):
    """2026-09-07: the Records screen's core safety property -- re-saving
    an opened record must correct that same row, never create a second
    one (the exact bug this whole feature exists to fix, see
    gui/new_idl_form.py's save_record docstring)."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.storage = _make_storage(self.tmp_dir)

    def test_update_changes_the_same_row_not_a_new_one(self):
        record_id = self.storage.save_record({"Surname": "ELALAM"})
        self.storage.update_record(record_id, {"Surname": "EL ALAM"})

        records = self.storage.list_records()
        self.assertEqual(len(records), 1, "update_record must not create a second row")
        self.assertEqual(records[0].id, record_id)
        self.assertEqual(records[0].fields["Surname"], "EL ALAM")

    def test_update_unknown_id_raises_rather_than_silently_no_opping(self):
        with self.assertRaises(ValueError):
            self.storage.update_record(999, {"Surname": "GHOST"})

    def test_update_preserves_created_at(self):
        record_id = self.storage.save_record({"Surname": "ELALAM"})
        original_created_at = self.storage.get_record(record_id).created_at
        self.storage.update_record(record_id, {"Surname": "EL ALAM"})
        self.assertEqual(self.storage.get_record(record_id).created_at, original_created_at)


class StaffUsersTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.storage = _make_storage(self.tmp_dir)

    def test_user_count_starts_at_zero(self):
        self.assertEqual(self.storage.user_count(), 0)

    def test_create_user_increments_the_count(self):
        self.storage.create_user("ROULA", "hunter2")
        self.assertEqual(self.storage.user_count(), 1)

    def test_correct_password_verifies(self):
        self.storage.create_user("ROULA", "hunter2")
        self.assertTrue(self.storage.verify_user("ROULA", "hunter2"))

    def test_wrong_password_does_not_verify(self):
        self.storage.create_user("ROULA", "hunter2")
        self.assertFalse(self.storage.verify_user("ROULA", "wrong-password"))

    def test_unknown_username_does_not_verify(self):
        self.assertFalse(self.storage.verify_user("NOBODY", "anything"))

    def test_username_lookup_is_case_insensitive(self):
        self.storage.create_user("ROULA", "hunter2")
        self.assertTrue(self.storage.verify_user("roula", "hunter2"))
        self.assertTrue(self.storage.verify_user("Roula", "hunter2"))

    def test_password_is_never_stored_in_plain_text(self):
        # The whole point of hashing (see _hash_password) -- a stolen .db
        # file must not contain the real password anywhere, recoverable
        # or not.
        self.storage.create_user("ROULA", "VERYDISTINCTIVEPASSWORD")
        raw_bytes = (self.tmp_dir / "test.db").read_bytes()
        self.assertNotIn(b"VERYDISTINCTIVEPASSWORD", raw_bytes)

    def test_two_accounts_with_the_same_password_get_different_hashes(self):
        # Confirms a fresh random salt is really used per account (see
        # _hash_password) -- if it weren't, two staff who happened to
        # pick the same password would have identical stored hashes,
        # which leaks that fact to anyone with DB access.
        self.storage.create_user("ROULA", "samepassword")
        self.storage.create_user("OJEIL", "samepassword")
        cur = self.storage._conn.execute("SELECT username, password_hash FROM staff_users ORDER BY username")
        hashes = dict(cur.fetchall())
        self.assertNotEqual(hashes["OJEIL"], hashes["ROULA"])

    def test_duplicate_username_raises(self):
        self.storage.create_user("ROULA", "hunter2")
        with self.assertRaises(ValueError):
            self.storage.create_user("ROULA", "different-password")

    def test_duplicate_username_raises_case_insensitively(self):
        self.storage.create_user("ROULA", "hunter2")
        with self.assertRaises(ValueError):
            self.storage.create_user("roula", "different-password")

    def test_blank_username_raises(self):
        with self.assertRaises(ValueError):
            self.storage.create_user("   ", "hunter2")

    def test_blank_password_raises(self):
        with self.assertRaises(ValueError):
            self.storage.create_user("ROULA", "")

    def test_list_usernames_returns_every_account_alphabetically(self):
        self.storage.create_user("ROULA", "pw1")
        self.storage.create_user("ASSISTANT", "pw2")
        self.assertEqual(self.storage.list_usernames(), ["ASSISTANT", "ROULA"])

    def test_change_password_takes_effect_immediately(self):
        self.storage.create_user("ROULA", "old-password")
        self.storage.change_password("ROULA", "new-password")
        self.assertFalse(self.storage.verify_user("ROULA", "old-password"))
        self.assertTrue(self.storage.verify_user("ROULA", "new-password"))

    def test_change_password_for_unknown_user_raises(self):
        with self.assertRaises(ValueError):
            self.storage.change_password("NOBODY", "new-password")

    def test_changing_one_account_does_not_affect_another(self):
        self.storage.create_user("ROULA", "roula-password")
        self.storage.create_user("OJEIL", "ojeil-password")
        self.storage.change_password("ROULA", "roula-new-password")
        self.assertTrue(self.storage.verify_user("OJEIL", "ojeil-password"))

    def test_delete_user_removes_the_account(self):
        self.storage.create_user("ROULA", "hunter2")
        self.storage.delete_user("ROULA")
        self.assertEqual(self.storage.user_count(), 0)
        self.assertFalse(self.storage.verify_user("ROULA", "hunter2"))

    def test_delete_unknown_user_raises(self):
        with self.assertRaises(ValueError):
            self.storage.delete_user("NOBODY")

    def test_deleting_one_account_does_not_affect_another(self):
        self.storage.create_user("ROULA", "roula-password")
        self.storage.create_user("OJEIL", "ojeil-password")
        self.storage.delete_user("ROULA")
        self.assertTrue(self.storage.verify_user("OJEIL", "ojeil-password"))


class AdminFlagTest(unittest.TestCase):
    """Regression coverage for the 2026-09-19 is_admin column (see this
    module's own docstring and gui/manage_users_dialog.py) -- added after
    Georgio asked who should be able to open "Manage Staff Accounts...".
    The two properties that matter most: a brand new account is NOT an
    admin unless asked for explicitly, and the last remaining admin can
    never be demoted or deleted (which would lock the app out of ever
    managing staff again)."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.storage = _make_storage(self.tmp_dir)

    def test_create_user_defaults_to_not_admin(self):
        self.storage.create_user("ROULA", "hunter2")
        self.assertFalse(self.storage.is_admin("ROULA"))

    def test_create_user_can_be_made_an_admin_directly(self):
        self.storage.create_user("ROULA", "hunter2", is_admin=True)
        self.assertTrue(self.storage.is_admin("ROULA"))

    def test_is_admin_is_false_for_an_unknown_username(self):
        self.assertFalse(self.storage.is_admin("NOBODY"))

    def test_is_admin_lookup_is_case_insensitive(self):
        self.storage.create_user("ROULA", "hunter2", is_admin=True)
        self.assertTrue(self.storage.is_admin("roula"))

    def test_admin_count_reflects_only_admin_accounts(self):
        self.storage.create_user("ROULA", "pw1", is_admin=True)
        self.storage.create_user("OJEIL", "pw2", is_admin=False)
        self.assertEqual(self.storage.admin_count(), 1)

    def test_list_users_pairs_each_username_with_its_admin_flag(self):
        self.storage.create_user("ROULA", "pw1", is_admin=True)
        self.storage.create_user("OJEIL", "pw2", is_admin=False)
        self.assertEqual(self.storage.list_users(), [("OJEIL", False), ("ROULA", True)])

    def test_set_admin_grants_access(self):
        self.storage.create_user("ROULA", "hunter2")
        self.storage.set_admin("ROULA", True)
        self.assertTrue(self.storage.is_admin("ROULA"))

    def test_set_admin_can_revoke_when_another_admin_remains(self):
        self.storage.create_user("ROULA", "pw1", is_admin=True)
        self.storage.create_user("OJEIL", "pw2", is_admin=True)
        self.storage.set_admin("ROULA", False)
        self.assertFalse(self.storage.is_admin("ROULA"))
        self.assertTrue(self.storage.is_admin("OJEIL"))

    def test_set_admin_refuses_to_demote_the_last_remaining_admin(self):
        self.storage.create_user("ROULA", "hunter2", is_admin=True)
        with self.assertRaises(ValueError):
            self.storage.set_admin("ROULA", False)
        self.assertTrue(self.storage.is_admin("ROULA"))  # unchanged

    def test_set_admin_for_unknown_user_raises(self):
        with self.assertRaises(ValueError):
            self.storage.set_admin("NOBODY", True)

    def test_delete_user_refuses_to_remove_the_last_remaining_admin(self):
        self.storage.create_user("ROULA", "hunter2", is_admin=True)
        with self.assertRaises(ValueError):
            self.storage.delete_user("ROULA")
        self.assertEqual(self.storage.user_count(), 1)  # NOT removed

    def test_delete_user_can_remove_an_admin_when_another_remains(self):
        self.storage.create_user("ROULA", "pw1", is_admin=True)
        self.storage.create_user("OJEIL", "pw2", is_admin=True)
        self.storage.delete_user("ROULA")
        self.assertEqual(self.storage.user_count(), 1)

    def test_delete_user_freely_removes_a_non_admin_account(self):
        # The last-remaining-admin guard must never block deleting an
        # ordinary (non-admin) account, even when it's the only account
        # of any kind on the machine.
        self.storage.create_user("OJEIL", "pw2", is_admin=False)
        self.storage.delete_user("OJEIL")
        self.assertEqual(self.storage.user_count(), 0)


class AdminMigrationTest(unittest.TestCase):
    """Regression coverage for _init_schema's is_admin migration (see its
    own comment) -- a real, immediate concern: Georgio's own machine
    already had one account created (via LoginDialog's bootstrap mode)
    from BEFORE the is_admin column existed at all, and re-opening that
    same database file must not error out, nor leave that account
    permanently unable to reach "Manage Staff Accounts...". Simulates
    that exact situation by creating a staff_users table the OLD way
    (no is_admin column) directly, then constructing Storage() against
    that same file, same as reopening the app for real would."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.tmp_dir / "test.db"
        self.key_path = self.tmp_dir / "test.key"

    def _create_pre_migration_table_with_one_account(self):
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """CREATE TABLE staff_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            "INSERT INTO staff_users (username, password_hash, password_salt, created_at) "
            "VALUES ('ROULA', 'fakehash', 'fakesalt', '2026-09-19T00:00:00')"
        )
        conn.commit()
        conn.close()

    def test_reopening_an_old_database_does_not_error(self):
        self._create_pre_migration_table_with_one_account()
        Storage(db_path=self.db_path, key_path=self.key_path)  # must not raise

    def test_the_sole_pre_existing_account_is_promoted_to_admin(self):
        self._create_pre_migration_table_with_one_account()
        storage = Storage(db_path=self.db_path, key_path=self.key_path)
        self.assertTrue(storage.is_admin("ROULA"))

    def test_a_fresh_database_is_unaffected_by_the_migration_path(self):
        # No pre-existing table at all -- _init_schema's plain CREATE
        # TABLE IF NOT EXISTS path should be the one that runs, and a
        # newly created account should NOT be auto-promoted just because
        # it happens to be the only one (that's create_user's is_admin
        # parameter's job, not the migration's).
        storage = _make_storage(self.tmp_dir)
        storage.create_user("ROULA", "hunter2")
        self.assertFalse(storage.is_admin("ROULA"))


if __name__ == "__main__":
    unittest.main()
