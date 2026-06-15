# -*- coding: utf-8 -*-
"""消去フィルター刷新の3前提を検証(test=2023-2025・JRA平地)。
 ① 半分消去の取りこぼし: 人気ランクで下位半分を消すと勝ち馬/3着内を何%失うか(recall下限)
 ② 穴救出: 人気薄(ninki>=8)のうち検証済み+ファクター(黄金ライン/厩舎当コース)を持つ馬の単勝ROI・残差
 ③ 危険人気馬: 人気上位(ninki<=3)のうち検証済み-ファクター(牝冬春/大幅距離変更/初ダート/前走フロック)を持つ馬の残差・ROI

train(〜2022)で黄金ライン(騎手×調教師top2率)・厩舎当コース勝率を構築しleak回避。
"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

con = sqlite3.connect(jj.JV_DB_PATH)
cur = con.cursor()
exp = jj.calibrate_odds_expectation(db_path=jj.JV_DB_PATH)


def e3(o):
    e = exp.get(jj._odds_band(o)); return e['top3'] if e else 0.22


def e1(o):
    e = exp.get(jj._odds_band(o)); return e['win'] if e else 0.08


BASE = ("FROM results r JOIN races ra ON r.race_key=ra.race_key "
        "WHERE r.chakujun>0 AND r.ketto_num!='' AND ra.surface IN ('芝','ダート') "
        "AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10")

print("train(〜2022)で黄金ライン・厩舎当コース構築...")
golden = defaultdict(lambda: [0, 0])    # (jockey,tc) -> [runs, top2]
tcourse = defaultdict(lambda: [0, 0])   # (tc,jyo,surf) -> [runs, wins]
for jky, tc, jyo, surf, chaku in cur.execute(
        f"SELECT r.jockey_name, r.trainer_code, ra.jyo, ra.surface, r.chakujun {BASE} "
        f"AND ra.year<'2023' AND r.trainer_code!='00000'"):
    g = golden[(jky, tc)]; g[0] += 1; g[1] += (1 if chaku <= 2 else 0)
    t = tcourse[(tc, jyo, surf)]; t[0] += 1; t[1] += (1 if chaku == 1 else 0)
print(f"  黄金ペア:{len(golden)} 厩舎コース:{len(tcourse)}")

# 性別(results.sex)で十分。chronological stateは test前の履歴で作る
last_dist = {}; dirt_runs = defaultdict(int); last_ninki = {}; last_chaku = {}

# ① recall
w_tot = w_bot = t3_tot = t3_bot = 0
# ②③ buckets: [top3残差, win残差, 単勝払戻合計, n]
b2 = defaultdict(lambda: [0.0, 0.0, 0.0, 0])
b3 = defaultdict(lambda: [0.0, 0.0, 0.0, 0])

print("時系列スキャン...")
rows = cur.execute(
    "SELECT r.race_key, r.ketto_num, r.jockey_name, r.trainer_code, r.chakujun, r.win_odds, "
    "       r.ninki, r.sex, ra.year, ra.monthday, ra.jyo, ra.surface, ra.kyori, ra.shusso_tosu "
    f"{BASE} ORDER BY r.race_key").fetchall()
print(f"  {len(rows)}行")

GOLD_TH, GOLD_N = 0.40, 10
TC_TH, TC_N = 0.20, 10
for (rk, ketto, jky, tc, chaku, o, ninki, sex, year, md, jyo, surf, kyori, tousu) in rows:
    if year >= '2023' and o and o > 0 and ninki:
        r3 = (1 if chaku <= 3 else 0) - e3(o)
        rw = (1 if chaku == 1 else 0) - e1(o)
        payout = o if chaku == 1 else 0.0
        try:
            mo = int(str(md)[:2])
        except Exception:
            mo = 0
        # ① recall(人気で下位半分を消した時の取りこぼし)
        if tousu and ninki * 2 > tousu:   # 下位半分(人気薄側)
            if chaku == 1:
                w_bot += 1
            if chaku <= 3:
                t3_bot += 1
        if chaku == 1:
            w_tot += 1
        if chaku <= 3:
            t3_tot += 1

        # +ファクター(検証済み)
        g = golden.get((jky, tc)); gold_ok = g and g[0] >= GOLD_N and g[1] / g[0] >= GOLD_TH
        tcv = tcourse.get((tc, jyo, surf)); tc_ok = tcv and tcv[0] >= TC_N and tcv[1] / tcv[0] >= TC_TH
        pos = bool(gold_ok or tc_ok)
        # -ファクター(検証済み)
        fade = sex == '2' and mo in (12, 1, 2, 3, 4, 5)
        pd_ = last_dist.get(ketto)
        distchg = pd_ and kyori and abs(kyori - pd_) >= 400
        hatsu_dirt = surf == 'ダート' and dirt_runs[ketto] == 0
        pn, pc = last_ninki.get(ketto), last_chaku.get(ketto)
        fluke = (pn is not None and pc is not None and pn >= 6 and pc <= 3)
        neg = bool(fade or distchg or hatsu_dirt or fluke)

        # ② 穴(人気薄ゾーン)
        if ninki >= 8:
            key = '＋ファクター有' if pos else '＋ファクター無'
            d = b2[key]; d[0] += r3; d[1] += rw; d[2] += payout; d[3] += 1
        # ③ 危険人気馬(人気上位ゾーン)
        if ninki <= 3:
            key = '−ファクター有(危険)' if neg else '−ファクター無'
            d = b3[key]; d[0] += r3; d[1] += rw; d[2] += payout; d[3] += 1

    # state更新
    if kyori:
        last_dist[ketto] = kyori
    if surf == 'ダート':
        dirt_runs[ketto] += 1
    last_ninki[ketto] = ninki
    last_chaku[ketto] = chaku
con.close()


def se_z(s3, n):
    if not n:
        return 0.0
    se = (0.22 * 0.78 / n) ** 0.5
    return (s3 / n) / se if se else 0.0


print("\n================ ① 半分消去(人気ランク下位半分)の取りこぼし ================")
print(f"  勝ち馬 総数{w_tot} / うち下位半分{w_bot} = 取りこぼし {w_bot/max(w_tot,1):.1%}")
print(f"  3着内 総数{t3_tot} / うち下位半分{t3_bot} = 取りこぼし {t3_bot/max(t3_tot,1):.1%}")
print("  →市場(人気)で半分消すとこれだけ勝ち馬を失う。②の穴救出で取り返す対象。")


def show(title, bucket, order):
    print(f"\n================ {title} ================")
    print("  区分                   |   n    | 3着内残差 | (z)   | 勝利残差 | 単勝回収率")
    for k in order:
        if k not in bucket:
            continue
        s3, sw, pay, n = bucket[k]
        if n:
            print(f"  {k:21s} | {n:6d} | {s3/n:+.4f} | {se_z(s3,n):+.2f} | {sw/n:+.4f} | {pay/n:6.1%}")


show("② 穴救出: 人気薄(≥8番人気)×検証+ファクター", b2, ['＋ファクター有', '＋ファクター無'])
show("③ 危険人気馬: 人気上位(≤3番人気)×検証−ファクター", b3, ['−ファクター有(危険)', '−ファクター無'])
print("\n②は＋有が残差/回収率で勝れば穴救出ルール有効。③は−有が残差で有意に低ければ危険検知有効。")
