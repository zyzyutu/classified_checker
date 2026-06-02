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
    原理：在关键词每个字符之间插入 .{0,5}?（匹配0~5个任意字符）
    """
    # 对关键词中的特殊正则字符进行转义
    escaped = re.escape(keyword)
    # 在每个转义字符之间插入 .{0,5}?，允许中间插入少量任意字符
    parts = escaped.split(r'\ ')
    # split 后按原始字符重新处理：逐字符构建
    pattern_parts = []
    for ch in keyword:
        pattern_parts.append(re.escape(ch))
    # 在字符之间插入 .{0,5}?
    fuzzy = r'.{0,5}?'.join(pattern_parts)
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


