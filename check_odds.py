from bs4 import BeautifulSoup
import re

def check():
    with open('odds_api.html', 'rb') as f:
        content = f.read().decode('euc-jp', errors='ignore')
    soup = BeautifulSoup(content, 'html.parser')
    rows = soup.find_all('tr')
    print(f"Total rows: {len(rows)}")
    for r in rows[:15]:
        cells = r.find_all('td')
        txts = [c.get_text(strip=True) for c in cells]
        print(txts)

if __name__ == "__main__":
    check()
