# -*- coding: utf-8 -*-
"""
GUI界面模块 - 基于tkinter的图形化操作界面
功能：路径显示与修改、关键词输入、开始检查、进度提示、结果展示
"""

import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
import threading
import queue

from config import (DOC_DIR, IMG_DIR,
                    DEFAULT_KEYWORDS, WEB_TARGET_URL,
                    WEB_MAX_WORKERS, WEB_CACHE_PATH,
                    LLM_ENABLED, OLLAMA_BASE_URL, OLLAMA_MODEL)
from llm_checker import check_ollama_connection, list_local_models
from checker_web import check_web
from checker_db import check_database, check_all_databases
from db_adapters import create_adapter
from llm_checker import check_database_with_llm
from checker_file import check_files, check_encrypted_files
from checker_image import check_images
from report import generate_report


# ========== 样式常量 ==========
BG_COLOR = "#2b2b2b"
FG_COLOR = "#d4d4d4"
ACCENT_COLOR = "#4FC3F7"
FRAME_BG = "#333333"
ENTRY_BG = "#3c3c3c"
BTN_START_COLOR = "#4CAF50"
BTN_STOP_COLOR = "#f44336"
BTN_REPORT_COLOR = "#2196F3"
BTN_CLEAR_COLOR = "#757575"
TITLE_BG = "#1a1a2e"


class App:
    """涉密信息综合检查系统主界面"""

    def __init__(self, root):
        self.root = root
        self.root.title("涉密信息综合检查系统")
        self.root.geometry("1600x1000")
        self.root.minsize(1400, 900)
        self.root.configure(bg=BG_COLOR)

        # 消息队列：用于子线程向主线程安全传递日志
        self.log_queue = queue.Queue()
        # 检查结果存储
        self.results = {}
        # 已完成的模块（支持断点续查）
        self._completed_modules = set()
        # 检查线程引用
        self.check_thread = None
        # 停止信号
        self._stop_event = threading.Event()
        # 加密文件密码请求队列（子线程→GUI线程）
        self._password_queue = queue.Queue()
        self._password_result = None

        self._setup_styles()
        self._build_ui()
        self._poll_log_queue()

    def _setup_styles(self):
        """配置 ttk 主题和自定义样式"""
        style = ttk.Style()
        available = style.theme_names()
        if "clam" in available:
            style.theme_use("clam")
        elif "vista" in available:
            style.theme_use("vista")

        style.configure(".", background=BG_COLOR, foreground=FG_COLOR)
        style.configure("TFrame", background=BG_COLOR)
        style.configure("TLabel", background=BG_COLOR, foreground=FG_COLOR)
        style.configure("TButton", padding=6)
        style.configure("TEntry", font=("Microsoft YaHei", 15),
                        fieldbackground="#ffffff", foreground="#1a1a1a")
        style.configure("TLabelframe", background=BG_COLOR, foreground=ACCENT_COLOR)
        style.configure("TLabelframe.Label", background=BG_COLOR,
                        foreground=ACCENT_COLOR, font=("Microsoft YaHei", 16, "bold"))
        style.configure("Header.TLabel", font=("Microsoft YaHei", 20, "bold"),
                        foreground=ACCENT_COLOR, background=BG_COLOR)
        style.configure("Status.TLabel", foreground=ACCENT_COLOR, font=("Consolas", 14))
        style.configure("Accent.TButton", font=("Microsoft YaHei", 16, "bold"))

        style.configure("green.Horizontal.TProgressbar",
                        troughcolor="#3c3c3c", background=BTN_START_COLOR)

    def _build_ui(self):
        """构建完整界面布局"""
        # ========== 主容器 ==========
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        main_frame.rowconfigure(2, weight=1)
        main_frame.columnconfigure(0, weight=1)

        # ========== 标题栏 ==========
        title_frame = tk.Frame(main_frame, bg=TITLE_BG, padx=15, pady=12)
        title_frame.grid(row=0, column=0, sticky=tk.EW, pady=(0, 8))
        tk.Label(title_frame, text="涉密信息综合检查系统",
                 font=("Microsoft YaHei", 24, "bold"),
                 fg=ACCENT_COLOR, bg=TITLE_BG).pack(side=tk.LEFT)
        tk.Label(title_frame, text="v2.0",
                 font=("Consolas", 14), fg="#888888",
                 bg=TITLE_BG).pack(side=tk.LEFT, padx=(14, 0), pady=(7, 0))

        # ========== 上半区：配置 + 按钮 + 进度条 ==========
        top_frame = ttk.Frame(main_frame)
        top_frame.grid(row=1, column=0, sticky=tk.EW)

        # ---------- 配置区域 ----------
        config_frame = ttk.LabelFrame(top_frame, text=" 检查配置 ",
                                      padding=(20, 16, 20, 16))
        config_frame.pack(fill=tk.X, padx=2, pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)

        row_pad = 12
        ctrl_pad = 12
        lbl_w = 18
        entry_font = ("Microsoft YaHei", 15)
        lbl_font = ("Microsoft YaHei", 14)

        # 文档目录
        ttk.Label(config_frame, text="文档目录:", width=lbl_w,
                  anchor=tk.E, font=lbl_font).grid(row=0, column=0, padx=(0, 8), pady=row_pad)
        self.doc_dir_var = tk.StringVar(value=DOC_DIR)
        doc_entry = ttk.Entry(config_frame, textvariable=self.doc_dir_var,
                              font=entry_font)
        doc_entry.grid(row=0, column=1, sticky=tk.EW, padx=(0, ctrl_pad))
        doc_btn_frame = ttk.Frame(config_frame)
        doc_btn_frame.grid(row=0, column=2, ipady=2)
        ttk.Button(doc_btn_frame, text="浏览", width=6,
                   command=lambda: self._browse_dir(self.doc_dir_var)
                   ).pack(side=tk.LEFT)
        ttk.Button(doc_btn_frame, text="+", width=3,
                   command=lambda: self._browse_dir_add(self.doc_dir_var)
                   ).pack(side=tk.LEFT, padx=(4, 0))

        # 图片目录
        ttk.Label(config_frame, text="图片目录:", width=lbl_w,
                  anchor=tk.E, font=lbl_font).grid(row=1, column=0, padx=(0, 8), pady=row_pad)
        self.img_dir_var = tk.StringVar(value=IMG_DIR)
        img_entry = ttk.Entry(config_frame, textvariable=self.img_dir_var,
                              font=entry_font)
        img_entry.grid(row=1, column=1, sticky=tk.EW, padx=(0, ctrl_pad))
        img_btn_frame = ttk.Frame(config_frame)
        img_btn_frame.grid(row=1, column=2, ipady=2)
        ttk.Button(img_btn_frame, text="浏览", width=6,
                   command=lambda: self._browse_dir(self.img_dir_var)
                   ).pack(side=tk.LEFT)
        ttk.Button(img_btn_frame, text="+", width=3,
                   command=lambda: self._browse_dir_add(self.img_dir_var)
                   ).pack(side=tk.LEFT, padx=(4, 0))

        # 数据库连接列表
        ttk.Label(config_frame, text="数据库检查:", width=lbl_w,
                  anchor=tk.E, font=lbl_font).grid(row=2, column=0, padx=(0, 8), pady=(row_pad, 0), sticky=tk.N)
        db_outer = ttk.Frame(config_frame)
        db_outer.grid(row=2, column=1, columnspan=2, sticky=tk.EW, padx=(0, ctrl_pad))

        # 统一网格容器（标题 + 所有连接行共享列宽）
        self.db_grid = ttk.Frame(db_outer)
        self.db_grid.pack(fill=tk.X)
        # 列: 0=类型 1=地址 2=用户名 3=密码 4=库名 5=删除按钮
        self.db_grid.columnconfigure(1, weight=1)  # 地址列自动扩展

        # 列标题（row=0）
        small_hint = ("Microsoft YaHei", 10)
        for col, text in enumerate(["类型", "地址/路径", "用户名", "密码", "库名(留空=全部)", ""]):
            ttk.Label(self.db_grid, text=text, font=small_hint,
                      foreground="#888888").grid(row=0, column=col, sticky=tk.W, padx=(0, 6))

        # 连接行从 row=1 开始
        self.db_conn_rows = []

        # 添加按钮
        add_btn_frame = ttk.Frame(db_outer)
        add_btn_frame.pack(fill=tk.X, pady=(6, 0))
        tk.Button(add_btn_frame, text="+ 添加连接", font=("Microsoft YaHei", 12),
                  bg="#3c3c3c", fg=ACCENT_COLOR, relief=tk.FLAT, padx=10, pady=4,
                  cursor="hand2", command=self._add_db_connection).pack(side=tk.LEFT)

        # 连接数据和UI行引用
        self.db_conn_rows = []    # [{"row": int, "widgets": [...], "type_var", ...}, ...]

        # 预置一条默认连接
        self._add_db_connection({"type": "MySQL", "host": "localhost",
                                 "user": "root", "password": "", "db_name": ""})

        # 关键词
        ttk.Label(config_frame, text="检查关键词:", width=lbl_w,
                  anchor=tk.E, font=lbl_font).grid(row=3, column=0, padx=(0, 8), pady=row_pad)
        self.keywords_var = tk.StringVar(value=",".join(DEFAULT_KEYWORDS))
        ttk.Entry(config_frame, textvariable=self.keywords_var,
                  font=entry_font).grid(row=3, column=1, sticky=tk.EW,
                                        padx=(0, ctrl_pad))
        ttk.Label(config_frame, text="(逗号分隔)", foreground="#888888",
                  font=("Microsoft YaHei", 13)).grid(row=3, column=2,
                                                     sticky=tk.W, padx=(4, 0))

        # 目标网址
        ttk.Label(config_frame, text="目标网址:", width=lbl_w,
                  anchor=tk.E, font=lbl_font).grid(row=4, column=0, padx=(0, 8), pady=row_pad)
        self.web_url_var = tk.StringVar(value=WEB_TARGET_URL)
        ttk.Entry(config_frame, textvariable=self.web_url_var,
                  font=entry_font).grid(row=4, column=1, sticky=tk.EW,
                                        padx=(0, ctrl_pad))
        web_btn_frame = ttk.Frame(config_frame)
        web_btn_frame.grid(row=4, column=2, ipady=2)
        ttk.Button(web_btn_frame, text="+", width=3,
                   command=lambda: self._browse_url_add()
                   ).pack(side=tk.LEFT)

        # 并行线程数
        ttk.Label(config_frame, text="并行线程数:", width=lbl_w,
                  anchor=tk.E, font=lbl_font).grid(row=5, column=0, padx=(0, 8), pady=row_pad)
        self.web_workers_var = tk.IntVar(value=WEB_MAX_WORKERS)
        workers_frame = ttk.Frame(config_frame)
        workers_frame.grid(row=5, column=1, sticky=tk.W, padx=(0, ctrl_pad))
        ttk.Scale(workers_frame, from_=1, to=16, variable=self.web_workers_var,
                  orient=tk.HORIZONTAL, length=350).pack(side=tk.LEFT)
        self.workers_label = ttk.Label(workers_frame, text=str(WEB_MAX_WORKERS),
                                       width=3, foreground=ACCENT_COLOR,
                                       font=("Consolas", 16, "bold"))
        self.workers_label.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Label(workers_frame, text="(1=单线程, 建议4~8)",
                  foreground="#888888",
                  font=("Microsoft YaHei", 13)).pack(side=tk.LEFT, padx=(10, 0))
        self.web_workers_var.trace_add("write", self._update_workers_label)

        # 增量检查开关
        self.web_incremental_var = tk.BooleanVar(value=True)
        incr_frame = ttk.Frame(config_frame)
        incr_frame.grid(row=6, column=0, columnspan=2, sticky=tk.W,
                        padx=(0, 8), pady=row_pad)
        ttk.Checkbutton(incr_frame, text="增量检查（检测页面更新）",
                        variable=self.web_incremental_var).pack(side=tk.LEFT)
        ttk.Label(incr_frame, text="  启用后仅检查更新的页面，跳过未变化的页面",
                  foreground="#888888",
                  font=("Microsoft YaHei", 13)).pack(side=tk.LEFT, padx=(8, 0))

        # 大模型配置
        ttk.Label(config_frame, text="大模型检查:", width=lbl_w,
                  anchor=tk.E, font=lbl_font).grid(row=7, column=0, padx=(0, 8), pady=row_pad)
        llm_frame = ttk.Frame(config_frame)
        llm_frame.grid(row=7, column=1, columnspan=2, sticky=tk.W, padx=(0, ctrl_pad))

        self.llm_enabled_var = tk.BooleanVar(value=LLM_ENABLED)
        ttk.Checkbutton(llm_frame, text="启用",
                        variable=self.llm_enabled_var,
                        command=self._toggle_llm).pack(side=tk.LEFT)

        self.llm_model_var = tk.StringVar(value=OLLAMA_MODEL)
        self.llm_model_combo = ttk.Combobox(llm_frame, textvariable=self.llm_model_var,
                                            width=18, font=("Microsoft YaHei", 12))
        self.llm_model_combo.pack(side=tk.LEFT, padx=(10, 0))

        # 刷新模型列表按钮
        tk.Button(llm_frame, text="刷新", font=("Microsoft YaHei", 11),
                  bg="#3c3c3c", fg=ACCENT_COLOR, relief=tk.FLAT, padx=8, pady=2,
                  cursor="hand2", command=self._refresh_llm_models).pack(side=tk.LEFT, padx=(6, 0))

        # 连接状态标签
        self.llm_status_var = tk.StringVar(value="未检测")
        self.llm_status_label = ttk.Label(llm_frame, textvariable=self.llm_status_var,
                                          font=("Microsoft YaHei", 11))
        self.llm_status_label.pack(side=tk.LEFT, padx=(10, 0))

        # 初始化时检测 Ollama
        self._refresh_llm_models()

        # ---------- 操作按钮 ----------
        btn_frame = ttk.Frame(top_frame)
        btn_frame.pack(fill=tk.X, padx=2, pady=(0, 4))

        self.start_btn = tk.Button(btn_frame, text="▶ 开始检查",
                                   command=self._start_check,
                                   bg=BTN_START_COLOR, fg="white",
                                   font=("Microsoft YaHei", 16, "bold"),
                                   relief=tk.FLAT, padx=28, pady=12,
                                   activebackground="#66BB6A", cursor="hand2")
        self.start_btn.pack(side=tk.LEFT, padx=(0, 14))

        self.stop_btn = tk.Button(btn_frame, text="■ 停止",
                                  command=self._stop_check,
                                  bg=BTN_STOP_COLOR, fg="white",
                                  font=("Microsoft YaHei", 15),
                                  relief=tk.FLAT, padx=28, pady=12,
                                  activebackground="#ef5350", cursor="hand2",
                                  state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 14))

        self.report_btn = tk.Button(btn_frame, text="生成报告",
                                    command=self._generate_report,
                                    bg=BTN_REPORT_COLOR, fg="white",
                                    font=("Microsoft YaHei", 15),
                                    relief=tk.FLAT, padx=28, pady=12,
                                    activebackground="#42A5F5", cursor="hand2",
                                    state=tk.DISABLED)
        self.report_btn.pack(side=tk.LEFT, padx=(0, 14))

        self.clear_btn = tk.Button(btn_frame, text="清空日志",
                                   command=self._clear_log,
                                   bg=BTN_CLEAR_COLOR, fg="white",
                                   font=("Microsoft YaHei", 15),
                                   relief=tk.FLAT, padx=28, pady=12,
                                   activebackground="#9e9e9e", cursor="hand2")
        self.clear_btn.pack(side=tk.RIGHT)

        # ---------- 进度条 + 状态 ----------
        progress_frame = ttk.Frame(top_frame)
        progress_frame.pack(fill=tk.X, padx=2, pady=(0, 2))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            progress_frame, variable=self.progress_var,
            maximum=100, mode="determinate",
            style="green.Horizontal.TProgressbar")
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(progress_frame, textvariable=self.status_var,
                  style="Status.TLabel", width=14,
                  anchor=tk.E).pack(side=tk.RIGHT)

        # ========== 下半区：日志/结果展示 ==========
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.grid(row=2, column=0, sticky=tk.NSEW, pady=(8, 0))

        result_frame = ttk.LabelFrame(bottom_frame, text=" 检查日志与结果 ",
                                      padding=6)
        result_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(
            result_frame, wrap=tk.WORD, font=("Consolas", 14),
            state=tk.DISABLED, bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="white", relief=tk.FLAT,
            borderwidth=0, padx=14, pady=12)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self.log_text.tag_configure("INFO", foreground="#4EC9B0")
        self.log_text.tag_configure("WARN", foreground="#DCDCAA")
        self.log_text.tag_configure("ERROR", foreground="#F44747")
        self.log_text.tag_configure("SUCCESS", foreground="#6A9955")
        self.log_text.tag_configure("MATCH", foreground="#FF6B6B",
                                    font=("Consolas", 13, "bold"))

    # ==================== 辅助方法 ====================

    def _add_db_connection(self, preset=None):
        """添加一条数据库连接配置行（直接在共享网格中添加控件）"""
        idx = len(self.db_conn_rows)
        row = idx + 1  # row=0 是列标题
        conn = preset or {"type": "MySQL", "host": "localhost", "user": "root",
                          "password": "", "db_name": ""}

        small_font = ("Microsoft YaHei", 12)
        g = self.db_grid

        # 类型下拉
        type_var = tk.StringVar(value=conn["type"])
        type_combo = ttk.Combobox(g, textvariable=type_var,
                                  values=["MySQL", "SQL Server", "PostgreSQL", "SQLite"],
                                  state="readonly", width=10, font=small_font)
        type_combo.grid(row=row, column=0, sticky=tk.W, padx=(0, 6), pady=2)

        # 地址
        host_var = tk.StringVar(value=conn["host"])
        host_entry = ttk.Entry(g, textvariable=host_var, font=small_font)
        host_entry.grid(row=row, column=1, sticky=tk.EW, padx=(0, 6), pady=2)

        # 用户名
        user_var = tk.StringVar(value=conn["user"])
        user_entry = ttk.Entry(g, textvariable=user_var, font=small_font, width=12)
        user_entry.grid(row=row, column=2, padx=(0, 6), pady=2)

        # 密码
        pwd_var = tk.StringVar(value=conn["password"])
        pwd_entry = ttk.Entry(g, textvariable=pwd_var, font=small_font,
                              width=12, show="*")
        pwd_entry.grid(row=row, column=3, padx=(0, 6), pady=2)

        # 库名
        dbname_var = tk.StringVar(value=conn["db_name"])
        dbname_entry = ttk.Entry(g, textvariable=dbname_var, font=small_font, width=14)
        dbname_entry.grid(row=row, column=4, padx=(0, 6), pady=2)

        # SQLite 切换时隐藏/显示用户名密码
        def on_type_change(*_):
            if type_var.get() == "SQLite":
                user_entry.grid_remove()
                pwd_entry.grid_remove()
                if host_var.get() == "localhost":
                    host_var.set("")
            else:
                user_entry.grid()
                pwd_entry.grid()
                if not host_var.get():
                    host_var.set("localhost")
        type_combo.bind("<<ComboboxSelected>>", on_type_change)
        on_type_change()  # 初始化

        # 先构建行数据，再创建删除按钮（按钮命令引用 conn_data）
        conn_data = {
            "row": row,  # 网格行号
            "widgets": [type_combo, host_entry, user_entry, pwd_entry, dbname_entry],
            "type_var": type_var, "host_var": host_var,
            "user_var": user_var, "pwd_var": pwd_var,
            "dbname_var": dbname_var
        }
        self.db_conn_rows.append(conn_data)

        # 删除按钮（按引用查找当前索引，不受行号重排影响）
        del_btn = tk.Button(g, text="×", font=("Microsoft YaHei", 12, "bold"),
                            fg="#ff5555", bg=BG_COLOR, relief=tk.FLAT, width=2,
                            cursor="hand2",
                            command=lambda ref=conn_data: self._remove_db_connection(ref))
        del_btn.grid(row=row, column=5, pady=2)
        conn_data["widgets"].append(del_btn)

    def _remove_db_connection(self, ref):
        """删除一条数据库连接（按引用查找）"""
        try:
            idx = self.db_conn_rows.index(ref)
        except ValueError:
            return
        row_data = self.db_conn_rows[idx]
        for w in row_data["widgets"]:
            w.destroy()
        self.db_conn_rows.pop(idx)
        # 重新布局：所有行上移
        for i, row_data in enumerate(self.db_conn_rows):
            new_row = i + 1  # row=0 是标题
            for w in row_data["widgets"]:
                w.grid(row=new_row)
            row_data["row"] = new_row

    def _update_workers_label(self, *_):
        """更新线程数标签显示"""
        self.workers_label.config(text=str(self.web_workers_var.get()))

    def _toggle_llm(self):
        """切换大模型启用状态"""
        if self.llm_enabled_var.get():
            self.llm_model_combo.config(state="readonly")
            self._refresh_llm_models()
        else:
            self.llm_model_combo.config(state="disabled")
            self.llm_status_var.set("已禁用（使用正则匹配）")

    def _refresh_llm_models(self):
        """刷新 Ollama 模型列表"""
        ok, models = check_ollama_connection(OLLAMA_BASE_URL)
        if ok:
            self.llm_model_combo["values"] = models
            if models and self.llm_model_var.get() not in models:
                self.llm_model_var.set(models[0])
            self.llm_status_var.set(f"✓ 已连接 ({len(models)}个模型)")
            self.llm_status_label.config(foreground="#6A9955")
            if not self.llm_enabled_var.get():
                self.llm_model_combo.config(state="disabled")
        else:
            self.llm_model_combo["values"] = []
            self.llm_status_var.set("✗ 未连接 (请启动Ollama)")
            self.llm_status_label.config(foreground="#F44747")

    def _browse_dir(self, var):
        """选择目录（替换）"""
        path = filedialog.askdirectory()
        if path:
            var.set(path)

    def _browse_dir_add(self, var):
        """追加目录（用分号分隔）"""
        path = filedialog.askdirectory()
        if path:
            current = var.get().strip()
            if current:
                var.set(current + ";" + path)
            else:
                var.set(path)

    def _browse_url_add(self):
        """追加网址（用分号分隔）"""
        url = simpledialog.askstring("添加网址", "输入新的目标网址:",
                                     parent=self.root)
        if url and url.strip():
            current = self.web_url_var.get().strip()
            if current:
                self.web_url_var.set(current + ";" + url.strip())
            else:
                self.web_url_var.set(url.strip())

    # ==================== 检查控制 ====================

    def _start_check(self):
        """启动检查（在子线程中执行）"""
        # ========== 输入校验 ==========
        errors = []

        # 关键词
        kw_text = self.keywords_var.get().strip()
        keywords = [kw.strip() for kw in kw_text.split(",") if kw.strip()]
        if not keywords:
            errors.append("检查关键词不能为空")

        # 网页地址（支持分号分隔多个）
        web_url = self.web_url_var.get().strip()
        if web_url:
            for u in web_url.split(";"):
                u = u.strip()
                if u and not u.startswith(("http://", "https://")):
                    errors.append(f"网址格式错误: {u}\n需以 http:// 或 https:// 开头")
                    break

        # 数据库连接校验（多连接模式）
        for conn in self.db_conn_rows:
            db_name = conn["dbname_var"].get().strip()
            if db_name and not re.match(r'^[a-zA-Z0-9_]+$', db_name):
                errors.append(f"数据库名格式错误: {db_name}\n只允许字母、数字和下划线")

        # 目录路径（支持分号分隔多目录）
        doc_dir = self.doc_dir_var.get().strip()
        if doc_dir:
            for d in doc_dir.split(";"):
                d = d.strip()
                if d and not os.path.isdir(d):
                    errors.append(f"文档目录不存在: {d}")
                    break

        img_dir = self.img_dir_var.get().strip()
        if img_dir:
            for d in img_dir.split(";"):
                d = d.strip()
                if d and not os.path.isdir(d):
                    errors.append(f"图片目录不存在: {d}")
                    break

        # 全部为空（数据库检查始终执行，只需其余三项有一项即可）
        if not any([web_url, doc_dir, img_dir]):
            errors.append("至少填写一项检查内容（网页/文档/图片）\n数据库检查会自动执行")

        if errors:
            messagebox.showwarning("输入校验", "\n\n".join(errors))
            return

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.report_btn.config(state=tk.DISABLED)
        self._stop_event.clear()

        # 判断是否续查
        if self._completed_modules:
            self._log("INFO", "=" * 60)
            self._log("INFO", f"  ▶ 续查模式 — 已完成: {', '.join(self._completed_modules)}")
            self._log("INFO", "  跳过已完成的模块，继续未完成的部分")
            self._log("INFO", "=" * 60)
        else:
            self.results = {}
            self._clear_log()
            self._log("INFO", "=" * 60)
            self._log("INFO", "  涉密信息综合检查系统 - 开始检查")
            self._log("INFO", f"  关键词: {', '.join(keywords)}")
            self._log("INFO", "=" * 60)

        self.check_thread = threading.Thread(
            target=self._run_check,
            args=(keywords,),
            daemon=True)
        self.check_thread.start()

    def _stop_check(self):
        """停止检查"""
        self._stop_event.set()
        self._log("WARN", "用户中止检查")
        self.stop_btn.config(state=tk.DISABLED)
        self.start_btn.config(state=tk.NORMAL)
        if self.results:
            self.report_btn.config(state=tk.NORMAL)

    def _run_check_one(self, name, func, step_info, progress_start, progress_end):
        """
        在守护线程中执行单个检查，支持立即停止。
        返回结果，被停止则返回 None。
        """
        result_box = {}

        def target():
            result_box["r"] = func()

        t = threading.Thread(target=target, daemon=True)
        t.start()

        # 轮询等待，每 0.2 秒检查一次停止信号
        while t.is_alive():
            if self._stop_event.is_set():
                self.log_queue.put(("WARN", f"  {step_info} 被中止"))
                return None
            t.join(timeout=0.2)

        return result_box.get("r")

    def _run_check(self, keywords):
        """子线程：执行全部检查任务，支持立即停止和断点续查"""
        try:
            web_url_input = self.web_url_var.get().strip()
            doc_dir_input = self.doc_dir_var.get().strip()
            img_dir_input = self.img_dir_var.get().strip()
            web_workers = self.web_workers_var.get()
            web_incremental = self.web_incremental_var.get()

            # 大模型配置
            use_llm = self.llm_enabled_var.get()
            llm_model = self.llm_model_var.get().strip() or None
            llm_base_url = OLLAMA_BASE_URL

            # 从UI收集所有数据库连接配置
            db_conns = []
            for row in self.db_conn_rows:
                db_conns.append({
                    "type": row["type_var"].get(),
                    "host": row["host_var"].get().strip() or "localhost",
                    "user": row["user_var"].get().strip() or "root",
                    "password": row["pwd_var"].get(),
                    "db_name": row["dbname_var"].get().strip()
                })

            total_steps = 4
            current_step = 0
            stopped = False

            def log_cb(msg):
                self.log_queue.put(("INFO", msg))

            # ---------- 1. 网页检查 ----------
            current_step += 1
            if "web" in self._completed_modules:
                pass
            elif self._stop_event.is_set():
                stopped = True
            elif web_url_input:
                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "━" * 50))
                mode_str = "增量" if web_incremental else "全量"
                url_count = len([u for u in web_url_input.split(";") if u.strip()])
                url_display = web_url_input if url_count == 1 else f"{url_count}个网址"
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 网页检查({mode_str}) - {url_display} "
                                    f"(全站遍历, 线程{web_workers})"))
                self.log_queue.put(("INFO", "━" * 50))
                self._update_progress(5)

                result = self._run_check_one(
                    "web",
                    lambda: check_web(web_url_input, keywords,
                                      log_callback=log_cb,
                                      max_workers=web_workers,
                                      incremental=web_incremental,
                                      cache_path=WEB_CACHE_PATH,
                                      use_llm=use_llm,
                                      llm_model=llm_model,
                                      llm_base_url=llm_base_url),
                    "网页检查", 5, 25)
                if result is None:
                    stopped = True
                else:
                    self.results["web"] = result
                    self._completed_modules.add("web")
                    self._update_progress(25)
                    skip_info = ""
                    if web_incremental:
                        cached_count = len(result.get("cached_matched_urls", []))
                        skip_info = (f", 跳过{result.get('skipped_pages', 0)}个未变化, "
                                     f"新增/更新{result.get('new_pages', 0)}个")
                        if cached_count:
                            skip_info += f", 缓存已有{cached_count}个涉密页"
                    self.log_queue.put(("SUCCESS",
                                        f"  网页检查完成: {result['total']} 个页面, "
                                        f"{result['matched_pages']} 个涉密{skip_info}"))

            # ---------- 2. 数据库检查（支持多连接） ----------
            current_step += 1
            if "db" in self._completed_modules:
                pass
            elif self._stop_event.is_set():
                stopped = True
            elif db_conns:
                type_map = {"MySQL": "mysql", "SQL Server": "sqlserver",
                            "PostgreSQL": "postgresql", "SQLite": "sqlite"}

                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "━" * 50))
                conn_descs = [f"{c['type']}" for c in db_conns]
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 数据库检查 - "
                                    f"{len(db_conns)}个连接({', '.join(conn_descs)})"))
                self.log_queue.put(("INFO", "━" * 50))
                self._update_progress(30)

                # 合并结果容器
                merged = {"total_databases": 0, "total_tables": 0, "total_records": 0,
                          "candidate_records": 0, "matched_tables": 0,
                          "table_stats": {}, "details": []}
                db_progress_step = 20 / max(len(db_conns), 1)
                db_progress = 30

                for conn_idx, conn in enumerate(db_conns):
                    if self._stop_event.is_set():
                        stopped = True
                        break

                    db_display = conn["db_name"] if conn["db_name"] else "全部数据库"
                    adapter_key = type_map.get(conn["type"], "mysql")
                    self.log_queue.put(("INFO",
                                        f"  [{conn_idx+1}/{len(db_conns)}] "
                                        f"{conn['type']}@{conn['host']} - {db_display}"))

                    try:
                        db_adapter = create_adapter(adapter_key)
                        db_adapter.connect(conn["host"], conn["user"],
                                           conn["password"], conn["db_name"] or None)
                    except Exception as e:
                        self.log_queue.put(("ERROR", f"  连接失败: {e}"))
                        continue

                    try:
                        if use_llm and llm_model:
                            # 大模型模式：用 LLM 替代正则精匹配
                            if conn["db_name"]:
                                result = check_database_with_llm(
                                    db_adapter, conn["db_name"], keywords,
                                    model=llm_model, base_url=llm_base_url,
                                    log_callback=log_cb)
                            else:
                                # 多库顺序检查（LLM模式）
                                user_dbs = db_adapter.list_databases()
                                result = {"total_databases": len(user_dbs),
                                          "total_tables": 0, "total_records": 0,
                                          "candidate_records": 0, "matched_tables": 0,
                                          "table_stats": {}, "details": []}
                                for db_idx, db_name in enumerate(user_dbs):
                                    log_cb(f"  [数据库] 检查 {db_name} "
                                           f"({db_idx+1}/{len(user_dbs)}) [LLM]...")
                                    sub = check_database_with_llm(
                                        db_adapter, db_name, keywords,
                                        model=llm_model, base_url=llm_base_url,
                                        log_callback=log_cb)
                                    result["total_tables"] += sub["total_tables"]
                                    result["total_records"] += sub["total_records"]
                                    result["candidate_records"] += sub["candidate_records"]
                                    result["matched_tables"] += sub["matched_tables"]
                                    for tname, tstats in sub["table_stats"].items():
                                        result["table_stats"][f"{db_name}.{tname}"] = tstats
                                    for d in sub["details"]:
                                        d["table"] = f"{db_name}.{d['table']}"
                                        result["details"].append(d)
                        else:
                            # 正则模式
                            if conn["db_name"]:
                                result = check_database(db_adapter, conn["db_name"],
                                                        keywords, log_callback=log_cb)
                            else:
                                result = check_all_databases(db_adapter, keywords,
                                                             log_callback=log_cb)
                    except Exception as e:
                        self.log_queue.put(("ERROR", f"  检查异常: {e}"))
                        result = None
                    finally:
                        try:
                            db_adapter.close()
                        except Exception:
                            pass

                    if result:
                        merged["total_databases"] += result.get("total_databases", 0)
                        merged["total_tables"] += result["total_tables"]
                        merged["total_records"] += result["total_records"]
                        merged["candidate_records"] += result["candidate_records"]
                        merged["matched_tables"] += result["matched_tables"]
                        merged["table_stats"].update(result["table_stats"])
                        merged["details"].extend(result["details"])

                        candidate = result.get('candidate_records', 0)
                        opt_info = f", 粗筛{candidate}条" if candidate else ""
                        self.log_queue.put(("SUCCESS",
                                            f"  完成: {result['total_records']}条记录{opt_info}, "
                                            f"{result['matched_tables']}个涉密表"))

                    db_progress += db_progress_step
                    self._update_progress(db_progress)

                if not stopped:
                    self.results["db"] = merged
                    self._completed_modules.add("db")
                    self._update_progress(50)
                    total_cand = merged['candidate_records']
                    opt_info = f", 粗筛{total_cand}条候选" if total_cand else ""
                    self.log_queue.put(("SUCCESS",
                                        f"  数据库检查全部完成: "
                                        f"{merged['total_records']} 条记录{opt_info}, "
                                        f"{merged['matched_tables']} 个涉密表"))

            # ---------- 3. 文件检查 ----------
            current_step += 1
            if "file" in self._completed_modules:
                pass
            elif self._stop_event.is_set():
                stopped = True
            elif doc_dir_input:
                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "━" * 50))
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 文件检查 - {doc_dir_input}"))
                self.log_queue.put(("INFO", "━" * 50))
                self._update_progress(55)

                result = self._run_check_one(
                    "file",
                    lambda: check_files(doc_dir_input, keywords,
                                        log_callback=log_cb,
                                        max_workers=web_workers,
                                        use_llm=use_llm,
                                        llm_model=llm_model,
                                        llm_base_url=llm_base_url),
                    "文件检查", 55, 80)
                if result is None:
                    stopped = True
                else:
                    self.results["file"] = result
                    self._completed_modules.add("file")
                    self._update_progress(80)
                    extra_info = []
                    arch_count = result.get('archives_scanned', 0)
                    if arch_count:
                        extra_info.append(f"压缩包{arch_count}个")
                    enc_count = len(result.get('encrypted_files', []))
                    if enc_count:
                        extra_info.append(f"加密{enc_count}个")
                    dmg_count = len(result.get('damaged_files', []))
                    if dmg_count:
                        extra_info.append(f"损坏{dmg_count}个")
                    extra_str = f", {', '.join(extra_info)}" if extra_info else ""
                    self.log_queue.put(("SUCCESS",
                                        f"  文件检查完成: {result['supported_files']} 个文件, "
                                        f"{result['matched_files']} 个涉密{extra_str}"))

            # ---------- 4. 图片检查 ----------
            current_step += 1
            if "image" in self._completed_modules:
                pass
            elif self._stop_event.is_set():
                stopped = True
            elif img_dir_input:
                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "━" * 50))
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 图片检查 - {img_dir_input}"))
                self.log_queue.put(("INFO", "━" * 50))
                self._update_progress(85)

                result = self._run_check_one(
                    "image",
                    lambda: check_images(img_dir_input, keywords,
                                         log_callback=log_cb,
                                         max_workers=web_workers),
                    "图片检查", 85, 100)
                if result is None:
                    stopped = True
                else:
                    self.results["image"] = result
                    self._completed_modules.add("image")
                    self._update_progress(100)
                    self.log_queue.put(("SUCCESS",
                                        f"  图片检查完成: {result['total_images']} 张图片, "
                                        f"{result['matched_images']} 张涉密"))

            # ---------- 5. 加密文件解密检查 ----------
            if not stopped and "file" in self._completed_modules:
                file_result = self.results.get("file", {})
                enc_files = list(file_result.get("encrypted_files", []))
                enc_archives = list(file_result.get("encrypted_archives", []))
                total_enc = len(enc_files) + len(enc_archives)

                while total_enc > 0 and not self._stop_event.is_set():
                    # 构造提示信息
                    failed_names = [os.path.basename(e["file"]) for e in enc_files] + \
                                   [os.path.basename(e["file"]) for e in enc_archives]
                    name_list = "\n".join(f"  {i+1}. {n}" for i, n in enumerate(failed_names[:10]))
                    if len(failed_names) > 10:
                        name_list += f"\n  ...共{len(failed_names)}个"
                    msg = (f"发现 {total_enc} 个加密文件/压缩包：\n\n"
                           f"{name_list}\n\n"
                           f"请输入密码解密（留空跳过）：")

                    # 请求密码（跨线程）
                    event = threading.Event()
                    self._password_result = None
                    self._password_queue.put({"msg": msg, "event": event})
                    event.wait()  # 等待 GUI 线程弹窗完成

                    password = self._password_result
                    if password is None or password == "":
                        # 用户跳过
                        for e in enc_files:
                            e["status"] = "skipped"
                        for e in enc_archives:
                            e["status"] = "skipped"
                        self.log_queue.put(("INFO", "  用户跳过加密文件解密"))
                        break

                    # 解密检查
                    self.log_queue.put(("INFO", f"  正在解密 {total_enc} 个加密文件..."))
                    decrypt_details, decrypt_ok, decrypt_fail = check_encrypted_files(
                        enc_files, enc_archives, password, keywords,
                        log_callback=log_cb, max_workers=web_workers,
                        use_llm=use_llm, llm_model=llm_model,
                        llm_base_url=llm_base_url)

                    # 更新状态
                    for e in enc_files:
                        if e["file"] in decrypt_ok:
                            e["status"] = "decrypted"
                            e["matched"] = sum(1 for d in decrypt_details
                                               if d["file"] == e["file"])
                        elif e["file"] in decrypt_fail:
                            e["status"] = "failed"
                    for e in enc_archives:
                        if e["file"] in decrypt_ok:
                            e["status"] = "decrypted"
                            e["matched"] = sum(1 for d in decrypt_details
                                               if d["file"] == e["file"])
                        elif e["file"] in decrypt_fail:
                            e["status"] = "failed"

                    # 合并涉密匹配到文件结果
                    if decrypt_details:
                        file_result["details"].extend(decrypt_details)
                        file_result["matched_files"] += len(set(
                            d["file"] for d in decrypt_details))

                    ok_count = len(decrypt_ok)
                    fail_count = len(decrypt_fail)
                    self.log_queue.put(("SUCCESS",
                                        f"  解密完成: 成功{ok_count}个, 失败{fail_count}个"))

                    # 准备下一轮（只重试失败的）
                    enc_files = [e for e in enc_files if e["status"] == "failed"]
                    enc_archives = [e for e in enc_archives if e["status"] == "failed"]
                    total_enc = len(enc_files) + len(enc_archives)

            # ---------- 完成汇总 ----------
            self.log_queue.put(("INFO", ""))
            self.log_queue.put(("INFO", "=" * 60))
            if stopped:
                done = sorted(self._completed_modules) if self._completed_modules else []
                all_modules = {"web", "db", "file", "image"}
                pending = sorted(all_modules - self._completed_modules)
                self.log_queue.put(("WARN", "  ■ 检查已中止"))
                if done:
                    self.log_queue.put(("INFO", f"  已完成: {', '.join(done)}"))
                if pending:
                    self.log_queue.put(("INFO", f"  待检查: {', '.join(pending)}"))
                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "  → 点击「生成报告」查看已完成部分的结果"))
                self.log_queue.put(("INFO", "  → 点击「开始检查」继续未完成的部分"))
            else:
                self.log_queue.put(("SUCCESS", "  全部检查完成!"))
                self._completed_modules.clear()

                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "正在自动生成检查报告..."))
                try:
                    report_path = generate_report(self.results, keywords,
                                                  use_llm=use_llm,
                                                  llm_model=llm_model)
                    self.log_queue.put(("SUCCESS",
                                        f"  报告已生成: {report_path}"))
                except Exception as e:
                    self.log_queue.put(("ERROR",
                                        f"  报告生成失败: {e}"))

            self.log_queue.put(("INFO", "=" * 60))

            self.root.after(0, lambda: self.report_btn.config(state=tk.NORMAL))

        except Exception as e:
            self.log_queue.put(("ERROR", f"检查过程发生异常: {e}"))
        finally:
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))
            self.root.after(0, lambda: self.status_var.set("检查完成"))

    # ==================== 报告生成 ====================

    def _generate_report(self):
        """手动触发报告生成"""
        if not self.results:
            messagebox.showinfo("提示", "请先执行检查")
            return

        kw_text = self.keywords_var.get().strip()
        keywords = [kw.strip() for kw in kw_text.split(",") if kw.strip()]

        use_llm = self.llm_enabled_var.get()
        llm_model = self.llm_model_var.get().strip() or None

        try:
            report_path = generate_report(self.results, keywords,
                                          use_llm=use_llm, llm_model=llm_model)
            self._log("SUCCESS", f"报告已生成: {report_path}")
            messagebox.showinfo("成功", f"报告已生成:\n{report_path}")
        except Exception as e:
            self._log("ERROR", f"报告生成失败: {e}")
            messagebox.showerror("错误", f"报告生成失败: {e}")

    # ==================== 日志与进度 ====================

    def _log(self, level, msg):
        """向日志区域追加一行（线程安全）"""
        self.log_queue.put((level, msg))

    def _ask_password_dialog(self, msg):
        """弹出较大的密码输入对话框（使用 ttk 控件，兼容深色主题）"""
        dlg = tk.Toplevel(self.root)
        dlg.title("加密文件解密")
        dlg.resizable(False, False)
        dlg.configure(bg=BG_COLOR)
        dlg.transient(self.root)
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)  # 禁止点X关闭

        result = {"value": None}

        # 提示文字
        tk.Label(dlg, text=msg, font=("Microsoft YaHei", 14),
                 bg=BG_COLOR, fg=FG_COLOR, wraplength=460,
                 justify=tk.LEFT).pack(padx=30, pady=(25, 15), anchor=tk.W)

        # 密码输入框（用 ttk.Entry，颜色由 style 控制）
        pwd_frame = ttk.Frame(dlg)
        pwd_frame.pack(fill=tk.X, padx=30, pady=(0, 20))
        ttk.Label(pwd_frame, text="密码:",
                  font=("Microsoft YaHei", 14)).pack(side=tk.LEFT)
        pwd_var = tk.StringVar()
        pwd_entry = ttk.Entry(pwd_frame, textvariable=pwd_var, show="*",
                              font=("Microsoft YaHei", 15), width=35)
        pwd_entry.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)

        # 按钮
        btn_frame = tk.Frame(dlg, bg=BG_COLOR)
        btn_frame.pack(fill=tk.X, padx=30, pady=(0, 20))

        def on_ok(event=None):
            result["value"] = pwd_var.get()
            dlg.destroy()

        def on_cancel():
            result["value"] = None
            dlg.destroy()

        pwd_entry.bind("<Return>", on_ok)

        ok_btn = tk.Button(btn_frame, text="确  认", font=("Microsoft YaHei", 14, "bold"),
                           bg=BTN_START_COLOR, fg="white", relief=tk.FLAT,
                           padx=20, pady=6, cursor="hand2", command=on_ok)
        ok_btn.pack(side=tk.RIGHT, padx=(10, 0))

        cancel_btn = tk.Button(btn_frame, text="跳  过", font=("Microsoft YaHei", 14),
                               bg=BTN_CLEAR_COLOR, fg="white", relief=tk.FLAT,
                               padx=20, pady=6, cursor="hand2", command=on_cancel)
        cancel_btn.pack(side=tk.RIGHT)

        # 先显示窗口，再设置大小和焦点
        dlg.update_idletasks()
        w, h = dlg.winfo_reqwidth() + 20, dlg.winfo_reqheight() + 10
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        dlg.geometry(f"{w}x{h}+{x}+{y}")

        # 延迟 grab，等窗口完全就绪
        def _do_grab():
            try:
                dlg.grab_set()
                pwd_entry.focus_force()
                pwd_entry.icursor(tk.END)
            except tk.TclError:
                pass
        dlg.after(150, _do_grab)

        self.root.wait_window(dlg)
        return result["value"]

    def _poll_log_queue(self):
        """轮询日志队列，将消息写入UI；处理加密文件密码请求"""
        while not self.log_queue.empty():
            try:
                level, msg = self.log_queue.get_nowait()
                self.log_text.config(state=tk.NORMAL)
                self.log_text.insert(tk.END, msg + "\n", level)
                self.log_text.see(tk.END)
                self.log_text.config(state=tk.DISABLED)
            except queue.Empty:
                break

        # 处理加密文件密码请求（子线程通过 _password_queue 请求）
        try:
            req = self._password_queue.get_nowait()
            msg = req.get("msg", "请输入密码：")
            pwd = self._ask_password_dialog(msg)
            self._password_result = pwd  # None 表示用户取消
            req["event"].set()  # 通知子线程
        except queue.Empty:
            pass

        self.root.after(100, self._poll_log_queue)

    def _update_progress(self, value):
        """更新进度条（线程安全）"""
        self.root.after(0, lambda: self.progress_var.set(value))
        self.root.after(0, lambda: self.status_var.set(
            f"检查进行中... {int(value)}%"))

    def _clear_log(self):
        """清空日志区域"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)
