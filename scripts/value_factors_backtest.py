# -*- coding: utf-8 -*-
"""妙味スキャナの『+ファクター』候補を現代データ(2023-2025)で検証。
資料(Data_Driven_Racing/解体新書)の未検証シグナルが市場を超えて好走するか=オッズ補正残差で確認。
残差>0かつz有意なら『妙味馬の+ファクター』として採用。

検証シグナル(前走=その馬の直前走の属性で判定):
 A 前走惜敗   : 前走着順≥6 だが 勝ち馬とのタイム差≤0.5秒(僅差大敗→巻き返し)
 B 前走脚余し : 前走 差し/追込 かつ 上がり3F順位≤3位 だが 着順>3(展開不向き)
 C 軽量馬     : 今回 斤量/馬体重≤11.2% かつ 馬体重≤489kg(資料:回収率107%)
 (比較対象として斤量比の他帯も)
"""
import os, sys, sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

con = sqlite3.connect(jj.JV_DB_PATH); cur = con.cursor()
exp = jj.calibrate_odds_expectation(db_path=jj.JV_DB_PATH)


def e1(o):
    e = exp.get(jj._odds_band(o)); return e['win'] if e else 0.08


def e3(o):
    e = exp.get(jj._odds_band(o)); return e['top3'] if e else 0.22


def se_z(s3, n):
    if not n:
        return 0.0
    se = (0.22 * 0.78 / n) ** 0.5
    return (s3 / n) / se if se else 0.0


def ptime(s):
    """'1129'->72.9s。右からtenth/sec/minute。"""
    s = str(s or '').strip()
    if not s.isdigit() or len(s) < 2:
        return None
    tenth = int(s[-1]); sec = int(s[-3:-1] or 0); minute = int(s[:-3] or 0)
    return minute * 60 + sec + tenth / 10.0


BASE = ("FROM results r JOIN races ra ON r.race_key=ra.race_key "
        "WHERE r.chakujun>0 AND ra.surface IN ('芝','ダート') "
        "AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10")

print("loading rows...")
rows = cur.execute(
    "SELECT r.race_key, r.ketto_num, r.chakujun, r.time, r.ato3f, r.futan, r.bataiju, "
    "       r.kyakushitsu, r.win_odds, r.ninki, ra.year "
    f"{BASE} ORDER BY r.race_key").fetchall()
print(f"  {len(rows)} rows")

# group by race_key
races = defaultdict(list)
for row in rows:
    races[row[0]].append(row)

prev = {}   # ketto -> dict(chaku, margin, kyaku, a3rank)
buckets = defaultdict(lambda: [0.0, 0.0, 0.0, 0])   # label -> [3着内残差,勝利残差,単勝払戻,n]


def add(label, r3, rw, pay):
    d = buckets[label]; d[0] += r3; d[1] += rw; d[2] += pay; d[3] += 1


for rk in sorted(races.keys()):
    grp = races[rk]
    # winner time
    wts = [ptime(g[3]) for g in grp if g[2] == 1 and ptime(g[3])]
    wt = min(wts) if wts else None
    # ato3f rank (smaller=faster=better)
    a3s = sorted([(g[4], g[1]) for g in grp if g[4] and g[4] > 0])
    a3rank = {}
    for idx, (_, ket) in enumerate(a3s, 1):
        a3rank[ket] = idx
    for g in grp:
        (_, ket, chaku, tm, ato3f, futan, bataiju, kyaku, o, ninki, year) = g
        # ---- 評価(今回がtest年 & 人気/オッズあり) ----
        if year >= '2023' and o and o > 0 and ninki:
            r3 = (1 if chaku <= 3 else 0) - e3(o)
            rw = (1 if chaku == 1 else 0) - e1(o)
            pay = o if chaku == 1 else 0.0
            p = prev.get(ket)
            if p:
                # A 前走惜敗
                if p['chaku'] is not None and p['chaku'] >= 6 and p['margin'] is not None and p['margin'] <= 0.5:
                    add('A_前走惜敗(着6+×差0.5以内)', r3, rw, pay)
                elif p['chaku'] is not None and p['chaku'] >= 6:
                    add('A_前走大敗(着6+×差0.5超)', r3, rw, pay)
                # B 前走脚余し
                if p['kyaku'] in ('3', '4') and p['a3rank'] and p['a3rank'] <= 3 and p['chaku'] and p['chaku'] > 3:
                    add('B_前走脚余し(上3位×着4+)', r3, rw, pay)
                elif p['kyaku'] in ('3', '4'):
                    add('B_前走差追(基準)', r3, rw, pay)
            # C 軽量馬(今回属性)
            if futan and bataiju and bataiju > 0:
                ratio = (futan / 10.0) / bataiju
                if ratio <= 0.112 and bataiju <= 489:
                    add('C_軽量馬(比≤11.2%×489以下)', r3, rw, pay)
                elif ratio <= 0.112:
                    add('C_斤量比≤11.2%(全馬体重)', r3, rw, pay)
                elif ratio <= 0.118:
                    add('C_斤量比11.2-11.8%', r3, rw, pay)
                else:
                    add('C_斤量比>11.8%', r3, rw, pay)
        # ---- prev更新 ----
        margin = None
        t = ptime(tm)
        if t is not None and wt is not None:
            margin = round(t - wt, 1)
        prev[ket] = {'chaku': chaku, 'margin': margin, 'kyaku': str(kyaku), 'a3rank': a3rank.get(ket)}
con.close()


def show(title, keys):
    print(f"\n==== {title} ====")
    print("  区分                          |   n    | 3着内残差 | (z)   | 勝利残差 | 単勝回収")
    for k in keys:
        if k not in buckets:
            continue
        s3, sw, pay, n = buckets[k]
        if n:
            print(f"  {k:28s} | {n:6d} | {s3/n:+.4f} | {se_z(s3,n):+.2f} | {sw/n:+.4f} | {pay/n:6.1%}")


print("\n【残差>0かつz≥+1.96=妙味(市場が過小評価)。採用候補】")
show("A 前走惜敗(僅差大敗)", ['A_前走惜敗(着6+×差0.5以内)', 'A_前走大敗(着6+×差0.5超)'])
show("B 前走脚余し", ['B_前走脚余し(上3位×着4+)', 'B_前走差追(基準)'])
show("C 軽量馬(資料:回収率107%主張)", ['C_軽量馬(比≤11.2%×489以下)', 'C_斤量比≤11.2%(全馬体重)', 'C_斤量比11.2-11.8%', 'C_斤量比>11.8%'])
