# -*- coding: utf-8 -*-
"""
网页检查模块 - 全站遍历指定URL，检查页面内容是否包含涉密关键词
"""

from urllib.parse import urljoin, urlparse
from collections import deque

import requests
from bs4 import BeautifulSoup

from utils import build_combined_pattern


def check_web(url, keywords, log_callback=None):
    """
    全站遍历检查网页涉密信息。

    参数:
        url:        起始URL
        keywords:   关键词列表
        log_callback: 日志回调函数（可选）

    返回:
        dict: {
            "total": 总页面数,
            "matched_pages": 涉密页面数,
            "details": [{url, line_no, content, keyword}, ...]
        }
    """
    pattern = build_combined_pattern(keywords)
    if not pattern:
        return {"total": 0, "matched_pages": 0, "details": []}

    parsed_base = urlparse(url)
    base_domain = parsed_base.netloc

    visited = set()
    queue = deque([url])
    total = 0
    details = []
    matched_urls = set()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    }

    while queue:
        current_url = queue.popleft()
        if current_url in visited:
            continue
        visited.add(current_url)
        total += 1

        if log_callback:
            log_callback(f"  [网页] 正在检查: {current_url}")

        try:
            resp = requests.get(current_url, headers=headers, timeout=10,
                                verify=False, allow_redirects=True)
            resp.encoding = resp.apparent_encoding or "utf-8"
            html = resp.text
        except Exception as e:
            if log_callback:
                log_callback(f"  [网页] 请求失败: {current_url} - {e}")
            continue

        # 逐行检查页面文本内容
        soup = BeautifulSoup(html, "html.parser")
        text_content = soup.get_text(separator="\n")
        lines = text_content.split("\n")

        for i, line in enumerate(lines, 1):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            matches = search_text_line(line_stripped, pattern)
            for matched_text in matches:
                details.append({
                    "url": current_url,
                    "line_no": i,
                    "content": line_stripped[:120],
                    "keyword": matched_text
                })
                matched_urls.add(current_url)

        # 提取同域名链接，继续遍历（忽略外链）
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            full_url = urljoin(current_url, href)
            parsed = urlparse(full_url)
            if (parsed.netloc == base_domain
                    and full_url not in visited
                    and parsed.scheme in ("http", "https")):
                # 去除片段标识符
                clean_url = full_url.split("#")[0]
                if clean_url not in visited:
                    queue.append(clean_url)

    return {
        "total": total,
        "matched_pages": len(matched_urls),
        "details": details
    }


def search_text_line(line, pattern):
    """在单行文本中搜索所有匹配的关键词，返回匹配文本列表"""
    return [m.group() for m in pattern.finditer(line)]
