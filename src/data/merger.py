"""
数据库合并/更新工具
用于合并多个数据库文件或增量更新
"""

import sqlite3
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.settings import DB


def merge_databases(source_path: Path, target_path: Path, tables: list = None):
    """将 source 数据库中的表合并到 target 数据库"""
    if not source_path.exists():
        raise FileNotFoundError(f"Source DB not found: {source_path}")
    if not target_path.exists():
        raise FileNotFoundError(f"Target DB not found: {target_path}")

    src_conn = sqlite3.connect(str(source_path))
    tgt_conn = sqlite3.connect(str(target_path))

    if tables is None:
        cursor = src_conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

    total_merged = 0
    for table in tables:
        try:
            df = pd.read_sql(f"SELECT * FROM {table}", src_conn)
            if df.empty:
                continue
            rows_before = pd.read_sql(f"SELECT COUNT(*) as c FROM {table}", tgt_conn).iloc[0, 0]
            df.to_sql(table, tgt_conn, if_exists='append', index=False)
            rows_after = pd.read_sql(f"SELECT COUNT(*) as c FROM {table}", tgt_conn).iloc[0, 0]
            merged = rows_after - rows_before
            total_merged += merged
            print(f"  {table}: +{merged} rows")
        except Exception as e:
            print(f"  {table}: ERROR - {e}")

    src_conn.close()
    tgt_conn.close()
    print(f"Total merged: {total_merged} rows")
    return total_merged
