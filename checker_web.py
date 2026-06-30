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

from utils import build_combined_pattern, check_text_for_keywords, check_text

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
        return False
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return True
    except IOError:
        return False


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


def _check_page(url, html, pattern, keywords=None, use_llm=False,
                llm_model=None, llm_base_url=None, log_callback=None):
    """检查单个页面内容，返回 (details, new_links)"""
    soup = BeautifulSoup(html, "html.parser")
    text_content = soup.get_text(separator="\n")

    details = []
    if use_llm and llm_model and keywords:
        matches = check_text(text_content, keywords, use_llm=True,
                             llm_model=llm_model, llm_base_url=llm_base_url,
                             log_callback=log_callback)
    else:
        matches = check_text_for_keywords(text_content, pattern)
    for line_no, content, keyword in matches:
        details.append({
            "url": url,
            "line_no": line_no,
            "content": content,
            "keyword": keyword
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

def _check_single_web(url, pattern, log_callback=None, max_depth=None,
                      max_workers=6, incremental=False, cache=None,
                      keywords=None, use_llm=False, llm_model=None,
                      llm_base_url=None):
    """
    BFS 并行爬取单个起始URL的网页涉密信息。
    """
    if cache is None:
        cache = {}

    parsed_base = urlparse(url)
    base_domain = parsed_base.netloc

    visited = set()
    all_details = []
    matched_urls = set()
    skipped_matched = set()   # 本次跳过但缓存标记为涉密的 URL
    total = 0
    skipped = 0
    new_or_changed = 0

    # 当前深度的 URL 队列
    current_level = [url]
    visited.add(url)
    depth = 0

    while current_level:

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
                    if log_callback:
                        log_callback(f"  [网页] 跳过(未变化): {page_url}")
                    # 跳过的页面：如果有缓存匹配详情，加入跳过匹配集合
                    cached_details = cache.get(page_url, {}).get("cached_details", [])
                    if cached_details:
                        skipped_matched.add(page_url)
                        for d in cached_details:
                            d_copy = dict(d)
                            d_copy["from_cache"] = True
                            all_details.append(d_copy)
                    # 跳过的页面也要提取链接，保证深度遍历不中断
                    if max_depth is None or depth < max_depth:
                        cached_links = cache.get(page_url, {}).get("links", [])
                        for link in cached_links:
                            if link not in visited:
                                visited.add(link)
                                next_level.append(link)
                    continue

                if html is not None:
                    pages_to_check.append((page_url, html))
                    # 更新缓存条目
                    if log_callback:
                        has_etag = bool(info.get("etag"))
                        has_lm = bool(info.get("last_modified"))
                        log_callback(f"  [网页] 获取页面: {page_url[:60]}... etag={has_etag} last_modified={has_lm}")
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
                executor.submit(_check_page, p_url, p_html, pattern,
                                keywords, use_llm, llm_model, llm_base_url,
                                log_callback): p_url
                for p_url, p_html in pages_to_check
            }
            for future in as_completed(check_futures):
                page_url = check_futures[future]
                details, new_links = future.result()
                all_details.extend(details)
                if details:
                    matched_urls.add(page_url)
                # 保存匹配详情到缓存（供增量模式跳过时使用）
                if page_url in cache:
                    cache[page_url]["cached_details"] = details

                # 保存链接到缓存（供下次增量时跳过的页面使用）
                if page_url in cache and new_links:
                    cache[page_url]["links"] = new_links

                # 收集下一层链接（去重）
                if max_depth is None or depth < max_depth:
                    for link in new_links:
                        if link not in visited:
                            visited.add(link)
                            next_level.append(link)

        if log_callback:
            log_callback(f"  [网页] 深度{depth} 完成，"
                         f"累计涉密页面: {len(matched_urls)}, "
                         f"跳过: {skipped}, 新增/更新: {new_or_changed}")

        current_level = next_level
        depth += 1

    # 本次跳过但缓存标记为涉密的 URL（排除本次有新匹配的）
    cached_matched_urls = []
    if incremental:
        for skipped_url in skipped_matched:
            if skipped_url not in matched_urls:
                cached_matched_urls.append(skipped_url)

    return {
        "total": total,
        "matched_pages": len(matched_urls),
        "skipped_pages": skipped,
        "new_pages": new_or_changed,
        "details": all_details,
        "cached_matched_urls": cached_matched_urls
    }


def check_web(urls, keywords, log_callback=None, max_depth=None,
              max_workers=6, incremental=False, cache_path=None,
              use_llm=False, llm_model=None, llm_base_url=None):
    """
    多线程并行爬取检查网页涉密信息。支持多起始URL。

    参数:
        urls:         起始URL（字符串或URL列表）
        keywords:     关键词列表
        log_callback: 日志回调函数（可选）
        max_depth:    最大爬取深度（None=无限深度全站遍历）
        max_workers:  并行线程数（默认6）
        incremental:  是否启用增量检测
        cache_path:   缓存文件路径
        use_llm:      是否使用大模型
        llm_model:    Ollama 模型名
        llm_base_url: Ollama 地址

    返回:
        dict: {
            "total": 总页面数,
            "matched_pages": 涉密页面数,
            "skipped_pages": 跳过（未变化）页面数,
            "new_pages": 新增/变化页面数,
            "details": [{url, line_no, content, keyword}, ...]
        }
    """
    # 统一为列表
    if isinstance(urls, str):
        urls = [u.strip() for u in urls.split(";") if u.strip()]

    pattern = build_combined_pattern(keywords)
    if not pattern:
        return {"total": 0, "matched_pages": 0,
                "skipped_pages": 0, "new_pages": 0,
                "details": [], "cached_matched_urls": []}

    # 加载缓存（所有URL共享同一份缓存）
    cache = load_cache(cache_path) if incremental else {}
    if log_callback:
        log_callback(f"  [网页] 增量={incremental}, 缓存条目={len(cache)}, "
                     f"起始URL={len(urls)}个")

    # 合并所有URL的结果
    total = 0
    matched_pages = 0
    skipped = 0
    new_or_changed = 0
    all_details = []
    all_cached_matched = []

    for i, start_url in enumerate(urls, 1):
        if log_callback:
            log_callback(f"  [网页] ({i}/{len(urls)}) 开始爬取: {start_url}")

        result = _check_single_web(
            start_url, pattern,
            log_callback=log_callback,
            max_depth=max_depth,
            max_workers=max_workers,
            incremental=incremental,
            cache=cache,
            keywords=keywords,
            use_llm=use_llm,
            llm_model=llm_model,
            llm_base_url=llm_base_url
        )

        total += result["total"]
        matched_pages += result["matched_pages"]
        skipped += result["skipped_pages"]
        new_or_changed += result["new_pages"]
        all_details.extend(result["details"])
        all_cached_matched.extend(result.get("cached_matched_urls", []))

    # 保存缓存（所有URL爬完后统一保存）
    if incremental:
        success = save_cache(cache, cache_path)
        if log_callback:
            log_callback(f"  [网页] 保存缓存: {len(cache)} 条, 成功={success}")

    return {
        "total": total,
        "matched_pages": matched_pages,
        "skipped_pages": skipped,
        "new_pages": new_or_changed,
        "details": all_details,
        "cached_matched_urls": all_cached_matched
    }
