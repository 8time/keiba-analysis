from bs4 import BeautifulSoup
import re

def analyze():
    with open('odds_c99_2024.html', 'rb') as f:
        content = f.read().decode('euc-jp', errors='ignore')
    soup = BeautifulSoup(content, 'html.parser')
    rows = soup.find_all('tr')
    for r in rows[:20]:
        cells = r.find_all('td')
        if len(cells) >= 3:
            # Combination Text
            # Netkeiba popularity list for 3-Ren-Puku sometimes looks like:
            # [Rank, Horse1, Horse2, Horse3, Odds, ...]
            txts = [c.get_text(strip=True) for c in cells]
            print(txts)

if __name__ == "__main__":
    analyze()
