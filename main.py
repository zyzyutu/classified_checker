# -*- coding: utf-8 -*-
"""
主入口 - 涉密信息综合检查系统
启动GUI界面，包含全局异常捕获
"""

import sys
import tkinter as tk
from tkinter import ttk  # 这里修复了
from tkinter import messagebox


def main():
    """程序主入口，包含全局异常捕获"""
    try:
        root = tk.Tk()

        # 设置DPI缩放（Windows高分屏适配）
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        # 设置主题样式
        style = ttk.Style()  # 这里也修复了
        available_themes = style.theme_names()
        if "clam" in available_themes:
            style.theme_use("clam")
        elif "vista" in available_themes:
            style.theme_use("vista")

        # 导入并启动GUI
        from gui import App
        app = App(root)

        root.mainloop()

    except Exception as e:
        # 全局异常捕获：弹窗提示并记录
        error_msg = f"程序发生未捕获的异常:\n\n{type(e).__name__}: {e}"
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("系统错误", error_msg)
        except Exception:
            print(error_msg, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()