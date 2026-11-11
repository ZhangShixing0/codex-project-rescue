"""Local view models, preflight checks and anonymous failure diagnostics."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, platform
from .core import ID_MAP, RecoveryError, account_views, normalized_roots, read_json, scan

PROJECT_STATUS = {
    "added": "将补回", "repaired": "补齐关联", "unchanged": "已有，保留",
    "project_conflicts": "跳过：目标账号有冲突", "cloud_linked_projects": "跳过：带云端关联",
    "ambiguous_projects": "跳过：身份不明确", "missing_roots": "跳过：目录不可用",
}


def project_overview(plan):
    before = account_views(json.loads(plan.before.decode("utf-8-sig")))
    after = account_views(plan.candidate)
    rows = []
    for account in plan.accounts:
        old, new = before[account["owner"]], after[account["owner"]]
        old_registry, new_registry = old.get("local-projects", {}), new.get("local-projects", {})
        old_members, new_members = old.get("thread-project-assignments", {}), new.get("thread-project-assignments", {})
        for project in plan.projects:
            pid = project["id"]
            new_record = new_registry.get(pid)
            conflict = (new_record is None or normalized_roots(new_record.get("rootPaths", [])) != normalized_roots(project["rootPaths"])
                        or any(issue.get("owner") == account["owner"] and issue["id"] == pid for issue in plan.project_issues))
            # The planner skips a target with a conflicting explicit server mapping.
            relevant_maps = [c for c in plan.changes if c["owner"] == account["owner"] and c["field"] == ID_MAP]
            mapping_changed = any(any(values.get(pid) != (old.get(ID_MAP, {}).get(host, {}).get(pid))
                                      for host, values in c["after"].items()) for c in relevant_maps)
            new_tids = {tid for tid, value in new_members.items() if value.get("projectId") == pid and tid not in old_members}
            repaired_hosts = any(value.get("projectId") == pid and new.get("thread-project-membership-host-ids", {}).get(tid) != old.get("thread-project-membership-host-ids", {}).get(tid)
                                 for tid, value in new_members.items())
            order_added = old.get("project-order", []).count(pid) != new.get("project-order", []).count(pid)
            added = not conflict and pid not in old_registry
            repaired = not conflict and not added and (mapping_changed or order_added or bool(new_tids) or repaired_hosts)
            status = "project_conflicts" if conflict else "added" if added else "repaired" if repaired else "unchanged"
            rows.append({"id": pid, "name": project["name"], "roots": project["rootPaths"],
                         "account": account["label"], "status": status, "memberships_added": len(new_tids) if not conflict else 0})
    for issue in plan.project_issues:
        if "owner" in issue:
            continue
        rows.append({"id": issue["id"], "name": issue["name"], "roots": issue["rootPaths"],
                     "account": "所选范围", "status": issue["reason"], "memberships_added": 0})
    priority = {"added": 0, "repaired": 1, "unchanged": 2}
    rows.sort(key=lambda row: (priority.get(row["status"], 3), row["name"], row["account"]))
    return {
        "rows": rows, "added_entries": sum(r["status"] == "added" for r in rows),
        "repaired_entries": sum(r["status"] == "repaired" for r in rows),
        "memberships_added": sum(r["memberships_added"] for r in rows),
        "existing_entries": sum(r["status"] == "unchanged" for r in rows),
        "skipped_entries": sum(r["status"] not in priority for r in rows),
        "account_count": len(plan.accounts), "saved_account_count": len(before),
    }


def build_status():
    return _build_status(None)


def _build_status(home):
    try:
        versions = platform.installed_builds()
        if len(versions) > 1:
            return {"status": "unsupported", "versions": versions, "detail": "检测到多个 Codex 安装版本。"}
        if len(versions) == 1 and versions[0] in platform.SUPPORTED_BUILDS:
            return {"status": "supported", "versions": versions, "detail": "已知版本；仍会复核本地结构。"}
        if home is not None:
            compatible, detail = platform.schema_probe(home)
            if compatible:
                return {"status": "schema-compatible", "versions": versions,
                        "detail": "版本号未列入清单，但本地状态结构通过兼容检查。"}
            return {"status": "unsupported", "versions": versions, "detail": detail}
        return {"status": "unsupported", "versions": versions, "detail": "需要读取本地状态结构后判断。"}
    except Exception:
        return {"status": "unknown", "versions": [], "detail": "无法核实本机版本；仍可只读扫描。"}


def build_status_for_home(home):
    return _build_status(home)


def preflight(plan, backup_root):
    result = {"build": build_status_for_home(plan.home), "process": "unknown", "backup": "unchecked", "preview": "unchecked", "ready": False}
    try:
        result["process"] = "running" if platform.running_processes() else "closed"
    except Exception:
        result["process"] = "unknown"
    try:
        root = backup_root.expanduser().resolve()
        if root == plan.home or root.is_relative_to(plan.home):
            raise RecoveryError("备份位置必须位于 Codex 数据目录之外。")
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=root) as probe:
            probe.write(b"backup-location-probe")
            probe.flush()
        result["backup"] = "available"
    except Exception:
        result["backup"] = "unavailable"
    if platform.can_write_status(result["build"]["status"]) and result["process"] == "closed":
        fresh = scan(plan.home, plan.scope, plan.extra_path)
        result["preview"] = "fresh" if fresh.input_signature == plan.input_signature and fresh.candidate == plan.candidate else "stale"
    result["ready"] = platform.can_write_status(result["build"]["status"]) and result["process"] == "closed" and result["backup"] == "available" and result["preview"] == "fresh" and plan.actionable
    return result


def failure_code(error):
    text = str(error)
    for needles, code in [(("预览已过期", "状态在检查后发生变化", "数据库在备份后发生变化"), "preview_changed"),
                          (("仍在运行",), "app_running"), (("当前应用版本尚未验证",), "unsupported_build"),
                          (("项目字段已经变化",), "rollback_conflict"), (("当前没有活动账号",), "no_active_account"),
                          (("无法读取状态 JSON",), "state_unavailable"), (("数据库不存在", "数据库完整性"), "database_unavailable")]:
        if any(needle in text for needle in needles):
            return code
    return "file_access" if isinstance(error, OSError) else "operation_failed"


def failure_report(stage, error, plan=None):
    stage = stage if stage in {"scan", "prepare", "apply", "rollback", "backups"} else "unknown"
    report = {"tool_version": __version__, "status": "failed", "stage": stage,
              "reason": failure_code(error), "live_state_written": None if stage in {"apply", "rollback", "unknown"} else False,
              "ui_recovery_verified": False}
    if plan is not None:
        report["preview"] = plan.public_report()
    return report


def list_backups(home: Path, root: Path):
    home, root = home.expanduser().resolve(), root.expanduser().resolve()
    if not root.exists():
        return []
    results = []
    for path in root.iterdir():
        if not path.is_dir() or path.is_symlink() or not (path / "manifest.json").is_file():
            continue
        try:
            manifest, _ = read_json(path / "manifest.json")
            if manifest.get("schema") != 1 or manifest.get("status") not in {"prepared", "applied_ui_not_verified"} or Path(manifest.get("home", "")).resolve() != home:
                continue
            changes = manifest["changes"]
            if not isinstance(changes, list) or not all(isinstance(c, dict) for c in changes):
                continue
            counts = {"projects_added": 0, "memberships_added": 0}
            for change in changes:
                if change.get("field") in {"local-projects", "thread-project-assignments"}:
                    old = change.get("before") or {}
                    new = change["after"]
                    if not isinstance(old, dict) or not isinstance(new, dict):
                        raise ValueError("Invalid backup summary")
                    key = "projects_added" if change["field"] == "local-projects" else "memberships_added"
                    counts[key] += len(set(new) - set(old))
            stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            results.append({"path": path, "time": stamp, "accounts": len({c["owner"] for c in changes}), "status": manifest["status"], **counts})
        except (OSError, ValueError, KeyError, TypeError, RecoveryError):
            continue
    return sorted(results, key=lambda entry: entry["time"], reverse=True)
