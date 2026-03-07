import asyncio
import scraper
import sys
import os
import json

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

async def diagnose_uindex(race_id):
    print(f"--- Diagnosing U-Index for Race: {race_id} ---")
    
    # Check session file
    session_path = "auth_session.json"
    if os.path.exists(session_path):
        print(f"✅ Session file found: {session_path}")
        try:
            with open(session_path, 'r') as f:
                state = json.load(f)
                print(f"   Cookies count: {len(state.get('cookies', []))}")
        except Exception as e:
            print(f"   ❌ Error reading session file: {e}")
    else:
        print("❌ Session file NOT found.")

    # Mock top_horse_ids (assuming 1-18)
    top_horse_ids = list(range(1, 19))
    
    print("\nRunning Playwright Scraper...")
    adv_data = scraper.fetch_advanced_data_playwright(race_id, top_horse_ids)
    
    print("\nExtraction Results (UIndex):")
    found_any = False
    for umaban, data in adv_data.items():
        u_val = data.get('UIndex')
        l_val = data.get('LaboIndex')
        if u_val is not None:
            found_any = True
            print(f"   Horse {umaban:2}: UIndex={u_val}, LaboIndex={l_val}")
    
    if not found_any:
        print("   ❌ No U-Index data extracted for any horse.")

if __name__ == "__main__":
    # Use a recent race ID or the one from user if known. 
    # The screenshot shows Big Caesar, which is likely a recent race.
    # I'll use a placeholder or try to extract from app state if I could.
    # For now, let's use the default ID or ask user, but I'll try with 202603010611 (example)
    # Actually, I'll check the most recent Analyze calls in logs if any.
    race_id = "202606020111" # Ocean Stakes 2026
    
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(diagnose_uindex(race_id))
