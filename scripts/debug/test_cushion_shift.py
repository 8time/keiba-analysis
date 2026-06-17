# -*- coding: utf-8 -*-
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from core.track_bias import cushion_day_shift, sire_cushion_flag, dirt_moisture_bloodtype

# Test 1: Find a date with a big shift at Tokyo (05)
import sqlite3
c = sqlite3.connect('data/jravan.db')
rows = c.execute("""
    SELECT year, monthday, cushion FROM track_cond
    WHERE jyo='05' AND cushion IS NOT NULL
    ORDER BY year||monthday DESC LIMIT 20
""").fetchall()
c.close()

print("=== Tokyo cushion history (recent) ===")
prev = None
for y, md, cv in reversed(rows):
    delta = f" (delta={cv-prev:+.1f})" if prev else ""
    print(f"  {y}/{md} cushion={cv}{delta}")
    prev = cv

# Test 2: test with known shifts
print("\n=== Shift tests ===")
for y, md, jyo, label in [
    ('2026', '0614', '05', '東京'),
    ('2026', '0613', '05', '東京'),
    ('2026', '0614', '06', '中山'),
]:
    s = cushion_day_shift(y, md, jyo)
    if s:
        print(f"{label} {y}/{md}: today={s['today']} prev={s['prev']} delta={s['delta']} shift={s['shift']} reliable={s['venue_reliable']}")
        for sire in ['ディープインパクト', 'キズナ', 'キタサンブラック', 'モーリス', 'レイデオロ']:
            f = sire_cushion_flag(sire, s)
            if f:
                print(f"  {f['flag']} {f['detail']}")
    else:
        print(f"{label} {y}/{md}: no data")

# Test 3: dirt moisture
print("\n=== Dirt moisture tests ===")
for sire, moist in [('ヘニーヒューズ', 2.0), ('フランケル', 2.0), ('ヘニーヒューズ', 10.0), ('フランケル', 10.0)]:
    d = dirt_moisture_bloodtype(sire, moist)
    if d:
        print(f"  {d['flag']} {d['detail']}")
