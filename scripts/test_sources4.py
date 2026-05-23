#!/usr/bin/env python3
import requests
import json

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}

print("=== Test sina 5min with large datalen ===")
for datalen in [48, 240, 480, 960, 2400, 4800]:
    try:
        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {
            "symbol": "sh600519",
            "scale": "5",
            "ma": "no",
            "datalen": str(datalen),
        }
        r = requests.get(url, params=params, headers=headers, timeout=15)
        data = json.loads(r.text)
        print(f"  datalen={datalen} => got {len(data)} rows, first={data[0]['day']}, last={data[-1]['day']}")
    except Exception as e:
        print(f"  datalen={datalen} => FAIL: {e}")

print("\n=== Test tencent 5min kline ===")
try:
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {
        "_var": "kline_5qfq",
        "param": "sh600519,m5,,,320,qfq",
    }
    r = requests.get(url, params=params, headers=headers, timeout=15)
    print(f"  tencent m5: status={r.status_code}, len={len(r.text)}")
    text = r.text
    if text.startswith("kline_5qfq="):
        text = text[len("kline_5qfq="):]
    data = json.loads(text)
    qfq = data.get("data", {}).get("sh600519", {}).get("m5", [])
    print(f"  got {len(qfq)} rows")
    if qfq:
        print(f"  first: {qfq[0]}")
        print(f"  last: {qfq[-1]}")
except Exception as e:
    print(f"  tencent m5 FAIL: {e}")

print("\n=== Test tencent 5min with more data ===")
try:
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {
        "_var": "kline_5qfq",
        "param": "sh600519,m5,,,640,qfq",
    }
    r = requests.get(url, params=params, headers=headers, timeout=15)
    text = r.text
    if text.startswith("kline_5qfq="):
        text = text[len("kline_5qfq="):]
    data = json.loads(text)
    qfq = data.get("data", {}).get("sh600519", {}).get("m5", [])
    print(f"  tencent m5 640: got {len(qfq)} rows")
    if qfq:
        print(f"  first: {qfq[0]}")
        print(f"  last: {qfq[-1]}")
except Exception as e:
    print(f"  tencent m5 640 FAIL: {e}")
