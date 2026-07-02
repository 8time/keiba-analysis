# -*- coding: utf-8 -*-
"""地方・中央の使い分け検証 ―― カード4②(ユーザー関心)。

jravan.dbはNAR結果(jyo 30-55・100万走・ketto_num付)も含むので、追加スクレイプ無しで
馬ごとの地方↔中央タイムラインが引ける。各JRA出走の『前走が地方だったか』は前走=発走前に
確定=リーク無し。

仮説: 連(厩舎/馬主)の地方・中央の使い分け=『地方帰り(前走NAR)のJRA出走馬』は人気を超えるか。
  H1 前走NAR全体(地方帰り/転入)
  H2 前走NAR×中央経験あり(JRA→…→NAR→JRA 立て直し戻り)
  H3 前走NAR×NAR育ち初転入(過去JRA走なし)
  H4 前走NAR×6人気以下(相手妙味)
指標: 人気別ベース(train2021-24 JRA)に対する複勝残差z + 単勝ROI。
採用ゲート: holdout2025で |残差z|>=2.0 かつ 符号が pooled(2021-25) と一致。
  満たさねば「地方帰りも織込み済み」で②も打ち切り。

前提: 単勝ROIは市場効率が既定([[verified_tansho_roi_efficient]])。ROIプラス主張は原則しない。
リーク厳守: 前走の場/日付のみ使用(発走前確定)。当該JRA走の着順は結果側。
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

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')


def is_jra(jyo):
    return '01' <= str(jyo) <= '10'


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    rows = con.execute("""
        SELECT r.ketto_num, ra.year, ra.monthday, ra.jyo, r.chakujun, r.ninki, r.win_odds
        FROM results r JOIN races ra ON ra.race_key=r.race_key
        WHERE CAST(ra.year AS INTEGER) BETWEEN 2018 AND 2025
          AND r.chakujun>0 AND r.ketto_num IS NOT NULL
    """).fetchall()
    con.close()

    hist = defaultdict(list)
    for ket, y, md, jyo, ch, nk, wo in rows:
        hist[ket].append({'d': int(y) * 10000 + int(md), 'jyo': jyo, 'y': int(y),
                          'ch': ch, 'nk': nk or 0, 'wo': wo or 0})
    for k in hist:
        hist[k].sort(key=lambda x: x['d'])

    # サンプル: JRA走 + 前走属性
    samples = []  # (y, ninki, t3, win, wo, prev_nar, had_jra, is_debut_nar)
    for ket, runs in hist.items():
        for i, r in enumerate(runs):
            if not is_jra(r['jyo']) or not r['nk'] or r['nk'] <= 0:
                continue
            prev_nar = i > 0 and not is_jra(runs[i - 1]['jyo'])
            had_jra = any(is_jra(runs[j]['jyo']) for j in range(i))
            samples.append((r['y'], int(r['nk']), 1 if r['ch'] <= 3 else 0,
                            1 if r['ch'] == 1 else 0, r['wo'],
                            prev_nar, had_jra, prev_nar and not had_jra))

    # 人気別ベース(train2021-24 JRA全走)
    base = defaultdict(lambda: [0, 0])
    for (y, nk, t3, *_ ) in samples:
        if 2021 <= y <= 2024:
            base[nk][0] += t3
            base[nk][1] += 1
    base_rate = {k: (v[0] / v[1] if v[1] else 0.22) for k, v in base.items()}

    def agg(pred, y_lo, y_hi):
        n = t3 = win = 0
        exp = roi = 0.0
        for (y, nk, tt, ww, wo, pnar, hadj, debut) in samples:
            if not (y_lo <= y <= y_hi) or not pred(nk, pnar, hadj, debut):
                continue
            n += 1
            t3 += tt
            win += ww
            exp += base_rate.get(nk, 0.22)
            roi += wo if ww else 0
        if n < 20:
            return {'n': n, 'small': True}
        p = t3 / n
        e = exp / n
        var = n * e * (1 - e)
        z = (t3 - exp) / math.sqrt(var) if var > 0 else 0
        return {'n': n, 'p': p, 'resid': (p - e) * 100, 'z': z, 'roi': roi / n * 100}

    groups = [
        ('H1 前走NAR(地方帰り/転入)', lambda nk, pn, hj, db: pn),
        ('H2 前走NAR×中央経験(立て直し戻り)', lambda nk, pn, hj, db: pn and hj),
        ('H3 前走NAR×NAR育ち初転入', lambda nk, pn, hj, db: db),
        ('H4 前走NAR×6人気以下(相手)', lambda nk, pn, hj, db: pn and nk >= 6),
        ('(対照)前走JRA全体', lambda nk, pn, hj, db: not pn),
    ]

    for tag, y0, y1 in [('pooled 2021-2025', 2021, 2025), ('holdout 2025', 2025, 2025)]:
        print(f"\n=== {tag} ===")
        print(f"{'群':<30}{'n':>7}{'複勝%':>7}{'残差pp':>8}{'z':>7}{'単ROI%':>8}")
        print('-' * 68)
        for name, pred in groups:
            r = agg(pred, y0, y1)
            if r.get('small'):
                print(f"{name:<30}{r['n']:>7} (n<20)")
                continue
            print(f"{name:<30}{r['n']:>7}{r['p']*100:>7.1f}{r['resid']:>+8.2f}{r['z']:>+7.2f}{r['roi']:>8.1f}")

    # 判定: H1〜H4 の holdout z と pooled z の符号一致 & |holdout z|>=2
    print('\n' + '=' * 68)
    print('採用ゲート: holdout2025 |残差z|>=2.0 かつ pooledと符号一致')
    any_edge = False
    for name, pred in groups[:4]:
        rp = agg(pred, 2021, 2025)
        rh = agg(pred, 2025, 2025)
        if rp.get('small') or rh.get('small'):
            print(f"  {name}: n不足")
            continue
        ok = abs(rh['z']) >= 2.0 and (rp['z'] * rh['z'] > 0)
        mark = '✅ 深掘り価値' if ok else '❌ 却下'
        print(f"  {name}: pooled z={rp['z']:+.2f} / holdout z={rh['z']:+.2f} → {mark}")
        any_edge = any_edge or ok
    if not any_edge:
        print('\n総合: ❌ 地方・中央の使い分け(地方帰り)も織込み済み → ②打ち切り。')
    else:
        print('\n総合: ✅ 気配あり→サブタイプ深掘り/owner_cacheと連×使い分けへ。')


if __name__ == '__main__':
    main()
