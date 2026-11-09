"""Read-only Windows discovery. Deliberately no process termination API."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


class EnvironmentError(RuntimeError):
    pass


SUPPORTED_BUILDS = frozenset({"26.1103.4239.0"})


def default_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()


def backup_home() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "CodexProjectRescue" / "backups"


def powershell_json(script: str):
    if os.name != "nt":
        raise EnvironmentError("应用修复目前仅支持 Windows；其他系统可以运行离线扫描。")
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
    values = powershell_json(
        "$v=@(Get-AppxPackage -Name OpenAI.Codex | ForEach-Object { $_.Version.ToString() }); "
        "ConvertTo-Json -InputObject $v -Compress"
    )
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise EnvironmentError("应用版本返回格式无法识别。")
    return values


def running_processes() -> list[dict]:
    values = powershell_json(
        "$p=@(Get-Process | Where-Object { $_.ProcessName -in @('ChatGPT','codex') } | "
        "Select-Object Id,ProcessName); ConvertTo-Json -InputObject $p -Compress"
    )
    if not isinstance(values, list):
        raise EnvironmentError("无法可靠识别 Codex 进程；没有写入。")
    return values


def require_offline():
    if running_processes():
        raise EnvironmentError("Codex/ChatGPT 仍在运行。请保存工作并由你手动完全退出后重试；工具不会关闭它。")


def require_supported_build():
    versions = installed_builds()
    if len(versions) != 1 or versions[0] not in SUPPORTED_BUILDS:
        raise EnvironmentError("当前应用版本尚未验证，仅可扫描。请勿使用旧版本脚本强行覆盖。")
