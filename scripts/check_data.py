#!/usr/bin/env python3
import sqlite3

DB = r"F:\日常项目\quant——project\data\db\market.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM minute_kline")
total = c.fetchone()[0]
print(f"Total rows: {total:,}")

c.execute("SELECT COUNT(DISTINCT code) FROM minute_kline")
codes = c.fetchone()[0]
print(f"Distinct codes: {codes}")

c.execute("SELECT MIN(date), MAX(date) FROM minute_kline")
dr = c.fetchone()
print(f"Date range: {dr[0]} ~ {dr[1]}")

c.execute("SELECT code, COUNT(*) as cnt FROM minute_kline GROUP BY code ORDER BY cnt ASC LIMIT 5")
print("Min rows per stock:")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]}")

c.execute("SELECT code, COUNT(*) as cnt FROM minute_kline GROUP BY code ORDER BY cnt DESC LIMIT 5")
print("Max rows per stock:")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]}")

c.execute("SELECT date, COUNT(*) as cnt FROM minute_kline GROUP BY date ORDER BY date DESC LIMIT 10")
print("Latest dates:")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]}")

c.execute("SELECT AVG(cnt) FROM (SELECT code, COUNT(*) as cnt FROM minute_kline GROUP BY code)")
avg = c.fetchone()[0]
print(f"Avg rows per stock: {avg:.0f}")

c.execute("SELECT COUNT(DISTINCT code) FROM minute_kline WHERE (SELECT COUNT(*) FROM minute_kline m WHERE m.code=minute_kline.code) < 10")
sparse = c.fetchone()[0]
print(f"Stocks with <10 rows: {sparse}")

conn.close()
