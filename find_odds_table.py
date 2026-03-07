import sys
from bs4 import BeautifulSoup

def find_table():
    try:
        with open('odds_test.html', 'rb') as f:
            content = f.read()
        
        # Try EUC-JP first
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
            
            # Print first few rows to see content
            rows = table.find_all('tr')[:3]
            for j, row in enumerate(rows):
                print(f"  Row {j}: {row.get_text(strip=True)[:100]}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    find_table()
