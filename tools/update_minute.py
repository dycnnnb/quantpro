import sys
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.fetcher import _get_session, _TENCENT_MIN_URL, _code_to_prefix

import json

DB_PATH = Path(r'f:\日常项目\quant——project\data\db\market.db')

def get_codes_needing_minute():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT DISTINCT code FROM minute_kline WHERE minute_type='5min'")
    existing = set(row[0] for row in c.fetchall())
    conn.close()

    c2 = sqlite3.connect(str(DB_PATH))
    cur = c2.cursor()
    cur.execute('SELECT DISTINCT code FROM stock_kline')
    all_codes = [row[0] for row in cur.fetchall()]
    c2.close()

    missing = [s for s in all_codes if s not in existing]
    return missing, len(all_codes)

def get_stale_minute_codes():
    cutoff = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT code FROM minute_kline WHERE minute_type='5min' GROUP BY code HAVING MAX(date) < ?", (cutoff,))
    stale = [row[0] for row in c.fetchall()]
    conn.close()
    return stale

def fetch_minute_tencent(stock_code, minute_type=5, days=5):
    prefix = _code_to_prefix(stock_code)
    freq_map = {5: 'm5', 15: 'm15', 30: 'm30', 60: 'm60'}
    freq = freq_map.get(minute_type, 'm5')
    count = days * 48

    session = _get_session()
    try:
        url = f'{_TENCENT_MIN_URL}?param={prefix}{stock_code},{freq},,{count}'
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return []

        data = json.loads(r.text)
        raw = data.get('data', {}).get(f'{prefix}{stock_code}', {}).get(freq, [])

        result = []
        for row in raw:
            if len(row) >= 6:
                dt_str = str(row[0])
                if len(dt_str) == 12:
                    date_part = f'{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]}'
                    time_part = f'{dt_str[8:10]}:{dt_str[10:12]}'
                else:
                    date_part = dt_str[:10]
                    time_part = dt_str[11:16] if len(dt_str) > 11 else ''

                result.append({
                    'code': stock_code, 'date': date_part, 'time': time_part,
                    'open': float(row[1] or 0), 'close': float(row[2] or 0),
                    'high': float(row[3] or 0), 'low': float(row[4] or 0),
                    'volume': int(float(row[5] or 0)),
                })
        return result
    except Exception:
        return []

def save_minute(data_list, minute_type='5min'):
    if not data_list:
        return 0
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    saved = 0
    for d in data_list:
        try:
            c.execute('''INSERT OR REPLACE INTO minute_kline
                (code, date, time, open, high, low, close, volume, minute_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (d['code'], d['date'], d['time'], d['open'],
                 d['high'], d['low'], d['close'], d['volume'], minute_type))
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
    print("=== 5分钟线数据更新（腾讯HTTP源） ===\n")

    missing, total = get_codes_needing_minute()
    stale = get_stale_minute_codes()

    print(f"  Total stocks: {total}")
    print(f"  Missing 5min data: {len(missing)}")
    print(f"  Stale 5min data: {len(stale)}")

    remaining = sorted(set(missing + stale))
    print(f"  Total to update: {len(remaining)}")
    print(f"  Estimated time: {len(remaining) * 0.15 / 60:.0f} minutes\n")

    if not remaining:
        print("All 5min data is up to date!")
        return

    total_saved = 0
    failed = []
    t0 = time.time()

    for i, code in enumerate(remaining):
        data = fetch_minute_tencent(code, minute_type=5, days=5)
        saved = save_minute(data, '5min')
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

if __name__ == '__main__':
    main()
