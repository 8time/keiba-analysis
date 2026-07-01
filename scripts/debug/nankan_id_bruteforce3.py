# -*- coding: utf-8 -*-
"""kaiji03(5/20=day03)とkaiji04(6/10=day03)の全日程を特定(レート制限付き)。"""
import sys
import io
import time
import requests
import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HEADERS = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT = 10


def probe(date_str, venue, kaiji, day, race=1):
    rid = f"{date_str}{venue}{kaiji:02d}{day:02d}{race:02d}"
    url = f"https://www.nankankeiba.com/result/{rid}.do"
    try:
        r = requests.get(url, headers=HEADERS, timeout=_TIMEOUT)
        time.sleep(0.6)
        if r.status_code != 200:
            return None
        html = r.content.decode("shift_jis", errors="replace")
        if "着順" not in html and "nk23_c-table01__table" not in html:
            return None
        return rid
    except Exception:
        time.sleep(0.6)
        return None


def find_meeting_extent(anchor_date, kaiji, anchor_day, venue=20, max_span=8):
    base = datetime.datetime.strptime(anchor_date, "%Y%m%d")
    found = {}
    for day in range(1, max_span + 1):
        delta = day - anchor_day
        d = base + datetime.timedelta(days=delta)
        d_str = d.strftime("%Y%m%d")
        rid = probe(d_str, venue, kaiji, day, race=1)
        if rid:
            found[day] = (d_str, rid)
    return found


if __name__ == "__main__":
    print("=== kaiji03(5/20=day03)の全日程 ===")
    ext3 = find_meeting_extent("20260520", 3, 3)
    for day, (d, rid) in sorted(ext3.items()):
        print(f"  day{day:02d}: {d} -> {rid}")

    print("\n=== kaiji04(6/10=day03)の全日程 ===")
    ext4 = find_meeting_extent("20260610", 4, 3)
    for day, (d, rid) in sorted(ext4.items()):
        print(f"  day{day:02d}: {d} -> {rid}")
