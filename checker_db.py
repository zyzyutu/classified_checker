# -*- coding: utf-8 -*-
"""
数据库检查模块 - 直连 MySQL 数据库，遍历所有表和字段，检查涉密信息
"""

import pymysql

from utils import build_combined_pattern


def check_database(db_name, keywords, log_callback=None,
                   host="localhost", user="root", password=""):
    """
    直连 MySQL 数据库，检查所有表中的涉密信息。

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
            "total_records": 记录总数,
            "matched_tables": 涉密表数,
            "details": [{table, field, record_id, keyword}, ...]
        }
    """
    pattern = build_combined_pattern(keywords)
    if not pattern:
        return {"total_tables": 0, "total_records": 0,
                "matched_tables": 0, "details": []}

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
                "matched_tables": 0, "details": []}

    try:
        with conn.cursor() as cursor:
            # 获取所有表名
            cursor.execute("SHOW TABLES")
            rows = cursor.fetchall()
            table_keys = list(rows[0].keys()) if rows else []
            if not table_keys:
                return {"total_tables": 0, "total_records": 0,
                        "matched_tables": 0, "details": []}

            table_key = table_keys[0]
            tables = [row[table_key] for row in rows]
            total_tables = len(tables)

            if log_callback:
                log_callback(f"  [数据库] 发现 {total_tables} 个表")

            total_records = 0
            matched_tables = set()
            details = []
            table_stats = {}  # {table_name: {total_records, matched_records, columns}}

            for table_name in tables:
                # 获取表字段名
                cursor.execute(f"DESCRIBE `{table_name}`")
                col_rows = cursor.fetchall()
                columns = [col["Field"] for col in col_rows]

                # 查询所有数据
                cursor.execute(f"SELECT * FROM `{table_name}`")
                data_rows = cursor.fetchall()

                table_matched_records = set()
                table_record_count = len(data_rows)

                for row_idx, row in enumerate(data_rows):
                    total_records += 1
                    for col_name in columns:
                        value = row.get(col_name)
                        if value is None:
                            continue
                        value_str = str(value)

                        matches = pattern.finditer(value_str)
                        for m in matches:
                            matched_tables.add(table_name)
                            table_matched_records.add(row_idx + 1)
                            details.append({
                                "table": table_name,
                                "field": col_name,
                                "record_id": row_idx + 1,
                                "keyword": m.group()
                            })

                table_stats[table_name] = {
                    "total_records": table_record_count,
                    "matched_records": len(table_matched_records),
                    "columns": columns
                }

            if log_callback:
                log_callback(f"  [数据库] 检查完成，共 {total_records} 条记录")

            return {
                "total_tables": total_tables,
                "total_records": total_records,
                "matched_tables": len(matched_tables),
                "table_stats": table_stats,
                "details": details
            }

    except pymysql.Error as e:
        if log_callback:
            log_callback(f"  [数据库] 查询异常: {e}")
        return {"total_tables": 0, "total_records": 0,
                "matched_tables": 0, "details": []}
    finally:
        conn.close()
