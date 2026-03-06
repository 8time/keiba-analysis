import bs4
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('playwright_fail.html', 'r', encoding='utf-8') as f:
    html = f.read()

soup = bs4.BeautifulSoup(html, 'html.parser')
tbl = soup.find('table', class_='RaceOdds_HorseList_Table')
if tbl:
    rows = tbl.find_all('tr')[2:4] # Skip headers
    for i, r in enumerate(rows):
        print(f'-- ROW {i} --')
        for j, c in enumerate(r.find_all('td')):
            print(f'TD {j}: "{c.text.strip()}"')
else:
    print('No target table found')
