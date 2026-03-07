import sys
from bs4 import BeautifulSoup

def analyze_success_2():
    try:
        with open('odds_success_2.html', 'rb') as f:
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
            
            # Print first 5 rows to see content
            rows = table.find_all('tr')[:5]
            for j, row in enumerate(rows):
                # Check for row text
                print(f"  Row {j}: {row.get_text(strip=True)[:100]}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    analyze_success_2()
