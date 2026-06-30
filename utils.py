# -*- coding: utf-8 -*-
"""
工具模块 - 文本涉密检查工具
支持两种模式：
  1. 正则模糊匹配（传统方法，作为回退方案）
  2. 大模型语义分析（主要方法，通过 Ollama 调用本地大模型）
"""

import re


# ========== 正则模糊匹配（回退方案） ==========

def build_fuzzy_pattern(keyword):
    """
    将关键词构建为正则模糊匹配模式。
    能识别：
      - 带空格的关键词，例如：绝  密
      - 带特殊符号的关键词，例如：机@密、秘～密
      - 关键词中间插入任意字符的情况
    原理：在关键词每个字符之间插入 .{0,2}?（匹配0~2个任意字符）
    """
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
    正则模式：扫描文本，返回所有关键词匹配。
    同一行的多个关键词合并为一条，同行重复匹配去重。

    参数:
        text:   待检查的文本内容
        pattern: build_combined_pattern 生成的正则对象

    返回:
        [(行号, 行内容, 匹配关键词逗号分隔), ...]
    """
    line_matches = {}
    for i, line in enumerate(text.split("\n"), 1):
        line_stripped = line.strip()
        if not line_stripped:
            continue
        matches = [m for m in pattern.finditer(line_stripped) if m.group()]
        if not matches:
            continue
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


# ========== 统一接口（自动选择 LLM 或正则） ==========

def check_text(text, keywords, use_llm=False, llm_model=None,
               llm_base_url=None, llm_timeout=30, log_callback=None):
    """
    统一文本检查接口。

    参数:
        text:          待检查文本
        keywords:      关键词列表
        use_llm:       是否使用大模型（False 则用正则）
        llm_model:     Ollama 模型名
        llm_base_url:  Ollama 地址
        llm_timeout:   LLM 超时秒数
        log_callback:  日志回调

    返回:
        [(行号, 内容摘要, 匹配关键词), ...]
    """
    if use_llm:
        from llm_checker import check_text_for_keywords_llm
        return check_text_for_keywords_llm(
            text, keywords, model=llm_model,
            base_url=llm_base_url, timeout=llm_timeout,
            log_callback=log_callback
        )
    else:
        pattern = build_combined_pattern(keywords)
        if not pattern:
            return []
        return check_text_for_keywords(text, pattern)
