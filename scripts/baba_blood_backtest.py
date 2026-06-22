# -*- coding: utf-8 -*-
"""道悪×血統(国型) 残差バックテスト — NotebookLM血統資料(情報ABC+α)の検証。

検証する仮説(資料の主張・事前登録):
  資料は「血統→予測器(recall@7)」ではなく「血統→人気帯別の残差/回収率」を主張している(p12)。
  cond6で潰したのは父×馬場(芝/ダ surface)であって、馬場状態(良/稍重/重/不良=道悪)は未検証。
  H1(FADE): 日本型瞬発力sire(ディープ/サンデー系)の【人気馬】は道悪で複勝残差マイナス(=危険人気馬)。
  H2(穴) : 米国型/欧州型パワーsireの【人気薄】は道悪で複勝残差プラス(=穴妙味)。

測るもの: オッズ期待(jockey_jv.calibrate_odds_expectation)に対する複勝/勝の残差。
  残差>0かつz>+2 → 市場を破る妙味。残差≈0 → 織込み済み。残差<0 → 過剰人気(FADEなら逆に狙い)。
対象: JRA平地(芝/ダート)・着順/オッズ/人気あり。--year で開始年(既定2018)。
注意: 名指しsireのみ事前登録分類(多重検定回避)。国型(p4)は二級の広い分類。
"""
import os
import sys
import argparse
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

ap = argparse.ArgumentParser()
ap.add_argument('--year', default='2018', help='開始年(含む)')
ap.add_argument('--robust', action='store_true', help='per-sire分解と馬場単調性のみ出力')
args = ap.parse_args()

DB = jj.JV_DB_PATH
exp = jj.calibrate_odds_expectation(db_path=DB)


def e3(o):
    e = exp.get(jj._odds_band(o)); return e['top3'] if e else 0.22


def e1(o):
    e = exp.get(jj._odds_band(o)); return e['win'] if e else 0.08


# ── 事前登録: 資料が名指しした sire(情報A明示ペア + p4/p9/p14) ──
# 完全一致でなく部分一致(系統名も拾う)。資料に無い種牡馬は分類しない。
FADE_SIRES = [  # 日本型瞬発力=道悪×(情報A明示 + p4日本型)
    'ディープインパクト', 'レイデオロ', 'スワーヴリチャード', 'ハーツクライ',
    'ダイワメジャー', 'ドゥラメンテ', 'エピファネイア', 'キタサンブラック',
    'サンデーサイレンス', 'ディープブリランテ', 'リアルインパクト',
]
POWER_SIRES = [  # 道悪○パワー(情報A明示 + 欧州/米国型 p4/p9/p14)
    'キズナ', 'ハービンジャー', 'ブリックスアンドモルタル', 'ルーラーシップ',
    'スクリーンヒーロー', 'ステイゴールド', 'オルフェーヴル', 'ゴールドシップ',
    'シンボリクリスエス', 'ブライアンズタイム', 'モーリス', 'ノヴェリスト',
    'シニスターミニスター', 'ダノンレジェンド', 'ヘニーヒューズ', 'パイロ',
    'マジェスティックウォリアー', 'カレンブラックヒル', 'ディーマジェスティ',
]
# 二級: 国型(p4)。米/欧はPOWER側に含むが、別集計用に分ける。
US_SIRES = ['シニスターミニスター', 'ダノンレジェンド', 'ヘニーヒューズ', 'パイロ',
            'マジェスティックウォリアー', 'カレンブラックヒル']
EU_SIRES = ['ハービンジャー', 'ブリックスアンドモルタル', 'ルーラーシップ', 'スクリーンヒーロー',
            'ステイゴールド', 'オルフェーヴル', 'ゴールドシップ', 'シンボリクリスエス',
            'ブライアンズタイム', 'モーリス', 'ノヴェリスト', 'ディーマジェスティ']
JP_SIRES = FADE_SIRES


def classify(sire):
    if not sire:
        return None, None
    grp = None
    if any(s in sire for s in FADE_SIRES):
        grp = 'FADE(日本型瞬発)'
    elif any(s in sire for s in POWER_SIRES):
        grp = 'POWER(道悪○)'
    ctype = None
    if any(s in sire for s in US_SIRES):
        ctype = '米国型'
    elif any(s in sire for s in EU_SIRES):
        ctype = '欧州型'
    elif any(s in sire for s in JP_SIRES):
        ctype = '日本型'
    return grp, ctype


def baba_state(surface, bshiba, bdirt):
    """1=良 2=稍重 3=重 4=不良。surfaceで芝/ダの該当列を読む。"""
    v = bshiba if surface == '芝' else bdirt
    try:
        v = int(v)
    except Exception:
        return 0
    return v if 1 <= v <= 4 else 0


def band_of(ninki):
    if ninki <= 3:
        return '1-3番人気'
    if ninki <= 5:
        return '4-5番人気'
    if ninki <= 9:
        return '6-9番人気'
    return '10番人気〜'


def agg():
    return {'n': 0, 't3': 0, 'w': 0, 'pay1': 0.0, 'r3': 0.0, 'rw': 0.0}


def add(d, chaku, o):
    d['n'] += 1
    if chaku <= 3:
        d['t3'] += 1
    if chaku == 1:
        d['w'] += 1; d['pay1'] += o
    d['r3'] += (1 if chaku <= 3 else 0) - e3(o)
    d['rw'] += (1 if chaku == 1 else 0) - e1(o)


def rep(name, d, indent=0):
    n = max(d['n'], 1)
    se3 = (0.22 * 0.78 / n) ** 0.5
    se1 = (0.08 * 0.92 / n) ** 0.5
    z3 = (d['r3'] / n) / se3 if se3 else 0
    z1 = (d['rw'] / n) / se1 if se1 else 0
    pad = ' ' * indent
    print(f"{pad}{name:18s} n={d['n']:6d} | 勝率{d['w']/n:6.2%} 複勝率{d['t3']/n:6.2%} "
          f"| 単ROI{d['pay1']/n:6.1%} | 複勝残差{d['r3']/n:+.4f}(z={z3:+.2f}) "
          f"勝残差{d['rw']/n:+.4f}(z={z1:+.2f})")


# ── sire辞書 (ketto_num -> sire) ──
con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
sire_of = {str(k): s for k, s in con.execute("SELECT ketto_num, sire FROM horses").fetchall()}

rows = con.execute(
    """SELECT r.ketto_num, r.chakujun, r.ninki, r.win_odds, r.waku,
              ra.surface, ra.baba_shiba, ra.baba_dirt, ra.kyori, ra.jyo, ra.year
       FROM results r JOIN races ra ON ra.race_key=r.race_key
       WHERE r.chakujun>0 AND r.win_odds>0 AND r.ninki>0
         AND ra.surface IN ('芝','ダート') AND ra.year>=?""", (args.year,)).fetchall()
con.close()

# 集計箱: state(良/道悪) × grp × ninki帯 ; state × ctype × ninki帯
STATE = {1: '良', 2: '稍重', 3: '重', 4: '不良'}
WET = {2, 3, 4}  # 道悪
BANDS = ('1-3番人気', '4-5番人気', '6-9番人気', '10番人気〜')

# grp(FADE/POWER) × {良, 道悪} × ninki帯
G = {g: {w: {b: agg() for b in BANDS} for w in ('良', '道悪')}
     for g in ('FADE(日本型瞬発)', 'POWER(道悪○)')}
# 単調性: grp × {良,稍重,重,不良} (1-3番人気のみ集計)
GS = {g: {s: agg() for s in ('良', '稍重', '重', '不良')}
      for g in ('FADE(日本型瞬発)', 'POWER(道悪○)')}
# per-sire分解: 個別sire × {良,道悪} (1-3番人気のみ)。資料名指しsireのcanonical名で集計
PS = defaultdict(lambda: {'良': agg(), '道悪': agg()})
ALLNAMED = FADE_SIRES + [s for s in POWER_SIRES if s not in FADE_SIRES]


def canon_sire(sire):
    for s in ALLNAMED:
        if s in sire:
            return s
    return None
# ctype × {良,稍重,重,不良} × ninki帯 (細かい馬場推移用)
C = {c: {s: {b: agg() for b in BANDS} for s in ('良', '稍重', '重', '不良')}
     for c in ('日本型', '米国型', '欧州型')}
ALL = {w: {b: agg() for b in BANDS} for w in ('良', '道悪')}

n_used = 0
for ketto, chaku, ninki, odds, waku, surf, bshiba, bdirt, kyori, jyo, year in rows:
    st = baba_state(surf, bshiba, bdirt)
    if st == 0:
        continue
    sire = sire_of.get(str(ketto))
    grp, ctype = classify(sire)
    band = band_of(ninki)
    wet = '道悪' if st in WET else '良'
    n_used += 1
    add(ALL[wet][band], chaku, odds)
    if grp:
        add(G[grp][wet][band], chaku, odds)
        if band == '1-3番人気':
            add(GS[grp][STATE[st]], chaku, odds)
    if band == '1-3番人気':
        cs = canon_sire(sire) if sire else None
        if cs:
            add(PS[cs][wet], chaku, odds)
    if ctype:
        add(C[ctype][STATE[st]][band], chaku, odds)

if args.robust:
    print(f"=== 頑健性チェック (year>={args.year}, 平地芝/ダ, n_used={n_used:,}) ===\n")
    print("【単調性】grp × 馬場悪化(良→稍重→重→不良) ※1-3番人気のみ")
    for g in ('FADE(日本型瞬発)', 'POWER(道悪○)'):
        print(f"\n■ {g}")
        for s in ('良', '稍重', '重', '不良'):
            rep(s, GS[g][s], 4)
    print("\n→ POWERは悪化で残差↑/FADEは悪化で残差↓なら資料の物理が単調支持。\n")
    print("【per-sire分解】個別sire × 良 vs 道悪 ※1-3番人気のみ (n>=80)")
    items = sorted(PS.items(), key=lambda kv: -(kv[1]['道悪']['n']))
    print(f"  {'sire':16s} {'馬場':4s}  n     複勝率   複勝残差     勝残差")
    for cs, d in items:
        for w in ('良', '道悪'):
            dd = d[w]
            if dd['n'] < 80:
                continue
            n = dd['n']
            print(f"  {cs:16s} {w:4s} {n:5d}  {dd['t3']/n:6.2%}  "
                  f"{dd['r3']/n:+.4f}    {dd['rw']/n:+.4f}")
    print("\n→ POWERの道悪プラス残差が1〜2頭依存(他はフラット/負)なら汎化しない。"
          "複数sireで道悪>良ならエッジは頑健。")
    sys.exit(0)

print(f"=== 道悪×血統 残差バックテスト (year>={args.year}, 平地芝/ダ, n_used={n_used:,}) ===")
print("残差>0&z>+2=市場を破る妙味 / ≈0=織込み済み / <0=過剰人気(FADE狙いなら逆に的)\n")

print("── 母集団(全馬) 良 vs 道悪 ──")
for w in ('良', '道悪'):
    for b in BANDS:
        rep(f"{w}/{b}", ALL[w][b], 2)
    print()

print("\n【一級証拠】資料の名指しsire群 — 良 vs 道悪 × 人気帯")
for g in ('FADE(日本型瞬発)', 'POWER(道悪○)'):
    print(f"\n■ {g}")
    for w in ('良', '道悪'):
        for b in BANDS:
            rep(f"{w}/{b}", G[g][w][b], 4)
        print()

print("\n【二級】国型(p4) × 馬場推移(良→稍重→重→不良) × 人気帯")
for c in ('日本型', '米国型', '欧州型'):
    print(f"\n■ {c}")
    for s in ('良', '稍重', '重', '不良'):
        for b in BANDS:
            d = C[c][s][b]
            if d['n'] >= 30:
                rep(f"{s}/{b}", d, 4)
        print()

print("\n→ H1検証: FADE群の『道悪×1-3番人気』複勝残差が負(z<-2)なら危険人気馬として有効。")
print("→ H2検証: POWER群の『道悪×6-9/10番人気〜』複勝残差が正(z>+2)なら穴妙味として有効。")
print("  良馬場との差分も見る(道悪 − 良)。差が出なければ『馬場状態も織込み済み』。")
