"""main.py - Miniconda 环境管理器 GUI (tkinter).

Entry point. All conda operations run on background threads; results and
output lines flow back to the UI through a queue polled on the main thread.
"""

import os
import queue
import threading
import tkinter as tk
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox
from tkinter import ttk

import conda_api

APP_TITLE = "Miniconda 环境管理器"

INVALID_NAME_CHARS = set('\\/:*?"<>| \t') | {"#", "&", "(", ")"}


class CondaEnvManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("820x640")
        self.minsize(680, 520)

        self.q = queue.Queue()
        self.conda = None          # located conda executable (absolute path) or None
        self.info = None           # {"base": ..., "envs_dirs": [...]} or None
        self.envs = []             # latest env dicts from list_envs
        self.busy = False
        self.conda_ok = False

        self._build_ui()
        self.after(100, self._poll_queue)
        self.after(200, self._startup)

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        # --- top: conda status -------------------------------------------
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="conda：").pack(side="left")
        self.status_var = tk.StringVar(value="正在检测 conda…")
        self.status_lbl = ttk.Label(top, textvariable=self.status_var, foreground="#555")
        self.status_lbl.pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="选择 conda", command=self._on_choose_conda).pack(side="right", padx=4)
        self.refresh_btn = ttk.Button(top, text="刷新", command=self._refresh_all)
        self.refresh_btn.pack(side="right", padx=4)

        # --- create form --------------------------------------------------
        create = ttk.LabelFrame(self, text="创建环境")
        create.pack(fill="x", **pad)
        create.columnconfigure(1, weight=1)
        create.columnconfigure(3, weight=1)

        ttk.Label(create, text="环境类型：").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        self.env_type = tk.StringVar(value="named")
        ttk.Radiobutton(create, text="命名环境", value="named", variable=self.env_type,
                        command=self._on_type_change).grid(row=0, column=1, sticky="w", padx=4, pady=(8, 2))
        ttk.Radiobutton(create, text="前缀环境", value="prefix", variable=self.env_type,
                        command=self._on_type_change).grid(row=0, column=2, columnspan=2, sticky="w",
                                                           padx=4, pady=(8, 2))

        # named row (subframe so the whole row can be toggled)
        self.named_frame = ttk.Frame(create)
        self.named_frame.grid(row=1, column=0, columnspan=4, sticky="ew")
        self.named_frame.columnconfigure(1, weight=1)
        self.named_frame.columnconfigure(3, weight=1)
        ttk.Label(self.named_frame, text="环境名称：").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.name_var = tk.StringVar()
        ttk.Entry(self.named_frame, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        ttk.Label(self.named_frame, text="环境目录：").grid(row=0, column=2, sticky="w", padx=8, pady=4)
        self.dir_var = tk.StringVar()
        self.dir_combo = ttk.Combobox(self.named_frame, textvariable=self.dir_var)
        self.dir_combo.grid(row=0, column=3, sticky="ew", padx=4, pady=4)
        self.dir_combo.bind("<<ComboboxSelected>>", lambda e: self._update_hint())
        self.dir_var.trace_add("write", lambda *a: self._update_hint())
        self.name_var.trace_add("write", lambda *a: self._update_hint())
        self.custom_dirs = []
        ttk.Button(self.named_frame, text="浏览…", command=self._on_browse_dir).grid(
            row=0, column=4, sticky="w", padx=8, pady=4)

        # prefix row (subframe so the whole row can be toggled)
        self.prefix_frame = ttk.Frame(create)
        self.prefix_frame.grid(row=2, column=0, columnspan=4, sticky="ew")
        self.prefix_frame.columnconfigure(1, weight=1)
        ttk.Label(self.prefix_frame, text="创建位置：").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.prefix_var = tk.StringVar()
        ttk.Entry(self.prefix_frame, textvariable=self.prefix_var).grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(self.prefix_frame, text="浏览…", command=self._on_browse).grid(row=0, column=2, sticky="w", padx=8, pady=4)
        self.prefix_var.trace_add("write", lambda *a: self._update_hint())

        # python version + create button
        ttk.Label(create, text="Python 版本：").grid(row=3, column=0, sticky="w", padx=8, pady=(4, 8))
        self.pyvar = tk.StringVar(value=conda_api.DEFAULT_PYTHON_VERSIONS[2])
        self.py_combo = ttk.Combobox(create, textvariable=self.pyvar, values=list(conda_api.DEFAULT_PYTHON_VERSIONS))
        self.py_combo.grid(row=3, column=1, sticky="w", padx=4, pady=(4, 8))
        self.create_btn = ttk.Button(create, text="创建环境", command=self._on_create)
        self.create_btn.grid(row=3, column=2, columnspan=2, sticky="e", padx=8, pady=(4, 8))

        self.hint_var = tk.StringVar()
        ttk.Label(create, textvariable=self.hint_var, foreground="#666").grid(
            row=4, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 6))

        self._show_named_row()
        self._update_hint()

        # --- env list -----------------------------------------------------
        lst = ttk.LabelFrame(self, text="已有环境")
        lst.pack(fill="both", expand=True, **pad)
        columns = ("name", "path", "status")
        self.tree = ttk.Treeview(lst, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("name", text="名称")
        self.tree.heading("path", text="路径")
        self.tree.heading("status", text="状态")
        self.tree.column("name", width=180, anchor="w")
        self.tree.column("path", width=420, anchor="w")
        self.tree.column("status", width=90, anchor="center")
        vsb = ttk.Scrollbar(lst, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        vsb.pack(side="left", fill="y", padx=(2, 8), pady=8)

        self.delete_btn = ttk.Button(lst, text="删除所选环境", command=self._on_delete)
        self.delete_btn.pack(side="bottom", anchor="e", padx=8, pady=(0, 8))

        # --- log ----------------------------------------------------------
        log = ttk.LabelFrame(self, text="输出日志")
        log.pack(fill="both", **pad)
        self.log_text = tk.Text(log, height=8, state="disabled", wrap="none")
        self.log_text.tag_configure("err", foreground="#c00")
        self.log_text.tag_configure("ok", foreground="#080")
        self.log_text.tag_configure("cmd", foreground="#333", font=("TkDefaultFont", 9, "bold"))
        log_vsb = ttk.Scrollbar(log, orient="vertical", command=self.log_text.yview)
        log_hsb = ttk.Scrollbar(log, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=log_vsb.set, xscrollcommand=log_hsb.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
        log_vsb.pack(side="right", fill="y", padx=(0, 8), pady=6)
        log_hsb.pack(side="bottom", fill="x", padx=(8, 0), pady=(0, 6))

    # ------------------------------------------------------------------ helpers

    def _show_named_row(self):
        if self.env_type.get() == "named":
            self.named_frame.grid()
            self.prefix_frame.grid_remove()
        else:
            self.prefix_frame.grid()
            self.named_frame.grid_remove()

    def _update_hint(self):
        if not self.conda_ok or not self.info:
            self.hint_var.set("请先选择 conda 后创建环境")
            return
        if self.env_type.get() == "named":
            name = self.name_var.get().strip()
            folder = self.dir_var.get() or ""
            if not name:
                self.hint_var.set("输入环境名称后显示创建位置")
                return
            self.hint_var.set(f"将创建于：{os.path.join(folder, name) if folder else '?'}")
        else:
            path = self.prefix_var.get().strip()
            self.hint_var.set(f"将创建于：{conda_api.resolve_prefix_env_path(path)}" if path
                              else "输入或浏览选择前缀环境目录（环境将放入该目录下的 .conda 文件夹）")

    def _append_log(self, line, tag=None):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.create_btn.configure(state=state)
        self.delete_btn.configure(state=state)
        self.refresh_btn.configure(state=state)

    def _set_status(self, text, ok=None):
        self.status_var.set(text)
        self.status_lbl.configure(foreground=("#080" if ok else "#c00") if ok is not None else "#555")

    # ------------------------------------------------------------------ queue

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "status":
                    self._set_status(*payload)
                elif kind == "log":
                    self._append_log(*payload)
                elif kind == "env_list":
                    self._show_envs(*payload)
                elif kind == "detected":
                    self._on_detected(*payload)
                elif kind == "detect_failed":
                    self._on_detect_failed(*payload)
                elif kind == "create_done":
                    self._on_create_done(*payload)
                elif kind == "remove_done":
                    self._on_remove_done(*payload)
                elif kind == "error":
                    messagebox.showerror("错误", payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _enqueue(self, kind, *payload):
        self.q.put((kind, payload))

    # ------------------------------------------------------------------ conda

    def _startup(self):
        self._detect_conda()

    def _detect_conda(self, preferred=None):
        self._set_status("正在检测 conda…")

        def work():
            conda = conda_api.find_conda(preferred)
            if not conda:
                self._enqueue("detect_failed", "未找到 conda，请手动选择 conda.exe 位置。")
                return
            try:
                info = conda_api.conda_info(conda)
            except conda_api.CondaError as e:
                self._enqueue("detect_failed", str(e))
                return
            self._enqueue("detected", conda, info)

        threading.Thread(target=work, daemon=True).start()

    def _on_detected(self, conda, info):
        self.conda = conda
        self.info = info
        self.conda_ok = True
        self.dir_combo.configure(values=list(info["envs_dirs"]) + list(self.custom_dirs))
        self.dir_var.set(info["envs_dirs"][0])
        self._set_status(f"已定位：{conda}（base：{info['base']}）", ok=True)
        self._update_hint()
        self._refresh_all()

    def _on_detect_failed(self, message):
        self.conda_ok = False
        self._set_status(message, ok=False)
        self._update_hint()

    def _on_choose_conda(self):
        path = filedialog.askopenfilename(
            title="选择 conda 可执行文件",
            filetypes=[("conda", "conda.exe conda.bat"), ("所有文件", "*.*")],
        )
        if path:
            self._detect_conda(path)

    def _refresh_all(self):
        if not self.conda_ok:
            return

        def work():
            try:
                info = conda_api.conda_info(self.conda)
                envs = conda_api.list_envs(self.conda, info["base"], info["envs_dirs"])
            except conda_api.CondaError as e:
                self._enqueue("error", str(e))
                return
            self._enqueue("env_list", envs)

        threading.Thread(target=work, daemon=True).start()

    def _show_envs(self, envs):
        self.envs = envs
        self.tree.delete(*self.tree.get_children())
        for env in envs:
            self.tree.insert(
                "", "end", values=(
                    env["name"], env["path"], "受保护" if env["is_base"] else "",
                ),
            )
        self._update_hint()

    # ------------------------------------------------------------------ create

    def _on_type_change(self):
        self._show_named_row()
        self._update_hint()

    def _on_browse(self):
        path = filedialog.askdirectory(title="选择前缀环境创建位置")
        if path:
            self.prefix_var.set(path)

    def _on_browse_dir(self):
        path = filedialog.askdirectory(title="选择环境目录（用于命名环境）")
        if path:
            if path not in self.custom_dirs:
                self.custom_dirs.append(path)
                self.dir_combo.configure(values=list(self.info["envs_dirs"]) + self.custom_dirs)
            self.dir_var.set(path)

    def _build_create_cmd(self):
        version = self.pyvar.get().strip()
        if not version:
            raise ValueError("请指定 Python 版本")
        if self.env_type.get() == "named":
            name = self.name_var.get().strip()
            if not name:
                raise ValueError("请输入环境名称")
            bad = [c for c in name if c in INVALID_NAME_CHARS]
            if bad:
                raise ValueError(f"环境名称包含非法字符：{''.join(sorted(set(bad)))}")
            if any(e["name"] == name for e in self.envs):
                raise ValueError(f"环境 '{name}' 已存在")
            selected_dir = self.dir_var.get().rstrip("\\/")
            if not selected_dir:
                raise ValueError("请选择环境目录")
            envs_dirs_norm = {os.path.normcase(d.rstrip("\\/")) for d in self.info["envs_dirs"]}
            if os.path.normcase(selected_dir) not in envs_dirs_norm and not os.path.isabs(selected_dir):
                raise ValueError("自定义环境目录必须为绝对路径")
            default_dir = self.info["envs_dirs"][0].rstrip("\\/")
            if os.path.normcase(selected_dir) == os.path.normcase(default_dir):
                args = conda_api.build_create_args(self.conda, name=name, python_version=version)
            else:
                args = conda_api.build_create_args(self.conda, prefix=os.path.join(selected_dir, name),
                                                   python_version=version)
        else:
            path = self.prefix_var.get().strip()
            if not path:
                raise ValueError("请输入前缀环境创建位置")
            if not os.path.isabs(path):
                raise ValueError("前缀环境位置必须为绝对路径")
            args = conda_api.build_create_args(self.conda, prefix=conda_api.resolve_prefix_env_path(path),
                                               python_version=version)
        return args

    def _on_create(self):
        if not self.conda_ok:
            messagebox.showwarning("提示", "尚未定位 conda，无法创建环境。")
            return
        try:
            args = self._build_create_cmd()
        except ValueError as e:
            messagebox.showwarning("输入有误", str(e))
            return

        self._set_busy(True)
        self._append_log("$ " + " ".join(args), "cmd")
        self._append_log("正在创建环境，请稍候…")

        def work():
            rc = conda_api.run_streaming(
                args,
                on_out=lambda l: self._enqueue("log", l),
                on_err=lambda l: self._enqueue("log", l, "err"),
            )
            self._enqueue("create_done", rc, args)

        threading.Thread(target=work, daemon=True).start()

    def _on_create_done(self, rc, args):
        if rc == 0:
            self._append_log("[成功] 环境创建成功。", "ok")
        else:
            self._append_log(f"[失败] 环境创建失败（退出码 {rc}），请查看上方输出。", "err")
        self._set_busy(False)
        self._refresh_all()

    # ------------------------------------------------------------------ delete

    def _on_delete(self):
        if not self.conda_ok:
            return
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选中要删除的环境。")
            return
        env = next((e for e in self.envs if e["name"] == self.tree.item(sel[0])["values"][0]), None)
        if not env:
            return
        if env["is_base"]:
            messagebox.showwarning("无法删除", "base 环境受保护，不能删除。")
            return
        target = f"环境 '{env['name']}'（{env['path']}）"
        if not messagebox.askyesno("确认删除", f"确定要删除{target}吗？此操作不可撤销。"):
            return

        if env["name"] == env["path"]:
            args = conda_api.build_remove_args(self.conda, prefix=env["path"])
        else:
            args = conda_api.build_remove_args(self.conda, name=env["name"])

        self._set_busy(True)
        self._append_log("$ " + " ".join(args), "cmd")
        self._append_log("正在删除环境，请稍候…")

        def work():
            rc = conda_api.run_streaming(
                args,
                on_out=lambda l: self._enqueue("log", l),
                on_err=lambda l: self._enqueue("log", l, "err"),
            )
            self._enqueue("remove_done", rc)

        threading.Thread(target=work, daemon=True).start()

    def _on_remove_done(self, rc):
        if rc == 0:
            self._append_log("[成功] 环境删除成功。", "ok")
        else:
            self._append_log(f"[失败] 环境删除失败（退出码 {rc}），请查看上方输出。", "err")
        self._set_busy(False)
        self._refresh_all()


def main():
    app = CondaEnvManagerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
