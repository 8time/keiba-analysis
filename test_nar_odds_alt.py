import sys
sys.path.append('.')
import requests
from bs4 import BeautifulSoup
import scraper

# Test Keibalab
url_kl = "https://www.keibalab.jp/db/race/202645030711/"
res = requests.get(url_kl, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(res.content, 'html.parser')
print("Keibalab Tables:", len(soup.find_all('table')))

# Test Umanity (Requires different ID format, Umanity doesn't use Netkeiba's 12-digit standard easily for NAR)
print("Umanity Test Skipped for now, checking Oddspark...")

# Test Oddspark (Very good for NAR)
# Race ID needs translation, typically Oddspark uses YYYYMMDD + track code + race num
# 2026 45 0307 11 -> 2026/03/07, Track=45, Race=11
# Track 45 might be Saga. Let's assume we can hit Oddspark with a known date/track.
