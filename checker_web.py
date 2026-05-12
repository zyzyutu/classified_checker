# -*- coding: utf-8 -*-
"""
网页检查模块 - 多线程并行爬取，支持增量检测（ETag/Last-Modified/内容哈希）
"""

import hashlib
import json
import os
from datetime import datetime
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

from utils import build_combined_pattern

# 全局 Session 复用连接池
_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
})
_session.verify = False


# ==================== 缓存管理 ====================

def load_cache(cache_path):
    """读取缓存文件，损坏时返回空字典"""
    if not cache_path or not os.path.isfile(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_cache(cache, cache_path):
    """写入缓存文件"""
    if not cache_path:
        return
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except IOError:
        pass


def _content_hash(html):
    """计算页面内容的 MD5 哈希"""
    return hashlib.md5(html.encode("utf-8", errors="ignore")).hexdigest()


# ==================== 页面抓取 ====================

def _fetch_page(url, cache_entry=None, incremental=False):
    """
    抓取单个页面。

    返回: (status, url, html, info)
        status: "new" | "changed" | "not_modified"
        info: dict with etag/last_modified for cache update (增量模式)
    """
    empty_info = {}

    if incremental and cache_entry:
        headers = {}
        if cache_entry.get("etag"):
            headers["If-None-Match"] = cache_entry["etag"]
        if cache_entry.get("last_modified"):
            headers["If-Modified-Since"] = cache_entry["last_modified"]

        try:
            resp = _session.get(url, timeout=10, allow_redirects=True,
                                headers=headers)
            if resp.status_code == 304:
                return "not_modified", url, None, empty_info
            resp.encoding = resp.apparent_encoding or "utf-8"
            html = resp.text

            # 检查内容哈希是否变化
            new_hash = _content_hash(html)
            old_hash = cache_entry.get("content_hash")
            if old_hash and new_hash == old_hash:
                return "not_modified", url, None, empty_info

            # 提取响应头中的缓存信息
            info = {
                "etag": resp.headers.get("ETag", ""),
                "last_modified": resp.headers.get("Last-Modified", ""),
            }
            return "changed", url, html, info
        except Exception:
            return "new", url, None, empty_info
    else:
        try:
            resp = _session.get(url, timeout=10, allow_redirects=True)
            resp.encoding = resp.apparent_encoding or "utf-8"
            info = {}
            if incremental:
                info = {
                    "etag": resp.headers.get("ETag", ""),
                    "last_modified": resp.headers.get("Last-Modified", ""),
                }
            return "new", url, resp.text, info
        except Exception:
            return "new", url, None, empty_info


def _check_page(url, html, pattern):
    """检查单个页面内容，返回 (details, new_links)"""
    soup = BeautifulSoup(html, "html.parser")
    text_content = soup.get_text(separator="\n")
    lines = text_content.split("\n")

    details = []
    for i, line in enumerate(lines, 1):
        line_stripped = line.strip()
        if not line_stripped:
            continue
        for m in pattern.finditer(line_stripped):
            details.append({
                "url": url,
                "line_no": i,
                "content": line_stripped[:120],
                "keyword": m.group()
            })

    # 提取同域名链接
    new_links = []
    parsed_base = urlparse(url)
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(url, href)
        parsed = urlparse(full_url)
        clean_url = full_url.split("#")[0]
        if (parsed.netloc == parsed_base.netloc
                and parsed.scheme in ("http", "https")):
            new_links.append(clean_url)

    return details, new_links


# ==================== 主检查函数 ====================

def check_web(url, keywords, log_callback=None, max_depth=5,
              max_workers=6, incremental=False, cache_path=None):
    """
    多线程并行爬取检查网页涉密信息。

    参数:
        url:          起始URL
        keywords:     关键词列表
        log_callback: 日志回调函数（可选）
        max_depth:    最大爬取深度（0表示只检查起始页面）
        max_workers:  并行线程数（默认6）
        incremental:  是否启用增量检测
        cache_path:   缓存文件路径

    返回:
        dict: {
            "total": 总页面数,
            "matched_pages": 涉密页面数,
            "skipped_pages": 跳过（未变化）页面数,
            "new_pages": 新增/变化页面数,
            "details": [{url, line_no, content, keyword}, ...]
        }
    """
    pattern = build_combined_pattern(keywords)
    if not pattern:
        return {"total": 0, "matched_pages": 0,
                "skipped_pages": 0, "new_pages": 0, "details": []}

    # 加载缓存
    cache = load_cache(cache_path) if incremental else {}

    parsed_base = urlparse(url)
    base_domain = parsed_base.netloc

    visited = set()
    all_details = []
    matched_urls = set()
    total = 0
    skipped = 0
    new_or_changed = 0

    # 当前深度的 URL 队列
    current_level = [url]
    visited.add(url)

    for depth in range(max_depth + 1):
        if not current_level:
            break

        if log_callback:
            mode = "增量" if incremental else "全量"
            log_callback(f"  [网页] 深度{depth}: {mode}检查 {len(current_level)} 个页面 (线程{max_workers})")

        next_level = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 并行抓取当前层所有页面
            futures = {
                executor.submit(
                    _fetch_page, u,
                    cache.get(u) if incremental else None,
                    incremental
                ): u for u in current_level
            }
            pages_to_check = []
            for future in as_completed(futures):
                status, page_url, html, info = future.result()
                total += 1

                if status == "not_modified":
                    skipped += 1
                    continue

                if html is not None:
                    pages_to_check.append((page_url, html))
                    # 更新缓存条目
                    cache_entry = {
                        "content_hash": _content_hash(html),
                        "last_checked": datetime.now().isoformat()
                    }
                    if info.get("etag"):
                        cache_entry["etag"] = info["etag"]
                    if info.get("last_modified"):
                        cache_entry["last_modified"] = info["last_modified"]
                    # 保留旧的 etag/last_modified（如果新响应没返回）
                    old = cache.get(page_url, {})
                    if not cache_entry.get("etag") and old.get("etag"):
                        cache_entry["etag"] = old["etag"]
                    if not cache_entry.get("last_modified") and old.get("last_modified"):
                        cache_entry["last_modified"] = old["last_modified"]
                    cache[page_url] = cache_entry

                new_or_changed += 1

            # 并行检查内容
            check_futures = {
                executor.submit(_check_page, p_url, p_html, pattern): p_url
                for p_url, p_html in pages_to_check
            }
            for future in as_completed(check_futures):
                page_url = check_futures[future]
                details, new_links = future.result()
                all_details.extend(details)
                if details:
                    matched_urls.add(page_url)

                # 收集下一层链接（去重）
                if depth < max_depth:
                    for link in new_links:
                        if link not in visited:
                            visited.add(link)
                            next_level.append(link)

        if log_callback:
            log_callback(f"  [网页] 深度{depth} 完成，"
                         f"累计涉密页面: {len(matched_urls)}, "
                         f"跳过: {skipped}, 新增/更新: {new_or_changed}")

        current_level = next_level

    # 保存缓存
    if incremental:
        save_cache(cache, cache_path)

    return {
        "total": total,
        "matched_pages": len(matched_urls),
        "skipped_pages": skipped,
        "new_pages": new_or_changed,
        "details": all_details
    }
