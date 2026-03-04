import requests
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

def check_html(race_id):
    url = f'https://race.netkeiba.com/odds/index.html?type=b7&race_id={race_id}&housiki=c99'
    res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    res.encoding = 'EUC-JP'
    html = res.text

    matches = re.findall(r'<td class="odds[^>]*>([^<]+)</td>', html)
    valid = [m.strip() for m in matches if m.strip() not in ['---.-', '-', '']]
    print(f'Race {race_id}: Found {len(valid)} actual odds values directly in HTML.')
    if valid:
        print('Sample value:', valid[0])

check_html('202408020310')
check_html('202507050501')
