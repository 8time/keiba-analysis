import os
import sys
import argparse
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from core import scraper
from bs4 import BeautifulSoup

def check():
    url = f"https://race.netkeiba.com/race/shutuba_past.html?race_id=202606020701"
    html = scraper.fetch_robust_html(url)
    soup = BeautifulSoup(html, 'html.parser')
    rows = soup.find_all('tr', class_='HorseList')
    for td in rows[0].find_all('td'):
        print(td.get('class', []), td.text.strip())

if __name__ == "__main__":
    check()
