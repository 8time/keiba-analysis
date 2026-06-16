# -*- coding: utf-8 -*-
"""
軸選定 head-to-head: ◎〇ルール vs 固定軸(人気上位2頭)
─────────────────────────────────────────────
3連複の土台＝『軸2頭が両方3着内(ダブル複勝)』。これが高いほど良い軸。

比較:
  [固定]  軸 = 人気1位+2位 を無条件採用。
  [ルール] 軸 = core/axis_selector の信頼度上位2頭。ただし両方が信頼度フロア
           (◎≥50, 〇≥42%)を通過したレースのみ『採用(play)』。
           = フロアが見送りフィルタとして働く。

検証する問い:
  (a) ルールが選ぶ軸2頭は固定軸と何%違うか(オッズ=人気順位なので大半一致のはず)。
  (b) ルールが play したレースのダブル複勝率は、
      固定軸(全レース)や同レースの固定軸より高いか＝フロア(見送り)に価値があるか。
  (c) play率(カバレッジ)。

指標=複勝率系のみ(win_odds欠損のためROIは不可。[[verified_ohtani_trap]])。
"""
import sys, io, os, sqlite3, argparse
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.jockey_jv import _parse_time_msst as ptime
from core import axis_selector as axs

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')


def date_key(y, m):
    try:
        return int(y) * 10000 + int(m)
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train_from', type=int, default=2014)
    ap.add_argument('--test_from', type=int, default=2021)
    ap.add_argument('--test_to', type=int, default=2025)
    ap.add_argument('--min_field', type=int, default=8)
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print(f"読み込み中... (year>={args.train_from})")
    rows = con.execute(
        "SELECT race_key, year, monthday, ketto_num, chakujun, ninki, win_odds, time "
        "FROM results WHERE CAST(year AS INTEGER) >= ?", (args.train_from,)).fetchall()
    con.close()
    print(f"  results: {len(rows):,}行")

    by_race = defaultdict(list)
    for r in rows:
        by_race[r['race_key']].append(r)

    # 前走圧勝margin: hist[ketto] = sorted [(dk, chakujun, win_margin_or_None)]
    hist = defaultdict(list)
    for rk, rs in by_race.items():
        dk = date_key(rs[0]['year'], rs[0]['monthday'])
        t1 = None; t2 = None
        for r in rs:
            if r['chakujun'] == 1: t1 = ptime(r['time'])
            elif r['chakujun'] == 2: t2 = ptime(r['time'])
        wm = (t2 - t1) if (t1 is not None and t2 is not None) else None
        for r in rs:
            if r['chakujun'] and r['chakujun'] > 0:
                hist[r['ketto_num']].append((dk, r['chakujun'], wm if r['chakujun'] == 1 else None))
    for k in hist:
        hist[k].sort(key=lambda x: x[0])

    def prev_margin(ketto, dk):
        h = hist.get(ketto)
        if not h:
            return None
        past = [x for x in h if x[0] < dk]
        if not past:
            return None
        _, pc, pwm = past[-1]
        return pwm if pc == 1 else None

    # 集計
    fixed_n = fixed_double = 0          # 固定軸(全レース)
    rule_play = rule_double = 0          # ルールがplayしたレース
    fixed_on_play_double = 0             # 同じplayレースでの固定軸ダブル複勝(比較用)
    diff_pair = 0                        # ルール軸2頭が固定軸と異なるレース数
    eligible = 0                         # 検証対象レース数

    for rk, rs in by_race.items():
        if not (args.test_from <= int(rs[0]['year']) <= args.test_to):
            continue
        if (rs[0]['shusso_tosu'] if 'shusso_tosu' in rs[0].keys() else len(rs)) and len(rs) < args.min_field:
            continue
        dk = date_key(rs[0]['year'], rs[0]['monthday'])
        # 各馬: name代わりにketto, pop, odds, top3?, prev_margin
        horses = []
        for r in rs:
            if not r['ninki'] or not r['chakujun'] or r['chakujun'] <= 0:
                continue
            horses.append({
                'key': r['ketto_num'], 'pop': r['ninki'],
                'odds': r['win_odds'] if (r['win_odds'] and r['win_odds'] > 0) else None,
                'top3': 1 if r['chakujun'] <= 3 else 0,
                'pwm': prev_margin(r['ketto_num'], dk),
            })
        if len(horses) < args.min_field:
            continue
        # 人気1,2が揃っているか
        by_pop = {h['pop']: h for h in horses}
        if 1 not in by_pop or 2 not in by_pop:
            continue
        eligible += 1

        # [固定] 人気1+2
        fa, fb = by_pop[1], by_pop[2]
        fixed_dbl = fa['top3'] * fb['top3']
        fixed_n += 1; fixed_double += fixed_dbl

        # [ルール] 信頼度上位2頭
        conf = []
        for h in horses:
            c = axs.axis_confidence(h['pop'], h['odds'], h['pwm'])
            if c is not None:
                conf.append((c, h))
        if len(conf) < 2:
            continue
        conf.sort(key=lambda x: x[0], reverse=True)
        (c1, h1), (c2, h2) = conf[0], conf[1]
        # フロア: ◎≥50, 〇≥42
        if c1 >= axs.FLOOR['◎'] and c2 >= axs.FLOOR['〇']:
            rule_play += 1
            rule_double += h1['top3'] * h2['top3']
            fixed_on_play_double += fixed_dbl
            pair_rule = {h1['key'], h2['key']}
            pair_fixed = {fa['key'], fb['key']}
            if pair_rule != pair_fixed:
                diff_pair += 1

    print(f"\n=== 軸 head-to-head (test {args.test_from}-{args.test_to}, 最低{args.min_field}頭, 対象{eligible}R) ===")
    print(f"\n[固定軸=人気1+2位] 全{fixed_n}R")
    print(f"   軸2頭ダブル複勝率(両方3着内): {100*fixed_double/fixed_n:.1f}%")
    if rule_play:
        print(f"\n[ルール軸=信頼度上位2頭・フロア通過時のみplay]")
        print(f"   play率(カバレッジ): {100*rule_play/eligible:.1f}%  ({rule_play}/{eligible}R)")
        print(f"   ルール軸ペアが固定軸と異なる: {100*diff_pair/rule_play:.1f}%  ({diff_pair}/{rule_play}R)")
        print(f"   ルール軸 ダブル複勝率(playレース): {100*rule_double/rule_play:.1f}%")
        print(f"   固定軸 ダブル複勝率(同じplayレース): {100*fixed_on_play_double/rule_play:.1f}%")
        print(f"   → フロア(見送り)の効果: ダブル複勝率 全{100*fixed_double/fixed_n:.1f}% "
              f"→ play時{100*rule_double/rule_play:.1f}% ({100*rule_double/rule_play - 100*fixed_double/fixed_n:+.1f}pp)")
        print(f"   → 同レース内 ルール vs 固定: {100*rule_double/rule_play:.1f}% vs {100*fixed_on_play_double/rule_play:.1f}% "
              f"({100*rule_double/rule_play - 100*fixed_on_play_double/rule_play:+.1f}pp)")


if __name__ == '__main__':
    main()
