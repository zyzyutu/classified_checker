# -*- coding: utf-8 -*-
"""
报告生成模块 - 将检查结果汇总输出为标准 Markdown 报告
"""

import os
from datetime import datetime

from config import REPORT_DIR, OCR_CONFIDENCE_THRESHOLD


def _sanitize(text, max_len=40):
    """清理文本用于 Markdown 表格：去除换行、转义管道符、截断"""
    return text.replace("\r", "").replace("\n", " ")[:max_len].replace("|", "\\|")


def _trim_keywords(kw_str, max_show=5):
    """关键词过多时截断：显示前N个 + 省略"""
    parts = [k.strip() for k in kw_str.split(",") if k.strip()]
    if len(parts) <= max_show:
        return kw_str
    return ", ".join(parts[:max_show]) + f" 等{len(parts)}个"


def _md_table(headers, rows):
    """生成 Markdown 表格"""
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join(["-----"] * len(headers)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return lines


def _visual_width(s):
    """计算字符串的显示宽度（中文/全角占2，ASCII占1）"""
    import unicodedata
    w = 0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ('W', 'F'):
            w += 2
        else:
            w += 1
    return w


def _truncate_path(fpath, width=40):
    """长路径统一截断：固定视觉宽度，前缀 + ... + 文件名（过长也截断）"""
    if _visual_width(fpath) <= width:
        return fpath

    fname = os.path.basename(fpath)

    # 前缀：取前N个字符，使视觉宽度≈14（盘符 + 第一个目录）
    import unicodedata
    prefix = ""
    pw = 0
    for ch in fpath:
        cw = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
        if pw + cw > 14:
            break
        prefix += ch
        pw += cw

    # 文件名预算 = 总宽 - 前缀宽 - "/.../" (4)
    name_budget = width - pw - 4

    # 文件名过长则截断（保留扩展名）
    if _visual_width(fname) > name_budget:
        dot_pos = fname.rfind(".")
        if dot_pos > 0:
            ext = fname[dot_pos:]
            base = fname[:dot_pos]
            ext_w = _visual_width(ext)
            base_budget = name_budget - ext_w
            if base_budget < 2:
                base_budget = 2
            base_trunc = ""
            w = 0
            for ch in base:
                cw = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
                if w + cw > base_budget - 1:
                    break
                base_trunc += ch
                w += cw
            fname = base_trunc + "~" + ext
        else:
            fname = fname[:max(name_budget - 1, 2)] + "~"

    return f"{prefix}/.../{fname}"


def _file_list(title, items, empty_msg):
    """生成编号文件列表，长路径自动截断"""
    lines = [f"### {title}", ""]
    if items:
        lines.append(f"共 **{len(items)}** 个：")
        lines.append("")
        for i, fpath in enumerate(items, 1):
            lines.append(f"{i}. `{_truncate_path(fpath)}`")
    else:
        lines.append(empty_msg)
    lines.append("")
    return lines


# ==================== 各模块报告段 ====================

def _section_summary(web, db, file, image):
    """汇总统计表"""
    cached_count = len(web.get("cached_matched_urls", []))
    web_total = web.get("matched_pages", 0) + cached_count
    total_matched = (web_total + db.get("matched_tables", 0)
                     + file.get("matched_files", 0) + image.get("matched_images", 0))

    # 网页备注
    wn = []
    if web.get("skipped_pages"): wn.append(f"跳过{web['skipped_pages']}个")
    if web.get("new_pages"): wn.append(f"新增/更新{web['new_pages']}个")
    # 文件备注
    fn = []
    if file.get("archives_scanned"): fn.append(f"压缩包{file['archives_scanned']}个")
    for key, label in [("encrypted_files", "加密"), ("damaged_files", "损坏"),
                       ("hidden_files", "隐藏")]:
        cnt = len(file.get(key, []))
        if cnt: fn.append(f"{label}{cnt}个")
    # 数据库备注
    db_notes = []
    db_dbs = db.get("total_databases", 0)
    db_tbls = db.get("total_tables", 0)
    if db_dbs: db_notes.append(f"{db_dbs}个数据库")
    if db_tbls: db_notes.append(f"{db_tbls}个表")
    db_cand = db.get("candidate_records", 0)
    if db_cand: db_notes.append(f"粗筛{db_cand}条")
    db_note = ", ".join(db_notes) if db_notes else "-"

    rows = [
        ["网页检查", f"{web.get('total', 0)} 个页面", f"{web_total} 个页面",
         ", ".join(wn) if wn else "-"],
        ["数据库检查", f"{db.get('total_records', 0)} 条记录",
         f"{db.get('matched_tables', 0)} 个表", db_note],
        ["文件检查", f"{file.get('supported_files', 0)} 个文件",
         f"{file.get('matched_files', 0)} 个文件", ", ".join(fn) if fn else "-"],
        ["图片检查", f"{image.get('total_images', 0)} 张图片",
         f"{image.get('matched_images', 0)} 张图片",
         f"OCR: {image.get('ocr_engine', 'N/A')}"],
    ]

    lines = ["## 一、汇总统计", ""]
    lines += _md_table(["检查模块", "检查总数", "涉密数量", "备注"], rows)
    lines += ["", f"**涉密总计**: {total_matched} 处", ""]
    return lines


def _section_web(web):
    """网页检查详情"""
    details = web.get("details", [])
    new = [d for d in details if not d.get("from_cache")]
    cached = [d for d in details if d.get("from_cache")]

    lines = ["## 二、网页检查详情", ""]

    for subset, title_fmt in [(new, "本次新发现 **{}** 处涉密匹配："),
                              (cached, "上次已发现（本次未变化，共 **{}** 处）：")]:
        if not subset:
            continue
        lines.append(title_fmt.format(len(subset)))
        lines.append("")
        rows = []
        for idx, d in enumerate(subset, 1):
            url = d['url'][:60] + "..." if len(d['url']) > 60 else d['url']
            rows.append([idx, url, d['line_no'], _trim_keywords(d['keyword']),
                         _sanitize(d['content'])])
        lines += _md_table(["序号", "URL", "行号", "关键词", "内容摘要"], rows)
        lines.append("")

    if not new and not cached:
        lines.append("未发现涉密内容。")
        lines.append("")
    return lines


def _section_db(db):
    """数据库检查详情"""
    lines = ["## 三、数据库检查详情", ""]
    table_stats = db.get("table_stats", {})
    details = db.get("details", [])

    if table_stats:
        lines.append("### 3.1 各表统计")
        lines.append("")
        rows = []
        for tname, stat in table_stats.items():
            text_cols = stat.get('text_columns', stat.get('columns', []))
            rows.append([tname, stat['total_records'], stat['matched_records'],
                         len(text_cols), len(stat['columns'])])
        lines += _md_table(["表名", "记录总数", "涉密记录数", "文本字段数", "总字段数"], rows)
        lines.append("")

    if details:
        lines.append("### 3.2 涉密匹配详情")
        lines.append("")
        lines.append(f"共发现 **{len(details)}** 处涉密匹配：")
        lines.append("")
        rows = [[idx, d['table'], d['field'], d['record_id'], _trim_keywords(d['keyword'])]
                for idx, d in enumerate(details, 1)]
        lines += _md_table(["序号", "表名", "字段", "记录ID", "关键词"], rows)
    else:
        lines.append("未发现涉密内容。")
    lines.append("")
    return lines


def _section_file(file):
    """文件检查详情"""
    lines = ["## 四、文件检查详情", ""]

    # 文件类型统计
    type_counts = file.get("type_counts", {})
    if type_counts:
        type_names = {'.txt': 'TXT', '.doc': 'DOC', '.docx': 'DOCX', '.xls': 'XLS',
                      '.xlsx': 'XLSX', '.ppt': 'PPT', '.pptx': 'PPTX', '.pdf': 'PDF',
                      '.zip': 'ZIP', '.rar': 'RAR', '.7z': '7Z'}
        lines.append("### 4.1 文件类型统计")
        lines.append("")
        rows = [[type_names.get(ext, ext), count] for ext, count in sorted(type_counts.items())]
        lines += _md_table(["文件类型", "数量"], rows)
        lines.append("")

    # 加密/损坏/隐藏文件
    for sub_idx, (key, label, empty_msg) in enumerate([
        ("encrypted_files", "4.2 加密文件", "未发现加密文件。"),
        ("damaged_files", "4.3 损坏文件", "未发现损坏文件。"),
        ("hidden_files", "4.4 隐藏文件", "未发现隐藏文件。"),
    ], 2):
        lines += _file_list(label, file.get(key, []), empty_msg)

    # 涉密匹配详情
    details = file.get("details", [])
    lines.append("### 4.5 涉密匹配详情")
    lines.append("")
    if details:
        lines.append(f"共发现 **{len(details)}** 处涉密匹配：")
        lines.append("")
        rows = []
        for idx, d in enumerate(details, 1):
            fp = _truncate_path(d['file'])
            rows.append([idx, fp, d['line_no'], d['file_type'],
                         _trim_keywords(d['keyword']), _sanitize(d['content'])])
        lines += _md_table(["序号", "文件路径", "行号", "类型", "关键词", "内容摘要"], rows)
    else:
        lines.append("未发现涉密内容。")
    lines.append("")
    return lines


def _section_image(image):
    """图片检查详情"""
    lines = ["## 五、图片检查详情", ""]
    lines.append(f"OCR引擎: **{image.get('ocr_engine', 'N/A')}**")
    lines.append(f"置信度阈值: **{OCR_CONFIDENCE_THRESHOLD}**")
    lines.append(f"共扫描: **{image.get('total_images', 0)}** 张, "
                 f"涉密: **{image.get('matched_images', 0)}** 张")
    lines.append("")

    # 图片类型统计
    type_counts = image.get("type_counts", {})
    if type_counts:
        img_names = {'.png': 'PNG', '.jpg': 'JPG', '.jpeg': 'JPEG', '.bmp': 'BMP',
                     '.tiff': 'TIFF', '.tif': 'TIF', '.gif': 'GIF'}
        lines.append("### 5.1 图片类型统计")
        lines.append("")
        rows = [[img_names.get(ext, ext.upper()), count]
                for ext, count in sorted(type_counts.items())]
        lines += _md_table(["图片类型", "数量"], rows)
        lines.append("")

    # 涉密图片列表
    details = image.get("details", [])
    lines.append("### 5.2 涉密图片列表")
    lines.append("")
    if details:
        lines.append(f"共发现 **{len(details)}** 处涉密匹配：")
        lines.append("")
        rows = []
        for idx, d in enumerate(details, 1):
            dr = d['directory'][:40] + "..." if len(d['directory']) > 40 else d['directory']
            pos = d.get('position', '')
            rows.append([idx, f"`{dr}`", d['filename'], pos, _trim_keywords(d['keyword']),
                         _sanitize(d['ocr_text'], 40)])
        lines += _md_table(["序号", "所在目录", "文件名", "位置", "关键词", "OCR文本"], rows)
    else:
        lines.append("未发现涉密内容。")
    lines.append("")
    return lines


# ==================== 主函数 ====================

def generate_report(results, keywords, output_dir=None):
    """生成 Markdown 格式的涉密信息检查报告，返回文件路径。"""
    if output_dir is None:
        output_dir = REPORT_DIR
    os.makedirs(output_dir, exist_ok=True)

    now = datetime.now()
    filepath = os.path.join(output_dir, f"涉密检查报告_{now.strftime('%Y%m%d_%H%M%S')}.md")

    web = results.get("web", {})
    db = results.get("db", {})
    file = results.get("file", {})
    image = results.get("image", {})

    lines = [
        "# 涉密信息综合检查报告", "",
        f"**检查时间**: {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**检查关键词**: {', '.join(keywords)}", "",
        "---", "",
    ]
    lines += _section_summary(web, db, file, image)
    lines += ["---", ""]
    lines += _section_web(web)
    lines += ["---", ""]
    lines += _section_db(db)
    lines += ["---", ""]
    lines += _section_file(file)
    lines += ["---", ""]
    lines += _section_image(image)
    lines += ["---", "", "*报告自动生成，仅供参考。请以人工复核为准。*"]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return filepath
