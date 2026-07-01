# -*- coding: utf-8 -*-
"""nankankeiba.com race_id(16桁)のkaiji/day総当たり探索。

過去の任意日付について、大井(venue=20)のkaiji(開催回)/day(日目)の組み合わせを
ブルートフォースで特定し、NARバックテスト用の標本を過去に拡大する。
race_id構造: YYYYMMDD(8) + venue(2) + kaiji(2) + day(2) + race(2)
"""
import sys
import io
import re
import time
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HEADERS = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT = 10


def probe(date_str, venue, kaiji, day, race=1):
    rid = f"{date_str}{venue}{kaiji:02d}{day:02d}{race:02d}"
    url = f"https://www.nankankeiba.com/result/{rid}.do"
    try:
        r = requests.get(url, headers=HEADERS, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        html = r.content.decode("shift_jis", errors="replace")
        # 有効な結果ページかを簡易判定(着順テーブルの有無)
        if "着順" not in html and "nk23_c-table01__table" not in html:
            return None
        return rid
    except Exception:
        return None


def scan_date(date_str, venue=20, kaiji_range=range(1, 13), day_range=range(1, 9)):
    """指定日付についてkaiji/dayを総当たりし、有効なrace_idを1件でも見つけたら返す。"""
    for kaiji in kaiji_range:
        for day in day_range:
            rid = probe(date_str, venue, kaiji, day, race=1)
            if rid:
                return rid
    return None


if __name__ == "__main__":
    # 直近で判明済みの基準点: 2026-06-30 = venue20/kaiji05/day02, 2026-07-01 = day03
    # ここから過去に遡って、大井の別開催(kaiji04以前)を探索する候補日を試す。
    targets = [
        "20260601",  # 1ヶ月弱前
        "20260515",
        "20260501",
        "20260415",
        "20260401",
        "20260315",
        "20260301",
        "20260215",
        "20260201",
        "20260115",
        "20260101",
    ]
    found = {}
    t0 = time.time()
    for d in targets:
        rid = scan_date(d)
        elapsed = round(time.time() - t0, 1)
        print(f"[{elapsed}s] {d}: {'FOUND ' + rid if rid else 'no meeting'}")
        if rid:
            found[d] = rid

    print("\n=== 発見済み開催 ===")
    for d, rid in found.items():
        print(d, "->", rid)
