# -*- coding: utf-8 -*-
"""
GUI界面模块 - 基于tkinter的图形化操作界面
功能：路径显示与修改、关键词输入、开始检查、进度提示、结果展示
"""

import os
import re
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import queue

from config import (DOC_DIR, IMG_DIR,
                    DB_HOST, DB_USER, DB_PASSWORD, DB_NAME,
                    DEFAULT_KEYWORDS, WEB_TARGET_URL, WEB_MAX_DEPTH)
from checker_web import check_web
from checker_db import check_database
from checker_file import check_files
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
        self.root.geometry("1550x1200")
        self.root.minsize(1200, 900)
        self.root.configure(bg=BG_COLOR)

        # 消息队列：用于子线程向主线程安全传递日志
        self.log_queue = queue.Queue()
        # 检查结果存储
        self.results = {}
        # 检查线程引用
        self.check_thread = None

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
        style.configure("TEntry", font=("Microsoft YaHei", 14),
                        fieldbackground="#ffffff", foreground="#1a1a1a")
        style.configure("TLabelframe", background=BG_COLOR, foreground=ACCENT_COLOR)
        style.configure("TLabelframe.Label", background=BG_COLOR,
                        foreground=ACCENT_COLOR, font=("Microsoft YaHei", 15, "bold"))
        style.configure("Header.TLabel", font=("Microsoft YaHei", 20, "bold"),
                        foreground=ACCENT_COLOR, background=BG_COLOR)
        style.configure("Status.TLabel", foreground=ACCENT_COLOR, font=("Consolas", 13))
        style.configure("Accent.TButton", font=("Microsoft YaHei", 15, "bold"))

        style.configure("green.Horizontal.TProgressbar",
                        troughcolor="#3c3c3c", background=BTN_START_COLOR)

    def _build_ui(self):
        """构建完整界面布局"""
        # ========== 主容器 ==========
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        main_frame.rowconfigure(1, weight=1)
        main_frame.columnconfigure(0, weight=1)

        # ========== 标题栏 ==========
        title_frame = tk.Frame(main_frame, bg=TITLE_BG, padx=15, pady=12)
        title_frame.grid(row=0, column=0, sticky=tk.EW, pady=(0, 8))
        tk.Label(title_frame, text="涉密信息综合检查系统",
                 font=("Microsoft YaHei", 22, "bold"),
                 fg=ACCENT_COLOR, bg=TITLE_BG).pack(side=tk.LEFT)
        tk.Label(title_frame, text="v2.0",
                 font=("Consolas", 14), fg="#888888",
                 bg=TITLE_BG).pack(side=tk.LEFT, padx=(14, 0), pady=(7, 0))

        # ========== 上半区：配置 + 按钮 + 进度条 ==========
        top_frame = ttk.Frame(main_frame)
        top_frame.grid(row=1, column=0, sticky=tk.EW)
        top_frame.grid_propagate(False)
        top_frame.configure(height=620)

        # ---------- 配置区域 ----------
        config_frame = ttk.LabelFrame(top_frame, text=" 检查配置 ",
                                      padding=(20, 16, 20, 16))
        config_frame.pack(fill=tk.X, padx=2, pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)

        row_pad = 12
        ctrl_pad = 12
        lbl_w = 18
        entry_font = ("Microsoft YaHei", 14)
        lbl_font = ("Microsoft YaHei", 13)

        # 文档目录
        ttk.Label(config_frame, text="文档目录:", width=lbl_w,
                  anchor=tk.E, font=lbl_font).grid(row=0, column=0, padx=(0, 8), pady=row_pad)
        self.doc_dir_var = tk.StringVar(value=DOC_DIR)
        doc_entry = ttk.Entry(config_frame, textvariable=self.doc_dir_var,
                              font=entry_font)
        doc_entry.grid(row=0, column=1, sticky=tk.EW, padx=(0, ctrl_pad))
        ttk.Button(config_frame, text="浏览", width=8,
                   command=lambda: self._browse_dir(self.doc_dir_var)
                   ).grid(row=0, column=2, ipady=2)

        # 图片目录
        ttk.Label(config_frame, text="图片目录:", width=lbl_w,
                  anchor=tk.E, font=lbl_font).grid(row=1, column=0, padx=(0, 8), pady=row_pad)
        self.img_dir_var = tk.StringVar(value=IMG_DIR)
        img_entry = ttk.Entry(config_frame, textvariable=self.img_dir_var,
                              font=entry_font)
        img_entry.grid(row=1, column=1, sticky=tk.EW, padx=(0, ctrl_pad))
        ttk.Button(config_frame, text="浏览", width=8,
                   command=lambda: self._browse_dir(self.img_dir_var)
                   ).grid(row=1, column=2, ipady=2)

        # 数据库名
        ttk.Label(config_frame, text="数据库名:", width=lbl_w,
                  anchor=tk.E, font=lbl_font).grid(row=2, column=0, padx=(0, 8), pady=row_pad)
        self.db_name_var = tk.StringVar(value=DB_NAME)
        ttk.Entry(config_frame, textvariable=self.db_name_var,
                  font=entry_font).grid(row=2, column=1, sticky=tk.EW,
                                        padx=(0, ctrl_pad))

        # 关键词
        ttk.Label(config_frame, text="检查关键词:", width=lbl_w,
                  anchor=tk.E, font=lbl_font).grid(row=3, column=0, padx=(0, 8), pady=row_pad)
        self.keywords_var = tk.StringVar(value=",".join(DEFAULT_KEYWORDS))
        ttk.Entry(config_frame, textvariable=self.keywords_var,
                  font=entry_font).grid(row=3, column=1, sticky=tk.EW,
                                        padx=(0, ctrl_pad))
        ttk.Label(config_frame, text="(逗号分隔)", foreground="#888888",
                  font=("Microsoft YaHei", 12)).grid(row=3, column=2,
                                                     sticky=tk.W, padx=(4, 0))

        # 目标网址
        ttk.Label(config_frame, text="目标网址:", width=lbl_w,
                  anchor=tk.E, font=lbl_font).grid(row=4, column=0, padx=(0, 8), pady=row_pad)
        self.web_url_var = tk.StringVar(value=WEB_TARGET_URL)
        ttk.Entry(config_frame, textvariable=self.web_url_var,
                  font=entry_font).grid(row=4, column=1, sticky=tk.EW,
                                        padx=(0, ctrl_pad))

        # 爬取深度
        ttk.Label(config_frame, text="爬取深度:", width=lbl_w,
                  anchor=tk.E, font=lbl_font).grid(row=5, column=0, padx=(0, 8), pady=row_pad)
        self.web_depth_var = tk.IntVar(value=WEB_MAX_DEPTH)
        depth_frame = ttk.Frame(config_frame)
        depth_frame.grid(row=5, column=1, sticky=tk.W, padx=(0, ctrl_pad))
        ttk.Scale(depth_frame, from_=0, to=10, variable=self.web_depth_var,
                  orient=tk.HORIZONTAL, length=350).pack(side=tk.LEFT)
        self.depth_label = ttk.Label(depth_frame, text=str(WEB_MAX_DEPTH),
                                     width=3, foreground=ACCENT_COLOR,
                                     font=("Consolas", 15, "bold"))
        self.depth_label.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Label(depth_frame, text="(0=仅首页, 越大爬越深)",
                  foreground="#888888",
                  font=("Microsoft YaHei", 12)).pack(side=tk.LEFT, padx=(10, 0))
        self.web_depth_var.trace_add("write", self._update_depth_label)

        # ---------- 操作按钮 ----------
        btn_frame = ttk.Frame(top_frame)
        btn_frame.pack(fill=tk.X, padx=2, pady=(0, 4))

        self.start_btn = tk.Button(btn_frame, text="▶ 开始检查",
                                   command=self._start_check,
                                   bg=BTN_START_COLOR, fg="white",
                                   font=("Microsoft YaHei", 15, "bold"),
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
            result_frame, wrap=tk.WORD, font=("Consolas", 13),
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

    def _update_depth_label(self, *_):
        """更新深度标签显示"""
        self.depth_label.config(text=str(self.web_depth_var.get()))

    def _browse_dir(self, var):
        """选择目录"""
        path = filedialog.askdirectory()
        if path:
            var.set(path)

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

        # 网页地址
        web_url = self.web_url_var.get().strip()
        if web_url and not web_url.startswith(("http://", "https://")):
            errors.append(f"网址格式错误: {web_url}\n需以 http:// 或 https:// 开头")

        # 数据库名
        db_name = self.db_name_var.get().strip()
        if db_name:
            if not re.match(r'^[a-zA-Z0-9_]+$', db_name):
                errors.append(f"数据库名格式错误: {db_name}\n只允许字母、数字和下划线")

        # 目录路径
        doc_dir = self.doc_dir_var.get().strip()
        if doc_dir and not os.path.isdir(doc_dir):
            errors.append(f"文档目录不存在: {doc_dir}")

        img_dir = self.img_dir_var.get().strip()
        if img_dir and not os.path.isdir(img_dir):
            errors.append(f"图片目录不存在: {img_dir}")

        # 爬取深度
        depth = self.web_depth_var.get()
        if depth < 0 or depth > 10:
            errors.append("爬取深度需在 0~10 之间")

        # 全部为空
        if not any([web_url, db_name, doc_dir, img_dir]):
            errors.append("至少填写一项检查内容")

        if errors:
            messagebox.showwarning("输入校验", "\n\n".join(errors))
            return

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.report_btn.config(state=tk.DISABLED)
        self.progress_var.set(0)
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
        self._log("WARN", "用户中止检查")
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

    def _run_check(self, keywords):
        """子线程：执行全部检查任务"""
        try:
            web_url_input = self.web_url_var.get().strip()
            db_name_input = self.db_name_var.get().strip()
            doc_dir_input = self.doc_dir_var.get().strip()
            img_dir_input = self.img_dir_var.get().strip()
            web_depth = self.web_depth_var.get()

            total_steps = 4
            current_step = 0

            def log_cb(msg):
                self.log_queue.put(("INFO", msg))

            # ---------- 1. 网页检查 ----------
            current_step += 1
            self.log_queue.put(("INFO", ""))
            self.log_queue.put(("INFO", "━" * 50))
            if web_url_input:
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 网页检查 - {web_url_input} (深度{web_depth})"))
                self.log_queue.put(("INFO", "━" * 50))
                self._update_progress(5)

                web_result = check_web(
                    web_url_input, keywords, log_callback=log_cb,
                    max_depth=web_depth)
                self.results["web"] = web_result
                self._update_progress(25)
                self.log_queue.put(("SUCCESS",
                                    f"  网页检查完成: {web_result['total']} 个页面, "
                                    f"{web_result['matched_pages']} 个涉密"))
            else:
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 网页检查 - 已跳过（未填写网址）"))
                self.log_queue.put(("INFO", "━" * 50))
                web_result = {"total": 0, "matched_pages": 0, "details": []}
                self.results["web"] = web_result

            # ---------- 2. 数据库检查 ----------
            current_step += 1
            self.log_queue.put(("INFO", ""))
            self.log_queue.put(("INFO", "━" * 50))
            if db_name_input:
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 数据库检查 - {db_name_input}"))
                self.log_queue.put(("INFO", "━" * 50))
                self._update_progress(30)

                db_result = check_database(
                    db_name_input, keywords, log_callback=log_cb,
                    host=DB_HOST, user=DB_USER, password=DB_PASSWORD)
                self.results["db"] = db_result
                self._update_progress(50)
                self.log_queue.put(("SUCCESS",
                                    f"  数据库检查完成: {db_result['total_records']} 条记录, "
                                    f"{db_result['matched_tables']} 个涉密表"))
            else:
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 数据库检查 - 已跳过（未填写数据库名）"))
                self.log_queue.put(("INFO", "━" * 50))
                db_result = {"total_tables": 0, "total_records": 0,
                             "matched_tables": 0, "details": []}
                self.results["db"] = db_result

            # ---------- 3. 文件检查 ----------
            current_step += 1
            self.log_queue.put(("INFO", ""))
            self.log_queue.put(("INFO", "━" * 50))
            if doc_dir_input:
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 文件检查 - {doc_dir_input}"))
                self.log_queue.put(("INFO", "━" * 50))
                self._update_progress(55)

                file_result = check_files(
                    doc_dir_input, keywords, log_callback=log_cb)
                self.results["file"] = file_result
                self._update_progress(80)
                self.log_queue.put(("SUCCESS",
                                    f"  文件检查完成: {file_result['supported_files']} 个文件, "
                                    f"{file_result['matched_files']} 个涉密"))
            else:
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 文件检查 - 已跳过（未填写文档目录）"))
                self.log_queue.put(("INFO", "━" * 50))
                file_result = {"total_files": 0, "supported_files": 0,
                               "matched_files": 0, "type_counts": {},
                               "encrypted_files": [], "hidden_files": [],
                               "details": []}
                self.results["file"] = file_result

            # ---------- 4. 图片检查 ----------
            current_step += 1
            self.log_queue.put(("INFO", ""))
            self.log_queue.put(("INFO", "━" * 50))
            if img_dir_input:
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 图片检查 - {img_dir_input}"))
                self.log_queue.put(("INFO", "━" * 50))
                self._update_progress(85)

                image_result = check_images(
                    img_dir_input, keywords, log_callback=log_cb)
                self.results["image"] = image_result
                self._update_progress(100)
                self.log_queue.put(("SUCCESS",
                                    f"  图片检查完成: {image_result['total_images']} 张图片, "
                                    f"{image_result['matched_images']} 张涉密"))
            else:
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 图片检查 - 已跳过（未填写图片目录）"))
                self.log_queue.put(("INFO", "━" * 50))
                image_result = {"total_images": 0, "matched_images": 0,
                                "ocr_engine": "N/A", "type_counts": {},
                                "details": []}
                self.results["image"] = image_result

            # ---------- 完成汇总 ----------
            self.log_queue.put(("INFO", ""))
            self.log_queue.put(("INFO", "=" * 60))
            total_matched = (
                web_result["matched_pages"]
                + db_result["matched_tables"]
                + file_result["matched_files"]
                + image_result["matched_images"]
            )
            self.log_queue.put(("SUCCESS",
                                f"  全部检查完成! 共发现 {total_matched} 处涉密"))
            self.log_queue.put(("INFO", "=" * 60))

            self.log_queue.put(("INFO", ""))
            self.log_queue.put(("INFO", "正在自动生成检查报告..."))
            try:
                report_path = generate_report(self.results, keywords)
                self.log_queue.put(("SUCCESS",
                                    f"  报告已生成: {report_path}"))
                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO",
                                    "提示: 可点击「生成报告」按钮重新生成"))
            except Exception as e:
                self.log_queue.put(("ERROR",
                                    f"  报告生成失败: {e}"))

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

        try:
            report_path = generate_report(self.results, keywords)
            self._log("SUCCESS", f"报告已生成: {report_path}")
            messagebox.showinfo("成功", f"报告已生成:\n{report_path}")
        except Exception as e:
            self._log("ERROR", f"报告生成失败: {e}")
            messagebox.showerror("错误", f"报告生成失败: {e}")

    # ==================== 日志与进度 ====================

    def _log(self, level, msg):
        """向日志区域追加一行（线程安全）"""
        self.log_queue.put((level, msg))

    def _poll_log_queue(self):
        """轮询日志队列，将消息写入UI"""
        while not self.log_queue.empty():
            try:
                level, msg = self.log_queue.get_nowait()
                self.log_text.config(state=tk.NORMAL)
                self.log_text.insert(tk.END, msg + "\n", level)
                self.log_text.see(tk.END)
                self.log_text.config(state=tk.DISABLED)
            except queue.Empty:
                break
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
