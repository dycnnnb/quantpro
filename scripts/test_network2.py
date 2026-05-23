#!/usr/bin/env python3
import os
import socket

print("=== Proxy settings ===")
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    val = os.environ.get(key, '(not set)')
    print(f"  {key} = {val}")

print("\n=== DNS resolution ===")
try:
    ip = socket.gethostbyname('baostock.com')
    print(f"  baostock.com => {ip}")
except Exception as e:
    print(f"  baostock.com DNS failed: {e}")

print("\n=== Test baostock internals ===")
import baostock.common.contants as cons
attrs = [a for a in dir(cons) if not a.startswith('_')]
print(f"  contants attrs: {attrs}")

print("\n=== Test direct TCP to baostock ===")
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(('baostock.com', 80))
    print(f"  TCP connect to baostock.com:80 => OK")
    s.close()
except Exception as e:
    print(f"  TCP connect failed: {e}")

print("\n=== Test tushare ===")
try:
    import tushare as ts
    print(f"  tushare version: {ts.__version__}")
    pro = ts.pro_api()
    df = pro.daily(ts_code='600519.SH', start_date='20250519', end_date='20250520')
    print(f"  tushare pro daily: {len(df)} rows")
except Exception as e:
    print(f"  tushare pro failed: {e}")

print("\n=== Test tushare 5min ===")
try:
    import tushare as ts
    pro = ts.pro_api()
    df = pro.stk_mins(ts_code='600519.SH', start_date='2025-05-19 09:30:00', end_date='2025-05-20 15:00:00', freq='5min')
    print(f"  tushare 5min: {len(df)} rows")
    if len(df) > 0:
        print(df.head(3))
except Exception as e:
    print(f"  tushare 5min failed: {e}")

print("\n=== Test akshare eastmoney direct ===")
try:
    import requests
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": "1.600519",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": "5",
        "fqt": "1",
        "beg": "20250519",
        "end": "20250520",
    }
    r = requests.get(url, params=params, timeout=10)
    print(f"  eastmoney direct: status={r.status_code}, len={len(r.text)}")
    data = r.json()
    klines = data.get("data", {}).get("klines", [])
    print(f"  klines count: {len(klines)}")
    if klines:
        print(f"  first: {klines[0]}")
        print(f"  last: {klines[-1]}")
except Exception as e:
    print(f"  eastmoney direct failed: {e}")
