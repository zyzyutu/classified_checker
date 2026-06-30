# -*- coding: utf-8 -*-
"""
大模型检查模块 - 通过 Ollama 本地大模型进行语义级涉密信息检测
替代传统正则模糊匹配，能理解语义、识别变体表达、过滤误报
"""

import json
import requests
import re


# ========== Ollama 配置 ==========
OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b"


def check_ollama_connection(base_url=None):
    """检查 Ollama 服务是否可用"""
    url = base_url or OLLAMA_BASE_URL
    try:
        resp = requests.get(f"{url}/api/tags", timeout=5)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            return True, models
        return False, []
    except Exception as e:
        return False, []


def list_local_models(base_url=None):
    """获取 Ollama 已下载的模型列表"""
    ok, models = check_ollama_connection(base_url)
    return models if ok else []


def analyze_text_with_llm(text, keywords, model=None, base_url=None, timeout=30):
    """
    用大模型分析文本是否包含涉密信息。

    参数:
        text:     待检查的文本内容
        keywords: 关键词列表（如 ["涉密", "秘密", "机密"]）
        model:    Ollama 模型名称
        base_url: Ollama 服务地址
        timeout:  请求超时秒数

    返回:
        dict: {
            "has_sensitive": bool,      # 是否包含涉密信息
            "matches": [                # 匹配详情列表
                {"keyword": str, "context": str, "reason": str}
            ],
            "error": str or None        # 错误信息
        }
    """
    url = base_url or OLLAMA_BASE_URL
    model = model or DEFAULT_MODEL

    if not text or not text.strip():
        return {"has_sensitive": False, "matches": [], "error": None}

    # 截断过长文本，避免超出模型上下文窗口
    max_chars = 4000
    if len(text) > max_chars:
        text = text[:max_chars] + "...(文本已截断)"

    keywords_str = "、".join(keywords)

    prompt = f"""你是一个涉密信息检查专家。请分析以下文本是否包含涉密信息。

检查关键词：{keywords_str}

判断规则：
1. 如果文本中明确包含上述关键词或其变体（如"机密文件"、"绝密级"、"涉密人员"等），判定为涉密
2. 如果关键词出现在正常语境中（如"保密协议"、"保密工作"等），也应标记
3. 如果文本不包含任何涉密相关内容，判定为不涉密
4. 注意识别变体表达，如"机 密"（中间有空格）、"秘~密"（中间有符号）等

请严格按以下JSON格式返回结果，不要返回其他内容：
{{"has_sensitive": true/false, "matches": [{{"keyword": "匹配的关键词", "context": "包含关键词的原文片段", "reason": "判定理由"}}]}}

待检查文本：
{text}"""

    try:
        resp = requests.post(
            f"{url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,      # 低温度，结果更确定
                    "num_predict": 512,      # 限制输出长度
                }
            },
            timeout=timeout
        )

        if resp.status_code != 200:
            return {"has_sensitive": False, "matches": [],
                    "error": f"Ollama 请求失败: HTTP {resp.status_code}"}

        response_text = resp.json().get("response", "").strip()
        return _parse_llm_response(response_text)

    except requests.Timeout:
        return {"has_sensitive": False, "matches": [],
                "error": f"Ollama 请求超时({timeout}s)"}
    except requests.ConnectionError:
        return {"has_sensitive": False, "matches": [],
                "error": "无法连接 Ollama 服务，请确认 Ollama 已启动"}
    except Exception as e:
        return {"has_sensitive": False, "matches": [],
                "error": f"LLM 调用异常: {e}"}


def _parse_llm_response(response_text):
    """解析大模型返回的 JSON 结果"""
    # 尝试提取 JSON 部分（模型可能返回额外文字）
    json_match = re.search(r'\{[\s\S]*\}', response_text)
    if json_match:
        try:
            result = json.loads(json_match.group())
            # 校验结构
            if "has_sensitive" not in result:
                result["has_sensitive"] = False
            if "matches" not in result:
                result["matches"] = []
            result["error"] = None
            return result
        except json.JSONDecodeError:
            pass

    # JSON 解析失败，尝试从文本中推断结果
    has_sensitive = any(kw in response_text for kw in ["true", "是", "包含", "涉密"])
    return {
        "has_sensitive": has_sensitive,
        "matches": [{"keyword": "未知", "context": response_text[:200], "reason": "JSON解析失败"}],
        "error": None
    }


def check_text_for_keywords_llm(text, keywords, model=None, base_url=None,
                                 timeout=30, log_callback=None):
    """
    用大模型检查文本中的涉密关键词（替代 check_text_for_keywords）。

    参数:
        text:         待检查文本
        keywords:     关键词列表
        model:        Ollama 模型名
        base_url:     Ollama 地址
        timeout:      超时秒数
        log_callback: 日志回调

    返回:
        [(行号, 内容摘要, 匹配关键词), ...]  — 与原 check_text_for_keywords 格式一致
    """
    results = []

    # 按段落/行分割，逐段检查（避免文本过长）
    lines = text.split("\n")
    batch_size = 10  # 每次发10行给LLM，减少请求次数

    for batch_start in range(0, len(lines), batch_size):
        batch_lines = lines[batch_start:batch_start + batch_size]
        batch_text = "\n".join(batch_lines)

        if not batch_text.strip():
            continue

        llm_result = analyze_text_with_llm(
            batch_text, keywords, model=model,
            base_url=base_url, timeout=timeout
        )

        if llm_result["error"]:
            if log_callback:
                log_callback(f"  [LLM] 分析异常: {llm_result['error']}")
            continue

        if llm_result["has_sensitive"]:
            for match in llm_result["matches"]:
                # 定位匹配所在的具体行号
                matched_line = _find_line_number(
                    lines, batch_start, match.get("context", ""))
                content = match.get("context", "")[:120]
                keyword = match.get("keyword", "未知")
                results.append((matched_line, content, keyword))

    # 去重：同行同关键词只保留一条
    seen = set()
    deduped = []
    for line_no, content, keyword in results:
        key = (line_no, keyword)
        if key not in seen:
            seen.add(key)
            deduped.append((line_no, content, keyword))

    return deduped


def _find_line_number(all_lines, batch_start, context):
    """在原始文本中定位匹配内容的行号"""
    if not context:
        return batch_start + 1

    # 在当前批次中搜索匹配的行
    for i, line in enumerate(all_lines[batch_start:batch_start + 10], batch_start):
        # 取关键词片段在行中搜索
        context_short = context[:30].strip()
        if context_short and context_short in line:
            return i + 1

    return batch_start + 1  # 找不到就返回批次首行


def check_database_with_llm(adapter, db_name, keywords, model=None,
                            base_url=None, timeout=30, log_callback=None):
    """
    用大模型检查单个数据库（替代 check_database 中的正则匹配）。

    流程：
      1. 获取表元数据（同原逻辑）
      2. SQL LIKE 粗筛（同原逻辑）
      3. LLM 语义精匹配（替代 Python re）
    """
    from db_adapters import _is_text_type

    try:
        adapter.use_database(db_name)
    except Exception as e:
        if log_callback:
            log_callback(f"  [数据库] 切换失败({db_name}): {e}")
        return {"total_tables": 0, "total_records": 0,
                "candidate_records": 0, "matched_tables": 0,
                "table_stats": {}, "details": []}

    try:
        tables_meta = adapter.get_tables_metadata(db_name)
    except Exception as e:
        if log_callback:
            log_callback(f"  [数据库] 获取元数据失败({db_name}): {e}")
        return {"total_tables": 0, "total_records": 0,
                "candidate_records": 0, "matched_tables": 0,
                "table_stats": {}, "details": []}

    total_tables = len(tables_meta)
    if log_callback:
        log_callback(f"  [数据库] {db_name}: 发现 {total_tables} 个表")

    if total_tables == 0:
        return {"total_tables": 0, "total_records": 0,
                "candidate_records": 0, "matched_tables": 0,
                "table_stats": {}, "details": []}

    total_records = 0
    candidate_records = 0
    matched_tables = set()
    details = []
    table_stats = {}

    for table_name, meta in tables_meta.items():
        all_columns = meta['columns']
        text_columns = meta['text_columns']
        table_record_count = meta['row_count']

        if not text_columns:
            table_stats[table_name] = {
                "total_records": 0, "matched_records": 0,
                "columns": all_columns, "text_columns": []
            }
            continue

        total_records += table_record_count

        if table_record_count == 0:
            table_stats[table_name] = {
                "total_records": 0, "matched_records": 0,
                "columns": all_columns, "text_columns": text_columns
            }
            continue

        # 第一轮：SQL LIKE 粗筛
        if log_callback:
            log_callback(f"  [数据库] {db_name}.{table_name}: LIKE粗筛 "
                         f"({table_record_count}条 → 候选...)")
        try:
            candidates = adapter.query_candidates(table_name, text_columns, keywords)
        except Exception as e:
            if log_callback:
                log_callback(f"  [数据库] {db_name}.{table_name} 查询失败: {e}")
            table_stats[table_name] = {
                "total_records": table_record_count, "matched_records": 0,
                "columns": all_columns, "text_columns": text_columns
            }
            continue

        candidate_count = len(candidates)
        candidate_records += candidate_count

        if log_callback:
            log_callback(f"  [数据库] {db_name}.{table_name}: 候选 {candidate_count} 条，"
                         f"LLM语义分析中...")

        # 第二轮：LLM 语义精匹配（替代 Python re）
        table_matched_records = set()
        raw_details = {}
        pk_columns = meta.get('pk_columns', [])

        for row_idx, row in enumerate(candidates):
            if pk_columns:
                record_id = (row.get(pk_columns[0]) if len(pk_columns) == 1
                             else "-".join(str(row.get(c, "")) for c in pk_columns))
            else:
                record_id = row_idx + 1

            for col_name in text_columns:
                value = row.get(col_name)
                if value is None:
                    continue

                # 用 LLM 分析单个字段值
                llm_result = analyze_text_with_llm(
                    str(value), keywords, model=model,
                    base_url=base_url, timeout=timeout
                )

                if llm_result["error"]:
                    if log_callback:
                        log_callback(f"  [LLM] {table_name}.{col_name} 分析异常: "
                                     f"{llm_result['error']}")
                    continue

                if llm_result["has_sensitive"]:
                    matched_tables.add(table_name)
                    table_matched_records.add(record_id)
                    key = (table_name, col_name, record_id)
                    if key not in raw_details:
                        raw_details[key] = {"keywords": set(), "contexts": []}
                    for m in llm_result["matches"]:
                        raw_details[key]["keywords"].add(m.get("keyword", ""))
                        if m.get("context"):
                            raw_details[key]["contexts"].append(m["context"])

        for (tname, fname, rid), info in raw_details.items():
            context = info["contexts"][0][:120] if info["contexts"] else ""
            details.append({
                "table": tname,
                "field": fname,
                "record_id": rid,
                "keyword": ", ".join(sorted(info["keywords"])),
                "content": context,
                "source": "LLM"
            })

        table_stats[table_name] = {
            "total_records": table_record_count,
            "matched_records": len(table_matched_records),
            "columns": all_columns,
            "text_columns": text_columns
        }

    if log_callback:
        log_callback(f"  [数据库] {db_name} 检查完成: "
                     f"{total_records} 条记录, "
                     f"候选 {candidate_records} 条, "
                     f"{len(matched_tables)} 个涉密表")

    return {
        "total_tables": total_tables,
        "total_records": total_records,
        "candidate_records": candidate_records,
        "matched_tables": len(matched_tables),
        "table_stats": table_stats,
        "details": details
    }
