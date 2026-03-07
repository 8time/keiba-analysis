# -*- coding: utf-8 -*-
from bs4 import BeautifulSoup
import re

with open('odds_c99.html', 'rb') as f:
    content = f.read().decode('euc-jp', errors='ignore')

soup = BeautifulSoup(content, 'html.parser')
rows = soup.find_all('tr')
print(f"Total <tr>: {len(rows)}")

for i, row in enumerate(rows[:5]):
    cells = row.find_all('td')
    print(f"\n--- Row {i} ({len(cells)} cells) ---")
    for j, cell in enumerate(cells):
        attrs = dict(cell.attrs) if cell.attrs else {}
        spans = cell.find_all('span')
        span_ids = [s.get('id','') for s in spans if s.get('id')]
        text = cell.get_text(strip=True)
        print(f"  td[{j}]: text='{text}' attrs={attrs} span_ids={span_ids}")
