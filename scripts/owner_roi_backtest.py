# -*- coding: utf-8 -*-
"""馬主特徴の検証 ―― カード4(④)①馬主ROI/複勝残差 ＋ ③馬主×厩舎。

owner_cache.json(scripts/owner_pilot_collect.py)+jravan.db で、各レース時点の
馬主の"過去"成績を逐次計算(リーク無し)。純粋な馬主シグナルを見るため
【自馬の走りは除外】し、馬主の"他の馬"の過去成績のみで prior を作る。

検証:
  ① 馬主prior複勝率tier(train中央値で凍結) → holdout2025で複勝残差z・単勝ROI
     (ユーザー関心=馬主ごとの回収率。ROIは市場効率で±の目安)
  ③ 馬主×厩舎ペアのprior複勝率tier → 同様に残差z
採用ゲート: holdout2025で 複勝残差 z>=2.0(6人気以下 or 全体)。
  満たさねば「馬主も織込み済み(厩舎全体勝率と同型)」として却下。
  ①が却下でも③(交互作用)が生きる場合あり→両方見る。

前提: 単勝ROIは市場効率が既定([[verified_tansho_roi_efficient]])。ROIプラス主張は原則しない。
"""
import os
import sys
import io
import json
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
CACHE = 'scripts/debug/owner_cache.json'
MIN_PRIOR = 30      # 馬主の"他馬"過去走 最低数
MIN_PAIR_PRIOR = 15  # 馬主×厩舎ペアの最低数


def zprop(hits, n, exp_sum):
    if n < 20:
        return None
    p = hits / n
    e = exp_sum / n
    var = n * e * (1 - e)
    z = (hits - exp_sum) / math.sqrt(var) if var > 0 else 0
    return {'n': n, 'p': p, 'resid': (p - e) * 100, 'z': z}


def contrast_z(hi, lo):
    """高tier残差 − 低tier残差 の z(=純粋な馬主質シグナル・一様な選抜バイアスを打消し)。
    これが本命の検定。単tierのzは選抜バイアスを含むので使わない。"""
    if not hi or not lo:
        return None
    diff = (hi['resid'] - lo['resid']) / 100.0  # pp→比率
    se = math.sqrt(hi['p'] * (1 - hi['p']) / hi['n'] + lo['p'] * (1 - lo['p']) / lo['n'])
    return {'diff_pp': hi['resid'] - lo['resid'], 'z': diff / se if se > 0 else 0}


def main():
    if not os.path.exists(CACHE):
        print('owner_cache.json が無い。先に owner_pilot_collect.py を回す。')
        return
    with open(CACHE, encoding='utf-8') as f:
        cache = json.load(f)
    owner_of = {k: v.get('owner_id') for k, v in cache.items() if v.get('owner_id')}
    print(f'キャッシュ {len(cache)}頭 / 馬主ID有り {len(owner_of)}頭')

    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    kets = list(owner_of.keys())
    q = f"""SELECT r.ketto_num, ra.year, ra.monthday, r.chakujun, r.ninki, r.win_odds,
                   r.trainer_code
            FROM results r JOIN races ra ON ra.race_key=r.race_key
            WHERE ra.jyo BETWEEN '01' AND '10' AND r.chakujun>0
              AND r.ketto_num IN ({','.join('?'*len(kets))})"""
    rows = con.execute(q, kets).fetchall()
    con.close()
    print(f'jravan結合: {len(rows):,}走')

    # レコード整形 + 時系列キー
    recs = []
    for ket, y, md, chaku, ninki, wo, tc in rows:
        oid = owner_of.get(ket)
        if not oid or not ninki or ninki <= 0:
            continue
        recs.append({'ket': ket, 'oid': oid, 'd': int(y) * 10000 + int(md),
                     'y': int(y), 'chaku': chaku, 'ninki': int(ninki),
                     'wo': wo or 0, 'tc': tc, 't3': 1 if chaku <= 3 else 0,
                     'win': 1 if chaku == 1 else 0})
    recs.sort(key=lambda x: x['d'])

    # 馬主別/ペア別の逐次prior(自馬除外はレース処理時にketで判定)
    owner_runs = defaultdict(list)   # oid -> [(d, ket, t3, win, wo)]
    pair_runs = defaultdict(list)    # (oid,tc) -> [(d, ket, t3)]
    for r in recs:
        owner_runs[r['oid']].append((r['d'], r['ket'], r['t3'], r['win'], r['wo']))
        pair_runs[(r['oid'], r['tc'])].append((r['d'], r['ket'], r['t3']))

    # train2023-24 で 人気別ベース + 馬主tier中央値 を凍結
    base = defaultdict(lambda: [0, 0])
    for r in recs:
        if 2023 <= r['y'] <= 2024:
            base[r['ninki']][0] += r['t3']
            base[r['ninki']][1] += 1
    base_rate = {k: (v[0] / v[1] if v[1] else 0.22) for k, v in base.items()}

    def owner_prior(oid, ket, d):
        """馬主の"他馬"のd未満の成績。戻り: (n, fuku_rate, roi) or None"""
        n = t3 = win = 0
        roi = 0.0
        for (dd, kk, tt, ww, wo) in owner_runs.get(oid, []):
            if dd >= d or kk == ket:  # 未来と自馬を除外
                continue
            n += 1
            t3 += tt
            win += ww
            roi += wo if ww else 0
        if n < MIN_PRIOR:
            return None
        return n, t3 / n, roi / n

    # train中央値(馬主prior複勝率)
    tr_rates = []
    for r in recs:
        if not (2023 <= r['y'] <= 2024):
            continue
        pr = owner_prior(r['oid'], r['ket'], r['d'])
        if pr:
            tr_rates.append(pr[1])
    tr_rates.sort()
    med = tr_rates[len(tr_rates) // 2] if tr_rates else 0.30
    print(f'凍結: 馬主prior複勝率 中央値={med:.3f} (train n={len(tr_rates)})')

    # ── ① 馬主単体: holdout2025 ──
    def eval_owner(year_lo, year_hi, band=None, tag=''):
        acc = {'高': {'n': 0, 't3': 0, 'exp': 0.0, 'roi': 0.0},
               '低': {'n': 0, 't3': 0, 'exp': 0.0, 'roi': 0.0}}
        for r in recs:
            if not (year_lo <= r['y'] <= year_hi):
                continue
            if band == '6+' and r['ninki'] < 6:
                continue
            pr = owner_prior(r['oid'], r['ket'], r['d'])
            if not pr:
                continue
            tier = '高' if pr[1] >= med else '低'
            a = acc[tier]
            a['n'] += 1
            a['t3'] += r['t3']
            a['exp'] += base_rate.get(r['ninki'], 0.22)
            a['roi'] += r['wo'] if r['win'] else 0
        print(f'\n=== ① 馬主prior複勝率tier {tag} ===')
        print(f"{'tier':<6}{'n':>7}{'複勝%':>7}{'残差pp':>8}{'z':>7}{'単ROI%':>8}")
        res = {}
        for tier in ('高', '低'):
            a = acc[tier]
            zz = zprop(a['t3'], a['n'], a['exp'])
            if not zz:
                print(f'{tier:<6}{a["n"]:>7} (n<20)')
                res[tier] = None
                continue
            roi = a['roi'] / a['n'] * 100
            print(f"{tier:<6}{a['n']:>7}{zz['p']*100:>7.1f}{zz['resid']:>+8.2f}{zz['z']:>+7.2f}{roi:>8.1f}")
            res[tier] = zz
        return res

    r_all = eval_owner(2025, 2025, tag='(holdout2025 全体)')
    r_ana = eval_owner(2025, 2025, band='6+', tag='(holdout2025 6人気以下)')

    # ── ③ 馬主×厩舎ペア: holdout2025 ──
    def pair_prior(oid, tc, ket, d):
        n = t3 = 0
        for (dd, kk, tt) in pair_runs.get((oid, tc), []):
            if dd >= d or kk == ket:
                continue
            n += 1
            t3 += tt
        return (n, t3 / n) if n >= MIN_PAIR_PRIOR else None

    pr_rates = []
    for r in recs:
        if 2023 <= r['y'] <= 2024:
            pp = pair_prior(r['oid'], r['tc'], r['ket'], r['d'])
            if pp:
                pr_rates.append(pp[1])
    pr_rates.sort()
    pmed = pr_rates[len(pr_rates) // 2] if pr_rates else 0.30

    acc = {'高': {'n': 0, 't3': 0, 'exp': 0.0}, '低': {'n': 0, 't3': 0, 'exp': 0.0}}
    for r in recs:
        if r['y'] != 2025:
            continue
        pp = pair_prior(r['oid'], r['tc'], r['ket'], r['d'])
        if not pp:
            continue
        tier = '高' if pp[1] >= pmed else '低'
        a = acc[tier]
        a['n'] += 1
        a['t3'] += r['t3']
        a['exp'] += base_rate.get(r['ninki'], 0.22)
    print(f'\n=== ③ 馬主×厩舎ペアprior複勝率tier (holdout2025・中央値{pmed:.3f}) ===')
    print(f"{'tier':<6}{'n':>7}{'複勝%':>7}{'残差pp':>8}{'z':>7}")
    r_pair = {}
    for tier in ('高', '低'):
        a = acc[tier]
        zz = zprop(a['t3'], a['n'], a['exp'])
        if not zz:
            print(f'{tier:<6}{a["n"]:>7} (n<20)')
            r_pair[tier] = None
            continue
        print(f"{tier:<6}{a['n']:>7}{zz['p']*100:>7.1f}{zz['resid']:>+8.2f}{zz['z']:>+7.2f}")
        r_pair[tier] = zz

    # ── 判定(高-低コントラストz=馬主質の純粋シグナル) ──
    print('\n' + '=' * 60)
    print('採用ゲート: holdout2025 高-低コントラスト |z|>=2.0(一様な選抜バイアスを打消した純シグナル)')

    def verdict(label, res):
        c = contrast_z(res.get('高'), res.get('低'))
        if not c:
            print(f'  {label}: n不足で評価不能')
            return False
        if abs(c['z']) >= 2.0:
            print(f'  {label}: ✅ 有意 (高-低={c["diff_pp"]:+.2f}pp z={c["z"]:+.2f}) → 深掘り価値あり')
            return True
        print(f'  {label}: ❌ 却下 (高-低={c["diff_pp"]:+.2f}pp z={c["z"]:+.2f} 未達=織込み済み)')
        return False
    a1 = verdict('①馬主 全体', r_all)
    a2 = verdict('①馬主 6人気以下', r_ana)
    a3 = verdict('③馬主×厩舎', r_pair)
    if not (a1 or a2 or a3):
        print('\n総合: ❌ 馬主も織込み済み(厩舎全体勝率と同型)。単勝ROIも全帯<100=市場効率的。')
        print('  → ①③は打ち切り。残るは②地方・中央の使い分け(別ビルド・独立に生きうる)。')
    else:
        print('\n総合: ✅ どこかにエッジの気配→拡大収集(representative sample)で再検証へ。')


if __name__ == '__main__':
    main()
