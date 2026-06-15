# -*- coding: utf-8 -*-
"""「危険な人気馬」候補シグナルを一括検証(test=2023-2025・JRA平地)。
資料(危険な人気馬の解体新書/2026 Playbook)の消し材料が、市場を超えて凡走するか=
オッズ補正残差で確認。対象は人気上位(ninki<=3、押し出しはninki==1)。
残差<0かつ有意なら『危険検知』として採用価値あり。

検証シグナル:
 A 押し出し1番人気(ninki==1 × 単勝オッズ帯)
 B トップ騎手からの乗り替わり(前走トップ騎手→今回別騎手)
 C 斤量比(futan/bataiju)≥12.6% / 小型馬439kg以下×酷量
 D 半年以上の休み明け(前走から180日以上)
 E ローカル開催(札幌/函館/福島/新潟/中京/小倉)
 F 極端脚質(前走 逃げ/追込)
 G 長距離戦(2400m以上 / 3000m以上)
"""
import os
import sys
import sqlite3
from datetime import datetime
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


def se_z(s3, n):
    if not n:
        return 0.0
    se = (0.22 * 0.78 / n) ** 0.5
    return (s3 / n) / se if se else 0.0


BASE = ("FROM results r JOIN races ra ON r.race_key=ra.race_key "
        "WHERE r.chakujun>0 AND r.ketto_num!='' AND ra.surface IN ('芝','ダート') "
        "AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10")

print("train(〜2022)でトップ騎手を判定...")
jstat = defaultdict(lambda: [0, 0])
for jky, chaku in cur.execute(f"SELECT r.jockey_name, r.chakujun {BASE} AND ra.year<'2023'"):
    jstat[jky][0] += 1
    jstat[jky][1] += (1 if chaku == 1 else 0)
TOPJ = {j for j, (n, w) in jstat.items() if n >= 500 and w / n >= 0.15}
print(f"  トップ騎手:{len(TOPJ)}人 例:{list(TOPJ)[:6]}")

LOCAL = {'01', '02', '03', '04', '07', '10'}
last_jky = {}; last_date = {}; last_kyaku = {}
buckets = defaultdict(lambda: [0.0, 0.0, 0.0, 0])   # label -> [3着内残差,勝利残差,単勝払戻,n]


def add(label, r3, rw, pay):
    d = buckets[label]; d[0] += r3; d[1] += rw; d[2] += pay; d[3] += 1


print("時系列スキャン...")
rows = cur.execute(
    "SELECT r.race_key, r.ketto_num, r.jockey_name, r.chakujun, r.win_odds, r.ninki, "
    "       r.futan, r.bataiju, r.kyakushitsu, ra.year, ra.jyo, ra.kyori "
    f"{BASE} ORDER BY r.race_key").fetchall()
print(f"  {len(rows)}行")

for (rk, ketto, jky, chaku, o, ninki, futan, bataiju, kyaku, year, jyo, kyori) in rows:
    if year >= '2023' and o and o > 0 and ninki:
        r3 = (1 if chaku <= 3 else 0) - e3(o)
        rw = (1 if chaku == 1 else 0) - e1(o)
        pay = o if chaku == 1 else 0.0
        fav = ninki <= 3
        # A 押し出し1番人気
        if ninki == 1:
            band = ('1人気 オッズ<2.0' if o < 2.0 else '1人気 2.0-3.0' if o < 3.0
                    else '1人気 3.0-4.0' if o < 4.0 else '1人気 ≥4.0(押し出し)')
            add('A_' + band, r3, rw, pay)
        if fav:
            # B トップ騎手乗り替わり
            pj = last_jky.get(ketto)
            if pj is not None:
                if pj in TOPJ and jky != pj:
                    add('B_トップ騎手から乗替', r3, rw, pay)
                else:
                    add('B_継続/非トップ', r3, rw, pay)
            # C 斤量比
            if futan and bataiju and bataiju > 0:
                ratio = (futan / 10.0) / bataiju
                if ratio >= 0.126:
                    add('C_斤量比≥12.6%', r3, rw, pay)
                    if bataiju <= 439:
                        add('C_小型馬439以下×酷量', r3, rw, pay)
                else:
                    add('C_斤量比<12.6%', r3, rw, pay)
            # D 休み明け
            pdte = last_date.get(ketto)
            if pdte:
                try:
                    gap = (datetime.strptime(rk[:8], '%Y%m%d') - pdte).days
                    if gap >= 180:
                        add('D_半年以上休み明け', r3, rw, pay)
                    elif gap >= 60:
                        add('D_中期(60-179日)', r3, rw, pay)
                    else:
                        add('D_叩き2戦目以内(<60日)', r3, rw, pay)
                except Exception:
                    pass
            # E ローカル
            add('E_ローカル' if jyo in LOCAL else 'E_中央場', r3, rw, pay)
            # F 極端脚質(前走)
            pk = last_kyaku.get(ketto)
            if pk == '1':
                add('F_前走逃げ', r3, rw, pay)
            elif pk == '4':
                add('F_前走追込', r3, rw, pay)
            elif pk in ('2', '3'):
                add('F_前走先行差し', r3, rw, pay)
            # G 長距離
            if kyori and kyori >= 3000:
                add('G_3000m以上', r3, rw, pay)
            elif kyori and kyori >= 2400:
                add('G_2400-2999m', r3, rw, pay)
            elif kyori:
                add('G_2399m以下', r3, rw, pay)
    # state更新
    last_jky[ketto] = jky
    try:
        last_date[ketto] = datetime.strptime(rk[:8], '%Y%m%d')
    except Exception:
        pass
    last_kyaku[ketto] = str(kyaku)
con.close()


def show(title, keys):
    print(f"\n==== {title} ====")
    print("  区分                     |   n    | 3着内残差 | (z)   | 勝利残差 | 単勝回収率")
    for k in keys:
        if k not in buckets:
            continue
        s3, sw, pay, n = buckets[k]
        if n:
            print(f"  {k:24s} | {n:6d} | {s3/n:+.4f} | {se_z(s3,n):+.2f} | {sw/n:+.4f} | {pay/n:6.1%}")


print("\n【対象=人気上位(ninki≤3)。残差<0かつz有意=危険検知の価値】")
show("A 押し出し1番人気(対象=1番人気)", ['A_1人気 オッズ<2.0', 'A_1人気 2.0-3.0', 'A_1人気 3.0-4.0', 'A_1人気 ≥4.0(押し出し)'])
show("B トップ騎手からの乗り替わり", ['B_トップ騎手から乗替', 'B_継続/非トップ'])
show("C 斤量×馬体重", ['C_斤量比≥12.6%', 'C_斤量比<12.6%', 'C_小型馬439以下×酷量'])
show("D 休み明け", ['D_半年以上休み明け', 'D_中期(60-179日)', 'D_叩き2戦目以内(<60日)'])
show("E ローカル開催", ['E_ローカル', 'E_中央場'])
show("F 前走脚質", ['F_前走逃げ', 'F_前走先行差し', 'F_前走追込'])
show("G 距離", ['G_2399m以下', 'G_2400-2999m', 'G_3000m以上'])
print("\n残差<0かつ|z|≥1.96で有意に危険→③検知に採用。0近傍/正は織込み済or効かず=非採用。")
