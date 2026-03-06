import scraper
import requests
from bs4 import BeautifulSoup
import re

date_str = "20260215"
print(f"Testing race list fetch for {date_str}...")

try:
    ids = scraper.get_race_ids_for_date(date_str)
    print(f"Found IDs: {ids}")
    
    # Manual check with headers (SUB URL)
    if not ids:
        # Try race_list_sub.html which is often used for AJAX content
        url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}"
        print(f"Manual check on {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest' # Often needed for AJAX endpoints
        }
        res = requests.get(url, headers=headers)
        res.encoding = 'EUC-JP'
        print(f"Status Code: {res.status_code}")
        print(f"Content length: {len(res.text)}")
        if "race_id=" in res.text:
            print("race_id string FOUND in raw text.")
            # simple regex check
            found = re.findall(r'race_id=(\d{12})', res.text)
            print(f"Found IDs: {len(set(found))}")
            print(list(set(found))[:5])
        else:
            print("race_id string NOT FOUND in raw text.")
            
except Exception as e:
    print(f"Error: {e}")
