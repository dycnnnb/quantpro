"""
新闻抓取 — NewsNow + AKShare(东方财富)
"""

import re
import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path

import requests

from config.settings import DB

NEWSNOW_URL = "https://newsnow.busiyi.world/api/s"
HEADERS = {"User-Agent": "Mozilla/5.0"}
STOCK_CODE_RE = re.compile(r'(?<!\d)([036]\d{5})(?!\d)')

_POSITIVE_KW = ['利好', '增长', '上涨', '突破', '新高', '盈利', '获批', '中标',
                '涨停', '反弹', '复苏', '超预期', '增持', '回购', '分红']
_NEGATIVE_KW = ['利空', '下跌', '亏损', '违规', '处罚', '退市', '暴跌', '跌停',
                '风险', '减持', '质押', '诉讼', '警示', '退回', '下滑']
_CATEGORY_KW = {
    'policy_news': ['政策', '央行', '国务院', '证监会', '发改委', '银保监', '财政'],
    'market_news': ['A股', '大盘', '指数', '沪深', '成交额', '北向', '融资'],
    'industry_news': ['行业', '板块', '产业链', '产能', '需求', '供给'],
    'company_news': ['公告', '业绩', '财报', '分红', '回购', '增持', '减持'],
}


def fetch_newsnow(source: str = "cls", page: int = 0) -> list:
    params = {"id": source, "page": page}
    try:
        r = requests.get(NEWSNOW_URL, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"newsnow fetch error: {e}")
        return []

    results = []
    for item in data.get("items", []):
        pub_ts = item.get("pubDate", 0)
        if pub_ts > 1e12:
            pub_ts = pub_ts / 1000
        pub_date = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M:%S")
        results.append({
            "id": item.get("id"),
            "title": item.get("title", ""),
            "content": item.get("description", ""),
            "url": item.get("url", ""),
            "pub_date": pub_date,
        })
    return results


def fetch_akshare_news(symbol: str = None, limit: int = 20) -> list:
    """通过 AKShare 获取东方财富新闻 (参考 TradingAgents-CN)"""
    try:
        import akshare as ak
    except ImportError:
        print("akshare not installed")
        return []

    results = []
    try:
        if symbol:
            df = ak.stock_news_em(symbol=symbol)
        else:
            df = ak.news_cctv()

        col_map = {
            '新闻标题': 'title', '标题': 'title',
            '新闻内容': 'content', '内容': 'content',
            '新闻摘要': 'content', '摘要': 'content',
            '新闻链接': 'url', '链接': 'url',
            '文章来源': 'source', '来源': 'source',
            '发布时间': 'pub_date', '时间': 'pub_date',
            '关键词': 'keywords',
        }

        for _, row in df.head(limit).iterrows():
            item = {}
            for cn_name, en_name in col_map.items():
                if cn_name in row.index:
                    val = row[cn_name]
                    item[en_name] = str(val) if val is not None else ''

            item.setdefault('title', '')
            item.setdefault('content', '')
            item.setdefault('url', '')
            item.setdefault('source', '东方财富')
            item.setdefault('pub_date', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            if symbol:
                item['stock_codes'] = symbol
            else:
                item['stock_codes'] = extract_stock_codes(
                    item.get('title', '') + ' ' + item.get('content', '')
                )

            item['id'] = hashlib.md5(
                (item.get('url', '') + item.get('title', '')).encode()
            ).hexdigest()

            item['sentiment'] = _classify_sentiment(item.get('title', '') + item.get('content', ''))
            item['category'] = _classify_category(item.get('title', '') + item.get('content', ''))

            results.append(item)

    except Exception as e:
        print(f"akshare news fetch error: {e}")

    return results


def _classify_sentiment(text: str) -> str:
    pos = sum(1 for kw in _POSITIVE_KW if kw in text)
    neg = sum(1 for kw in _NEGATIVE_KW if kw in text)
    if pos > neg:
        return 'positive'
    elif neg > pos:
        return 'negative'
    return 'neutral'


def _classify_category(text: str) -> str:
    for cat, keywords in _CATEGORY_KW.items():
        if any(kw in text for kw in keywords):
            return cat
    return 'general'


def extract_stock_codes(text: str) -> str:
    codes = STOCK_CODE_RE.findall(text)
    return ",".join(sorted(set(codes)))


def save_news_to_market(news_items: list, db_path: Path = None) -> int:
    """保存新闻到 market.db 的 news 表"""
    db_path = db_path or DB["market"]
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS news (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        content TEXT,
        source TEXT,
        stock_codes TEXT,
        published_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        url TEXT,
        sentiment TEXT DEFAULT 'neutral',
        category TEXT DEFAULT 'general'
    )''')

    saved = 0
    for item in news_items:
        try:
            c.execute('''INSERT OR IGNORE INTO news
                (id, title, content, source, stock_codes, published_at, url, sentiment, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (item.get('id', ''),
                 item.get('title', ''),
                 item.get('content', ''),
                 item.get('source', ''),
                 item.get('stock_codes', ''),
                 item.get('pub_date', ''),
                 item.get('url', ''),
                 item.get('sentiment', 'neutral'),
                 item.get('category', 'general')))
            if c.rowcount > 0:
                saved += 1
        except Exception:
            pass

    conn.commit()
    conn.close()
    return saved


def save_news(news_items: list, db_path: Path = None):
    db_path = db_path or DB["quantpro"]
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS news (
        id TEXT PRIMARY KEY, title TEXT, content TEXT,
        url TEXT, pub_date TEXT, stock_codes TEXT
    )''')

    saved = 0
    for item in news_items:
        try:
            codes = extract_stock_codes(item['title'] + ' ' + item.get('content', ''))
            c.execute('''INSERT OR IGNORE INTO news
                (id, title, content, url, pub_date, stock_codes)
                VALUES (?, ?, ?, ?, ?, ?)''',
                (item['id'], item['title'], item['content'],
                 item['url'], item['pub_date'], codes))
            saved += 1
        except Exception:
            pass

    conn.commit()
    conn.close()
    return saved
