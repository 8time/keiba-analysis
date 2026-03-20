"""
Debug v3: oikiri の raw HTML を確認 + 実際のレースIDで試す
"""
import sys, os, asyncio, re
from playwright.async_api import async_playwright

async def dump(race_id):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        )
        page = await context.new_page()
        url = f"https://race.netkeiba.com/race/oikiri.html?race_id={race_id}"
        print(f"Fetching: {url}")

        await page.goto(url, wait_until='domcontentloaded', timeout=20000)
        # Wait extra for any JS
        await page.wait_for_timeout(3000)

        html = await page.content()
        print(f"HTML length: {len(html)}")
        print(f"\n=== First 5000 chars of HTML ===")
        print(html[:5000])
        print(f"\n=== Looking for 'oikiri' or '調教' in HTML ===")
        if '調教' in html:
            # Find context around 調教
            idx = html.find('調教')
            print(html[max(0,idx-200):idx+500])
        else:
            print("No '調教' found in HTML")

        await browser.close()

if __name__ == '__main__':
    # Try a past race that likely has oikiri data
    rid = sys.argv[1] if len(sys.argv) > 1 else '202503010801'
    asyncio.run(dump(rid))
