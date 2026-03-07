import asyncio
import platform

if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from adv_fetch_helper import fetch_advanced_data

async def main():
    # Pass 2026030706020311 matching the screenshot
    # Netkeiba ID 12 digits: 2026 06 02 03 11
    res = await fetch_advanced_data('202606020311')
    print('Scrape Test Complete. Total Horses:', len(res))
    for umaban, data in res.items():
        if data.get('UIndex'):
            print(f'Umaban {umaban} (ID {data.get("HorseID")}): U-Index {data.get("UIndex")}')
        if data.get('LaboIndex'):
            print(f'Umaban {umaban}: Labo-Index {data.get("LaboIndex")}')

asyncio.run(main())
