"""
Debug: oikiri ページの実際の HTML を確認するスクリプト
Usage: py scripts/debug/dump_oikiri.py <race_id>
"""
import sys, os, asyncio, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def dump(race_id):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()
        url = f"https://race.netkeiba.com/race/oikiri.html?race_id={race_id}"
        print(f"Fetching: {url}")
        await page.goto(url, wait_until='domcontentloaded', timeout=20000)
        try:
            await page.wait_for_selector('table', timeout=8000)
        except:
            pass

        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')

        print(f"\n=== Page title: {soup.title.string if soup.title else 'N/A'} ===\n")

        # Print all table class names found
        tables = soup.find_all('table')
        print(f"Tables found: {len(tables)}")
        for i, t in enumerate(tables):
            print(f"  Table[{i}] class={t.get('class')} id={t.get('id')}")

        # Print first 3 rows of each table
        for i, tbl in enumerate(tables[:3]):
            rows = tbl.find_all('tr')
            print(f"\n--- Table[{i}] rows={len(rows)} ---")
            for j, row in enumerate(rows[:5]):
                tds = row.find_all(['td', 'th'])
                cells = [td.get_text(strip=True)[:20] for td in tds]
                classes = [' '.join(td.get('class', [])) for td in tds]
                print(f"  Row[{j}]: {list(zip(cells, classes))}")

        # Also look for any element containing grade letters
        print("\n=== Elements with class containing Hyoka/Rank/Grade ===")
        for el in soup.find_all(class_=re.compile(r'hyoka|Hyoka|Rank|Grade|rank', re.I))[:10]:
            print(f"  tag={el.name} class={el.get('class')} text={el.get_text(strip=True)[:30]}")

        await browser.close()

if __name__ == '__main__':
    rid = sys.argv[1] if len(sys.argv) > 1 else '202503010801'
    asyncio.run(dump(rid))
