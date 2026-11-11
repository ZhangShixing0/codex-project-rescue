"""Assemble a portable archive from a clean CPython / PyInstaller build."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sqlite3
import sys
import tkinter
import zipfile
from pathlib import Path


def main():
    if sys.platform != "win32" or "conda" in sys.version.lower() or (Path(sys.base_prefix) / "conda-meta").exists():
        raise SystemExit("Use a clean Windows CPython installation, such as actions/setup-python.")
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "src"))
    from codex_rescue.platform import supported_builds_label
    version = (repo / "VERSION").read_text().strip()
    dist = repo / "dist"
    executable = dist / "CodexProjectRescue.exe"
    if not executable.is_file():
        raise SystemExit("Build CodexProjectRescue.exe before packaging.")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise SystemExit("The CPython license file is missing; do not publish this build.")
    read_first = (
        "Codex项目恢复助手 - Windows 预览版\n\n"
        "1. 将 ZIP 完整解压到独立文件夹。\n"
        "2. 双击 CodexProjectRescue.exe，无需安装 Python。\n"
        "3. 点击“开始检查”，确认项目和账号范围。检查时可以保持 Codex 打开。\n"
        "4. 准备修复时，由你保存工作并手动退出 Codex，保持本工具打开。\n"
        "5. 重新检查运行状态，点击“备份并修复”。完成后由你打开 Codex 核验。\n\n"
        "工具不会关闭、重启或自动打开 Codex。这是独立社区预览版。\n"
        f"当前写入仅支持 Windows Codex {supported_builds_label()}；其他版本只允许扫描。\n"
        "完整备份含私人数据，请勿上传。详细步骤与限制见 README.md。\n"
    )
    archive = dist / f"CodexProjectRescue-{version}-windows-x64.zip"
    sources = ["README.md", "SECURITY.md", "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md", "VERSION", "pyproject.toml", "docs/recovery-model.md", "docs/compatibility.md", "docs/cover.png", "docs/preview.png"]
    sources += [str(path.relative_to(repo)).replace("\\", "/") for path in (repo / "docs/badges").glob("*.svg")]
    sources += [str(path.relative_to(repo)).replace("\\", "/") for path in (repo / "docs/licenses").iterdir() if path.is_file()]
    if (repo / "LICENSE").is_file():
        sources.append("LICENSE")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        bundle.write(executable, executable.name)
        for source in sources:
            bundle.write(repo / source, source)
        bundle.write(python_license, "docs/licenses/CPython-runtime-LICENSE.txt")
        bundle.writestr("READ-FIRST.txt", read_first)
        bundle.writestr("BUILD-INFO.json", json.dumps({
            "tool": version, "python": platform.python_version(), "architecture": platform.machine(),
            "pyinstaller": importlib.metadata.version("pyinstaller"), "sqlite": sqlite3.sqlite_version,
            "tcl": tkinter.Tcl().eval("info patchlevel"),
            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "source_commit": os.environ.get("GITHUB_SHA"),
            "build_run_id": os.environ.get("GITHUB_RUN_ID"),
        }, indent=2))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist / "SHA256SUMS.txt").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(f"Created {archive.name} with runtime notices and SHA-256 checksum.")


if __name__ == "__main__":
    main()
