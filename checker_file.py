# -*- coding: utf-8 -*-
"""
文件检查模块 - 支持多种文档格式的涉密信息检查
包含：TXT、DOC、DOCX、XLS、XLSX、PPT、PPTX、PDF
功能：Magic Number校验、加密文件识别、异常不崩溃
"""

import os
import struct
from collections import Counter

from utils import build_combined_pattern

# ========== Magic Number 定义（文件头校验真实类型） ==========
MAGIC_NUMBERS = {
    '.doc':  [b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'],          # OLE2格式
    '.docx': [b'PK\x03\x04'],                                    # ZIP格式
    '.xls':  [b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'],          # OLE2格式
    '.xlsx': [b'PK\x03\x04'],                                    # ZIP格式
    '.ppt':  [b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'],          # OLE2格式
    '.pptx': [b'PK\x03\x04'],                                    # ZIP格式
    '.pdf':  [b'%PDF'],                                           # PDF格式
    '.txt':  None,  # TXT无固定Magic Number，不校验
}


def check_files(directory, keywords, log_callback=None):
    """
    递归扫描目录下所有支持的文件，检查涉密信息。

    参数:
        directory:  扫描目录路径
        keywords:   关键词列表
        log_callback: 日志回调函数（可选）

    返回:
        dict: {
            "total_files": 扫描文件总数,
            "supported_files": 支持格式文件数,
            "matched_files": 涉密文件数,
            "details": [{file, line_no, content, keyword, file_type}, ...]
        }
    """
    pattern = build_combined_pattern(keywords)
    if not pattern:
        return {"total_files": 0, "supported_files": 0,
                "matched_files": 0, "type_counts": {},
                "encrypted_files": [], "hidden_files": [],
                "details": []}

    if not os.path.isdir(directory):
        if log_callback:
            log_callback(f"  [文件] 目录不存在: {directory}")
        return {"total_files": 0, "supported_files": 0,
                "matched_files": 0, "type_counts": {},
                "encrypted_files": [], "hidden_files": [],
                "details": []}

    total_files = 0
    supported_files = 0
    matched_files = set()
    details = []
    type_counts = Counter()       # 各类型文件计数
    encrypted_files = []          # 加密文件列表
    hidden_files = []             # 隐藏文件列表

    for root, dirs, files in os.walk(directory):
        for fname in files:
            total_files += 1
            fpath = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lower()

            # 检测隐藏文件（Windows: FILE_ATTRIBUTE_HIDDEN = 0x02）
            try:
                import ctypes
                attrs = ctypes.windll.kernel32.GetFileAttributesW(fpath)
                if attrs != -1 and (attrs & 0x02):
                    hidden_files.append(fpath)
                    if log_callback:
                        log_callback(f"  [文件] 发现隐藏文件: {fpath}")
            except Exception:
                pass

            if ext not in MAGIC_NUMBERS:
                continue

            supported_files += 1
            type_counts[ext] += 1

            if log_callback:
                log_callback(f"  [文件] 正在检查: {fpath}")

            # Magic Number校验真实类型
            real_ext = _check_magic_number(fpath, ext)
            if real_ext != ext:
                if log_callback:
                    log_callback(f"  [文件] 类型不匹配: {fname} "
                                 f"(扩展名{ext}, 实际{real_ext})")

            # 读取文件内容并检查
            try:
                file_text = _extract_text(fpath, ext)
                if file_text is None:
                    encrypted_files.append(fpath)
                    if log_callback:
                        log_callback(f"  [文件] 无法读取或已加密: {fpath}")
                    continue

                # 检查提取结果是否为加密标记
                if file_text.startswith("[") and "加密" in file_text:
                    encrypted_files.append(fpath)
                    if log_callback:
                        log_callback(f"  [文件] 已加密: {fpath}")
                    continue

                lines = file_text.split("\n")
                for i, line in enumerate(lines, 1):
                    line_stripped = line.strip()
                    if not line_stripped:
                        continue
                    matches = pattern.finditer(line_stripped)
                    for m in matches:
                        matched_files.add(fpath)
                        details.append({
                            "file": fpath,
                            "line_no": i,
                            "content": line_stripped[:120],
                            "keyword": m.group(),
                            "file_type": ext
                        })
            except Exception as e:
                if log_callback:
                    log_callback(f"  [文件] 处理异常: {fpath} - {e}")

    return {
        "total_files": total_files,
        "supported_files": supported_files,
        "matched_files": len(matched_files),
        "type_counts": dict(type_counts),
        "encrypted_files": encrypted_files,
        "hidden_files": hidden_files,
        "details": details
    }


def _check_magic_number(fpath, expected_ext):
    """
    通过文件头Magic Number校验文件真实类型。
    返回实际检测到的扩展名，无法识别则返回原扩展名。
    """
    try:
        with open(fpath, 'rb') as f:
            header = f.read(16)
    except Exception:
        return expected_ext

    # ZIP格式：可能是docx/xlsx/pptx
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
        return '.docx'  # 默认

    # OLE2格式：可能是doc/xls/ppt
    if header.startswith(b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'):
        return expected_ext  # 无法精确区分，返回原扩展名

    # PDF格式
    if header.startswith(b'%PDF'):
        return '.pdf'

    return expected_ext


def _extract_text(fpath, ext):
    """
    根据文件类型提取文本内容。
    返回提取的文本字符串，无法读取返回None。
    """
    extractors = {
        '.txt': _extract_txt,
        '.doc': _extract_doc,
        '.docx': _extract_docx,
        '.xls': _extract_xls,
        '.xlsx': _extract_xlsx,
        '.ppt': _extract_ppt,
        '.pptx': _extract_pptx,
        '.pdf': _extract_pdf,
    }
    extractor = extractors.get(ext)
    if extractor:
        return extractor(fpath)
    return None


def _extract_txt(fpath):
    """提取TXT文件文本"""
    for enc in ('utf-8', 'gbk', 'gb2312', 'latin-1'):
        try:
            with open(fpath, 'r', encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    return None


def _extract_doc(fpath):
    """
    提取旧版DOC文件文本（OLE2格式）。
    使用 WPS/Word COM 接口，严格按实验文档要求：
      - pythoncom.CoInitialize() 初始化COM
      - WPS 预启动
    """
    # 方案一：通过 WPS/Word COM 接口读取（Windows环境推荐）
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()

        app = None
        doc = None
        try:
            # 优先尝试 WPS，其次 Microsoft Word
            for prog_id in ("KWps.Application", "WPS.Application",
                            "Word.Application", "et.Application"):
                try:
                    app = win32com.client.Dispatch(prog_id)
                    app.Visible = False
                    app.DisplayAlerts = False
                    break
                except Exception:
                    app = None
                    continue

            if app is None:
                return None

            # 以只读方式打开文档
            abs_path = os.path.abspath(fpath)
            doc = app.Documents.Open(abs_path, ReadOnly=True,
                                     PasswordDocument="",
                                     PasswordTemplate="",
                                     NoEncodingDialog=True)

            # 提取全文文本
            full_text = doc.Content.Text
            return full_text if full_text else None

        finally:
            # 确保释放COM资源
            if doc is not None:
                try:
                    doc.Close(SaveChanges=False)
                except Exception:
                    pass
            if app is not None:
                try:
                    app.Quit()
                except Exception:
                    pass
            pythoncom.CoUninitialize()

    except ImportError:
        pass  # 未安装 pywin32，跳到备用方案
    except Exception:
        pass  # COM调用异常，跳到备用方案

    # 方案二：使用 olefile 检测文件是否为加密文件（辅助判断）
    try:
        import olefile
        if olefile.isOleFile(fpath):
            ole = olefile.OleFileIO(fpath)
            # 检查是否为加密文件（Word文档加密时会写入 EncryptionInfo 流）
            is_encrypted = ole.exists('EncryptionInfo')
            ole.close()
            if is_encrypted:
                return "[DOC文件-已加密，无法读取]"
    except Exception:
        pass

    # 方案三：二进制暴力提取可打印字符（兜底方案）
    try:
        with open(fpath, 'rb') as f:
            raw = f.read()
        # 提取连续的可打印ASCII和中文GBK字符片段
        import re
        # 匹配连续中文字符（GBK编码：高位0xB0-0xF7，低位0xA1-0xFE）
        # 以及连续可打印ASCII
        text_parts = []
        # 方法：按字节扫描，提取GBK中文片段
        i = 0
        while i < len(raw):
            b = raw[i]
            # GBK中文双字节
            if 0xB0 <= b <= 0xF7 and i + 1 < len(raw):
                b2 = raw[i + 1]
                if 0xA1 <= b2 <= 0xFE:
                    # 连续GBK字符
                    start = i
                    while i < len(raw) - 1:
                        b = raw[i]
                        b2 = raw[i + 1]
                        if 0xB0 <= b <= 0xF7 and 0xA1 <= b2 <= 0xFE:
                            i += 2
                        else:
                            break
                    try:
                        segment = raw[start:i].decode('gbk', errors='ignore')
                        if len(segment) >= 2:
                            text_parts.append(segment)
                    except Exception:
                        pass
                    continue
            # ASCII可打印字符
            if 0x20 <= b <= 0x7E:
                start = i
                while i < len(raw) and 0x20 <= raw[i] <= 0x7E:
                    i += 1
                segment = raw[start:i].decode('ascii', errors='ignore')
                if len(segment) >= 4:
                    text_parts.append(segment)
                continue
            i += 1

        result = "\n".join(text_parts)
        return result if result else None
    except Exception:
        return None


def _extract_docx(fpath):
    """提取DOCX文件文本"""
    try:
        from docx import Document
        doc = Document(fpath)
        paragraphs = [p.text for p in doc.paragraphs]
        # 同时提取表格内容
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    paragraphs.append(cell.text)
        return "\n".join(paragraphs)
    except Exception:
        return None


def _extract_xls(fpath):
    """提取旧版XLS文件文本"""
    try:
        import xlrd
        wb = xlrd.open_workbook(fpath)
        texts = []
        for sheet in wb.sheets():
            for row_idx in range(sheet.nrows):
                row_values = [str(sheet.cell_value(row_idx, col))
                              for col in range(sheet.ncols)]
                texts.append("\t".join(row_values))
        return "\n".join(texts)
    except Exception:
        return None


def _extract_xlsx(fpath):
    """提取XLSX文件文本"""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(fpath, data_only=True)
        texts = []
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                row_text = "\t".join(str(c) if c is not None else ""
                                     for c in row)
                texts.append(row_text)
        return "\n".join(texts)
    except Exception:
        return None


def _extract_ppt(fpath):
    """
    提取旧版PPT文件文本（OLE2格式）。
    同DOC，使用 WPS/Word COM 接口读取。
    """
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()

        app = None
        pres = None
        try:
            for prog_id in ("KWpp.Application", "WPP.Application",
                            "PowerPoint.Application"):
                try:
                    app = win32com.client.Dispatch(prog_id)
                    app.Visible = False
                    break
                except Exception:
                    app = None
                    continue

            if app is None:
                return None

            abs_path = os.path.abspath(fpath)
            pres = app.Presentations.Open(abs_path, ReadOnly=True,
                                          WithWindow=False)

            texts = []
            for slide in pres.Slides:
                for shape in slide.Shapes:
                    if shape.HasTextFrame:
                        texts.append(shape.TextFrame.TextRange.Text)
                    if shape.HasTable:
                        for row in shape.Table.Rows:
                            for cell in row.Cells:
                                texts.append(cell.Shape.TextFrame
                                             .TextRange.Text)

            return "\n".join(texts) if texts else None

        finally:
            if pres is not None:
                try:
                    pres.Close()
                except Exception:
                    pass
            if app is not None:
                try:
                    app.Quit()
                except Exception:
                    pass
            pythoncom.CoUninitialize()

    except ImportError:
        pass
    except Exception:
        pass

    return None


def _extract_pptx(fpath):
    """提取PPTX文件文本"""
    try:
        from pptx import Presentation
        prs = Presentation(fpath)
        texts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for paragraph in shape.text_frame.paragraphs:
                        texts.append(paragraph.text)
                if shape.has_table:
                    for row in shape.table.rows:
                        for cell in row.cells:
                            texts.append(cell.text)
        return "\n".join(texts)
    except Exception:
        return None


def _extract_pdf(fpath):
    """提取PDF文件文本"""
    try:
        import PyPDF2
        texts = []
        with open(fpath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            if reader.is_encrypted:
                return None  # 加密文件
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    texts.append(text)
        return "\n".join(texts)
    except Exception:
        pass

    # 备用方案：pdfplumber
    try:
        import pdfplumber
        texts = []
        with pdfplumber.open(fpath) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    texts.append(text)
        return "\n".join(texts)
    except Exception:
        return None
