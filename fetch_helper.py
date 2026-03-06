import sys
import io
import os
import time
from scrapling import DynamicFetcher

# Ensure UTF-8 output
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

def fetch_main(url):
    try:
        # Use a fresh fetcher every time
        fetcher = DynamicFetcher()
        # netkeiba sometimes needs a real user agent
        response = fetcher.fetch(
            url, 
            timeout=60000, 
            wait_until='networkidle' # Wait for network to be quiet
        )
        
        html = response.text
        if not html or len(html) < 100:
             # Try getting it from the body
             html = response.body.decode('utf-8', errors='replace')
        
        if html:
            sys.stdout.write(html)
            sys.stdout.flush()
        else:
            sys.stderr.write("FETCH_EMPTY: HTML was empty\n")
            sys.exit(1)
            
    except Exception as e:
        sys.stderr.write(f"FETCH_ERROR: {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        fetch_main(sys.argv[1])
