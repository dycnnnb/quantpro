#!/usr/bin/env python3
import os
import socket

print("=== Proxy settings ===")
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'no_proxy', 'NO_PROXY', 'all_proxy', 'ALL_PROXY']:
    val = os.environ.get(key, '')
    if val:
        print(f"  {key} = {val}")
    else:
        print(f"  {key} = (not set)")

print("\n=== DNS resolution ===")
try:
    ip = socket.gethostbyname('baostock.com')
    print(f"  baostock.com => {ip}")
except Exception as e:
    print(f"  baostock.com DNS failed: {e}")

try:
    ip = socket.gethostbyname('push2his.eastmoney.com')
    print(f"  push2his.eastmoney.com => {ip}")
except Exception as e:
    print(f"  eastmoney DNS failed: {e}")

print("\n=== Test baostock with explicit connection ===")
import baostock as bs
import baostock.common.contants as cons
print(f"  baostock API host: {cons.api_host}")
print(f"  baostock API port: {cons.api_port}")

print("\n=== Test direct TCP to baostock ===")
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((cons.api_host, cons.api_port))
    print(f"  TCP connect to {cons.api_host}:{cons.api_port} => OK")
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
    print(df.head(3))
except Exception as e:
    print(f"  tushare 5min failed: {e}")
