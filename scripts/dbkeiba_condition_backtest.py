# -*- coding: utf-8 -*-
"""db-keiba.com の『騎手×条件』買い/消し条件は本当に効くのか ―― 初の検証。

【結論(2026-07-23)】不採用。**集計期間の中でしか効かない＝多重検定の産物**。
表示は残すが「参考であって根拠ではない」の位置づけを変えない(スコア非連動を維持)。

  窓                          📗買い条件            📕消し条件
  ─────────────────────────────────────────────────────────────
  2026(集計より後・真の未来)   +0.71pp z=+1.71     +0.22pp z=+0.32 ←符号が逆
  2016-20(集計より前)         +0.26pp z=+1.70     +0.10pp z=+0.47 ←符号が逆
  2021-25(★集計期間=in-sample) +1.23pp z=+8.87     -0.67pp z=-3.27

  in-sampleでz=+8.87/-3.27と強烈に効くのに、前後の窓に出た瞬間 z<2 に落ち、
  **消し条件は両方のout-of-sample窓で符号が反転**(消しなのに残差プラス)。
  条件種類別でも枠(in z+7.11 → 2026 z+2.49 → 2016-20 z+0.31)のように窓ごとに
  バラバラで再現しない。事前に立てた仮説①②③がそのまま当たった形。

  ⚠ 唯一の含み: 買い条件は out-of-sample 2窓とも符号が正(+0.26/+0.71pp・z1.7台)。
    完全なゼロではない。ただし「騎手に得意条件が多少ある」程度の話で、それは既に
    LTRの jockey_jyo_win / jockey_dist_win が拾っている([[project_auto_feature_loop]])。
    db-keibaの選別基準(単勝回収率)が最適でないだけの可能性もあるが、
    消し条件が両窓で符号逆である以上、この表をエッジとして使ってはいけない。


背景:
  core/dbkeiba.py が取得する騎手別の『買い条件(単勝回収率が高い)』『消し条件(低い)』は
  SRAのJ5表と騎手分析Proに**表示専用**で出しているが、当プロジェクトの検証を1度も
  通していない([[project_dbkeiba_jcombo]]に「検証未実施」と明記)。
  ユーザーから「実際に調べたんだっけ?」と問われたため検証する。

疑う理由(事前に立てた仮説):
  ① 単勝回収率ベース。単勝は全オッズ帯で+ROIポケット無しと検証済み([[verified_tansho_roi_efficient]])
  ② 母数不明(サイトは出走100件以上で精選と言うが100件の回収率121%は誤差の範囲)
  ③ 多重検定。騎手1人につき枠/人気/距離/場…を総当たりすれば偶然120%超は必ず出る
     ([[verified_prior_margin_debunk]][[verified_cushion_theory]]で繰り返し踏んだ罠)

⚠ リーク遮断の要:
  db-keibaの集計期間は **2021-2025**。よってその期間で検証すると in-sample になり
  「当たり前に当たる」結果しか出ない。**2026年(集計期間より後)を主窓**とし、
  2016-2020(集計期間より前)を副窓として両側で見る。

評価指標:
  単勝回収率ではなく **複勝率の人気補正残差** を使う。理由は単勝ROIが母数に対して
  極端に不安定なのと、単勝自体が市場効率的で+EVが出ないと確定しているため。
  買い条件に該当した馬の複勝率が「その人気から期待される複勝率」を上回るかを見る。

照合できる条件(事前確定情報のみ):
  人気 / 枠(芝ダ別) / 場×芝ダ / 性別 / 距離帯(芝ダ別)
除外する条件:
  脚質(逃げ・先行) … **結果由来でリーク源**([[verified_stress_debuff]]の重大教訓)
  クラス(1勝クラス等) … jravan.dbに条件クラスコードが無い([[project_auto_feature_loop]]第5イテレーション)

Usage: python scripts/dbkeiba_condition_backtest.py
"""
import os
import sys
import re
import json
import glob
import math
import sqlite3
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

from core import dbkeiba as dk  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JV_DB = os.path.join(ROOT, 'data', 'jravan.db')

# 場名 → jravan jyoコード
JYO = {'札幌': '01', '函館': '02', '福島': '03', '新潟': '04', '東京': '05',
       '中山': '06', '中京': '07', '京都': '08', '阪神': '09', '小倉': '10'}


def parse_condition(label):
    """条件ラベル → 判定関数 or None(照合不能)。

    戻り値: (kind, fn)。fn(row)->bool。row は dict(ninki/waku/jyo/surf/kyori/sex)。
    surf は '芝'/'ダ'。
    """
    s = str(label or '').strip()

    # 脚質は結果由来=リーク源のため明示的に除外する
    if any(k in s for k in ('逃げ', '先行', '差し', '追込', 'まくり')):
        return None

    # ① N人気
    m = re.fullmatch(r'(\d+)人気', s)
    if m:
        n = int(m.group(1))
        return ('人気', lambda r, n=n: r['ninki'] == n)

    # ② 芝N枠 / ダートN枠
    m = re.fullmatch(r'(芝|ダート)(\d)枠', s)
    if m:
        sf = '芝' if m.group(1) == '芝' else 'ダ'
        w = int(m.group(2))
        return ('枠', lambda r, sf=sf, w=w: r['surf'] == sf and r['waku'] == w)

    # ③ {場}芝コース / {場}ダートコース
    m = re.fullmatch(r'(.+?)(芝|ダート)コース', s)
    if m and m.group(1) in JYO:
        jy = JYO[m.group(1)]
        sf = '芝' if m.group(2) == '芝' else 'ダ'
        return ('場×馬場', lambda r, jy=jy, sf=sf: r['jyo'] == jy and r['surf'] == sf)

    # ④ 牝馬 / 牡馬 / セン馬
    if s in ('牝馬', '牡馬', 'セン馬'):
        code = {'牡馬': 1, '牝馬': 2, 'セン馬': 3}[s]
        return ('性別', lambda r, c=code: r['sex'] == c)

    # ⑤ {芝|ダート}{短距離|マイル|中距離|長距離}（NNNNm～NNNNm）
    m = re.fullmatch(r'(芝|ダート)\S*?（(\d+)m[~〜～](\d+)m）', s)
    if m:
        sf = '芝' if m.group(1) == '芝' else 'ダ'
        lo, hi = int(m.group(2)), int(m.group(3))
        return ('距離帯', lambda r, sf=sf, lo=lo, hi=hi:
                r['surf'] == sf and lo <= r['kyori'] <= hi)

    return None


def load_conditions():
    """キャッシュ → {騎手名: {'buy': [(kind, fn, label)], 'fade': [...]}}"""
    out, n_lab, n_ok = {}, 0, 0
    for f in glob.glob(os.path.join(dk.CACHE_DIR, '*.json')):
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        nm = (d or {}).get('jockey')
        conds = dk.extract_conditions(d) if isinstance(d, dict) else None
        if not nm or not conds:
            continue
        rec = {'buy': [], 'fade': []}
        for side in ('buy', 'fade'):
            for c in conds.get(side, []):
                n_lab += 1
                p = parse_condition(c['label'])
                if p:
                    n_ok += 1
                    rec[side].append((p[0], p[1], c['label']))
        if rec['buy'] or rec['fade']:
            out[str(nm).replace(' ', '').replace('　', '')] = rec
    print(f'騎手 {len(out)}人 / 条件ラベル {n_lab}件中 {n_ok}件を照合可能 '
          f'({n_ok / max(n_lab, 1):.0%})', file=sys.stderr)
    return out


def load_runs(year_lo, year_hi):
    """検証窓のレース結果。事前確定情報のみ(脚質・着順以外)。"""
    con = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=30)
    rows = con.execute(f"""
        SELECT r.jockey_name, r.ninki, r.waku, ra.jyo, ra.surface, ra.kyori,
               r.sex, r.chakujun
        FROM results r JOIN races ra ON ra.race_key = r.race_key
        WHERE ra.jyo <= '10' AND ra.surface IN ('芝','ダート')
          AND CAST(ra.year AS INTEGER) BETWEEN {year_lo} AND {year_hi}
          AND r.chakujun > 0 AND r.ninki > 0
    """).fetchall()
    con.close()
    out = []
    for jk, nk, wk, jyo, surf, kyori, sex, chaku in rows:
        try:
            out.append({
                'jk': str(jk or '').replace(' ', '').replace('　', ''),
                'ninki': int(nk), 'waku': int(wk or 0), 'jyo': str(jyo),
                'surf': '芝' if '芝' in str(surf) else 'ダ',
                'kyori': int(kyori), 'sex': int(sex or 0),
                't3': 1 if int(chaku) <= 3 else 0,
            })
        except (TypeError, ValueError):
            continue
    return out


def resid_z(hits, base_map):
    """人気補正残差と z。hits: [(ninki, t3)...]"""
    n = len(hits)
    if n < 30:
        return None
    obs = sum(t for _, t in hits)
    exp = sum(base_map.get(min(nk, 18), 0.15) for nk, _ in hits)
    var = sum(p * (1 - p) for p in
              (base_map.get(min(nk, 18), 0.15) for nk, _ in hits))
    if var <= 0:
        return None
    return {'rate': obs / n, 'exp': exp / n, 'resid': (obs - exp) / n,
            'z': (obs - exp) / math.sqrt(var), 'n': n}


def evaluate(runs, conds, label):
    """買い条件/消し条件に該当した騎乗の複勝率残差を測る。"""
    base = defaultdict(lambda: [0, 0])
    for r in runs:
        b = base[min(r['ninki'], 18)]
        b[0] += r['t3']; b[1] += 1
    base_map = {k: (v[0] / v[1]) for k, v in base.items() if v[1] >= 50}

    buy, fade, by_kind = [], [], defaultdict(lambda: {'buy': [], 'fade': []})
    for r in runs:
        c = conds.get(r['jk'])
        if not c:
            continue
        for side, bucket in (('buy', buy), ('fade', fade)):
            for kind, fn, _lb in c[side]:
                try:
                    if fn(r):
                        bucket.append((r['ninki'], r['t3']))
                        by_kind[kind][side].append((r['ninki'], r['t3']))
                        break          # 1騎乗につき片側1回だけ計上
                except Exception:
                    continue

    print(f'\n{"=" * 78}\n{label}  (対象騎乗 {len(runs):,})\n{"=" * 78}')
    print(f'{"群":26s} {"複勝率":>7s} {"期待":>7s} {"残差":>8s} {"z":>7s} {"n":>8s}')
    res = {}
    for nm, hits in (('📗買い条件に該当', buy), ('📕消し条件に該当', fade)):
        r = resid_z(hits, base_map)
        res[nm] = r
        if r is None:
            print(f'{nm:26s}  n<30 (判定不能)')
            continue
        print(f'{nm:26s} {r["rate"]:6.2%} {r["exp"]:6.2%} '
              f'{r["resid"] * 100:+7.2f}pp {r["z"]:+7.2f} {r["n"]:8,}')
    print('\n  ── 条件の種類別 ──')
    for kind in sorted(by_kind):
        for side, mark in (('buy', '📗'), ('fade', '📕')):
            r = resid_z(by_kind[kind][side], base_map)
            if r:
                print(f'    {mark}{kind:10s} 残差 {r["resid"] * 100:+6.2f}pp '
                      f'z={r["z"]:+6.2f}  n={r["n"]:,}')
    return res


def main():
    conds = load_conditions()
    if not conds:
        raise SystemExit('db-keibaキャッシュが無い。SRAで取得してから再実行。')

    print('\n★ db-keibaの集計期間は2021-2025。よってそこは in-sample。')
    print('  主窓=2026年(集計より後) / 副窓=2016-2020(集計より前) で検証する。')

    verdicts = {}
    for lo, hi, lb in ((2026, 2026, '【主窓】2026年 ― db-keiba集計期間より"後"(真の未来データ)'),
                       (2016, 2020, '【副窓】2016-2020年 ― 集計期間より"前"'),
                       (2021, 2025, '【参考】2021-2025年 ― ★集計期間そのもの=in-sample(当たって当然)')):
        runs = load_runs(lo, hi)
        if runs:
            verdicts[lb] = evaluate(runs, conds, lb)

    print(f'\n{"=" * 78}\n判定\n{"=" * 78}')
    print('採用ゲート: 主窓(2026)で 📗買い条件が残差>0 かつ z>=2、')
    print('            もしくは 📕消し条件が残差<0 かつ z<=-2。')
    print('            さらに副窓(2016-2020)でも同じ符号なら「本物」。')
    print('※ in-sample窓(2021-2025)だけ効いているなら、それは多重検定の産物。')


if __name__ == '__main__':
    main()
