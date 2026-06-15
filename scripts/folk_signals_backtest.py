# -*- coding: utf-8 -*-
"""競馬俗説5案を一括検証(test=2023-2025・JRA平地)。
results を race_key昇順で時系列スキャンし、各馬の「当該レースより前」の履歴のみで特徴量を作る(リーク防止)。
オッズ補正残差(実績 − オッズ別期待)で層別。残差>0=人気以上に来る=妙味。

 ①初ブリ大穴combo: 初ブリ × 前走大敗(前走10着以下) × 人気薄(8番人気以下)
 ②大幅距離短縮:    前走比の距離差バケット
 ③コース適性お帰り: 今回開催場での過去複勝率が高い馬の「戻り」
 ④性×季節バイアス: 牡/牝/セ × 春夏秋冬
 ⑤初ダート:        芝→初ダート。5項目(外枠/体重460+/牝馬限定/母ダート実績/兄弟ダート実績)で採点
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
pcur = con.cursor()   # 血統(母/兄弟)照会用
exp = jj.calibrate_odds_expectation(db_path=jj.JV_DB_PATH)


def e3(o):
    e = exp.get(jj._odds_band(o))
    return e['top3'] if e else 0.22


def e1(o):
    e = exp.get(jj._odds_band(o))
    return e['win'] if e else 0.08


def se_z(s3, n):
    if not n:
        return 0.0
    se = (0.22 * 0.78 / n) ** 0.5
    return (s3 / n) / se if se else 0.0


# 牝馬限定戦(全出走馬が牝=sex'2')の race_key 集合
print("牝馬限定戦 抽出...")
filly_only = set(r[0] for r in cur.execute(
    "SELECT race_key FROM results GROUP BY race_key "
    "HAVING SUM(CASE WHEN sex='2' THEN 0 ELSE 1 END)=0 AND COUNT(*)>=5"))
print(f"  牝馬限定: {len(filly_only)}R")

# 母名→そのダート好走(<=5着)有無 / 兄弟(同母)ダート好走有無 のキャッシュ
_dam_dirt = {}
_sib_dirt = {}


def dam_dirt_ok(dam_name, before_key):
    if not dam_name:
        return False
    key = (dam_name, before_key[:6])
    if key in _dam_dirt:
        return _dam_dirt[key]
    row = pcur.execute(
        "SELECT 1 FROM results r JOIN races ra ON r.race_key=ra.race_key "
        "JOIN horses h ON r.ketto_num=h.ketto_num "
        "WHERE h.bamei=? AND ra.surface='ダート' AND r.chakujun BETWEEN 1 AND 5 "
        "AND r.race_key<? LIMIT 1", (dam_name, before_key)).fetchone()
    _dam_dirt[key] = bool(row)
    return _dam_dirt[key]


def sib_dirt_ok(dam_name, self_ketto, before_key):
    if not dam_name:
        return False
    row = pcur.execute(
        "SELECT 1 FROM results r JOIN races ra ON r.race_key=ra.race_key "
        "JOIN horses h ON r.ketto_num=h.ketto_num "
        "WHERE h.dam=? AND r.ketto_num!=? AND ra.surface='ダート' "
        "AND r.chakujun BETWEEN 1 AND 5 AND r.race_key<? LIMIT 1",
        (dam_name, self_ketto, before_key)).fetchone()
    return bool(row)


# horses: ketto -> dam 事前ロード(血統用。sexはhorses未投入のためresults.sexを使う)
print("horses ロード...")
horse_dam = {r[0]: r[1] for r in cur.execute("SELECT ketto_num, dam FROM horses")}

# 状態(各馬の「これまで」)
last_dist = {}        # ketto -> 前走距離
dirt_runs = defaultdict(int)
blinker_prior = defaultdict(int)
last_chaku = {}
venue_rec = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # ketto -> jyo -> [runs, top3]

b1 = defaultdict(lambda: [0.0, 0.0, 0])   # 初ブリcombo
b2 = defaultdict(lambda: [0.0, 0.0, 0])   # 距離短縮
b3 = defaultdict(lambda: [0.0, 0.0, 0])   # お帰り
b4 = defaultdict(lambda: [0.0, 0.0, 0])   # 性×季節
b5 = defaultdict(lambda: [0.0, 0.0, 0])   # 初ダート score
b5h = defaultdict(lambda: [0.0, 0.0, 0])  # 初ダート score>=3 × 人気薄

SEX = {'1': '牡', '2': '牝', '3': 'セ'}
SEASON = {12: '冬', 1: '冬', 2: '冬', 3: '春', 4: '春', 5: '春',
          6: '夏', 7: '夏', 8: '夏', 9: '秋', 10: '秋', 11: '秋'}

print("時系列スキャン...")
rows = cur.execute(
    "SELECT r.race_key, r.ketto_num, r.blinker, r.chakujun, r.win_odds, r.ninki, "
    "       r.bataiju, r.umaban, r.waku, r.sex, ra.year, ra.monthday, ra.jyo, ra.surface, ra.kyori "
    "FROM results r JOIN races ra ON r.race_key=ra.race_key "
    "WHERE r.chakujun>0 AND r.ketto_num!='' AND ra.surface IN ('芝','ダート') "
    "AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10 "
    "ORDER BY r.race_key").fetchall()
print(f"  {len(rows)}行")

n_test = 0
for (rk, ketto, bl, chaku, o, ninki, bataiju, umaban, waku, sex,
     year, md, jyo, surf, kyori) in rows:
    bl = 1 if str(bl) == '1' else 0
    is_test = (year >= '2023') and o and o > 0
    if is_test:
        n_test += 1
        r3 = (1 if chaku <= 3 else 0) - e3(o)
        rw = (1 if chaku == 1 else 0) - e1(o)
        dam = horse_dam.get(ketto, '')

        # ① 初ブリ大穴combo
        if bl == 1 and blinker_prior[ketto] == 0:
            lc = last_chaku.get(ketto)
            taihai = lc is not None and lc >= 10
            ninki_usu = ninki and ninki >= 8
            if taihai and ninki_usu:
                b1['初ブリ×前走大敗×人気薄'][0] += r3; b1['初ブリ×前走大敗×人気薄'][1] += rw; b1['初ブリ×前走大敗×人気薄'][2] += 1
            b1['初ブリ(全体)'][0] += r3; b1['初ブリ(全体)'][1] += rw; b1['初ブリ(全体)'][2] += 1

        # ② 距離短縮
        pd_ = last_dist.get(ketto)
        if pd_ and kyori:
            d = kyori - pd_
            lab = ('大幅短縮(≤-400)' if d <= -400 else '短縮(-399〜-100)' if d <= -100
                   else '同距離(±99)' if d < 100 else '延長(100〜399)' if d < 400 else '大幅延長(≥400)')
            b2[lab][0] += r3; b2[lab][1] += rw; b2[lab][2] += 1

        # ③ お帰り(当場の過去複勝率)
        vr = venue_rec[ketto][jyo]
        if vr[0] >= 3:
            rate = vr[1] / vr[0]
            lab = ('得意≥50%' if rate >= 0.5 else '良34-49%' if rate >= 0.34
                   else '並20-33%' if rate >= 0.20 else '苦手<20%')
            b3[lab][0] += r3; b3[lab][1] += rw; b3[lab][2] += 1

        # ④ 性×季節
        try:
            mo = int(str(md)[:2])
        except Exception:
            mo = 0
        sslab = f"{SEX.get(str(sex), '?')}×{SEASON.get(mo, '?')}"
        b4[sslab][0] += r3; b4[sslab][1] += rw; b4[sslab][2] += 1

        # ⑤ 初ダート
        if surf == 'ダート' and dirt_runs[ketto] == 0:
            score = 0
            if waku and waku >= 6:
                score += 1
            if bataiju and bataiju >= 460:
                score += 1
            if rk in filly_only:
                score += 1
            if dam_dirt_ok(dam, rk):
                score += 1
            if sib_dirt_ok(dam, ketto, rk):
                score += 1
            b5[f"score{score}"][0] += r3; b5[f"score{score}"][1] += rw; b5[f"score{score}"][2] += 1
            if score >= 3 and ninki and ninki >= 6:
                b5h['score≥3×人気薄'][0] += r3; b5h['score≥3×人気薄'][1] += rw; b5h['score≥3×人気薄'][2] += 1
            b5h['初ダート(全体)'][0] += r3; b5h['初ダート(全体)'][1] += rw; b5h['初ダート(全体)'][2] += 1

    # ---- 状態更新(当該レース後) ----
    if kyori:
        last_dist[ketto] = kyori
    if surf == 'ダート':
        dirt_runs[ketto] += 1
    if bl == 1:
        blinker_prior[ketto] += 1
    last_chaku[ketto] = chaku
    vr = venue_rec[ketto][jyo]
    vr[0] += 1
    if chaku <= 3:
        vr[1] += 1
con.close()


def show(title, bucket, order=None):
    print(f"\n==== {title} ====")
    print("  区分                  |   n    | 3着内残差 | (z)   | 勝利残差")
    keys = order or sorted(bucket, key=lambda k: -bucket[k][2])
    for k in keys:
        if k not in bucket:
            continue
        s3, sw, n = bucket[k]
        if n:
            print(f"  {k:20s} | {n:6d} | {s3/n:+.4f} | {se_z(s3,n):+.2f} | {sw/n:+.4f}")


print(f"\ntest対象(延べ): {n_test}")
show("① 初ブリ大穴combo", b1, ['初ブリ(全体)', '初ブリ×前走大敗×人気薄'])
show("② 大幅距離短縮", b2, ['大幅短縮(≤-400)', '短縮(-399〜-100)', '同距離(±99)', '延長(100〜399)', '大幅延長(≥400)'])
show("③ コース適性お帰り(当場過去複勝率)", b3, ['得意≥50%', '良34-49%', '並20-33%', '苦手<20%'])
show("④ 性×季節バイアス", b4)
show("⑤ 初ダート score別(5項目)", b5, ['score0', 'score1', 'score2', 'score3', 'score4', 'score5'])
show("⑤b 初ダート 注目subset", b5h, ['初ダート(全体)', 'score≥3×人気薄'])
print("\n|z|>=1.96で5%有意。残差>0かつ有意な区分のみ『市場を超える妙味』。0近傍は織込み済=表示のみ。")
