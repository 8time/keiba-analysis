import sys
import os
sys.path.append(os.getcwd())
import scraper
from bs4 import BeautifulSoup
import re

race_id = "202608020310"
url = f"https://race.netkeiba.com/odds/index.html?type=b7&race_id={race_id}&housiki=c99"
print(f"Fetching {url}")

html = scraper.fetch_html(url)
print(f"HTML Length: {len(html) if html else 0}")

soup = BeautifulSoup(html, 'html.parser')

# Find the odds table
table = soup.find('div', id='odds_list') or soup.find('table', class_='Odds_Table')
if not table:
    # Try finding any table containing 組合せ or オッズ
    tables = soup.find_all('table')
    for t in tables:
        if 'オッズ' in t.text and getattr(t.find('th'), 'text', '') == '人気':
            table = t
            break

if not table:
    print("Could not find Odds table. Here is some HTML from the page:")
    print(html[:2000])
else:
    print("Found Odds Table!")
    rows = table.find_all('tr')
    print(f"Found {len(rows)} rows.")
    for row in rows[:10]:
        print(row.text.strip().replace('\n', ' '))
