#!/usr/bin/env python
"""
数据库维护工具 — 清理空表、过期数据、压缩数据库
用法: python scripts/db_cleanup.py [--drop-empty] [--vacuum] [--clean-minute 30]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import DB

EMPTY_SAFE_TABLES = {
    "market": [
        "account", "backtests", "kline_cache", "positions",
        "stock_scores", "strategies", "trades", "trades_old_backup",
        "update_log", "user_sessions",
    ],
    "quantpro": [
        "trade_log",
    ],
}


def list_tables(conn):
    c = conn.cursor()
    return [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]


def table_row_count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]


def drop_empty_tables(db_name, db_path, dry_run=True):
    safe_tables = EMPTY_SAFE_TABLES.get(db_name, [])
    if not safe_tables:
        return 0

    conn = sqlite3.connect(str(db_path))
    existing = set(list_tables(conn))
    dropped = 0

    for tbl in safe_tables:
        if tbl not in existing:
            continue
        cnt = table_row_count(conn, tbl)
        if cnt == 0:
            if dry_run:
                print(f"  [DRY-RUN] DROP TABLE {tbl} (0 rows)")
            else:
                conn.execute(f"DROP TABLE [{tbl}]")
                print(f"  Dropped {tbl} (was 0 rows)")
            dropped += 1

    if not dry_run:
        conn.commit()
    conn.close()
    return dropped


def clean_minute_kline(db_path, keep_days=30, dry_run=True):
    conn = sqlite3.connect(str(db_path))
    cnt_before = table_row_count(conn, "minute_kline")

    row = conn.execute(
        "SELECT MAX(date) FROM minute_kline"
    ).fetchone()
    latest_date = row[0] if row else None

    if not latest_date:
        conn.close()
        return 0

    cutoff = f"date('{latest_date}', '-{keep_days} days')"
    cnt_old = conn.execute(
        f"SELECT COUNT(*) FROM minute_kline WHERE date < {cutoff}"
    ).fetchone()[0]

    if cnt_old == 0:
        print(f"  minute_kline: {cnt_before} rows, no data older than {keep_days} days")
        conn.close()
        return 0

    if dry_run:
        print(f"  [DRY-RUN] DELETE FROM minute_kline WHERE date < {cutoff} => {cnt_old} rows")
    else:
        conn.execute(f"DELETE FROM minute_kline WHERE date < {cutoff}")
        conn.commit()
        cnt_after = table_row_count(conn, "minute_kline")
        print(f"  minute_kline: {cnt_before} -> {cnt_after} rows (deleted {cnt_old})")

    conn.close()
    return cnt_old


def clean_operation_logs(db_path, keep_days=90, dry_run=True):
    conn = sqlite3.connect(str(db_path))
    cnt_before = table_row_count(conn, "operation_logs")
    if cnt_before == 0:
        conn.close()
        return 0

    cutoff = f"datetime('now', '-{keep_days} days')"
    cnt_old = conn.execute(
        f"SELECT COUNT(*) FROM operation_logs WHERE timestamp < {cutoff}"
    ).fetchone()[0]

    if cnt_old == 0:
        print(f"  operation_logs: {cnt_before} rows, all within {keep_days} days")
        conn.close()
        return 0

    if dry_run:
        print(f"  [DRY-RUN] DELETE FROM operation_logs WHERE timestamp < {cutoff} => {cnt_old} rows")
    else:
        conn.execute(f"DELETE FROM operation_logs WHERE timestamp < {cutoff}")
        conn.commit()
        cnt_after = table_row_count(conn, "operation_logs")
        print(f"  operation_logs: {cnt_before} -> {cnt_after} rows (deleted {cnt_old})")

    conn.close()
    return cnt_old


def vacuum_db(db_path, dry_run=True):
    size_before = db_path.stat().st_size / 1024 / 1024
    if dry_run:
        print(f"  [DRY-RUN] VACUUM {db_path} ({size_before:.1f} MB)")
        return

    conn = sqlite3.connect(str(db_path))
    conn.execute("VACUUM")
    conn.close()
    size_after = db_path.stat().st_size / 1024 / 1024
    print(f"  VACUUM {db_path}: {size_before:.1f} -> {size_after:.1f} MB (saved {size_before - size_after:.1f} MB)")


def remove_legacy_db(dry_run=True):
    legacy = Path("data/market.db")
    if not legacy.exists():
        return
    size = legacy.stat().st_size
    if size == 0:
        if dry_run:
            print(f"  [DRY-RUN] DELETE {legacy} (0 bytes, unused)")
        else:
            legacy.unlink()
            print(f"  Deleted {legacy} (was 0 bytes)")
    else:
        print(f"  [SKIP] {legacy} exists ({size} bytes) — manual review needed")


def main():
    parser = argparse.ArgumentParser(description="Database cleanup tool")
    parser.add_argument("--drop-empty", action="store_true", help="Drop known empty tables")
    parser.add_argument("--vacuum", action="store_true", help="VACUUM databases to reclaim space")
    parser.add_argument("--clean-minute", type=int, metavar="DAYS",
                        help="Delete minute_kline data older than DAYS")
    parser.add_argument("--clean-logs", type=int, metavar="DAYS",
                        help="Delete operation_logs older than DAYS")
    parser.add_argument("--remove-legacy", action="store_true", help="Remove empty legacy market.db")
    parser.add_argument("--execute", action="store_true", help="Actually execute (default is dry-run)")
    args = parser.parse_args()

    dry_run = not args.execute

    if dry_run:
        print("=" * 60)
        print("DRY-RUN MODE (use --execute to apply changes)")
        print("=" * 60)

    print("\n--- Database Status ---")
    for name, path in DB.items():
        if not path.exists():
            print(f"  {name}: {path} (NOT FOUND)")
            continue
        size_mb = path.stat().st_size / 1024 / 1024
        conn = sqlite3.connect(str(path))
        tables = list_tables(conn)
        print(f"  {name}: {path} ({size_mb:.1f} MB, {len(tables)} tables)")
        for tbl in tables:
            cnt = table_row_count(conn, tbl)
            if cnt > 0:
                print(f"    {tbl}: {cnt:,} rows")
            else:
                print(f"    {tbl}: 0 rows (empty)")
        conn.close()

    if args.drop_empty:
        print("\n--- Dropping Empty Tables ---")
        for name, path in DB.items():
            print(f"\n  [{name}]")
            drop_empty_tables(name, path, dry_run=dry_run)

    if args.clean_minute:
        print(f"\n--- Cleaning minute_kline (keep {args.clean_minute} days) ---")
        clean_minute_kline(DB["market"], keep_days=args.clean_minute, dry_run=dry_run)

    if args.clean_logs:
        print(f"\n--- Cleaning operation_logs (keep {args.clean_logs} days) ---")
        clean_operation_logs(DB["quantpro"], keep_days=args.clean_logs, dry_run=dry_run)

    if args.remove_legacy:
        print("\n--- Removing Legacy Files ---")
        remove_legacy_db(dry_run=dry_run)

    if args.vacuum:
        print("\n--- VACUUM ---")
        for name, path in DB.items():
            if path.exists():
                vacuum_db(path, dry_run=dry_run)

    if dry_run and any([args.drop_empty, args.clean_minute, args.clean_logs,
                        args.remove_legacy, args.vacuum]):
        print("\n" + "=" * 60)
        print("Add --execute to apply the above changes")
        print("=" * 60)


if __name__ == "__main__":
    main()
