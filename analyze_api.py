import sys
from bs4 import BeautifulSoup
import re

def analyze_api():
    try:
        with open('odds_api.html', 'rb') as f:
            content = f.read()
        
        try:
            html = content.decode('euc-jp')
        except:
            html = content.decode('utf-8', errors='replace')
            
        soup = BeautifulSoup(html, 'html.parser')
        
        # In API response, it might be a list of <li> or a simple table
        # Let's search for rows that look like: Popularity, Combination, Odds
        rows = soup.find_all(['tr', 'li'])
        print(f"Found {len(rows)} potential rows.")
        
        for i, row in enumerate(rows[:20]):
            text = row.get_text(separator=' ', strip=True)
            # Look for patterns like "1 1-2-3 10.5"
            print(f"Row {i}: {text}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    analyze_api()
