import sys
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.fetcher import StockFetcher, _get_session, _TENCENT_DAILY_URL, _code_to_prefix

import json

DB_PATH = Path(r'f:\日常项目\quant——project\data\db\market.db')

def get_stale_codes(stale_days=3):
    cutoff = (datetime.now() - timedelta(days=stale_days)).strftime('%Y-%m-%d')
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT code FROM stock_kline GROUP BY code HAVING MAX(date) < ?", (cutoff,))
    codes = [row[0] for row in c.fetchall()]
    conn.close()
    return codes

def get_missing_codes():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute('SELECT DISTINCT code FROM stock_kline')
    existing = set(row[0] for row in c.fetchall())
    conn.close()

    fetcher = StockFetcher()
    all_stocks = fetcher._get_stock_list_eastmoney()
    missing = [s for s in all_stocks if s not in existing]
    return missing

def fetch_daily_tencent(stock_code, days=1095):
    prefix = _code_to_prefix(stock_code)
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    count = min(days, 800)

    session = _get_session()
    try:
        url = f'{_TENCENT_DAILY_URL}?param={prefix}{stock_code},day,{start},{end},{count},qfq'
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return []

        data = json.loads(r.text)
        sd = data.get('data', {}).get(f'{prefix}{stock_code}', {})
        raw = sd.get('qfqday') or sd.get('day') or []

        result = []
        for row in raw:
            if len(row) >= 6:
                result.append({
                    'code': stock_code, 'date': row[0],
                    'open': float(row[1] or 0), 'close': float(row[2] or 0),
                    'high': float(row[3] or 0), 'low': float(row[4] or 0),
                    'volume': int(float(row[5] or 0)), 'amount': 0,
                })
        return result
    except Exception:
        return []

def save_daily(data_list):
    if not data_list:
        return 0
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    saved = 0
    for d in data_list:
        try:
            c.execute('''INSERT OR REPLACE INTO stock_kline
                (code, date, open, high, low, close, volume, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (d['code'], d['date'], d['open'], d['high'],
                 d['low'], d['close'], d['volume'], d['amount']))
            saved += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return saved

def progress_bar(current, total, code, saved):
    pct = current / total * 100
    filled = int(30 * pct / 100)
    bar = '█' * filled + '░' * (30 - filled)
    print(f"\r[{bar}] {current}/{total} ({pct:.0f}%) {code} saved:{saved}", end='', flush=True)

def main():
    print("=== 数据更新（腾讯HTTP源） ===\n")

    print("1. 检查stale codes...")
    stale = get_stale_codes()
    print(f"   Stale: {len(stale)} stocks need update")

    print("\n2. 检查missing codes...")
    missing = get_missing_codes()
    print(f"   Missing: {len(missing)} new stocks")

    remaining = sorted(set(stale + missing))
    print(f"\n3. Total to update: {len(remaining)} stocks")
    print(f"   Estimated time: {len(remaining) * 0.2 / 60:.0f} minutes\n")

    if not remaining:
        print("All data is up to date!")
        return

    total_saved = 0
    failed = []
    t0 = time.time()

    for i, code in enumerate(remaining):
        data = fetch_daily_tencent(code, days=1095)
        if not data:
            data = fetch_daily_tencent(code, days=1825)
        saved = save_daily(data)
        total_saved += saved
        if not data:
            failed.append(code)
        progress_bar(i + 1, len(remaining), code, saved)
        time.sleep(0.1)

    elapsed = time.time() - t0
    print(f"\n\n=== 完成 ===")
    print(f"  耗时: {elapsed/60:.1f} 分钟")
    print(f"  保存: {total_saved:,} 行")
    print(f"  失败: {len(failed)} 只")

    if failed and len(failed) <= 20:
        print(f"  失败列表: {failed}")

if __name__ == '__main__':
    main()
