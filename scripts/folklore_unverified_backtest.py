# -*- coding: utf-8 -*-
"""俗説ハンター「未検証(U)だが出馬表系データで検証可能」39項目の一括バックテスト。

対象: core/folklore_lib.py の CATALOG で verdict=unverified かつ
match が _always_skip / _tag_m(パドック・調教観察) ではない項目。
フラグ定義は folklore_lib の各 _m_* マッチャを jravan.db 列に忠実に写す。

方法（このプロジェクトの慣例に倣う）:
  - 人気ならし残差: 該当馬の複勝(3着内)率 − 同人気のtrain基準率
  - train  = 2021-2024（基準率・騎手統計の凍結窓）
  - holdout= 2025（本番判定窓）
  - recent = 2026-03-21以降（符号確認）
  - 判定: holdout n>=200 必須。主張方向に z>=2 かつ recent 同符号 → 採用方向。
          逆方向 z<=-2 → 否決(逆)。|z|<1 かつ n>=2000 → 否決(効果なし)。
          ※39件の多重検定なので |z|>=2 かつ2窓符号一致を最低条件とする。

データ上の注意（jravan.db実調査で判明）:
  - JRA平地(jyo 01-10)に限定（同DBの地方行はgrade体系が別で混ぜられない）。
  - 条件戦のrace_nameは空のため、クラス階級は **出走メンバーのキャリアから導出**:
    grade A/B/C→G1/G2/G3、L→リステッド、それ以外は
    全馬初出走→新馬(0)、最大勝数 0→未勝利(1)、1→1勝(2)、2→2勝(3)、3→3勝(4)、4+→OP(5)。
    （2019-06以降のJRAは勝数クラス制なのでeval窓2021+では正確）
  - 馬の経歴（前走・初場所・初距離・初ブリンカー）は2014年以降のJRA有効走から構築。
    2013年以前にデビューした古馬の初場所判定にわずかな切詰め誤差あり。

Usage: python scripts/folklore_unverified_backtest.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'jravan.db')
OUT_JSON = os.path.join(ROOT, 'data', 'folklore_unverified_summary.json')

HIST_FROM = 2014          # 前走・経歴の参照は2014年から（評価は2021年から）
TRAIN_YEARS = (2021, 2024)
HOLDOUT_YEAR = 2025
RECENT_FROM = 20260321
MIN_N = 200
BIG_N = 2000

LOCAL_JYO = {'01', '02', '03', '04', '07', '10'}  # 札幌函館福島新潟中京小倉
WET = {'2', '3', '4'}                              # 稍重/重/不良

# (id, 主張の向き +1=買い / -1=消し, 日本語タイトル)
ITEMS = [
    ('blinker_on',        +1, 'ブリンカー着用は集中して買い'),
    ('top_jockey',        +1, '強い騎手だから買い'),
    ('course_jockey',     +1, 'この騎手はこのコースに強い'),
    ('weight_minus20',    -1, '馬体重-20kgは消し'),
    ('age4',              +1, '4歳は完成期で買い'),
    ('short_rest',        +1, '連闘・中1週は買い'),
    ('dirt_layoff',       -1, 'ダートの休み明けは割引'),
    ('prev_close',        +1, '前走僅差の着外は次走買い'),
    ('prev_stakes',       +1, '前走重賞負けは相手が強かったから買い'),
    ('ninki1_solid',      +1, '1番人気は一番強くて堅い'),
    ('filly_fav1_any',    -1, '牝馬の1番人気は信用できない'),
    ('colt_winter',       +1, '冬は牡馬'),
    ('gelding_summer',    -1, '夏負けは夏キン（セン馬は夏弱い）'),
    ('dirt_class_up',     -1, 'ダートの昇級戦は危険'),
    ('maiden_up',         -1, '前走未勝利の昇級馬は信頼できない'),
    ('nige_win_up',       -1, '前走逃げて勝った馬の昇級は負けやすい'),
    ('first_venue',       -1, '初めての競馬場は不安'),
    ('first_dist',        -1, '初めての距離は不安'),
    ('local_rensen',      +1, 'ローカル開催の連闘は勝負気配'),
    ('stay_jockey',       +1, '継続騎乗の方が馬を知っていて有利'),
    ('jockey_up',         +1, '下位騎手から強い騎手への乗り替わりは買い'),
    ('closer_overbet',    -1, '追い込み馬はかっこよくて売れやすい'),
    ('small_field_closer', +1, '少頭数は差し馬を買え'),
    ('closer_blinker',    -1, '追い込み馬のブリンカー装着は危険'),
    ('prev_fluke',        -1, '前走人気薄の好走はフロックで次走飛ぶ'),
    ('wet_to_good',       -1, '前走道悪好走→良馬場は評価が逆転する'),
    ('inner_to_outer',    -1, '前走内枠好走→今回外枠は同じ脚が使えない'),
    ('dirt_out_to_in',    -1, 'ダートで外枠から内枠に変わると砂を被る'),
    ('fav_slow_agari',    -1, '人気馬なのに上がりが遅いのは飛ぶ'),
    ('dirt_front',        +1, 'ダートは逃げ・先行が届く'),
    ('dirt_closer_miss',  -1, 'ダートの差し・追い込みは届かない'),
    ('dirt_small',        -1, 'ダートの440kg以下は苦戦'),
    ('dirt_2yo_power',    +1, 'ダート2歳は460kg以上が優勢'),
    ('open_nakaana',      +1, 'オープン・重賞の中穴（4〜6番人気）は飛びやすい'),
    ('stakes_nige',       -1, '重賞の逃げ先行はマークされて失速しやすい'),
    ('open_cond_win_fav', -1, '条件戦を勝ってオープンの1番人気は飛ぶ'),
    ('maiden_fav1',       +1, '新馬戦の1番人気は信頼できる'),
    ('turf_2yo_small',    +1, '芝の夏2歳新馬は小型馬が穴で走る'),
    ('filly_wear',        -1, '牝馬の馬体重急減は使い減り'),
]


def load_frame():
    import sqlite3
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60)
    q = """
    SELECT r.race_key, r.year, r.monthday, r.jyo, r.waku, r.umaban, r.ketto_num,
           r.sex, r.age, r.futan, r.blinker, r.jockey_name,
           r.bataiju, r.zogen, r.chakujun, r.time,
           r.corner1, r.corner2, r.corner3, r.corner4,
           r.win_odds, r.ninki, r.ato3f, r.ijo,
           ra.race_num, ra.grade, ra.kigo, ra.shubetsu, ra.race_name,
           ra.kyori, ra.surface, ra.baba_shiba, ra.baba_dirt, ra.shusso_tosu
    FROM results r JOIN races ra ON r.race_key = ra.race_key
    WHERE r.year >= ? AND ra.surface IN ('芝','ダート')
      AND ra.jyo IN ('01','02','03','04','05','06','07','08','09','10')
    """
    df = pd.read_sql(q, con, params=(str(HIST_FROM),))
    con.close()
    return df


def parse_time(s):
    """'1543'→94.3秒 / '548'→54.8秒。取れなければNaN。"""
    t = str(s or '').strip()
    if not t or not t.isdigit() or len(t) < 3:
        return np.nan
    try:
        return int(t[:-3]) * 60 + int(t[-3:-1]) + int(t[-1]) / 10.0
    except ValueError:
        return np.nan


def prepare(df):
    for c in ('year', 'waku', 'umaban', 'age', 'blinker', 'bataiju', 'zogen',
              'chakujun', 'ninki', 'kyori', 'shusso_tosu'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['win_odds'] = pd.to_numeric(df['win_odds'], errors='coerce')
    df['ato3f'] = pd.to_numeric(df['ato3f'], errors='coerce')
    df.loc[df['ato3f'] <= 0, 'ato3f'] = np.nan
    df['day'] = (df['year'].astype(int) * 10000
                 + pd.to_numeric(df['monthday'].astype(str).str.zfill(4), errors='coerce')).astype('Int64')
    df['month'] = (df['day'] // 100 % 100).astype('Int64')
    df['dt'] = pd.to_datetime(df['day'], format='%Y%m%d', errors='coerce')
    df['is_dirt'] = df['surface'] == 'ダート'
    df['baba'] = np.where(df['is_dirt'], df['baba_dirt'], df['baba_shiba']).astype(str)
    df['is_wet'] = df['baba'].isin(WET)
    df['is_good'] = df['baba'] == '1'
    df['field'] = df['shusso_tosu']
    df['sex_code'] = df['sex'].astype(str)
    df['time_sec'] = df['time'].map(parse_time)
    df['jockey'] = df['jockey_name'].astype(str).str.replace(r'\s+', '', regex=True)

    # 有効走のみ（中止・失格等は前走として使わない／評価行からも外す）
    df['valid'] = (df['ijo'].astype(str) == '0') & df['chakujun'].between(1, 30)

    df['is_fillies'] = df['kigo'].astype(str).str[1] == '2'

    # レース内の勝ちタイム→着差(秒)
    v = df[df['valid']]
    win_t = v.groupby('race_key')['time_sec'].min().rename('win_time')
    df = df.merge(win_t, on='race_key', how='left')
    df['margin'] = df['time_sec'] - df['win_time']

    # 馬ごとの前走（有効走のみでシフト）
    df = df.sort_values(['ketto_num', 'day', 'race_key']).reset_index(drop=True)
    vidx = df.index[df['valid']]
    vdf = df.loc[vidx].copy()
    g = vdf.groupby('ketto_num', sort=False)
    gid = g.ngroup()

    vdf['runs_before'] = g.cumcount()
    win_i = (vdf['chakujun'] == 1).astype(int)
    vdf['wins_before'] = (win_i.groupby(gid).cumsum() - win_i).to_numpy()

    # クラス階級: 出走メンバーのキャリアから導出（条件戦はrace_nameが空のため）
    race_meta = df.groupby('race_key').agg(grade=('grade', 'first'),
                                           month=('month', 'first'),
                                           shubetsu=('shubetsu', 'first'))
    rmax_w = vdf.groupby('race_key')['wins_before'].max()
    rmax_r = vdf.groupby('race_key')['runs_before'].max()
    gmap = {'A': 8, 'B': 7, 'C': 6, 'L': 5}
    crank = race_meta['grade'].astype(str).map(gmap).copy()
    rest = crank.isna()
    w = rmax_w.reindex(crank.index[rest])
    r = rmax_r.reindex(crank.index[rest])
    derived = pd.Series(np.where(r == 0, 0, np.where(w >= 4, 5, w + 1)),
                        index=crank.index[rest])
    # JRAの未勝利戦は「2歳(6-12月)」と「3歳(1-3月)」にしか存在しない。
    # 全員0勝でも 古馬戦/4月以降の3歳戦 は実態が1勝クラス → 未勝利誤判定を補正
    mo = pd.to_numeric(race_meta['month'].reindex(derived.index), errors='coerce')
    sb = race_meta['shubetsu'].astype(str).reindex(derived.index)
    misl = (derived == 1) & ((sb.isin(['13', '14'])) | ((sb == '12') & (mo >= 4)))
    derived[misl.fillna(False)] = 2
    crank.loc[rest] = derived
    df['crank'] = df['race_key'].map(crank)
    vdf['crank'] = vdf['race_key'].map(crank)

    shift_cols = ['day', 'dt', 'chakujun', 'ninki', 'kyori', 'is_dirt', 'baba',
                  'crank', 'jockey', 'umaban', 'margin', 'field', 'ato3f',
                  'corner1', 'corner2', 'corner3', 'corner4', 'jyo', 'race_name']
    for c in shift_cols:
        vdf['p_' + c] = g[c].shift(1)

    # 前走の通過位置（非ゼロコーナーのみで folklore_lib.passing_nums と同じ扱い）
    for c in ('corner1', 'corner2', 'corner3', 'corner4'):
        vdf[f'p_{c}'] = pd.to_numeric(vdf[f'p_{c}'], errors='coerce')
    pc = vdf[[f'p_{c}' for c in ('corner1', 'corner2', 'corner3', 'corner4')]]
    pc = pc.where(pc > 0)
    vdf['p_passavg'] = pc.mean(axis=1)
    vdf['p_c4'] = pc.ffill(axis=1).iloc[:, -1]
    pc3 = pc.mask(pc.notna().cumsum(axis=1) == pc.notna().sum(axis=1).to_numpy()[:, None])
    vdf['p_c3'] = pc3.ffill(axis=1).iloc[:, -1]  # 最後から2番目
    cnt = pc.notna().sum(axis=1)
    vdf.loc[cnt == 1, 'p_c3'] = pc.loc[cnt == 1].bfill(axis=1).iloc[:, 0]  # 1個だけならそれ
    vdf['p_passratio'] = vdf['p_passavg'] / vdf['p_field']

    # 経歴フラグ（有効走ベース）
    vdf['first_venue'] = (vdf.groupby(['ketto_num', 'jyo'], sort=False).cumcount() == 0) & (vdf['runs_before'] >= 1)
    fd = (vdf.groupby(['ketto_num', 'kyori'], sort=False).cumcount() == 0) & (vdf['runs_before'] >= 1)
    kgrp = vdf.groupby('ketto_num', sort=False)
    c1150 = (vdf['kyori'] == 1150).astype(int)
    c1200 = (vdf['kyori'] == 1200).astype(int)
    had1150 = (c1150.groupby(kgrp.ngroup()).cumsum() - c1150) > 0
    had1200 = (c1200.groupby(kgrp.ngroup()).cumsum() - c1200) > 0
    vdf['first_dist'] = fd & ~((vdf['kyori'] == 1200) & had1150.to_numpy()) & ~((vdf['kyori'] == 1150) & had1200.to_numpy())
    bl = (vdf['blinker'] == 1).astype(int)
    bl_before = bl.groupby(kgrp.ngroup()).cumsum() - bl
    vdf['blinker_first'] = (vdf['blinker'] == 1) & (bl_before.to_numpy() == 0)

    keep = [c for c in vdf.columns if c.startswith('p_') or c in
            ('runs_before', 'first_venue', 'first_dist', 'blinker_first')]
    df = df.merge(vdf[['race_key', 'umaban', 'ketto_num'] + list(dict.fromkeys(keep))],
                  on=['race_key', 'umaban', 'ketto_num'], how='left')

    df['is_open'] = df['crank'] >= 5
    df['is_maiden'] = df['crank'] == 0
    df['gap_days'] = (df['dt'] - df['p_dt']).dt.days
    df['dist_diff'] = df['kyori'] - df['p_kyori']
    df['class_up'] = df['crank'].notna() & df['p_crank'].notna() & (df['crank'] > df['p_crank'])
    df['jockey_changed'] = (df['runs_before'] >= 1) & df['p_jockey'].notna() & (df['jockey'] != df['p_jockey'])
    return df


def add_period(df):
    yr = df['year'].astype(int)
    per = pd.Series('other', index=df.index, dtype=object)
    per[(yr >= TRAIN_YEARS[0]) & (yr <= TRAIN_YEARS[1])] = 'train'
    per[yr == HOLDOUT_YEAR] = 'holdout'
    per[(df['day'] >= RECENT_FROM)] = 'recent'
    df['period'] = per
    return df


def jockey_tables(df):
    """train窓(<=2024)で凍結する騎手統計（リーク防止でholdout/recentには使わない）。"""
    tr = df[(df['valid']) & (df['year'] <= TRAIN_YEARS[1]) & (df['jockey'] != '')]
    gj = tr.groupby('jockey')['chakujun']
    st = gj.agg(rides='size', wins=lambda s: (s == 1).sum())
    top = set(st[(st['rides'] >= 500) & (st['wins'] / st['rides'] >= 0.15)].index)
    gc = tr.groupby(['jockey', 'jyo', 'is_dirt'])['chakujun']
    sc = gc.agg(runs='size', wins=lambda s: (s == 1).sum())
    hot = {f'{a}|{b}|{c}' for a, b, c in
           sc[(sc['runs'] >= 30) & (sc['wins'] / sc['runs'] >= 0.15)].index}
    return top, hot


def add_flags(df, top_jockeys, course_hot):
    p = df
    p['has_prev'] = p['runs_before'] >= 1

    flags = {}
    flags['blinker_on'] = (p['blinker'] == 1) & (p['blinker_first'] != True)
    flags['top_jockey'] = p['jockey'].isin(top_jockeys)
    flags['course_jockey'] = (p['jockey'] + '|' + p['jyo'].astype(str) + '|'
                              + p['is_dirt'].astype(str)).isin(course_hot).to_numpy()
    flags['weight_minus20'] = p['zogen'] <= -20
    flags['age4'] = p['age'] == 4
    flags['short_rest'] = p['gap_days'].between(1, 14)
    flags['dirt_layoff'] = p['is_dirt'] & (p['gap_days'] >= 63)
    flags['prev_close'] = p['p_margin'].gt(0) & (p['p_margin'] <= 0.3) & (p['p_chakujun'] >= 4)
    flags['prev_stakes'] = p['p_crank'].isin([6, 7, 8]) & (p['p_chakujun'] >= 4)
    flags['ninki1_solid'] = p['ninki'] == 1
    flags['filly_fav1_any'] = (p['sex_code'] == '2') & (p['ninki'] == 1) & (~p['is_fillies'])
    flags['colt_winter'] = (p['sex_code'] == '1') & (p['month'].isin([12, 1, 2]))
    flags['gelding_summer'] = (p['sex_code'] == '3') & (p['month'].isin([6, 7, 8]))
    flags['dirt_class_up'] = p['is_dirt'] & p['class_up']
    flags['maiden_up'] = (p['p_crank'] == 1) & p['class_up']
    flags['nige_win_up'] = p['class_up'] & (p['p_chakujun'] == 1) & (p['p_c4'] <= 2)
    flags['first_venue'] = p['first_venue'] == True
    flags['first_dist'] = p['first_dist'] == True
    flags['local_rensen'] = p['jyo'].isin(LOCAL_JYO) & p['gap_days'].between(1, 8)
    flags['stay_jockey'] = p['has_prev'] & p['p_jockey'].notna() & (p['jockey'] == p['p_jockey'])
    flags['jockey_up'] = p['jockey_changed'] & p['jockey'].isin(top_jockeys)
    flags['closer_overbet'] = (p['p_c4'] >= np.maximum(8, p['p_field'] * 0.7)) & (p['ninki'] <= 5)
    flags['small_field_closer'] = (p['field'] <= 10) & (p['p_c4'] >= 6)
    flags['closer_blinker'] = (p['blinker'] == 1) & (p['p_c4'] >= 8)
    flags['prev_fluke'] = (p['p_ninki'] >= 6) & (p['p_chakujun'] <= 2)
    flags['wet_to_good'] = p['p_baba'].isin(WET) & p['is_good']
    flags['inner_to_outer'] = (p['p_umaban'] <= 3) & (p['p_chakujun'] <= 3) & (p['waku'] >= 6)
    flags['dirt_out_to_in'] = p['is_dirt'] & (p['p_umaban'] >= 6) & (p['waku'] <= 3)
    flags['dirt_front'] = p['is_dirt'] & (p['p_passratio'] <= 0.28)
    back_c4 = p['p_c4'] >= np.maximum(6, p['p_field'] * 0.55)
    flags['dirt_closer_miss'] = p['is_dirt'] & (back_c4 | (p['p_passratio'] >= 0.50))
    flags['dirt_small'] = p['is_dirt'] & (p['bataiju'] <= 440)
    flags['dirt_2yo_power'] = p['is_dirt'] & (p['age'] == 2) & (p['bataiju'] >= 460)
    flags['open_nakaana'] = p['is_open'] & p['ninki'].between(4, 6)
    flags['stakes_nige'] = p['is_open'] & (p['p_passratio'] <= 0.28)
    flags['open_cond_win_fav'] = (p['is_open'] & (p['ninki'] == 1) & (p['p_chakujun'] == 1)
                                  & (p['p_crank'] <= 3))
    flags['maiden_fav1'] = p['is_maiden'] & (p['ninki'] == 1)
    flags['turf_2yo_small'] = (~p['is_dirt']) & (p['age'] == 2) & p['is_maiden'] \
        & p['month'].isin([6, 7, 8, 9]) & (p['bataiju'] < 400) & (p['ninki'] >= 6)
    flags['filly_wear'] = (p['sex_code'] == '2') & (p['zogen'] <= -10)

    # 人気馬×前走上り下位（このレースのメンバー内での前走ato3f順位）
    pr = p['p_ato3f']
    p['_ag_rank'] = pr.groupby(p['race_key']).rank(ascending=True)
    p['_ag_n'] = pr.groupby(p['race_key']).transform('count')
    flags['fav_slow_agari'] = ((p['ninki'] <= 3) & (p['_ag_n'] >= 5)
                               & (p['_ag_rank'] >= np.maximum(6, (p['_ag_n'] * 0.6).astype(int))))

    out = pd.DataFrame(flags, index=p.index).fillna(False).astype(bool)
    return out


def stats(sub, base):
    n = len(sub)
    if n == 0:
        return None
    hit = float(sub['top3'].mean())
    exp = float(sub['ninki'].astype(int).map(base).mean())
    resid = hit - exp
    se = (exp * (1 - exp) / n) ** 0.5 if exp and exp == exp else np.nan
    z = resid / se if se and se > 0 else 0.0
    win = float(sub['win'].mean())
    roi = float(np.where(sub['win'] == 1, np.nan_to_num(sub['win_odds'], nan=0.0), 0.0).sum() / n)
    return dict(n=int(n), hit=hit, exp=exp, resid=resid, z=float(z), win=win, roi=roi)


def judge(direction, h, r):
    """主張方向 direction(+1買い/-1消し) に対する判定。"""
    if h is None or h['n'] < MIN_N:
        return '標本不足'
    z = h['z'] * direction
    ok_recent = (r is not None and r['n'] >= 50 and (r['resid'] * direction) > 0)
    if z >= 2 and ok_recent:
        return '採用方向（holdout有意+recent同符号）'
    if z >= 2:
        return 'holdoutのみ有意（recent未確認）'
    if z <= -2:
        return '否決（逆方向に有意）'
    if abs(h['z']) < 1 and h['n'] >= BIG_N:
        return '否決（効果なし・織込み済み）'
    return '未達（傾向のみ）'


def main():
    print('DB読み込み(2014年〜)...', flush=True)
    df = load_frame()
    print(f'  {len(df):,} 行', flush=True)
    df = prepare(df)
    df = add_period(df)

    chk = df[df['year'] == HOLDOUT_YEAR].groupby('race_key')['crank'].first()
    print('  2025クラス分布(0新馬 1未勝利 2一勝 3二勝 4三勝 5OP/L 6G3 7G2 8G1):',
          chk.value_counts().sort_index().to_dict(), flush=True)

    ev = df[df['valid'] & df['ninki'].between(1, 18)].copy()
    ev['top3'] = (ev['chakujun'] <= 3).astype(float)
    ev['win'] = (ev['chakujun'] == 1).astype(float)
    ev = ev[ev['period'].isin(['train', 'holdout', 'recent', 'other'])]
    ev = ev[ev['year'] >= TRAIN_YEARS[0]]  # 評価は2021年〜

    train = ev[ev['period'] == 'train']
    base = train.groupby(train['ninki'].astype(int))['top3'].mean().to_dict()
    print(f'評価行 {len(ev):,}  train基準率 {len(base)}人気', flush=True)

    top_jockeys, course_hot = jockey_tables(df)
    print(f'トップ騎手(train凍結) {len(top_jockeys)}人 / コース巧者セル {len(course_hot)}', flush=True)

    flags = add_flags(ev, top_jockeys, course_hot)

    print('\n========== 未検証39項目 バックテスト ==========')
    print('残差=複勝率−同人気train基準。zの符号は主張方向(+が買い主張に有利)。')
    results = {}
    for fid, direction, title in ITEMS:
        m = flags[fid]
        row = {}
        for per in ('train', 'holdout', 'recent'):
            sub = ev[(ev['period'] == per) & m]
            row[per] = stats(sub, base)
        comb = ev[m & ev['period'].isin(['holdout', 'recent'])]
        row['holdout+recent'] = stats(comb, base)
        results[fid] = row
        verd = judge(direction, row['holdout'], row['recent'])

        def f(s):
            if s is None:
                return 'n=0'
            return (f"n={s['n']:6d} 複{s['hit']:5.1%}(期{s['exp']:5.1%}) "
                    f"残差{s['resid']*100:+5.2f}pp z={s['z']:+5.2f} 単ROI{s['roi']:6.1%}")
        mark = '＋' if direction > 0 else '−'
        print(f"\n[{mark}] {fid}  {title}")
        print(f"  train          {f(row['train'])}")
        print(f"  holdout(2025)  {f(row['holdout'])}")
        print(f"  recent(2026-)  {f(row['recent'])}")
        print(f"  holdout+recent {f(row['holdout+recent'])}")
        print(f"  → {verd}")
        results[fid]['verdict'] = verd
        results[fid]['direction'] = direction
        results[fid]['title'] = title

    print('\n========== 一覧（holdout基準・主張方向のzでソート） ==========')
    rows = []
    for fid, direction, title in ITEMS:
        h = results[fid]['holdout']
        r = results[fid]['recent']
        rows.append({
            'id': fid, 'title': title, 'dir': direction,
            'n': h['n'] if h else 0,
            'z_dir': (h['z'] * direction) if h else np.nan,
            'resid_pp': (h['resid'] * 100 * direction) if h else np.nan,
            'recent_same': bool(r and r['n'] >= 50 and (r['resid'] * direction) > 0),
            'verdict': results[fid]['verdict'],
        })
    tbl = pd.DataFrame(rows).sort_values('z_dir', ascending=False, na_position='last')
    pd.set_option('display.width', 200)
    print(tbl.to_string(index=False,
                        formatters={'z_dir': lambda x: f'{x:+.2f}' if x == x else '-',
                                    'resid_pp': lambda x: f'{x:+.2f}' if x == x else '-'}))

    try:
        with open(OUT_JSON, 'w', encoding='utf-8') as f:
            json.dump({'train_years': TRAIN_YEARS, 'holdout': HOLDOUT_YEAR,
                       'recent_from': RECENT_FROM, 'items': results},
                      f, ensure_ascii=False, indent=2, default=str)
        print(f'\n要約: {OUT_JSON}')
    except Exception as e:
        print(f'JSON保存スキップ: {e}')


if __name__ == '__main__':
    main()
