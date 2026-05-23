#!/usr/bin/env python3
import sqlite3

DB = r"F:\日常项目\quant——project\data\db\market.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

print("=== minute_kline code prefix distribution ===")
c.execute("SELECT substr(code, 1, 3) as prefix, COUNT(DISTINCT code) as cnt FROM minute_kline GROUP BY prefix ORDER BY cnt DESC")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]} stocks")

print("\n=== stock_kline code prefix distribution ===")
c.execute("SELECT substr(code, 1, 3) as prefix, COUNT(DISTINCT code) as cnt FROM stock_kline GROUP BY prefix ORDER BY cnt DESC")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]} stocks")

print("\n=== minute_kline sample codes (non sh.6/sz.0/sz.3) ===")
c.execute("SELECT DISTINCT code FROM minute_kline WHERE code NOT LIKE 'sh.6%' AND code NOT LIKE 'sz.0%' AND code NOT LIKE 'sz.3%' LIMIT 20")
for r in c.fetchall():
    print(f"  {r[0]}")

print("\n=== stock_kline sample codes ===")
c.execute("SELECT DISTINCT code FROM stock_kline LIMIT 20")
for r in c.fetchall():
    print(f"  {r[0]}")

conn.close()
