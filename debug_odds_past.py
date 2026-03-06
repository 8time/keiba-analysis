import requests
from bs4 import BeautifulSoup
import sys

sys.stdout.reconfigure(encoding='utf-8')

# fetch the main odds page for the past race
url = 'https://race.netkeiba.com/odds/index.html?type=b1&race_id=202610011006'
html = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).content.decode('euc-jp', errors='ignore')
soup = BeautifulSoup(html, 'html.parser')

tables = soup.find_all('table')
print(f"B1 Tab Tables: {len(tables)}")
for table in tables:
    for tr in table.find_all('tr')[:3]:
        tds = [td.text.strip().replace('\n', ' ') for td in tr.find_all(['td', 'th'])]
        print("B1 Row:", tds)
        
url_b7 = 'https://race.netkeiba.com/odds/index.html?type=b7&race_id=202610011006'
html_b7 = requests.get(url_b7, headers={'User-Agent': 'Mozilla/5.0'}).content.decode('euc-jp', errors='ignore')
soup_b7 = BeautifulSoup(html_b7, 'html.parser')
tables_b7 = soup_b7.find_all('table')
print(f"\nB7 Tab Tables: {len(tables_b7)}")
for table in tables_b7:
    for tr in table.find_all('tr')[:3]:
        tds = [td.text.strip().replace('\n', ' ') for td in tr.find_all(['td', 'th'])]
        print("B7 Row:", tds)
