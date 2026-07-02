# -*- coding: utf-8 -*-
"""PCI傾向×コース形状の交互作用検証 ―― カード6(⑦ PCIの最終検証)。

動画仮説: 馬のPCI傾向(高=後傾/瞬発/ギアチェンジ型・低=前傾/持続型)を
コース形状にマッチさせる。
  O字コース(トップスピード維持有利) ↔ 低PCI(持続型)     = match
  U字コース(再加速・トルク有利)      ↔ 高PCI(瞬発型)     = match
前走で不向きコースに負け人気を落とした馬が、次走で適性コースに出る穴を狙う。

検証(リーク無し・単体PCIは却下済みなので"交互作用"のみを問う):
  純粋交互作用コントラスト(主効果を打ち消す):
    C = [resid(低PCI,O) + resid(高PCI,U)] − [resid(高PCI,O) + resid(低PCI,U)]
  対象=6人気以下(ninki>=6)のみ。resid=複勝実績−人気別ベース(train凍結)。
  PCI高低の閾値・人気ベースは train2021-24 で凍結→holdout2025で C の z。
採用ゲート(カード6): holdout2025 で C が仮説方向(正)かつ z>=2.0。
  縮退(主効果だけ)/非有意なら却下=「PCIは完全終了」と恒久記録。

PCI公式(core.race_analysis_tools.PCICalculator 準拠):
  pci = (t - a)/((d/200 - 3)) * 3/a * 100 - 50   (t=走破秒, a=上がり3F秒, d=距離m)
コース形状(場): O=長い直線/トップスピード維持, U=短い直線/再加速。
  O: 05東京 04新潟 07中京 / U: 06中山 10小倉 03福島 02函館 01札幌
  (08京都 09阪神=内外併用で曖昧→除外)。芝限定(ダPCIは別物・動画も短距離芝推奨)。
"""
import os
import sys
import sqlite3
import math
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
COURSE = {'05': 'O', '04': 'O', '07': 'O',
          '06': 'U', '10': 'U', '03': 'U', '02': 'U', '01': 'U'}
MIN_PCI_RUNS = 3


def t_sec(s):
    s = ''.join(ch for ch in str(s) if ch.isdigit())
    if not s:
        return None
    if len(s) <= 3:
        return int(s) / 10.0
    return int(s[:-3]) * 60 + int(s[-3:]) / 10.0


def pci_of(time, ato3f, kyori):
    t = t_sec(time)
    if t is None or not ato3f or not kyori:
        return None
    a = ato3f / 10.0
    d = float(kyori)
    if a <= 0 or d <= 600:
        return None
    fb = d / 200.0 - 3.0
    if fb <= 0:
        return None
    p = (t - a) / fb * 3.0 / a * 100.0 - 50.0
    return p if 20.0 <= p <= 100.0 else None


def dk(y, md):
    return int(y) * 10000 + int(md)


def load():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    rows = con.execute(
        """SELECT ra.year, ra.monthday, ra.jyo, ra.surface, r.ketto_num, r.chakujun,
                  r.ninki, r.time, r.ato3f, ra.kyori
           FROM results r JOIN races ra ON ra.race_key=r.race_key
           WHERE CAST(ra.year AS INTEGER) >= 2019 AND ra.jyo BETWEEN '01' AND '10'
             AND ra.surface='芝' AND r.chakujun>0""").fetchall()
    con.close()
    return rows


def main():
    print("読み込み中...")
    rows = load()
    print(f"  {len(rows):,}行")

    # 馬ごとの走行履歴(PCI付き・日付順)
    hist = defaultdict(list)
    for (y, md, jyo, surf, kt, ch, nk, tm, a3, ki) in rows:
        p = pci_of(tm, a3, ki)
        hist[kt].append({'dk': dk(y, md), 'pci': p})
    for k in hist:
        hist[k].sort(key=lambda z: z['dk'])

    def prior_avg_pci(kt, d):
        h = hist.get(kt, [])
        ps = [x['pci'] for x in h if x['dk'] < d and x['pci'] is not None][-5:]
        return (sum(ps) / len(ps)) if len(ps) >= MIN_PCI_RUNS else None

    # サンプル: (year, ninki, course, avg_pci, top3)
    samples = []
    for (y, md, jyo, surf, kt, ch, nk, tm, a3, ki) in rows:
        cs = COURSE.get(jyo)
        if not cs or not nk or nk <= 0:
            continue
        ap = prior_avg_pci(kt, dk(y, md))
        if ap is None:
            continue
        samples.append((int(y), int(nk), cs, ap, 1 if ch <= 3 else 0))

    # train2021-24 で PCI中央値(高低境界)と 人気別ベース を凍結
    tr = [s for s in samples if 2021 <= s[0] <= 2024]
    pcis_tr = sorted(s[3] for s in tr)
    med = pcis_tr[len(pcis_tr) // 2]
    base = defaultdict(lambda: [0, 0])  # ninki -> [top3, n]
    for (_, nk, _, _, t3) in tr:
        base[nk][0] += t3
        base[nk][1] += 1
    base_rate = {nk: (v[0] / v[1] if v[1] else 0.22) for nk, v in base.items()}
    print(f"凍結: PCI高低境界(中央値)={med:.1f} / 人気別ベース {len(base_rate)}帯")

    def cells(period_from, period_to, tag):
        # 6人気以下のみ・4セルの残差
        acc = {('低', 'O'): [0, 0.0, 0], ('高', 'U'): [0, 0.0, 0],
               ('高', 'O'): [0, 0.0, 0], ('低', 'U'): [0, 0.0, 0]}
        # [n, sum_resid, top3]
        for (y, nk, cs, ap, t3) in samples:
            if not (period_from <= y <= period_to) or nk < 6:
                continue
            hi = '高' if ap >= med else '低'
            key = (hi, cs)
            resid = t3 - base_rate.get(nk, 0.22)
            acc[key][0] += 1
            acc[key][1] += resid
            acc[key][2] += t3
        print(f"\n=== {tag} (6人気以下) ===")
        print(f"{'セル':<12}{'n':>7}{'複勝%':>7}{'残差pp':>8}")
        m = {}
        for key, (n, sres, t3) in acc.items():
            lbl = f"{key[0]}PCI×{key[1]}字"
            if n < 30:
                print(f"{lbl:<12}{n:>7} (n<30)")
                m[key] = None
                continue
            mres = sres / n
            print(f"{lbl:<12}{n:>7}{t3/n*100:>7.1f}{mres*100:>+8.2f}")
            m[key] = {'n': n, 'mres': mres, 'p': t3 / n}
        # 交互作用コントラスト C = (低O + 高U) - (高O + 低U)
        need = [('低', 'O'), ('高', 'U'), ('高', 'O'), ('低', 'U')]
        if any(m.get(k) is None for k in need):
            print("  → セル不足で交互作用評価不能")
            return None
        C = (m[('低', 'O')]['mres'] + m[('高', 'U')]['mres']
             - m[('高', 'O')]['mres'] - m[('低', 'U')]['mres'])
        var = sum(m[k]['p'] * (1 - m[k]['p']) / m[k]['n'] for k in need)
        z = C / math.sqrt(var) if var > 0 else 0
        print(f"  交互作用コントラスト C={C*100:+.2f}pp  z={z:+.2f}  "
              f"(正=マッチ馬が人気超え=仮説成立)")
        return {'C': C, 'z': z}

    cells(2021, 2024, 'train 2021-24')
    rh = cells(2025, 2025, 'holdout 2025')
    cells(2026, 2026, 'confirm 2026')

    print("\n" + "=" * 56)
    print("採用ゲート(カード6): holdout2025 交互作用 C>0 かつ z>=2.0")
    if not rh:
        print("判定: ❌ 却下(セル不足)→ PCIは完全終了")
    elif rh['C'] > 0 and rh['z'] >= 2.0:
        print(f"判定: ✅ 採用 (C={rh['C']*100:+.2f}pp z={rh['z']:+.2f}) → 相手ファクター配線可")
    else:
        print(f"判定: ❌ 却下 (C={rh['C']*100:+.2f}pp z={rh['z']:+.2f} が仮説方向×z2.0未達)"
              f" → PCIは完全終了・再提案打ち切り")


if __name__ == '__main__':
    main()
