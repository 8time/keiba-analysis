import sys
import io
from scrapling import DynamicFetcher

# Scrapling JRA Utility
import asyncio
if sys.platform == 'win32':
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass # Already set or not supported

def scrape_jra_top():
    url = "https://www.jra.go.jp/"
    fetcher = DynamicFetcher()
    
    try:
        response = fetcher.fetch(url)
        all_links = response.css('a')
        
        results = []
        for link in all_links:
            text = link.text.strip()
            href = link.attrib.get('href', '')
            
            # Target "出馬表" (Race List) links
            if "出馬表" in text:
                # Convert relative URL to absolute
                full_url = href if href.startswith('http') else "https://www.jra.go.jp" + href
                results.append({"text": f"🏇 {text}", "url": full_url})
            
        # If no race list found directly, include some menu links for context
        if not results:
            for link in all_links:
                text = link.text.strip()
                href = link.attrib.get('href', '')
                if "競馬メニュー" in text or "レース情報" in text:
                    full_url = href if href.startswith('http') else "https://www.jra.go.jp" + href
                    results.append({"text": f"📋 {text}", "url": full_url})
                    
        return results
    except Exception:
        err_msg = traceback.format_exc()
        return [{"text": "Error Detail", "url": err_msg}]

def scrape_race_list(url):
    """Fetch specific race list from a JRA subpage"""
    fetcher = DynamicFetcher()
    try:
        response = fetcher.fetch(url)
        # Look for venue names (e.g., 中山, 阪神) or race numbers
        items = response.css('div.venue, .race_new, a:contains("R")')
        results = []
        for item in items:
            text = item.text.strip()
            href = item.attrib.get('href', '')
            if text:
                results.append({"text": text, "url": href})
        return results
    except Exception as e:
        return [{"text": f"Error: {str(e)}", "url": ""}]

def scrape_netkeiba_race_list(date_str=None):
    """Fetch Netkeiba race list using Scrapling to prove it captures dynamic race names"""
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")
    
    url = f"https://race.netkeiba.com/top/race_list.html?kaisai_date={date_str}"
    fetcher = DynamicFetcher()
    
    try:
        response = fetcher.fetch(url)
        # Netkeiba handles race names in span.ItemTitle within RaceList_DataItem
        items = response.css('li.RaceList_DataItem')
        results = []
        for item in items:
            race_num = item.css('div.Race_Num').text.strip() if item.css('div.Race_Num') else ""
            race_name = item.css('span.ItemTitle').text.strip() if item.css('span.ItemTitle') else ""
            
            if race_num or race_name:
                results.append({
                    "R": race_num,
                    "レース名": race_name,
                    "検証": "✅ 取得成功" if race_name else "❌ 取得失敗"
                })
        return results
    except Exception as e:
        return [{"text": f"Error: {str(e)}", "url": ""}]

if __name__ == "__main__":
    from datetime import datetime
    # results = scrape_netkeiba_race_list()
    # links = scrape_jra_top()
    pass
