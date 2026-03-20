"""
Debug v4: AJAX待ち + OikiriAllWrapper 内部構造確認
"""
import sys, os, asyncio, re
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def dump(race_id):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        # Capture network requests
        ajax_urls = []
        page.on("request", lambda req: ajax_urls.append(req.url) if 'oikiri' in req.url.lower() or 'training' in req.url.lower() or 'ajax' in req.url.lower() or '.json' in req.url.lower() else None)

        url = f"https://race.netkeiba.com/race/oikiri.html?race_id={race_id}"
        print(f"Fetching: {url}")

        await page.goto(url, wait_until='domcontentloaded', timeout=20000)
        # Wait up to 8s for any horse-like element
        try:
            await page.wait_for_selector('.OikiriHorse, .HorseList, [class*="Oikiri"], tr', timeout=8000)
        except:
            pass
        await page.wait_for_timeout(4000)  # Extra wait for AJAX

        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser', from_encoding='utf-8')

        print(f"HTML length: {len(html)}")
        print(f"\nAJAX-related URLs captured: {ajax_urls[:10]}")

        # All class names in page
        all_classes = set()
        for el in soup.find_all(class_=True):
            for c in el.get('class', []):
                all_classes.add(c)
        oikiri_classes = [c for c in sorted(all_classes) if 'oikiri' in c.lower() or 'Oikiri' in c]
        print(f"\nOikiri-related classes: {oikiri_classes}")

        # OikiriAllWrapper contents
        wrapper = soup.find(class_='OikiriAllWrapper')
        if wrapper:
            print(f"\n=== OikiriAllWrapper HTML (first 3000) ===")
            print(str(wrapper)[:3000])
        else:
            print("OikiriAllWrapper not found")

        # Tables
        tables = soup.find_all('table')
        print(f"\nTables: {len(tables)}")
        for i, t in enumerate(tables[:3]):
            print(f"  [{i}] class={t.get('class')}")
            for j, r in enumerate(t.find_all('tr')[:3]):
                print(f"    {[td.get_text(strip=True)[:20] for td in r.find_all(['td','th'])]}")

        await browser.close()

if __name__ == '__main__':
    rid = sys.argv[1] if len(sys.argv) > 1 else '202503010801'
    asyncio.run(dump(rid))
