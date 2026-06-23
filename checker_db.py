# -*- coding: utf-8 -*-
"""
数据库检查模块 - 通过适配器支持多种数据库（MySQL/SQL Server/PostgreSQL/SQLite）
优化：
  1. 适配器封装 SQL 方言差异
  2. LIKE 精确子串匹配 + Python re 模糊精确匹配
  3. 多库并行检查（ThreadPoolExecutor）
"""

from utils import build_combined_pattern, check_text_for_keywords


def check_database(adapter, db_name, keywords, log_callback=None):
    """
    检查单个数据库的涉密信息。

    参数:
        adapter:      DatabaseAdapter 实例（已连接）
        db_name:      数据库名
        keywords:     关键词列表
        log_callback: 日志回调函数（可选）

    返回:
        dict: {
            "total_tables", "total_records", "candidate_records",
            "matched_tables", "table_stats", "details"
        }
    """
    pattern = build_combined_pattern(keywords)
    if not pattern:
        return {"total_tables": 0, "total_records": 0,
                "candidate_records": 0, "matched_tables": 0,
                "table_stats": {}, "details": []}

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
        skipped_columns = meta['skipped_columns']
        table_record_count = meta['row_count']

        if not text_columns:
            if log_callback:
                log_callback(f"  [数据库] {db_name}.{table_name}: 无文本字段，跳过")
            table_stats[table_name] = {
                "total_records": 0, "matched_records": 0,
                "columns": all_columns, "text_columns": []
            }
            continue

        if log_callback and skipped_columns:
            log_callback(f"  [数据库] {db_name}.{table_name}: 跳过数值字段 "
                         f"{', '.join(skipped_columns)}")

        total_records += table_record_count

        if table_record_count == 0:
            table_stats[table_name] = {
                "total_records": 0, "matched_records": 0,
                "columns": all_columns, "text_columns": text_columns
            }
            continue

        # 数据库端模糊过滤（LIKE 子串匹配）
        if log_callback:
            log_callback(f"  [数据库] {db_name}.{table_name}: 模糊过滤 "
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
            log_callback(f"  [数据库] {db_name}.{table_name}: 过滤完成，"
                         f"{candidate_count} 条候选")

        # Python re 精确匹配（按 表+字段+记录ID 去重合并关键词）
        table_matched_records = set()
        raw_details = {}  # (table, field, record_id) -> {keywords}
        pk_columns = meta.get('pk_columns', [])
        for row_idx, row in enumerate(candidates):
            if pk_columns:
                record_id = row.get(pk_columns[0]) if len(pk_columns) == 1 else \
                            "-".join(str(row.get(c, "")) for c in pk_columns)
            else:
                record_id = row_idx + 1
            for col_name in text_columns:
                value = row.get(col_name)
                if value is None:
                    continue
                for _, _, keyword in check_text_for_keywords(str(value), pattern):
                    matched_tables.add(table_name)
                    table_matched_records.add(record_id)
                    key = (table_name, col_name, record_id)
                    if key not in raw_details:
                        raw_details[key] = set()
                    raw_details[key].add(keyword)

        for (tname, fname, rid), kws in raw_details.items():
            details.append({
                "table": tname,
                "field": fname,
                "record_id": rid,
                "keyword": ", ".join(sorted(kws))
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


def check_all_databases(adapter, keywords, log_callback=None):
    """
    并行检查所有用户数据库。

    参数:
        adapter:      DatabaseAdapter 实例（已连接）
        keywords:     关键词列表
        log_callback: 日志回调函数（可选）
        max_workers:  并行检查的数据库数（默认4）

    返回:
        dict: 与 check_database 相同结构，table_stats 的 key 带数据库名前缀
    """
    try:
        user_dbs = adapter.list_databases()
    except Exception as e:
        if log_callback:
            log_callback(f"  [数据库] 获取数据库列表失败: {e}")
        return {"total_tables": 0, "total_records": 0,
                "candidate_records": 0, "matched_tables": 0,
                "table_stats": {}, "details": []}

    if log_callback:
        log_callback(f"  [数据库] 发现 {len(user_dbs)} 个用户数据库: {', '.join(user_dbs)}")

    if not user_dbs:
        return {"total_tables": 0, "total_records": 0,
                "candidate_records": 0, "matched_tables": 0,
                "table_stats": {}, "details": []}

    # 合并结果容器
    total_tables = 0
    total_records = 0
    candidate_records = 0
    matched_tables = 0
    merged_table_stats = {}
    merged_details = []

    # 顺序检查多个数据库（共享同一连接，不能并行）
    for db_idx, db_name in enumerate(user_dbs):
        if log_callback:
            log_callback(f"  [数据库] 检查 {db_name} ({db_idx+1}/{len(user_dbs)})...")
        try:
            result = check_database(adapter, db_name, keywords, log_callback)
        except Exception as e:
            if log_callback:
                log_callback(f"  [数据库] {db_name} 异常: {e}")
            continue

        total_tables += result["total_tables"]
        total_records += result["total_records"]
        candidate_records += result["candidate_records"]
        matched_tables += result["matched_tables"]

        for tname, tstats in result["table_stats"].items():
            merged_table_stats[f"{db_name}.{tname}"] = tstats

        for d in result["details"]:
            d["table"] = f"{db_name}.{d['table']}"
            merged_details.append(d)

    return {
        "total_databases": len(user_dbs),
        "total_tables": total_tables,
        "total_records": total_records,
        "candidate_records": candidate_records,
        "matched_tables": matched_tables,
        "table_stats": merged_table_stats,
        "details": merged_details
    }
