"""
新闻抓取 — 多源财经新闻获取（RSS + JSON API）
"""

import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests

from config.settings import DB, news_config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

STOCK_CODE_RE = re.compile(r'(?<!\d)([036]\d{5})(?!\d)')

RSS_FEEDS = {
    "中新网-财经": "https://www.chinanews.com.cn/rss/finance.xml",
}

JSON_API_SOURCES = {
    "财联社-电报": {
        "url": "https://www.cls.cn/nodeapi/updateTelegraphList?app=CailianpressWeb&os=web&rn=20",
        "parser": "_parse_cls",
    },
    "东方财富-快讯": {
        "url": "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_20_1_.html",
        "parser": "_parse_eastmoney",
    },
    "同花顺-7x24": {
        "url": "https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&limit=20",
        "parser": "_parse_ths",
    },
    "新浪财经-滚动": {
        "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num=20&page=1",
        "parser": "_parse_sina",
    },
}


def _make_id(url: str, title: str) -> str:
    raw = f"{url}:{title}"
    return hashlib.md5(raw.encode()).hexdigest()


def _extract_stock_codes(text: str) -> str:
    codes = STOCK_CODE_RE.findall(text)
    return ",".join(sorted(set(codes)))


def _fetch_with_timeout(url: str, timeout: int = 15, retries: int = 2) -> str | None:
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            print(f"  Retry {i+1} failed: {e}")
            if i < retries - 1:
                time.sleep(1)
    return None


def _parse_cls(data: dict, max_items: int) -> list[dict]:
    items = []
    raw_list = data.get("data", {}) or {}
    if isinstance(raw_list, dict):
        raw_list = raw_list.get("roll_data", []) or raw_list.get("list", [])
    if not isinstance(raw_list, list):
        raw_list = []
    for article in raw_list[:max_items]:
        title = article.get("title", "") or article.get("brief", "")
        content = article.get("content", "") or article.get("brief", "")
        url = article.get("shareurl", "") or f"https://www.cls.cn/detail/{article.get('id', '')}"
        pub_ts = article.get("ctime", 0) or article.get("sort_score", 0)
        if pub_ts and pub_ts > 1e9:
            pub_date = datetime.fromtimestamp(int(pub_ts)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            pub_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stock_codes = ""
        stock_list = article.get("stock_list", [])
        if isinstance(stock_list, list) and stock_list:
            codes = []
            for s in stock_list:
                if isinstance(s, dict):
                    code = str(s.get("stock_code", "") or s.get("code", ""))
                    if code and len(code) == 6:
                        codes.append(code)
                elif isinstance(s, str) and len(s) == 6:
                    codes.append(s)
            if codes:
                stock_codes = ",".join(sorted(set(codes)))
        if not stock_codes:
            stock_codes = _extract_stock_codes(f"{title} {content}")
        items.append({
            "id": _make_id(url, title),
            "title": title,
            "content": content[:1500],
            "url": url,
            "pub_date": pub_date,
            "source": "cls",
            "stock_codes": stock_codes,
        })
    return items


def _parse_eastmoney(data: dict, max_items: int) -> list[dict]:
    items = []
    news_list = data.get("LivesList", []) or data.get("data", {}) or []
    if isinstance(news_list, dict):
        news_list = news_list.get("list", [])
    if isinstance(news_list, list):
        for article in news_list[:max_items]:
            title = article.get("title", "") or article.get("simtitle", "")
            content = article.get("digest", "") or article.get("simdigest", "") or article.get("content", "")
            url = article.get("url_w", "") or article.get("url_m", "") or article.get("url_unique", "")
            pub_ts = article.get("sort", "") or article.get("showtime", "") or article.get("ptime", "")
            if isinstance(pub_ts, (int, float)) and pub_ts > 1e12:
                pub_date = datetime.fromtimestamp(int(pub_ts) / 1000).strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(pub_ts, str) and pub_ts and len(pub_ts) >= 10:
                pub_date = pub_ts[:19] if "T" in pub_ts or " " in pub_ts else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                pub_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            stock_codes = _extract_stock_codes(f"{title} {content}")
            items.append({
                "id": _make_id(url, title),
                "title": title,
                "content": content[:1500],
                "url": url,
                "pub_date": pub_date,
                "source": "eastmoney",
                "stock_codes": stock_codes,
            })
    return items


def _parse_ths(data: dict, max_items: int) -> list[dict]:
    items = []
    news_list = data.get("data", {}) or {}
    if isinstance(news_list, dict):
        news_list = news_list.get("list", []) or news_list.get("items", [])
    if isinstance(news_list, list):
        for article in news_list[:max_items]:
            title = article.get("title", "")
            content = article.get("digest", "") or article.get("content", "") or article.get("desc", "")
            url = article.get("url", "") or f"https://news.10jqka.com.cn/{article.get('id', '')}"
            pub_ts = article.get("ctime", 0) or article.get("pub_time", 0)
            if isinstance(pub_ts, (int, float)) and pub_ts > 1e9:
                pub_date = datetime.fromtimestamp(int(pub_ts)).strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(pub_ts, str) and pub_ts:
                pub_date = pub_ts
            else:
                pub_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            stock_codes = _extract_stock_codes(f"{title} {content}")
            items.append({
                "id": _make_id(url, title),
                "title": title,
                "content": content[:1500],
                "url": url,
                "pub_date": pub_date,
                "source": "ths",
                "stock_codes": stock_codes,
            })
    return items


def _parse_sina(data: dict, max_items: int) -> list[dict]:
    items = []
    news_list = data.get("result", {}) or {}
    if isinstance(news_list, dict):
        news_list = news_list.get("data", [])
    if isinstance(news_list, list):
        for article in news_list[:max_items]:
            title = article.get("title", "")
            content = article.get("intro", "") or article.get("content", "")
            url = article.get("url", "") or article.get("wapurl", "")
            pub_ts = article.get("ctime", "") or article.get("pub_date", "")
            if isinstance(pub_ts, (int, float)) and pub_ts > 1e9:
                pub_date = datetime.fromtimestamp(int(pub_ts)).strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(pub_ts, str) and pub_ts:
                pub_date = pub_ts
            else:
                pub_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            stock_codes = _extract_stock_codes(f"{title} {content}")
            items.append({
                "id": _make_id(url, title),
                "title": title,
                "content": content[:1500],
                "url": url,
                "pub_date": pub_date,
                "source": "sina",
                "stock_codes": stock_codes,
            })
    return items


def _fetch_rss_source(source: str, url: str, max_items: int) -> list[dict]:
    try:
        import feedparser
    except ImportError:
        print(f"  [SKIP] feedparser not installed")
        return []

    text = _fetch_with_timeout(url, timeout=15)
    if not text:
        print(f"  [SKIP] fetch failed")
        return []

    feed = feedparser.parse(text)
    if not feed or not hasattr(feed, "entries") or not feed.entries:
        print(f"  [SKIP] no entries")
        return []

    items = []
    for entry in feed.entries[:max_items]:
        title = entry.get("title", "")
        link = entry.get("link", "") or entry.get("guid", "")
        if not title:
            continue

        pub_ts = entry.get("published_parsed") or entry.get("updated_parsed")
        if pub_ts:
            try:
                pub_date = datetime(*pub_ts[:6]).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pub_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            pub_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        content = entry.get("summary", "") or entry.get("description", "")
        stock_codes = _extract_stock_codes(f"{title} {content}")

        items.append({
            "id": _make_id(link or title, title),
            "title": title,
            "content": content[:1500],
            "url": link,
            "pub_date": pub_date,
            "source": source,
            "stock_codes": stock_codes,
        })
    return items


def _fetch_json_source(source: str, config: dict, max_items: int) -> list[dict]:
    url = config["url"]
    parser_name = config["parser"]

    text = _fetch_with_timeout(url, timeout=15)
    if not text:
        print(f"  [SKIP] fetch failed")
        return []

    try:
        json_text = text
        if json_text.startswith("jQuery") or json_text.startswith("callback"):
            json_text = re.sub(r'^[^(]+\(', '', json_text)
            json_text = re.sub(r'\);?$', '', json_text)
        if json_text.startswith("var ") or "=" in json_text[:50]:
            json_text = re.sub(r'^var\s+\w+\s*=\s*', '', json_text)
            if json_text.endswith(";"):
                json_text = json_text[:-1]
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f"  [SKIP] JSON parse failed: {e}")
        return []

    parser_fn = globals().get(parser_name)
    if not parser_fn:
        print(f"  [SKIP] parser {parser_name} not found")
        return []

    return parser_fn(data, max_items)


def fetch_rss_feeds(
    sources: list[str] | None = None,
    max_per_source: int = None,
) -> list[dict]:
    max_per_source = max_per_source or news_config.rss_max_per_source
    results = []

    for source, url in RSS_FEEDS.items():
        if sources and source not in sources:
            continue
        print(f"[RSS] {source}: {url}")
        items = _fetch_rss_source(source, url, max_per_source)
        print(f"  Got {len(items)} articles")
        results.extend(items)
        time.sleep(0.3)

    for source, config in JSON_API_SOURCES.items():
        if sources and source not in sources:
            continue
        print(f"[API] {source}: {config['url'][:60]}...")
        items = _fetch_json_source(source, config, max_per_source)
        print(f"  Got {len(items)} articles")
        results.extend(items)
        time.sleep(0.3)

    print(f"Total: {len(results)} news articles")
    return results


def _ensure_news_raw_schema(conn):
    c = conn.cursor()
    row = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='news_raw'").fetchone()
    if row and "INTEGER PRIMARY KEY" in (row[0] or ""):
        cnt = c.execute("SELECT COUNT(*) FROM news_raw").fetchone()[0]
        if cnt == 0:
            c.execute("DROP TABLE news_raw")
        else:
            print(f"  [WARN] news_raw has {cnt} rows with old schema (id=INTEGER), migrating...")
            c.execute("ALTER TABLE news_raw RENAME TO news_raw_old")
            c.execute('''CREATE TABLE news_raw (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT,
                url TEXT,
                pub_date TEXT NOT NULL,
                source TEXT,
                stock_codes TEXT,
                fetched_at TEXT DEFAULT (datetime('now'))
            )''')
            c.execute('''INSERT OR IGNORE INTO news_raw (id, title, content, url, pub_date, source, stock_codes)
                SELECT CAST(id AS TEXT), title, content, url, pub_date, source, stock_codes FROM news_raw_old''')
            c.execute("DROP TABLE news_raw_old")
            conn.commit()


def save_raw_news(items: list[dict], db_path: Path = None) -> int:
    db_path = db_path or DB["quantpro"]
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    _ensure_news_raw_schema(conn)

    c.execute('''CREATE TABLE IF NOT EXISTS news_raw (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        content TEXT,
        url TEXT,
        pub_date TEXT NOT NULL,
        source TEXT,
        stock_codes TEXT,
        fetched_at TEXT DEFAULT (datetime('now'))
    )''')

    saved = 0
    for item in items:
        try:
            c.execute('''INSERT OR IGNORE INTO news_raw
                (id, title, content, url, pub_date, source, stock_codes)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (item["id"], item["title"], item["content"],
                 item["url"], item["pub_date"], item["source"],
                 item["stock_codes"]))
            if c.rowcount > 0:
                saved += 1
        except Exception as e:
            print(f"  [WARN] save news failed (id={item.get('id','?')}): {e}")

    conn.commit()
    conn.close()
    return saved
