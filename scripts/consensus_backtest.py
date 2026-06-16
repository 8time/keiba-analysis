# -*- coding: utf-8 -*-
"""
MAGI 合議ゲート バックテスト — 「承認数が多いほど的中率/ROIは上がるか？」の実測
──────────────────────────────────────────────────────────────────────────
背景: core/magi_consensus.py は「独立した検証済みエッジが一致するほど本物」という
      仮説で 3機(MELCHIOR/BALTHASAR/CASPER)の承認数を信号にしている。だが
      『一致＝上積み』自体は未検証。むしろ verified_spurt_index step2 では
      「単複乖離 × 末脚top の AND は悪化（良い乖離馬を削る）」と分かっている。
      → 票が多い＝良い とは限らない。本スクリプトで人気薄候補について実測する。

検証は jravan.db で歴史的に計算できる "互いに独立な3軸" で合議の原理を再現する:
  S_spurt : 末脚指数 ≥ thr   (results.ato3f をレース内標準化・直近K走平均。CASPER。検証済)
  S_form  : フォーム指数 ≥ thr(results.chakujun をレース内標準化・直近K走平均。MELCHIOR代理)
  S_gap   : オッズ断層アンカー(win_odds 昇順で次馬が ratio 倍に跳ねる直前。BALTHASAR代理)

注意/限界:
  - 本来の BALTHASAR の主力は単複乖離(place odds)だが、jravan.db の odds.place は
    1993-96 と 2026 しか無いため広域窓では使えない → 計算可能な断層アンカーで代理。
    断層は docstring 上「人気7+では効果なし」なので、人気薄では弱い前提で読む。
  - MELCHIOR(強適消去スコア=-人気+factor)は人気依存が強く、人気薄に条件付けると差が出にくい
    → 独立性のため "直近フォーム指数" を代理に使う(オッズ・末脚と別軸)。
  - よって本検証は evaluate_consensus の逐行再現ではなく『合議＝独立軸の一致が
    人気薄の的中/ROIを押し上げるか』という"原理"の検証。

出力: ①各単独軸の人気薄seg ②票数(0/1/2/3)別の勝率/複勝率/単勝ROI
      ③主要ペアの AND / OR  — 票数で単調に良くなるか、ただ点数が減るだけかを判定。
"""
import sys, io, os, sqlite3, statistics, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.value_scanner import odds_gap_anchors

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')


def date_key(year, monthday):
    try:
        return int(year) * 10000 + int(monthday)
    except Exception:
        return 0


def within_race_dev(rs, field, sign):
    """rs(同一レースの行list)について field の値をレース内標準化して dev を返す。
    sign=+1: 値が大きいほど正 / sign=-1: 値が小さいほど正(着順・上がり3F)。"""
    vals = [r[field] for r in rs if r[field] is not None and r[field] > 0]
    if len(vals) < 5:
        return {}
    m = statistics.mean(vals)
    sd = statistics.pstdev(vals)
    if sd <= 0:
        return {}
    out = {}
    for r in rs:
        v = r[field]
        if v is None or v <= 0:
            continue
        out[r['ketto_num']] = sign * (v - m) / sd
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train_from', type=int, default=2015)
    ap.add_argument('--test_from', type=int, default=2021)
    ap.add_argument('--test_to', type=int, default=2025)
    ap.add_argument('--k', type=int, default=3, help='指数に使う直近走数')
    ap.add_argument('--thr', type=float, default=0.8, help='末脚/フォーム指数のしきい値(ライブ採用値)')
    ap.add_argument('--ninki_ana', type=int, default=6, help='人気薄(穴)の下限人気')
    ap.add_argument('--min_field', type=int, default=8, help='最低出走頭数(指数保有)')
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    print(f"読み込み中... (year>={args.train_from})")
    rows = con.execute(
        "SELECT race_key, year, monthday, ketto_num, umaban, chakujun, ninki, win_odds, ato3f "
        "FROM results WHERE CAST(year AS INTEGER) >= ?", (args.train_from,)).fetchall()
    print(f"  結果: {len(rows):,}行")

    by_race = {}
    for r in rows:
        by_race.setdefault(r['race_key'], []).append(r)

    # ── 末脚dev(ato3f, 速い=正) / フォームdev(chakujun, 上位=正) を全レースで算出し馬別履歴に ──
    hist_spurt = {}   # ketto -> [(date_key, dev)]
    hist_form = {}
    for rk, rs in by_race.items():
        dk = date_key(rs[0]['year'], rs[0]['monthday'])
        sdev = within_race_dev(rs, 'ato3f', -1)   # 上がり3Fは小さいほど速い=正
        fdev = within_race_dev(rs, 'chakujun', -1)  # 着順は小さいほど上位=正
        for k, v in sdev.items():
            hist_spurt.setdefault(k, []).append((dk, v))
        for k, v in fdev.items():
            hist_form.setdefault(k, []).append((dk, v))
    for d in (hist_spurt, hist_form):
        for k in d:
            d[k].sort()
    print(f"  末脚履歴 {len(hist_spurt):,}頭 / フォーム履歴 {len(hist_form):,}頭")

    def prior_index(hist, ketto, dk, K):
        h = hist.get(ketto)
        if not h:
            return None
        past = [v for (d2, v) in h if d2 < dk]
        if not past:
            return None
        seg = past[-K:]
        return sum(seg) / len(seg), len(seg)

    races = con.execute(
        "SELECT race_key, year, monthday FROM races WHERE CAST(year AS INTEGER) BETWEEN ? AND ?",
        (args.test_from, args.test_to)).fetchall()
    print(f"検証対象レース: {len(races):,} ({args.test_from}-{args.test_to})\n")

    # 集計器: seg名 -> dict(n,win,place,ret)
    segs = {}
    def add(seg, won, placed, odds):
        b = segs.setdefault(seg, {'n': 0, 'win': 0, 'place': 0, 'ret': 0.0})
        b['n'] += 1
        if won:
            b['win'] += 1
            if odds:
                b['ret'] += odds * 100
        if placed:
            b['place'] += 1

    n_race = 0
    for race in races:
        rk = race['race_key']
        dk = date_key(race['year'], race['monthday'])
        rs = by_race.get(rk)
        if not rs:
            continue

        # オッズ断層アンカー(レース内, 確定win_oddsで代理)
        odds_by_um = {r['umaban']: r['win_odds'] for r in rs
                      if r['umaban'] is not None and r['win_odds'] and r['win_odds'] > 0}
        anchors = odds_gap_anchors(odds_by_um)

        cand = []
        for r in rs:
            si = prior_index(hist_spurt, r['ketto_num'], dk, args.k)
            fi = prior_index(hist_form, r['ketto_num'], dk, args.k)
            if si is None or fi is None:
                continue
            cand.append({
                'um': r['umaban'], 'ninki': r['ninki'], 'chaku': r['chakujun'],
                'odds': r['win_odds'],
                's_idx': si[0], 's_runs': si[1],
                'f_idx': fi[0], 'f_runs': fi[1],
            })
        if len(cand) < args.min_field:
            continue
        n_race += 1

        for c in cand:
            # 人気薄(穴)のみ対象 ── 合議ゲートの焦点候補と同じ
            if not (c['ninki'] and c['ninki'] >= args.ninki_ana):
                continue
            if c['odds'] is None or c['odds'] <= 0:
                continue
            won = (c['chaku'] == 1)
            placed = bool(c['chaku'] and c['chaku'] <= 3)
            od = c['odds']

            s = bool(c['s_idx'] >= args.thr and c['s_runs'] >= 2)   # CASPER
            f = bool(c['f_idx'] >= args.thr and c['f_runs'] >= 2)   # MELCHIOR代理
            g = bool(c['um'] in anchors)                            # BALTHASAR代理
            votes = int(s) + int(f) + int(g)

            add('BASE(人気薄全体)', won, placed, od)
            if s: add('S1 末脚', won, placed, od)
            if f: add('S2 フォーム', won, placed, od)
            if g: add('S3 断層', won, placed, od)
            add(f'votes={votes}', won, placed, od)
            # 主要ペアの AND / OR
            if s and f: add('AND 末脚&フォーム', won, placed, od)
            if s or f: add('OR  末脚|フォーム', won, placed, od)
            if s and g: add('AND 末脚&断層', won, placed, od)
            if votes >= 2: add('votes>=2 (合議)', won, placed, od)

    con.close()

    def pct(a, b):
        return f"{100*a/b:5.1f}%" if b else "  -  "

    base = segs.get('BASE(人気薄全体)', {'n': 0})
    print("=" * 74)
    print(f"■ 検証レース {n_race:,} / 人気薄(>= {args.ninki_ana}番人気) 母数 {base['n']:,}点 "
          f"/ 指数thr={args.thr} K={args.k}")
    print("=" * 74)
    order = ['BASE(人気薄全体)', 'S1 末脚', 'S2 フォーム', 'S3 断層',
             'votes=0', 'votes=1', 'votes=2', 'votes=3', 'votes>=2 (合議)',
             'AND 末脚&フォーム', 'OR  末脚|フォーム', 'AND 末脚&断層']
    print(f"{'セグメント':<22}{'点数':>8}{'勝率':>9}{'複勝率':>9}{'単ROI':>9}")
    print("-" * 74)
    for name in order:
        b = segs.get(name)
        if not b:
            print(f"{name:<22}{0:>8}{'  -  ':>9}{'  -  ':>9}{'  -  ':>9}")
            continue
        print(f"{name:<22}{b['n']:>8}{pct(b['win'], b['n']):>9}"
              f"{pct(b['place'], b['n']):>9}{pct(b['ret'], b['n']*100):>9}")
    print("-" * 74)
    print("判定の読み方:")
    print("  ・votes が増えるほど 勝率/複勝率/ROI が単調に上がる → 合議は本物(承認数=自信度)")
    print("  ・votes>=2 が S1単独(末脚)に勝てない / 点数が減るだけ → 合議は幻想。OR運用が正解")
    print("  ・AND が OR や単独に劣る → step2と同じ『一致を要求すると良い馬を削る』再現")


if __name__ == '__main__':
    main()
