from __future__ import annotations

import copy
import importlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from codex_rescue import core

PROJECT = "10000000-0000-4000-8000-000000000001"
SERVER = "20000000-0000-4000-8000-000000000001"
THREAD = "30000000-0000-4000-8000-000000000001"


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "profile"
        self.home.mkdir()
        self.folder = self.base / "示例项目"
        self.folder.mkdir()
        self.rollout = self.home / "sessions" / "synthetic.jsonl"
        self.rollout.parent.mkdir()
        self.rollout.write_text('{"synthetic":true}\n', encoding="utf-8")
        self.backups = self.base / "backups"
        project = {"id": PROJECT, "name": "Synthetic project", "rootPaths": [str(self.folder)], "createdAt": 1, "updatedAt": 2}
        self.state = {
            core.SCOPE: {"owner": "current-owner", "inactive": {
                "previous-owner": {"atoms": {"keep-account-setting": True}, "globals": {
                    "local-projects": {PROJECT: project},
                    core.ID_MAP: {"local:" + str(self.home): {PROJECT: SERVER}},
                    "thread-project-assignments": {THREAD: {"projectKind": "local", "projectId": PROJECT}},
                }}
            }},
            "local-projects": {}, "unrelated-setting": {"keep": "unchanged"},
            "electron-persisted-atom-state": {"do-not-move": "current-account"},
        }
        self.write_state()
        (self.home / (core.STATE_NAME + ".bak")).write_bytes(b'{"distinct_backup":true}')
        connection = sqlite3.connect(self.home / core.DB_NAME)
        connection.executescript('''
            CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT,metadata TEXT,position INTEGER,created_at_ms INTEGER,updated_at_ms INTEGER);
            CREATE TABLE project_roots(project_id TEXT,position INTEGER,path TEXT);
            CREATE TABLE project_idempotency_keys(key TEXT,project_id TEXT);
            CREATE TABLE threads(id TEXT PRIMARY KEY,project_id TEXT,rollout_path TEXT);
        ''')
        connection.execute("INSERT INTO projects VALUES (?,?,?,?,?,?)", (SERVER, "Synthetic project", "{}", 0, 1, 2))
        connection.execute("INSERT INTO project_roots VALUES (?,?,?)", (SERVER, 0, str(self.folder)))
        connection.execute("INSERT INTO project_idempotency_keys VALUES (?,?)", (PROJECT, SERVER))
        connection.execute("INSERT INTO threads VALUES (?,?,?)", (THREAD, None, str(self.rollout)))
        connection.commit()
        connection.close()
        self.addCleanup(mock.patch.stopall)
        self.offline = mock.patch.object(core, "require_offline").start()
        self.supported = mock.patch.object(core, "require_supported_build").start()

    def write_state(self):
        (self.home / core.STATE_NAME).write_bytes(core.encode(self.state))

    def execute(self, query, args=()):
        c = sqlite3.connect(self.home / core.DB_NAME)
        c.execute(query, args)
        c.commit()
        c.close()

    def scan(self, scope="current", history=None):
        return core.scan(self.home, scope, history)

    def test_scan_is_read_only_and_restores_original_identity(self):
        before = (self.home / core.STATE_NAME).read_bytes()
        db_before = (self.home / core.DB_NAME).read_bytes()
        plan = self.scan()
        self.assertTrue(plan.actionable)
        self.assertEqual(plan.candidate["local-projects"][PROJECT]["id"], PROJECT)
        self.assertEqual(plan.accounts[0]["memberships_added"], 1)
        self.assertEqual((self.home / core.STATE_NAME).read_bytes(), before)
        self.assertEqual((self.home / core.DB_NAME).read_bytes(), db_before)
        self.assertEqual(plan.candidate[core.SCOPE], self.state[core.SCOPE])

    def test_all_accounts_dynamic_including_new_current_owner(self):
        self.state[core.SCOPE]["inactive"]["newly-saved-owner"] = {"atoms": {}, "globals": {}}
        self.state[core.SCOPE]["owner"] = "another-new-active-owner"
        self.write_state()
        plan = self.scan("all")
        self.assertEqual(len(plan.accounts), 3)
        for g in core.account_views(plan.candidate).values():
            self.assertIn(PROJECT, g["local-projects"])
        self.assertEqual(plan.candidate[core.SCOPE]["owner"], "another-new-active-owner")
        self.assertEqual(plan.candidate["electron-persisted-atom-state"], self.state["electron-persisted-atom-state"])

    def test_no_active_owner_all_scope_only_touches_saved_accounts(self):
        self.state[core.SCOPE]["owner"] = None
        self.write_state()
        with self.assertRaises(core.RecoveryError):
            self.scan()
        plan = self.scan("all")
        self.assertEqual(plan.candidate["local-projects"], {})

    def test_legacy_state_and_database_only_identity(self):
        self.state = {"local-projects": {}}
        self.write_state()
        self.execute("UPDATE threads SET project_id=?", (SERVER,))
        plan = self.scan()
        self.assertIn(PROJECT, plan.candidate["local-projects"])
        self.assertEqual(plan.accounts[0]["memberships_added"], 1)

    def test_ambiguous_idempotency_keys_are_not_guessed(self):
        self.state = {"local-projects": {}}
        self.write_state()
        self.execute("INSERT INTO project_idempotency_keys VALUES (?,?)", ("10000000-0000-4000-8000-000000000002", SERVER))
        plan = self.scan()
        self.assertFalse(plan.actionable)
        self.assertEqual(plan.skipped["ambiguous_projects"], 1)

    def test_cloud_linked_project_is_skipped_without_detaching(self):
        self.execute("UPDATE projects SET metadata=?", (json.dumps({"codex.chatGptBacking": "synthetic-reference"}),))
        plan = self.scan("all")
        self.assertEqual(plan.skipped["cloud_linked_projects"], 1)
        self.assertEqual(plan.candidate, self.state)

    def test_conflicting_metadata_identity_is_not_ignored(self):
        self.execute("UPDATE projects SET metadata=?", (json.dumps({"codex.localProjectId": "10000000-0000-4000-8000-000000000002"}),))
        plan = self.scan()
        self.assertFalse(plan.actionable)
        self.assertEqual(plan.skipped["ambiguous_projects"], 1)

    def test_conflicting_saved_mapping_cannot_fall_back_to_database_key(self):
        old = self.state[core.SCOPE]["inactive"]["previous-owner"]["globals"]
        old[core.ID_MAP]["local:" + str(self.home)][PROJECT] = "other-server"
        self.write_state()
        plan = self.scan()
        self.assertFalse(plan.actionable)
        self.assertEqual(plan.skipped["ambiguous_projects"], 1)

    def test_unknown_idempotency_key_does_not_create_a_new_desktop_identity(self):
        self.state = {"local-projects": {}}
        self.write_state()
        self.execute("UPDATE project_idempotency_keys SET key='unknown-format'")
        plan = self.scan()
        self.assertFalse(plan.actionable)

    def test_malformed_metadata_identity_is_rejected_without_changes(self):
        self.execute("UPDATE projects SET metadata=?", (json.dumps({"codex.localProjectId": ["unexpected"]}),))
        self.assertFalse(self.scan().actionable)

    def test_missing_root_is_reported_and_not_recreated(self):
        self.folder.rmdir()
        plan = self.scan()
        self.assertEqual(plan.skipped["missing_roots"], 1)
        self.assertFalse(self.folder.exists())
        self.assertFalse(plan.actionable)

    def test_missing_thread_assignment_not_copied(self):
        self.execute("DELETE FROM threads")
        plan = self.scan()
        self.assertEqual(plan.skipped["missing_threads"], 1)
        self.assertNotIn("thread-project-assignments", plan.candidate)

    def test_missing_rollout_and_compressed_rollout(self):
        self.rollout.unlink()
        self.assertEqual(self.scan().skipped["missing_rollouts"], 1)
        Path(str(self.rollout) + ".zst").write_bytes(b"synthetic-not-parsed")
        plan = self.scan()
        self.assertEqual(plan.accounts[0]["memberships_added"], 1)
        self.assertFalse(plan.public_report()["transcript_integrity_verified"])

    def test_projectless_target_preserved(self):
        self.state["projectless-thread-ids"] = [THREAD]
        self.write_state()
        plan = self.scan()
        self.assertNotIn("thread-project-assignments", plan.candidate)
        self.assertEqual(plan.skipped["preserved_memberships"], 1)

    def test_existing_conflicting_membership_preserved(self):
        old = {"projectKind": "local", "projectId": "different-project"}
        self.state["thread-project-assignments"] = {THREAD: old}
        self.write_state()
        self.assertEqual(self.scan().candidate["thread-project-assignments"][THREAD], old)

    def test_existing_duplicate_root_is_not_overwritten(self):
        self.state["local-projects"] = {"another-id": {"id": "another-id", "name": "newly-added", "rootPaths": [str(self.folder)]}}
        self.write_state()
        plan = self.scan()
        self.assertEqual(plan.candidate["local-projects"], self.state["local-projects"])
        self.assertEqual(plan.skipped["project_conflicts"], 1)

    def test_multiroot_preserves_order(self):
        another = self.base / "docs"
        another.mkdir()
        self.execute("INSERT INTO project_roots VALUES (?,?,?)", (SERVER, 1, str(another)))
        self.state[core.SCOPE]["inactive"]["previous-owner"]["globals"]["local-projects"][PROJECT]["rootPaths"].append(str(another))
        self.write_state()
        self.assertEqual(self.scan().candidate["local-projects"][PROJECT]["rootPaths"], [str(self.folder), str(another)])

    def test_historical_state_read_only(self):
        old = self.base / "old.json"
        old.write_bytes(core.encode(self.state))
        self.state[core.SCOPE]["inactive"] = {}
        self.write_state()
        old_before = old.read_bytes()
        self.assertEqual(self.scan(history=old).accounts[0]["memberships_added"], 1)
        self.assertEqual(old.read_bytes(), old_before)

    def test_no_folder_guess_for_unassigned_threads(self):
        self.state[core.SCOPE]["inactive"]["previous-owner"]["globals"].pop("thread-project-assignments")
        self.write_state()
        self.assertEqual(self.scan().accounts[0]["memberships_added"], 0)

    def test_duplicate_json_keys_and_invalid_schema_refused(self):
        (self.home / core.STATE_NAME).write_text('{"local-projects":{},"local-projects":{}}')
        with self.assertRaises(core.RecoveryError):
            self.scan()
        self.state["project-order"] = "bad"
        self.write_state()
        with self.assertRaises(core.RecoveryError):
            self.scan()

    def test_public_report_is_anonymous(self):
        report = json.dumps(self.scan().public_report(), ensure_ascii=False)
        for private in [PROJECT, SERVER, THREAD, "current-owner", "previous-owner", str(self.folder), "Synthetic project"]:
            self.assertNotIn(private, report)

    def test_apply_and_field_scoped_rollback_preserve_unrelated_changes(self):
        plan = self.scan("all")
        db_before = (self.home / core.DB_NAME).read_bytes()
        output = core.apply(plan, self.backups)
        self.assertEqual((output / "state.before.json").read_bytes(), plan.before)
        self.assertEqual(core.read_json(output / "manifest.json")[0]["status"], "applied_ui_not_verified")
        self.assertEqual((self.home / core.DB_NAME).read_bytes(), db_before)
        applied = core.read_json(self.home / core.STATE_NAME)[0]
        applied["new-unrelated-preference"] = 42
        (self.home / core.STATE_NAME).write_bytes(core.encode(applied))
        core.rollback(self.home, output, self.backups)
        restored = core.read_json(self.home / core.STATE_NAME)[0]
        expected = copy.deepcopy(self.state)
        expected["new-unrelated-preference"] = 42
        self.assertEqual(restored, expected)
        self.assertEqual((self.home / core.DB_NAME).read_bytes(), db_before)

    def test_rollback_refuses_later_membership_changes(self):
        output = core.apply(self.scan(), self.backups)
        applied = core.read_json(self.home / core.STATE_NAME)[0]
        applied["thread-project-assignments"]["later-thread"] = {"projectId": PROJECT, "projectKind": "local"}
        (self.home / core.STATE_NAME).write_bytes(core.encode(applied))
        with self.assertRaises(core.RecoveryError):
            core.rollback(self.home, output, self.backups)

    def test_stale_preview_refused_before_backup(self):
        plan = self.scan()
        self.state["new-setting"] = True
        self.write_state()
        with self.assertRaisesRegex(core.RecoveryError, "预览已过期"):
            core.apply(plan, self.backups)
        self.assertFalse(self.backups.exists())

    def test_stale_database_refused(self):
        plan = self.scan()
        self.execute("UPDATE threads SET project_id=?", (SERVER,))
        with self.assertRaisesRegex(core.RecoveryError, "预览已过期"):
            core.apply(plan, self.backups)

    def test_running_app_refused_before_backup(self):
        self.offline.side_effect = RuntimeError("still running")
        with self.assertRaisesRegex(RuntimeError, "still running"):
            core.apply(self.scan(), self.backups)
        self.assertFalse(self.backups.exists())

    def test_unknown_version_refused(self):
        self.supported.side_effect = RuntimeError("unknown build")
        with self.assertRaisesRegex(RuntimeError, "unknown build"):
            core.apply(self.scan(), self.backups)
        self.assertFalse(self.backups.exists())

    def test_write_failure_rolls_back(self):
        main, bak = self.home / core.STATE_NAME, self.home / (core.STATE_NAME + ".bak")
        original, oldbak = main.read_bytes(), bak.read_bytes()
        real, failed = core.atomic_bytes, [False]
        def fail_second(path, data):
            if path == bak and not failed[0]:
                failed[0] = True
                raise OSError("simulated second-file failure")
            return real(path, data)
        with mock.patch.object(core, "atomic_bytes", side_effect=fail_second):
            with self.assertRaises(OSError):
                core.install_pair(main, bak, b'{}', original, oldbak)
        self.assertEqual(main.read_bytes(), original)
        self.assertEqual(bak.read_bytes(), oldbak)

    def test_backups_inside_codex_home_refused(self):
        with self.assertRaises(core.RecoveryError):
            core.apply(self.scan(), self.home / "unsafe-backups")

    def test_idempotent_scan_after_success(self):
        core.apply(self.scan(), self.backups)
        self.assertFalse(self.scan().actionable)


if __name__ == "__main__":
    unittest.main(verbosity=2)
