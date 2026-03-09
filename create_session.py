import asyncio
import os
import sys
from playwright.async_api import async_playwright

async def create_session(site="umanity"):
    """
    Launch browser to let user login to a site manually,
    then save the session.
    """
    if site == "umanity":
        url = "https://umanity.jp/login.php"
        session_path = "auth_session.json"
        site_name = "ウマニティ (Umanity)"
    elif site == "keibalab":
        url = "https://www.keibalab.jp/login/"
        session_path = "labo_session.json"
        site_name = "競馬ラボ (KeibaLab)"
    else:
        print(f"Unknown site: {site}")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        )
        page = await context.new_page()
        
        print(f"Opening {site_name}: {url}...")
        await page.goto(url)
        
        print(f"\n*** PLEASE LOGIN MANUALLY TO {site_name} IN THE OPENED BROWSER ***")
        print("Once logged in and race data is visible, the session will be saved automatically.")
        print("Close the browser window after you have successfully logged in.")
        
        # Wait until the user finishes (browser close)
        while True:
            try:
                if browser.is_connected():
                    await asyncio.sleep(1)
                else:
                    break
            except:
                break
                
        # Save storage state
        await context.storage_state(path=session_path)
        print(f"\nSession saved to {session_path}")
        await browser.close()

if __name__ == "__main__":
    import sys
    target = "umanity"
    if len(sys.argv) > 1:
        target = sys.argv[1].lower()
    
    try:
        asyncio.run(create_session(target))
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception as e:
        print(f"\nError: {e}")
