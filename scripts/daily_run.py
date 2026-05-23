#!/usr/bin/env python
"""
每日运行入口
新闻抓取 + 信号生成 + 模拟交易执行
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.loader import DataLoader
from src.execution.paper import PaperTrader
from config.settings import data_config


def run_news_pipeline():
    print("\n" + "=" * 60)
    print("Step 1: News Pipeline")
    print("=" * 60)
    try:
        from src.news.rss_fetcher import fetch_rss_feeds, save_raw_news
        from src.news.fetcher import fetch_newsnow, save_news, save_news_to_market
        from src.news.analyzer import analyze_all_pending, aggregate_daily_factors

        items = fetch_rss_feeds()
        if items:
            saved = save_raw_news(items)
            save_news_to_market(items)
            print(f"  RSS: Saved {saved} new articles")
        else:
            print("  No RSS news fetched")

        items2 = fetch_newsnow()
        if items2:
            saved2 = save_news(items2)
            save_news_to_market(items2)
            print(f"  NewsNow: Saved {saved2} new articles")
        else:
            print("  No NewsNow news fetched")

        analyzed = analyze_all_pending()
        if analyzed > 0:
            agg = aggregate_daily_factors()
            print(f"  Analyzed {analyzed} factors, aggregated {agg} daily factors")
    except Exception as e:
        print(f"  [WARN] News pipeline failed: {e}")


def main():
    print("=" * 60)
    print("Daily Run")
    print("=" * 60)

    run_news_pipeline()

    loader = DataLoader()
    symbols = loader.get_daily_symbols(min_days=data_config.min_trading_days)
    print(f"Stock pool: {len(symbols)} stocks")

    if not symbols:
        print("No stocks available")
        return

    trader = PaperTrader()
    trader.run_daily(symbols[:100], top_k=5)
    print("Done.")


if __name__ == '__main__':
    main()
