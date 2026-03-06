import sys, io
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass
import pandas as pd
import scraper

rid = "202610010811"
print(f"Fetching {rid}...")
df = scraper.get_race_data(rid)

targets = ['ジョーメッドヴィン', 'アスクワンタイム']

for i, row in df.iterrows():
    if row['Name'] in targets:
        print(f"\n🐴 Name: {row['Name']}")
        print(f"Current Dist: {row.get('CurrentDistance')}")
        past = row.get('PastRuns', [])
        print(f"Past Runs Found: {len(past)}")
        for r in past:
            print(f" - Date: {r.get('Date')}, Dist: {r.get('Distance')}, Agari: {r.get('Agari')} ({r.get('AgariType')}), Pos: {r.get('Passing')} ({r.get('PassingType')})")
            # print raw text if possible? No, scraper returns struct.
