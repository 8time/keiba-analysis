# -*- coding: utf-8 -*-
"""発見済み開催(kaiji01@4/15, kaiji02@5/1)の前後日程を特定しつつ、
未発見のkaiji03/04(5月中旬〜6月下旬の間)を探索する第2段。"""
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
        time.sleep(0.5)  # IPブロック回避のためリクエスト間隔を空ける
        if r.status_code != 200:
            return None
        html = r.content.decode("shift_jis", errors="replace")
        if "着順" not in html and "nk23_c-table01__table" not in html:
            return None
        return rid
    except Exception:
        time.sleep(0.5)
        return None


def find_meeting_extent(anchor_date, kaiji, anchor_day, venue=20, max_span=8):
    """既知アンカー(anchor_date=YYYYMMDD, その日のday=anchor_day)から、
    同一kaiji内の全dayに対応する日付をdayを前後にずらして特定する。"""
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


def scan_gap(dates, venue=20, kaiji_range=range(3, 5), day_range=range(1, 9)):
    found = {}
    for d in dates:
        for kaiji in kaiji_range:
            for day in day_range:
                rid = probe(d, venue, kaiji, day, race=1)
                if rid:
                    found[d] = rid
                    break
            if d in found:
                break
    return found


if __name__ == "__main__":
    t0 = time.time()
    print("=== kaiji01(4/15=day03)の全日程 ===")
    ext1 = find_meeting_extent("20260415", 1, 3)
    for day, (d, rid) in sorted(ext1.items()):
        print(f"  day{day:02d}: {d} -> {rid}")
    print(f"[{time.time()-t0:.1f}s]")

    print("\n=== kaiji02(5/1=day05)の全日程 ===")
    ext2 = find_meeting_extent("20260501", 2, 5)
    for day, (d, rid) in sorted(ext2.items()):
        print(f"  day{day:02d}: {d} -> {rid}")
    print(f"[{time.time()-t0:.1f}s]")

    print("\n=== kaiji03/04探索(5月中旬〜6月下旬の隙間) ===")
    gap_dates = ["20260505", "20260510", "20260520", "20260525",
                 "20260605", "20260610", "20260615", "20260620", "20260625"]
    gap_found = scan_gap(gap_dates)
    for d, rid in gap_found.items():
        print(f"  {d} -> {rid}")
    print(f"[{time.time()-t0:.1f}s] total")
