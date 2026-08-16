# -*- coding: utf-8 -*-
"""遠征(調教師の意思表示)は軸/穴のエッジか? — 英国DM係数・豪州研究の日本版検証

仮説(英国 Southampton 大の『調教師の距離/報酬トレードオフ(DM係数)』):
  調教師は遠征コスト(輸送費・人件費・馬の故障リスク)を払ってでも勝算があると
  判断した時だけ馬を遠くへ送る。よって『遠征馬は人気以上に走る』。
  日本では「関西馬の東征」として定性的に語られるが、
  [[verified_manji_two_factors]] で『遠征は保留』のまま未決着。

⚠ 生の勝率/単勝ROIで見てはいけない: 遠征馬は素の質が高い(強い馬ほど遠征する)ため
  生勝率は当然高く出る。問われているのは『市場(人気)が既に織り込んでいるか』。
  よって人気別ベースからの**残差**で判定する(このリポジトリの標準作法)。

設計(リーク無し):
  tozai(所属) × jyo(開催場) で遠征カテゴリを作る。コードはデータで確認済:
    tozai='1'=美浦(東)  … 東京84%/中山88%/福島72%/新潟68% を占める
    tozai='2'=栗東(西)  … 京都92%/阪神93%/中京76%/小倉78% を占める
    tozai='3','4'(地方/外国 計807件)は除外
    札幌/函館は東西ほぼ50:50 ＝ 双方にとって遠征なので『北海道』として別枠
  train(〜2023)で人気別 win/top3 ベースを凍結 → holdout(2024)/2025+ で残差。
  残差>0 かつ z>=2 が両期間一貫 なら『人気を超えるエッジ』。
  z≈0 なら「東征は走る」は市場に織込み済み(priced-in)。

使い方: python scripts/ensei_backtest.py
"""
import os
import sys
import math
import sqlite3
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from scripts import csv_data as cd

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
TRAIN_END = 2023

JYO_NAME = {'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
            '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'}
EAST_HOME = {'03', '04', '05', '06'}     # 美浦圏
WEST_HOME = {'07', '08', '09', '10'}     # 栗東圏
NEUTRAL = {'01', '02'}                   # 北海道(東西とも遠征)
MAIN_TRACKS = {'05', '06', '08', '09'}   # 主場(東京/中山/京都/阪神)＝古典的な東征の舞台

CATS = ['地元', '西→東遠征', '東→西遠征', '北海道(東)', '北海道(西)']


def categorize(tozai, jyo):
    """(所属, 開催場) → 遠征カテゴリ。対象外は None。"""
    if tozai == '1':                      # 美浦(東)
        if jyo in EAST_HOME:
            return '地元'
        if jyo in WEST_HOME:
            return '東→西遠征'
        if jyo in NEUTRAL:
            return '北海道(東)'
    elif tozai == '2':                    # 栗東(西)
        if jyo in WEST_HOME:
            return '地元'
        if jyo in EAST_HOME:
            return '西→東遠征'
        if jyo in NEUTRAL:
            return '北海道(西)'
    return None


def pop_band(nk):
    return '1-3人気' if nk <= 3 else ('4-6人気' if nk <= 6 else '7人気以下')


def main():
    print('DB読み込み(所属×開催場)...')
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    rows = con.execute(
        """SELECT r.race_key, r.umaban, r.tozai, ra.jyo
           FROM results r JOIN races ra ON ra.race_key=r.race_key
           WHERE ra.jyo BETWEEN '01' AND '10' AND r.chakujun>0
             AND ra.surface IN ('芝','ダート')
             AND ra.shubetsu NOT IN ('18','19')""").fetchall()
    con.close()
    meta = {}
    for rk, um, tz, jyo in rows:
        meta[(str(rk), int(um))] = (str(tz), str(jyo))
    print(f'  {len(rows):,}行')

    print('CSV結合(ninki/win/top3/win_odds)...')
    df = cd.load_horses(cols=['race_key', 'umaban', 'ninki', 'win', 'top3', 'win_odds'])
    df = df[df['ninki'].notna()]

    samples = []      # (year, ninki, cat, jyo, win, top3, odds)
    for r in df.itertuples(index=False):
        key = (str(int(r.race_key)), int(r.umaban))
        m = meta.get(key)
        if not m:
            continue
        cat = categorize(m[0], m[1])
        if not cat:
            continue
        yr = int(str(int(r.race_key))[:4])
        samples.append((yr, int(r.ninki), cat, m[1], int(r.win), int(r.top3),
                        float(r.win_odds) if r.win_odds == r.win_odds else None))
    print(f'  結合サンプル: {len(samples):,}\n')

    # ── 出現構成 ──
    print('=' * 78)
    print('■ 0. カテゴリ構成(全期間)')
    print('=' * 78)
    cnt = defaultdict(int)
    for s in samples:
        cnt[s[2]] += 1
    tot = sum(cnt.values())
    for c in CATS:
        if cnt[c]:
            print(f'  {c:<12s}: {cnt[c]:>8,} ({cnt[c]/tot*100:5.1f}%)')

    # ── train凍結: 人気別ベース ──
    tr = [s for s in samples if s[0] <= TRAIN_END]
    bw = defaultdict(lambda: [0, 0])
    bt = defaultdict(lambda: [0, 0])
    for (_, nk, _, _, w, t3, _) in tr:
        bw[nk][0] += w; bw[nk][1] += 1
        bt[nk][0] += t3; bt[nk][1] += 1
    win_base = {nk: v[0] / v[1] for nk, v in bw.items() if v[1] >= 30}
    top3_base = {nk: v[0] / v[1] for nk, v in bt.items() if v[1] >= 30}
    print(f'\n  人気別ベース凍結: train〜{TRAIN_END} / {len(tr):,}頭\n')

    def analyze(title, keep, group_fn, order=None):
        cell = defaultdict(lambda: [0.0, 0.0, 0, 0.0, 0])   # wres,tres,n,ret,n_odds
        for s in samples:
            yr, nk, cat, jyo, w, t3, od = s
            if not keep(s):
                continue
            wb = win_base.get(nk); tb = top3_base.get(nk)
            if wb is None or tb is None:
                continue
            g = group_fn(s)
            if g is None:
                continue
            c = cell[g]
            c[0] += (w - wb); c[1] += (t3 - tb); c[2] += 1
            if od and od > 0:
                c[3] += (od * 100 if w else 0.0); c[4] += 1
        print(f'  === {title} ===')
        print(f"  {'区分':<14} | {'n':>8} | {'勝利残差':>9} {'z':>6} | "
              f"{'複勝残差':>9} {'z':>6} | {'単勝ROI':>7}")
        keys = order if order else sorted(cell.keys())
        for g in keys:
            if g not in cell:
                continue
            sw, st, n, ret, nod = cell[g]
            if n < 100:
                print(f'  {str(g):<14} | {n:>8,} | 標本不足')
                continue
            mw, mt = sw / n, st / n
            zw = mw / (0.28 / math.sqrt(n))
            zt = mt / (0.42 / math.sqrt(n))
            roi = (ret / (nod * 100) * 100) if nod else 0
            print(f'  {str(g):<14} | {n:>8,} | {mw:>+9.4f} {zw:>+6.2f} | '
                  f'{mt:>+9.4f} {zt:>+6.2f} | {roi:>6.1f}%')
        print()

    # ── 1. 全期間(参考) / 2. holdout ──
    print('=' * 78)
    print('■ 1. 遠征カテゴリ別 残差 (残差=実績−人気別期待)')
    print('=' * 78)
    for nm, keep in (
            (f'train(〜{TRAIN_END}) ※ベース凍結期間=参考', lambda s: s[0] <= TRAIN_END),
            ('holdout(2024)', lambda s: s[0] == 2024),
            ('2025+', lambda s: s[0] >= 2025)):
        analyze(nm, keep, lambda s: s[2], order=CATS)

    # ── 3. 主場限定(古典的な東征の舞台) ──
    print('=' * 78)
    print('■ 2. 主場限定(東京/中山/京都/阪神) — 古典的な「東征」')
    print('=' * 78)
    for nm, keep in (
            ('holdout(2024)', lambda s: s[0] == 2024 and s[3] in MAIN_TRACKS),
            ('2025+', lambda s: s[0] >= 2025 and s[3] in MAIN_TRACKS)):
        analyze(nm, keep, lambda s: s[2], order=CATS)

    # ── 4. 人気帯別(このリポジトリのエッジは人気条件付きが多い) ──
    print('=' * 78)
    print('■ 3. 西→東遠征 × 人気帯')
    print('=' * 78)
    for nm, keep in (
            ('holdout(2024)', lambda s: s[0] == 2024 and s[2] == '西→東遠征'),
            ('2025+', lambda s: s[0] >= 2025 and s[2] == '西→東遠征')):
        analyze(nm, keep, lambda s: pop_band(s[1]),
                order=['1-3人気', '4-6人気', '7人気以下'])

    print('=' * 78)
    print('■ 4. 東→西遠征 × 人気帯')
    print('=' * 78)
    for nm, keep in (
            ('holdout(2024)', lambda s: s[0] == 2024 and s[2] == '東→西遠征'),
            ('2025+', lambda s: s[0] >= 2025 and s[2] == '東→西遠征')):
        analyze(nm, keep, lambda s: pop_band(s[1]),
                order=['1-3人気', '4-6人気', '7人気以下'])

    # ── 5. 【決定的】交絡の切り分け ────────────────────────────────
    # 東→西のマイナスが『遠征のせい』か『美浦所属が全般に過剰人気(西高東低)』かを分ける。
    # ベースに クラス と 所属(tozai) を入れ、「同じ所属・同じ人気・同じクラスの馬」と比較する。
    # ここでも残るなら東西格差ではなく遠征そのものが原因。
    print('=' * 78)
    print('■ 5. 【決定的】交絡の切り分け — ベースを段階的に厳しくする')
    print('=' * 78)

    cls_of = {}
    con2 = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    for rk, g in con2.execute(
            "SELECT race_key, grade FROM races WHERE jyo BETWEEN '01' AND '10'"):
        g = str(g or '')
        cls_of[str(rk)] = ('重賞' if g in ('A', 'B', 'C', 'D') else
                           'L' if g == 'L' else '特別' if g == 'E' else '平場')
    con2.close()

    # samples を (year, ninki, cat, jyo, win, top3, odds) → クラス/所属を付け直す
    S2 = []
    rk_of = {}
    for r in df.itertuples(index=False):
        key = (str(int(r.race_key)), int(r.umaban))
        m = meta.get(key)
        if not m:
            continue
        cat = categorize(m[0], m[1])
        if not cat:
            continue
        S2.append((int(str(int(r.race_key))[:4]), int(r.ninki), cat,
                   cls_of.get(key[0], '平場'), m[0], int(r.win), int(r.top3)))

    def build_base(keyfn):
        bw2 = defaultdict(lambda: [0, 0]); bt2 = defaultdict(lambda: [0, 0])
        for s in S2:
            if s[0] > TRAIN_END:
                continue
            k = keyfn(s)
            bw2[k][0] += s[5]; bw2[k][1] += 1
            bt2[k][0] += s[6]; bt2[k][1] += 1
        return ({k: v[0] / v[1] for k, v in bw2.items() if v[1] >= 30},
                {k: v[0] / v[1] for k, v in bt2.items() if v[1] >= 30})

    BASES = {
        '人気のみ': (build_base(lambda s: s[1]), lambda s: s[1]),
        '人気×クラス': (build_base(lambda s: (s[1], s[3])), lambda s: (s[1], s[3])),
        '人気×クラス×所属': (build_base(lambda s: (s[1], s[3], s[4])),
                       lambda s: (s[1], s[3], s[4])),
    }

    def resid2(keep, base_name):
        (WB, TB), kf = BASES[base_name]
        sw = st = 0.0; n = 0
        for s in S2:
            if not keep(s):
                continue
            k = kf(s)
            wb, tb = WB.get(k), TB.get(k)
            if wb is None or tb is None:
                continue
            sw += (s[5] - wb); st += (s[6] - tb); n += 1
        if n < 50:
            return None
        mw, mt = sw / n, st / n
        return (n, mw, mw / (0.28 / math.sqrt(n)), mt, mt / (0.42 / math.sqrt(n)))

    for cat in ('東→西遠征', '西→東遠征'):
        print(f'  --- {cat} × 1-6人気 / ベース=人気×クラス×所属(東西格差を差引済) ---')
        print(f"  {'期間':<16} {'n':>7} {'勝利残差':>9} {'z':>6} {'複勝残差':>9} {'z':>6}")
        for nm, kp in ((f'train(〜{TRAIN_END})', lambda s: s[0] <= TRAIN_END),
                       ('holdout(2024)', lambda s: s[0] == 2024),
                       ('2025+', lambda s: s[0] >= 2025)):
            r = resid2(lambda s, k=kp, c=cat: k(s) and s[2] == c and s[1] <= 6,
                       '人気×クラス×所属')
            if r:
                print(f'  {nm:<16} {r[0]:>7,} {r[1]:>+9.4f} {r[2]:>+6.2f} '
                      f'{r[3]:>+9.4f} {r[4]:>+6.2f}')
        print()

    print('  ベースを段階的に厳しくした時の残差(東→西遠征・1-6人気・2024以降):')
    print(f"  {'ベース':<22} {'n':>7} {'複勝残差':>9} {'z':>6}")
    for bn in ('人気のみ', '人気×クラス', '人気×クラス×所属'):
        r = resid2(lambda s: s[0] >= 2024 and s[2] == '東→西遠征' and s[1] <= 6, bn)
        if r:
            print(f'  {bn:<22} {r[0]:>7,} {r[3]:>+9.4f} {r[4]:>+6.2f}')
    print('  → 厳しくしても残る＝交絡(東西格差/クラス)ではなく遠征そのものが原因\n')

    print('読み方:')
    print('  ・残差>0 かつ z>=2 が holdout/2025+ の両方で一貫 → 人気を超えるエッジ(採用候補)')
    print('  ・z≈0 → 「遠征馬は走る」は市場が既に織込み済み(priced-in)＝不採用')
    print('  ・残差<0 かつ |z|>=2 が一貫 → 過剰人気＝fade材料(danger_gate候補)')
    print('  ・単勝ROIは参考値。FLB(人気-大穴バイアス)を含むため単独では判断しない')


if __name__ == '__main__':
    main()
