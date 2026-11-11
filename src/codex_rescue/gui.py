"""Native four-step wizard for Codex项目恢复助手."""
from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, platform
from .core import apply, rollback, scan
from .platform import backup_home, default_home, supported_builds_label
from .presentation import PROJECT_STATUS, build_status_for_home, failure_report, list_backups, preflight, project_overview
from .widgets import BODY, COLORS as C, Button, folder_symbol

APP_NAME = "Codex项目恢复助手"


def label(parent, text="", size=10, color=None, bold=False, **kwargs):
    return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color or C["text"],
                    font=(BODY, size, "bold" if bold else "normal"), anchor="w", **kwargs)


class RescueApp:
    def __init__(self, root, home=None):
        self.root, self.plan, self.last_backup = root, None, None
        self.view, self.readiness, self.diagnostic = None, None, None
        self.build, self.error, self.result, self.user_verified = None, None, None, False
        self.state, self.busy, self.events = "start", False, queue.Queue()
        self.home = tk.StringVar(value=str(home or default_home()))
        self.history = tk.StringVar()
        self.backups = tk.StringVar(value=str(backup_home()))
        self.all_accounts = tk.BooleanVar(value=False)
        root.title(APP_NAME)
        root.geometry("1160x820")
        root.minsize(980, 740)
        root.configure(bg=C["surface"])
        self.setup_styles()
        header = tk.Frame(root, bg=C["surface"])
        header.pack(fill="x", padx=28, pady=20)
        logo = tk.Canvas(header, width=37, height=37, bg=C["surface"], bd=0, highlightthickness=0)
        logo.pack(side="left", padx=(0, 12))
        folder_symbol(logo, .45)
        identity = tk.Frame(header, bg=C["surface"])
        identity.pack(side="left")
        label(identity, APP_NAME, size=13, bold=True, color=C["ink"]).pack(anchor="w")
        label(identity, f"本地工具 · 社区预览版 {__version__}", size=9, color=C["muted"]).pack(anchor="w")
        self.settings_button = self.link(header, "数据位置与设置", self.show_settings)
        self.settings_button.pack(side="right")
        tk.Frame(root, bg=C["line"], height=1).pack(fill="x")
        shell = tk.Frame(root, bg=C["surface"])
        shell.pack(fill="both", expand=True)
        rail = tk.Frame(shell, bg="#F7FAF7", width=208)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        tk.Frame(shell, bg=C["line"], width=1).pack(side="left", fill="y")
        self.steps = []
        for number, (title, subtitle) in enumerate((("检查本机", "寻找已有记录"), ("确认项目", "看清将恢复什么"), ("准备与修复", "由你确认后写入"), ("核验结果", "回到 Codex 看一眼")), 1):
            item = tk.Frame(rail, bg=rail.cget("bg"))
            item.pack(fill="x", padx=23, pady=(28 if number == 1 else 17, 0))
            num = label(item, str(number), size=11, color=C["muted"], padx=8, pady=4)
            num.pack(side="left", anchor="n", padx=(0, 9))
            texts = tk.Frame(item, bg=rail.cget("bg"))
            texts.pack(side="left")
            title_label = label(texts, title, size=10, bold=True)
            title_label.pack(anchor="w")
            label(texts, subtitle, size=9, color=C["muted"]).pack(anchor="w", pady=(3, 0))
            self.steps.append((num, title_label))
        support = tk.Frame(rail, bg=rail.cget("bg"))
        support.pack(side="bottom", fill="x", padx=23, pady=23)
        label(support, "项目和聊天留在本机", size=9, color=C["muted"]).pack(anchor="w")
        label(support, "工具不会关闭、重启\n或自动打开 Codex。", size=9, color=C["muted"], justify="left").pack(anchor="w", pady=(7, 14))
        self.backup_button = self.link(support, "备份与撤销", self.show_backups)
        self.backup_button.pack(anchor="w")
        self.export_button = self.link(support, "导出匿名诊断", self.export)
        self.export_button.pack(anchor="w", pady=(7, 0))
        main = tk.Frame(shell, bg=C["surface"])
        main.pack(fill="both", expand=True)
        self.actionbar = tk.Frame(main, bg="#FDFEFD", padx=30, pady=16)
        self.actionbar.pack(side="bottom", fill="x")
        tk.Frame(main, bg=C["line"], height=1).pack(side="bottom", fill="x")
        self.content = tk.Frame(main, bg=C["surface"])
        self.content.pack(fill="both", expand=True, padx=32, pady=(27, 18))
        self.render()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(80, self.poll)

    def setup_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=(BODY, 10), background=C["surface"])
        style.configure("TRadiobutton", background=C["surface"], foreground=C["text"], padding=4, focuscolor=C["accent"])
        style.map("TRadiobutton", background=[("active", C["surface"])])
        style.configure("Treeview", background=C["surface"], fieldbackground=C["surface"], foreground=C["text"], rowheight=56, font=(BODY, 10), borderwidth=0)
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure("Treeview.Heading", background=C["quiet"], foreground=C["muted"], borderwidth=0, relief="flat", font=(BODY, 9), padding=(7, 9))
        style.map("Treeview.Heading", background=[("active", C["quiet"])])
        style.map("Treeview", background=[("selected", C["soft"])], foreground=[("selected", C["ink"])])
        style.configure("Vertical.TScrollbar", background=C["line"], troughcolor=C["surface"], borderwidth=0, arrowsize=11)
        style.configure("TProgressbar", background=C["accent"], troughcolor=C["quiet"], borderwidth=0)

    def link(self, parent, text, command):
        return tk.Button(parent, text=text, command=command, bg=parent.cget("bg"), fg=C["accent"],
                         activebackground=C["quiet"], activeforeground=C["ink"], disabledforeground=C["muted"],
                         relief="flat", bd=0, highlightthickness=1, highlightbackground=parent.cget("bg"),
                         highlightcolor=C["accent"], font=(BODY, 9), cursor="hand2", padx=2, pady=5)

    def text(self, value, size=10, muted=False, bold=False, pady=(0, 0), parent=None):
        widget = label(parent or self.content, value, size=size, color=C["muted"] if muted else C["ink"] if bold else C["text"], bold=bold, wraplength=775, justify="left")
        widget.pack(anchor="w", pady=pady)
        return widget

    def title(self, value, description):
        self.text(value, size=23, bold=True)
        self.text(description, muted=True, pady=(8, 23))

    def notice(self, value, warning=False, parent=None):
        frame = tk.Frame(parent or self.content, bg="#FCF4E9" if warning else C["quiet"], padx=14, pady=12)
        frame.pack(fill="x", pady=(12, 0))
        label(frame, value, size=9, color="#85511D" if warning else C["text"], wraplength=750, justify="left").pack(anchor="w")

    def footer(self, hint, primary, command, secondary=None, enabled=True):
        for widget in self.actionbar.winfo_children():
            widget.destroy()
        button = Button(self.actionbar, primary, command, kind="primary", width=max(144, min(225, len(primary)*13+28)), state="normal" if enabled and not self.busy else "disabled")
        button.pack(side="right")
        self.primary_button = button
        if secondary:
            Button(self.actionbar, secondary[0], secondary[1], width=112, state="disabled" if self.busy else "normal").pack(side="right", padx=(8, 10))
        hint_widget = label(self.actionbar, hint, size=9, color=C["muted"], wraplength=340, justify="left")
        hint_widget.pack(side="left", fill="x", expand=True, padx=(0, 12))
        hint_widget.bind("<Configure>", lambda e: hint_widget.configure(wraplength=max(100, e.width)))

    def render(self):
        for widget in self.content.winfo_children():
            widget.destroy()
        step = {"start": 1, "scan": 1, "review": 2, "prepare": 3, "apply": 3, "rollback": 3, "done": 4, "error": 1}.get(self.state, 1)
        for index, (num, title) in enumerate(self.steps, 1):
            num.configure(bg=C["accent"] if index == step else C["soft"] if index < step else "#F7FAF7", fg="white" if index == step else C["muted"])
            title.configure(fg=C["accent"] if index == step else C["muted"])
        for widget in (self.settings_button, self.backup_button):
            widget.configure(state="disabled" if self.busy else "normal")
        self.export_button.configure(state="normal" if self.diagnostic and not self.busy else "disabled")
        if self.busy:
            messages = {"scan": ("正在检查已有记录", "核对项目目录、旧账号记录和聊天关联。"), "prepare": ("正在检查修复条件", "核对版本、进程、备份位置和预览是否仍然有效。"), "apply": ("正在备份并写入恢复记录", "请保持本工具打开，等待这一步完成。"), "rollback": ("正在核对备份并撤销", "仅撤销此次修复的项目字段。"), "backups": ("正在查找本机备份", "只查看当前数据目录对应的修复备份。")}
            title, detail = messages.get(self.operation, messages["scan"])
            self.title(title, detail)
            progress = ttk.Progressbar(self.content, mode="indeterminate")
            progress.pack(fill="x", pady=20)
            progress.start(12)
            self.footer("数据留在本机。工具不会关闭或启动 Codex。", "正在处理…", lambda: None, enabled=False)
            return
        getattr(self, "page_" + self.state, self.page_start)()

    def page_start(self):
        mark = tk.Canvas(self.content, width=85, height=75, bg=C["surface"], bd=0, highlightthickness=0)
        mark.pack(anchor="w", pady=(6, 20))
        folder_symbol(mark, 1)
        self.title("项目文件还在，左侧却空了？", "先检查这台电脑上的项目记录，看看哪些项目和原有聊天可以重新显示。")
        self.notice("从原记录中恢复，保留原来的项目身份。\n恢复能否完成，取决于版本支持和本地记录是否完整。")
        for value in ("检查时可以保持 Codex 打开", "先给你看结果，确认后才写入", "写入前会自动保存备份"):
            self.text("·  " + value, pady=(18, 0))
        self.footer("本次检查只读取记录，不修改任何项目。", "开始检查", self.start_scan)

    def page_review(self):
        view = self.view
        if view["added_entries"]:
            title = f"可以补回 {view['added_entries']} 个项目入口"
        elif self.plan.actionable:
            title = "可以补齐已有项目的关联记录"
        else:
            title = "没有需要写入的项目记录"
        self.title(title, f"本次范围：{view['account_count']} 个账号。可新增 {view['memberships_added']} 条聊天关联；正文仍需在 Codex 中核验。")
        below = tk.Frame(self.content, bg=C["surface"])
        below.pack(side="bottom", fill="x", pady=(14, 0))
        self.link(below, f"查看全部依据：已有 {view['existing_entries']} 项，跳过 {view['skipped_entries']} 项", self.show_details).pack(anchor="w")
        label(below, "双击项目可查看完整目录。", size=9, color=C["muted"]).pack(anchor="w", pady=(3, 0))
        label(below, "恢复到哪里？", bold=True).pack(anchor="w", pady=(13, 7))
        options = tk.Frame(below, bg=C["surface"])
        options.pack(fill="x")
        for title, value in (("仅当前账号（推荐）", False), (f"我管理的 {view['saved_account_count']} 个已保存账号", True)):
            ttk.Radiobutton(options, text=title, variable=self.all_accounts, value=value, command=self.scope_changed).pack(side="left", padx=(0, 16))
        write_capable = platform.can_write_status(self.build["status"])
        if not write_capable:
            self.notice("本地状态结构尚未通过写入检查，仍可查看只读结果。现在无需退出 Codex。", warning=True, parent=below)
        elif not self.plan.actionable:
            self.notice("记录可能已齐全，或缺少足够依据。请查看跳过原因；侧栏仍空时继续排查显示问题。", parent=below)
        rows = [r for r in view["rows"] if r["status"] in {"added", "repaired"}]
        self.project_table(self.content, rows or view["rows"])
        if self.plan.actionable and write_capable:
            self.footer("这一步尚未写入。下一步会检查修复条件。", "确认项目，继续", self.prepare, ("重新检查", self.start_scan))
        elif not write_capable:
            self.footer("保持原记录，先完成本地结构检查。", "查看兼容说明", self.compatibility, ("重新检查", self.start_scan))
        else:
            self.footer("未修改项目记录。", "查看后续处理", self.troubleshoot, ("重新检查", self.start_scan))

    def project_table(self, parent, rows):
        frame = tk.Frame(parent, bg=C["surface"])
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=("account", "chats", "status"), show="tree headings", height=4)
        for column, title, width in (("#0", "项目 / 本地目录", 300), ("account", "目标账号", 105), ("chats", "新增聊天关联", 105), ("status", "处理方式", 140)):
            tree.heading(column, text=title)
            tree.column(column, width=width, minwidth=80, stretch=column == "#0", anchor="w" if column in {"#0", "status"} else "center")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for index, row in enumerate(rows):
            def concise(path):
                parts = Path(path).parts
                return str(Path(parts[0]) / "…" / Path(*parts[-2:])) if len(path) > 46 and len(parts) > 3 else path
            roots = " ; ".join(concise(path) for path in row["roots"]) or "目录记录缺失"
            tree.insert("", "end", iid=str(index), text=row["name"] + "\n" + roots, values=(row["account"], str(row["memberships_added"]), PROJECT_STATUS.get(row["status"], "保留 / 跳过")))
        def inspect(event=None):
            selected = tree.selection()
            if selected:
                row = rows[int(selected[0])]
                messagebox.showinfo(row["name"], "本地目录：\n" + "\n".join(row["roots"]) + "\n\n处理方式：" + PROJECT_STATUS.get(row["status"], "保留 / 跳过"), parent=parent.winfo_toplevel())
        tree.bind("<Double-1>", inspect)
        tree.bind("<Return>", inspect)
        self.table = tree

    def page_prepare(self):
        ready = self.readiness or {}
        if not platform.can_write_status(ready.get("build", {}).get("status", "")):
            self.build = ready.get("build", {"status": "unknown", "versions": []})
            self.title("本地状态结构未通过写入检查", "修复前的复核未通过。你仍然可以查看项目预览和导出匿名诊断。")
            self.notice("现在无需退出 Codex。请保留原记录，先修复结构检查问题。", warning=True)
            self.footer("没有写入项目记录。", "查看兼容说明", self.compatibility, ("返回预览", self.return_review))
            return
        self.title("准备好了，由你确认修复" if ready.get("ready") else "确认好项目后，再准备修复", "工具只按刚才确认的范围处理。不会自动退出、重启或打开 Codex。")
        entries = [
            ("兼容性", "版本已知或本地结构通过检查，可以应用" if platform.can_write_status(ready.get("build", {}).get("status", "")) else "本地结构未通过检查，只能扫描", platform.can_write_status(ready.get("build", {}).get("status", ""))),
            ("备份位置", "已确认可写入，修复前会自动备份" if ready.get("backup") == "available" else "无法写入，请更换独立备份目录", ready.get("backup") == "available"),
            ("Codex 运行状态", {"running": "等待你手动退出；请保留本工具窗口", "closed": "已经退出，仍需由你点击按钮才写入", "unknown": "无法核实，暂不允许写入"}.get(ready.get("process"), "正在等待检查"), ready.get("process") == "closed"),
            ("恢复预览", {"fresh": "与当前记录一致", "stale": "记录已有变化，请重新扫描并确认", "unchecked": "退出 Codex 后再复核"}.get(ready.get("preview"), "等待复核"), ready.get("preview") == "fresh"),
        ]
        for title, detail, good in entries:
            row = tk.Frame(self.content, bg=C["surface"])
            row.pack(fill="x", pady=(0, 12))
            label(row, "通过" if good else "待处理", size=9, color=C["accent"] if good else "#85511D", padx=10, pady=6).pack(side="right")
            label(row, title, bold=True).pack(anchor="w")
            label(row, detail, size=9, color=C["muted"], wraplength=660, justify="left").pack(anchor="w", pady=(5, 8))
            tk.Frame(row, bg=C["line"], height=1).pack(fill="x")
        self.notice("条件已满足。点击“备份并修复”后，将先保存备份再写入。\n写入时还会再次检查版本、进程和数据变化。" if ready.get("ready") else "先保存工作，再由你手动退出 Codex，并保留本工具窗口。\n点击“重新检查运行状态”，条件满足后即可备份并修复。")
        if ready.get("ready"):
            self.footer("将先保存原始备份，再应用已确认的方案。", "备份并修复", self.start_apply, ("返回预览", self.return_review))
        elif ready.get("preview") == "stale":
            self.footer("旧预览已失效，尚未写入。", "重新扫描并确认", self.start_scan, ("返回预览", self.return_review))
        else:
            self.footer("条件未满足时不会写入。", "重新检查运行状态", self.prepare, ("返回预览", self.return_review))

    def page_done(self):
        undo = self.result and self.result["action"] == "rollback"
        self.title("你已确认项目和旧聊天的状态" if self.user_verified else "撤销记录已写入，请回 Codex 核验" if undo else "记录已写入，再回 Codex 看一眼", "核验来自你的确认。本工具还不能判断侧栏是否已经恢复。")
        if self.result and not undo:
            self.notice(f"补回 {self.result['added_entries']} 个项目入口，补齐 {self.result['repaired_entries']} 项关联记录，新增 {self.result['memberships_added']} 条聊天关联。")
        for number, text in enumerate(("手动打开 Codex，使用刚才选择的账号", "查看左侧是否显示原来的项目", "进入项目，打开几条之前的聊天"), 1):
            self.text(f"{number}   {text}", pady=(23, 0))
        self.link(self.content, "查看本次备份与撤销条件", self.show_backups).pack(anchor="w", pady=(26, 0))
        if self.user_verified:
            self.footer("已记录本次手动核验状态，未进行自动判定。", "返回首页", self.return_start)
        else:
            self.footer("仍未恢复时，请保留备份继续排查。", "我已核验项目和旧聊天", self.confirm_result, ("仍未恢复", self.troubleshoot))

    def page_error(self):
        code = self.diagnostic.get("reason", "operation_failed") if self.diagnostic else "operation_failed"
        titles = {"state_unavailable": "无法读取本地项目状态", "database_unavailable": "无法核实本地数据库", "preview_changed": "预览已过期，需要重新检查", "no_active_account": "当前没有活动账号", "unsupported_build": "当前版本尚未适配", "app_running": "Codex 仍在运行", "rollback_conflict": "项目已有新变化，暂不自动撤销"}
        self.title(titles.get(code, "这一步未完成，请查看原因"), "匿名诊断仍然可以导出，原始错误仅在本机显示。")
        area = tk.Text(self.content, height=7, wrap="word", font=(BODY, 10), bg=C["quiet"], fg=C["text"], relief="flat", padx=15, pady=15)
        area.pack(fill="both", expand=True, pady=(0, 18))
        area.insert("1.0", self.error or "未收到完整结果。")
        area.configure(state="disabled")
        uncertain = self.diagnostic and self.diagnostic.get("live_state_written") is None
        self.notice("写入结果无法确认。请先保留最新备份，避免重复覆盖。" if uncertain else "这一步没有写入 Codex 项目记录。", warning=bool(uncertain))
        if code == "no_active_account":
            self.link(self.content, "改为检查我管理的已保存账号", self.scan_saved_accounts).pack(anchor="w", pady=(12, 0))
        self.footer("请勿上传完整状态、数据库或聊天内容。", "导出匿名诊断", self.export, ("重新检查", self.start_scan))

    def scan_saved_accounts(self):
        self.all_accounts.set(True)
        self.start_scan()

    def start_scan(self):
        if self.busy:
            return
        self.plan, self.view, self.readiness = None, None, None
        home, history = Path(self.home.get()), Path(self.history.get()) if self.history.get().strip() else None
        scope = "all" if self.all_accounts.get() else "current"
        def inspect():
            plan = scan(home, scope, history)
            build = build_status_for_home(home)
            return plan, build
        self.state = "scan"
        self.run("scan", inspect)

    def show_plan(self, plan, build=None):
        self.plan, self.view = plan, project_overview(plan)
        self.build = build or {"status": "unknown", "versions": []}
        self.diagnostic = plan.public_report()
        self.diagnostic["build_status"] = self.build["status"]
        self.state = "review"
        self.render()

    def scope_changed(self):
        self.start_scan()

    def prepare(self):
        if not self.plan or self.busy:
            return
        plan, backups = self.plan, Path(self.backups.get())
        self.state = "prepare"
        self.run("prepare", lambda: preflight(plan, backups))

    def start_apply(self):
        if self.busy or not self.plan or not self.readiness or not self.readiness.get("ready"):
            return
        plan, backups = self.plan, Path(self.backups.get())
        self.state = "apply"
        self.run("apply", lambda: apply(plan, backups))

    def return_review(self):
        self.readiness = None
        self.state = "review"
        self.render()

    def return_start(self):
        self.plan, self.view, self.readiness = None, None, None
        self.user_verified, self.state = False, "start"
        self.render()

    def confirm_result(self):
        self.user_verified = True
        if self.diagnostic:
            self.diagnostic["user_reported_verified"] = True
            self.diagnostic["ui_recovery_verified"] = False
        self.render()

    def run(self, action, function):
        if self.busy:
            return
        self.busy, self.operation = True, action
        self.render()
        def worker():
            try:
                self.events.put((action, function(), None))
            except Exception as error:
                self.events.put((action, None, error))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            action, result, error = self.events.get_nowait()
            self.busy = False
            if error:
                self.diagnostic = failure_report(action, error, self.plan)
                self.error, self.readiness, self.plan, self.state = str(error), None, None, "error"
            elif action == "scan":
                self.show_plan(*result)
            elif action == "prepare":
                self.readiness, self.state = result, "prepare"
            elif action in {"apply", "rollback"}:
                self.last_backup = result
                self.result = {"action": action, **{key: (self.view or {}).get(key, 0) for key in ("added_entries", "repaired_entries", "memberships_added")}}
                self.diagnostic = {"tool_version": __version__, "status": "written_waiting_for_user", "operation": action,
                                   "live_state_written": True, "ui_recovery_verified": False, "user_reported_verified": False}
                self.plan, self.readiness, self.user_verified, self.state = None, None, False, "done"
            elif action == "backups":
                self.render()
                self.backup_dialog(result)
            self.render()
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def show_settings(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title(APP_NAME + " · 数据与备份位置")
        dialog.geometry("780x450")
        dialog.configure(bg=C["surface"])
        dialog.transient(self.root)
        dialog.grab_set()
        inner = tk.Frame(dialog, bg=C["surface"], padx=26, pady=22)
        inner.pack(fill="both", expand=True)
        label(inner, "数据位置与历史备份", size=19, bold=True).pack(anchor="w")
        label(inner, "通常可使用默认位置。需要历史状态时，再选择辅助文件。", size=9, color=C["muted"]).pack(anchor="w", pady=(8, 20))
        values = []
        for name, target, is_file in (("Codex 数据目录", self.home, False), ("历史状态文件（可选）", self.history, True), ("独立备份目录", self.backups, False)):
            variable = tk.StringVar(value=target.get())
            values.append((target, variable))
            label(inner, name, size=9, color=C["muted"]).pack(anchor="w", pady=(0, 5))
            row = tk.Frame(inner, bg=C["surface"])
            row.pack(fill="x", pady=(0, 13))
            entry = tk.Entry(row, textvariable=variable, font=(BODY, 10), relief="flat", highlightthickness=1, highlightbackground=C["line"], highlightcolor=C["accent"])
            entry.pack(side="left", fill="x", expand=True, ipady=7)
            def choose(v=variable, f=is_file):
                selected = filedialog.askopenfilename(parent=dialog, filetypes=[("状态 JSON", "*.json"), ("所有文件", "*")]) if f else filedialog.askdirectory(parent=dialog)
                if selected:
                    v.set(selected)
            self.link(row, "选择…", choose).pack(side="right", padx=(12, 0))
        def save():
            changed = any(target.get() != variable.get() for target, variable in values)
            for target, variable in values:
                target.set(variable.get())
            dialog.destroy()
            if changed:
                self.return_start()
        Button(inner, "保存设置", save, kind="primary", width=135).pack(side="right", pady=(8, 0))
        dialog.bind("<Escape>", lambda _: dialog.destroy())

    def show_details(self):
        if not self.view:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title(APP_NAME + " · 全部恢复依据")
        dialog.geometry("1040x540")
        dialog.configure(bg=C["surface"])
        content = tk.Frame(dialog, bg=C["surface"], padx=22, pady=22)
        content.pack(fill="both", expand=True)
        label(content, "将补回、保留和跳过的项目", size=18, bold=True).pack(anchor="w", pady=(0, 15))
        notes = "\n".join(self.plan.notices)
        below = tk.Frame(content, bg=C["surface"])
        below.pack(side="bottom", fill="x")
        self.notice(notes + "\n双击项目可查看完整目录。", parent=below)
        self.project_table(content, self.view["rows"])
        dialog.bind("<Escape>", lambda _: dialog.destroy())

    def show_backups(self):
        if not self.busy:
            home, root = Path(self.home.get()), Path(self.backups.get())
            self.run("backups", lambda: list_backups(home, root))

    def backup_dialog(self, entries):
        dialog = tk.Toplevel(self.root)
        dialog.title(APP_NAME + " · 备份与撤销")
        dialog.geometry("850x470")
        dialog.configure(bg=C["surface"])
        dialog.transient(self.root)
        dialog.grab_set()
        content = tk.Frame(dialog, bg=C["surface"], padx=24, pady=23)
        content.pack(fill="both", expand=True)
        label(content, "当前数据目录的修复备份", size=18, bold=True).pack(anchor="w")
        label(content, "撤销前仍需手动退出 Codex；项目字段已有后续变化时会停止。", size=9, color=C["muted"]).pack(anchor="w", pady=(7, 17))
        tree = ttk.Treeview(content, columns=("accounts", "projects", "status"), show="tree headings", height=4)
        for column, text, width in (("#0", "备份时间（本机时区）", 220), ("accounts", "账号", 70), ("projects", "新增项目", 90), ("status", "记录状态", 180)):
            tree.heading(column, text=text)
            tree.column(column, width=width, anchor="w")
        tree.pack(fill="both", expand=True)
        for index, entry in enumerate(entries):
            tree.insert("", "end", iid=str(index), text=entry["time"], values=(entry["accounts"], entry["projects_added"], "已写入，未核验界面" if entry["status"] == "applied_ui_not_verified" else "结果待确认"))
        path_text = tk.StringVar(value="尚无可识别的本工具修复备份。" if not entries else "选择一条备份，查看其保存位置。")
        label(content, textvariable=path_text, size=9, color=C["muted"], wraplength=780, justify="left").pack(anchor="w", pady=(14, 8))
        controls = tk.Frame(content, bg=C["surface"])
        controls.pack(fill="x")
        def restore():
            selected = tree.selection()
            if not selected:
                return
            entry = entries[int(selected[0])]
            if not messagebox.askyesno("确认撤销所选修复", "只撤销此次修复的项目字段，保留其他设置。\n请确认已手动退出 Codex。是否继续？", parent=dialog):
                return
            home, backup_root = Path(self.home.get()), Path(self.backups.get())
            dialog.destroy()
            self.state = "rollback"
            self.run("rollback", lambda: rollback(home, entry["path"], backup_root))
        undo = Button(controls, "撤销所选修复", restore, width=155, state="disabled")
        undo.pack(side="right")
        def select(_=None):
            chosen = tree.selection()
            if chosen:
                path_text.set(str(entries[int(chosen[0])]["path"]))
                undo.configure(state="normal")
        tree.bind("<<TreeviewSelect>>", select)
        dialog.bind("<Escape>", lambda _: dialog.destroy())

    def export(self):
        if not self.diagnostic or self.busy:
            return
        target = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json", initialfile="codex-rescue-diagnostic.json", filetypes=[("匿名诊断", "*.json")])
        if target:
            try:
                Path(target).write_text(json.dumps(self.diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
                messagebox.showinfo("诊断已导出", "报告不含项目名、路径、账号标识、错误原文或聊天正文。", parent=self.root)
            except OSError as error:
                messagebox.showerror("导出未完成", str(error), parent=self.root)

    def compatibility(self):
        versions = ", ".join((self.build or {}).get("versions", [])) or "未能核实"
        detail = (self.build or {}).get("detail", "")
        messagebox.showinfo("本地兼容性", f"本机版本：{versions}\n已知版本：{supported_builds_label()}。\n工具优先检查本地状态结构；结构通过即可继续，不再只按版本号拦截。\n{detail}\n现在无需退出 Codex。", parent=self.root)

    def troubleshoot(self):
        messagebox.showinfo("下一步怎么做", "1. 确认当前登录账号属于刚才选择的恢复范围。\n2. 区分项目未显示与某条聊天打不开。\n3. 查看全部依据中的跳过原因，保留本次备份。\n4. 缺少记录时，可在设置中选择已有历史状态文件。\n5. 导出匿名诊断继续排查，避免反复覆盖。\n\nWindows 的免退出窗口绕行尚未验证。工具不会自动重启应用。", parent=self.root)

    def on_close(self):
        if self.busy:
            messagebox.showinfo("正在处理", "请等待当前操作完成，避免中断备份或写入。", parent=self.root)
        else:
            self.root.destroy()


def main(home=None):
    root = tk.Tk()
    RescueApp(root, home)
    root.mainloop()


if __name__ == "__main__":
    main()
