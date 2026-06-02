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

from utils import build_combined_pattern
from config import IMG_CACHE_PATH, OCR_CONFIDENCE_THRESHOLD

IMG_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.gif'}


def _file_md5(fpath):
    """计算文件内容的 MD5 哈希"""
    h = hashlib.md5()
    with open(fpath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_img_cache(cache_path):
    """读取图片OCR缓存"""
    if not os.path.isfile(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_img_cache(cache, cache_path):
    """保存图片OCR缓存"""
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def check_images(directory, keywords, log_callback=None, max_workers=4):
    """
    递归扫描目录下所有图片，使用本地OCR检查涉密信息。
    支持多线程并行OCR、MD5缓存、置信度过滤。

    参数:
        directory:    图片目录路径
        keywords:     关键词列表
        log_callback: 日志回调函数（可选）
        max_workers:  并行线程数（默认4）

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

    # 初始化OCR引擎（只做一次，所有线程共享）
    ocr_engine, ocr_func = _init_ocr(log_callback)
    if ocr_func is None:
        if log_callback:
            log_callback("  [图片] 未找到可用的本地OCR引擎，"
                         "请安装 rapidocr-onnxruntime 或 pytesseract")
        return {"total_images": 0, "matched_images": 0,
                "ocr_engine": "无（请安装OCR引擎）", "type_counts": {},
                "details": []}

    # 加载图片OCR缓存
    img_cache = _load_img_cache(IMG_CACHE_PATH)
    cached_hits = 0
    _cache_lock = threading.Lock()

    # ========== 阶段一：收集所有图片 ==========
    image_files = []
    type_counts = Counter()

    for root, dirs, files in os.walk(directory):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in IMG_EXTS:
                continue
            type_counts[ext] += 1
            fpath = os.path.join(root, fname)
            image_files.append((fpath, root, fname))

    total_images = len(image_files)
    if log_callback:
        log_callback(f"  [图片] 收集完成: {total_images} 张图片")

    if total_images == 0:
        return {"total_images": 0, "matched_images": 0,
                "ocr_engine": ocr_engine, "type_counts": {},
                "details": []}

    # ========== 阶段二：多线程并行OCR ==========
    matched_images = set()
    details = []

    def process_one_image(item):
        """处理单张图片，返回匹配结果"""
        nonlocal cached_hits
        fpath, root, fname = item

        # 计算文件MD5，查缓存
        md5 = _file_md5(fpath)
        with _cache_lock:
            if md5 in img_cache:
                ocr_items = img_cache[md5].get("ocr_items")
                if ocr_items is not None:
                    cached_hits += 1
                else:
                    ocr_items = None  # 旧缓存格式，需要重新识别
            else:
                ocr_items = None

        if ocr_items is None:
            # 缓存未命中，执行OCR
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

        # 置信度过滤 + 关键词匹配
        image_details = []
        for item in ocr_items:
            text = item[0]
            confidence = item[1]
            if confidence < OCR_CONFIDENCE_THRESHOLD:
                continue
            for line in text.split("\n"):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                for m in pattern.finditer(line_stripped):
                    image_details.append({
                        "file": fpath,
                        "directory": root,
                        "filename": fname,
                        "keyword": m.group(),
                        "ocr_text": line_stripped[:150]
                    })
        return image_details

    if log_callback:
        log_callback(f"  [图片] 开始并行OCR {total_images} 张图片 "
                     f"(线程{max_workers}, 置信度≥{OCR_CONFIDENCE_THRESHOLD})")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_one_image, item): item
                   for item in image_files}

        for future in as_completed(futures):
            try:
                image_details = future.result()
                for d in image_details:
                    matched_images.add(d["file"])
                details.extend(image_details)
            except Exception as e:
                if log_callback:
                    log_callback(f"  [图片] 处理异常: {futures[future][2]} - {e}")

    # 保存缓存
    _save_img_cache(img_cache, IMG_CACHE_PATH)
    if log_callback and cached_hits:
        log_callback(f"  [图片] 缓存命中 {cached_hits} 张, "
                     f"新识别 {total_images - cached_hits} 张, "
                     f"缓存共 {len(img_cache)} 条")

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
        import onnxruntime as ort

        # 优先使用 DirectML (AMD/Intel GPU)，否则用 CPU
        providers = ort.get_available_providers()
        if "DmlExecutionProvider" in providers:
            engine = RapidOCR(det_use_dml=True, rec_use_dml=True)
            ocr_label = "RapidOCR (DirectML GPU加速)"
        elif "CUDAExecutionProvider" in providers:
            engine = RapidOCR(det_use_cuda=True, rec_use_cuda=True)
            ocr_label = "RapidOCR (CUDA GPU加速)"
        else:
            engine = RapidOCR()
            ocr_label = "RapidOCR (CPU)"

        def rapid_ocr_func(img_path):
            """返回 [(文本, 置信度), ...] 列表，不做过滤"""
            result, _ = engine(img_path)
            if not result:
                return []
            return [(item[1], item[2]) for item in result]

        if log_callback:
            log_callback(f"  [图片] OCR引擎: {ocr_label}")
        return ocr_label, rapid_ocr_func

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
            """返回 [(文本, 置信度), ...] 列表，不做过滤"""
            img = Image.open(img_path)
            try:
                data = pytesseract.image_to_data(img, lang="chi_sim",
                                                  output_type=pytesseract.Output.DICT)
            except Exception:
                data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            # 按行聚合，返回 (文本, 置信度) 对
            results = []
            for i, text in enumerate(data["text"]):
                conf = float(data["conf"][i]) / 100.0  # pytesseract 返回 0~100
                if text.strip():
                    results.append((text.strip(), conf))
            return results

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
