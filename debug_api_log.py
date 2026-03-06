import sys
from bs4 import BeautifulSoup

def debug_api():
    try:
        with open('odds_api.html', 'rb') as f:
            content = f.read()
        
        try:
            html = content.decode('euc-jp')
        except:
            html = content.decode('utf-8', errors='replace')
            
        soup = BeautifulSoup(html, 'html.parser')
        
        with open('api_debug.log', 'w', encoding='utf-8') as log:
            log.write("DEBUG API STRUCTURE\n")
            # Look for <li> which is common in ninki view
            items = soup.find_all(['li', 'tr'])
            log.write(f"Found {len(items)} items.\n")
            
            for i, item in enumerate(items):
                log.write(f"Item {i}: tag={item.name}, class={item.get('class')}, id={item.get('id')}\n")
                log.write(f"  Content: {item.get_text(separator=' ', strip=True)}\n")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_api()
