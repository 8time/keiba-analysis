import asyncio
import os
import sys
import json
from playwright.async_api import async_playwright

# Ensure the paths are absolute relative to the script's directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

async def create_session(site="umanity"):
    """
    Launch browser to let user login to a site manually,
    then save the session.
    """
    if site == "umanity":
        url = "https://umanity.jp/login.php"
        session_path = os.path.join(BASE_DIR, "auth_session.json")
        site_name = "ウマニティ (Umanity)"
    elif site == "keibalab":
        # Re-verify the most reliable login URL
        url = "https://www.keibalab.jp/login/login.html"
        session_path = os.path.join(BASE_DIR, "labo_session.json")
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
        print("Once logged in, the session will be saved automatically.")
        print("You can close the browser window after you have successfully logged in.")
        
        # Wait loop with auto-save detection
        login_detected = False
        try:
            while True:
                if not browser.is_connected():
                    break
                
                # Check for successful login by URL change + title check (Avoid saving on 404)
                current_url = page.url
                try:
                    title = await page.title()
                except:
                    title = ""
                
                is_error_page = "404" in title or "Not Found" in title or "エラー" in title or "error" in current_url.lower()
                
                if not is_error_page:
                    if site == "keibalab" and ("/login" not in current_url and "keibalab.jp" in current_url):
                        if not login_detected:
                            print("\n[INFO] Login detected (KeibaLab)! Saving session...")
                            await context.storage_state(path=session_path)
                            login_detected = True
                            print("Closing in 3 seconds...")
                            await asyncio.sleep(3)
                            break
                    
                    if site == "umanity" and ("/login.php" not in current_url and "umanity.jp" in current_url):
                        if not login_detected:
                            print("\n[INFO] Login detected (Umanity)! Saving session...")
                            await context.storage_state(path=session_path)
                            login_detected = True
                            print("Closing in 3 seconds...")
                            await asyncio.sleep(3)
                            break

                await asyncio.sleep(2)
        except Exception as e:
            print(f"Watch loop error: {e}")
                
        # Final save on exit just in case
        try:
            await context.storage_state(path=session_path)
            print(f"\n[SUCCESS] Session saved to {session_path}")
        except Exception as e:
            print(f"Failed to save session: {e}")
            
        await browser.close()

if __name__ == "__main__":
    target = "umanity"
    if len(sys.argv) > 1:
        target = sys.argv[1].lower()
    
    try:
        asyncio.run(create_session(target))
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception as e:
        print(f"\nError: {e}")
