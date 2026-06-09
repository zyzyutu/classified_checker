# -*- coding: utf-8 -*-
"""
图片检查模块 - 本地OCR识别图片中的涉密文字
引擎优先级：RapidOCR（轻量ONNX） > pytesseract
支持多线程并行OCR、MD5缓存跳过相同图片、置信度过滤
"""

import hashlib
import json
import os
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils import build_combined_pattern, check_text_for_keywords
from config import IMG_CACHE_PATH, OCR_CONFIDENCE_THRESHOLD

IMG_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.gif'}


def _bbox_position(bbox, img_height):
    """根据OCR边界框和图片高度，判断文字在图片的哪个位置"""
    try:
        y_mid = (bbox[0][1] + bbox[2][1]) / 2
        ratio = y_mid / img_height
        if ratio < 0.33:
            return "上部"
        elif ratio < 0.66:
            return "中部"
        else:
            return "下部"
    except Exception:
        return ""


# 空结果模板
_EMPTY = {"total_images": 0, "matched_images": 0,
          "ocr_engine": "N/A", "type_counts": {}, "details": []}


def _file_md5(fpath):
    h = hashlib.md5()
    with open(fpath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_img_cache(path):
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_img_cache(cache, path):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _init_ocr(log_callback=None):
    """
    初始化 RapidOCR 引擎。
    返回: (引擎名称, 识别函数) 或 ("无", None)
    识别函数签名: f(img_path) -> [(文本, 置信度, 位置), ...]
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
        import onnxruntime as ort

        providers = ort.get_available_providers()
        if "DmlExecutionProvider" in providers:
            engine = RapidOCR(det_use_dml=True, rec_use_dml=True)
            label = "RapidOCR (DirectML)"
        elif "CUDAExecutionProvider" in providers:
            engine = RapidOCR(det_use_cuda=True, rec_use_cuda=True)
            label = "RapidOCR (CUDA)"
        else:
            engine = RapidOCR()
            label = "RapidOCR (CPU)"

        def ocr_func(img_path):
            from PIL import Image
            result, _ = engine(img_path)
            if not result:
                return []
            img_h = Image.open(img_path).height
            return [(item[1], item[2], _bbox_position(item[0], img_h))
                    for item in result]

        if log_callback:
            log_callback(f"  [图片] OCR引擎: {label}")
        return label, ocr_func
    except ImportError:
        pass
    except Exception as e:
        if log_callback:
            log_callback(f"  [图片] RapidOCR 初始化失败: {e}")

    return "无", None


def check_images(dirs, keywords, log_callback=None, max_workers=4):
    """
    递归扫描目录下所有图片，OCR检查涉密信息。
    参数:
        dirs:         图片目录（字符串或列表，分号分隔）
        keywords:     关键词列表
        log_callback: 日志回调
        max_workers:  并行线程数
    """
    if isinstance(dirs, str):
        dirs = [d.strip() for d in dirs.split(";") if d.strip()]

    pattern = build_combined_pattern(keywords)
    if not pattern:
        return _EMPTY

    valid_dirs = [d for d in dirs if os.path.isdir(d)]
    if not valid_dirs:
        for d in dirs:
            if log_callback:
                log_callback(f"  [图片] 目录不存在，跳过: {d}")
        return _EMPTY

    ocr_engine, ocr_func = _init_ocr(log_callback)
    if ocr_func is None:
        if log_callback:
            log_callback("  [图片] 未找到OCR引擎，请安装 rapidocr-onnxruntime 或 pytesseract")
        return {**_EMPTY, "ocr_engine": "无（请安装OCR引擎）"}

    img_cache = _load_img_cache(IMG_CACHE_PATH)
    cached_hits = 0
    _cache_lock = threading.Lock()

    # 收集图片
    image_files = []
    type_counts = Counter()
    for directory in valid_dirs:
        for root, _, files in os.walk(directory):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in IMG_EXTS:
                    type_counts[ext] += 1
                    image_files.append((os.path.join(root, fname), root, fname))

    total_images = len(image_files)
    if log_callback:
        log_callback(f"  [图片] 收集完成: {total_images} 张图片")
    if total_images == 0:
        return {**_EMPTY, "ocr_engine": ocr_engine}

    # 并行OCR
    matched_images = set()
    details = []

    def process_one(item):
        nonlocal cached_hits
        fpath, root, fname = item
        md5 = _file_md5(fpath)

        with _cache_lock:
            entry = img_cache.get(md5, {})
            ocr_items = entry.get("ocr_items")
            if ocr_items is not None:
                cached_hits += 1
            else:
                ocr_items = None

        if ocr_items is None:
            try:
                ocr_items = ocr_func(fpath)
                if ocr_items:
                    with _cache_lock:
                        img_cache[md5] = {"ocr_items": ocr_items}
            except Exception as e:
                if log_callback:
                    log_callback(f"  [图片] OCR异常: {fname} - {e}")
                return []

        if not ocr_items:
            return []

        result = []
        for item in ocr_items:
            # 兼容旧缓存2元组 (text, confidence) 和新3元组 (text, confidence, position)
            text, confidence = item[0], item[1]
            position = item[2] if len(item) > 2 else ""
            if confidence < OCR_CONFIDENCE_THRESHOLD:
                continue
            for _, content, keyword in check_text_for_keywords(text, pattern):
                result.append({"file": fpath, "directory": root,
                               "filename": fname, "keyword": keyword,
                               "ocr_text": content, "position": position})
        return result

    if log_callback:
        log_callback(f"  [图片] 开始并行OCR {total_images} 张 "
                     f"(线程{max_workers}, 置信度≥{OCR_CONFIDENCE_THRESHOLD})")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_one, item): item for item in image_files}
        for future in as_completed(futures):
            try:
                for d in future.result():
                    matched_images.add(d["file"])
                    details.append(d)
            except Exception as e:
                if log_callback:
                    log_callback(f"  [图片] 处理异常: {futures[future][2]} - {e}")

    _save_img_cache(img_cache, IMG_CACHE_PATH)
    if log_callback and cached_hits:
        log_callback(f"  [图片] 缓存命中 {cached_hits} 张, "
                     f"新识别 {total_images - cached_hits} 张")

    return {"total_images": total_images, "matched_images": len(matched_images),
            "ocr_engine": ocr_engine, "type_counts": dict(type_counts), "details": details}
