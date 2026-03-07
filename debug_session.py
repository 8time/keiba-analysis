import requests
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

race_id = '202608020211'
url = f'https://race.netkeiba.com/odds/index.html?type=b7&race_id={race_id}&housiki=c99'

session = requests.Session()
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}
session.headers.update(headers)
session.get('https://race.netkeiba.com/') # Get cookies
res = session.get(url)
res.encoding = res.apparent_encoding
html = res.text

with open('debug_past2.html', 'w', encoding='utf-8') as f:
    f.write(html)

matches = re.findall(r'<td class="odds[^>]*>([^<]+)</td>', html)
valid = [m.strip() for m in matches if m.strip() not in ['---.-', '-', '']]
print(f'Found {len(valid)} actual odds values with normal requests session')
if valid: print(valid[:5])
