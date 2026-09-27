# -*- coding: utf-8 -*-
"""Maiden Score Phase 2 / Step A: 単変数ゲート（唯一の仕様: repo/maiden_score_design.md）

3変数を **単独** に、人気統制後の複勝残差で評価する。合成スコアは作らない。
  V1 騎手係数      : jockey_jv.jockey_factor の mult（3分位で3段階化）
  V2 黄金ライン    : jockey_jv.jockey_trainer_combo の連対率（固定区分 40%+=2 / 30-40%=1 / 他=0）
  V3 厩舎当コース  : jockey_jv.trainer_course_winrate の win_rate_shrunk（3分位で3段階化）

事前固定（変更禁止）:
  母集団 : 各馬の初出走（デビュー戦）。JRA場01-10・芝/ダート・障害除外
  分割   : train 〜2017 / holdout 2018-2022
  ベース : 人気別 複勝率（train で凍結）
  リーク防止: 全変数 before_key=当該 race_key（当該レースより前の成績のみ）
             USM 較正テーブルも train 期間（2014-2017）で固定
  ゲート : 上位区分の複勝残差 > 0 かつ z >= +2.0 かつ 区分間で残差が単調減少 → 採用
  全体   : 採用変数が2つ以上 → GO（Step B 合成検証へ）。1つ以下 → NO-GO（Phase 1 維持）

出力:
  repo/analysis/maiden_score/step_a_summary.json    … 判定サマリ（機械可読）
  repo/analysis/maiden_score/step_a_univariate.csv  … 変数×区分の全指標
  data/maiden_score_features.csv                    … 特徴量チェックポイント（再開用）

使い方:
  python scripts/maiden_score_backtest.py              # フル実行（再開対応）
  python scripts/maiden_score_backtest.py --max-races 300  # パイプライン動作確認
"""
import argparse
import csv
import json
import math
import os
import random
import sqlite3
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'jravan.db')
OUT_DIR = os.path.join(ROOT, 'repo', 'analysis', 'maiden_score')
CKPT = os.path.join(ROOT, 'data', 'maiden_score_features.csv')

# ── 事前固定（変更禁止） ──
TRAIN_END = 2017
HOLDOUT_MIN = 2018
HOLDOUT_MAX = 2022
YEAR_MIN = 2010
EXP_YEARS = ('2014', '2015', '2016', '2017')  # USM較正はtrain期間のみ（holdout各レース時点で過去）
RESID_SD = 0.42          # 複勝残差のSD（先行検証と同じ定数）
Z_ADOPT = 2.0            # 採用ゲートの z 閾値
MIN_N_TIER = 100         # 区分の最小標本
MIN_N_BASELINE = 50      # 人気別ベースラインの最小標本
V2_RIDES_MIN = 15        # 黄金ライン区分の最小騎乗数（jockey_factor と同じ）
V2_T2_TOP2 = 0.40        # 黄金ライン tier2 閾値（固定）
V2_T1_TOP2 = 0.30        # 黄金ライン tier1 閾値（固定）
BOOT_N = 2000
BOOT_SEED = 42

FEATURE_COLS = ['race_key', 'ketto_num', 'umaban', 'year', 'ninki', 'chakujun',
                'win_odds', 'v1_mult', 'v2_tier', 'v3_shrunk']


# ══════════════════════════════════════════════════════════════
# 純粋関数（テスト可能・DB非依存）
# ══════════════════════════════════════════════════════════════

def tertile_edges(values):
    """train 分布の3分位 (lo=33.3%, hi=66.7%) を返す。凍結ルールの機械的手続き。"""
    vs = sorted(v for v in values if v is not None)
    if not vs:
        return (None, None)
    n = len(vs)
    return (vs[n // 3], vs[(2 * n) // 3])


def tier_of(value, lo, hi):
    """3分位エッジによる3段階化（2=上位 / 1=中位 / 0=下位）。エッジ崩壊時は lo のみで2分割。"""
    if value is None or lo is None:
        return None
    if hi is None or lo == hi:
        return 2 if value > lo else 0
    if value > hi:
        return 2
    if value > lo:
        return 1
    return 0


def v2_tier(combo):
    """黄金ライン固定区分（設計書 §2: 40%+=2 / 30-40%=1 / それ以外・不足=0）。"""
    if not combo:
        return 0
    if (combo.get('rides') or 0) < V2_RIDES_MIN:
        return 0
    top2 = combo.get('top2') or 0.0
    if top2 >= V2_T2_TOP2:
        return 2
    if top2 >= V2_T1_TOP2:
        return 1
    return 0


def z_of(mean_resid, n, sd=RESID_SD):
    return mean_resid / (sd / math.sqrt(n)) if n else 0.0


def tier_metrics(rows, baseline):
    """1区分の指標。rows: dict のリスト（ninki/chakujun/win_odds を持つ）。
    戻り値: n, 的中率(1着率), 複勝率, 人気統制後の複勝残差, z, CI, 単勝ROI。"""
    use = [r for r in rows if r['ninki'] in baseline]
    n = len(use)
    if n == 0:
        return None
    resids = [(1 if r['chakujun'] <= 3 else 0) - baseline[r['ninki']] for r in use]
    m = sum(resids) / n
    ci_lo = ci_hi = None
    if n >= MIN_N_TIER:
        random.seed(BOOT_SEED)
        bs = sorted(sum(resids[random.randrange(n)] for _ in range(n)) / n
                    for _ in range(BOOT_N))
        ci_lo, ci_hi = bs[50], bs[1949]
    rois = [r['win_odds'] if r['chakujun'] == 1 else 0.0 for r in use if r['win_odds']]
    return {
        'n': n,
        'win_rate': sum(1 for r in use if r['chakujun'] == 1) / n,
        'place_rate': sum(1 for r in use if r['chakujun'] <= 3) / n,
        'residual': m,
        'z': z_of(m, n),
        'ci_lo': ci_lo,
        'ci_hi': ci_hi,
        'roi_win': (sum(rois) / len(rois)) if rois else None,
    }


def gate_verdict(per_tier):
    """事前固定ゲート: 上位区分の残差 > 0 かつ z >= +2.0 かつ 単調減少 → 採用。
    per_tier: {0: metrics|None, 1: metrics|None, 2: metrics|None}（holdout）。
    戻り値: (採用bool, 理由str)"""
    t0, t1, t2 = per_tier.get(0), per_tier.get(1), per_tier.get(2)
    if not t2 or t2['n'] < MIN_N_TIER:
        return False, f'上位区分の標本不足（n={t2["n"] if t2 else 0} < {MIN_N_TIER}）'
    if t2['residual'] <= 0:
        return False, f"上位区分の残差が非正（{t2['residual'] * 100:+.2f}pp）"
    if t2['z'] < Z_ADOPT:
        return False, f"z 未達（{t2['z']:+.2f} < +{Z_ADOPT}）"
    if not (t1 and t0):
        return False, '中位/下位区分が欠損（単調性を確認できない）'
    if not (t2['residual'] >= t1['residual'] >= t0['residual']):
        return False, ('区分間が単調でない'
                       f"（t2={t2['residual'] * 100:+.2f} t1={t1['residual'] * 100:+.2f}"
                       f" t0={t0['residual'] * 100:+.2f}）")
    return True, f"残差{t2['residual'] * 100:+.2f}pp / z={t2['z']:+.2f} / 単調"


# ══════════════════════════════════════════════════════════════
# データ抽出・特徴量計算（before_key 必須）
# ══════════════════════════════════════════════════════════════

def load_debut_runs(db_path=DB, year_min=YEAR_MIN, year_max=HOLDOUT_MAX):
    """各馬の初出走（デビュー戦）を抽出。先行検証と同一の母集団定義。"""
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=60)
    rows = con.execute(
        "SELECT r.race_key, r.ketto_num, r.umaban, r.chakujun, r.ninki, r.win_odds, "
        "       r.jockey_name, r.trainer_code, ra.year, ra.monthday, ra.jyo, "
        "       ra.kyori, ra.surface "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE ra.jyo BETWEEN '01' AND '10' AND ra.surface IN ('芝','ダート') "
        "AND ra.shubetsu NOT IN ('18','19') AND r.chakujun>0 AND r.ketto_num<>''"
    ).fetchall()
    con.close()
    by_horse = defaultdict(list)
    for rk, kt, um, ch, nk, wo, jn, tc, y, md, jyo, ky, surf in rows:
        by_horse[str(kt)].append(
            (int(str(y) + str(md).zfill(4)), str(rk), str(um),
             int(ch), (int(nk) if nk else None), (float(wo) if wo else None),
             str(jn), str(tc), int(y), str(jyo), int(ky), str(surf)))
    debut = []
    for kt, lst in by_horse.items():
        lst.sort()
        _, rk, um, ch, nk, wo, jn, tc, y, jyo, ky, surf = lst[0]
        if y < year_min or y > year_max or nk is None:
            continue
        debut.append({
            'race_key': rk, 'ketto_num': kt, 'umaban': um, 'chakujun': ch,
            'ninki': nk, 'win_odds': wo, 'jockey': jn, 'trainer_code': tc,
            'year': y, 'jyo': jyo, 'kyori': ky, 'surface': surf,
        })
    debut.sort(key=lambda d: d['race_key'])
    return debut


def compute_one(jv, run, expected):
    """1頭分の特徴量。全て before_key=当該 race_key（未来情報リーク防止の核心）。"""
    bk = run['race_key']
    v1 = v2 = v3 = None
    if run['jockey']:
        try:
            fac = jv.jockey_factor(
                run['jockey'], venue=jv._venue_name(run['jyo']),
                distance=run['kyori'], trainer_code=run['trainer_code'],
                before_key=bk, expected=expected)
            v1 = fac.get('mult')
        except Exception:
            v1 = None
        try:
            combo = jv.jockey_trainer_combo(
                run['jockey'], run['trainer_code'], before_key=bk)
            v2 = v2_tier(combo)
        except Exception:
            v2 = None
    if run['trainer_code']:
        try:
            cw = jv.trainer_course_winrate(
                run['trainer_code'], run['jyo'], run['surface'],
                before_key=bk, min_year=str(run['year'] - 3))
            if cw:
                v3 = cw.get('win_rate_shrunk')
        except Exception:
            v3 = None
    return v1, v2, v3


def compute_features(debut, jv, expected, ckpt_path=CKPT, max_races=None, log_every=200,
                     workers=4):
    """特徴量を計算してチェックポイントCSVへ追記（再開対応）。

    jockey_jv._con は呼出ごとに新規コネクションを張るため読み取りはスレッド安全。
    書き込みはメインスレッドのみが行う。計算順は結果に影響しない（before_key固定）。
    """
    from concurrent.futures import ThreadPoolExecutor

    done = set()
    if os.path.exists(ckpt_path):
        with open(ckpt_path, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                done.add((row['race_key'], row['ketto_num']))
    todo = [d for d in debut if (d['race_key'], d['ketto_num']) not in done]
    if max_races:
        keys = sorted({d['race_key'] for d in todo})[:max_races]
        todo = [d for d in todo if d['race_key'] in set(keys)]
    print(f'  特徴量計算: 残 {len(todo):,}頭（済 {len(done):,}頭 / workers={workers}）')
    t0 = time.time()
    new_mode = 'a' if done else 'w'
    with open(ckpt_path, new_mode, newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FEATURE_COLS)
        if not done:
            w.writeheader()

        def _job(run):
            v1, v2, v3 = compute_one(jv, run, expected)
            return run, v1, v2, v3

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, (run, v1, v2, v3) in enumerate(ex.map(_job, todo)):
                w.writerow({
                    'race_key': run['race_key'], 'ketto_num': run['ketto_num'],
                    'umaban': run['umaban'], 'year': run['year'], 'ninki': run['ninki'],
                    'chakujun': run['chakujun'],
                    'win_odds': run['win_odds'] if run['win_odds'] is not None else '',
                    'v1_mult': v1 if v1 is not None else '',
                    'v2_tier': v2 if v2 is not None else '',
                    'v3_shrunk': v3 if v3 is not None else '',
                })
                if (i + 1) % log_every == 0:
                    f.flush()
                    el = time.time() - t0
                    eta = el / (i + 1) * (len(todo) - i - 1)
                    print(f'    {i + 1:,}/{len(todo):,} 経過{el / 60:.1f}分 ETA{eta / 60:.1f}分',
                          flush=True)
    return ckpt_path


def load_features(ckpt_path=CKPT):
    out = []
    with open(ckpt_path, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            out.append({
                'race_key': row['race_key'], 'ketto_num': row['ketto_num'],
                'umaban': row['umaban'], 'year': int(row['year']),
                'ninki': int(row['ninki']), 'chakujun': int(row['chakujun']),
                'win_odds': float(row['win_odds']) if row['win_odds'] else None,
                'v1_mult': float(row['v1_mult']) if row['v1_mult'] else None,
                'v2_tier': int(row['v2_tier']) if row['v2_tier'] != '' else None,
                'v3_shrunk': float(row['v3_shrunk']) if row['v3_shrunk'] else None,
            })
    return out


# ══════════════════════════════════════════════════════════════
# 評価
# ══════════════════════════════════════════════════════════════

def build_baseline(rows):
    """人気別 複勝率（train のみで凍結）。"""
    bp = defaultdict(lambda: [0, 0])
    for r in rows:
        if r['year'] <= TRAIN_END:
            bp[r['ninki']][0] += 1 if r['chakujun'] <= 3 else 0
            bp[r['ninki']][1] += 1
    return {k: v[0] / v[1] for k, v in bp.items() if v[1] >= MIN_N_BASELINE}


def evaluate_variable(name, feat_key, holdout, baseline, edges=None):
    """1変数の holdout 評価。tier 割当 → 区分別指標 → ゲート判定。"""
    per_tier_rows = {0: [], 1: [], 2: []}
    skipped = 0
    for r in holdout:
        v = r[feat_key]
        if v is None:
            skipped += 1
            continue
        if feat_key == 'v2_tier':
            tier = v
        else:
            tier = tier_of(v, edges[0], edges[1])
        if tier is None:
            skipped += 1
            continue
        per_tier_rows[tier].append(r)
    per_tier = {t: tier_metrics(rs, baseline) for t, rs in per_tier_rows.items()}
    adopt, reason = gate_verdict(per_tier)
    return {'variable': name, 'tiers': per_tier, 'skipped': skipped,
            'adopt': adopt, 'reason': reason, 'edges': edges}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-races', type=int, default=None,
                    help='動作確認用: 特徴量計算を先頭N レースに限定')
    ap.add_argument('--workers', type=int, default=6,
                    help='特徴量計算のスレッド数（既定6）')
    args = ap.parse_args()

    from core import jockey_jv as jv

    os.makedirs(OUT_DIR, exist_ok=True)
    print('=' * 84)
    print('Maiden Score Step A: 単変数ゲート（設計: repo/maiden_score_design.md）')
    print('=' * 84)
    print(f'  母集団: 各馬の初出走 / train〜{TRAIN_END} / holdout {HOLDOUT_MIN}-{HOLDOUT_MAX}')
    print(f'  リーク防止: before_key=race_key 必須 / USM較正={"+".join(EXP_YEARS)}')

    print('\n■ デビュー戦の抽出')
    t0 = time.time()
    debut = load_debut_runs()
    print(f'  {len(debut):,}頭（{time.time() - t0:.0f}s）')

    print('\n■ USM較正テーブル（train期間のみで固定）')
    expected = jv.calibrate_odds_expectation(years=EXP_YEARS)
    print(f'  bands={len(expected)}')

    print('\n■ 特徴量計算（before_key 付き・再開対応）')
    compute_features(debut, jv, expected, max_races=args.max_races, workers=args.workers)

    feats = load_features()
    train = [f for f in feats if f['year'] <= TRAIN_END]
    holdout = [f for f in feats if HOLDOUT_MIN <= f['year'] <= HOLDOUT_MAX]
    print(f'\n  特徴量: train {len(train):,} / holdout {len(holdout):,}')

    baseline = build_baseline(feats)
    print(f'  ベースライン人気区分: {len(baseline)}')

    # 3分位エッジは train のみで凍結
    v1_edges = tertile_edges([f['v1_mult'] for f in train])
    v3_edges = tertile_edges([f['v3_shrunk'] for f in train])
    print(f'  V1 3分位エッジ(train凍結): {v1_edges}')
    print(f'  V3 3分位エッジ(train凍結): {v3_edges}')

    results = [
        evaluate_variable('V1 騎手係数', 'v1_mult', holdout, baseline, edges=v1_edges),
        evaluate_variable('V2 黄金ライン', 'v2_tier', holdout, baseline),
        evaluate_variable('V3 厩舎当コース勝率', 'v3_shrunk', holdout, baseline, edges=v3_edges),
    ]

    # ── 出力 ──
    print('\n' + '=' * 84)
    print('■ Step A 結果（holdout 2018-2022・人気統制後の複勝残差）')
    print('=' * 84)
    csv_rows = []
    for res in results:
        print(f"\n── {res['variable']} ──  (対象外skip: {res['skipped']:,})")
        print(f"  {'区分':<14}{'n':>8}{'的中率':>8}{'複勝率':>8}{'残差':>10}{'z':>8}"
              f"{'95%CI':>20}{'単勝ROI':>9}")
        for t in (2, 1, 0):
            m = res['tiers'].get(t)
            lbl = {2: '上位', 1: '中位', 0: '下位'}[t]
            if not m:
                print(f'  {lbl}(tier{t})    データなし')
                continue
            ci = (f"[{m['ci_lo'] * 100:+.2f},{m['ci_hi'] * 100:+.2f}]"
                  if m['ci_lo'] is not None else '-')
            roi = f"{m['roi_win'] * 100:.1f}%" if m['roi_win'] is not None else '-'
            print(f"  {lbl}(tier{t}) {m['n']:>8,}{m['win_rate'] * 100:>7.1f}%"
                  f"{m['place_rate'] * 100:>7.1f}%{m['residual'] * 100:>+9.2f}pp"
                  f"{m['z']:>+8.2f}{ci:>20}{roi:>9}")
            csv_rows.append({
                'variable': res['variable'], 'tier': t, 'n': m['n'],
                'win_rate': round(m['win_rate'], 4), 'place_rate': round(m['place_rate'], 4),
                'residual': round(m['residual'], 4), 'z': round(m['z'], 2),
                'ci_lo': round(m['ci_lo'], 4) if m['ci_lo'] is not None else '',
                'ci_hi': round(m['ci_hi'], 4) if m['ci_hi'] is not None else '',
                'roi_win': round(m['roi_win'], 4) if m['roi_win'] is not None else '',
            })
        verdict = '✅ 採用' if res['adopt'] else '❌ 不採用'
        print(f"  → {verdict}: {res['reason']}")

    adopted = [r['variable'] for r in results if r['adopt']]
    go = len(adopted) >= 2
    print('\n' + '=' * 84)
    print(f'■ Step A 判定: {"GO（Step B 合成検証へ進める）" if go else "NO-GO（Phase 1 表示のまま維持）"}')
    print(f'  採用変数: {adopted if adopted else "なし"}（{len(adopted)}/3）')
    print('=' * 84)

    csv_path = os.path.join(OUT_DIR, 'step_a_univariate.csv')
    if csv_rows:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
            w.writeheader()
            w.writerows(csv_rows)
    else:
        print('  （holdout 行なしのため CSV は未作成。--max-races による部分実行の可能性）')

    summary = {
        'spec': 'repo/maiden_score_design.md',
        'step': 'A_univariate_gate',
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'population': 'JRA debut races (jyo 01-10, turf/dirt, no obstacle)',
        'split': {'train_end': TRAIN_END, 'holdout': [HOLDOUT_MIN, HOLDOUT_MAX]},
        'leak_guard': {'before_key': 'race_key', 'expected_years': list(EXP_YEARS)},
        'edges': {'v1': v1_edges, 'v3': v3_edges},
        'n_train': len(train), 'n_holdout': len(holdout),
        'variables': [{
            'name': r['variable'], 'adopt': r['adopt'], 'reason': r['reason'],
            'skipped': r['skipped'],
            'tiers': {str(t): m for t, m in r['tiers'].items()},
        } for r in results],
        'adopted': adopted,
        'verdict': 'GO' if go else 'NO-GO',
    }
    json_path = os.path.join(OUT_DIR, 'step_a_summary.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f'\n  保存: {csv_path}')
    print(f'  保存: {json_path}')
    print(f'  特徴量CKPT: {CKPT}')
    return 0 if go else 1


if __name__ == '__main__':
    sys.exit(main())
