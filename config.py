# -*- coding: utf-8 -*-
"""
配置模块 - 集中管理所有默认路径、关键词和系统常量
"""

import os

# ========== 默认路径（严格按实验文档） ==========
DOC_DIR = r"F:\保密技术检查\document"
IMG_DIR = r"F:\保密技术检查\image"

# ========== MySQL 数据库连接配置 ==========
DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = os.environ.get("CLASSIFIED_CHECKER_DB_PASS", "521581")
DB_NAME = "baomi"

# ========== 默认关键词（严格按实验文档） ==========
DEFAULT_KEYWORDS = ["涉密", "秘密", "机密", "绝密", "保密", "泄密"]

# ========== 网页检查配置 ==========
WEB_TARGET_URL = "https://bm.yangyq.net/"
WEB_MAX_DEPTH = 5
WEB_MAX_WORKERS = 6
WEB_CACHE_PATH = r"D:\Tools\Claude\classified_checker\web_cache.json"

# ========== 图片检查配置 ==========
IMG_CACHE_PATH = r"D:\Tools\Claude\classified_checker\img_cache.json"
OCR_CONFIDENCE_THRESHOLD = 0.7   # OCR置信度阈值，低于此值的结果丢弃

# ========== 支持的文件类型 ==========
SUPPORTED_FILE_EXTS = {
    '.txt', '.doc', '.docx',
    '.xls', '.xlsx',
    '.ppt', '.pptx',
    '.pdf',
    '.zip', '.rar', '.7z'
}

# ========== 报告输出路径 ==========
REPORT_DIR = r"D:\Tools\Claude\classified_checker"

# ========== 检查结果持久化 ==========
RESULTS_PATH = r"D:\Tools\Claude\classified_checker\check_results.json"
