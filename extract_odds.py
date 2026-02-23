import sys
from bs4 import BeautifulSoup
import re

def extract_odds():
    try:
        with open('odds_api.html', 'rb') as f:
            content = f.read()
        
        try:
            html = content.decode('euc-jp')
        except:
            html = content.decode('utf-8', errors='replace')
            
        soup = BeautifulSoup(html, 'html.parser')
        
        # Look for table rows
        rows = soup.find_all('tr')
        results = []
        
        for row in rows:
            cells = row.find_all('td')
            if len(cells) >= 3:
                txts = [c.get_text(strip=True) for c in cells]
                # Combination pattern: "1 - 2 - 3"
                comb = txts[1]
                odds = txts[2]
                
                # Clean combination
                nums = re.findall(r'\d+', comb)
                if len(nums) == 3:
                    try:
                        odds_val = float(odds)
                        results.append((nums, odds_val))
                    except:
                        pass
        
        print(f"Extracted {len(results)} combinations.")
        for res in results[:10]:
            print(f"Combination: {'-'.join(res[0])}, Odds: {res[1]}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    extract_odds()
