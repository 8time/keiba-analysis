import re
import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

with open('debug_netkeiba_2025.html', 'r', encoding='utf-8') as f:
    html = f.read()

# search for the common JSON parse pattern netkeiba uses
match = re.search(r'var\s+odds_list\s*=\s*(\{.*?\});', html)
if match:
    print('Found odds_list:', match.group(1)[:200])
else:
    print('No odds_list found')

# search for aOddsList or horse_list
match2 = re.search(r'var\s+aOddsList\s*=\s*(JSON\.parse\([^)]+\));', html)
if match2:
    print('Found JSON.parse for aOddsList')
else:
    # Extract any massive dictionary
    dicts = re.findall(r'(\w+)\s*=\s*(\{".*?\})\s*;', html)
    for name, content in dicts:
        if len(content) > 1000:
            print(f'Found large JSON dict: {name}')
            print(content[:200])
