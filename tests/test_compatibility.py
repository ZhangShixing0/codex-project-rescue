"""Compatibility gates using synthetic profiles and simulated OS discovery."""
from __future__ import annotations

import copy
import json
import unittest
from unittest import mock

import test_recovery as fixtures
from codex_rescue import core, platform, presentation


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RecoveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        # Exercise the real safety guards; only OS discovery is simulated.
        mock.patch.object(core, "require_offline", platform.require_offline).start()
        mock.patch.object(core, "require_supported_build", platform.require_supported_build).start()

    def test_reviewed_builds_allow_backup_apply_and_rollback_offline(self):
        f = self.fixture
        migration = {"local:" + str(f.home): {"version": 1, "projectsMigrated": True, "threadAssignmentsMigrated": True}}
        f.state["app-server-projects-migration-by-host"] = migration
        f.write_state()
        baseline = copy.deepcopy(f.state)
        database_before = (f.home / core.DB_NAME).read_bytes()
        for version in ("26.1103.4239.0", "26.1103.7773.0"):
            with self.subTest(version=version), mock.patch.object(platform, "installed_builds", return_value=[version]), mock.patch.object(platform, "running_processes", return_value=[]):
                self.assertEqual(presentation.build_status()["status"], "supported")
                plan = f.scan()
                self.assertTrue(presentation.preflight(plan, f.backups)["ready"])
                backup = core.apply(plan, f.backups)
                after = core.read_json(f.home / core.STATE_NAME)[0]
                self.assertEqual(after["local-projects"][fixtures.PROJECT]["id"], fixtures.PROJECT)
                self.assertEqual(after[core.ID_MAP]["local:" + str(f.home)][fixtures.PROJECT], fixtures.SERVER)
                self.assertEqual(after["thread-project-assignments"][fixtures.THREAD], {"projectId": fixtures.PROJECT, "projectKind": "local"})
                self.assertEqual(after[core.SCOPE], baseline[core.SCOPE])
                self.assertEqual(after["app-server-projects-migration-by-host"], migration)
                self.assertEqual(json.loads((backup / "state.before.json").read_text(encoding="utf-8")), baseline)
                core.rollback(f.home, backup, f.backups)
                self.assertEqual(core.read_json(f.home / core.STATE_NAME)[0], baseline)
                self.assertEqual((f.home / core.DB_NAME).read_bytes(), database_before)

    def test_new_build_still_blocks_writes_while_codex_is_running(self):
        f = self.fixture
        before = (f.home / core.STATE_NAME).read_bytes()
        with mock.patch.object(platform, "installed_builds", return_value=["26.1103.7773.0"]), mock.patch.object(platform, "running_processes", return_value=[{"Id": 123, "ProcessName": "codex"}]):
            plan = f.scan()
            self.assertFalse(presentation.preflight(plan, f.backups)["ready"])
            with self.assertRaisesRegex(platform.EnvironmentError, "仍在运行"):
                core.apply(plan, f.backups)
        self.assertEqual((f.home / core.STATE_NAME).read_bytes(), before)
        self.assertEqual(list(f.backups.iterdir()), [])

    def test_unknown_builds_use_schema_compatibility_and_multiple_installs_block(self):
        f = self.fixture
        with mock.patch.object(platform, "installed_builds", return_value=[]), mock.patch.object(platform, "running_processes", return_value=[]):
            plan = f.scan()
            self.assertTrue(plan.actionable)
            self.assertEqual(presentation.build_status_for_home(f.home)["status"], "schema-compatible")
            backup = core.apply(plan, f.backups)
            self.assertTrue((f.home / core.STATE_NAME).read_bytes() != plan.before)
            core.rollback(f.home, backup, f.backups)

        before = (f.home / core.STATE_NAME).read_bytes()
        with mock.patch.object(platform, "installed_builds", return_value=["26.1103.7773.0", "26.1103.4239.0"]), mock.patch.object(platform, "running_processes", return_value=[]):
            plan = f.scan()
            self.assertEqual(presentation.build_status_for_home(f.home)["status"], "unsupported")
            with self.assertRaisesRegex(platform.EnvironmentError, "多个 Codex"):
                core.apply(plan, f.backups)
        self.assertEqual((f.home / core.STATE_NAME).read_bytes(), before)

    def test_discovery_failure_does_not_enable_new_build_writes(self):
        f = self.fixture
        with mock.patch.object(platform, "installed_builds", side_effect=platform.EnvironmentError("discovery failed")), mock.patch.object(platform, "running_processes", return_value=[]):
            self.assertEqual(presentation.build_status()["status"], "unknown")
            with self.assertRaises(platform.EnvironmentError):
                core.apply(f.scan(), f.backups)
        self.assertFalse(f.backups.exists())

    def test_unknown_build_with_damaged_schema_remains_scan_only(self):
        f = self.fixture
        plan = f.scan()
        (f.home / core.DB_NAME).unlink()
        with mock.patch.object(platform, "installed_builds", return_value=["99.0.0.0"]), mock.patch.object(platform, "running_processes", return_value=[]):
            self.assertEqual(presentation.build_status_for_home(f.home)["status"], "unsupported")
            with self.assertRaisesRegex(platform.EnvironmentError, "结构"):
                core.apply(plan, f.backups)
        self.assertFalse(f.backups.exists())


if __name__ == "__main__":
    unittest.main()
