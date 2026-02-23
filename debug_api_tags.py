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
        
        # Print all tags to see what we have
        all_tags = soup.find_all(True)
        print(f"Total tags: {len(all_tags)}")
        
        for i, tag in enumerate(all_tags[:50]):
            text = tag.get_text(strip=True)
            if len(text) > 0:
                print(f"Tag {i}: {tag.name}, class={tag.get('class')}, id={tag.get('id')}, text={text[:50]}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_api()
