# -*- coding: utf-8 -*-
"""
数据库检查模块 - 直连 MySQL，REGEXP 粗筛 + Python re 精确匹配
优化：
  1. INFORMATION_SCHEMA 批量获取表元数据（替代逐表 DESCRIBE）
  2. REGEXP 粗筛（保证字符顺序，比 LIKE 更精准）
  3. 多库并行检查（ThreadPoolExecutor）
"""

import re as _re
import pymysql
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils import build_combined_pattern, check_text_for_keywords

# 数值类型字段，不可能包含文字关键词，直接跳过
NUMERIC_TYPES = {
    'int', 'integer', 'bigint', 'smallint', 'mediumint', 'tinyint',
    'float', 'double', 'decimal', 'numeric', 'bit', 'real',
    'serial', 'bigserial', 'smallserial'
}

# 系统数据库，不需要检查
_SYSTEM_DATABASES = {'mysql', 'information_schema', 'performance_schema', 'sys'}


def _is_text_type(col_type):
    """判断字段类型是否为文本类型（需要检查的）"""
    base_type = col_type.split('(')[0].strip().lower()
    base_type = base_type.replace(' unsigned', '').strip()
    return base_type not in NUMERIC_TYPES


def _escape_regexp(s):
    """转义 MySQL REGEXP 特殊字符"""
    return _re.escape(s)


def _build_regexp_conditions(keywords, col_name):
    """
    为单个字段构建 REGEXP 粗筛条件。
    比 LIKE 更精准：保证首字在末字之前出现（顺序匹配）。
    """
    conditions = []
    for kw in keywords:
        if len(kw) < 2:
            safe = _escape_regexp(kw)
            conditions.append(f"`{col_name}` REGEXP '{safe}'")
        else:
            first = _escape_regexp(kw[0])
            last = _escape_regexp(kw[-1])
            conditions.append(f"`{col_name}` REGEXP '{first}.*{last}'")
    return " OR ".join(conditions)


def _get_tables_metadata(cursor, db_name):
    """
    通过 INFORMATION_SCHEMA 批量获取所有表的字段信息和行数。
    替代逐表 SHOW TABLES + DESCRIBE，只需 2 条 SQL。
    """
    # 获取所有用户表的行数
    cursor.execute(
        "SELECT TABLE_NAME, TABLE_ROWS "
        "FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'",
        (db_name,)
    )
    rows_data = cursor.fetchall()

    # 获取所有表的列信息
    cursor.execute(
        "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s "
        "ORDER BY TABLE_NAME, ORDINAL_POSITION",
        (db_name,)
    )
    columns_data = cursor.fetchall()

    # 获取所有表的主键列
    cursor.execute(
        "SELECT TABLE_NAME, COLUMN_NAME "
        "FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA = %s AND CONSTRAINT_NAME = 'PRIMARY' "
        "ORDER BY TABLE_NAME, ORDINAL_POSITION",
        (db_name,)
    )
    pk_data = cursor.fetchall()

    # 构建表结构字典
    tables = {}
    for row in rows_data:
        tname = row['TABLE_NAME']
        tables[tname] = {
            'row_count': row['TABLE_ROWS'] or 0,
            'columns': [],
            'text_columns': [],
            'skipped_columns': [],
            'pk_columns': []
        }

    for row in pk_data:
        tname = row['TABLE_NAME']
        if tname in tables:
            tables[tname]['pk_columns'].append(row['COLUMN_NAME'])

    for row in columns_data:
        tname = row['TABLE_NAME']
        if tname not in tables:
            continue
        col_name = row['COLUMN_NAME']
        col_type = row['COLUMN_TYPE']
        tables[tname]['columns'].append(col_name)
        if _is_text_type(col_type):
            tables[tname]['text_columns'].append(col_name)
        else:
            tables[tname]['skipped_columns'].append(f"{col_name}({col_type})")

    return tables


def check_database(db_name, keywords, log_callback=None,
                   host="localhost", user="root", password=""):
    """
    检查单个数据库的涉密信息。
    REGEXP 粗筛 + Python re 精确匹配，跳过数值类型字段。

    参数:
        db_name:      数据库名
        keywords:     关键词列表
        log_callback: 日志回调函数（可选）
        host/user/password: 数据库连接信息

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
        conn = pymysql.connect(
            host=host, user=user, password=password,
            database=db_name, charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )
    except pymysql.Error as e:
        if log_callback:
            log_callback(f"  [数据库] 连接失败({db_name}): {e}")
        return {"total_tables": 0, "total_records": 0,
                "candidate_records": 0, "matched_tables": 0,
                "table_stats": {}, "details": []}

    try:
        with conn.cursor() as cursor:
            # 批量获取所有表的元数据（2条SQL替代N条DESCRIBE）
            tables_meta = _get_tables_metadata(cursor, db_name)
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

                # REGEXP 粗筛（保证字符顺序，比 LIKE 更精准）
                regexp_parts = []
                for col_name in text_columns:
                    regexp_parts.append(
                        f"({_build_regexp_conditions(keywords, col_name)})"
                    )
                where_clause = " OR ".join(regexp_parts)

                sql = f"SELECT * FROM `{table_name}` WHERE {where_clause}"
                if log_callback:
                    log_callback(f"  [数据库] {db_name}.{table_name}: REGEXP 粗筛 "
                                 f"({table_record_count}条 → 候选...)")

                try:
                    cursor.execute(sql)
                    candidates = cursor.fetchall()
                except pymysql.Error as e:
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
                    log_callback(f"  [数据库] {db_name}.{table_name}: 粗筛完成，"
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
                             f"REGEXP候选 {candidate_records} 条, "
                             f"{len(matched_tables)} 个涉密表")

            return {
                "total_tables": total_tables,
                "total_records": total_records,
                "candidate_records": candidate_records,
                "matched_tables": len(matched_tables),
                "table_stats": table_stats,
                "details": details
            }

    except pymysql.Error as e:
        if log_callback:
            log_callback(f"  [数据库] {db_name} 查询异常: {e}")
        return {"total_tables": 0, "total_records": 0,
                "candidate_records": 0, "matched_tables": 0,
                "table_stats": {}, "details": []}
    finally:
        conn.close()


def check_all_databases(keywords, log_callback=None, max_workers=4,
                        host="localhost", user="root", password=""):
    """
    并行检查 MySQL 服务器上所有用户数据库。

    参数:
        keywords:     关键词列表
        log_callback: 日志回调函数（可选）
        max_workers:  并行检查的数据库数（默认4）
        host/user/password: 数据库连接信息

    返回:
        dict: 与 check_database 相同结构，table_stats 的 key 带数据库名前缀
    """
    try:
        conn = pymysql.connect(
            host=host, user=user, password=password,
            charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
    except pymysql.Error as e:
        if log_callback:
            log_callback(f"  [数据库] 连接失败: {e}")
        return {"total_tables": 0, "total_records": 0,
                "candidate_records": 0, "matched_tables": 0,
                "table_stats": {}, "details": []}

    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW DATABASES")
            rows = cursor.fetchall()
            db_key = list(rows[0].keys())[0] if rows else "Database"
            all_dbs = [row[db_key] for row in rows]
    finally:
        conn.close()

    user_dbs = [db for db in all_dbs if db.lower() not in _SYSTEM_DATABASES]
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

    # 并行检查多个数据库
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                check_database, db, keywords,
                log_callback, host, user, password
            ): db for db in user_dbs
        }

        for future in as_completed(futures):
            db_name = futures[future]
            try:
                result = future.result()
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
