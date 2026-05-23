#!/usr/bin/env python3
import time

print("=== Testing akshare 5min kline ===")
try:
    import akshare as ak
    df = ak.stock_zh_a_hist(
        symbol="600519",
        period="5",
        start_date="20250501",
        end_date="20250520",
        adjust="qfq",
    )
    print(f"  akshare 5min ok: {len(df)} rows")
    print(df.head(3))
    print(df.columns.tolist())
except Exception as e:
    print(f"  akshare stock_zh_a_hist failed: {e}")

print("\n=== Testing akshare stock list ===")
try:
    import akshare as ak
    df = ak.stock_info_a_code_name()
    print(f"  A-share stocks: {len(df)}")
    print(df.head(3))
except Exception as e:
    print(f"  stock_info_a_code_name failed: {e}")

print("\n=== Testing tushare ===")
try:
    import tushare as ts
    print(f"  tushare version: {ts.__version__}")
except ImportError:
    print("  tushare not installed")

print("\n=== Testing baostock TCP ===")
import socket
for port in [80, 8080, 8888, 9000]:
    s = socket.socket()
    s.settimeout(3)
    r = s.connect_ex(('baostock.com', port))
    print(f"  baostock.com:{port} => {'OK' if r==0 else f'FAIL({r})'}")
    s.close()
