import sqlite3

for db_name, db_path in [
    ('quantpro', r'f:\日常项目\quant——project\data\db\quantpro.db'),
    ('market', r'f:\日常项目\quant——project\data\db\market.db'),
]:
    print(f"\n=== {db_name}.db ===")
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        tables = [t[0] for t in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        for t in tables:
            if 'news' in t.lower():
                n = cur.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
                print(f"  {t}: {n:,} rows")
                if n > 0 and n < 50:
                    cols = [c[1] for c in cur.execute(f"PRAGMA table_info([{t}])").fetchall()]
                    print(f"    columns: {cols}")
                    samples = cur.execute(f"SELECT * FROM [{t}] LIMIT 3").fetchall()
                    for s in samples:
                        print(f"    {s[:5]}...")
        conn.close()
    except Exception as e:
        print(f"  ERROR: {e}")
