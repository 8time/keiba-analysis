import sys, io
sys.stdout.reconfigure(encoding='utf-8')
from bs4 import BeautifulSoup

html = open('c:/Users/kimnhaty/.gemini/antigravity/scratch/keiba_analysis/odds_form_dump.html', encoding='utf-8').read()
soup = BeautifulSoup(html, 'html.parser')

tables = soup.find_all('table')
print(f"Total tables: {len(tables)}")
for i, table in enumerate(tables):
    print(f"--- Table {i} ---")
    trs = table.find_all('tr')
    for tr in trs[:3]: # First 3 rows
        tds = tr.find_all(['td', 'th'])
        row_texts = [td.text.strip().replace('\n', '') for td in tds]
        print(f"  Row: {row_texts}")
    break
