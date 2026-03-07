import sys, io
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass
import pandas as pd
import numpy as np
import scraper
from calculator import calculate_ogura_index, STANDARD_TIMES, DEFAULT_STD

rid = "202610010811"
print(f"Fetching {rid}...")
df = scraper.get_race_data(rid)

target = 'ジョーメッドヴィン'
row = df[df['Name'] == target].iloc[0]

print(f"\n🐴 Analysis for {target}")
past = row.get('PastRuns', [])
print(f"Runs Found: {len(past)}")

scores = []
print(f"\n{'Date':<12} {'Dist':<6} {'Time':<8} {'Std':<6} {'Cond':<6} {'Weight':<6} {'RawScore':<8}")
for run in past:
    t = run.get('Time', 0)
    d = run.get('Distance', 0)
    w = run.get('Weight', 55.0)
    cond = run.get('Condition', '良')
    surf = run.get('Surface', '芝')
    
    # Calc
    ref_times = STANDARD_TIMES.get('芝', DEFAULT_STD)
    std = ref_times.get(d, 0)
    
    baba = 0
    if '稍' in cond: baba = 10
    elif '重' in cond: baba = 20
    elif '不' in cond: baba = 30
    
    raw = (std - t) * 10 + baba + (w - 55)*2 + 50
    scores.append(raw)
    
    print(f"{run.get('Date', '-'):<12} {d:<6} {t:<8.1f} {std:<6.1f} {cond:<6} {w:<6} {raw:<8.1f}")

if scores:
    print(f"\nRaw Mean: {np.mean(scores):.1f}")
    q75, q25 = np.percentile(scores, [75, 25])
    iqr = q75 - q25
    lb = q25 - 1.5 * iqr
    ub = q75 + 1.5 * iqr
    valid = [s for s in scores if lb <= s <= ub]
    print(f"IQR Mean: {np.mean(valid):.1f} (Excluded: {len(scores)-len(valid)})")
else:
    print("No scores.")
