#!/usr/bin/env python
"""
数据更新入口
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.fetcher import StockFetcher


def main():
    print("=" * 60)
    print("Data Update")
    print("=" * 60)

    fetcher = StockFetcher()
    fetcher.init_db()

    print("\nUpdating daily data...")
    saved = fetcher.fetch_all_daily(days=1095)
    print(f"Daily: {saved:,} rows saved")

    print("\nUpdating 5min data...")
    saved = fetcher.fetch_all_minute(minute_type=5, days=30)
    print(f"5min: {saved:,} rows saved")

    stats = fetcher.get_db_stats()
    print(f"\nDatabase stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("Update complete.")


if __name__ == '__main__':
    main()
