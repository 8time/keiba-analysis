"""
Debug v2: oikiri の実際のDOM要素を全て確認
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
        url = f"https://race.netkeiba.com/race/oikiri.html?race_id={race_id}"
        print(f"Fetching: {url}")

        # Wait for network idle to get JS-rendered content
        await page.goto(url, wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(2000)

        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')

        print(f"HTML length: {len(html)}")
        print(f"Title: {soup.title.string if soup.title else 'N/A'}")

        # All div classes present
        divs = soup.find_all('div', class_=True)
        div_classes = set()
        for d in divs:
            for c in d.get('class', []):
                div_classes.add(c)
        print(f"\nAll div classes ({len(div_classes)}):")
        for c in sorted(div_classes)[:50]:
            print(f"  {c}")

        # Tables
        tables = soup.find_all('table')
        print(f"\nTables: {len(tables)}")
        for i, t in enumerate(tables[:5]):
            print(f"  [{i}] class={t.get('class')}")
            rows = t.find_all('tr')
            for j, r in enumerate(rows[:3]):
                tds = r.find_all(['td','th'])
                print(f"    row[{j}]: {[td.get_text(strip=True)[:15] for td in tds]}")

        # Print first 2000 chars of body
        body = soup.find('body')
        if body:
            print(f"\n=== Body text (first 3000 chars) ===")
            print(body.get_text()[:3000])

        await browser.close()

if __name__ == '__main__':
    rid = sys.argv[1] if len(sys.argv) > 1 else '202503010801'
    asyncio.run(dump(rid))
