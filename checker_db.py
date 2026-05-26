# -*- coding: utf-8 -*-
"""
数据库检查模块 - 直连 MySQL，LIKE 粗筛 + Python re 精确匹配，跳过数值字段
"""

import pymysql

from utils import build_combined_pattern

# 数值类型字段，不可能包含文字关键词，直接跳过
NUMERIC_TYPES = {
    'int', 'integer', 'bigint', 'smallint', 'mediumint', 'tinyint',
    'float', 'double', 'decimal', 'numeric', 'bit', 'real',
    'serial', 'bigserial', 'smallserial'
}


def _is_text_type(col_type):
    """判断字段类型是否为文本类型（需要检查的）"""
    # 去掉括号和长度部分，如 varchar(255) → varchar
    base_type = col_type.split('(')[0].strip().lower()
    # 去掉 unsigned 等修饰符
    base_type = base_type.replace(' unsigned', '').strip()
    return base_type not in NUMERIC_TYPES


def _escape_like(kw):
    """转义 LIKE 语句中的特殊字符（%, _, \），防止 SQL 注入和误匹配"""
    return kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_like_conditions(keywords, col_name):
    """
    为单个字段构建 LIKE 粗筛条件。
    每个关键词：field LIKE '%首字%' AND field LIKE '%末字%'
    多个关键词之间用 OR 连接。
    """
    conditions = []
    for kw in keywords:
        if len(kw) < 2:
            safe = _escape_like(kw)
            conditions.append(f"`{col_name}` LIKE '%{safe}%'")
        else:
            first = _escape_like(kw[0])
            last = _escape_like(kw[-1])
            conditions.append(
                f"`{col_name}` LIKE '%{first}%' AND `{col_name}` LIKE '%{last}%'"
            )
    return " OR ".join(conditions)


def check_database(db_name, keywords, log_callback=None,
                   host="localhost", user="root", password=""):
    """
    直连 MySQL 数据库，LIKE 粗筛 + Python re 精确匹配检查涉密信息。
    跳过数值类型字段（INT/FLOAT等）。

    参数:
        db_name:    数据库名
        keywords:   关键词列表
        log_callback: 日志回调函数（可选）
        host:       数据库主机（默认 localhost）
        user:       用户名（默认 root）
        password:   密码

    返回:
        dict: {
            "total_tables": 表总数,
            "total_records": 记录总数（粗筛前）,
            "candidate_records": 粗筛后候选数,
            "matched_tables": 涉密表数,
            "table_stats": {表名: {total_records, matched_records, columns, text_columns}},
            "details": [{table, field, record_id, keyword}, ...]
        }
    """
    pattern = build_combined_pattern(keywords)
    if not pattern:
        return {"total_tables": 0, "total_records": 0,
                "candidate_records": 0, "matched_tables": 0,
                "table_stats": {}, "details": []}

    # 连接数据库
    try:
        conn = pymysql.connect(
            host=host,
            user=user,
            password=password,
            database=db_name,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )
    except pymysql.Error as e:
        if log_callback:
            log_callback(f"  [数据库] 连接失败: {e}")
        return {"total_tables": 0, "total_records": 0,
                "candidate_records": 0, "matched_tables": 0,
                "table_stats": {}, "details": []}

    try:
        with conn.cursor() as cursor:
            # 获取所有表名
            cursor.execute("SHOW TABLES")
            rows = cursor.fetchall()
            table_keys = list(rows[0].keys()) if rows else []
            if not table_keys:
                return {"total_tables": 0, "total_records": 0,
                        "candidate_records": 0, "matched_tables": 0,
                        "table_stats": {}, "details": []}

            table_key = table_keys[0]
            tables = [row[table_key] for row in rows]
            total_tables = len(tables)

            if log_callback:
                log_callback(f"  [数据库] 发现 {total_tables} 个表")

            total_records = 0
            candidate_records = 0
            matched_tables = set()
            details = []
            table_stats = {}

            for table_name in tables:
                # 获取表字段名和类型
                cursor.execute(f"DESCRIBE `{table_name}`")
                col_rows = cursor.fetchall()

                # 分离文本字段和数值字段
                all_columns = [col["Field"] for col in col_rows]
                text_columns = []
                skipped_columns = []
                for col in col_rows:
                    col_name = col["Field"]
                    col_type = col.get("Type", "")
                    if _is_text_type(col_type):
                        text_columns.append(col_name)
                    else:
                        skipped_columns.append(f"{col_name}({col_type})")

                if not text_columns:
                    if log_callback:
                        log_callback(f"  [数据库] 表 {table_name}: 无文本字段，跳过")
                    table_stats[table_name] = {
                        "total_records": 0,
                        "matched_records": 0,
                        "columns": all_columns,
                        "text_columns": []
                    }
                    continue

                if log_callback and skipped_columns:
                    log_callback(f"  [数据库] 表 {table_name}: 跳过数值字段 "
                                 f"{', '.join(skipped_columns)}")

                # 获取总记录数
                cursor.execute(f"SELECT COUNT(*) AS cnt FROM `{table_name}`")
                table_record_count = cursor.fetchone()["cnt"]
                total_records += table_record_count

                if table_record_count == 0:
                    table_stats[table_name] = {
                        "total_records": 0,
                        "matched_records": 0,
                        "columns": all_columns,
                        "text_columns": text_columns
                    }
                    continue

                # 构建 LIKE 粗筛条件（对所有文本字段用 OR 连接）
                like_parts = []
                for col_name in text_columns:
                    like_parts.append(
                        f"({(_build_like_conditions(keywords, col_name))})"
                    )
                where_clause = " OR ".join(like_parts)

                # LIKE 粗筛查询
                sql = f"SELECT * FROM `{table_name}` WHERE {where_clause}"
                if log_callback:
                    log_callback(f"  [数据库] 表 {table_name}: LIKE 粗筛 "
                                 f"({table_record_count}条 → 候选...)")

                try:
                    cursor.execute(sql)
                    candidates = cursor.fetchall()
                except pymysql.Error as e:
                    if log_callback:
                        log_callback(f"  [数据库] 表 {table_name} 查询失败: {e}")
                    table_stats[table_name] = {
                        "total_records": table_record_count,
                        "matched_records": 0,
                        "columns": all_columns,
                        "text_columns": text_columns
                    }
                    continue

                candidate_count = len(candidates)
                candidate_records += candidate_count

                if log_callback:
                    log_callback(f"  [数据库] 表 {table_name}: 粗筛完成，"
                                 f"{candidate_count} 条候选")

                # Python re 精确匹配
                table_matched_records = set()
                for row_idx, row in enumerate(candidates):
                    for col_name in text_columns:
                        value = row.get(col_name)
                        if value is None:
                            continue
                        value_str = str(value)

                        for m in pattern.finditer(value_str):
                            matched_tables.add(table_name)
                            # 用原始记录ID（从候选集的自增ID或行号获取）
                            record_id = row.get("id", row_idx + 1)
                            table_matched_records.add(record_id)
                            details.append({
                                "table": table_name,
                                "field": col_name,
                                "record_id": record_id,
                                "keyword": m.group()
                            })

                table_stats[table_name] = {
                    "total_records": table_record_count,
                    "matched_records": len(table_matched_records),
                    "columns": all_columns,
                    "text_columns": text_columns
                }

            if log_callback:
                log_callback(f"  [数据库] 检查完成: 共 {total_records} 条记录, "
                             f"粗筛 {candidate_records} 条候选, "
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
            log_callback(f"  [数据库] 查询异常: {e}")
        return {"total_tables": 0, "total_records": 0,
                "candidate_records": 0, "matched_tables": 0,
                "table_stats": {}, "details": []}
    finally:
        conn.close()
