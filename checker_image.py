# -*- coding: utf-8 -*-
"""
图片检查模块 - 本地OCR识别图片中的涉密文字
引擎优先级：RapidOCR（轻量ONNX） > pytesseract
"""

import os
from collections import Counter

from utils import build_combined_pattern


def check_images(directory, keywords, log_callback=None):
    """
    递归扫描目录下所有图片，使用本地OCR检查涉密信息。

    参数:
        directory:  图片目录路径
        keywords:   关键词列表
        log_callback: 日志回调函数（可选）

    返回:
        dict: {
            "total_images": 图片总数,
            "matched_images": 涉密图片数,
            "ocr_engine": 使用的OCR引擎,
            "type_counts": {扩展名: 数量},
            "details": [{file, directory, filename, keyword, ocr_text}, ...]
        }
    """
    pattern = build_combined_pattern(keywords)
    if not pattern:
        return {"total_images": 0, "matched_images": 0,
                "ocr_engine": "N/A", "type_counts": {}, "details": []}

    if not os.path.isdir(directory):
        if log_callback:
            log_callback(f"  [图片] 目录不存在: {directory}")
        return {"total_images": 0, "matched_images": 0,
                "ocr_engine": "N/A", "type_counts": {}, "details": []}

    # 初始化OCR引擎（只做一次）
    ocr_engine, ocr_func = _init_ocr(log_callback)
    if ocr_func is None:
        if log_callback:
            log_callback("  [图片] 未找到可用的本地OCR引擎，"
                         "请安装 rapidocr-onnxruntime 或 pytesseract")
        return {"total_images": 0, "matched_images": 0,
                "ocr_engine": "无（请安装OCR引擎）", "type_counts": {},
                "details": []}

    img_exts = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.gif'}
    total_images = 0
    matched_images = set()
    details = []
    type_counts = Counter()

    for root, dirs, files in os.walk(directory):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in img_exts:
                continue

            total_images += 1
            type_counts[ext] += 1
            fpath = os.path.join(root, fname)

            if log_callback:
                log_callback(f"  [图片] 正在OCR: {fname}")

            try:
                ocr_text = ocr_func(fpath)
                if not ocr_text:
                    continue

                for line in ocr_text.split("\n"):
                    line_stripped = line.strip()
                    if not line_stripped:
                        continue
                    for m in pattern.finditer(line_stripped):
                        matched_images.add(fpath)
                        details.append({
                            "file": fpath,
                            "directory": root,
                            "filename": fname,
                            "keyword": m.group(),
                            "ocr_text": line_stripped[:150]
                        })
            except Exception as e:
                if log_callback:
                    log_callback(f"  [图片] OCR异常: {fname} - {e}")

    return {
        "total_images": total_images,
        "matched_images": len(matched_images),
        "ocr_engine": ocr_engine,
        "type_counts": dict(type_counts),
        "details": details
    }


# ==================== OCR引擎初始化 ====================

def _init_ocr(log_callback=None):
    """
    按优先级初始化本地OCR引擎：
      1. RapidOCR（ONNX Runtime，轻量无Paddle依赖）
      2. pytesseract（需预装Tesseract-OCR）
    返回: (引擎名称, 识别函数) 或 ("无", None)
    """
    # ---- 方案一：RapidOCR ----
    try:
        from rapidocr_onnxruntime import RapidOCR

        engine = RapidOCR()

        def rapid_ocr_func(img_path):
            result, _ = engine(img_path)
            if not result:
                return ""
            return "\n".join(item[1] for item in result)

        if log_callback:
            log_callback("  [图片] OCR引擎: RapidOCR (ONNX Runtime)")
        return "RapidOCR", rapid_ocr_func

    except ImportError:
        pass
    except Exception as e:
        if log_callback:
            log_callback(f"  [图片] RapidOCR 初始化失败: {e}")

    # ---- 方案二：pytesseract ----
    try:
        import pytesseract
        from PIL import Image

        def tesseract_ocr_func(img_path):
            img = Image.open(img_path)
            try:
                return pytesseract.image_to_string(img, lang="chi_sim")
            except Exception:
                return pytesseract.image_to_string(img)

        # 验证 tesseract 可执行文件是否存在
        pytesseract.get_tesseract_version()

        if log_callback:
            log_callback("  [图片] OCR引擎: pytesseract (Tesseract)")
        return "pytesseract", tesseract_ocr_func

    except ImportError:
        pass
    except Exception as e:
        if log_callback:
            log_callback(f"  [图片] pytesseract 不可用: {e}")

    return "无", None
