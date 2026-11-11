"""Assemble a portable archive for the current non-Windows build."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sqlite3
import sys
import zipfile
from pathlib import Path


def platform_tag() -> str:
    machine = platform.machine().lower().replace(" ", "-")
    if sys.platform == "darwin":
        return f"macos-{machine}"
    if sys.platform.startswith("linux"):
        return f"linux-{machine}"
    return f"{sys.platform}-{machine}"


def artifact_path(dist: Path) -> Path:
    candidates = [dist / "CodexProjectRescue"]
    if sys.platform == "darwin":
        candidates.insert(0, dist / "CodexProjectRescue.app")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit("Build CodexProjectRescue with PyInstaller before packaging.")


def add_path(bundle: zipfile.ZipFile, path: Path, arcname: str):
    if path.is_dir():
        for child in path.rglob("*"):
            relative = child.relative_to(path.parent)
            if child.is_dir():
                continue
            bundle.write(child, str(Path(arcname).parent / relative).replace("\\", "/"))
    else:
        bundle.write(path, arcname)


def runtime_license() -> Path | None:
    for candidate in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"):
        if candidate.is_file():
            return candidate
    return None


def main():
    if sys.platform == "win32":
        raise SystemExit("Use package_windows.py for Windows builds.")
    if "conda" in sys.version.lower() or (Path(sys.base_prefix) / "conda-meta").exists():
        raise SystemExit("Use a clean CPython installation, such as actions/setup-python.")
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "src"))
    from codex_rescue.platform import supported_builds_label

    version = (repo / "VERSION").read_text(encoding="utf-8").strip()
    dist = repo / "dist"
    artifact = artifact_path(dist)
    tag = platform_tag()
    archive = dist / f"CodexProjectRescue-{version}-{tag}.zip"
    read_first = (
        "Codex项目恢复助手 - 跨平台预览版\n\n"
        "1. 将 ZIP 完整解压到独立文件夹。\n"
        "2. 启动 CodexProjectRescue（macOS 首次运行可能需要在系统设置中允许打开）。\n"
        "3. 点击“开始检查”，确认项目和账号范围。检查时可以保持 Codex 打开。\n"
        "4. 准备修复时，由你保存工作并手动退出 Codex，保持本工具打开。\n"
        "5. 重新检查运行状态，点击“备份并修复”。完成后由你打开 Codex 核验。\n\n"
        "工具不会关闭、重启或自动打开 Codex。这是独立社区预览版。\n"
        f"已知 Windows 版本：{supported_builds_label()}；其他版本先做本地结构检查，通过后也可继续。\n"
        "完整备份含私人数据，请勿上传。详细步骤与限制见 README.md。\n"
    )
    sources = [
        "README.md", "SECURITY.md", "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md", "VERSION",
        "pyproject.toml", "docs/recovery-model.md", "docs/compatibility.md", "docs/cover.png", "docs/preview.png",
    ]
    sources += [str(path.relative_to(repo)).replace("\\", "/") for path in (repo / "docs/badges").glob("*.svg")]
    sources += [str(path.relative_to(repo)).replace("\\", "/") for path in (repo / "docs/licenses").iterdir() if path.is_file()]
    if (repo / "LICENSE").is_file():
        sources.append("LICENSE")
    license_path = runtime_license()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        add_path(bundle, artifact, artifact.name)
        for source in sources:
            bundle.write(repo / source, source)
        if license_path:
            bundle.write(license_path, "docs/licenses/CPython-runtime-LICENSE.txt")
        bundle.writestr("READ-FIRST.txt", read_first)
        try:
            pyinstaller = importlib.metadata.version("pyinstaller")
        except importlib.metadata.PackageNotFoundError:
            pyinstaller = "unknown"
        bundle.writestr("BUILD-INFO.json", json.dumps({
            "tool": version, "python": platform.python_version(), "architecture": platform.machine(),
            "platform": sys.platform, "pyinstaller": pyinstaller, "sqlite": sqlite3.sqlite_version,
            "executable_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest() if artifact.is_file() else None,
            "source_commit": os.environ.get("GITHUB_SHA"), "build_run_id": os.environ.get("GITHUB_RUN_ID"),
        }, indent=2))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist / f"SHA256SUMS-{tag}.txt").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(f"Created {archive.name} with runtime notices and SHA-256 checksum.")


if __name__ == "__main__":
    main()
