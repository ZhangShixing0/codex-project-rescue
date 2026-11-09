from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import RecoveryError, apply, rollback, scan
from .platform import EnvironmentError, backup_home, default_home


def parser():
    command = argparse.ArgumentParser(description="Codex项目恢复助手；默认只读，不关闭应用。")
    command.add_argument("--home", type=Path, default=default_home(), help="Codex 数据目录")
    command.add_argument("--scope", choices=["current", "all"], default="current", help="all 仅在确认这些账号都由你管理时使用")
    command.add_argument("--historical-state", type=Path, help="可选的历史 global-state JSON；只读")
    command.add_argument("--backup-dir", type=Path, default=backup_home(), help="Codex 数据目录之外的私有备份目录")
    actions = command.add_subparsers(dest="action")
    inspect = actions.add_parser("scan", help="只读扫描；默认动作")
    inspect.add_argument("--json", action="store_true", help="输出仅含数量的可分享诊断")
    actions.add_parser("apply", help="重新扫描、展示摘要并要求输入 RESTORE；需用户已手动退出 Codex")
    undo = actions.add_parser("rollback", help="撤销指定备份对应的项目字段；需用户已手动退出 Codex")
    undo.add_argument("backup", type=Path)
    actions.add_parser("gui", help="打开图形界面")
    return command


def main(argv=None):
    args = parser().parse_args(argv)
    if args.action == "gui":
        from .gui import main as gui_main
        gui_main(args.home)
        return 0
    try:
        if args.action == "rollback":
            print("只撤销此次修复的项目字段；如后续已变化，将拒绝覆盖。不会关闭或启动 Codex。")
            if input("输入 ROLLBACK 确认：").strip() != "ROLLBACK":
                print("已取消。")
                return 0
            output = rollback(args.home, args.backup, args.backup_dir)
            print("撤销已写入，请手动打开 Codex 验证。备份：", output)
            return 0
        plan = scan(args.home, args.scope, args.historical_state)
        if getattr(args, "json", False):
            print(json.dumps(plan.public_report(), ensure_ascii=False, indent=2))
        else:
            print(f"找到 {len(plan.projects)} 个可恢复普通本地项目，范围：{len(plan.accounts)} 个账号。")
            for account in plan.accounts:
                print(f"{account['label']}: 项目 {account['projects_before']} → {account['projects_after']}，新增归属 {account['memberships_added']}")
            for key, count in plan.skipped.items():
                if count:
                    print(f"保留/跳过 {key}: {count}")
            for notice in plan.notices:
                print(notice)
        if args.action == "apply":
            print("将先备份，再写入两个项目状态 JSON。范围内已有设置保留。不会修改会话正文或数据库。")
            if args.scope == "all":
                print("你选择了本机所有已保存账号，请确认这些账号均由你管理且希望共享本地项目列表。")
            if input("输入 RESTORE 确认：").strip() != "RESTORE":
                print("已取消。")
                return 0
            output = apply(plan, args.backup_dir)
            print("状态已写入；界面尚未验证。请手动打开 Codex。备份：", output)
        else:
            print("只读扫描完成，没有修改 Codex。") if not getattr(args, "json", False) else None
        return 0
    except (RecoveryError, EnvironmentError, OSError, EOFError) as exc:
        print("未完成：", str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
