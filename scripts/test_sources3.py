#!/usr/bin/env python3
import requests
import json

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
}

print("=== Test eastmoney with full headers ===")
try:
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
    r = requests.get(url, params=params, headers=headers, timeout=15)
    print(f"  status={r.status_code}, len={len(r.text)}")
    data = r.json()
    klines = data.get("data", {}).get("klines", [])
    print(f"  klines count: {len(klines)}")
    if klines:
        print(f"  first: {klines[0]}")
        print(f"  last: {klines[-1]}")
except Exception as e:
    print(f"  FAIL: {e}")

print("\n=== Test eastmoney with HTTP (not HTTPS) ===")
try:
    url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": "1.600519",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": "5",
        "fqt": "1",
        "beg": "20250519",
        "end": "20250520",
    }
    r = requests.get(url, params=params, headers=headers, timeout=15)
    print(f"  status={r.status_code}, len={len(r.text)}")
    data = r.json()
    klines = data.get("data", {}).get("klines", [])
    print(f"  klines count: {len(klines)}")
    if klines:
        print(f"  first: {klines[0]}")
except Exception as e:
    print(f"  FAIL: {e}")

print("\n=== Test 163 money API ===")
try:
    url = "http://quotes.money.163.com/service/lsjhx.html"
    params = {
        "code": "1600519",
        "type": "5",
        "start": "20250519",
        "end": "20250520",
    }
    r = requests.get(url, params=params, headers=headers, timeout=15)
    print(f"  163 money: status={r.status_code}, len={len(r.text)}")
except Exception as e:
    print(f"  163 money FAIL: {e}")

print("\n=== Test sina finance API ===")
try:
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        "symbol": "sh600519",
        "scale": "5",
        "ma": "no",
        "datalen": "48",
    }
    r = requests.get(url, params=params, headers=headers, timeout=15)
    print(f"  sina: status={r.status_code}, len={len(r.text)}")
    if r.text:
        print(f"  first 200 chars: {r.text[:200]}")
except Exception as e:
    print(f"  sina FAIL: {e}")

print("\n=== Test Tencent finance API ===")
try:
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {
        "_var": "kline_dayqfq",
        "param": "sh600519,day,,,48,qfq",
    }
    r = requests.get(url, params=params, headers=headers, timeout=15)
    print(f"  tencent: status={r.status_code}, len={len(r.text)}")
    if r.text:
        print(f"  first 200 chars: {r.text[:200]}")
except Exception as e:
    print(f"  tencent FAIL: {e}")
