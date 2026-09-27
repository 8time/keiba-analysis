# -*- coding: utf-8 -*-
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

con = sqlite3.connect('data/jravan.db')
cur = con.cursor()
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print('TABLES:', tables)
for t in tables:
    cols = [c[1] for c in cur.execute(f'PRAGMA table_info({t})')]
    n = cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'\n== {t} ({n:,} rows) ==')
    print(cols)
