import requests
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = 'https://race.netkeiba.com/odds/index.html?type=b7&race_id=202507050501&housiki=c99'
res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
res.encoding = 'EUC-JP'
html = res.text

print('HTML Len:', len(html))
print('Has RaceOdds_HorseList_Table?', 'RaceOdds_HorseList_Table' in html)

matches = re.findall(r'<td class="odds[^>]*>([^<]+)</td>', html)
valid = [m.strip() for m in matches if m.strip() not in ['---.-', '-', '']]
print(f'Found {len(valid)} actual odds values directly in HTML.')

if not valid:
    # try searching for embedded json string
    j_match = re.search(r'var\s+odds_list\s*=\s*(\{.*?\});', html)
    print('Found embedded json odds_list?', bool(j_match))
    
    # check if there is any JS redirect or error
    if 'class="btn_update"' in html:
        print('Update button found (normal odds page structure).')
