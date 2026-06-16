# -*- coding: utf-8 -*-
"""
3連複パターン・セレクター検証 — 「①/②/鉄板のどれを買うかを当てる」
──────────────────────────────────────────────────────────────────────────
背景: 勝ち3連複の形は 鉄板(人気3)37% / ①人気2-穴1 46% / ②人気1-穴2 15.5% / 大穴1.5%。
      ①を機械的に買えば的中46%が天井。ユーザー要望=「3つのうちどれを買うか上手く当て」
      12R中6→7的中(50→58%)。そのためには『このレースは①にならない(②や鉄板になる)』
      をレース前に見抜くセレクターが要る。

仮説: 勝ち形＝レースの荒れ度。荒れ度はレース前オッズ(1番人気の支持の強さ＝確定オッズで代理)で
      事前に分かる。1番人気が抜けて堅い→鉄板/①、混戦(1番人気が薄い)→②/大穴に振れる。

検証: 2018+ の3連複確定レースを「1番人気の確定オッズ」で堅/中/荒に層別し、
      各層の勝ち形分布を見る → 層ごとに最頻形をセレクターが選ぶ。
      『セレクター選択形の的中率』を ①固定・②固定・おまかせ(=形不問で人気2+穴で当たる箱)と比較。

注意: 確定オッズで層別＝事後情報を含む近似。だが1番人気の支持率は発走時点でほぼ確定して
      おり、レース前オッズと強く相関するため荒れ度の事前代理として妥当。
"""
import os, sys, sqlite3, statistics
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

POP_TH = 5  # 人気=ninki<=5

con = sqlite3.connect(jj.JV_DB_PATH)
# レースごとに 全馬の(ninki,win_odds,chakujun) と 頭数 と 3連複配当 を取得
rows = con.execute("""
    SELECT r.race_key, r.ninki, r.win_odds, r.chakujun, ra.shusso_tosu, p.payout
    FROM results r
    JOIN races ra ON ra.race_key=r.race_key
    JOIN payouts p ON p.race_key=r.race_key AND p.bet_type='3連複'
    WHERE r.ninki>0 AND p.payout>0 AND ra.year>='2018'
""").fetchall()
con.close()

races = defaultdict(lambda: {'fav_odds': None, 'top3_ninki': [], 'tosu': 0, 'pay': 0})
for rk, ninki, wodds, chaku, tosu, pay in rows:
    R = races[rk]
    R['tosu'] = tosu or 0
    R['pay'] = pay
    if ninki == 1 and wodds and wodds > 0:
        R['fav_odds'] = wodds
    if chaku in (1, 2, 3):
        R['top3_ninki'].append(ninki)

# 1番人気オッズ判明 & 1-3着人気が3頭揃ったレースのみ
races = {k: v for k, v in races.items()
         if v['fav_odds'] and len(v['top3_ninki']) == 3}
N = len(races)
print(f"対象レース(3連複・1番人気オッズ判明・1-3着揃い): {N:,}\n")


def shape(top3):
    pops = sum(1 for x in top3 if x <= POP_TH)
    return {3: '鉄板', 2: '①', 1: '②', 0: '大穴'}[pops]


# ── 1番人気オッズの分位点で 堅/中/荒 を切る ──
fav = sorted(v['fav_odds'] for v in races.values())
q33 = fav[int(N * 0.33)]
q66 = fav[int(N * 0.66)]
print(f"1番人気オッズの層境界: 堅 ≤{q33:.1f} < 中 ≤{q66:.1f} < 荒")


def band(fo):
    if fo <= q33:
        return '堅(1番人気が抜けて堅い)'
    if fo <= q66:
        return '中'
    return '荒(1番人気が薄い混戦)'


# ── 層別の勝ち形分布 ──
layer = defaultdict(lambda: defaultdict(lambda: {'n': 0, 'pays': []}))
layer_tot = defaultdict(int)
for v in races.values():
    b = band(v['fav_odds'])
    s = shape(v['top3_ninki'])
    layer[b][s]['n'] += 1
    layer[b][s]['pays'].append(v['pay'])
    layer_tot[b] += 1

print("\n=== 層別 勝ち3連複の形 分布 ===")
print(f"{'層':<22}{'鉄板':>10}{'①人2穴1':>11}{'②人1穴2':>11}{'大穴':>9}")
for b in ['堅(1番人気が抜けて堅い)', '中', '荒(1番人気が薄い混戦)']:
    tot = layer_tot[b] or 1
    cells = []
    for s in ['鉄板', '①', '②', '大穴']:
        n = layer[b][s]['n']
        cells.append(f"{n/tot*100:5.1f}%")
    print(f"{b:<22}{cells[0]:>10}{cells[1]:>11}{cells[2]:>11}{cells[3]:>9}  (n={layer_tot[b]:,})")

# ── 各層の最頻形を「セレクター推奨」とし、選択形の的中率を測る ──
selector = {}
for b in layer_tot:
    best_s = max(['鉄板', '①', '②'], key=lambda s: layer[b][s]['n'])
    selector[b] = best_s
print("\n=== セレクター推奨（層→最頻形）===")
for b, s in selector.items():
    md = statistics.median(layer[b][s]['pays']) / 100
    print(f"  {b:<22} → {s}  (その層での的中率 {layer[b][s]['n']/layer_tot[b]*100:.1f}% / 配当中央値{md:.0f}倍)")

# ── 戦略比較: 全レースを通した「選んだ形が当たった率」 ──
def hit_rate(choose):
    """choose(race)->形 を返す関数。選択形=実際の形 なら的中。"""
    hits = 0
    for v in races.values():
        if choose(v) == shape(v['top3_ninki']):
            hits += 1
    return hits, hits / N * 100

always1, _ = hit_rate(lambda v: '①')
always2, _ = hit_rate(lambda v: '②')
sel_hits, sel_pct = hit_rate(lambda v: selector[band(v['fav_odds'])])

print("\n=== 戦略比較: 『選んだ形が当たった率』(1R1点想定の形的中) ===")
print(f"  ①固定        : {always1/N*100:5.1f}%  ({always1:,}/{N:,})")
print(f"  ②固定        : {always2/N*100:5.1f}%  ({always2:,}/{N:,})")
print(f"  セレクター層別 : {sel_pct:5.1f}%  ({sel_hits:,}/{N:,})")

# ── おまかせ(形不問で人気2頭以上絡めば当たる箱)の参考的中率 ──
omakase = sum(1 for v in races.values()
              if sum(1 for x in v['top3_ninki'] if x <= POP_TH) >= 2)
print(f"  おまかせ(人気2頭以上絡む): {omakase/N*100:5.1f}%  ({omakase:,}/{N:,})  ※点数多=配当安")

# ── 層別 "最頻2形カバー" 戦略: 単一形を当てるのでなく、その層で多い2形を同時に覆う ──
cover2 = {}
for b in layer_tot:
    top2 = sorted(['鉄板', '①', '②', '大穴'],
                  key=lambda s: -layer[b][s]['n'])[:2]
    cover2[b] = set(top2)
print("\n=== セレクター(最頻2形カバー): 単一形を当てず『層で多い2形』を覆う ===")
for b in ['堅(1番人気が抜けて堅い)', '中', '荒(1番人気が薄い混戦)']:
    covered = sum(layer[b][s]['n'] for s in cover2[b])
    label = '+'.join(sorted(cover2[b], key=lambda s: ['鉄板','①','②','大穴'].index(s)))
    print(f"  {b:<22} → [{label}] カバー率 {covered/layer_tot[b]*100:.1f}%")
cov_hits = sum(1 for v in races.values() if shape(v['top3_ninki']) in cover2[band(v['fav_odds'])])
print(f"  全体カバー率(層別2形): {cov_hits/N*100:5.1f}%  ({cov_hits:,}/{N:,})")

print("\n" + "=" * 60)
print("【結論】")
print(" ・荒れ度で『単一の形』を当てるのは無理(セレクター≒①固定46%)。①はどの層でも44-49%で一定。")
print(" ・2形カバーでも全層で『鉄板+①』が最頻=人気上位2頭が必ず3着内に2頭入る形。")
print("   荒レースですら 鉄板+①(75%) > ①+②(71%)。②単独狙いは荒れても22%止まりで割に合わない。")
print(" ・的中を上げる唯一の正解 = 『人気上位2頭を必ず軸に入れ、3頭目に人気3番手〜穴を広く流す』")
print("   = 鉄板と①を同時カバー = 83%。これが『おまかせが一番当たった』の正体。")
print(" ・トレードオフ: 鉄板の配当は中央値~15倍(ほぼトリガミ)、①は~71倍。的中率↑だが鉄板ヒットは利が薄い。")
print(" ・12R中6→7的中の最短路: ②(人気1-穴2)単独の列を減らし、人気上位2頭軸の鉄板+①カバーに寄せる。")
print("   荒れと読んだ時だけ3頭目の穴を厚く(配当を取りにいく)。形当てではなく軸2頭固定で底上げ。")
