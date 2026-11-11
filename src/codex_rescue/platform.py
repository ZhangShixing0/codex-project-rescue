"""Cross-platform discovery and structural compatibility checks.

The helper never terminates or launches Codex. Version strings are evidence,
not the write gate: a new build can use the same state schema safely after the
local profile passes the structural checks performed by the recovery planner.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sqlite3
import sys
from pathlib import Path


class EnvironmentError(RuntimeError):
    pass


# Known builds are useful labels, but are intentionally not the compatibility
# boundary. Unknown versions can be written only after the profile structure
# passes the same schema checks used by the planner.
SUPPORTED_BUILDS = frozenset({"26.1103.4239.0", "26.1103.7773.0"})
WRITE_CAPABLE_STATUSES = frozenset({"supported", "schema-compatible"})


def supported_builds_label() -> str:
    return "、".join(sorted(SUPPORTED_BUILDS, key=lambda value: tuple(map(int, value.split(".")))))


def candidate_homes() -> list[Path]:
    """Return platform conventions in priority order, without touching files."""
    home = Path.home()
    candidates: list[Path] = []
    if os.environ.get("CODEX_HOME"):
        candidates.append(Path(os.environ["CODEX_HOME"]))
    candidates.append(home / ".codex")
    if os.name == "nt":
        for variable in ("APPDATA", "LOCALAPPDATA"):
            if os.environ.get(variable):
                candidates.append(Path(os.environ[variable]) / "Codex")
    elif sys.platform == "darwin":
        candidates.extend((
            home / "Library" / "Application Support" / "Codex",
            home / "Library" / "Application Support" / "OpenAI" / "Codex",
        ))
    else:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
        candidates.append(config / "Codex")
    result: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result


def default_home() -> Path:
    for candidate in candidate_homes():
        if (candidate / ".codex-global-state.json").is_file() or (candidate / "state_5.sqlite").is_file():
            return candidate
    return candidate_homes()[0]


def backup_home() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "CodexProjectRescue" / "backups"


def powershell_json(script: str):
    if os.name != "nt":
        raise EnvironmentError("当前系统不提供 PowerShell 进程检查。")
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    executable = system_root / "System32/WindowsPowerShell/v1.0/powershell.exe"
    prefix = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
    try:
        result = subprocess.run(
            [str(executable), "-NoProfile", "-NonInteractive", "-Command", prefix + script],
            capture_output=True, encoding="utf-8", errors="strict", timeout=20, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return json.loads(result.stdout.lstrip("\ufeff").strip())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise EnvironmentError("无法核实应用状态；没有写入。请从独立窗口运行工具后再试。") from exc


def installed_builds() -> list[str]:
    if os.name != "nt":
        # macOS/Linux installations do not share the Windows Store package
        # registry. The profile schema remains the authoritative signal.
        return []
    values = powershell_json(
        "$v=@(Get-AppxPackage -Name OpenAI.Codex | ForEach-Object { $_.Version.ToString() }); "
        "ConvertTo-Json -InputObject $v -Compress"
    )
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise EnvironmentError("应用版本返回格式无法识别。")
    return values


def running_processes() -> list[dict]:
    if os.name == "nt":
        values = powershell_json(
            "$p=@(Get-Process | Where-Object { $_.ProcessName -in @('ChatGPT','codex') } | "
            "Select-Object Id,ProcessName); ConvertTo-Json -InputObject $p -Compress"
        )
        if not isinstance(values, list):
            raise EnvironmentError("无法可靠识别 Codex 进程；没有写入。")
        return values
    pgrep = shutil.which("pgrep")
    if not pgrep:
        raise EnvironmentError("当前系统无法可靠识别 Codex 进程；没有写入。")
    try:
        # POSIX ERE is shared by macOS and Linux; avoid PCRE-only syntax.
        result = subprocess.run([pgrep, "-af", "(^|/)(ChatGPT|codex)($|[ /])"],
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise EnvironmentError("无法可靠识别 Codex 进程；没有写入。") from exc
    if result.returncode not in (0, 1):
        raise EnvironmentError("无法可靠识别 Codex 进程；没有写入。")
    values = []
    for line in result.stdout.splitlines():
        pieces = line.split(maxsplit=1)
        if pieces and pieces[0].isdigit():
            values.append({"Id": int(pieces[0]), "ProcessName": pieces[1] if len(pieces) > 1 else "codex"})
    return values


def require_offline():
    if running_processes():
        raise EnvironmentError("Codex/ChatGPT 仍在运行。请保存工作并由你手动完全退出后重试；工具不会关闭它。")


def schema_probe(home: Path) -> tuple[bool, str]:
    """Check the minimal durable shape without importing the recovery planner."""
    home = home.expanduser().resolve()
    state_path, db_path = home / ".codex-global-state.json", home / "state_5.sqlite"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        if not isinstance(state, dict):
            return False, "状态文件顶层不是对象"
        connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                return False, "数据库完整性检查未通过"
            required = {"projects", "project_roots", "project_idempotency_keys", "threads"}
            found = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = sorted(required - found)
            if missing:
                return False, "数据库缺少必要表：" + ", ".join(missing)
        finally:
            connection.close()
    except (OSError, UnicodeError, ValueError, sqlite3.Error) as exc:
        return False, "无法读取本地状态结构"
    return True, "本地状态结构可由恢复规划器读取"


def can_write_status(status: str) -> bool:
    return status in WRITE_CAPABLE_STATUSES


def require_supported_build(home: Path | None = None):
    versions = installed_builds()
    if len(versions) > 1:
        raise EnvironmentError("检测到多个 Codex 安装版本；请保留一个版本后再写入。")
    if len(versions) == 1 and versions[0] in SUPPORTED_BUILDS:
        return
    if home is not None:
        compatible, detail = schema_probe(home)
        if compatible:
            return
        raise EnvironmentError(f"本地状态结构未通过兼容检查：{detail}。仍可扫描，但没有写入。")
    raise EnvironmentError("无法确认本地状态结构；没有写入。")
