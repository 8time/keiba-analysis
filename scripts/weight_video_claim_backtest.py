# -*- coding: utf-8 -*-
"""動画「馬体重増減だけで消すな」主張の検証。

主張の核:
  1) 大型馬ほど有利（400kg未満複勝~7% / 500kg台~25% / 540kg超は回収優秀）
  2) -10〜-19kg は切るほど悪くない（複17.3% / 単回収68）
     -20kg以上は警戒（複10.2% / 単回収47）
  3) +20kg以上は複勝平凡でも単回収93＝市場が太りを嫌って過小評価
  4) 見るべきは前走比より「過去好走時体重との距離」
  5) 年齢（若馬の増＝成長 / 6歳以上の増＝太め）・夏の減・滞在/遠征減
  6) エンジンには消し条件ではなく「能力上位なのに体重で人気が落ちた」妙味

判定（プロジェクト慣例）:
  穴馬ハンター候補 = 6番人気以下・見る(〜2024)と確認(2025)の両方で
                     複残差 z>=+2 かつ n>=200 かつ残差>0
  危険/消去        = 1-3番人気で両窓 z<=-2 かつ n>=200
                     （絶対複勝<20%なら消去寄り。高ければ単独では切らない）
  単回収の生数字は参考。判定はオッズ帯統制の複勝残差。

Usage: python scripts/weight_video_claim_backtest.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import jockey_jv as jj
from scripts import csv_data as cd

MIN_N = 200
Z_HUNTER = 2.0
Z_FADE = -2.0
NORTH = {1, 2}      # 札幌・函館
KOKURA = {10}


def _band_exp(odds, exp, key, default):
    bands = odds.map(jj._odds_band)
    return bands.map(lambda b: (exp.get(b) or {}).get(key, default)).astype(float)


def stats(sub, e3):
    n = len(sub)
    if n == 0:
        return None
    t3 = sub['top3'].to_numpy()
    win = sub['win'].to_numpy()
    odds = sub['win_odds'].to_numpy()
    resid = t3 - e3.loc[sub.index].to_numpy()
    se = (0.22 * 0.78 / n) ** 0.5
    z = (resid.mean() / se) if se > 0 else 0.0
    pay = np.where(win == 1, odds, 0.0).sum()
    return {
        'n': n,
        'hit': float(t3.mean()),
        'win': float(win.mean()),
        'roi': float(pay / n),
        'z': float(z),
        'resid': float(resid.mean()),
    }


def fmt(s):
    if s is None:
        return 'n=0'
    if s['n'] < MIN_N:
        return f"n={s['n']:6d}  (標本不足)"
    return (f"n={s['n']:6d} 複{s['hit']:5.1%} 勝{s['win']:5.1%} "
            f"単ROI{s['roi']:6.1%} 複残差{s['resid']*100:+5.2f}pp z={s['z']:+5.2f}")


def both_ok(train, hold, z_min=None, z_max=None):
    if train is None or hold is None:
        return False
    if train['n'] < MIN_N or hold['n'] < MIN_N:
        return False
    if z_min is not None and not (train['z'] >= z_min and hold['z'] >= z_min):
        return False
    if z_max is not None and not (train['z'] <= z_max and hold['z'] <= z_max):
        return False
    return True


def gate_label(train, hold, pop_name):
    hunter = pop_name == '6番人気以下' and both_ok(train, hold, z_min=Z_HUNTER)
    if hunter and train['resid'] > 0 and hold['resid'] > 0:
        return '★穴馬候補(6番以下 両窓 z>=+2)'
    danger = pop_name in ('1-3番人気', '全体') and both_ok(train, hold, z_max=Z_FADE)
    if danger and pop_name == '1-3番人気':
        if hold['hit'] < 0.20:
            return '★危険+消去候補(両窓 z<=-2 かつ絶対複<20%)'
        return '★危険候補(1-3人気 両窓 z<=-2 / 絶対率は高いので単独では切らない)'
    if danger and pop_name == '全体':
        return '★全体fade(両窓 z<=-2)＝買い妙味なし'
    return 'ゲート未達'


def run_block(title, conds, pops, periods, df, e3, collect):
    print(f'\n{"=" * 72}')
    print(title)
    print('=' * 72)
    for pop_name, pop in pops.items():
        print(f'\n-------- {pop_name} --------')
        for cname, cmask in conds:
            print(f'--- {cname} ---')
            row = {'block': title, 'pop': pop_name, 'cond': cname}
            for pname, pm in periods.items():
                st = stats(df[pop & cmask & pm], e3)
                row[pname] = st
                print(f'  {pname:12s} {fmt(st)}')
            row['verdict'] = gate_label(
                row['見る(〜2024)'], row['確認(2025)'], pop_name)
            print('  → ' + row['verdict'])
            collect.append(row)


def past_best_weight(df):
    """馬ごと・過去の3着内体重の中央値（今回は含めない＝リーク無し）。"""
    order = np.lexsort((df['race_key'].to_numpy(),
                        df['day'].to_numpy(),
                        df['ketto_num'].to_numpy()))
    ketto = df['ketto_num'].to_numpy()[order]
    w = df['bataiju'].to_numpy()[order]
    t3 = df['top3'].to_numpy()[order]
    out = np.full(len(df), np.nan)
    hist = {}
    for i in range(len(df)):
        k = ketto[i]
        lst = hist.get(k)
        if lst:
            out[order[i]] = float(np.median(lst))
        if t3[i] == 1 and np.isfinite(w[i]):
            hist.setdefault(k, []).append(float(w[i]))
    return pd.Series(out, index=df.index)


def region(j):
    try:
        j = int(j)
    except (TypeError, ValueError):
        return 'unk'
    if j in NORTH:
        return 'hokkaido'
    if j in KOKURA:
        return 'kokura'
    if j in (3, 4, 5, 6):
        return 'east'
    if j in (7, 8, 9):
        return 'west'
    return 'unk'


def main():
    cols = [
        'race_key', 'day', 'jyo', 'ketto_num', 'ninki', 'win_odds',
        'bataiju', 'zogen', 'age', 'h7_rank', 'ability_score',
        'chakujun', 'top3', 'win',
    ]
    df = cd.load_horses(cols=cols)
    df['bataiju'] = pd.to_numeric(df['bataiju'], errors='coerce')
    df['zogen'] = pd.to_numeric(df['zogen'], errors='coerce')
    df['age'] = pd.to_numeric(df['age'], errors='coerce')
    df['win_odds'] = pd.to_numeric(df['win_odds'], errors='coerce')
    df['ninki'] = pd.to_numeric(df['ninki'], errors='coerce')
    df['jyo'] = pd.to_numeric(df['jyo'], errors='coerce')
    df['h7_rank'] = pd.to_numeric(df['h7_rank'], errors='coerce')
    df['ability_score'] = pd.to_numeric(df['ability_score'], errors='coerce')
    df = df[
        (df['bataiju'] >= 300) & (df['bataiju'] <= 700)
        & df['zogen'].notna() & (df['zogen'].abs() <= 80)
        & (df['win_odds'] > 0) & (df['ninki'] > 0)
        & df['chakujun'].notna()
    ].copy()
    df['month'] = (df['day'] // 100) % 100
    df['summer'] = df['month'].isin([6, 7, 8, 9])
    df = df.sort_values(['ketto_num', 'day', 'race_key'])
    df['prev_jyo'] = df.groupby('ketto_num')['jyo'].shift(1)
    df['best_w'] = past_best_weight(df)
    df['d_best'] = df['bataiju'] - df['best_w']
    df['near_best'] = df['d_best'].abs() <= 4
    df['far_best'] = df['d_best'].abs() >= 12
    _rj = df['jyo'].map(region)
    _rp = df['prev_jyo'].map(region)
    df['long_haul'] = (
        df['prev_jyo'].notna()
        & (_rj != _rp)
        & (df['jyo'].isin(NORTH | KOKURA) | df['prev_jyo'].isin(NORTH | KOKURA))
    )
    stay = df['jyo'].isin(NORTH | KOKURA)

    exp = jj.calibrate_odds_expectation()
    e3 = _band_exp(df['win_odds'], exp, 'top3', 0.22)

    pops = {
        '全体': pd.Series(True, index=df.index),
        '1-3番人気': df['ninki'] <= 3,
        '6番人気以下': df['ninki'] >= 6,
    }
    periods = {
        '見る(〜2024)': df['period'] == 'train',
        '確認(2025)': df['period'] == 'holdout',
        '直近2026': df['period'] == 'recent',
    }
    collect = []

    print('=== 動画「馬体重だけで消すな」検証 ===')
    print(f'JRA平地 CSV n={len(df):,}  '
          f"train={(df['period']=='train').sum():,}  "
          f"holdout={(df['period']=='holdout').sum():,}  "
          f"recent={(df['period']=='recent').sum():,}")
    print('判定は複勝残差（同オッズ帯の期待複勝との差）。単ROIは参考。')

    # 生数字（動画の表と並べる・期間は見る窓）
    print('\n' + '=' * 72)
    print('【参考】動画の生数字 vs 当データ見る窓(〜2024) 全体・オッズ統制なし')
    print('=' * 72)
    raw = [
        ('400kg未満', df['bataiju'] < 400, '複~7%'),
        ('500-539kg', (df['bataiju'] >= 500) & (df['bataiju'] < 540), '複~25%'),
        ('540kg超', df['bataiju'] >= 540, '複はやや低下・回収優秀'),
        ('-10〜-19kg', (df['zogen'] <= -10) & (df['zogen'] >= -19), '複17.3% / 単68'),
        ('-20kg以下', df['zogen'] <= -20, '複10.2% / 単47'),
        ('+20kg以上', df['zogen'] >= 20, '複17.9% / 単93'),
        ('±9kg以内', df['zogen'].abs() <= 9, '通常'),
    ]
    tr = df['period'] == 'train'
    for name, mask, claim in raw:
        st = stats(df[mask & tr], e3)
        print(f'  {name:12s} 動画「{claim}」  実測 {fmt(st)}')

    w = df['bataiju']
    z = df['zogen']
    run_block(
        '① 馬体重の水準（大型有利？）',
        [
            ('400kg未満', w < 400),
            ('400-439kg', (w >= 400) & (w < 440)),
            ('440-499kg', (w >= 440) & (w < 500)),
            ('500-539kg', (w >= 500) & (w < 540)),
            ('540kg超', w >= 540),
        ],
        pops, periods, df, e3, collect,
    )

    run_block(
        '②③ 増減バケツ（動画の切れ目）',
        [
            ('-20kg以下', z <= -20),
            ('-10〜-19kg', (z <= -10) & (z >= -19)),
            ('-9〜-3kg', (z <= -3) & (z >= -9)),
            ('±2kg', z.abs() <= 2),
            ('+3〜+9kg', (z >= 3) & (z <= 9)),
            ('+10〜+19kg', (z >= 10) & (z <= 19)),
            ('+20kg以上', z >= 20),
        ],
        pops, periods, df, e3, collect,
    )

    run_block(
        '③b 核心「体重増 × 人気落ち」',
        [
            ('+20kg×6番以下', (z >= 20) & (df['ninki'] >= 6)),
            ('+10〜19×6番以下', (z >= 10) & (z <= 19) & (df['ninki'] >= 6)),
            ('能力上位(補正T4位以内)×+10kg以上×6番以下',
             (df['h7_rank'] <= 4) & (z >= 10) & (df['ninki'] >= 6)),
            ('能力上位×+20kg×6番以下',
             (df['h7_rank'] <= 4) & (z >= 20) & (df['ninki'] >= 6)),
            ('+20kg×1-3番人気', (z >= 20) & (df['ninki'] <= 3)),
            ('-20kg×1-3番人気', (z <= -20) & (df['ninki'] <= 3)),
        ],
        {'全体': pops['全体'], '6番人気以下': pops['6番人気以下'],
         '1-3番人気': pops['1-3番人気']},
        periods, df, e3, collect,
    )

    run_block(
        '④ 過去好走時体重との距離（リーク無し）',
        [
            ('好走体重±4kg以内', df['near_best'] & df['best_w'].notna()),
            ('好走体重から12kg以上ズレ', df['far_best'] & df['best_w'].notna()),
            ('前走+10kg以上だが好走ゾーン内',
             (z >= 10) & df['near_best'] & df['best_w'].notna()),
            ('前走+10kg以上かつ好走ゾーンから12kgズレ',
             (z >= 10) & df['far_best'] & df['best_w'].notna()),
            ('前走-10kg以下だが好走ゾーン内',
             (z <= -10) & df['near_best'] & df['best_w'].notna()),
        ],
        pops, periods, df, e3, collect,
    )

    run_block(
        '⑤ 年齢 × 増減',
        [
            ('2-3歳 × +10kg以上', (df['age'] <= 3) & (z >= 10)),
            ('6歳以上 × +10kg以上', (df['age'] >= 6) & (z >= 10)),
            ('2-3歳 × -10kg以下', (df['age'] <= 3) & (z <= -10)),
            ('6歳以上 × -10kg以下', (df['age'] >= 6) & (z <= -10)),
        ],
        pops, periods, df, e3, collect,
    )

    run_block(
        '⑥ 夏場の増減',
        [
            ('夏(6-9月) × -10kg以下', df['summer'] & (z <= -10)),
            ('夏 × -20kg以下', df['summer'] & (z <= -20)),
            ('夏 × +10kg以上', df['summer'] & (z >= 10)),
            ('夏以外 × -10kg以下', (~df['summer']) & (z <= -10)),
        ],
        pops, periods, df, e3, collect,
    )

    run_block(
        '⑦ 滞在場(札幌/函館/小倉)・遠征の減',
        [
            ('札幌函館小倉 × -10kg以下', stay & (z <= -10)),
            ('同場 × ±9kg', stay & (z.abs() <= 9)),
            ('遠征(北/小倉またぎ) × -10kg以下', df['long_haul'] & (z <= -10)),
            ('遠征 × ±9kg', df['long_haul'] & (z.abs() <= 9)),
        ],
        pops, periods, df, e3, collect,
    )

    stars = [r for r in collect if str(r.get('verdict', '')).startswith('★')]
    print('\n' + '=' * 72)
    print('【ゲート通過】')
    print('=' * 72)
    if not stars:
        print('  なし。動画の「+20kgを買え」「大型は回収優秀」は両窓の穴馬ゲートを超えない。')
    else:
        for r in stars:
            print(f"  {r['verdict']} ｜ {r['pop']} ｜ {r['cond']}")

    print('\n【エンジンへの含意】')
    print('  ・数字だけで切るな、は生複勝では一理ある（-10〜-19は-20よりマシ）。')
    print('  ・ただし判定は残差。織込み済みなら「嫌われて妙味」は出ない。')
    print('  ・既存: 小柄×馬体減 / 馬体増+8kgは fade デバフ済み。')
    print('  ・elim_cross の体重±16kg は「来にくさ」フラグで妙味発見ではない。')
    print('  ・+20kgを期待値ルールにするのは、ゲート未達なら実装しない。')


if __name__ == '__main__':
    main()
