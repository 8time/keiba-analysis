import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('playwright_fail.html', 'r', encoding='utf-8') as f:
    html = f.read()
    
# check what combos and odds look like 
matches = re.finditer(r'<tr id="ninki-data_.*?</tr>', html, re.DOTALL)
count = 0
for m in matches:
    row = m.group(0)
    print('ROW HTML:', row[:200])
    count += 1
    if count >= 2: break
