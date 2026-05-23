#!/usr/bin/env python3
import akshare as ak
import inspect

print("=== akshare version ===")
print(ak.__version__)

print("\n=== stock_zh_a_hist signature ===")
sig = inspect.signature(ak.stock_zh_a_hist)
print(sig)

print("\n=== Try different period values ===")
for period in ["5", "5min", "5m", "5minute"]:
    try:
        df = ak.stock_zh_a_hist(
            symbol="600519",
            period=period,
            start_date="20250519",
            end_date="20250520",
            adjust="qfq",
        )
        print(f"  period='{period}' => OK, {len(df)} rows")
        print(f"  columns: {df.columns.tolist()}")
        break
    except Exception as e:
        print(f"  period='{period}' => FAIL: {e}")

print("\n=== Try stock_zh_a_hist_min_em ===")
try:
    df = ak.stock_zh_a_hist_min_em(symbol="600519", period="5", adjust="qfq")
    print(f"  OK, {len(df)} rows")
    print(f"  columns: {df.columns.tolist()}")
    print(df.head(3))
except Exception as e:
    print(f"  FAIL: {e}")
