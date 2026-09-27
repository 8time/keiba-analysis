"""Query key DB schemas only."""
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[2]

for db_rel in ["data/odds_history.db", "data/jravan.db"]:
    db = root / db_rel
    print(f"\n=== {db_rel} ({db.stat().st_size if db.exists() else 0} bytes) ===")
    if not db.exists():
        print("NOT FOUND")
        continue
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    print("TABLE_COUNT:", len(tables))
    print("TABLES:", tables)
    for t in tables:
        cur.execute(f'PRAGMA table_info("{t}")')
        cols = cur.fetchall()
        cur.execute(f'SELECT COUNT(*) FROM "{t}"')
        cnt = cur.fetchone()[0]
        print(f"\n{t}: rows={cnt}")
        print("  cols:", [c[1] + ":" + c[2] for c in cols])
        date_names = [c[1] for c in cols if any(k in c[1].lower() for k in ["date", "time", "year", "month", "day", "race_date", "kdate"])]
        for dn in date_names[:2]:
            try:
                cur.execute(f'SELECT MIN("{dn}"), MAX("{dn}") FROM "{t}"')
                print(f"  {dn}:", cur.fetchone())
            except Exception as e:
                print(f"  {dn} err:", e)
    conn.close()

# export csv headers
for csv_rel in ["data/export/races.csv", "data/export/horse_races.csv"]:
    p = root / csv_rel
    if p.exists():
        with open(p, encoding="utf-8", errors="replace") as f:
            header = f.readline().strip()
        print(f"\n=== {csv_rel} header ===")
        print(header)
        # count lines quickly
        n = sum(1 for _ in open(p, encoding="utf-8", errors="replace")) - 1
        print("ROWS:", n)

# history json
hist = root / "data" / "history"
if hist.exists():
    js = list(hist.glob("*.json"))
    if js:
        import json
        print("\n=== data/history sample ===")
        print("FILES:", [x.name for x in js])
        with open(js[0], encoding="utf-8") as f:
            d = json.load(f)
        print("TOP_KEYS:", list(d.keys()))
