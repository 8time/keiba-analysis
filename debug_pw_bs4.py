import bs4
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('playwright_fail.html', 'r', encoding='utf-8') as f:
    html = f.read()

soup = bs4.BeautifulSoup(html, 'html.parser')
tables = soup.find_all('table')

valid = 0
for tbl in tables:
    for row in tbl.find_all('tr'):
        cols = row.find_all('td')
        if len(cols) >= 4:
            rank = cols[0].text.strip()
            combo = cols[2].text.strip().replace('\n', '')
            odds = cols[3].text.strip()
            
            if rank.isdigit() and '-' in combo and odds and '---' not in odds:
                if valid < 3:
                    print(f'Rank: {rank}, Combo: {combo}, Odds: {odds}')
                valid += 1

print(f'Found {valid} valid odds rows using BeautifulSoup on Playwright HTML.')
