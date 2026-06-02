# -*- coding: utf-8 -*-
"""
报告生成模块 - 将检查结果汇总输出为标准 Markdown 报告
"""

import os
from datetime import datetime

from config import REPORT_DIR, OCR_CONFIDENCE_THRESHOLD


def _sanitize(text, max_len=50):
    """清理文本用于 Markdown 表格：去除换行、转义管道符、截断"""
    return text.replace("\r", "").replace("\n", " ")[:max_len].replace("|", "\\|")


def generate_report(results, keywords, output_dir=None):
    """
    生成 Markdown 格式的涉密信息检查报告。

    参数:
        results:    检查结果字典（包含 web/db/file/image 四个模块）
        keywords:   使用的关键词列表
        output_dir: 报告输出目录（默认使用配置中的路径）

    返回:
        str: 生成的报告文件路径
    """
    if output_dir is None:
        output_dir = REPORT_DIR

    os.makedirs(output_dir, exist_ok=True)

    # 生成带时间戳的文件名
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    filename = f"涉密检查报告_{timestamp}.md"
    filepath = os.path.join(output_dir, filename)

    # 构建报告内容
    lines = []
    lines.append("# 涉密信息综合检查报告")
    lines.append("")
    lines.append(f"**检查时间**: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**检查关键词**: {', '.join(keywords)}")
    lines.append("")

    # ========== 汇总统计 ==========
    lines.append("---")
    lines.append("")
    lines.append("## 一、汇总统计")
    lines.append("")

    web = results.get("web", {})
    db = results.get("db", {})
    file = results.get("file", {})
    image = results.get("image", {})

    total_matched = (
        (web.get("matched_pages", 0) + len(web.get("cached_matched_urls", [])))
        + db.get("matched_tables", 0)
        + file.get("matched_files", 0)
        + image.get("matched_images", 0)
    )

    lines.append("| 检查模块 | 检查总数 | 涉密数量 | 备注 |")
    lines.append("|---------|---------|---------|------|")
    web_note_parts = []
    skipped = web.get("skipped_pages", 0)
    new_pages = web.get("new_pages", 0)
    cached_matched_count = len(web.get("cached_matched_urls", []))
    if skipped:
        web_note_parts.append(f"跳过{skipped}个")
    if new_pages:
        web_note_parts.append(f"新增/更新{new_pages}个")
    web_matched_total = web.get('matched_pages', 0) + cached_matched_count
    lines.append(f"| 网页检查 | {web.get('total', 0)} 个页面 | "
                 f"{web_matched_total} 个页面 | "
                 f"{', '.join(web_note_parts) if web_note_parts else '-'} |")
    db_total = db.get('total_records', 0)
    db_candidate = db.get('candidate_records', 0)
    db_note = f"粗筛{db_candidate}条" if db_candidate else "-"
    lines.append(f"| 数据库检查 | {db_total} 条记录 | "
                 f"{db.get('matched_tables', 0)} 个表 | {db_note} |")
    enc_count = len(file.get("encrypted_files", []))
    dmg_count = len(file.get("damaged_files", []))
    hid_count = len(file.get("hidden_files", []))
    arch_count = file.get("archives_scanned", 0)
    enc_arch = len(file.get("encrypted_archives", []))
    file_note = []
    if arch_count:
        file_note.append(f"压缩包{arch_count}个")
    if enc_count:
        file_note.append(f"加密{enc_count}个")
    if dmg_count:
        file_note.append(f"损坏{dmg_count}个")
    if hid_count:
        file_note.append(f"隐藏{hid_count}个")
    lines.append(f"| 文件检查 | {file.get('supported_files', 0)} 个文件 | "
                 f"{file.get('matched_files', 0)} 个文件 | "
                 f"{', '.join(file_note) if file_note else '-'} |")
    lines.append(f"| 图片检查 | {image.get('total_images', 0)} 张图片 | "
                 f"{image.get('matched_images', 0)} 张图片 | "
                 f"OCR: {image.get('ocr_engine', 'N/A')} |")
    lines.append("")
    lines.append(f"**涉密总计**: {total_matched} 处")
    lines.append("")

    # ========== 网页检查详情 ==========
    lines.append("---")
    lines.append("")
    lines.append("## 二、网页检查详情")
    lines.append("")
    web_details = web.get("details", [])
    new_web = [d for d in web_details if not d.get("from_cache")]
    cached_web = [d for d in web_details if d.get("from_cache")]

    if new_web:
        lines.append(f"本次新发现 **{len(new_web)}** 处涉密匹配：")
        lines.append("")
        lines.append("| 序号 | URL | 行号 | 关键词 | 内容摘要 |")
        lines.append("|-----|-----|------|-------|---------|")
        for idx, d in enumerate(new_web, 1):
            url_short = d['url'][:60] + "..." if len(d['url']) > 60 else d['url']
            content_short = _sanitize(d['content'])
            lines.append(f"| {idx} | {url_short} | {d['line_no']} | "
                         f"{d['keyword']} | {content_short} |")
        lines.append("")

    if cached_web:
        lines.append(f"上次已发现的涉密内容（本次未变化，共 **{len(cached_web)}** 处）：")
        lines.append("")
        lines.append("| 序号 | URL | 行号 | 关键词 | 内容摘要 |")
        lines.append("|-----|-----|------|-------|---------|")
        for idx, d in enumerate(cached_web, 1):
            url_short = d['url'][:60] + "..." if len(d['url']) > 60 else d['url']
            content_short = _sanitize(d['content'])
            lines.append(f"| {idx} | {url_short} | {d['line_no']} | "
                         f"{d['keyword']} | {content_short} |")
        lines.append("")

    if not new_web and not cached_web:
        lines.append("未发现涉密内容。")
        lines.append("")

    # ========== 数据库检查详情 ==========
    lines.append("---")
    lines.append("")
    lines.append("## 三、数据库检查详情")
    lines.append("")
    db_details = db.get("details", [])
    table_stats = db.get("table_stats", {})

    if table_stats:
        lines.append("### 3.1 各表统计")
        lines.append("")
        lines.append("| 表名 | 记录总数 | 涉密记录数 | 文本字段数 | 总字段数 |")
        lines.append("|------|---------|-----------|----------|---------|")
        for tname, stat in table_stats.items():
            text_cols = stat.get('text_columns', stat.get('columns', []))
            lines.append(f"| {tname} | {stat['total_records']} | "
                         f"{stat['matched_records']} | "
                         f"{len(text_cols)} | {len(stat['columns'])} |")
        lines.append("")

    if db_details:
        lines.append("### 3.2 涉密匹配详情")
        lines.append("")
        lines.append(f"共发现 **{len(db_details)}** 处涉密匹配：")
        lines.append("")
        lines.append("| 序号 | 表名 | 字段 | 记录ID | 关键词 |")
        lines.append("|-----|------|------|-------|-------|")
        for idx, d in enumerate(db_details, 1):
            lines.append(f"| {idx} | {d['table']} | {d['field']} | "
                         f"{d['record_id']} | {d['keyword']} |")
    else:
        lines.append("未发现涉密内容。")
    lines.append("")

    # ========== 文件检查详情 ==========
    lines.append("---")
    lines.append("")
    lines.append("## 四、文件检查详情")
    lines.append("")

    # 各类型文件统计
    type_counts = file.get("type_counts", {})
    if type_counts:
        lines.append("### 4.1 文件类型统计")
        lines.append("")
        lines.append("| 文件类型 | 数量 |")
        lines.append("|---------|------|")
        type_names = {
            '.txt': 'TXT 文本', '.doc': 'DOC (旧版Word)',
            '.docx': 'DOCX (Word)', '.xls': 'XLS (旧版Excel)',
            '.xlsx': 'XLSX (Excel)', '.ppt': 'PPT (旧版PowerPoint)',
            '.pptx': 'PPTX (PowerPoint)', '.pdf': 'PDF',
            '.zip': 'ZIP 压缩包', '.rar': 'RAR 压缩包', '.7z': '7Z 压缩包'
        }
        for ext, count in sorted(type_counts.items()):
            name = type_names.get(ext, ext)
            lines.append(f"| {name} | {count} |")
        lines.append("")

    # 加密文件
    encrypted_files = file.get("encrypted_files", [])
    lines.append("### 4.2 加密文件")
    lines.append("")
    if encrypted_files:
        lines.append(f"共发现 **{len(encrypted_files)}** 个加密文件：")
        lines.append("")
        for idx, fpath in enumerate(encrypted_files, 1):
            lines.append(f"{idx}. `{fpath}`")
    else:
        lines.append("未发现加密文件。")
    lines.append("")

    # 损坏文件
    damaged_files = file.get("damaged_files", [])
    lines.append("### 4.3 损坏文件")
    lines.append("")
    if damaged_files:
        lines.append(f"共发现 **{len(damaged_files)}** 个损坏或格式异常的文件：")
        lines.append("")
        for idx, fpath in enumerate(damaged_files, 1):
            lines.append(f"{idx}. `{fpath}`")
    else:
        lines.append("未发现损坏文件。")
    lines.append("")

    # 隐藏文件
    hidden_files = file.get("hidden_files", [])
    lines.append("### 4.4 隐藏文件")
    lines.append("")
    if hidden_files:
        lines.append(f"共发现 **{len(hidden_files)}** 个隐藏文件：")
        lines.append("")
        for idx, fpath in enumerate(hidden_files, 1):
            lines.append(f"{idx}. `{fpath}`")
    else:
        lines.append("未发现隐藏文件。")
    lines.append("")

    # 涉密文件匹配详情
    lines.append("### 4.5 涉密匹配详情")
    lines.append("")
    file_details = file.get("details", [])
    if file_details:
        lines.append(f"共发现 **{len(file_details)}** 处涉密匹配：")
        lines.append("")
        lines.append("| 序号 | 文件路径 | 行号 | 类型 | 关键词 | 内容摘要 |")
        lines.append("|-----|---------|------|------|-------|---------|")
        for idx, d in enumerate(file_details, 1):
            file_short = (d['file'][:50] + "..."
                          if len(d['file']) > 50 else d['file'])
            content_short = _sanitize(d['content'])
            lines.append(f"| {idx} | {file_short} | {d['line_no']} | "
                         f"{d['file_type']} | {d['keyword']} | "
                         f"{content_short} |")
    else:
        lines.append("未发现涉密内容。")
    lines.append("")

    # ========== 图片检查详情 ==========
    lines.append("---")
    lines.append("")
    lines.append("## 五、图片检查详情")
    lines.append("")

    # 图片类型统计
    img_type_counts = image.get("type_counts", {})
    lines.append(f"OCR引擎: **{image.get('ocr_engine', 'N/A')}**")
    lines.append(f"置信度阈值: **{OCR_CONFIDENCE_THRESHOLD}**（低于此值的识别结果已过滤）")
    lines.append("")
    lines.append(f"共扫描图片: **{image.get('total_images', 0)}** 张")
    lines.append(f"涉密图片: **{image.get('matched_images', 0)}** 张")
    lines.append("")

    if img_type_counts:
        lines.append("### 5.1 图片类型统计")
        lines.append("")
        lines.append("| 图片类型 | 数量 |")
        lines.append("|---------|------|")
        img_type_names = {
            '.png': 'PNG', '.jpg': 'JPG', '.jpeg': 'JPEG',
            '.bmp': 'BMP', '.tiff': 'TIFF', '.tif': 'TIF',
            '.gif': 'GIF'
        }
        for ext, count in sorted(img_type_counts.items()):
            name = img_type_names.get(ext, ext.upper())
            lines.append(f"| {name} | {count} |")
        lines.append("")

    # 涉密图片列表
    image_details = image.get("details", [])
    lines.append("### 5.2 涉密图片列表")
    lines.append("")
    if image_details:
        lines.append(f"共发现 **{len(image_details)}** 处涉密匹配：")
        lines.append("")
        lines.append("| 序号 | 所在目录 | 文件名 | 关键词 | OCR识别文本 |")
        lines.append("|-----|---------|-------|-------|-----------|")
        for idx, d in enumerate(image_details, 1):
            dir_short = (d['directory'][:40] + "..."
                         if len(d['directory']) > 40 else d['directory'])
            ocr_short = _sanitize(d['ocr_text'], 60)
            lines.append(f"| {idx} | `{dir_short}` | "
                         f"{d['filename']} | {d['keyword']} | {ocr_short} |")
    else:
        lines.append("未发现涉密内容。")
    lines.append("")

    # ========== 报告尾部 ==========
    lines.append("---")
    lines.append("")
    lines.append("*报告自动生成，仅供参考。请以人工复核为准。*")

    # 写入文件
    report_content = "\n".join(lines)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_content)

    return filepath
