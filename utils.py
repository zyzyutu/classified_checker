# -*- coding: utf-8 -*-
"""
工具模块 - 正则表达式模糊匹配构建器
"""

import re


def build_fuzzy_pattern(keyword):
    """
    将关键词构建为正则模糊匹配模式。
    能识别：
      - 带空格的关键词，例如：绝  密
      - 带特殊符号的关键词，例如：机@密、秘～密
      - 关键词中间插入任意字符的情况
    原理：在关键词每个字符之间插入 .{0,2}?（匹配0~2个任意字符）
    """
    # 逐字符构建模糊模式，字符间允许插入0~2个任意字符
    pattern_parts = []
    for ch in keyword:
        pattern_parts.append(re.escape(ch))
    fuzzy = r'.{0,2}?'.join(pattern_parts)
    return re.compile(fuzzy, re.IGNORECASE)


def build_combined_pattern(keywords):
    """
    将多个关键词合并为一个正则表达式，用 | 连接。
    返回编译后的正则对象。
    """
    if not keywords:
        return None
    patterns = [build_fuzzy_pattern(kw) for kw in keywords]
    # 合并为一个大正则：每个子模式用非捕获组包裹
    combined = "|".join(f"(?:{p.pattern})" for p in patterns)
    return re.compile(combined, re.IGNORECASE)


def _extract_context(text, match, ctx_len=40):
    """提取匹配关键词周围的上下文片段"""
    start = match.start()
    end = match.end()
    ctx_start = max(0, start - ctx_len)
    ctx_end = min(len(text), end + ctx_len)
    snippet = text[ctx_start:ctx_end]
    if ctx_start > 0:
        snippet = "..." + snippet
    if ctx_end < len(text):
        snippet = snippet + "..."
    return snippet


def check_text_for_keywords(text, pattern):
    """
    扫描文本，返回所有关键词匹配。同一行的多个关键词合并为一条，同行重复匹配去重。
    内容摘要：短文本直接展示，长文本截取关键词周围的上下文。

    参数:
        text:   待检查的文本内容
        pattern: build_combined_pattern 生成的正则对象

    返回:
        [(行号, 行内容, 匹配关键词逗号分隔), ...]
    """
    line_matches = {}  # (line_no, content) -> {keywords}
    for i, line in enumerate(text.split("\n"), 1):
        line_stripped = line.strip()
        if not line_stripped:
            continue
        matches = [m for m in pattern.finditer(line_stripped) if m.group()]
        if not matches:
            continue
        # 短文本直接展示，长文本截取关键词上下文
        if len(line_stripped) <= 120:
            content = line_stripped
        else:
            content = _extract_context(line_stripped, matches[0])
        key = (i, content)
        if key not in line_matches:
            line_matches[key] = set()
        for m in matches:
            line_matches[key].add(m.group())
    return [(line_no, content, ", ".join(sorted(keywords)))
            for (line_no, content), keywords in line_matches.items()
            if keywords]
