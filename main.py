"""环境检测工具 GUI"""
import os
import shutil
import threading
import tkinter as tk
from tkinter import ttk, messagebox


class _TrackedLines:
    """追踪每行状态，只在变化时重渲染"""
    def __init__(self):
        self.lines = []
        self.last = ""
    def update(self, line):
        self.lines.append(line)
        # 只保留最后 20 行
        if len(self.lines) > 20:
            self.lines = self.lines[-20:]
    def render(self):
        s = "\n".join(self.lines)
        if s != self.last:
            self.last = s
        return s

from checker import (
    ALL_CHECKS, run_checks, get_available_drives,
    install_python_package, install_node_package, install_conda_package,
    uninstall_python_package, uninstall_node_package, uninstall_conda_package,
    delete_conda_env, delete_python_venv,
    create_python_venv, create_conda_env,
    open_url,
)


class EnvCheckerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("环境检测工具")
        self.root.geometry("880x640")
        # 保证最窄时按钮栏所有按钮都可见
        self.root.minsize(680, 460)

        self.check_vars = {}
        self.drive_vars = {}
        self.drive_all_var = tk.BooleanVar(value=True)
        self.custom_envs = []
        self.results = []
        self.item_to_result = {}
        self.install_cancel_event = None
        self.installing = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    # --------------- UI 构建 ---------------

    def _build_ui(self):
        # 标题
        tk.Label(self.root, text="Echecker",
                 font=("Microsoft YaHei", 14, "bold"),
                 bg="#f0f0f0", fg="#2c3e50").pack(pady=(12, 6))

        # 底部按钮栏 — 先占位，永远可见
        bottom = tk.Frame(self.root, bg="#f0f0f0")
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 8))
        ttk.Button(bottom, text="全选", command=self._select_all).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="清除选择", command=self._clear_all).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="检测选中项", command=self._start_check).pack(side=tk.LEFT, padx=3)
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=200)
        self.progress.pack(side=tk.LEFT, padx=10)
        self.cancel_btn = ttk.Button(bottom, text="取消安装", command=self._cancel_install,
                                     state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="复制报告", command=self._copy_report).pack(side=tk.RIGHT, padx=3)

        # 主体 — PanedWindow 左右两栏
        pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
        self._build_left(pane)
        self._build_right(pane)

    def _build_left(self, parent):
        left = ttk.LabelFrame(parent, text="设置", padding=4)
        parent.add(left, weight=1)

        # 底部固定：自定义输入 + 添加按钮
        custom = ttk.LabelFrame(left, text="自定义检测", padding=4)
        custom.pack(side=tk.BOTTOM, fill=tk.X)
        row = tk.Frame(custom); row.pack(fill=tk.X)
        self.custom_var = tk.StringVar()
        entry = tk.Entry(row, textvariable=self.custom_var, font=("Consolas", 9))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry.bind("<Return>", lambda e: self._add_custom())
        ttk.Button(row, text="添加", command=self._add_custom).pack(side=tk.RIGHT, padx=(4, 0))

        # 可滚动区域 — 填满剩余空间
        canvas = tk.Canvas(left, bg="#f0f0f0", highlightthickness=0)
        vsb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)

        self._left_inner = tk.Frame(canvas, bg="#f0f0f0")
        self._left_win = canvas.create_window((0, 0), window=self._left_inner, anchor=tk.NW)

        canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        def _conf_scroll(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # 用 canvas 可见高度做判断（inner 的 reqheight 在缩放时可能不变）
            bbox = canvas.bbox("all")
            if bbox and bbox[3] > canvas.winfo_height():
                vsb.pack(side=tk.RIGHT, fill=tk.Y)
            else:
                vsb.pack_forget()
        self._left_inner.bind("<Configure>", _conf_scroll)

        def _conf_cv(event=None):
            if event:
                canvas.itemconfig(self._left_win, width=event.width)
            _conf_scroll()
        canvas.bind("<Configure>", _conf_cv, add="+")

        def _enter(e):
            canvas.bind_all("<MouseWheel>", lambda ev: canvas.yview_scroll(
                int(-1 * (ev.delta / 120)), "units"))
        def _leave(e):
            canvas.unbind_all("<MouseWheel>")
        canvas.bind("<Enter>", _enter)
        canvas.bind("<Leave>", _leave)

        inner = self._left_inner

        tk.Label(inner, text="检测项:", font=("Microsoft YaHei", 10, "bold"),
                 bg="#f0f0f0", anchor=tk.W).pack(fill=tk.X)
        self.check_box = tk.Frame(inner, bg="#ffffff", bd=1, relief=tk.SOLID)
        self.check_box.pack(fill=tk.X, pady=(4, 10))
        self._custom_check_vars = {}  # name -> BooleanVar (for custom items)
        self._custom_check_rows = {}  # name -> (frame, var) for removal
        for name in ALL_CHECKS:
            var = tk.BooleanVar(value=True)
            self.check_vars[name] = var
            tk.Checkbutton(self.check_box, text=name, variable=var,
                           font=("Microsoft YaHei", 10), bg="#ffffff",
                           activebackground="#e8f0fe", anchor=tk.W,
                           padx=8, pady=3).pack(fill=tk.X)

        tk.Label(inner, text="扫描范围:", font=("Microsoft YaHei", 10, "bold"),
                 bg="#f0f0f0", anchor=tk.W).pack(fill=tk.X)
        drive_box = tk.Frame(inner, bg="#ffffff", bd=1, relief=tk.SOLID)
        drive_box.pack(fill=tk.X, pady=(4, 0))
        tk.Checkbutton(drive_box, text="全盘扫描", variable=self.drive_all_var,
                       command=self._toggle_all_drives, font=("Microsoft YaHei", 9, "bold"),
                       bg="#ffffff", activebackground="#e8f0fe", anchor=tk.W,
                       padx=8, pady=2).pack(fill=tk.X)
        for drive in get_available_drives():
            var = tk.BooleanVar(value=True)
            self.drive_vars[drive] = var
            tk.Checkbutton(drive_box, text="  " + drive, variable=var,
                           font=("Microsoft YaHei", 9), bg="#ffffff",
                           activebackground="#e8f0fe", anchor=tk.W,
                           padx=24, pady=1).pack(fill=tk.X)

    def _build_right(self, parent):
        right = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        parent.add(right, weight=3)

        # 上：结果树
        tree_frame = ttk.LabelFrame(right, text="检测结果", padding=4)
        right.add(tree_frame, weight=1)
        self.tree = ttk.Treeview(tree_frame, columns=("status", "version"), show="tree headings")
        self.tree.heading("#0", text="环境", anchor=tk.W)
        self.tree.heading("status", text="", anchor=tk.CENTER)
        self.tree.heading("version", text="版本/状态", anchor=tk.W)
        self.tree.column("#0", width=300)
        self.tree.column("status", width=36, anchor=tk.CENTER, stretch=False)
        self.tree.column("version", width=220)
        self.tree.tag_configure("found", foreground="#1a7a1a")
        self.tree.tag_configure("missing", foreground="#c0392b")
        self.tree.tag_configure("child", foreground="#4a4a4a")
        tree_vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # 下：详情 + 操作按钮
        detail_frame = ttk.LabelFrame(right, text="详情与操作", padding=4)
        right.add(detail_frame, weight=1)

        # 按钮栏 — Canvas + 水平滚动条，按钮超出时自动可滑
        btn_outer = tk.Frame(detail_frame, bg="#f0f0f0", height=52)
        btn_outer.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))
        btn_outer.pack_propagate(False)

        self._btn_canvas = tk.Canvas(btn_outer, bg="#f0f0f0", height=34, highlightthickness=0)
        self._btn_hscroll = ttk.Scrollbar(btn_outer, orient=tk.HORIZONTAL,
                                          command=self._btn_canvas.xview)
        self._btn_canvas.configure(xscrollcommand=self._btn_hscroll.set)

        self.btn_frame = tk.Frame(self._btn_canvas, bg="#f0f0f0")
        self._btn_win = self._btn_canvas.create_window((0, 0), window=self.btn_frame, anchor=tk.NW)

        self._btn_canvas.pack(side=tk.TOP, fill=tk.X, expand=True)

        def _btn_check_scroll(event=None):
            self._btn_canvas.configure(scrollregion=self._btn_canvas.bbox("all"))
            bbox = self._btn_canvas.bbox("all")
            if bbox and bbox[2] > self._btn_canvas.winfo_width():
                self._btn_hscroll.pack(side=tk.BOTTOM, fill=tk.X)
            else:
                self._btn_hscroll.pack_forget()
        self.btn_frame.bind("<Configure>", _btn_check_scroll)
        self._btn_canvas.bind("<Configure>", lambda e: (
            self._btn_canvas.itemconfig(self._btn_win, width=e.width),
            _btn_check_scroll()), add="+")

        def _btn_wheel(event):
            self._btn_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
        self._btn_canvas.bind("<Enter>",
                              lambda e: self._btn_canvas.bind_all("<MouseWheel>", _btn_wheel))
        self._btn_canvas.bind("<Leave>",
                              lambda e: self._btn_canvas.unbind_all("<MouseWheel>"))

        # 详情文本 — 填满剩余空间
        self.detail = tk.Text(detail_frame, wrap=tk.WORD, font=("Microsoft YaHei", 9),
                              bg="#fafafa", padx=6, pady=4)
        self.detail.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.detail.configure(state=tk.DISABLED)
        self.detail.tag_configure("h1", font=("Microsoft YaHei", 11, "bold"))
        self.detail.tag_configure("ok", foreground="#1a7a1a")
        self.detail.tag_configure("fail", foreground="#c0392b")
        self.detail.tag_configure("info", foreground="#333")
        self.detail.tag_configure("path", foreground="#555")

    # --------------- 操作逻辑 ---------------

    def _toggle_all_drives(self):
        for var in self.drive_vars.values():
            var.set(self.drive_all_var.get())

    def _select_all(self):
        for var in self.check_vars.values():
            var.set(True)
        for var in self._custom_check_vars.values():
            var.set(True)

    def _clear_all(self):
        for var in self.check_vars.values():
            var.set(False)
        for var in self._custom_check_vars.values():
            var.set(False)

    def _add_custom(self):
        name = self.custom_var.get().strip()
        if not name:
            return
        # 大小写不敏感去重：与内置检测项 + 已添加自定义项比较
        all_lower = [k.lower() for k in ALL_CHECKS] + [k.lower() for k in self._custom_check_vars]
        if name.lower() in all_lower:
            messagebox.showinfo("提示", '"%s" 已在检测列表中' % name)
            return

        self.custom_envs.append(name)
        var = tk.BooleanVar(value=True)
        row = tk.Frame(self.check_box, bg="#ffffff")
        row.pack(fill=tk.X)
        cb = tk.Checkbutton(row, text=name, variable=var,
                            font=("Microsoft YaHei", 10), bg="#ffffff",
                            fg="#2980b9", activebackground="#e8f0fe",
                            anchor=tk.W, padx=8, pady=3)
        cb.pack(side=tk.LEFT)
        lbl = tk.Label(row, text="✕", fg="#c0392b", bg="#ffffff",
                       font=("Microsoft YaHei", 8), cursor="hand2")
        lbl.pack(side=tk.RIGHT, padx=(0, 8))
        lbl.bind("<Button-1>", lambda e, n=name, r=row: self._remove_custom(n, r))

        self.check_vars[name] = var
        self._custom_check_vars[name] = var
        self._custom_check_rows[name] = (row, var)
        self.custom_var.set("")

    def _remove_custom(self, name, row):
        if name in self.custom_envs:
            self.custom_envs.remove(name)
        self.check_vars.pop(name, None)
        self._custom_check_vars.pop(name, None)
        self._custom_check_rows.pop(name, None)
        row.destroy()

    def _selected_custom_envs(self):
        """返回勾选中的自定义环境名列表"""
        return [name for name, var in self._custom_check_vars.items() if var.get()]

    def _selected_drives(self):
        if not self.drive_all_var.get():
            return None
        return [d for d, v in self.drive_vars.items() if v.get()]

    def _start_check(self):
        selected = [name for name, var in self.check_vars.items() if var.get()]
        custom = self._selected_custom_envs()
        if not selected and not custom:
            messagebox.showinfo("提示", "请至少勾选一项或添加自定义环境")
            return
        self.progress.start(10)
        self._set_detail("正在检测...", keep_progress=True)
        threading.Thread(
            target=self._run_checks,
            args=(selected, self._selected_drives(), custom),
            daemon=True).start()

    def _run_checks(self, selected, drives, custom):
        results = run_checks(selected, drives=drives, custom=custom)
        self.root.after(0, self._fill_tree, results)

    def _fill_tree(self, results):
        self.progress.stop()
        self.results = results
        self.tree.delete(*self.tree.get_children())
        self.item_to_result.clear()
        self._clear_detail()
        for result in results:
            iid = self._insert_result("", result, is_child=False)
            for child in result.get("children", []):
                self._insert_result(iid, child, is_child=True)

    def _reload_tree(self):
        """重新渲染当前 results（用于创建后刷新）"""
        self.tree.delete(*self.tree.get_children())
        self.item_to_result.clear()
        for result in self.results:
            iid = self._insert_result("", result, is_child=False)
            for child in result.get("children", []):
                self._insert_result(iid, child, is_child=True)

    def _remove_child_from_tree(self, child_result):
        """从父级 children 和 Treeview 中移除指定子结果"""
        # 从 results 中找到父级并移除 children 条目
        for parent in self.results:
            children = parent.get("children", [])
            for c in children:
                if c is child_result:
                    children.remove(c)
                    break
            else:
                continue
            break
        # 从 Treeview 中移除对应行
        for iid, r in list(self.item_to_result.items()):
            if r is child_result:
                self.tree.delete(iid)
                del self.item_to_result[iid]
                break
        self._clear_detail()

    def _insert_result(self, parent_iid, result, is_child=False):
        symbol = "OK" if result.get("found") else "NO"
        version = result.get("version", "") if result.get("found") else "未安装"
        tag = "child" if is_child else ("found" if result.get("found") else "missing")
        iid = self.tree.insert(parent_iid, tk.END, text=result["name"],
                               values=(symbol, version), tags=(tag,))
        self.item_to_result[iid] = result
        return iid

    def _on_select(self, event):
        sel = self.tree.selection()
        if sel:
            result = self.item_to_result.get(sel[0])
            if result:
                self._show_detail(result)

    def _clear_detail(self):
        self._set_detail("")
        for w in self.btn_frame.winfo_children():
            w.destroy()
        if hasattr(self, '_btn_canvas'):
            self._btn_canvas.xview_moveto(0)

    def _set_detail(self, text, keep_progress=False):
        if not keep_progress:
            self.progress.stop()
        self.detail.configure(state=tk.NORMAL)
        self.detail.delete("1.0", tk.END)
        if text:
            self.detail.insert(tk.END, text + "\n", "info")
        self.detail.configure(state=tk.DISABLED)

    # --------------- 详情展示 ---------------

    def _show_detail(self, result):
        self._clear_detail()
        if result.get("found"):
            self._show_found(result)
        else:
            self._show_missing(result)

    def _show_found(self, result):
        d = self.detail
        d.configure(state=tk.NORMAL)
        d.insert(tk.END, result["name"] + "  ", "h1")
        d.insert(tk.END, "已安装\n", "ok")
        d.insert(tk.END, "版本: %s\n" % result.get("version", ""), "info")
        if result.get("path"):
            d.insert(tk.END, "路径: %s\n" % result["path"], "path")

        env_type = result.get("env_type", "system")
        if env_type == "python_venv":
            d.insert(tk.END, "类型: Python 虚拟环境\n", "info")
        elif env_type == "conda_env":
            d.insert(tk.END, "类型: Conda 虚拟环境\n", "info")
        elif env_type in ("python", "conda"):
            d.insert(tk.END, "虚拟环境: 支持 (点击左侧 [+] 展开查看)\n", "info")
        elif env_type == "custom":
            pass
        else:
            d.insert(tk.END, "虚拟环境: 无 (该环境不支持虚拟环境)\n", "info")

        for key, value in result.get("details", {}).items():
            if key != "environments":
                d.insert(tk.END, "%s: %s\n" % (key, value), "info")

        pkgs = result.get("installed_pkgs", [])
        missing = result.get("missing_pkgs", [])
        if pkgs:
            d.insert(tk.END, "\n已安装的包: %d 个\n" % len(pkgs), "info")
            d.insert(tk.END, ", ".join(pkgs[:30]), "info")
            if len(pkgs) > 30:
                d.insert(tk.END, "\n... 还有 %d 个" % (len(pkgs) - 30), "info")
        if missing:
            d.insert(tk.END, "\n\n推荐安装 (共%d个未装): " % len(missing), "fail")
            d.insert(tk.END, ", ".join(missing[:10]), "info")
        d.configure(state=tk.DISABLED)

        # 操作按钮 — 直接 pack 在 btn_frame
        if pkgs:
            ttk.Button(self.btn_frame, text="查看全部已安装的包",
                       command=lambda r=result: self._popup_pkg_list(r)
                       ).pack(side=tk.LEFT, padx=2, pady=2)
        if self._install_fn(result["name"]):
            ttk.Button(self.btn_frame, text="选择安装...",
                       command=lambda r=result: self._popup_install_list(r, "install")
                       ).pack(side=tk.LEFT, padx=2, pady=2)
        if pkgs:
            ttk.Button(self.btn_frame, text="移除已安装的包...",
                       command=lambda r=result: self._popup_install_list(r, "uninstall")
                       ).pack(side=tk.LEFT, padx=2, pady=2)
        if result.get("deletable") and env_type in ("conda_env", "python_venv"):
            ttk.Button(self.btn_frame, text="删除此环境",
                       command=lambda r=result: self._confirm_delete_env(r)
                       ).pack(side=tk.RIGHT, padx=2, pady=2)
        if env_type in ("python", "conda"):
            ttk.Button(self.btn_frame, text="创建虚拟环境",
                       command=lambda r=result: self._popup_create_env(r)
                       ).pack(side=tk.LEFT, padx=2, pady=2)

    def _show_missing(self, result):
        d = self.detail
        d.configure(state=tk.NORMAL)
        d.insert(tk.END, result["name"] + "  ", "h1")
        d.insert(tk.END, "未安装\n", "fail")
        d.insert(tk.END, "系统中未检测到该环境。\n", "info")
        d.configure(state=tk.DISABLED)
        if result.get("download_url"):
            ttk.Button(self.btn_frame, text="访问下载页面",
                       command=lambda url=result["download_url"]: open_url(url)
                       ).pack(side=tk.LEFT, padx=2, pady=2)

    # --------------- 安装/卸载 ---------------

    def _install_fn(self, name):
        if name.startswith("Conda"):
            return install_conda_package
        if name.startswith("Python"):
            return install_python_package
        if name.startswith("Node.js"):
            return install_node_package
        return None

    def _uninstall_fn(self, name):
        if name.startswith("Conda"):
            return uninstall_conda_package
        if name.startswith("Python"):
            return uninstall_python_package
        if name.startswith("Node.js"):
            return uninstall_node_package
        return None

    def _begin_install(self, msg):
        if self.installing:
            messagebox.showinfo("提示", "已有安装任务正在执行，请先等待或取消。")
            return None
        self.installing = True
        self.install_cancel_event = threading.Event()
        self.cancel_btn.configure(state=tk.NORMAL)
        self.progress.configure(mode="indeterminate")
        self.progress.start(10)
        self._set_detail(msg, keep_progress=True)
        return self.install_cancel_event

    def _show_progress(self, msg):
        """详情区实时追加一行进度"""
        self._set_detail(msg, keep_progress=True)

    def _finish_install(self, title, msg):
        self.progress.stop()
        self.installing = False
        self.install_cancel_event = None
        self.cancel_btn.configure(state=tk.DISABLED)
        self._set_detail(msg)
        messagebox.showinfo(title, msg[-2500:])

    def _refresh_pkgs(self, result, new_pkgs):
        """安装后将新包添加到 result 的 installed_pkgs，更新 missing_pkgs"""
        pkgs = list(result.get("installed_pkgs", []))
        added = []
        for pkg in new_pkgs:
            pkg_lower = pkg.lower()
            if pkg_lower not in pkgs:
                pkgs.append(pkg_lower)
                added.append(pkg_lower)
        result["installed_pkgs"] = pkgs
        rm_set = set(p.lower() for p in new_pkgs)
        result["missing_pkgs"] = [p for p in result.get("missing_pkgs", [])
                                   if p.lower() not in rm_set]

    def _remove_pkgs(self, result, removed_pkgs):
        """卸载后从 result 的 installed_pkgs 中移除"""
        rm_set = set(p.lower() for p in removed_pkgs)
        result["installed_pkgs"] = [p for p in result.get("installed_pkgs", [])
                                     if p.lower() not in rm_set]

    def _cancel_install(self):
        if self.install_cancel_event is not None:
            self.install_cancel_event.set()
            self.cancel_btn.configure(state=tk.DISABLED)
            self._set_detail("正在取消安装，并清理本次已安装的包...", keep_progress=True)

    def _rollback(self, result, pkgs):
        fn = self._uninstall_fn(result["name"])
        messages = []
        if not fn:
            return messages
        for pkg in reversed(pkgs):
            ok, out = fn(pkg, result)
            messages.append("%s: %s" % (pkg, "已清理" if ok else "清理失败"))
            if out:
                messages.append(out[-300:])
        return messages

    def _install_batch(self, result, pkgs):
        fn = self._install_fn(result["name"])
        if not fn:
            messagebox.showinfo("提示", "%s 不支持包安装" % result["name"])
            return
        total = len(pkgs)
        event = self._begin_install("安装进度 (0/%d) ..." % total)
        if event is None:
            return

        lines = _TrackedLines()

        def worker(f=fn):
            ok_count = 0
            installed_now = []
            failed = []
            outputs = []
            for index, pkg in enumerate(pkgs, 1):
                if event.is_set():
                    break
                i, t, p = index, total, pkg
                lines.update("[%d/%d] %s" % (i, t, p))
                self.root.after(0, lambda: self._set_detail(lines.render(), keep_progress=True))
                ok, out = f(pkg, result, cancel_event=event,
                            on_progress=lambda msg: self.root.after(0, self._show_progress, msg))
                outputs.append("===== %s =====\n%s" % (pkg, out[-1200:]))
                if ok:
                    ok_count += 1
                    installed_now.append(pkg)
                    lines.update("[OK %d/%d] %s" % (i, t, p))
                else:
                    failed.append(pkg)
                    lines.update("[FAIL %d/%d] %s" % (i, t, p))
                self.root.after(0, lambda: self._set_detail(lines.render(), keep_progress=True))

            cancelled = event.is_set()
            cleanup = []
            if cancelled and installed_now:
                self.root.after(0, lambda: self._set_detail(
                    "正在取消安装，并清理本次已安装的包...", keep_progress=True))
                cleanup = self._rollback(result, installed_now)

            if cancelled:
                title = "安装已取消"
                msg = "安装已取消，已成功安装的 %d 个包已尝试清理。\n\n%s" % (
                    len(installed_now), "\n".join(cleanup + outputs[-2:]))
            elif failed:
                if ok_count == 0:
                    title = "安装失败"
                    msg = "安装失败: %d 个包均未成功。\n失败原因:\n\n%s" % (
                        total, "\n\n".join(outputs[-3:]))
                else:
                    title = "安装部分成功"
                    msg = "%d/%d 安装成功, %d 失败。\n失败包: %s\n\n%s" % (
                        ok_count, total, len(failed), ", ".join(failed),
                        "\n\n".join(outputs[-3:]))
            else:
                title = "安装成功"
                msg = "全部安装完毕: %d/%d 成功。" % (ok_count, total)

            if installed_now:
                self.root.after(0, lambda r=result, new=installed_now: self._refresh_pkgs(r, new))

            # 最终进度 + 结果合并显示
            final = lines.render() + "\n\n" + msg
            self.root.after(0, lambda t=title, m=final: self._finish_install(t, m))

        threading.Thread(target=worker, daemon=True).start()

    def _uninstall_batch(self, result, pkgs):
        fn = self._uninstall_fn(result["name"])
        if not fn:
            messagebox.showinfo("提示", "%s 不支持卸载" % result["name"])
            return
        total = len(pkgs)
        self._begin_install("卸载进度 (0/%d) ..." % total)

        lines = _TrackedLines()

        def worker(f=fn):
            ok_count = 0
            removed = []
            outputs = []
            for index, pkg in enumerate(pkgs, 1):
                i, t, p = index, total, pkg
                lines.update("[%d/%d] %s" % (i, t, p))
                self.root.after(0, lambda: self._set_detail(lines.render(), keep_progress=True))
                ok, out = f(pkg, result,
                            on_progress=lambda msg: self.root.after(0, self._show_progress, msg))
                outputs.append("===== %s =====\n%s" % (pkg, out[-800:]))
                if ok:
                    ok_count += 1
                    removed.append(pkg)
                    lines.update("[OK %d/%d] %s" % (i, t, p))
                else:
                    lines.update("[FAIL %d/%d] %s" % (i, t, p))
                self.root.after(0, lambda: self._set_detail(lines.render(), keep_progress=True))

            if removed:
                self.root.after(0, lambda r=result, rm=removed: self._remove_pkgs(r, rm))

            if ok_count == total:
                title, msg = "卸载完成", "全部卸载完毕: %d/%d 成功。" % (ok_count, total)
            elif ok_count == 0:
                title, msg = "卸载失败", "卸载失败: %d 个包均未成功。\n\n%s" % (
                    total, "\n\n".join(outputs[-3:]))
            else:
                title, msg = "卸载部分成功", "%d/%d 卸载成功, %d 失败。\n\n%s" % (
                    ok_count, total, total - ok_count, "\n\n".join(outputs[-3:]))
            final = lines.render() + "\n\n" + msg
            self.root.after(0, lambda t=title, m=final: self._finish_install(t, m))

        threading.Thread(target=worker, daemon=True).start()

    def _popup_create_env(self, result):
        env_type = result.get("env_type", "")
        win = tk.Toplevel(self.root)
        win.title("创建虚拟环境")
        win.geometry("380x180")
        win.minsize(300, 140)
        win.transient(self.root)
        win.grab_set()

        tk.Label(win, text="创建 %s 虚拟环境" % ("Conda" if env_type == "conda" else "Python"),
                 font=("Microsoft YaHei", 10, "bold")).pack(pady=(12, 8))

        row = tk.Frame(win); row.pack(fill=tk.X, padx=16)
        tk.Label(row, text="名称:").pack(side=tk.LEFT)
        name_var = tk.StringVar()
        tk.Entry(row, textvariable=name_var, font=("Consolas", 10)).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        if env_type == "conda":
            py_row = tk.Frame(win); py_row.pack(fill=tk.X, padx=16, pady=(4, 0))
            tk.Label(py_row, text="Python版本 (可选):").pack(side=tk.LEFT)
            py_var = tk.StringVar(value="3.12")
            tk.Entry(py_row, textvariable=py_var, font=("Consolas", 10), width=8).pack(side=tk.LEFT, padx=4)
        else:
            py_var = tk.StringVar()

        def _do_create():
            name = name_var.get().strip()
            if not name:
                messagebox.showinfo("提示", "请输入环境名", parent=win)
                return
            # 检查是否已有同名子环境
            for child in result.get("children", []):
                if any(name.lower() == part.lower()
                       for part in child.get("name", "").replace(": ", " ").replace("(", " ").replace(")", "").split()):
                    messagebox.showinfo("提示",
                                        "已有同名子环境 \"%s\"" % child.get("name", ""),
                                        parent=win)
                    return
            # 检查磁盘上是否已存在
            if env_type == "conda":
                conda_root = os.path.dirname(os.path.dirname(
                    result.get("path", ""))) if "Scripts" in result.get("path", "") else ""
                check = os.path.join(conda_root, "envs", name)
            else:
                check = os.path.join(os.path.dirname(result.get("path", "")), "..", name)
            check = os.path.abspath(check)
            if os.path.exists(check) and os.path.isdir(check):
                messagebox.showinfo("提示",
                                    "目录已存在: %s" % check,
                                    parent=win)
                return
            win.destroy()
            self.progress.configure(mode="indeterminate")
            self.progress.start(10)
            self._set_detail("正在创建虚拟环境 %s ..." % name, keep_progress=True)

            def worker():
                if env_type == "conda":
                    conda_exe = result.get("path", "conda")
                    if not conda_exe.endswith("conda.exe"):
                        conda_exe = "conda"
                    ok, msg = create_conda_env(conda_exe, name,
                                               python_version=py_var.get().strip())
                else:
                    py_exe = result.get("path", "python")
                    ok, msg = create_python_venv(py_exe, name)
                # 成功后把新环境挂到父结果下，刷新树
                if ok:
                    # 从 msg 中提取路径（格式: "...: D:\path" 或 "...: D:\path\n..."）
                    parts = msg.rsplit(": ", 1)
                    target_path = parts[-1].strip().split("\n")[0] if ": " in msg else ""
                    new_child = {
                        "name": "%s env: %s (%s)" % (
                            "Conda" if env_type == "conda" else "Python venv",
                            name,
                            os.path.splitdrive(target_path)[0] if target_path else "?"),
                        "found": True,
                        "version": py_var.get().strip() if env_type == "conda" else "",
                        "path": target_path,
                        "details": {},
                        "download_url": "",
                        "installed_pkgs": [],
                        "missing_pkgs": [],
                        "env_type": "conda_env" if env_type == "conda" else "python_venv",
                        "deletable": True,
                        "children": [],
                    }
                    result.setdefault("children", []).append(new_child)
                    self.root.after(0, lambda: self._reload_tree())
                self.root.after(0, lambda m=msg: self._set_detail(m))
                self.root.after(0, lambda: self.progress.stop())
                self.root.after(0, lambda t="创建%s" % ("成功" if ok else "失败"), m=msg:
                                messagebox.showinfo(t, m))

            threading.Thread(target=worker, daemon=True).start()

        btn_row = tk.Frame(win); btn_row.pack(fill=tk.X, padx=16, pady=(12, 0))
        ttk.Button(btn_row, text="创建", command=_do_create).pack(side=tk.RIGHT, padx=3)
        ttk.Button(btn_row, text="取消", command=win.destroy).pack(side=tk.RIGHT, padx=3)

    def _confirm_delete_env(self, result):
        env_type = result.get("env_type", "")
        label = "Conda 虚拟环境" if env_type == "conda_env" else "Python venv"
        if not messagebox.askyesno(
            "确认删除",
            "确定要删除 %s 吗？\n\n路径: %s\n\n此操作不可恢复！" % (label, result["path"])):
            return
        self.progress.configure(mode="indeterminate")
        self.progress.start(10)
        self._set_detail("正在删除 %s ..." % result["name"], keep_progress=True)

        def worker():
            if env_type == "conda_env":
                conda_exe = result.get("details", {}).get("conda_exe",
                            shutil.which("conda") or "conda")
                ok, msg = delete_conda_env(conda_exe, result["path"])
                if not ok:
                    ok, msg = False, "删除失败，错误原因: %s" % msg[-300:]
            elif env_type == "python_venv":
                ok, msg = delete_python_venv(result["path"])
            else:
                ok, msg = False, "未知环境类型"
            # 删除成功后从结果树中移除
            if ok:
                self.root.after(0, lambda r=result: self._remove_child_from_tree(r))
            self.root.after(0, lambda m=msg: self._set_detail(m))
            self.root.after(0, lambda: self.progress.configure(mode="indeterminate"))
            self.root.after(0, lambda: messagebox.showinfo(
                "删除%s" % ("成功" if ok else "失败"), msg))

        threading.Thread(target=worker, daemon=True).start()

    # --------------- 弹窗 ---------------

    def _popup_pkg_list(self, result):
        win = tk.Toplevel(self.root)
        win.title("%s 已安装的包" % result["name"])
        win.geometry("500x450")
        win.minsize(300, 250)

        # 搜索框
        search_frame = tk.Frame(win)
        search_frame.pack(fill=tk.X, padx=8, pady=6)
        tk.Label(search_frame, text="搜索:", font=("Microsoft YaHei", 9)).pack(side=tk.LEFT)
        search = tk.StringVar()
        tk.Entry(search_frame, textvariable=search, font=("Consolas", 10)).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        tree = ttk.Treeview(win, columns=("pkg",), show="headings")
        tree.heading("pkg", text="包名")
        tree.column("pkg", width=400)
        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        tree_scroll = ttk.Scrollbar(tree, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        pkgs = result.get("installed_pkgs", [])

        def fill(*args):
            needle = search.get().lower()
            tree.delete(*tree.get_children())
            for pkg in pkgs:
                if needle in pkg.lower():
                    tree.insert("", tk.END, values=(pkg,))

        search.trace_add("write", fill)
        fill()
        tk.Label(win, text="共 %d 个包" % len(pkgs), fg="#666").pack(pady=4)

    def _popup_install_list(self, result, mode="install"):
        is_uninstall = mode == "uninstall"
        pkgs = list(result.get("installed_pkgs", []) if is_uninstall
                    else result.get("missing_pkgs", []))
        win = tk.Toplevel(self.root)
        win.title("卸载包" if is_uninstall else "安装包")
        win.geometry("500x580")
        win.minsize(350, 350)

        vars_by_pkg = {}

        def add_pkg(pkg, checked=False):
            pkg = pkg.strip()
            if not pkg or pkg in vars_by_pkg:
                return
            var = tk.BooleanVar(value=checked)
            vars_by_pkg[pkg] = var
            tk.Checkbutton(inner, text=pkg, variable=var, anchor=tk.W,
                           font=("Consolas", 10), padx=4, pady=2).pack(fill=tk.X)

        def action():
            selected = [p for p, var in vars_by_pkg.items() if var.get()]
            if not selected:
                messagebox.showinfo("提示", "请至少选择一项", parent=win)
                return
            win.destroy()
            if is_uninstall:
                self._uninstall_batch(result, selected)
            else:
                self._install_batch(result, selected)

        def add_custom():
            add_pkg(custom_var.get(), checked=True)
            custom_var.set("")

        # 底部按钮 — 先 pack，保证始终可见
        bottom = tk.Frame(win)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=8)
        if not is_uninstall:
            ttk.Button(bottom, text="添加自定义", command=add_custom).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="全选",
                   command=lambda: [v.set(True) for v in vars_by_pkg.values()]
                   ).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="取消全选",
                   command=lambda: [v.set(False) for v in vars_by_pkg.values()]
                   ).pack(side=tk.LEFT, padx=3)
        ttk.Button(bottom, text="卸载选中" if is_uninstall else "安装选中",
                   command=action).pack(side=tk.RIGHT, padx=3)

        # 自定义输入（仅安装模式）
        custom_var = tk.StringVar()
        if not is_uninstall:
            row = tk.Frame(win)
            row.pack(fill=tk.X, padx=8, pady=(8, 4))
            tk.Label(row, text="自定义:").pack(side=tk.LEFT)
            tk.Entry(row, textvariable=custom_var, font=("Consolas", 10)).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        # 搜索跳转（卸载模式显示所有已装包，需搜索定位）
        search_var = tk.StringVar()
        search_row = tk.Frame(win)
        search_row.pack(fill=tk.X, padx=8, pady=(0, 4))
        tk.Label(search_row, text="搜索:", font=("Microsoft YaHei", 9)).pack(side=tk.LEFT)
        search_entry = tk.Entry(search_row, textvariable=search_var, font=("Consolas", 10))
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        def _jump_to_pkg(event=None):
            needle = search_var.get().strip().lower()
            if not needle:
                return
            # 收集当前 inner 里所有 checkbox 的 text
            for child in inner.winfo_children():
                if isinstance(child, tk.Checkbutton):
                    text = child.cget("text").lower()
                    if needle in text:
                        # 获取该 widget 在 scrollregion 中的位置
                        y_pos = child.winfo_y()
                        total = canvas.bbox("all")[3] or 1
                        fraction = y_pos / total if total > 0 else 0
                        canvas.yview_moveto(fraction)
                        child.configure(bg="#fff3cd")
                        win.after(800, lambda w=child: w.configure(bg="#f0f0f0"))
                        return
            messagebox.showinfo("提示", "未找到匹配项", parent=win)

        search_entry.bind("<Return>", _jump_to_pkg)

        # 可滚动复选框区域 — 填满剩余空间
        main = tk.Frame(win)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        canvas = tk.Canvas(main, highlightthickness=0)
        inner = tk.Frame(canvas)
        vsb = ttk.Scrollbar(main, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.create_window((0, 0), window=inner, anchor=tk.NW)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def _cfg_scroll(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            bbox = canvas.bbox("all")
            if bbox and bbox[3] > canvas.winfo_height():
                vsb.pack(side=tk.RIGHT, fill=tk.Y)
            else:
                vsb.pack_forget()
        inner.bind("<Configure>", _cfg_scroll)

        def _cfg_cv(event=None):
            if event:
                for w in canvas.find_all():
                    canvas.itemconfig(w, width=event.width)
            _cfg_scroll()
        canvas.bind("<Configure>", _cfg_cv, add="+")

        def _popup_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _popup_wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        for pkg in pkgs:
            add_pkg(pkg)
        if not pkgs:
            tk.Label(inner, text="（无推荐包，请使用上方自定义输入）",
                     fg="#777").pack(pady=20)

    # --------------- 复制报告 ---------------

    def _copy_report(self):
        if not self.results:
            messagebox.showinfo("提示", "请先执行检测")
            return
        lines = ["===== 环境检测报告 =====", ""]
        for result in self.results:
            self._report_one(lines, result)
            for child in result.get("children", []):
                self._report_one(lines, child, prefix="  ")
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))
        messagebox.showinfo("提示", "报告已复制到剪贴板")

    def _report_one(self, lines, result, prefix=""):
        mark = "[已安装]" if result.get("found") else "[未找到]"
        lines.append("%s%s %s  %s" % (prefix, mark, result["name"], result.get("version", "")))
        if result.get("path"):
            lines.append("%s  路径: %s" % (prefix, result["path"]))
        if result.get("installed_pkgs"):
            lines.append("%s  已安装包数: %d" % (prefix, len(result["installed_pkgs"])))
        if result.get("missing_pkgs"):
            lines.append("%s  建议安装: %s" % (prefix, ", ".join(result["missing_pkgs"][:10])))
        lines.append("")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    EnvCheckerApp().run()
