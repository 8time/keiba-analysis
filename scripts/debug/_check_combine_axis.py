# -*- coding: utf-8 -*-
"""combine_axis の単体テスト"""
import sys

sys.path.insert(0, r"C:\Users\kimnhaty\.gemini\antigravity\scratch\keiba_analysis")
from core import fav_check as fk


def fake(verdict):
    return {"verdict": verdict,
            "emoji": {"buy": "🟢", "caution": "🟡", "avoid": "🔴"}[verdict],
            "headline": "x", "fuku": 60.0, "items": [], "note": "n"}


# 両方🟢 + 重複3 → 🟢
r = fk.combine_axis([fake("buy"), fake("buy")],
                    race_ctx={"overlap": 3, "label": "🎯勝負向き", "fav_top3": 76})
assert r["verdict"] == "buy" and r["headline"] == "軸2頭とも信頼できます", r
# 片方🟡 → 🟡
r = fk.combine_axis([fake("buy"), fake("caution")], race_ctx={"overlap": 2})
assert r["verdict"] == "caution" and not r["capped_by_race"], r
# 片方🔴 → 🔴
r = fk.combine_axis([fake("avoid"), fake("buy")], race_ctx={"overlap": 2})
assert r["verdict"] == "avoid", r
# 両方🟢でも重複0 → 🟡 capped
r = fk.combine_axis([fake("buy"), fake("buy")], race_ctx={"overlap": 0})
assert r["verdict"] == "caution" and r["capped_by_race"], r
assert r["headline"] == "レースとして軸が立ちにくい組み合わせです", r
# 1件のみ
r = fk.combine_axis([fake("buy")], race_ctx={"overlap": 2})
assert r["headline"] == "軸にできます", r
# 空・race_ctx なし
r = fk.combine_axis([], race_ctx=None)
assert r["verdict"] == "caution", r
print("combine_axis: all 6 cases OK")
