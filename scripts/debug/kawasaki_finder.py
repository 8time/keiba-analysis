# -*- coding: utf-8 -*-
"""川崎(venue=21)の開催日程を効率的に特定する。

戦略: nankankeiba.comのカレンダーページから川崎の開催日を取得し、
各開催のkaiji/dayを逆算する。カレンダーが取れなければアンカー方式で
前後に走査する。
"""
import sys
import io
import time
import requests
import datetime
import re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HEADERS = {"User-Agent": "Mozilla/5.0"}
VENUE = 21
_TIMEOUT = 10


def probe(date_str, kaiji, day, race=1):
    rid = f"{date_str}{VENUE}{kaiji:02d}{day:02d}{race:02d}"
    url = f"https://www.nankankeiba.com/result/{rid}.do"
    try:
        r = requests.get(url, headers=HEADERS, timeout=_TIMEOUT)
        time.sleep(0.4)
        if r.status_code != 200:
            return None
        html = r.content.decode("shift_jis", errors="replace")
        if "着順" not in html and "nk23_c-table01__table" not in html:
            return None
        return rid
    except Exception:
        time.sleep(0.4)
        return None


def find_meeting_days(anchor_date, kaiji, anchor_day, max_span=8):
    """アンカー日からkaiji内の全dayを探す。"""
    base = datetime.datetime.strptime(anchor_date, "%Y%m%d")
    found = {}
    for day in range(1, max_span + 1):
        delta = day - anchor_day
        d = base + datetime.timedelta(days=delta)
        d_str = d.strftime("%Y%m%d")
        rid = probe(d_str, kaiji, day)
        if rid:
            found[day] = d_str
    return found


def find_next_kaiji_anchor(last_date, last_kaiji, max_gap=30):
    """最後の開催日からmax_gap日先まで次のkaijiの1日目を探す。"""
    base = datetime.datetime.strptime(last_date, "%Y%m%d")
    new_kaiji = last_kaiji + 1
    for offset in range(3, max_gap + 1):
        d = base + datetime.timedelta(days=offset)
        d_str = d.strftime("%Y%m%d")
        rid = probe(d_str, new_kaiji, 1)
        if rid:
            return d_str, new_kaiji
    return None, None


if __name__ == "__main__":
    print("=== 川崎(venue=21) 開催日程探索 ===\n")

    # アンカー: kaiji01/day01 = 2026-04-06 (先行プローブで確認済み)
    meetings = []
    current_kaiji = 1
    anchor_date = "20260406"
    anchor_day = 1

    while current_kaiji <= 10:
        print(f"--- kaiji{current_kaiji:02d} (anchor: {anchor_date}/day{anchor_day}) ---")
        days = find_meeting_days(anchor_date, current_kaiji, anchor_day)

        if not days:
            print(f"  kaiji{current_kaiji}: NOT FOUND")
            break

        last_date = None
        for day in sorted(days):
            print(f"  day{day:02d}: {days[day]}")
            meetings.append((days[day], current_kaiji, day))
            last_date = days[day]

        # 次のkaijiを探す
        next_date, next_kaiji = find_next_kaiji_anchor(last_date, current_kaiji)
        if next_date is None:
            print(f"\n  kaiji{current_kaiji + 1}のアンカー見つからず。探索終了。")
            break
        current_kaiji = next_kaiji
        anchor_date = next_date
        anchor_day = 1
        print()

    print(f"\n=== 発見した川崎開催: {len(meetings)}日分 ===")
    print("_KAWASAKI_MEETINGS = [")
    prev_kaiji = None
    for date_str, kaiji, day in meetings:
        if kaiji != prev_kaiji:
            print(f"    # kaiji{kaiji:02d}")
            prev_kaiji = kaiji
        print(f'    ("{date_str}", {kaiji}, {day}),')
    print("]")
