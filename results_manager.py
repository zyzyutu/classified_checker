# -*- coding: utf-8 -*-
"""
结果持久化模块 - 将检查结果保存到 JSON 文件，支持历史查看
策略：同一文件只保留最新检查结果（覆盖模式）
"""

import json
import os
from datetime import datetime


def save_results(results, keywords, results_path):
    """
    保存检查结果到 JSON 文件。同一文件路径只保留最新结果。

    参数:
        results:      检查结果字典（包含 web/db/file/image 四个模块）
        keywords:     使用的关键词列表
        results_path: JSON 文件路径
    """
    now = datetime.now().isoformat(timespec='seconds')

    # 构建持久化数据（只保存需要的字段）
    data = {
        "last_check_time": now,
        "keywords": keywords,
        "files": {},
        "images": {},
        "web_pages": {},
        "db_tables": {}
    }

    # ---------- 文件检查结果 ----------
    file_result = results.get("file", {})
    for d in file_result.get("details", []):
        fpath = d["file"]
        # 同一文件只保留最新的
        data["files"][fpath] = {
            "checked_at": now,
            "matched": True,
            "file_type": d.get("file_type", ""),
            "matches": [
                {"line_no": d["line_no"], "keyword": d["keyword"],
                 "content": d["content"]}
            ]
        }

    # 记录未涉密的文件（从 type_counts 无法得知具体文件，只记录涉密的）
    # 加密文件单独记录
    for fpath in file_result.get("encrypted_files", []):
        if fpath not in data["files"]:
            data["files"][fpath] = {
                "checked_at": now,
                "matched": False,
                "status": "encrypted",
                "matches": []
            }

    # 隐藏文件单独记录
    for fpath in file_result.get("hidden_files", []):
        if fpath not in data["files"]:
            data["files"][fpath] = {
                "checked_at": now,
                "matched": False,
                "status": "hidden",
                "matches": []
            }

    # ---------- 图片检查结果 ----------
    image_result = results.get("image", {})
    for d in image_result.get("details", []):
        fpath = d["file"]
        data["images"][fpath] = {
            "checked_at": now,
            "matched": True,
            "ocr_engine": image_result.get("ocr_engine", ""),
            "matches": [
                {"keyword": d["keyword"], "ocr_text": d["ocr_text"]}
            ]
        }

    # ---------- 网页检查结果 ----------
    web_result = results.get("web", {})
    for d in web_result.get("details", []):
        url = d["url"]
        if url not in data["web_pages"]:
            data["web_pages"][url] = {
                "checked_at": now,
                "matched": True,
                "matches": []
            }
        data["web_pages"][url]["matches"].append(
            {"line_no": d["line_no"], "keyword": d["keyword"],
             "content": d["content"]}
        )

    # ---------- 数据库检查结果 ----------
    db_result = results.get("db", {})
    for d in db_result.get("details", []):
        table = d["table"]
        key = f"{table}.{d['field']}"
        if key not in data["db_tables"]:
            data["db_tables"][key] = {
                "checked_at": now,
                "matched": True,
                "table": table,
                "field": d["field"],
                "matches": []
            }
        data["db_tables"][key]["matches"].append(
            {"record_id": d["record_id"], "keyword": d["keyword"]}
        )

    # 写入文件
    try:
        os.makedirs(os.path.dirname(results_path), exist_ok=True)
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_results(results_path):
    """
    读取保存的检查结果。

    返回: dict 或 None（文件不存在或损坏时）
    """
    if not os.path.isfile(results_path):
        return None
    try:
        with open(results_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def format_history_summary(data):
    """
    将保存的结果格式化为可读的摘要文本（用于 GUI 显示）。

    返回: str
    """
    if not data:
        return "暂无历史检查记录"

    lines = []
    lines.append(f"上次检查时间: {data.get('last_check_time', '未知')}")
    lines.append(f"检查关键词: {', '.join(data.get('keywords', []))}")
    lines.append("")

    # 文件统计
    files = data.get("files", {})
    matched_files = {k: v for k, v in files.items() if v.get("matched")}
    encrypted = {k: v for k, v in files.items() if v.get("status") == "encrypted"}
    hidden = {k: v for k, v in files.items() if v.get("status") == "hidden"}
    lines.append(f"文件检查: {len(files)} 个文件, "
                 f"{len(matched_files)} 个涉密, "
                 f"{len(encrypted)} 个加密, "
                 f"{len(hidden)} 个隐藏")

    # 图片统计
    images = data.get("images", {})
    matched_images = {k: v for k, v in images.items() if v.get("matched")}
    lines.append(f"图片检查: {len(images)} 张图片, "
                 f"{len(matched_images)} 张涉密")

    # 网页统计
    web_pages = data.get("web_pages", {})
    lines.append(f"网页检查: {len(web_pages)} 个涉密页面")

    # 数据库统计
    db_tables = data.get("db_tables", {})
    lines.append(f"数据库检查: {len(db_tables)} 个涉密字段")

    lines.append("")
    lines.append("— 涉密文件列表 —")
    for fpath, info in sorted(matched_files.items()):
        keywords = set(m["keyword"] for m in info.get("matches", []))
        lines.append(f"  {fpath}")
        lines.append(f"    关键词: {', '.join(keywords)}")

    lines.append("")
    lines.append("— 涉密图片列表 —")
    for fpath, info in sorted(matched_images.items()):
        keywords = set(m["keyword"] for m in info.get("matches", []))
        lines.append(f"  {fpath}")
        lines.append(f"    关键词: {', '.join(keywords)}")

    if web_pages:
        lines.append("")
        lines.append("— 涉密网页列表 —")
        for url, info in sorted(web_pages.items()):
            keywords = set(m["keyword"] for m in info.get("matches", []))
            lines.append(f"  {url}")
            lines.append(f"    关键词: {', '.join(keywords)}")

    if db_tables:
        lines.append("")
        lines.append("— 涉密数据库字段 —")
        for key, info in sorted(db_tables.items()):
            lines.append(f"  {info['table']}.{info['field']}")
            keywords = set(m["keyword"] for m in info.get("matches", []))
            lines.append(f"    关键词: {', '.join(keywords)}")

    return "\n".join(lines)
