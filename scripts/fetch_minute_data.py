#!/usr/bin/env python3
"""
全市场 5 分钟线数据抓取 — 新浪财经 API (主) + baostock (备)
支持增量更新、断点续传、定时运行、多数据源自动降级

用法:
  python fetch_minute_data.py                    # 抓取全部
  python fetch_minute_data.py --days 30          # 最近30天
  python fetch_minute_data.py --codes 600519,000001  # 指定股票
  python fetch_minute_data.py --daemon           # 守护进程模式（每天自动抓取）
  python fetch_minute_data.py --source sina      # 强制使用新浪
  python fetch_minute_data.py --source baostock  # 强制使用baostock
"""

import argparse
import json
import sqlite3
import sys
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

import requests

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "db" / "market.db"
LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "fetch_minute.log"
STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "fetch_minute_state.json"

REQUEST_INTERVAL = 0.15
SINA_MAX_DATALEN = 5049
SINA_BATCH_SIZE = 4800

SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn/",
    "Accept": "*/*",
}

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_PATH), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("fetcher")


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS minute_kline (
        code TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        minute_type TEXT DEFAULT '5min',
        PRIMARY KEY (code, date, time, minute_type)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS stock_kline (
        code TEXT NOT NULL,
        date TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        amount REAL,
        PRIMARY KEY (code, date)
    )''')

    c.execute('CREATE INDEX IF NOT EXISTS idx_minute_code ON minute_kline(code)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_minute_date ON minute_kline(date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_minute_code_date ON minute_kline(code, date)')

    conn.commit()
    conn.close()
    log.info(f"Database initialized: {DB_PATH}")


def get_all_stocks_sina():
    stocks = []
    page = 1
    while True:
        for retry in range(3):
            try:
                url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
                params = {
                    "page": str(page),
                    "num": "80",
                    "sort": "symbol",
                    "asc": "1",
                    "node": "hs_a",
                    "symbol": "",
                    "_s_r_a": "page",
                }
                r = requests.get(url, params=params, headers=SINA_HEADERS, timeout=30)
                data = json.loads(r.text)
                if not data:
                    if retry < 2:
                        time.sleep(2)
                        continue
                    break
                for item in data:
                    code = item.get("code", "")
                    if code.startswith("6"):
                        stocks.append(f"sh.{code}")
                    elif code.startswith("0") or code.startswith("3"):
                        stocks.append(f"sz.{code}")
                if len(data) < 80:
                    return stocks
                page += 1
                time.sleep(0.3)
                break
            except Exception as e:
                log.warning(f"Sina stock list page {page} retry {retry+1}: {e}")
                if retry < 2:
                    time.sleep(3 * (retry + 1))
                else:
                    return stocks
    return stocks


def get_all_stocks_baostock():
    try:
        import baostock as bs
    except ImportError:
        return []

    for attempt in range(3):
        lg = bs.login()
        if lg.error_code == '0':
            break
        log.warning(f"Baostock login attempt {attempt+1} failed: {lg.error_msg}")
        time.sleep(5 * (attempt + 1))
    else:
        log.error(f"Baostock login failed after 3 attempts")
        return []

    try:
        rs = bs.query_stock_basic()
        stocks = []
        while rs.next():
            row = rs.get_row_data()
            code = row[0]
            status = row[4]
            if status == '1' and (
                code.startswith('sh.6') or
                code.startswith('sz.0') or
                code.startswith('sz.3')
            ):
                stocks.append(code)
    finally:
        try:
            bs.logout()
        except Exception:
            pass

    log.info(f"Total A-share stocks from baostock: {len(stocks)}")
    return stocks


def get_all_stocks():
    db_stocks = _get_stocks_from_db()
    if len(db_stocks) >= 4000:
        log.info(f"Using {len(db_stocks)} stocks from DB (sufficient)")
        return db_stocks

    sina_stocks = get_all_stocks_sina()
    if len(sina_stocks) >= 4000:
        log.info(f"Using {len(sina_stocks)} stocks from sina")
        return sina_stocks

    bs_stocks = get_all_stocks_baostock()
    if len(bs_stocks) >= 4000:
        log.info(f"Using {len(bs_stocks)} stocks from baostock")
        return bs_stocks

    all_stocks = list(set(db_stocks + sina_stocks + bs_stocks))
    log.info(f"Merged stock list: {len(all_stocks)} stocks")
    return all_stocks


def _normalize_code(code):
    if code.startswith("sh.") or code.startswith("sz."):
        return code
    pure = code.replace(".", "").strip()
    if pure.startswith("6"):
        return f"sh.{pure}"
    elif pure.startswith("0") or pure.startswith("3"):
        return f"sz.{pure}"
    return code


def _get_stocks_from_db():
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    raw_codes = set()
    for table in ["minute_kline", "stock_kline"]:
        try:
            c.execute(f"SELECT DISTINCT code FROM {table}")
            for r in c.fetchall():
                raw_codes.add(r[0])
        except Exception:
            pass
    conn.close()
    stocks = []
    for code in raw_codes:
        nc = _normalize_code(code)
        if nc.startswith("sh.6") or nc.startswith("sz.0") or nc.startswith("sz.3"):
            stocks.append(nc)
    stocks = sorted(list(set(stocks)))
    log.info(f"Stocks from DB: {len(stocks)}")
    return stocks


def _sina_code(code):
    if code.startswith("sh."):
        return f"sh{code[3:]}"
    elif code.startswith("sz."):
        return f"sz{code[3:]}"
    elif code.startswith("6"):
        return f"sh{code}"
    elif code.startswith("0") or code.startswith("3"):
        return f"sz{code}"
    return code


def fetch_stock_minute_sina(code, start_date=None, end_date=None):
    sina_code = _sina_code(code)
    db_code = _normalize_code(code)
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"

    try:
        params = {
            "symbol": sina_code,
            "scale": "5",
            "ma": "no",
            "datalen": str(SINA_MAX_DATALEN),
        }
        r = requests.get(url, params=params, headers=SINA_HEADERS, timeout=30)
        if r.status_code != 200:
            return 0

        data = json.loads(r.text)
        if not data or not isinstance(data, list):
            return 0

        rows = []
        for item in data:
            day_str = item.get("day", "")
            if not day_str:
                continue
            parts = day_str.split(" ")
            date_val = parts[0] if len(parts) >= 1 else ""
            time_val = parts[1] if len(parts) >= 2 else ""

            if start_date and date_val < start_date:
                continue
            if end_date and date_val > end_date:
                continue

            rows.append((
                db_code,
                date_val,
                time_val,
                float(item.get("open", 0)) if item.get("open") else None,
                float(item.get("high", 0)) if item.get("high") else None,
                float(item.get("low", 0)) if item.get("low") else None,
                float(item.get("close", 0)) if item.get("close") else None,
                float(item.get("volume", 0)) if item.get("volume") else None,
                '5min',
            ))

        if not rows:
            return 0

        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        c.executemany('''INSERT OR REPLACE INTO minute_kline
            (code, date, time, open, high, low, close, volume, minute_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', rows)
        conn.commit()
        conn.close()
        return len(rows)

    except Exception as e:
        log.debug(f"Sina fetch {code}: {e}")
        return -1


def fetch_stock_minute_baostock(code, start_date, end_date):
    try:
        import baostock as bs
    except ImportError:
        return -1

    fields = "date,time,open,high,low,close,volume"

    for attempt in range(3):
        try:
            lg = bs.login()
            if lg.error_code != '0':
                time.sleep(3 * (attempt + 1))
                continue

            rs = bs.query_history_k_data_plus(
                code, fields,
                start_date=start_date,
                end_date=end_date,
                frequency="5",
                adjustflag="3",
            )

            rows = []
            if rs.error_code == '0':
                while rs.next():
                    rows.append(rs.get_row_data())

            bs.logout()

            if not rows:
                return 0

            conn = sqlite3.connect(str(DB_PATH))
            c = conn.cursor()
            c.executemany('''INSERT OR REPLACE INTO minute_kline
                (code, date, time, open, high, low, close, volume, minute_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                [(code, r[0], r[1],
                  float(r[2]) if r[2] else None,
                  float(r[3]) if r[3] else None,
                  float(r[4]) if r[4] else None,
                  float(r[5]) if r[5] else None,
                  float(r[6]) if r[6] else None,
                  '5min') for r in rows])
            conn.commit()
            conn.close()
            return len(rows)

        except Exception as e:
            try:
                bs.logout()
            except Exception:
                pass
            if attempt < 2:
                time.sleep(2)

    return -1


def fetch_stock_minute(code, start_date=None, end_date=None, source="auto"):
    if source in ("sina", "auto"):
        result = fetch_stock_minute_sina(code, start_date, end_date)
        if result >= 0:
            return result
        log.warning(f"Sina failed for {code}, trying baostock...")

    if source in ("baostock", "auto"):
        sd = start_date or (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        ed = end_date or datetime.now().strftime('%Y-%m-%d')
        result = fetch_stock_minute_baostock(code, sd, ed)
        if result >= 0:
            return result

    return 0


def _db_code_variants(code):
    variants = [code]
    if code.startswith("sh."):
        variants.append(code[3:])
    elif code.startswith("sz."):
        variants.append(code[3:])
    else:
        if code.startswith("6"):
            variants.append(f"sh.{code}")
        elif code.startswith("0") or code.startswith("3"):
            variants.append(f"sz.{code}")
    return variants


def get_last_date(code):
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    variants = _db_code_variants(code)
    placeholders = ",".join(["?"] * len(variants))
    c.execute(f"SELECT MAX(date) FROM minute_kline WHERE code IN ({placeholders}) AND minute_type='5min'", variants)
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def get_row_count(code):
    if not DB_PATH.exists():
        return 0
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    variants = _db_code_variants(code)
    placeholders = ",".join(["?"] * len(variants))
    c.execute(f"SELECT COUNT(*) FROM minute_kline WHERE code IN ({placeholders}) AND minute_type='5min'", variants)
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {"last_run": None, "last_code_idx": 0, "total_stocks": 0, "source": "sina"}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding='utf-8')


def run_fetch(days=365, codes=None, reset=False, source="auto"):
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')

    if reset:
        if STATE_PATH.exists():
            STATE_PATH.unlink()
            log.info("Deleted state file")

    log.info(f"=== Fetch started: {start_date} ~ {end_date}, source={source} ===")

    init_db()

    if codes:
        stock_list = [f"sh.{c}" if c.startswith('6') else f"sz.{c}" for c in codes]
    else:
        stock_list = get_all_stocks()

    if not stock_list:
        log.error("No stocks to fetch")
        return

    state = load_state()
    start_idx = state.get("last_code_idx", 0) if not codes else 0

    total = len(stock_list)
    total_saved = 0
    errors = 0
    skipped = 0

    log.info(f"Starting from index {start_idx}/{total}")

    for i, code in enumerate(stock_list[start_idx:], start_idx):
        try:
            existing_rows = get_row_count(code)

            if existing_rows >= SINA_MAX_DATALEN * 0.95 and not codes:
                skipped += 1
                if (i + 1) % 500 == 0:
                    log.info(f"Progress: {i+1}/{total} ({(i+1)/total*100:.1f}%) | saved={total_saved} skipped={skipped} errors={errors}")
                    state["last_code_idx"] = i + 1
                    state["total_stocks"] = total
                    state["source"] = source
                    save_state(state)
                time.sleep(0.01)
                continue

            saved = fetch_stock_minute(code, start_date=start_date, end_date=end_date, source=source)
            if saved < 0:
                errors += 1
            else:
                total_saved += saved

            if (i + 1) % 50 == 0:
                log.info(f"Progress: {i+1}/{total} ({(i+1)/total*100:.1f}%) | saved={total_saved} skipped={skipped} errors={errors}")
                state["last_code_idx"] = i + 1
                state["total_stocks"] = total
                state["source"] = source
                save_state(state)

            time.sleep(REQUEST_INTERVAL)

        except KeyboardInterrupt:
            log.info("Interrupted by user, saving state...")
            state["last_code_idx"] = i
            state["total_stocks"] = total
            state["source"] = source
            save_state(state)
            return
        except Exception as e:
            errors += 1
            log.error(f"  {code}: {e}")
            if errors > 100:
                log.error("Too many errors, stopping")
                state["last_code_idx"] = i + 1
                state["total_stocks"] = total
                state["source"] = source
                save_state(state)
                break
            time.sleep(1)

    state["last_run"] = datetime.now().isoformat()
    state["last_code_idx"] = 0
    state["total_stocks"] = total
    state["source"] = source
    save_state(state)

    log.info(f"=== Fetch done: {total_saved} rows saved, {skipped} skipped, {errors} errors ===")

    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT code), COUNT(*), MIN(date), MAX(date) FROM minute_kline WHERE minute_type='5min'")
    row = c.fetchone()
    conn.close()
    log.info(f"Database: {row[0]} stocks, {row[1]} rows, {row[2]} ~ {row[3]}")


def run_daemon():
    log.info("=== Daemon mode started ===")
    while True:
        now = datetime.now()
        if now.hour >= 15 and now.minute >= 30:
            weekday = now.weekday()
            if weekday < 5:
                try:
                    run_fetch(days=5, source="auto")
                except Exception as e:
                    log.error(f"Fetch error: {e}")
                time.sleep(3600 * 12)
            else:
                time.sleep(3600)
        else:
            time.sleep(300)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="全市场5分钟线抓取")
    parser.add_argument("--days", type=int, default=365, help="历史天数(默认365)")
    parser.add_argument("--codes", type=str, default=None, help="指定股票(逗号分隔)")
    parser.add_argument("--daemon", action="store_true", help="守护进程模式")
    parser.add_argument("--reset", action="store_true", help="重置断点重新抓取")
    parser.add_argument("--source", type=str, default="auto", choices=["auto", "sina", "baostock"], help="数据源")
    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    else:
        codes = args.codes.split(",") if args.codes else None
        run_fetch(days=args.days, codes=codes, reset=args.reset, source=args.source)
