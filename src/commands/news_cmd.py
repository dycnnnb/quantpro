"""
新闻因子分析 CLI 命令
"""


def cmd_news_fetch(args):
    """抓取新闻"""
    from src.news.rss_fetcher import fetch_rss_feeds, save_raw_news

    sources = None
    if args.sources:
        sources = [s.strip() for s in args.sources.split(",")]

    print("=" * 50)
    print("抓取新闻")
    print("=" * 50)

    items = fetch_rss_feeds(sources=sources)
    if not items:
        print("没有获取到新闻")
        return

    saved = save_raw_news(items)
    print(f"保存: {saved} 条新新闻（共 {len(items)} 条）")


def cmd_news_analyze(args):
    """分析新闻因子"""
    from src.news.analyzer import analyze_all_pending, aggregate_daily_factors

    print("=" * 50)
    print("分析新闻因子")
    print("=" * 50)

    analyzed = analyze_all_pending(
        batch_size=args.batch_size,
        limit=args.limit,
    )

    if analyzed > 0:
        print("\n聚合日频因子...")
        aggregated = aggregate_daily_factors()
        print(f"完成: 分析 {analyzed} 条, 聚合 {aggregated} 条日频因子")
    else:
        print("没有新的新闻需要分析")
