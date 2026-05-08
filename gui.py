# -*- coding: utf-8 -*-
"""
GUI界面模块 - 基于tkinter的图形化操作界面
功能：路径显示与修改、关键词输入、开始检查、进度提示、结果展示
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import queue
import time

from config import (DOC_DIR, IMG_DIR,
                    DB_HOST, DB_USER, DB_PASSWORD, DB_NAME,
                    DEFAULT_KEYWORDS, WEB_TARGET_URL)
from checker_web import check_web
from checker_db import check_database
from checker_file import check_files
from checker_image import check_images
from report import generate_report


class App:
    """涉密信息综合检查系统主界面"""

    def __init__(self, root):
        self.root = root
        self.root.title("涉密信息综合检查系统")
        self.root.geometry("980x720")
        self.root.minsize(800, 600)

        # 消息队列：用于子线程向主线程安全传递日志
        self.log_queue = queue.Queue()
        # 检查结果存储
        self.results = {}
        # 检查线程引用
        self.check_thread = None

        self._build_ui()
        self._poll_log_queue()

    # ==================== UI构建 ====================

    def _build_ui(self):
        """构建完整界面布局，配置区:日志区 = 1:3"""
        # ========== 主容器 ==========
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        main_frame.rowconfigure(1, weight=3)
        main_frame.columnconfigure(0, weight=1)

        # ========== 上半区：配置 + 按钮 + 进度条（固定高度） ==========
        top_frame = ttk.Frame(main_frame)
        top_frame.grid(row=0, column=0, sticky=tk.EW)
        # 禁止顶部区域被压缩，给足够高度容纳所有控件
        top_frame.grid_propagate(False)
        top_frame.configure(height=220)

        # ---------- 配置区域 ----------
        config_frame = ttk.LabelFrame(top_frame, text="检查配置",
                                      padding=(15, 10, 15, 10))
        config_frame.pack(fill=tk.X, padx=4, pady=(4, 6))

        config_frame.columnconfigure(1, weight=1)
        row_pad = 8
        ctrl_pad = 8
        lbl_w = 12

        # 文档目录
        ttk.Label(config_frame, text="文档目录:", width=lbl_w,
                  anchor=tk.E).grid(row=0, column=0,
                                    padx=(0, 8), pady=row_pad)
        self.doc_dir_var = tk.StringVar(value=DOC_DIR)
        ttk.Entry(config_frame, textvariable=self.doc_dir_var,
                  state="readonly").grid(row=0, column=1,
                                         sticky=tk.EW, padx=(0, ctrl_pad))
        ttk.Button(config_frame, text="浏 览", width=8,
                   command=lambda: self._browse_dir(self.doc_dir_var)
                   ).grid(row=0, column=2)

        # 图片目录
        ttk.Label(config_frame, text="图片目录:", width=lbl_w,
                  anchor=tk.E).grid(row=1, column=0,
                                    padx=(0, 8), pady=row_pad)
        self.img_dir_var = tk.StringVar(value=IMG_DIR)
        ttk.Entry(config_frame, textvariable=self.img_dir_var,
                  state="readonly").grid(row=1, column=1,
                                         sticky=tk.EW, padx=(0, ctrl_pad))
        ttk.Button(config_frame, text="浏 览", width=8,
                   command=lambda: self._browse_dir(self.img_dir_var)
                   ).grid(row=1, column=2)

        # 数据库名
        ttk.Label(config_frame, text="数据库名:", width=lbl_w,
                  anchor=tk.E).grid(row=2, column=0,
                                    padx=(0, 8), pady=row_pad)
        self.db_name_var = tk.StringVar(value=DB_NAME)
        ttk.Entry(config_frame, textvariable=self.db_name_var
                  ).grid(row=2, column=1, sticky=tk.EW,
                         padx=(0, ctrl_pad))

        # 关键词
        ttk.Label(config_frame, text="检查关键词:", width=lbl_w,
                  anchor=tk.E).grid(row=3, column=0,
                                    padx=(0, 8), pady=row_pad)
        self.keywords_var = tk.StringVar(
            value=",".join(DEFAULT_KEYWORDS))
        ttk.Entry(config_frame, textvariable=self.keywords_var
                  ).grid(row=3, column=1, sticky=tk.EW,
                         padx=(0, ctrl_pad))
        ttk.Label(config_frame, text="(逗号分隔)",
                  foreground="gray").grid(row=3, column=2,
                                          sticky=tk.W, padx=(4, 0))

        # 目标网址
        ttk.Label(config_frame, text="目标网址:", width=lbl_w,
                  anchor=tk.E).grid(row=4, column=0,
                                    padx=(0, 8), pady=row_pad)
        self.web_url_var = tk.StringVar(value=WEB_TARGET_URL)
        ttk.Entry(config_frame, textvariable=self.web_url_var
                  ).grid(row=4, column=1, sticky=tk.EW,
                         padx=(0, ctrl_pad))

        # ---------- 操作按钮 ----------
        btn_frame = ttk.Frame(top_frame)
        btn_frame.pack(fill=tk.X, padx=4, pady=(0, 4))

        btn_pad_x = 10
        btn_h = 3

        self.start_btn = ttk.Button(btn_frame, text="▶ 开始检查",
                                    command=self._start_check)
        self.start_btn.pack(side=tk.LEFT, padx=btn_pad_x, ipady=btn_h)

        self.stop_btn = ttk.Button(btn_frame, text="■ 停止",
                                   command=self._stop_check,
                                   state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=btn_pad_x, ipady=btn_h)

        self.report_btn = ttk.Button(btn_frame, text="生成报告",
                                     command=self._generate_report,
                                     state=tk.DISABLED)
        self.report_btn.pack(side=tk.LEFT, padx=btn_pad_x, ipady=btn_h)

        self.clear_btn = ttk.Button(btn_frame, text="清空日志",
                                    command=self._clear_log)
        self.clear_btn.pack(side=tk.RIGHT, padx=btn_pad_x, ipady=btn_h)

        # ---------- 进度条 + 状态 ----------
        progress_frame = ttk.Frame(top_frame)
        progress_frame.pack(fill=tk.X, padx=4, pady=(0, 2))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            progress_frame, variable=self.progress_var,
            maximum=100, mode="determinate")
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(progress_frame, textvariable=self.status_var,
                  foreground="blue", width=14,
                  anchor=tk.E).pack(side=tk.RIGHT, padx=(8, 0))

        # ========== 下半区：日志/结果展示（占据剩余空间） ==========
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.grid(row=1, column=0, sticky=tk.NSEW)

        result_frame = ttk.LabelFrame(bottom_frame, text="检查日志与结果",
                                      padding=6)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.log_text = scrolledtext.ScrolledText(
            result_frame, wrap=tk.WORD, font=("Consolas", 9),
            state=tk.DISABLED, bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="white")
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self.log_text.tag_configure("INFO", foreground="#4EC9B0")
        self.log_text.tag_configure("WARN", foreground="#DCDCAA")
        self.log_text.tag_configure("ERROR", foreground="#F44747")
        self.log_text.tag_configure("SUCCESS", foreground="#6A9955")
        self.log_text.tag_configure("MATCH", foreground="#FF6B6B",
                                    font=("Consolas", 9, "bold"))

    # ==================== 文件/目录浏览 ====================

    def _browse_dir(self, var):
        """选择目录"""
        path = filedialog.askdirectory()
        if path:
            var.set(path)

    # ==================== 检查控制 ====================

    def _start_check(self):
        """启动检查（在子线程中执行）"""
        # 解析关键词
        kw_text = self.keywords_var.get().strip()
        if not kw_text:
            messagebox.showwarning("提示", "请输入检查关键词")
            return
        keywords = [kw.strip() for kw in kw_text.split(",") if kw.strip()]
        if not keywords:
            messagebox.showwarning("提示", "关键词不能为空")
            return

        # 禁用开始按钮，启用停止按钮
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.report_btn.config(state=tk.DISABLED)
        self.progress_var.set(0)
        self.results = {}

        # 清空日志
        self._clear_log()
        self._log("INFO", "=" * 60)
        self._log("INFO", "  涉密信息综合检查系统 - 开始检查")
        self._log("INFO", f"  关键词: {', '.join(keywords)}")
        self._log("INFO", "=" * 60)

        # 启动子线程
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
        """
        子线程：执行全部检查任务。
        使用日志队列与主线程通信。
        """
        try:
            web_url_input = self.web_url_var.get().strip()
            db_name_input = self.db_name_var.get().strip()
            doc_dir_input = self.doc_dir_var.get().strip()
            img_dir_input = self.img_dir_var.get().strip()

            total_steps = sum(1 for x in [web_url_input, db_name_input,
                                          doc_dir_input, img_dir_input] if x)
            if total_steps == 0:
                self.log_queue.put(("WARN", "所有检查项均为空，无任务可执行"))
                return
            current_step = 0

            def log_cb(msg):
                self.log_queue.put(("INFO", msg))

            # ---------- 1. 网页检查 ----------
            if web_url_input:
                current_step += 1
                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "━" * 50))
                self.log_queue.put(("INFO",
                                    f"[1/{total_steps}] 网页检查 - {web_url_input}"))
                self.log_queue.put(("INFO", "━" * 50))
                self._update_progress(5)

                web_result = check_web(
                    web_url_input, keywords, log_callback=log_cb)
                self.results["web"] = web_result
                self._update_progress(25)
                self.log_queue.put(("SUCCESS",
                                    f"  网页检查完成: {web_result['total']} 个页面, "
                                    f"{web_result['matched_pages']} 个涉密"))
            else:
                current_step += 1
                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "━" * 50))
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 网页检查 - 已跳过（未填写网址）"))
                self.log_queue.put(("INFO", "━" * 50))
                web_result = {"total": 0, "matched_pages": 0, "details": []}
                self.results["web"] = web_result

            # ---------- 2. 数据库检查 ----------
            if db_name_input:
                current_step += 1
                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "━" * 50))
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
                current_step += 1
                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "━" * 50))
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 数据库检查 - 已跳过（未填写数据库名）"))
                self.log_queue.put(("INFO", "━" * 50))
                db_result = {"total_tables": 0, "total_records": 0,
                             "matched_tables": 0, "details": []}
                self.results["db"] = db_result

            # ---------- 3. 文件检查 ----------
            if doc_dir_input:
                current_step += 1
                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "━" * 50))
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
                current_step += 1
                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "━" * 50))
                self.log_queue.put(("INFO",
                                    f"[{current_step}/{total_steps}] 文件检查 - 已跳过（未填写文档目录）"))
                self.log_queue.put(("INFO", "━" * 50))
                file_result = {"total_files": 0, "supported_files": 0,
                               "matched_files": 0, "type_counts": {},
                               "encrypted_files": [], "hidden_files": [],
                               "details": []}
                self.results["file"] = file_result

            # ---------- 4. 图片检查 ----------
            if img_dir_input:
                current_step += 1
                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "━" * 50))
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
                current_step += 1
                self.log_queue.put(("INFO", ""))
                self.log_queue.put(("INFO", "━" * 50))
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

            # 自动提示生成报告
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

            # 启用报告按钮
            self.root.after(0, lambda: self.report_btn.config(state=tk.NORMAL))

        except Exception as e:
            self.log_queue.put(("ERROR", f"检查过程发生异常: {e}"))
        finally:
            # 恢复按钮状态
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
