from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

import test_recovery as fixtures
from codex_rescue import core, presentation


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RecoveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_existing_projects_are_not_presented_as_new_projects(self):
        f = self.fixture
        core.apply(f.scan(), f.backups)
        view = presentation.project_overview(f.scan())
        self.assertEqual(view["added_entries"], 0)

    def test_conflicting_target_is_not_advertised_as_recoverable(self):
        f = self.fixture
        f.state["local-projects"] = {"other-id": {"id": "other-id", "name": "Existing", "rootPaths": [str(f.folder)]}}
        f.write_state()
        view = presentation.project_overview(f.scan())
        self.assertEqual(view["added_entries"], 0)

    def test_project_preview_is_specific_to_each_target_account(self):
        f = self.fixture
        view = presentation.project_overview(f.scan("all"))
        self.assertEqual(view["added_entries"], 1)
        self.assertEqual(view["memberships_added"], 1)
        current = next(r for r in view["rows"] if r["account"] == "当前账号")
        saved = next(r for r in view["rows"] if r["account"] != "当前账号")
        self.assertEqual((current["status"], current["memberships_added"]), ("added", 1))
        self.assertEqual((saved["status"], saved["memberships_added"]), ("repaired", 0))

    def test_duplicate_target_directory_is_shown_as_conflict_not_complete(self):
        f = self.fixture
        project = copy.deepcopy(f.state[core.SCOPE]["inactive"]["previous-owner"]["globals"]["local-projects"][fixtures.PROJECT])
        f.state["local-projects"] = {fixtures.PROJECT: project, "other-id": {**project, "id": "other-id"}}
        f.write_state()
        view = presentation.project_overview(f.scan())
        self.assertEqual(len(view["rows"]), 1)
        self.assertEqual(view["rows"][0]["status"], "project_conflicts")
        self.assertEqual(view["existing_entries"], 0)

    def test_explicit_projectless_chat_is_not_advertised_as_new_membership(self):
        f = self.fixture
        f.state["projectless-thread-ids"] = [fixtures.THREAD]
        f.write_state()
        self.assertEqual(presentation.project_overview(f.scan())["memberships_added"], 0)

    def test_cloud_project_has_local_skip_details_but_no_private_export(self):
        f = self.fixture
        f.execute("UPDATE projects SET metadata=?", (json.dumps({"codex.chatGptBacking": "private-link"}),))
        plan = f.scan()
        view = presentation.project_overview(plan)
        self.assertEqual(view["rows"][0]["status"], "cloud_linked_projects")
        self.assertEqual(view["rows"][0]["name"], "Synthetic project")
        self.assertNotIn("Synthetic project", json.dumps(plan.public_report()))

    def test_failure_report_is_shareable_even_when_no_plan_exists(self):
        report = presentation.failure_report("scan", OSError("private-user and secret path D:/private/chat.jsonl"))
        encoded = json.dumps(report)
        self.assertNotIn("private", encoded)
        self.assertNotIn("chat.jsonl", encoded)
        self.assertFalse(report["live_state_written"])

    def test_write_failure_does_not_claim_that_nothing_was_written(self):
        report = presentation.failure_report("apply", OSError("write interrupted"))
        self.assertIsNone(report["live_state_written"])
        self.assertFalse(report["ui_recovery_verified"])

    def test_preflight_blocks_running_app_without_writing_profile(self):
        from codex_rescue import platform
        f = self.fixture
        plan = f.scan()
        before = (f.home / core.STATE_NAME).read_bytes()
        with mock.patch.object(platform, "installed_builds", return_value=["26.1103.4239.0"]), mock.patch.object(platform, "running_processes", return_value=[{"Id": 99, "ProcessName": "codex"}]):
            result = presentation.preflight(plan, f.backups)
        self.assertFalse(result["ready"])
        self.assertEqual(result["process"], "running")
        self.assertEqual((f.home / core.STATE_NAME).read_bytes(), before)

    def test_preflight_cannot_approve_an_expired_preview(self):
        from codex_rescue import platform
        f = self.fixture
        plan = f.scan()
        f.state["later-setting"] = True
        f.write_state()
        with mock.patch.object(platform, "installed_builds", return_value=["26.1103.4239.0"]), mock.patch.object(platform, "running_processes", return_value=[]):
            result = presentation.preflight(plan, f.backups)
        self.assertFalse(result["ready"])
        self.assertEqual(result["preview"], "stale")

    def test_unknown_version_is_diagnosed_before_offline_requirement(self):
        from codex_rescue import platform
        with mock.patch.object(platform, "installed_builds", return_value=["99.0.0.0"]):
            status = presentation.build_status()
        self.assertEqual(status["status"], "unsupported")

    def test_preflight_rejects_backup_directory_inside_profile(self):
        from codex_rescue import platform
        f = self.fixture
        with mock.patch.object(platform, "installed_builds", return_value=["26.1103.4239.0"]), mock.patch.object(platform, "running_processes", return_value=[]):
            result = presentation.preflight(f.scan(), f.home / "backup")
        self.assertFalse(result["ready"])
        self.assertEqual(result["backup"], "unavailable")
        self.assertFalse((f.home / "backup").exists())

    def test_recent_backups_only_include_matching_profile(self):
        f = self.fixture
        own = core.apply(f.scan(), f.backups)
        other = f.backups / "unrelated-backup"
        other.mkdir()
        manifest = core.read_json(own / "manifest.json")[0]
        manifest["home"] = str(f.base / "another-profile")
        (other / "manifest.json").write_bytes(core.encode(manifest))
        listing = presentation.list_backups(f.home, f.backups)
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["path"], own)
        self.assertEqual(listing[0]["projects_added"], 1)
        self.assertEqual(listing[0]["accounts"], 1)


if __name__ == "__main__":
    unittest.main()
