#!/usr/bin/env python3
import sqlite3

DB = r"F:\日常项目\quant——project\data\db\market.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

c.execute("SELECT COUNT(DISTINCT code) FROM minute_kline")
print(f"minute_kline distinct codes: {c.fetchone()[0]}")

c.execute("SELECT COUNT(DISTINCT code) FROM stock_kline")
print(f"stock_kline distinct codes: {c.fetchone()[0]}")

c.execute("SELECT DISTINCT code FROM minute_kline WHERE code LIKE 'sh.6%' OR code LIKE 'sz.0%' OR code LIKE 'sz.3%'")
mk_codes = set(r[0] for r in c.fetchall())
print(f"minute_kline A-share codes: {len(mk_codes)}")

c.execute("SELECT DISTINCT code FROM stock_kline WHERE code LIKE 'sh.6%' OR code LIKE 'sz.0%' OR code LIKE 'sz.3%'")
sk_codes = set(r[0] for r in c.fetchall())
print(f"stock_kline A-share codes: {len(sk_codes)}")

all_codes = mk_codes | sk_codes
print(f"Total unique A-share codes: {len(all_codes)}")

sample = sorted(list(all_codes))[:10]
print(f"Sample codes: {sample}")

conn.close()
