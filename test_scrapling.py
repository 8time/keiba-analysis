import sys
sys.stdout.reconfigure(encoding='utf-8')

from scrapling import Fetcher

def main():
    print("Scraplingを起動し、example.com にアクセスしています...")
    
    fetcher = Fetcher()
    
    # SSL証明書エラーを回避
    response = fetcher.get("https://example.com", verify=False)
    
    title = response.css('title').text()
    heading = response.css('h1').text()
    
    print("\n=== スクレイピング成功！ ===")
    print(f"ページタイトル : {title}")
    print(f"見出し(h1)     : {heading}")

if __name__ == "__main__":
    main()