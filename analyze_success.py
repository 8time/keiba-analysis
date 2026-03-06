import sys
from bs4 import BeautifulSoup

def analyze_success():
    try:
        with open('odds_success_1.html', 'rb') as f:
            content = f.read()
        
        try:
            html = content.decode('euc-jp')
        except:
            html = content.decode('utf-8', errors='replace')
            
        soup = BeautifulSoup(html, 'html.parser')
        
        # Search for tables
        tables = soup.find_all('table')
        print(f"Found {len(tables)} tables.")
        
        for i, table in enumerate(tables):
            cls = table.get('class', [])
            id = table.get('id', '')
            print(f"Table {i}: class={cls}, id={id}")
            
            # Print first 10 rows to see content
            rows = table.find_all('tr')[:10]
            for j, row in enumerate(rows):
                # Look for horse numbers and odds
                # Popularity table usually has: Rank, Combination (e.g. 1-2-10), Odds
                cells = row.find_all('td')
                cell_texts = [c.get_text(strip=True) for c in cells]
                print(f"  Row {j}: {cell_texts}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    analyze_success()
