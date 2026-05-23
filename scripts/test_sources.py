#!/usr/bin/env python3
import baostock as bs
import time

print("Testing baostock connection...")
for attempt in range(5):
    lg = bs.login()
    print(f"  Attempt {attempt+1}: error_code={lg.error_code}, msg={lg.error_msg}")
    if lg.error_code == '0':
        try:
            rs = bs.query_history_k_data_plus(
                'sh.600519',
                'date,time,open,high,low,close,volume',
                start_date='2025-05-19',
                end_date='2025-05-20',
                frequency='5',
                adjustflag='3',
            )
            print(f"  Query: error={rs.error_code}, msg={rs.error_msg}")
            cnt = 0
            while rs.next():
                cnt += 1
            print(f"  Got {cnt} rows for sh.600519")
        except Exception as e:
            print(f"  Query exception: {e}")
        finally:
            bs.logout()
        break
    time.sleep(5 * (attempt + 1))

print("\nTesting akshare...")
try:
    import akshare as ak
    df = ak.stock_zh_a_hist(symbol="600519", period="5", start_date="20250519", end_date="20250520", adjust="qfq")
    print(f"  akshare 5min ok: {len(df)} rows")
    print(df.head(3))
except Exception as e:
    print(f"  akshare failed: {e}")

print("\nTesting tushare...")
try:
    import tushare as ts
    print("  tushare installed, version:", ts.__version__)
except ImportError:
    print("  tushare not installed")
