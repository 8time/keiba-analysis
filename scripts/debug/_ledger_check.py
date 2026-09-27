import sqlite3, json
from pathlib import Path
root = Path(__file__).resolve().parents[2]
p = root / 'data' / 'ledger.db'
if p.exists():
    c = sqlite3.connect(p)
    cur = c.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print('ledger tables:', tables)
    for t in tables:
        cur.execute(f'SELECT COUNT(*) FROM "{t}"')
        print(f'  {t}: {cur.fetchone()[0]} rows')
        cur.execute(f'PRAGMA table_info("{t}")')
        print('   cols:', [x[1] for x in cur.fetchall()])
    c.close()
else:
    print('ledger.db NOT FOUND')

d = json.load(open(root / 'data/retro_ledger.json', encoding='utf-8'))
print('retro len', len(d))
if d and isinstance(d[0], dict):
    print('retro[0] keys', list(d[0].keys()))
