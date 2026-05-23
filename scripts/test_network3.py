#!/usr/bin/env python3
import baostock.common.contants as cons
print(f"BAOSTOCK_SERVER_IP = {cons.BAOSTOCK_SERVER_IP}")
print(f"BAOSTOCK_SERVER_PORT = {cons.BAOSTOCK_SERVER_PORT}")

import socket
print(f"\n=== Test TCP to {cons.BAOSTOCK_SERVER_IP}:{cons.BAOSTOCK_SERVER_PORT} ===")
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((cons.BAOSTOCK_SERVER_IP, cons.BAOSTOCK_SERVER_PORT))
    print(f"  TCP connect => OK")
    s.close()
except Exception as e:
    print(f"  TCP connect => FAIL: {e}")

print(f"\n=== Test HTTP to eastmoney (no SSL) ===")
try:
    import urllib.request
    url = "http://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.600519&fields1=f1&fields2=f51&klt=5&fqt=1&beg=20250519&end=20250520"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    print(f"  HTTP eastmoney => OK, status={resp.status}, len={len(resp.read())}")
except Exception as e:
    print(f"  HTTP eastmoney => FAIL: {e}")

print(f"\n=== Test HTTPS to eastmoney ===")
try:
    import urllib.request
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.600519&fields1=f1&fields2=f51&klt=5&fqt=1&beg=20250519&end=20250520"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    print(f"  HTTPS eastmoney => OK, status={resp.status}, len={len(resp.read())}")
except Exception as e:
    print(f"  HTTPS eastmoney => FAIL: {e}")

print(f"\n=== Test HTTP to baidu ===")
try:
    import urllib.request
    resp = urllib.request.urlopen("http://www.baidu.com", timeout=5)
    print(f"  HTTP baidu => OK, status={resp.status}")
except Exception as e:
    print(f"  HTTP baidu => FAIL: {e}")

print(f"\n=== Test HTTPS to baidu ===")
try:
    import urllib.request
    resp = urllib.request.urlopen("https://www.baidu.com", timeout=5)
    print(f"  HTTPS baidu => OK, status={resp.status}")
except Exception as e:
    print(f"  HTTPS baidu => FAIL: {e}")
