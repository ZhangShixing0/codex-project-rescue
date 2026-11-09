"""Recovery planning from existing identities; no authentication or network access."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .platform import require_offline, require_supported_build

SCOPE = "electron-account-renderer-state-v1"
ID_MAP = "app-server-project-id-by-legacy-project-id-by-host"
STATE_NAME = ".codex-global-state.json"
DB_NAME = "state_5.sqlite"
FIELDS = ("local-projects", ID_MAP, "project-order", "thread-project-assignments", "thread-project-membership-host-ids")
CLOUD_KEYS = ("chatGptBacking", "retiredChatGptBacking", "chatGptBackingCreation", "chatGptBackingRecoveryPending")
MAX_JSON_BYTES = 64 * 1024 * 1024


class RecoveryError(RuntimeError):
    pass


def encode(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def semantic_hash(value: Any) -> str:
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def read_json(path: Path) -> tuple[dict, bytes]:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise RecoveryError("状态文件过大，需要单独检查。")
        raw = path.read_bytes()
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise RecoveryError("JSON 存在重复字段，不能安全合并。")
                result[key] = value
            return result
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("无法读取状态 JSON。保留原文件，选择有效的历史状态文件辅助诊断。") from exc
    if not isinstance(value, dict):
        raise RecoveryError("状态 JSON 顶层必须是对象。")
    return value, raw


def account_views(state: dict) -> dict[str, dict]:
    if SCOPE not in state:
        return {"legacy": state}
    scoped = state[SCOPE]
    if not isinstance(scoped, dict) or not isinstance(scoped.get("inactive"), dict):
        raise RecoveryError("未知账号状态格式，仅能人工诊断。")
    owner = scoped.get("owner")
    if owner is not None and (not isinstance(owner, str) or not owner):
        raise RecoveryError("当前账号标识无效。")
    accounts = {owner: state} if owner is not None else {}
    for key, value in scoped["inactive"].items():
        if not isinstance(key, str) or not key or key in accounts or not isinstance(value, dict) or not isinstance(value.get("globals"), dict):
            raise RecoveryError("已保存账号状态格式无效。")
        accounts[key] = value["globals"]
    if not accounts:
        raise RecoveryError("没有已保存账号，无法确定恢复目标。")
    return accounts


def validate_globals(globals_state: dict):
    for key in FIELDS:
        expected = list if key == "project-order" else dict
        if key in globals_state and not isinstance(globals_state[key], expected):
            raise RecoveryError("项目状态字段类型不兼容：" + key)
    for pid, project in globals_state.get("local-projects", {}).items():
        if not isinstance(project, dict) or project.get("id") != pid:
            raise RecoveryError("项目标识格式不兼容。")
        if not isinstance(project.get("name"), str) or not isinstance(project.get("rootPaths"), list):
            raise RecoveryError("项目名称或根目录格式不兼容。")
        if not project["rootPaths"] or not all(isinstance(p, str) and p for p in project["rootPaths"]):
            raise RecoveryError("项目根目录缺失。")
    for values in globals_state.get(ID_MAP, {}).values():
        if not isinstance(values, dict) or not all(isinstance(v, str) for v in values.values()):
            raise RecoveryError("项目 ID 映射格式不兼容。")
    if not all(isinstance(v, str) for v in globals_state.get("project-order", [])):
        raise RecoveryError("项目排序格式不兼容。")
    for value in globals_state.get("thread-project-assignments", {}).values():
        if not isinstance(value, dict) or not isinstance(value.get("projectId"), str):
            raise RecoveryError("聊天归属格式不兼容。")
    if not all(isinstance(v, str) for v in globals_state.get("thread-project-membership-host-ids", {}).values()):
        raise RecoveryError("聊天主机格式不兼容。")
    if not isinstance(globals_state.get("projectless-thread-ids", []), list) or not all(isinstance(v, str) for v in globals_state.get("projectless-thread-ids", [])):
        raise RecoveryError("无项目聊天标记格式不兼容。")
    if not isinstance(globals_state.get("thread-projectless-output-directories", {}), dict):
        raise RecoveryError("无项目输出标记格式不兼容。")


def database_snapshot(path: Path) -> dict:
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            if [r[0] for r in connection.execute("PRAGMA quick_check")] != ["ok"]:
                raise RecoveryError("数据库完整性检查失败；不进行写入。")
            result = {}
            for table, columns in {
                "projects": "id,name,metadata,position,created_at_ms,updated_at_ms",
                "project_roots": "project_id,position,path",
                "project_idempotency_keys": "key,project_id",
                "threads": "id,project_id,rollout_path",
            }.items():
                result[table] = [dict(r) for r in connection.execute(f"SELECT {columns} FROM {table} ORDER BY 1,2")]
            return result
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise RecoveryError("数据库不存在、被占用或格式不受支持；没有写入。") from exc


def normalized_roots(roots: list[str]) -> tuple[str, ...]:
    return tuple(os.path.normcase(os.path.normpath(p)) for p in roots)


def uuid_like(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


@dataclass
class Plan:
    home: Path
    scope: str
    before: bytes
    backup_before: bytes | None
    candidate: dict
    db_fingerprint: str
    extra_path: Path | None
    extra_hash: str | None
    accounts: list[dict]
    projects: list[dict]
    notices: list[str]
    skipped: dict[str, int]
    changes: list[dict]
    input_signature: str
    schema: int = 1

    @property
    def actionable(self):
        return bool(self.changes)

    def public_report(self):
        """Aggregate-only export: no paths, names, IDs, profile hashes, transcripts."""
        return {
            "tool_version": __version__, "status": "preview_only",
            "scope": self.scope, "account_count": len(self.accounts),
            "recoverable_project_count": len(self.projects),
            "accounts": [{k: v for k, v in a.items() if k != "owner"} for a in self.accounts],
            "skipped": self.skipped, "notices": self.notices,
            "changed_field_count": len(self.changes),
            "transcript_integrity_verified": False, "live_state_written": False,
        }


def scan(home: Path, scope: str = "current", historical_state: Path | None = None) -> Plan:
    if scope not in {"current", "all"}:
        raise RecoveryError("恢复范围必须为 current 或 all。")
    home = home.expanduser().resolve()
    state_path = home / STATE_NAME
    state, before = read_json(state_path)
    backup_path = home / (STATE_NAME + ".bak")
    backup_before = backup_path.read_bytes() if backup_path.exists() else None
    accounts = account_views(state)
    for value in accounts.values():
        validate_globals(value)
    current_owner = state.get(SCOPE, {}).get("owner") if SCOPE in state else "legacy"
    if scope == "current" and current_owner is None:
        raise RecoveryError("当前没有活动账号。可选择同步所有已保存账号，不会修改登录身份。")
    sources = list(accounts.values())
    extra_path, extra_hash = None, None
    notices = []
    if historical_state is not None:
        extra_path = historical_state.expanduser().resolve()
        extra, extra_raw = read_json(extra_path)
        extra_hash = digest(extra_raw)
        more = list(account_views(extra).values())
        for value in more:
            validate_globals(value)
        sources.extend(more)
    db = database_snapshot(home / DB_NAME)
    db_projects = {p["id"]: p for p in db["projects"]}
    roots = {}
    for r in sorted(db["project_roots"], key=lambda r: (r["project_id"], r["position"])):
        roots.setdefault(r["project_id"], []).append(r["path"])
    keys = {}
    for r in db["project_idempotency_keys"]:
        keys.setdefault(r["key"], set()).add(r["project_id"])
    host_key = "local:" + str(home)
    mappings = []
    for source in sources:
        for host, values in source.get(ID_MAP, {}).items():
            if host.startswith("local:") and Path(host[6:]).expanduser().resolve() == home:
                mappings.append(values)
                host_key = host
    saved = {}
    for source in sources:
        for pid, p in source.get("local-projects", {}).items():
            saved.setdefault(pid, []).append(p)
    candidates = {}
    skipped = {"cloud_linked_projects": 0, "ambiguous_projects": 0, "missing_roots": 0,
               "missing_threads": 0, "ambiguous_memberships": 0, "missing_rollouts": 0,
               "project_conflicts": 0, "preserved_memberships": 0}
    for sid, dbp in db_projects.items():
        try:
            metadata = json.loads(dbp["metadata"])
        except (ValueError, TypeError) as exc:
            raise RecoveryError("数据库项目元数据格式无效。") from exc
        if not isinstance(metadata, dict):
            raise RecoveryError("数据库项目元数据格式未知。")
        legacy_ids = set()
        conflicting_evidence = False
        for pid, variants in saved.items():
            evidence = set(keys.get(pid, ()))
            if pid in db_projects:
                evidence.add(pid)
            for mapping in mappings:
                if pid in mapping:
                    evidence.add(mapping[pid])
            if evidence == {sid}:
                legacy_ids.add(pid)
            elif sid in evidence:
                conflicting_evidence = True
        explicit = metadata.get("codex.localProjectId")
        related_keys = {k for k, ids in keys.items() if sid in ids}
        possible = {k for k, ids in keys.items() if ids == {sid} and uuid_like(k)}
        if explicit is not None:
            conflicting_evidence |= not isinstance(explicit, str) or not uuid_like(explicit)
            if isinstance(explicit, str):
                conflicting_evidence |= bool(legacy_ids and legacy_ids != {explicit})
                conflicting_evidence |= bool(possible and possible != {explicit})
        conflicting_evidence |= any(keys[k] != {sid} for k in related_keys)
        if conflicting_evidence:
            skipped["ambiguous_projects"] += 1
            continue
        if not legacy_ids:
            if explicit and uuid_like(explicit):
                legacy_ids = {explicit}
            elif len(possible) == 1:
                legacy_ids = possible
            elif not related_keys and uuid_like(sid):
                legacy_ids = {sid}
        if len(legacy_ids) != 1:
            skipped["ambiguous_projects"] += 1
            continue
        pid = next(iter(legacy_ids))
        variants = saved.get(pid, [])
        if any(k.startswith("codex.chatGpt") or k.startswith("codex.retiredChatGpt") for k in metadata) or any(any(p.get(k) is not None for k in CLOUD_KEYS) for p in variants):
            skipped["cloud_linked_projects"] += 1
            continue
        paths = roots.get(sid, [])
        if not paths or not all(Path(path).is_absolute() and Path(path).is_dir() for path in paths):
            skipped["missing_roots"] += 1
            continue
        if any(normalized_roots(p["rootPaths"]) != normalized_roots(paths) for p in variants):
            skipped["ambiguous_projects"] += 1
            continue
        candidates[pid] = {
            "record": {"id": pid, "name": dbp["name"], "rootPaths": paths,
                       "createdAt": dbp["created_at_ms"], "updatedAt": dbp["updated_at_ms"]},
            "server_id": sid, "position": dbp["position"],
            "evidence": "saved_and_database" if variants else "database_identity",
        }
    server_to_legacy = {p["server_id"]: pid for pid, p in candidates.items()}
    assignments = {}
    saved_assignments = {}
    for source in sources:
        projectless = set(source.get("projectless-thread-ids", [])) | set(source.get("thread-projectless-output-directories", {}))
        for tid, value in source.get("thread-project-assignments", {}).items():
            if value.get("projectKind") == "local" and value["projectId"] in candidates and tid not in projectless and source.get("thread-project-membership-host-ids", {}).get(tid, "local") == "local":
                saved_assignments.setdefault(tid, set()).add(value["projectId"])
    threads = {t["id"]: t for t in db["threads"]}
    skipped["missing_threads"] = len(set(saved_assignments) - set(threads))
    for tid, thread in threads.items():
        explicit = saved_assignments.get(tid, set())
        server = thread["project_id"]
        authoritative = server_to_legacy.get(server)
        if server is not None:
            if authoritative is None:
                continue
            if explicit and explicit != {authoritative}:
                skipped["ambiguous_memberships"] += 1
                continue
            pid = authoritative
        elif len(explicit) == 1:
            pid = next(iter(explicit))
        else:
            if len(explicit) > 1:
                skipped["ambiguous_memberships"] += 1
            continue
        rollout = thread.get("rollout_path")
        if not rollout or not (Path(rollout).is_file() or Path(rollout + ".zst").is_file()):
            skipped["missing_rollouts"] += 1
            continue
        assignments[tid] = {"projectId": pid, "projectKind": "local"}
    result = copy.deepcopy(state)
    targets = account_views(result)
    selected = list(accounts) if scope == "all" else [current_owner]
    changes, summaries = [], []
    for index, owner in enumerate(selected, 1):
        old, target = accounts[owner], targets[owner]
        registry = copy.deepcopy(target.get("local-projects", {}))
        mapping_root = copy.deepcopy(target.get(ID_MAP, {}))
        mapping = mapping_root.setdefault(host_key, {})
        order = list(dict.fromkeys(target.get("project-order", [])))
        included = set()
        for pid, p in sorted(candidates.items(), key=lambda pair: (pair[1]["position"], pair[0])):
            record = p["record"]
            existing = registry.get(pid)
            conflict = (pid in mapping and mapping[pid] != p["server_id"])
            if existing:
                conflict |= normalized_roots(existing["rootPaths"]) != normalized_roots(record["rootPaths"])
                conflict |= any(existing.get(k) is not None for k in CLOUD_KEYS)
            conflict |= any(key != pid and normalized_roots(other["rootPaths"]) == normalized_roots(record["rootPaths"]) for key, other in registry.items())
            if conflict:
                skipped["project_conflicts"] += 1
                continue
            registry.setdefault(pid, copy.deepcopy(record))
            mapping[pid] = p["server_id"]
            if pid not in order:
                order.append(pid)
            included.add(pid)
        membership = copy.deepcopy(target.get("thread-project-assignments", {}))
        hosts = copy.deepcopy(target.get("thread-project-membership-host-ids", {}))
        projectless = set(target.get("projectless-thread-ids", [])) | set(target.get("thread-projectless-output-directories", {}))
        added_memberships = 0
        for tid, value in assignments.items():
            if value["projectId"] not in included:
                continue
            if tid in projectless or (tid in membership and membership[tid] != value) or (tid in hosts and hosts[tid] != "local"):
                skipped["preserved_memberships"] += 1
                continue
            added_memberships += int(tid not in membership)
            membership[tid], hosts[tid] = value, "local"
        if included:
            updates = {"local-projects": registry, ID_MAP: mapping_root, "project-order": order}
            if added_memberships or membership != target.get("thread-project-assignments", {}) or hosts != target.get("thread-project-membership-host-ids", {}):
                updates.update({"thread-project-assignments": membership, "thread-project-membership-host-ids": hosts})
            for key, value in updates.items():
                if key not in old or old[key] != value:
                    target[key] = value
                    changes.append({"owner": owner, "field": key, "before_present": key in old,
                                    "before": copy.deepcopy(old.get(key)), "after": copy.deepcopy(value)})
        summaries.append({"owner": owner, "label": "当前账号" if owner == current_owner else f"已保存账号 {index}",
                          "projects_before": len(old.get("local-projects", {})), "projects_after": len(registry),
                          "memberships_added": added_memberships})
    if not candidates:
        notices.append("没有找到可明确恢复的普通本地项目。文件夹存在本身不构成完整恢复依据。")
    if skipped["cloud_linked_projects"]:
        notices.append("带 ChatGPT 云端关联的项目暂不迁移；已有记录保持原样。")
    if not changes and candidates:
        notices.append("项目状态已完整或存在冲突；此工具不会强行覆盖。若界面仍空，优先排查窗口加载问题。")
    notices.append("只恢复项目与聊天的对应记录，不验证或重建聊天正文；不会使未来新账号自动同步。")
    verify_changes(state, result, changes)
    db_hash = semantic_hash(db)
    signature = semantic_hash([str(home), digest(before), digest(backup_before) if backup_before is not None else None,
                               db_hash, extra_hash, scope])
    return Plan(home, scope, before, backup_before, result, db_hash, extra_path, extra_hash, summaries,
                [{"id": pid, **p["record"], "evidence": p["evidence"]} for pid, p in candidates.items()],
                notices, skipped, changes, signature)


def verify_changes(before, candidate, changes):
    expected = copy.deepcopy(before)
    targets = account_views(expected)
    for change in changes:
        if change["field"] not in FIELDS:
            raise RecoveryError("修复方案越过了允许的项目字段。")
        targets[change["owner"]][change["field"]] = copy.deepcopy(change["after"])
    if expected != candidate:
        raise RecoveryError("修复方案包含未审阅的其他状态变化。")


def atomic_bytes(path: Path, data: bytes):
    if path.is_symlink():
        raise RecoveryError("不写入符号链接状态文件。")
    descriptor, name = tempfile.mkstemp(prefix=".rescue-", suffix=".tmp", dir=path.parent)
    stage = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, path)
    finally:
        stage.unlink(missing_ok=True)


def install_pair(main: Path, backup: Path, proposed: bytes, before: bytes, before_backup: bytes | None):
    if main.parent.resolve() != backup.parent.resolve() or main.is_symlink() or backup.is_symlink():
        raise RecoveryError("状态文件目标不安全；没有写入。")
    installed = []
    try:
        atomic_bytes(main, proposed)
        installed.append((main, before))
        atomic_bytes(backup, proposed)
        installed.append((backup, before_backup))
        if main.read_bytes() != proposed or backup.read_bytes() != proposed:
            raise RecoveryError("写入后校验失败。")
    except BaseException as original:
        try:
            for path, original_bytes in reversed(installed):
                if original_bytes is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_bytes(path, original_bytes)
        except BaseException as rollback_error:
            raise RecoveryError("自动回滚失败。保留备份目录，不要继续修复；需从备份人工恢复。") from rollback_error
        raise original


def new_backup(home: Path, root: Path, before: bytes, before_backup: bytes | None) -> Path:
    root = root.expanduser().resolve()
    if root == home or root.is_relative_to(home):
        raise RecoveryError("请选择 Codex 数据目录之外的备份位置。")
    root.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    output = root / name
    output.mkdir()
    (output / "state.before.json").write_bytes(before)
    if before_backup is not None:
        (output / "state.bak.before.json").write_bytes(before_backup)
    source = sqlite3.connect((home / DB_NAME).as_uri() + "?mode=ro", uri=True, timeout=10)
    dest = sqlite3.connect(output / "state.snapshot.sqlite")
    try:
        source.backup(dest)
        if dest.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RecoveryError("备份数据库校验失败；没有应用修复。")
    finally:
        dest.close()
        source.close()
    if (output / "state.before.json").read_bytes() != before:
        raise RecoveryError("备份文件校验失败。")
    return output


def assert_unchanged(home: Path, before: bytes, before_backup: bytes | None):
    path = home / STATE_NAME
    backup = home / (STATE_NAME + ".bak")
    if path.read_bytes() != before or (backup.read_bytes() if backup.exists() else None) != before_backup:
        raise RecoveryError("状态在检查后发生变化；请重新扫描，没有写入。")


def apply(plan: Plan, backup_root: Path) -> Path:
    require_offline()
    require_supported_build()
    fresh = scan(plan.home, plan.scope, plan.extra_path)
    if fresh.input_signature != plan.input_signature or fresh.candidate != plan.candidate:
        raise RecoveryError("预览已过期，请重新扫描后再应用。")
    if not fresh.actionable:
        raise RecoveryError("没有需要写入的修复项。")
    output = new_backup(plan.home, backup_root, fresh.before, fresh.backup_before)
    proposed = encode(fresh.candidate)
    (output / "state.after.json").write_bytes(proposed)
    manifest = {"schema": 1, "tool_version": __version__, "status": "prepared", "home": str(plan.home),
                "before_sha256": digest(fresh.before), "after_sha256": digest(proposed),
                "backup_before_present": fresh.backup_before is not None, "changes": fresh.changes}
    (output / "manifest.json").write_bytes(encode(manifest))
    require_offline()
    assert_unchanged(plan.home, fresh.before, fresh.backup_before)
    if semantic_hash(database_snapshot(plan.home / DB_NAME)) != fresh.db_fingerprint:
        raise RecoveryError("数据库在备份后发生变化；请重新扫描。")
    install_pair(plan.home / STATE_NAME, plan.home / (STATE_NAME + ".bak"), proposed, fresh.before, fresh.backup_before)
    manifest["status"] = "applied_ui_not_verified"
    try:
        atomic_bytes(output / "manifest.json", encode(manifest))
    except OSError as exc:
        raise RecoveryError("状态已写入，但结果记录更新失败。保留最新备份目录；尚未验证界面。") from exc
    return output


def rollback(home: Path, backup_dir: Path, backup_root: Path) -> Path:
    require_offline()
    require_supported_build()
    home, backup_dir = home.expanduser().resolve(), backup_dir.expanduser().resolve()
    manifest, _ = read_json(backup_dir / "manifest.json")
    if manifest.get("schema") != 1 or manifest.get("status") not in {"prepared", "applied_ui_not_verified"} or Path(manifest.get("home", "")).resolve() != home:
        raise RecoveryError("备份不属于此数据目录或不支持撤销。")
    old, old_raw = read_json(backup_dir / "state.before.json")
    after, after_raw = read_json(backup_dir / "state.after.json")
    if digest(old_raw) != manifest.get("before_sha256") or digest(after_raw) != manifest.get("after_sha256"):
        raise RecoveryError("备份校验失败；拒绝撤销。")
    changes = manifest.get("changes", [])
    verify_changes(old, after, changes)
    current, before = read_json(home / STATE_NAME)
    bak = home / (STATE_NAME + ".bak")
    before_backup = bak.read_bytes() if bak.exists() else None
    candidate = copy.deepcopy(current)
    targets, original_targets = account_views(candidate), account_views(old)
    for change in changes:
        owner, key = change["owner"], change["field"]
        if owner not in targets or key not in targets[owner] or targets[owner][key] != change["after"]:
            raise RecoveryError("恢复后的项目字段已经变化。为保留后续工作，不自动撤销；备份仍在。")
        old_globals = original_targets[owner]
        if key in old_globals:
            targets[owner][key] = copy.deepcopy(old_globals[key])
        else:
            targets[owner].pop(key, None)
    output = new_backup(home, backup_root, before, before_backup)
    proposed = encode(candidate)
    (output / "rollback-target.json").write_bytes(proposed)
    require_offline()
    assert_unchanged(home, before, before_backup)
    install_pair(home / STATE_NAME, bak, proposed, before, before_backup)
    (output / "rollback-result.json").write_bytes(encode({"status": "rollback_applied_ui_not_verified"}))
    return output
