# -*- coding: utf-8 -*-
"""
数据库检查模块 - 读取SQL文件，遍历所有表和字段，检查涉密信息
"""

import re
import os

from utils import build_combined_pattern


def check_database(sql_file, keywords, log_callback=None):
    """
    读取SQL文件并检查所有表中的涉密信息。

    参数:
        sql_file:   SQL文件路径
        keywords:   关键词列表
        log_callback: 日志回调函数（可选）

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

    if not os.path.isfile(sql_file):
        if log_callback:
            log_callback(f"  [数据库] 文件不存在: {sql_file}")
        return {"total_tables": 0, "total_records": 0,
                "matched_tables": 0, "details": []}

    # 读取SQL文件内容
    try:
        with open(sql_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        if log_callback:
            log_callback(f"  [数据库] 读取失败: {e}")
        return {"total_tables": 0, "total_records": 0,
                "matched_tables": 0, "details": []}

    # 解析所有建表语句，获取表名和字段
    tables = _parse_create_tables(content)
    total_tables = len(tables)

    if log_callback:
        log_callback(f"  [数据库] 发现 {total_tables} 个表")

    total_records = 0
    matched_tables = set()
    details = []

    # 解析所有INSERT语句并检查
    inserts = _parse_inserts(content)

    for table_name, columns, rows in inserts:
        for row_idx, row in enumerate(rows):
            total_records += 1
            for col_idx, value in enumerate(row):
                if col_idx < len(columns):
                    col_name = columns[col_idx]
                else:
                    col_name = f"col_{col_idx}"

                # 搜索匹配
                matches = pattern.finditer(str(value))
                for m in matches:
                    matched_tables.add(table_name)
                    details.append({
                        "table": table_name,
                        "field": col_name,
                        "record_id": row_idx + 1,
                        "keyword": m.group()
                    })

    if log_callback:
        log_callback(f"  [数据库] 检查完成，共 {total_records} 条记录")

    return {
        "total_tables": total_tables,
        "total_records": total_records,
        "matched_tables": len(matched_tables),
        "details": details
    }


def _parse_create_tables(content):
    """
    从SQL内容中解析所有CREATE TABLE语句。
    返回: {table_name: [column_names]}
    """
    tables = {}
    # 匹配 CREATE TABLE 语句
    pattern = re.compile(
        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\']?(\w+)[`"\']?\s*\((.*?)\)\s*;',
        re.IGNORECASE | re.DOTALL
    )
    for m in pattern.finditer(content):
        table_name = m.group(1)
        columns_block = m.group(2)
        columns = _parse_columns(columns_block)
        tables[table_name] = columns
    return tables


def _parse_columns(columns_block):
    """从CREATE TABLE的列定义块中提取列名"""
    columns = []
    # 按逗号分割，但要注意括号内的逗号（如 DECIMAL(10,2)）
    depth = 0
    current = ""
    for ch in columns_block:
        if ch == '(':
            depth += 1
            current += ch
        elif ch == ')':
            depth -= 1
            current += ch
        elif ch == ',' and depth == 0:
            columns.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        columns.append(current.strip())

    # 提取列名（每段第一个 token，跳过 PRIMARY/KEY/INDEX 等）
    result = []
    skip_keywords = {'PRIMARY', 'KEY', 'INDEX', 'UNIQUE', 'CONSTRAINT',
                     'CHECK', 'FOREIGN', 'REFERENCES', 'DEFAULT',
                     'AUTO_INCREMENT', 'COMMENT'}
    for col_def in columns:
        tokens = col_def.split()
        if tokens:
            col_name = tokens[0].strip('`"\'[]')
            if col_name.upper() not in skip_keywords:
                result.append(col_name)
    return result


def _parse_inserts(content):
    """
    解析SQL内容中的所有INSERT语句。
    返回: [(table_name, [columns], [rows])]
    """
    results = []
    # 匹配 INSERT INTO ... VALUES ... 格式
    insert_pattern = re.compile(
        r'INSERT\s+INTO\s+[`"\']?(\w+)[`"\']?\s*'
        r'(?:\(([^)]+)\)\s*)?'
        r'VALUES\s*(.*?);',
        re.IGNORECASE | re.DOTALL
    )

    for m in insert_pattern.finditer(content):
        table_name = m.group(1)
        columns_str = m.group(2)
        values_str = m.group(3)

        # 解析列名
        if columns_str:
            columns = [c.strip().strip('`"\'[]') for c in columns_str.split(',')]
        else:
            columns = []

        # 解析值行
        rows = _parse_value_rows(values_str)
        if rows:
            results.append((table_name, columns, rows))

    return results


def _parse_value_rows(values_str):
    """
    解析INSERT语句中的值行。
    支持多行INSERT和单行INSERT。
    处理字符串中的引号转义。
    """
    rows = []
    # 将值按行分隔（支持多行 VALUES）
    # 简单处理：找到每个 (...) 块
    i = 0
    while i < len(values_str):
        # 找到 '(' 开始
        start = values_str.find('(', i)
        if start == -1:
            break
        # 找到对应的 ')'，考虑嵌套引号
        depth = 1
        j = start + 1
        while j < len(values_str) and depth > 0:
            ch = values_str[j]
            if ch == '(' :
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == "'":
                # 跳过引号内的内容
                j += 1
                while j < len(values_str):
                    if values_str[j] == "'" and values_str[j-1:j+2] != "''":
                        break
                    j += 1
            j += 1

        if depth == 0:
            row_content = values_str[start+1:j-1]
            values = _split_values(row_content)
            rows.append(values)

        i = j

    return rows


def _split_values(row_content):
    """
    分割一行中的各个值，正确处理引号内的逗号。
    """
    values = []
    current = ""
    in_string = False
    quote_char = None
    i = 0
    while i < len(row_content):
        ch = row_content[i]
        if in_string:
            if ch == quote_char:
                # 检查是否是转义引号 ''
                if i + 1 < len(row_content) and row_content[i+1] == quote_char:
                    current += ch + ch
                    i += 2
                    continue
                else:
                    in_string = False
            current += ch
        else:
            if ch in ("'", '"'):
                in_string = True
                quote_char = ch
                current += ch
            elif ch == ',':
                values.append(current.strip().strip("'\""))
                current = ""
            else:
                current += ch
        i += 1

    if current.strip():
        values.append(current.strip().strip("'\""))
    return values
