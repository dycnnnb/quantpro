#!/usr/bin/env python3
import requests
import json
import time

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}

print("=== Test sina 5min max datalen ===")
for datalen in [4800, 6000, 8000, 10000, 12000, 15000, 20000, 30000]:
    try:
        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {
            "symbol": "sh600519",
            "scale": "5",
            "ma": "no",
            "datalen": str(datalen),
        }
        r = requests.get(url, params=params, headers=headers, timeout=30)
        data = json.loads(r.text)
        print(f"  datalen={datalen} => got {len(data)} rows, first={data[0]['day']}, last={data[-1]['day']}")
    except Exception as e:
        print(f"  datalen={datalen} => FAIL: {str(e)[:100]}")
    time.sleep(0.5)

print("\n=== Test sina stock list ===")
try:
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    params = {
        "page": "1",
        "num": "80",
        "sort": "symbol",
        "asc": "1",
        "node": "hs_a",
        "symbol": "",
        "_s_r_a": "page",
    }
    r = requests.get(url, params=params, headers=headers, timeout=15)
    data = json.loads(r.text)
    print(f"  Page 1: {len(data)} stocks")
    if data:
        print(f"  First: {data[0]}")
except Exception as e:
    print(f"  Stock list FAIL: {e}")

print("\n=== Get total A-share count from sina ===")
try:
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeDataCount"
    params = {"node": "hs_a"}
    r = requests.get(url, params=params, headers=headers, timeout=15)
    print(f"  Count: {r.text}")
except Exception as e:
    print(f"  Count FAIL: {e}")
