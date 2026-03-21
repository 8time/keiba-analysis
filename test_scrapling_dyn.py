from scrapling import DynamicFetcher
import sys

def test():
    print("Scrapling DynamicFetcher START")
    try:
        # Note: v0.4.x may have changed configure/init arguments.
        # Let's try basic fetching which defaults to headless in Scrapling usually.
        fetcher = DynamicFetcher()
        print("Fetching... (timeout 25s)")
        # In v0.4: DynamicFetcher.fetch(url, timeout=ms, headless=True)
        page = fetcher.fetch("https://www.google.com", timeout=25000)
        print("OK. Body length:", len(page.body) if page else 0)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("FAILED:", e, file=sys.stderr)
    print("Scrapling DynamicFetcher END")

if __name__ == "__main__":
    test()
