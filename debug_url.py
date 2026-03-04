import requests
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = 'https://race.netkeiba.com/odds/index.html?type=b7&race_id=202608020211&housiki=c99'
headers = {"User-Agent": "Mozilla/5.0"}

res = requests.get(url, headers=headers)
res.encoding = res.apparent_encoding # Use apparent encoding as suggested
html = res.text

print('Status:', res.status_code)
print('Total len:', len(html))
print('Has RaceOdds_HorseList_Table?', 'RaceOdds_HorseList_Table' in html)
print('Has Ninki?', 'Ninki' in html)

# dump first 500 chars to see what we got
print("HTML HEAD:")
print(html[:500])

# check if any actual odds floating point number format is present
matches = re.findall(r'<td class="odds[^>]*>([^<]+)</td>', html)
print(f"Found {len(matches)} td elements with odds-like classes")

valid_odds = []
for m in matches:
    text = m.strip()
    if text != '---.-' and text and text != '-':
        valid_odds.append(text)

print(f"Found {len(valid_odds)} actual (non-empty) odds values")
if valid_odds:
    print(valid_odds[:10])
