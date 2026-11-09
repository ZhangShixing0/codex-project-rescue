"""Assemble a portable archive from a clean CPython / PyInstaller build."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
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
    version = (repo / "VERSION").read_text().strip()
    dist = repo / "dist"
    executable = dist / "CodexProjectRescue.exe"
    if not executable.is_file():
        raise SystemExit("Build CodexProjectRescue.exe before packaging.")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise SystemExit("The CPython license file is missing; do not publish this build.")
    read_first = (
        "Codex Project Rescue - Windows preview\n\n"
        "1. Extract this archive to a folder.\n"
        "2. Double-click CodexProjectRescue.exe. Python installation is not required.\n"
        "3. Scan and review first. Quit Codex manually only when ready to apply.\n"
        "4. After applying, open Codex manually and verify projects and old chats.\n\n"
        "The tool never closes or starts Codex. It is an independent community preview.\n"
        "Only reviewed Codex versions allow writes. See README.md for limits.\n"
        "Full backups are private. Never upload them or real profile data.\n"
    )
    archive = dist / f"CodexProjectRescue-{version}-windows-x64.zip"
    sources = ["README.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md", "docs/recovery-model.md", "docs/preview.png"]
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
        }, indent=2))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist / "SHA256SUMS.txt").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(f"Created {archive.name} with runtime notices and SHA-256 checksum.")


if __name__ == "__main__":
    main()
