"""
Check if race result page has exposed Time Index values.
"""
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

import scraper
import re
from bs4 import BeautifulSoup

# A finished race from Joe's history
race_url = "https://db.netkeiba.com/race/202506050211/"
print(f"Fetching: {race_url}")

html = scraper.fetch_html(race_url)
soup = BeautifulSoup(html, 'html.parser')

table = soup.find('table', class_='race_table_01')
if not table:
    print("No result table found!")
    sys.exit(1)

headers = [th.text.strip() for th in table.find_all('th')]
print(f"Headers: {headers[:15]}")

# Find Time Index column
ti_col = -1
for i, h in enumerate(headers):
    if '指数' in h and 'ﾀｲﾑ' in h:
        ti_col = i
        print(f"Time Index at col {i}")
        break

rows = table.find_all('tr')[1:]
print(f"\nFound {len(rows)} rows")
print(f"{'Rank':<5} {'Horse':<15} {'TimeIdx':<10} {'Agari':<8} {'Pass':<10}")
print("-" * 50)

for row in rows[:10]:
    tds = row.find_all('td')
    if len(tds) < 12: continue
    
    rank = tds[0].text.strip()
    horse = tds[3].text.strip()[:12]
    
    ti_val = tds[ti_col].text.strip() if ti_col >= 0 and len(tds) > ti_col else "-"
    agari = tds[11].text.strip() if len(tds) > 11 else "-"
    passing = tds[10].text.strip() if len(tds) > 10 else "-"
    
    print(f"{rank:<5} {horse:<15} {ti_val:<10} {agari:<8} {passing:<10}")
