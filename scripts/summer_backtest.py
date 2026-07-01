# -*- coding: utf-8 -*-
"""夏競馬バックテスト — scripts/summer_backtest.py

検証対象:
  ① ハンデ戦×斤量帯別の複勝残差（軽ハンデ消去 / 重ハンデ軸補強）
  ② 昇級初戦×季節別の複勝残差（夏の昇級馬は消去候補か）
  ③ 洋芝(北海道)×特定種牡馬の複勝残差（キズナ等）

残差 = 実際の複勝率 - 人気ベースライン複勝率
  → 正なら市場が過小評価（妙味あり）、負なら織込み済み/過剰人気
"""
import os, sys, sqlite3
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JV_DB = os.path.join(_ROOT, 'data', 'jravan.db')

def _connect():
    return sqlite3.connect(f'file:{_JV_DB}?mode=ro', uri=True, timeout=10)


def _pop_baseline(con, year_min=2015, year_max=2024):
    """人気別の複勝率ベースラインを計算。"""
    rows = con.execute('''
        SELECT r.ninki,
               COUNT(*) as n,
               SUM(CASE WHEN r.chakujun <= 3 THEN 1 ELSE 0 END) as top3
        FROM results r
        JOIN races ra ON r.race_key = ra.race_key
        WHERE ra.year >= ? AND ra.year <= ?
          AND r.ninki > 0 AND r.ninki <= 18
          AND r.chakujun > 0
          AND ra.shusso_tosu >= 8
        GROUP BY r.ninki
    ''', (year_min, year_max)).fetchall()
    baseline = {}
    for nk, n, t3 in rows:
        baseline[nk] = t3 / n if n > 0 else 0
    return baseline


def _residual(actual_top3_rate, ninki_list, baseline):
    """複勝残差を計算。"""
    if not ninki_list:
        return 0, 0
    expected = np.mean([baseline.get(nk, 0.15) for nk in ninki_list])
    residual = actual_top3_rate - expected
    return residual, expected


def _z_score(hits, n, expected_rate):
    if n < 10:
        return 0
    p = expected_rate
    se = np.sqrt(p * (1 - p) / n) if p > 0 and p < 1 else 0.01
    return (hits / n - p) / se if se > 0 else 0


def _print_group(label, n, hits, ninki_list, baseline, win_hits=None):
    if n == 0:
        print(f'  {label}: n=0')
        return
    top3_rate = hits / n
    residual, expected = _residual(top3_rate, ninki_list, baseline)
    z = _z_score(hits, n, expected)
    avg_pop = np.mean(ninki_list) if ninki_list else 0

    win_str = ''
    if win_hits is not None:
        win_rate = win_hits / n
        win_str = f' 勝率{win_rate*100:.1f}%'

    print(f'  {label}: n={n:,} 複勝率{top3_rate*100:.1f}% '
          f'期待{expected*100:.1f}% 残差{residual*100:+.1f}pp z={z:+.1f} '
          f'平均人気{avg_pop:.1f}{win_str}')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ① ハンデ戦×斤量帯
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_handicap_weight(con, baseline):
    print('\n' + '=' * 70)
    print('① ハンデ戦×斤量帯別の複勝残差')
    print('  仮説: 軽ハンデ(≤51kg)は消去、重ハンデ(≥57kg)は軸補強')
    print('=' * 70)

    rows = con.execute('''
        SELECT r.futan, r.ninki, r.chakujun, r.win_odds, r.sex,
               CASE WHEN r.chakujun = 1 THEN 1 ELSE 0 END as is_win
        FROM results r
        JOIN races ra ON r.race_key = ra.race_key
        WHERE ra.juryo = '4'
          AND ra.year >= 2015 AND ra.year <= 2024
          AND r.ninki > 0 AND r.chakujun > 0
          AND ra.shusso_tosu >= 8
    ''').fetchall()

    groups = {
        '≤50kg': (0, 500),
        '50.5-51kg': (505, 510),
        '51.5-53kg': (515, 530),
        '53.5-55kg': (535, 550),
        '55.5-56kg': (555, 560),
        '56.5-57kg': (565, 570),
        '≥58kg': (580, 999),
    }

    for label, (lo, hi) in groups.items():
        subset = [r for r in rows if lo <= r[0] <= hi]
        n = len(subset)
        hits = sum(1 for r in subset if r[2] <= 3)
        wins = sum(1 for r in subset if r[2] == 1)
        ninkis = [r[1] for r in subset]
        _print_group(label, n, hits, ninkis, baseline, win_hits=wins)

    # 人気帯×斤量のクロス（織込み度を確認）
    print('\n  --- 人気帯別クロス（ハンデ戦のみ）---')
    for pop_label, pop_lo, pop_hi in [('1-3人気', 1, 3), ('4-6人気', 4, 6),
                                       ('7-9人気', 7, 9), ('10人気+', 10, 18)]:
        for wgt_label, (lo, hi) in [('軽≤51', (0, 510)), ('中52-56', (520, 560)),
                                     ('重≥57', (570, 999))]:
            subset = [r for r in rows if lo <= r[0] <= hi and pop_lo <= r[1] <= pop_hi]
            n = len(subset)
            hits = sum(1 for r in subset if r[2] <= 3)
            ninkis = [r[1] for r in subset]
            _print_group(f'{pop_label}×{wgt_label}', n, hits, ninkis, baseline)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ② 昇級初戦×季節
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_promotion_season(con, baseline):
    print('\n' + '=' * 70)
    print('② 昇級初戦(前走1着)×季節別の複勝残差')
    print('  仮説: 夏(7-9月)の昇級馬は苦戦し消去候補')
    print('=' * 70)

    # 各馬の出走履歴を取得し、前走1着かどうかを判定
    rows = con.execute('''
        WITH horse_runs AS (
            SELECT r.ketto_num, r.race_key, ra.race_id, r.chakujun, r.ninki,
                   ra.year, ra.monthday, ra.grade, r.win_odds,
                   ROW_NUMBER() OVER (PARTITION BY r.ketto_num ORDER BY ra.race_id) as run_seq
            FROM results r
            JOIN races ra ON r.race_key = ra.race_key
            WHERE ra.year >= 2015 AND ra.year <= 2024
              AND r.ninki > 0 AND r.chakujun > 0
              AND ra.shusso_tosu >= 8
        )
        SELECT curr.ketto_num, curr.chakujun, curr.ninki, curr.win_odds,
               curr.monthday, curr.grade,
               prev.chakujun as prev_chakujun, prev.grade as prev_grade
        FROM horse_runs curr
        JOIN horse_runs prev ON curr.ketto_num = prev.ketto_num
                            AND curr.run_seq = prev.run_seq + 1
        WHERE prev.chakujun = 1
    ''').fetchall()

    print(f'  前走1着のデータ: {len(rows):,}件')

    # 季節別
    seasons = {
        '1-3月(冬春)': ('01', '03'),
        '4-6月(春)': ('04', '06'),
        '7-9月(夏)': ('07', '09'),
        '10-12月(秋冬)': ('10', '12'),
    }

    for s_label, (m_lo, m_hi) in seasons.items():
        subset = [r for r in rows if m_lo <= r[4][:2] <= m_hi]
        n = len(subset)
        hits = sum(1 for r in subset if r[1] <= 3)
        wins = sum(1 for r in subset if r[1] == 1)
        ninkis = [r[2] for r in subset]
        _print_group(s_label, n, hits, ninkis, baseline, win_hits=wins)

    # 重賞限定
    print('\n  --- 重賞(A/B/C)限定 ---')
    graded = [r for r in rows if r[5] in ('A', 'B', 'C')]
    print(f'  重賞データ: {len(graded):,}件')
    for s_label, (m_lo, m_hi) in seasons.items():
        subset = [r for r in graded if m_lo <= r[4][:2] <= m_hi]
        n = len(subset)
        hits = sum(1 for r in subset if r[1] <= 3)
        wins = sum(1 for r in subset if r[1] == 1)
        ninkis = [r[2] for r in subset]
        _print_group(s_label, n, hits, ninkis, baseline, win_hits=wins)

    # 人気帯別×夏 vs 非夏
    print('\n  --- 人気帯×夏/非夏（前走1着馬のみ）---')
    for pop_label, pop_lo, pop_hi in [('1-3人気', 1, 3), ('4-6人気', 4, 6),
                                       ('7-9人気', 7, 9), ('10人気+', 10, 18)]:
        for season_label, is_summer in [('夏(7-9月)', True), ('非夏', False)]:
            if is_summer:
                subset = [r for r in rows if '07' <= r[4][:2] <= '09'
                          and pop_lo <= r[2] <= pop_hi]
            else:
                subset = [r for r in rows if not ('07' <= r[4][:2] <= '09')
                          and pop_lo <= r[2] <= pop_hi]
            n = len(subset)
            hits = sum(1 for r in subset if r[1] <= 3)
            ninkis = [r[2] for r in subset]
            _print_group(f'{pop_label}×{season_label}', n, hits, ninkis, baseline)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ③ 洋芝(北海道)×種牡馬
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_youshiba_sire(con, baseline):
    print('\n' + '=' * 70)
    print('③ 洋芝(函館01/札幌02)×種牡馬の複勝残差')
    print('  仮説: キズナ等は洋芝で市場が過小評価')
    print('=' * 70)

    # 北海道=jyo 01(札幌) or 02(函館)
    # Check jyo codes
    jyo_check = con.execute('''
        SELECT DISTINCT ra.jyo, COUNT(*)
        FROM races ra WHERE ra.year >= 2015
        GROUP BY ra.jyo ORDER BY ra.jyo
    ''').fetchall()
    print('  開催場コード:', [(j, n) for j, n in jyo_check[:15]])

    # 芝レースのみ (surface)
    surface_check = con.execute('''
        SELECT DISTINCT surface, COUNT(*) FROM races
        WHERE year >= 2015 GROUP BY surface
    ''').fetchall()
    print('  surface:', surface_check)

    rows = con.execute('''
        SELECT r.ninki, r.chakujun, r.win_odds, h.sire, ra.jyo, ra.surface,
               CASE WHEN r.chakujun = 1 THEN 1 ELSE 0 END as is_win
        FROM results r
        JOIN races ra ON r.race_key = ra.race_key
        LEFT JOIN horses h ON r.ketto_num = h.ketto_num
        WHERE ra.year >= 2015 AND ra.year <= 2024
          AND r.ninki > 0 AND r.chakujun > 0
          AND ra.shusso_tosu >= 8
          AND ra.surface = '芝'
    ''').fetchall()

    hokkaido_jyo = {'01', '02'}  # 札幌, 函館
    hokkaido = [r for r in rows if r[4] in hokkaido_jyo]
    honshu = [r for r in rows if r[4] not in hokkaido_jyo]

    print(f'\n  北海道芝: {len(hokkaido):,}件 / 本州芝: {len(honshu):,}件')

    # 種牡馬別で北海道vs本州を比較
    target_sires = ['キズナ', 'ハービンジャー', 'ドゥラメンテ', 'オルフェーヴル',
                    'フランケル', 'キタサンブラック', 'モーリス',
                    'ディープインパクト', 'ロードカナロア', 'エピファネイア',
                    'ハーツクライ']

    print('\n  種牡馬           | 北海道(n/複勝率/残差/z)         | 本州(n/複勝率/残差/z)         | Δ残差')
    print('  ' + '-' * 100)

    for sire in target_sires:
        # 北海道
        hk = [r for r in hokkaido if r[3] == sire]
        hk_n = len(hk)
        hk_hits = sum(1 for r in hk if r[1] <= 3)
        hk_ninkis = [r[0] for r in hk]
        hk_rate = hk_hits / hk_n if hk_n > 0 else 0
        hk_res, hk_exp = _residual(hk_rate, hk_ninkis, baseline)
        hk_z = _z_score(hk_hits, hk_n, hk_exp)

        # 本州
        hs = [r for r in honshu if r[3] == sire]
        hs_n = len(hs)
        hs_hits = sum(1 for r in hs if r[1] <= 3)
        hs_ninkis = [r[0] for r in hs]
        hs_rate = hs_hits / hs_n if hs_n > 0 else 0
        hs_res, hs_exp = _residual(hs_rate, hs_ninkis, baseline)
        hs_z = _z_score(hs_hits, hs_n, hs_exp)

        delta = hk_res - hs_res if hk_n > 30 and hs_n > 30 else float('nan')

        if hk_n >= 10:
            print(f'  {sire:14s} | n={hk_n:4d} 複{hk_rate*100:5.1f}% 残{hk_res*100:+5.1f}pp z={hk_z:+4.1f}'
                  f' | n={hs_n:5d} 複{hs_rate*100:5.1f}% 残{hs_res*100:+5.1f}pp z={hs_z:+4.1f}'
                  f' | Δ{delta*100:+5.1f}pp' if not np.isnan(delta) else
                  f'  {sire:14s} | n={hk_n:4d} 複{hk_rate*100:5.1f}% 残{hk_res*100:+5.1f}pp z={hk_z:+4.1f}'
                  f' | n={hs_n:5d} 複{hs_rate*100:5.1f}% 残{hs_res*100:+5.1f}pp z={hs_z:+4.1f}'
                  f' | n<30')

    # 全種牡馬で北海道残差top10
    print('\n  --- 北海道芝・残差トップ10種牡馬（n≥50）---')
    from collections import defaultdict
    sire_stats = defaultdict(lambda: {'n': 0, 'hits': 0, 'ninkis': []})
    for r in hokkaido:
        if r[3]:
            s = sire_stats[r[3]]
            s['n'] += 1
            if r[1] <= 3:
                s['hits'] += 1
            s['ninkis'].append(r[0])

    sire_residuals = []
    for sire, st in sire_stats.items():
        if st['n'] >= 50:
            rate = st['hits'] / st['n']
            res, exp = _residual(rate, st['ninkis'], baseline)
            z = _z_score(st['hits'], st['n'], exp)
            sire_residuals.append((sire, st['n'], rate, res, z))

    sire_residuals.sort(key=lambda x: -x[3])
    for sire, n, rate, res, z in sire_residuals[:10]:
        print(f'  {sire:16s}: n={n:4d} 複勝率{rate*100:5.1f}% 残差{res*100:+5.1f}pp z={z:+4.1f}')

    print('\n  --- 北海道芝・残差ワースト10種牡馬（n≥50）---')
    for sire, n, rate, res, z in sire_residuals[-10:]:
        print(f'  {sire:16s}: n={n:4d} 複勝率{rate*100:5.1f}% 残差{res*100:+5.1f}pp z={z:+4.1f}')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ④ ボーナス: 夏×牝馬（既検証の再確認）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_summer_mare(con, baseline):
    print('\n' + '=' * 70)
    print('④ 夏(7-9月)×牝馬の複勝残差（再確認）')
    print('=' * 70)

    rows = con.execute('''
        SELECT r.sex, r.ninki, r.chakujun, ra.monthday, r.win_odds
        FROM results r
        JOIN races ra ON r.race_key = ra.race_key
        WHERE ra.year >= 2015 AND ra.year <= 2024
          AND r.ninki > 0 AND r.chakujun > 0
          AND ra.shusso_tosu >= 8
    ''').fetchall()

    # sex: 1=牡, 2=牝, 3=セン
    for sex_label, sex_code in [('牡馬', '1'), ('牝馬', '2')]:
        for season_label, m_lo, m_hi in [('夏(7-9月)', '07', '09'),
                                          ('非夏', None, None)]:
            if m_lo:
                subset = [r for r in rows if r[0] == sex_code
                          and m_lo <= r[3][:2] <= m_hi]
            else:
                subset = [r for r in rows if r[0] == sex_code
                          and not ('07' <= r[3][:2] <= '09')]
            n = len(subset)
            hits = sum(1 for r in subset if r[2] <= 3)
            wins = sum(1 for r in subset if r[2] == 1)
            ninkis = [r[1] for r in subset]
            _print_group(f'{sex_label}×{season_label}', n, hits, ninkis,
                         baseline, win_hits=wins)


if __name__ == '__main__':
    con = _connect()
    baseline = _pop_baseline(con)
    print('人気ベースライン複勝率:')
    for nk in range(1, 13):
        print(f'  {nk}人気: {baseline.get(nk, 0)*100:.1f}%')

    test_handicap_weight(con, baseline)
    test_promotion_season(con, baseline)
    test_youshiba_sire(con, baseline)
    test_summer_mare(con, baseline)

    con.close()
    print('\n✅ 完了')
