# -*- coding: utf-8 -*-
"""Deep analysis of api_get_odds_ninki and db.netkeiba.com responses."""
import requests
from bs4 import BeautifulSoup
import re

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

race_id = "202610010101"

# === api_get_odds_ninki analysis ===
print("=" * 60)
print("api_get_odds_ninki analysis")
print("=" * 60)
url = f"https://race.netkeiba.com/api/api_get_odds_ninki.html?type=b7&race_id={race_id}"
h = {**headers, "X-Requested-With": "XMLHttpRequest",
     "Referer": f"https://race.netkeiba.com/odds/index.html?type=b7&race_id={race_id}"}
r = requests.get(url, headers=h, timeout=10)
content = r.content
# Try multiple encodings
for enc in ['utf-8', 'euc-jp', 'shift_jis']:
    try:
        text = content.decode(enc)
        print(f"  Encoding: {enc} (len={len(text)})")
        break
    except:
        continue

soup = BeautifulSoup(text, 'html.parser')

# Look for all elements with IDs
ids = [el.get('id') for el in soup.find_all(id=True)]
print(f"  Elements with IDs: {len(ids)}")
print(f"  Sample IDs: {ids[:20]}")

# Look for classes
classes = set()
for el in soup.find_all(class_=True):
    for c in el.get('class', []):
        classes.add(c)
print(f"  Unique classes: {sorted(classes)[:20]}")

# Look for table/tr structures
tables = soup.find_all('table')
print(f"  Tables: {len(tables)}")
trs = soup.find_all('tr')
print(f"  Rows: {len(trs)}")

# Print ALL content (it's only 21KB)
print(f"\n  --- Raw text (first 3000 chars) ---")
print(text[:3000])

# === db.netkeiba.com analysis ===
print("\n" + "=" * 60)
print("db.netkeiba.com analysis")
print("=" * 60)
url2 = f"https://db.netkeiba.com/race/{race_id}/"
r2 = requests.get(url2, headers=headers, timeout=10)
text2 = r2.content.decode('euc-jp', errors='ignore')
soup2 = BeautifulSoup(text2, 'html.parser')

# Look for odds-related content
odds_text = re.findall(r'3連複|三連複|sanrenpuku', text2, re.IGNORECASE)
print(f"  '3連複' mentions: {len(odds_text)}")

# Check for pay_block or result tables
pay_blocks = soup2.find_all(class_=re.compile(r'pay|odds|result', re.I))
print(f"  Pay/odds/result elements: {len(pay_blocks)}")
for pb in pay_blocks[:5]:
    print(f"    class={pb.get('class')}, tag={pb.name}, text={pb.get_text(strip=True)[:100]}")
