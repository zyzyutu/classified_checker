# -*- coding: utf-8 -*-
"""
文件检查模块 - 支持多种文档格式和压缩包的涉密信息检查
功能：Magic Number校验、加密文件识别、压缩包递归解压、多线程并行检查
文本提取逻辑在 extractors.py
"""

import os
import tempfile
import shutil
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils import build_combined_pattern, check_text_for_keywords
from extractors import extract_text, diagnose_extract_failure, _com_app_quit

# ========== Magic Number 定义（文件头校验真实类型） ==========
MAGIC_NUMBERS = {
    '.doc':  [b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'],
    '.docx': [b'PK\x03\x04'],
    '.xls':  [b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'],
    '.xlsx': [b'PK\x03\x04'],
    '.ppt':  [b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'],
    '.pptx': [b'PK\x03\x04'],
    '.pdf':  [b'%PDF'],
    '.txt':  None,
    '.zip':  [b'PK\x03\x04'],
    '.rar':  [b'Rar!\x1a\x07'],
    '.7z':   [b'7z\xbc\xaf\x27\x1c'],
}

ARCHIVE_EXTS = {'.zip', '.rar', '.7z'}
MAX_ARCHIVE_DEPTH = 3


# ==================== 压缩包处理 ====================

def _is_archive(fpath):
    """判断文件是否为支持的压缩包"""
    ext = os.path.splitext(fpath)[1].lower()
    if ext not in ARCHIVE_EXTS:
        return False
    try:
        with open(fpath, 'rb') as f:
            header = f.read(8)
    except Exception:
        return False
    if ext == '.zip':
        return header.startswith(b'PK\x03\x04')
    if ext == '.rar':
        return header.startswith(b'Rar!\x1a\x07')
    if ext == '.7z':
        return header.startswith(b'7z\xbc\xaf\x27\x1c')
    return False


def _is_archive_encrypted(fpath):
    """预检压缩包是否加密，避免静默提取空文件"""
    ext = os.path.splitext(fpath)[1].lower()
    try:
        if ext == '.zip':
            import zipfile
            with zipfile.ZipFile(fpath, 'r') as zf:
                return any(info.flag_bits & 0x1 for info in zf.infolist())
        if ext == '.rar':
            import rarfile
            with rarfile.RarFile(fpath, 'r') as rf:
                return rf.needs_password()
        if ext == '.7z':
            import py7zr
            with py7zr.SevenZipFile(fpath, 'r') as sz:
                return sz.needs_password()
    except Exception:
        pass
    return False


def _extract_archive(fpath, extract_dir):
    """解压压缩包到指定目录"""
    ext = os.path.splitext(fpath)[1].lower()
    if ext == '.zip':
        import zipfile
        with zipfile.ZipFile(fpath, 'r') as zf:
            zf.extractall(extract_dir)
    elif ext == '.rar':
        import rarfile
        with rarfile.RarFile(fpath, 'r') as rf:
            rf.extractall(extract_dir)
    elif ext == '.7z':
        import py7zr
        with py7zr.SevenZipFile(fpath, 'r') as sz:
            sz.extractall(extract_dir)


def _check_archive(fpath, pattern, log_callback, depth, visited_archives):
    """递归检查压缩包内部文件"""
    if depth > MAX_ARCHIVE_DEPTH:
        if log_callback:
            log_callback(f"  [文件] 压缩包超过最大嵌套深度({MAX_ARCHIVE_DEPTH}): {fpath}")
        return [], False

    abs_path = os.path.abspath(fpath)
    if abs_path in visited_archives:
        return [], False
    visited_archives.add(abs_path)

    details = []
    tmp_dir = tempfile.mkdtemp(prefix="classified_check_")
    try:
        # 预检加密（RAR/7z可能静默提取空文件）
        if _is_archive_encrypted(fpath):
            if log_callback:
                log_callback(f"  [文件] 加密压缩包: {fpath}")
            return [], True

        try:
            _extract_archive(fpath, tmp_dir)
        except Exception as e:
            err_msg = str(e).lower()
            # 检测加密特征
            if any(kw in err_msg for kw in ("password", "encrypted", "bad password",
                                              "requires password", "need password",
                                              "bad7zfile", "invalid header",
                                              "crc failed", "bad crc")):
                if log_callback:
                    log_callback(f"  [文件] 加密压缩包: {fpath}")
                return [], True
            # 其他解压异常视为损坏
            if log_callback:
                log_callback(f"  [文件] 压缩包损坏: {fpath} - {e}")
            return [], False

        for root, dirs, files in os.walk(tmp_dir):
            for fname in files:
                epath = os.path.join(root, fname)
                ext = os.path.splitext(fname)[1].lower()

                # 递归处理嵌套压缩包
                if ext in ARCHIVE_EXTS:
                    sub_details, _ = _check_archive(
                        epath, pattern, log_callback, depth + 1, visited_archives)
                    details.extend(sub_details)
                    continue

                if ext not in MAGIC_NUMBERS:
                    continue

                try:
                    file_text = extract_text(epath, ext)
                    if file_text is None:
                        continue
                    if file_text.startswith("[") and "加密" in file_text:
                        continue

                    for line_no, content, keyword in check_text_for_keywords(file_text, pattern):
                        details.append({
                            "file": fpath,
                            "line_no": line_no,
                            "content": content,
                            "keyword": keyword,
                            "file_type": f"[压缩包内{ext}]"
                        })
                except Exception:
                    pass
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    return details, False


# ==================== Magic Number 校验 ====================

def _check_magic_number(fpath, expected_ext):
    """通过文件头Magic Number校验文件真实类型"""
    try:
        with open(fpath, 'rb') as f:
            header = f.read(16)
    except Exception:
        return expected_ext

    if header.startswith(b'PK\x03\x04'):
        try:
            import zipfile
            if zipfile.is_zipfile(fpath):
                with zipfile.ZipFile(fpath, 'r') as zf:
                    names = zf.namelist()
                    if any('word/' in n for n in names):
                        return '.docx'
                    elif any('xl/' in n for n in names):
                        return '.xlsx'
                    elif any('ppt/' in n for n in names):
                        return '.pptx'
        except Exception:
            pass
        return '.docx'

    if header.startswith(b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'):
        return expected_ext
    if header.startswith(b'%PDF'):
        return '.pdf'
    return expected_ext


# ==================== 主检查函数 ====================

def check_files(dirs, keywords, log_callback=None, max_workers=6):
    """
    递归扫描目录下所有支持的文件和压缩包，多线程并行检查涉密信息。

    参数:
        dirs:         扫描目录路径（字符串或目录列表，分号分隔）
        keywords:     关键词列表
        log_callback: 日志回调函数（可选）
        max_workers:  并行线程数（默认6）
    """
    if isinstance(dirs, str):
        dirs = [d.strip() for d in dirs.split(";") if d.strip()]

    pattern = build_combined_pattern(keywords)
    empty_result = {
        "total_files": 0, "supported_files": 0, "matched_files": 0,
        "type_counts": {}, "encrypted_files": [], "damaged_files": [],
        "hidden_files": [], "archives_scanned": 0,
        "encrypted_archives": [], "details": []
    }
    if not pattern:
        return empty_result

    valid_dirs = []
    for d in dirs:
        if os.path.isdir(d):
            valid_dirs.append(d)
        elif log_callback:
            log_callback(f"  [文件] 目录不存在，跳过: {d}")
    if not valid_dirs:
        return empty_result

    # ========== 阶段一：收集所有文件 ==========
    all_files = []
    hidden_files = []

    for directory in valid_dirs:
        for root, subdirs, files in os.walk(directory):
            for fname in files:
                fpath = os.path.join(root, fname)
                ext = os.path.splitext(fname)[1].lower()

                is_hidden = False
                try:
                    import ctypes
                    attrs = ctypes.windll.kernel32.GetFileAttributesW(fpath)
                    if attrs != -1 and (attrs & 0x02):
                        is_hidden = True
                except Exception:
                    pass
                if fname.startswith("."):
                    is_hidden = True
                if is_hidden:
                    hidden_files.append(fpath)
                    if log_callback:
                        log_callback(f"  [文件] 发现隐藏文件: {fpath}")

                if ext in MAGIC_NUMBERS and ext not in ARCHIVE_EXTS:
                    all_files.append((fpath, ext, False))
                elif ext in ARCHIVE_EXTS:
                    all_files.append((fpath, ext, True))

    total_files = len([f for f in all_files if not f[2]])
    archive_files = [f for f in all_files if f[2]]

    if log_callback:
        log_callback(f"  [文件] 收集完成: {total_files} 个普通文件, "
                     f"{len(archive_files)} 个压缩包")

    # ========== 阶段二：多线程并行处理压缩包 ==========
    matched_files = set()
    details = []
    type_counts = Counter()
    encrypted_files = []
    damaged_files = []
    encrypted_archives = []
    archives_scanned = 0
    visited_archives = set()

    if log_callback:
        log_callback(f"  [文件] 开始处理压缩包 ({len(archive_files)} 个)")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for fpath, ext, _ in archive_files:
            futures[executor.submit(
                _check_archive, fpath, pattern, log_callback, 0, visited_archives
            )] = fpath

        for future in as_completed(futures):
            arch_path = futures[future]
            try:
                arch_details, is_encrypted = future.result()
                archives_scanned += 1
                if is_encrypted:
                    encrypted_archives.append(arch_path)
                else:
                    details.extend(arch_details)
                    if arch_details:
                        matched_files.add(arch_path)
                if log_callback:
                    log_callback(f"  [文件] 压缩包处理完成: {arch_path}")
            except Exception as e:
                if log_callback:
                    log_callback(f"  [文件] 压缩包处理异常: {arch_path} - {e}")

    # ========== 阶段三：多线程并行检查普通文件 ==========
    def process_one_file(fpath, ext):
        ext = _check_magic_number(fpath, ext)
        result_type = ext
        data = {"file": fpath, "ext": ext, "matched": False, "details": [],
                "encrypted": False, "damaged": False, "status_msg": ""}

        file_text = extract_text(fpath, ext)

        if file_text is None:
            reason = diagnose_extract_failure(fpath, ext)
            if reason == "encrypted":
                data["encrypted"] = True
                data["status_msg"] = "文件已加密"
            elif reason == "damaged":
                data["damaged"] = True
                data["status_msg"] = "文件损坏"
            elif reason == "missing_lib":
                data["damaged"] = True
                data["status_msg"] = "缺少解析库（需安装WPS或Office）"
            else:
                data["damaged"] = True
                data["status_msg"] = "无法读取"
            return result_type, data

        if file_text.startswith("[") and "加密" in file_text:
            data["encrypted"] = True
            data["status_msg"] = file_text.strip("[]")
            return result_type, data

        if file_text.startswith("[") and "损坏" in file_text:
            data["damaged"] = True
            data["status_msg"] = file_text.strip("[]")
            return result_type, data

        if file_text.startswith("[") and "缺少" in file_text:
            data["status_msg"] = file_text.strip("[]")
            return result_type, data

        # 补充检测：文件较大但提取文本极少 → 内容损坏
        try:
            file_size = os.path.getsize(fpath)
        except Exception:
            file_size = 0
        if file_size > 10240 and len(file_text.strip()) < 10:
            reason = diagnose_extract_failure(fpath, ext)
            if reason == "encrypted":
                data["encrypted"] = True
                data["status_msg"] = "文件已加密"
            else:
                data["damaged"] = True
                data["status_msg"] = "文件损坏（内容无法解析）"
            return result_type, data

        file_details = []
        for line_no, content, keyword in check_text_for_keywords(file_text, pattern):
            file_details.append({
                "file": fpath, "line_no": line_no,
                "content": content, "keyword": keyword, "file_type": ext
            })

        if file_details:
            data["matched"] = True
            data["details"] = file_details
        return result_type, data

    if log_callback:
        normal_count = len([f for f in all_files if not f[2]])
        log_callback(f"  [文件] 开始并行检查 {normal_count} 个文件 (线程{max_workers})")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for fpath, ext, is_archive in all_files:
            if not is_archive:
                futures[executor.submit(process_one_file, fpath, ext)] = fpath

        for future in as_completed(futures):
            try:
                _, data = future.result()
                if data["encrypted"]:
                    encrypted_files.append(data["file"])
                    if log_callback:
                        log_callback(f"  [文件] 已加密: {data['file']} "
                                     f"({data.get('status_msg', '')})")
                elif data["damaged"]:
                    damaged_files.append(data["file"])
                    if log_callback:
                        log_callback(f"  [文件] 文件损坏: {data['file']} "
                                     f"({data.get('status_msg', '')})")
                elif data["matched"]:
                    matched_files.add(data["file"])
                    details.extend(data["details"])
                type_counts[data["ext"]] += 1
            except Exception as e:
                if log_callback:
                    log_callback(f"  [文件] 处理异常: {futures[future]} - {e}")

    # 释放缓存的 COM 应用（Word/WPS），不再逐文件重启
    _com_app_quit()

    return {
        "total_files": total_files,
        "supported_files": total_files,
        "matched_files": len(matched_files),
        "type_counts": dict(type_counts),
        "encrypted_files": encrypted_files,
        "damaged_files": damaged_files,
        "hidden_files": hidden_files,
        "archives_scanned": archives_scanned,
        "encrypted_archives": encrypted_archives,
        "details": details
    }
