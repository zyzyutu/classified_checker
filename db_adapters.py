# -*- coding: utf-8 -*-
"""
数据库适配层 - 支持 MySQL / SQL Server / PostgreSQL / SQLite
每种数据库实现统一接口，checker_db 只调用适配器方法。
"""

import re as _re
from abc import ABC, abstractmethod


class DatabaseAdapter(ABC):
    """数据库通用接口"""

    @abstractmethod
    def connect(self, host, user, password, db_name=None):
        """建立连接"""

    @abstractmethod
    def close(self):
        """关闭连接"""

    @abstractmethod
    def list_databases(self):
        """返回用户数据库名列表（排除系统库）"""

    @abstractmethod
    def get_tables_metadata(self, db_name):
        """
        返回 {table_name: {
            'row_count': int,
            'columns': [col_name, ...],
            'text_columns': [col_name, ...],
            'skipped_columns': ['col(type)', ...],
            'pk_columns': [col_name, ...]
        }}
        """

    @abstractmethod
    def query_candidates(self, table_name, text_columns, keywords):
        """
        用数据库端的模糊过滤查询候选行。
        返回 list[dict]，每个 dict 是一行数据。
        """

    @abstractmethod
    def escape_identifier(self, name):
        """转义表名/字段名（防注入）"""

    @abstractmethod
    def use_database(self, db_name):
        """切换当前数据库"""


# 数值类型，跳过
NUMERIC_TYPES = {
    'int', 'integer', 'bigint', 'smallint', 'mediumint', 'tinyint',
    'float', 'double', 'decimal', 'numeric', 'bit', 'real',
    'serial', 'bigserial', 'smallserial', 'money', 'smallmoney',
}


def _is_text_type(col_type):
    base = col_type.split('(')[0].strip().lower()
    base = base.replace(' unsigned', '').replace(' varying', '').strip()
    return base not in NUMERIC_TYPES


def _build_like_conditions(keywords, col_name, esc_fn):
    """用 LIKE 构建精确子串匹配条件（兼容所有数据库）"""
    conds = []
    for kw in keywords:
        safe = kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conds.append(f"{esc_fn(col_name)} LIKE '%{safe}%'")
    return " OR ".join(conds)


# ==================== MySQL ====================

class MySQLAdapter(DatabaseAdapter):
    SYSTEM_DBS = {'mysql', 'information_schema', 'performance_schema', 'sys'}

    def __init__(self):
        import pymysql
        self._pymysql = pymysql
        self._conn = None

    def connect(self, host, user, password, db_name=None):
        self._conn = self._pymysql.connect(
            host=host, user=user, password=password,
            database=db_name, charset="utf8mb4",
            cursorclass=self._pymysql.cursors.DictCursor
        )

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _cursor(self):
        return self._conn.cursor()

    def list_databases(self):
        with self._cursor() as cur:
            cur.execute("SHOW DATABASES")
            rows = cur.fetchall()
            key = list(rows[0].keys())[0] if rows else "Database"
            return [r[key] for r in rows if r[key].lower() not in self.SYSTEM_DBS]

    def use_database(self, db_name):
        self._conn.select_db(db_name)

    def get_tables_metadata(self, db_name):
        with self._cursor() as cur:
            cur.execute(
                "SELECT TABLE_NAME, TABLE_ROWS FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'", (db_name,))
            rows_data = cur.fetchall()

            cur.execute(
                "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE "
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME, ORDINAL_POSITION", (db_name,))
            cols_data = cur.fetchall()

            cur.execute(
                "SELECT TABLE_NAME, COLUMN_NAME "
                "FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = %s AND CONSTRAINT_NAME = 'PRIMARY' "
                "ORDER BY TABLE_NAME, ORDINAL_POSITION", (db_name,))
            pk_data = cur.fetchall()

        return self._build_metadata(rows_data, cols_data, pk_data)

    def _build_metadata(self, rows_data, cols_data, pk_data):
        tables = {}
        for r in rows_data:
            t = r['TABLE_NAME']
            tables[t] = {'row_count': r['TABLE_ROWS'] or 0, 'columns': [],
                         'text_columns': [], 'skipped_columns': [], 'pk_columns': []}
        for r in pk_data:
            t = r['TABLE_NAME']
            if t in tables:
                tables[t]['pk_columns'].append(r['COLUMN_NAME'])
        for r in cols_data:
            t = r['TABLE_NAME']
            if t not in tables:
                continue
            cn, ct = r['COLUMN_NAME'], r['COLUMN_TYPE']
            tables[t]['columns'].append(cn)
            if _is_text_type(ct):
                tables[t]['text_columns'].append(cn)
            else:
                tables[t]['skipped_columns'].append(f"{cn}({ct})")
        return tables

    def query_candidates(self, table_name, text_columns, keywords):
        conds = []
        for col in text_columns:
            col_conds = _build_like_conditions(keywords, col, self.escape_identifier)
            conds.append(f"({col_conds})")
        where = " OR ".join(conds)
        sql = f"SELECT * FROM {self.escape_identifier(table_name)} WHERE {where}"
        with self._cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()

    def escape_identifier(self, name):
        return f"`{name.replace('`', '``')}`"


# ==================== SQL Server ====================

class SQLServerAdapter(DatabaseAdapter):
    SYSTEM_DBS = {'master', 'tempdb', 'model', 'msdb', 'resource'}

    def __init__(self):
        self._conn = None
        self._driver = None

    def connect(self, host, user, password, db_name=None):
        try:
            import pymssql
            self._conn = pymssql.connect(
                server=host, user=user, password=password,
                database=db_name or 'master', charset='utf8')
            self._driver = 'pymssql'
        except ImportError:
            import pyodbc
            conn_str = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={host};UID={user};PWD={password};"
                f"DATABASE={db_name or 'master'};TrustServerCertificate=yes;"
            )
            self._conn = pyodbc.connect(conn_str)
            self._driver = 'pyodbc'

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _cursor(self):
        return self._conn.cursor()

    def list_databases(self):
        with self._cursor() as cur:
            cur.execute("SELECT name FROM sys.databases")
            return [r[0] for r in cur.fetchall()
                    if r[0].lower() not in self.SYSTEM_DBS]

    def use_database(self, db_name):
        with self._cursor() as cur:
            cur.execute(f"USE [{db_name}]")

    def get_tables_metadata(self, db_name):
        with self._cursor() as cur:
            cur.execute(
                "SELECT t.TABLE_NAME, p.rows AS TABLE_ROWS "
                "FROM INFORMATION_SCHEMA.TABLES t "
                "LEFT JOIN sys.partitions p ON OBJECT_ID(t.TABLE_SCHEMA + '.' + t.TABLE_NAME) = p.object_id AND p.index_id IN (0,1) "
                "WHERE t.TABLE_CATALOG = %s AND t.TABLE_TYPE = 'BASE TABLE'",
                (db_name,))
            rows_data = cur.fetchall()

            cur.execute(
                "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE "
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_CATALOG = %s ORDER BY TABLE_NAME, ORDINAL_POSITION",
                (db_name,))
            cols_data = cur.fetchall()

            cur.execute(
                "SELECT tc.TABLE_NAME, kcu.COLUMN_NAME "
                "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc "
                "JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu "
                "ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME "
                "WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY' AND tc.TABLE_CATALOG = %s "
                "ORDER BY tc.TABLE_NAME, kcu.ORDINAL_POSITION",
                (db_name,))
            pk_data = cur.fetchall()

        return self._build_metadata(rows_data, cols_data, pk_data)

    def _build_metadata(self, rows_data, cols_data, pk_data):
        tables = {}
        for r in rows_data:
            t = r[0]
            tables[t] = {'row_count': r[1] or 0, 'columns': [],
                         'text_columns': [], 'skipped_columns': [], 'pk_columns': []}
        for r in pk_data:
            t = r[0]
            if t in tables:
                tables[t]['pk_columns'].append(r[1])
        for r in cols_data:
            t, cn, ct = r[0], r[1], r[2]
            if t not in tables:
                continue
            tables[t]['columns'].append(cn)
            if _is_text_type(ct):
                tables[t]['text_columns'].append(cn)
            else:
                tables[t]['skipped_columns'].append(f"{cn}({ct})")
        return tables

    def query_candidates(self, table_name, text_columns, keywords):
        conds = []
        for col in text_columns:
            col_conds = _build_like_conditions(keywords, col, self.escape_identifier)
            conds.append(f"({col_conds})")
        where = " OR ".join(conds)
        sql = f"SELECT * FROM {self.escape_identifier(table_name)} WHERE {where}"
        with self._cursor() as cur:
            cur.execute(sql)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def escape_identifier(self, name):
        return f"[{name.replace(']', ']]')}]"


# ==================== PostgreSQL ====================

class PostgreSQLAdapter(DatabaseAdapter):
    SYSTEM_DBS = {'postgres', 'template0', 'template1'}

    def __init__(self):
        self._conn = None

    def connect(self, host, user, password, db_name=None):
        import psycopg2
        import psycopg2.extras
        self._conn = psycopg2.connect(
            host=host, user=user, password=password,
            dbname=db_name or 'postgres')
        self._psycopg2_extras = psycopg2.extras

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _cursor(self):
        return self._conn.cursor(cursor_factory=self._psycopg2_extras.DictCursor)

    def list_databases(self):
        with self._cursor() as cur:
            cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false")
            return [r['datname'] for r in cur.fetchall()
                    if r['datname'].lower() not in self.SYSTEM_DBS]

    def use_database(self, db_name):
        self._conn.close()
        import psycopg2
        import psycopg2.extras
        self._conn = psycopg2.connect(
            host=self._conn.info.host, user=self._conn.info.user,
            password=self._conn.info.password, dbname=db_name)
        self._psycopg2_extras = psycopg2.extras

    def get_tables_metadata(self, db_name):
        with self._cursor() as cur:
            cur.execute(
                "SELECT c.relname AS table_name, c.reltuples::bigint AS row_count "
                "FROM pg_class c JOIN pg_namespace n ON c.relnamespace = n.oid "
                "WHERE c.relkind = 'r' AND n.nspname = 'public'")
            rows_data = cur.fetchall()

            cur.execute(
                "SELECT table_name, column_name, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position")
            cols_data = cur.fetchall()

            cur.execute(
                "SELECT tc.table_name, kcu.column_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "ON tc.constraint_name = kcu.constraint_name "
                "WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public' "
                "ORDER BY tc.table_name, kcu.ordinal_position")
            pk_data = cur.fetchall()

        tables = {}
        for r in rows_data:
            t = r['table_name']
            tables[t] = {'row_count': r['row_count'] or 0, 'columns': [],
                         'text_columns': [], 'skipped_columns': [], 'pk_columns': []}
        for r in pk_data:
            t = r['table_name']
            if t in tables:
                tables[t]['pk_columns'].append(r['column_name'])
        for r in cols_data:
            t = r['table_name']
            if t not in tables:
                continue
            cn, ct = r['column_name'], r['data_type']
            tables[t]['columns'].append(cn)
            if _is_text_type(ct):
                tables[t]['text_columns'].append(cn)
            else:
                tables[t]['skipped_columns'].append(f"{cn}({ct})")
        return tables

    def query_candidates(self, table_name, text_columns, keywords):
        conds = []
        for col in text_columns:
            col_conds = _build_like_conditions(keywords, col, self.escape_identifier)
            conds.append(f"({col_conds})")
        where = " OR ".join(conds)
        sql = f"SELECT * FROM {self.escape_identifier(table_name)} WHERE {where}"
        with self._cursor() as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]

    def escape_identifier(self, name):
        return f'"{name.replace(chr(34), chr(34)*2)}"'


# ==================== SQLite ====================

class SQLiteAdapter(DatabaseAdapter):

    def __init__(self):
        import sqlite3
        self._sqlite3 = sqlite3
        self._conn = None

    def connect(self, host, user, password, db_name=None):
        # host 参数当作文件路径
        db_path = host if host else db_name
        self._conn = self._sqlite3.connect(db_path)
        self._conn.row_factory = self._sqlite3.Row

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _cursor(self):
        return self._conn.cursor()

    def list_databases(self):
        # SQLite 单文件，返回自身
        return ["main"]

    def use_database(self, db_name):
        pass  # SQLite 只有一个库

    def get_tables_metadata(self, db_name):
        with self._cursor() as cur:
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            table_names = [r[0] for r in cur.fetchall()]

        tables = {}
        for tname in table_names:
            with self._cursor() as cur:
                cur.execute(f"PRAGMA table_info([{tname}])")
                cols_info = cur.fetchall()

                cur.execute(f"SELECT COUNT(*) FROM [{tname}]")
                row_count = cur.fetchone()[0]

            pk_cols = []
            columns = []
            text_cols = []
            skipped = []
            for col in cols_info:
                cn = col[1]
                ct = col[2] or 'TEXT'
                columns.append(cn)
                if col[5]:  # pk flag
                    pk_cols.append(cn)
                if _is_text_type(ct):
                    text_cols.append(cn)
                else:
                    skipped.append(f"{cn}({ct})")

            tables[tname] = {
                'row_count': row_count, 'columns': columns,
                'text_columns': text_cols, 'skipped_columns': skipped,
                'pk_columns': pk_cols
            }
        return tables

    def query_candidates(self, table_name, text_columns, keywords):
        conds = []
        for col in text_columns:
            col_conds = _build_like_conditions(keywords, col, self.escape_identifier)
            conds.append(f"({col_conds})")
        where = " OR ".join(conds)
        sql = f"SELECT * FROM [{table_name}] WHERE {where}"
        with self._cursor() as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]

    def escape_identifier(self, name):
        return f"[{name.replace(']', ']]')}]"


# ==================== 工厂函数 ====================

def create_adapter(db_type):
    """
    根据数据库类型创建适配器。
    db_type: "mysql" / "sqlserver" / "postgresql" / "sqlite"
    """
    adapters = {
        "mysql": MySQLAdapter,
        "sqlserver": SQLServerAdapter,
        "postgresql": PostgreSQLAdapter,
        "sqlite": SQLiteAdapter,
    }
    cls = adapters.get(db_type.lower())
    if cls is None:
        raise ValueError(f"不支持的数据库类型: {db_type}，可选: {list(adapters.keys())}")
    return cls()
