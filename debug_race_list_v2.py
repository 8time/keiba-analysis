import scraper
import requests
from bs4 import BeautifulSoup
import re

date_str = "20260215"
print(f"Testing Race List Fetch for {date_str}...")

# 1. Test get_race_ids_for_date
try:
    rids = scraper.get_race_ids_for_date(date_str)
    print(f"Race IDs Found: {len(rids)}")
    print(rids)
except Exception as e:
    print(f"Error in get_race_ids_for_date: {e}")

# 2. Inspect Raw HTML if empty
url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}"
print(f"Fetching URL: {url}")
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}
try:
    response = requests.get(url, headers=headers)
    response.encoding = 'EUC-JP'
    html = response.text
    print(f"HTML Length: {len(html)}")
    
    # Check for specific elements
    soup = BeautifulSoup(html, 'html.parser')
    race_list_data = soup.find_all('li', class_='RaceList_DataItem')
    print(f"RaceList_DataItem count: {len(race_list_data)}")
    
    if len(html) < 500:
        print("HTML Content (Short):")
        print(html)
        
except Exception as e:
    print(f"Request failed: {e}")

# Dump snippet
print("Snippet of HTML:")
print(html[:500])
