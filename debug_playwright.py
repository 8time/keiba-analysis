import asyncio
import re
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print('Navigating to Netkeiba...')
        
        # Go to the odds URL and wait for domcontentloaded instead of networkidle
        await page.goto('https://race.netkeiba.com/odds/index.html?type=b7&race_id=202507050501&housiki=c99', wait_until='domcontentloaded')
        
        # Wait a few seconds for JS to process the odds data
        print('Waiting 5 seconds for JS execution...')
        await page.wait_for_timeout(5000)
        
        # Grab the fully rendered HTML
        html = await page.content()
        await browser.close()
        
        # Analyze the result
        print('Rendered HTML length:', len(html))
        matches = re.findall(r'<td class="odds[^>]*>([^<]+)</td>', html)
        valid = [m.strip() for m in matches if m.strip() not in ['---.-', '-', '']]
        print(f'Found {len(valid)} actual odds values after JS execution.')
        if valid:
            print('Sample odds:', valid[:10])
            
            # extract some combos too to prove it
            combos = re.findall(r'<td class="name_combination[^>]*>([^<]+)</td>', html)
            print('Sample combos:', [c.strip() for c in combos[:10] if '-' in c])
        else:
            print('Still no odds found. Saving fallback html.')
            with open('playwright_fail.html', 'w', encoding='utf-8') as f:
                f.write(html)

asyncio.run(run())
