import sys
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.fetcher import _get_session, _TENCENT_DAILY_URL, _code_to_prefix

import json

DB_PATH = Path(r'f:\日常项目\quant——project\data\db\market.db')

def get_remaining():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute('SELECT DISTINCT code FROM monthly_kline')
    existing = set(row[0] for row in c.fetchall())
    c2 = conn.cursor()
    c2.execute('SELECT DISTINCT code FROM stock_kline')
    all_codes = [row[0] for row in c2.fetchall()]

    cutoff = (datetime.now() - timedelta(days=35)).strftime('%Y-%m-%d')
    c3 = conn.cursor()
    c3.execute("SELECT code FROM monthly_kline GROUP BY code HAVING MAX(date) < ?", (cutoff,))
    stale = set(row[0] for row in c3.fetchall())
    conn.close()

    missing = [s for s in all_codes if s not in existing]
    need_update = [s for s in missing if s not in stale] + list(stale)
    return sorted(set(need_update))

def fetch_monthly_tencent(stock_code, months=24):
    prefix = _code_to_prefix(stock_code)
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=months * 35)).strftime('%Y-%m-%d')
    count = min(months + 5, 120)

    session = _get_session()
    try:
        url = f'{_TENCENT_DAILY_URL}?param={prefix}{stock_code},month,{start},{end},{count},qfq'
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return []
        data = json.loads(r.text)
        sd = data.get('data', {}).get(f'{prefix}{stock_code}', {})
        raw = sd.get('qfqmonth') or sd.get('month') or []
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

def save_monthly(data_list):
    if not data_list:
        return 0
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    saved = 0
    for d in data_list:
        try:
            c.execute('''INSERT OR REPLACE INTO monthly_kline
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

def main():
    remaining = get_remaining()
    print(f"Monthly remaining: {len(remaining)} stocks")

    if not remaining:
        print("All monthly data is up to date!")
        return

    BATCH = 500
    total_saved = 0
    failed = 0

    for batch_start in range(0, len(remaining), BATCH):
        batch = remaining[batch_start:batch_start + BATCH]
        print(f"\nBatch {batch_start // BATCH + 1}: {len(batch)} stocks ({batch_start+1}-{batch_start+len(batch)})")

        for i, code in enumerate(batch):
            data = fetch_monthly_tencent(code, months=24)
            saved = save_monthly(data)
            total_saved += saved
            if not data:
                failed += 1
            pct = (batch_start + i + 1) / len(remaining) * 100
            print(f"\r  [{pct:.0f}%] {code} saved:{saved}", end='', flush=True)
            time.sleep(0.1)

        print(f"\n  Batch done. Total saved: {total_saved:,}")

    print(f"\n=== 完成 ===")
    print(f"  Total saved: {total_saved:,}")
    print(f"  Failed: {failed}")

if __name__ == '__main__':
    main()
