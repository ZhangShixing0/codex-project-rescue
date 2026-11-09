"""Native Windows GUI. All account/profile data stays on this computer."""
from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .core import apply, rollback, scan
from .platform import backup_home, default_home


SKIP_LABELS = {
    "cloud_linked_projects": "带云端关联的项目（保留，不迁移）",
    "ambiguous_projects": "项目身份不明确",
    "missing_roots": "项目目录不可用",
    "missing_threads": "历史归属缺少本地线程记录",
    "ambiguous_memberships": "历史聊天归属冲突",
    "missing_rollouts": "未找到对应会话文件",
    "project_conflicts": "目标账号已有冲突项目",
    "preserved_memberships": "保留当前归属或无项目标记",
}


class RescueApp:
    def __init__(self, root: tk.Tk, home: Path | None = None):
        self.root, self.plan, self.last_backup = root, None, None
        self.events = queue.Queue()
        self.busy = False
        root.title("Codex Project Rescue · 本地项目恢复")
        root.geometry("1000x760")
        root.minsize(840, 650)
        root.configure(bg="#f4f6f8")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background="#f4f6f8")
        style.configure("TLabel", background="#f4f6f8", foreground="#233348", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("Sub.TLabel", foreground="#5e6b7c")
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(13, 8))
        style.configure("TCheckbutton", background="#f4f6f8")
        style.configure("Accent.TButton", background="#1c655c", foreground="white")
        style.map("Accent.TButton", background=[("disabled", "#b5c7c4"), ("active", "#164c46")])
        style.configure("Treeview", rowheight=30, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="找回项目，保留原来的对话", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text=f"Codex Project Rescue {__version__} · 社区预览版 · 数据仅在本机处理", style="Sub.TLabel").pack(anchor="w", pady=(4, 17))
        ttk.Label(frame, text="先扫描并查看证据。应用修复前由你手动退出 Codex；工具绝不替你关闭或重启它。", wraplength=890).pack(anchor="w", pady=(0, 18))
        paths = ttk.Frame(frame)
        paths.pack(fill="x")
        paths.columnconfigure(1, weight=1)
        self.home = tk.StringVar(value=str(home or default_home()))
        self.history = tk.StringVar()
        self.backups = tk.StringVar(value=str(backup_home()))
        self.all_accounts = tk.BooleanVar(value=False)
        self.inputs = []
        for row, (label, variable, choose_file) in enumerate([
            ("Codex 数据目录", self.home, False),
            ("历史状态文件（可选）", self.history, True),
            ("备份保存位置", self.backups, False),
        ]):
            ttk.Label(paths, text=label).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=5)
            entry = ttk.Entry(paths, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            button = ttk.Button(paths, text="选择", command=lambda v=variable, f=choose_file: self.choose(v, f))
            button.grid(row=row, column=2, padx=(8, 0))
            self.inputs.extend([entry, button])
        checkbox = ttk.Checkbutton(frame, text="同步到本机所有已保存账号（仅在这些账号都由你管理时选择）", variable=self.all_accounts, command=self.invalidate)
        checkbox.pack(anchor="w", pady=(14, 12))
        self.inputs.append(checkbox)
        self.status = tk.StringVar(value="还没有扫描。扫描不会修改 Codex 数据。")
        ttk.Label(frame, textvariable=self.status, font=("Microsoft YaHei UI", 11, "bold"), wraplength=890).pack(anchor="w", pady=(0, 10))
        table = ttk.Frame(frame)
        table.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table, columns=("before", "after", "members"), show="tree headings", height=6)
        self.table.heading("#0", text="恢复范围")
        self.table.heading("before", text="现有项目")
        self.table.heading("after", text="恢复后项目")
        self.table.heading("members", text="新增聊天归属")
        self.table.column("#0", width=300, stretch=True)
        for column in ("before", "after", "members"):
            self.table.column(column, width=130, anchor="center")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.details = tk.Text(frame, height=5, wrap="word", relief="flat", bg="#e9eef2", fg="#334155", font=("Microsoft YaHei UI", 10), padx=12, pady=10)
        self.details.pack(fill="x", side="bottom", before=table, pady=12)
        self.set_details("若项目状态已完整，但左侧仍为空，可能是窗口没有加载新状态。不要反复覆盖文件。\nmacOS 有通过“文件 → 新建窗口”恢复的社区报告，Windows 尚未验证。")
        controls = ttk.Frame(frame)
        controls.pack(fill="x", side="bottom", before=self.details)
        self.scan_button = ttk.Button(controls, text="1  扫描并预览", style="Accent.TButton", command=self.start_scan)
        self.apply_button = ttk.Button(controls, text="2  备份并修复", command=self.start_apply, state="disabled")
        self.projects_button = ttk.Button(controls, text="查看项目明细", command=self.show_projects, state="disabled")
        self.export_button = ttk.Button(controls, text="导出匿名诊断", command=self.export, state="disabled")
        self.undo_button = ttk.Button(controls, text="撤销上次修复", command=self.start_rollback)
        for button in (self.scan_button, self.apply_button, self.projects_button, self.export_button, self.undo_button):
            button.pack(side="left", padx=(0, 8))
        for variable in (self.home, self.history, self.backups):
            variable.trace_add("write", lambda *_: self.invalidate())
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(80, self.poll)

    def choose(self, variable, file):
        value = filedialog.askopenfilename(filetypes=[("JSON 状态文件", "*.json"), ("所有文件", "*")]) if file else filedialog.askdirectory()
        if value:
            variable.set(value)

    def invalidate(self):
        self.plan = None
        self.apply_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.projects_button.configure(state="disabled")
        self.status.set("选项已变化，请重新扫描。")

    def set_details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def run(self, action, function):
        if self.busy:
            return
        self.busy = True
        for button in [self.scan_button, self.apply_button, self.projects_button, self.export_button, self.undo_button, *self.inputs]:
            button.configure(state="disabled")
        self.status.set({"scan": "正在只读扫描…", "apply": "正在复核、备份和写入…", "rollback": "正在检查备份并撤销…"}[action])
        def worker():
            try:
                self.events.put((action, function(), None))
            except Exception as exc:
                self.events.put((action, None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def start_scan(self):
        home, scope = Path(self.home.get()), "all" if self.all_accounts.get() else "current"
        history = Path(self.history.get()) if self.history.get().strip() else None
        self.run("scan", lambda: scan(home, scope, history))

    def show_plan(self, plan):
        self.plan = plan
        self.table.delete(*self.table.get_children())
        for account in plan.accounts:
            self.table.insert("", "end", text=account["label"], values=(account["projects_before"], account["projects_after"], account["memberships_added"]))
        lines = [f"找到 {len(plan.projects)} 个可明确识别的普通本地项目。聊天归属有记录依据，但正文完整性未验证。"]
        lines.extend(f"{SKIP_LABELS[key]}：{count}" for key, count in plan.skipped.items() if count)
        lines.extend(plan.notices)
        self.set_details("\n".join(lines))
        self.status.set("预览已准备。应用前请手动完全退出 Codex。" if plan.actionable else "没有需要应用的修复；请查看诊断说明。")

    def start_apply(self):
        if not self.plan:
            return
        if not messagebox.askyesno("确认修复范围", "将按当前预览备份并合并项目记录。\n已有项目、登录信息、数据库与会话正文不会被替换。\n\n请确认已手动退出 Codex，并允许应用此预览。"):
            return
        plan, backups = self.plan, Path(self.backups.get())
        self.run("apply", lambda: apply(plan, backups))

    def show_projects(self):
        if not self.plan:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("候选项目与恢复依据 · 仅本机显示")
        dialog.geometry("960x500")
        container = ttk.Frame(dialog, padding=18)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="以下是有身份记录的候选项目。目标账号已有冲突时仍会跳过，请结合扫描说明查看。", wraplength=900).pack(anchor="w", pady=(0, 12))
        tree = ttk.Treeview(container, columns=("name", "roots", "evidence"), show="headings")
        for column, heading, width in [("name", "项目名称", 200), ("roots", "本地目录", 490), ("evidence", "恢复依据", 200)]:
            tree.heading(column, text=heading)
            tree.column(column, width=width)
        scroll = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for project in self.plan.projects:
            evidence = "账号记录 + 数据库" if project["evidence"] == "saved_and_database" else "数据库中的原有身份"
            tree.insert("", "end", values=(project["name"], " ; ".join(project["rootPaths"]), evidence))

    def start_rollback(self):
        selected = filedialog.askdirectory(title="选择含 manifest.json 的一次修复备份目录", initialdir=self.backups.get())
        if not selected:
            return
        if not messagebox.askyesno("撤销项目字段", "只撤销选中修复的项目字段；如果这些字段已有后续变化，会拒绝覆盖。\n请先手动退出 Codex。是否继续？"):
            return
        home, backups = Path(self.home.get()), Path(self.backups.get())
        self.run("rollback", lambda: rollback(home, Path(selected), backups))

    def export(self):
        if not self.plan:
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="rescue-diagnostic.json", filetypes=[("匿名诊断", "*.json")])
        if path:
            try:
                Path(path).write_text(json.dumps(self.plan.public_report(), ensure_ascii=False, indent=2), encoding="utf-8")
                messagebox.showinfo("已导出", "报告只包含数量和诊断类别，不包含项目名称、路径、账号 ID 或对话。")
            except OSError as exc:
                messagebox.showerror("导出失败", str(exc))

    def poll(self):
        try:
            action, result, error = self.events.get_nowait()
            self.busy = False
            for widget in [self.scan_button, self.undo_button, *self.inputs]:
                widget.configure(state="normal")
            if error:
                self.status.set("操作未完成，请查看原因。")
                self.set_details(error + "\n修复结果不能视为成功；请按提示处理后重试。")
                messagebox.showerror("操作未完成", error)
            elif action == "scan":
                self.show_plan(result)
            else:
                self.plan = None
                self.last_backup = result
                self.status.set("状态文件已更新。请手动打开 Codex，检查项目和旧聊天。")
                self.set_details(f"备份与结果已保存在：\n{result}\n\n界面效果和账号切换后的状态尚未验证。工具不会启动 Codex。")
            self.apply_button.configure(state="normal" if self.plan and self.plan.actionable else "disabled")
            self.export_button.configure(state="normal" if self.plan else "disabled")
            self.projects_button.configure(state="normal" if self.plan else "disabled")
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def on_close(self):
        if self.busy:
            messagebox.showinfo("正在处理", "请等待当前操作结束，以免中断备份或写入。")
            return
        self.root.destroy()


def main(home=None):
    root = tk.Tk()
    RescueApp(root, home)
    root.mainloop()


if __name__ == "__main__":
    main()
