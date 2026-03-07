from bs4 import BeautifulSoup
import re

def analyze_c99():
    with open('odds_c99.html', 'rb') as f:
        content = f.read().decode('euc-jp', errors='ignore')
    soup = BeautifulSoup(content, 'html.parser')
    rows = soup.find_all('tr')
    print(f"Total rows: {len(rows)}")
    for r in rows[:15]:
        cells = r.find_all('td')
        txts = [c.get_text(separator=' ', strip=True) for c in cells]
        print(txts)

if __name__ == "__main__":
    analyze_c99()
