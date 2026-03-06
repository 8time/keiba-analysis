# -*- coding: utf-8 -*-
"""Test SP (mobile) Netkeiba odds pages."""
import requests
from bs4 import BeautifulSoup
import re

# SP mobile pages often have server-rendered odds
race_id = "202610010101"  # Today Kokura 1R (finished)

headers = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
}

# Try SP odds page
urls = [
    f"https://race.sp.netkeiba.com/?pid=odds_view&type=b7&race_id={race_id}&housiki=ninki",
    f"https://race.sp.netkeiba.com/?pid=odds_view&type=b7&race_id={race_id}",
    f"https://sp.netkeiba.com/odds/index.html?type=b7&race_id={race_id}",
]

for url in urls:
    print(f"\n{'='*60}")
    print(f"URL: {url}")
    try:
        r = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        print(f"Status: {r.status_code}, Length: {len(r.content)}, Final URL: {r.url}")
        
        text = r.content.decode('utf-8', errors='ignore')
        soup = BeautifulSoup(text, 'html.parser')
        
        # Look for odds data in the HTML
        # Check for combination patterns like "1-2-3" or numbers
        combos = re.findall(r'(\d{1,2})\s*[-ー]\s*(\d{1,2})\s*[-ー]\s*(\d{1,2})', text)
        print(f"  Combinations found: {len(combos)}, first: {combos[:5] if combos else 'none'}")
        
        # Look for odds values like "12.3"
        odds_vals = re.findall(r'(\d+\.\d+)倍', text)
        print(f"  Odds values found: {len(odds_vals)}, first: {odds_vals[:5] if odds_vals else 'none'}")
        
        # Check page title
        title = soup.find('title')
        print(f"  Title: {title.text.strip() if title else 'none'}")
        
    except Exception as e:
        print(f"  Error: {e}")

# Also try the old-style netkeiba odds page
print(f"\n{'='*60}")
print("Old-style netkeiba.com odds")
url_old = f"https://www.netkeiba.com/?pid=odds&id=c{race_id}&type=b7"
try:
    r = requests.get(url_old, headers={"User-Agent": "Mozilla/5.0"}, timeout=10, allow_redirects=True)
    print(f"Status: {r.status_code}, Length: {len(r.content)}, Final URL: {r.url}")
    text = r.content.decode('euc-jp', errors='ignore')
    combos = re.findall(r'(\d+)\s*[-ー]\s*(\d+)\s*[-ー]\s*(\d+)', text)
    print(f"  Combinations found: {len(combos)}")
except Exception as e:
    print(f"  Error: {e}")
