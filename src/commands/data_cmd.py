"""
数据管理命令
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def cmd_data_update(args):
    """更新行情数据"""
    from src.data.fetcher import StockFetcher

    fetcher = StockFetcher()
    fetcher.init_db()

    if args.type in ('daily', 'all'):
        print("\n=== Updating daily data ===")
        saved = fetcher.fetch_all_daily(days=args.days, limit=args.limit)
        print(f"Daily: {saved:,} rows saved")

    if args.type in ('minute', 'all'):
        print(f"\n=== Updating {args.minute}min data ===")
        saved = fetcher.fetch_all_minute(minute_type=args.minute, days=30, limit=args.limit)
        print(f"{args.minute}min: {saved:,} rows saved")

    if args.type in ('monthly', 'all'):
        print("\n=== Updating monthly data ===")
        saved = fetcher.fetch_all_monthly(months=24, limit=args.limit)
        print(f"Monthly: {saved:,} rows saved")

    stats = fetcher.get_db_stats()
    print(f"\nDatabase stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


def cmd_data_info(args):
    """显示数据概况"""
    from src.data.loader import DataLoader

    loader = DataLoader()
    info = loader.get_db_info()

    print("=" * 60)
    print("Database Info")
    print("=" * 60)
    for k, v in info.items():
        print(f"\n{k}:")
        for kk, vv in v.items():
            print(f"  {kk}: {vv}")

    symbols = loader.get_daily_symbols(min_days=100)
    print(f"\nStocks with >= 100 days: {len(symbols)}")
    if symbols:
        print(f"  Sample: {symbols[:10]}")


def cmd_data_merge(args):
    """合并数据库"""
    from pathlib import Path
    from src.data.merger import merge_databases

    source = Path(args.source)
    target = Path(args.target)
    merge_databases(source, target)
