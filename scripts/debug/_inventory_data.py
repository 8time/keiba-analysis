"""Temporary data inventory script."""
import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[2]

print("=== DATA FILES (csv/json/db/parquet) ===")
exts = {".csv", ".json", ".db", ".parquet"}
files = []
for p in root.rglob("*"):
    if p.is_file() and p.suffix.lower() in exts:
        if any(x in p.parts for x in [".git", "__pycache__", ".venv", "node_modules"]):
            continue
        try:
            sz = p.stat().st_size
        except OSError:
            continue
        files.append((str(p.resolve()), sz))
files.sort(key=lambda x: x[1], reverse=True)
for fp, sz in files:
    print(f"{sz:>12}  {fp}")

print("\n=== race_history.csv ===")
rh = root / "race_history.csv"
if rh.exists():
    with open(rh, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    print("COLUMNS:", header)
    print("COL_COUNT:", len(header))
    print("ROW_COUNT:", len(rows))
    date_cols = [
        i
        for i, c in enumerate(header)
        if any(k in c.lower() for k in ["date", "日", "開催", "race_date", "年月日", "kdate"])
    ]
    print("DATE_COLS:", [(header[i], i) for i in date_cols])
    dates = []
    for r in rows:
        for i in date_cols:
            if i < len(r) and r[i].strip():
                dates.append(r[i].strip())
                break
    if dates:
        print("DATE_RANGE:", min(dates), "to", max(dates))
    if rows:
        print("SAMPLE_ROW_0:", rows[0][: min(10, len(rows[0]))])
    if "RaceID" in header:
        idx = header.index("RaceID")
        c = Counter(r[idx] for r in rows if len(r) > idx)
        print("UNIQUE_RACEIDS:", len(c))
        if c:
            print("ROWS_PER_RACE_MINMAX:", min(c.values()), max(c.values()))
else:
    print("NOT FOUND")

print("\n=== data/ directory ===")
data = root / "data"
if data.exists():
    cnt = 0
    for p in sorted(data.rglob("*")):
        if p.is_file():
            cnt += 1
            print(f"{p.stat().st_size:>12}  {p.resolve()}")
    print("FILE_COUNT:", cnt)
else:
    print("data/ NOT FOUND")

print("\n=== data/history/ ===")
hist = root / "data" / "history"
if hist.exists():
    jsons = list(hist.glob("**/*.json"))
    print("JSON_COUNT:", len(jsons))
    if jsons:
        names = sorted(p.name for p in jsons)
        print("NAME_SAMPLES:", names[:8], "...", names[-3:])
        with open(jsons[0], encoding="utf-8") as f:
            d = json.load(f)

        def show_keys(obj, depth=0, max_depth=3):
            if depth > max_depth:
                return "..."
            if isinstance(obj, dict):
                return {k: show_keys(v, depth + 1, max_depth) for k in list(obj.keys())[:20]}
            if isinstance(obj, list):
                if not obj:
                    return []
                return [show_keys(obj[0], depth + 1, max_depth), f"...(len={len(obj)})"]
            return type(obj).__name__

        print("FIRST_FILE:", jsons[0].resolve())
        print("STRUCTURE:", json.dumps(show_keys(d), ensure_ascii=False)[:2500])
else:
    print("DIR NOT FOUND")

for db_rel in ["data/odds_history.db", "jravan.db", "data/jravan.db"]:
    db = root / db_rel
    print(f"\n=== {db_rel} ===")
    if not db.exists():
        print("NOT FOUND")
        continue
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    print("TABLES:", tables[:30], ("..." if len(tables) > 30 else ""))
    print("TABLE_COUNT:", len(tables))
    for t in tables[:15]:
        cur.execute(f'PRAGMA table_info("{t}")')
        cols = cur.fetchall()
        print(f"\nTABLE {t}:")
        for c in cols:
            print(f"  {c[1]} {c[2]}")
        cur.execute(f'SELECT COUNT(*) FROM "{t}"')
        print(f"  ROW_COUNT: {cur.fetchone()[0]}")
        date_names = [
            c[1]
            for c in cols
            if any(k in c[1].lower() for k in ["date", "time", "ts", "created", "recorded", "at", "year"])
        ]
        for dn in date_names[:2]:
            try:
                cur.execute(f'SELECT MIN("{dn}"), MAX("{dn}") FROM "{t}"')
                print(f"  {dn}_RANGE:", cur.fetchone())
            except Exception as e:
                print(f"  {dn}_RANGE_ERR:", e)
    conn.close()
