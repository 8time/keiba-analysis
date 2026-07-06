# -*- coding: utf-8 -*-
"""複勝×高combo人気薄 の実配当ROI検証(買い方研究の突破口)。

3連単は全帯で控除率floor(75%)は超えるが利益(100%)未満だった(verified_formation_roi・市場効率的)。
しかし我々の検証済みエッジ(末脚/combo/荒れ)は全て『3着内率』の話で人気薄に集中=券種がミスマッチだった。
3着内エッジに正しく対応する券種=複勝/ワイド。しかも複勝プールは単勝/3連単より資金が薄い=市場効率が低い。

仮説: 人気薄(6+)×combo(荒れ6シグナル同時発火数)が多い馬を複勝で買うと+EVになるのでは?
→ payouts表の複勝実配当(網羅率99.9%)でbootstrap 90%CI検証。
結果: combo≥4で ROI中央123.5%・CI下限109.8%>100% = 統計的に+EV。combo≥3は損益分岐±(2025は+有意)。
※comboはCSVで2024+のみ付与(2.5年)=標本限定。より長い履歴で再確認する価値あり(Fable案件候補)。

⚠⚠ 事後注記(2026-07-07・Fable案件③ scripts/fukusho_wide_ev.py で反証済み) ⚠⚠
  この+EVは**look-aheadリークの幻**と判定された。combo構成モジュールの統計が凍結DB全期間
  (=歴史レースから見た未来)を含むため(補正T get_figure=馬の未来走含むベスト図/jockey_power
  before_key無し/血統静的辞書)。厳密leak-free版combo6pでは全期間-EV(≥4でROI81-85%)。
  リーク署名: +EVはleak-free版と不一致の群(未来情報でのみ上位)にROI144%で集中し、
  一致群は104%(非有意)、未来情報が最少の2026年は97.7%で消滅。
  → この結果を+EVの根拠に使わないこと。詳細=repo/fable_report_fukusho_wide.md。
"""
import os
import sys
import sqlite3
import random
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import csv_data as cd
from core import jockey_jv as jj


def load_fukusho():
    """(race_key, umaban) -> 複勝配当。複勝は1レース3頭ぶん。"""
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = {}
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type='複勝'"):
        c = str(combo)
        if c.isdigit():
            out[(rk, int(c))] = float(pay)
    con.close()
    return out


def main():
    print("複勝配当 読み込み...")
    fuku = load_fukusho()
    df = cd.load_horses(pop_min=6, cols=['race_key', 'day', 'ninki', 'combo',
                                         'chakujun', 'umaban', 'top3'])
    df = df[df['combo'].notna()]
    print(f"  人気薄(6+)×combo付与 {len(df):,}頭")

    # 網羅性
    t3 = df[df['top3'] == 1]
    cov = sum(1 for r in t3.itertuples(index=False)
              if (str(r.race_key), int(r.umaban)) in fuku) / max(len(t3), 1)
    print(f"  複勝配当 網羅率(3着内馬): {cov:.1%}")

    def recs(sub):
        out = []
        for r in sub.itertuples(index=False):
            p = fuku.get((str(r.race_key), int(r.umaban)), 0.0)
            out.append((100.0, p if r.top3 == 1 else 0.0))
        return out

    random.seed(42)

    def report(sub, label):
        rr = recs(sub)
        m = len(rr)
        if m < 50:
            print(f"  {label:22s} n={m}(小)")
            return
        hit = sum(1 for x in rr if x[1] > 0)
        rois = []
        for _ in range(2000):
            s = [rr[random.randrange(m)] for _ in range(m)]
            c = sum(x[0] for x in s); r = sum(x[1] for x in s)
            rois.append(r / c)
        rois.sort()
        lo, mid, hi = rois[100], rois[1000], rois[1900]
        v = '★★+EV(CI下限>100%)' if lo > 1.0 else ('floor超' if lo > 0.75 else '未達')
        print(f"  {label:22s} n={m:6d} 複勝率{hit/m:5.1%} ROI中央{mid:6.1%} "
              f"90%CI[{lo:5.1%},{hi:6.1%}] {v}")

    print("\n=== 人気薄(6+) 複勝ROI by combo (実配当・bootstrap 90%CI・2024-2026) ===")
    for c in range(0, 5):
        report(df[df['combo'] == c], f'combo={c}')
    report(df[df['combo'] >= 2], 'combo>=2')
    report(df[df['combo'] >= 3], 'combo>=3')
    report(df[df['combo'] >= 4], 'combo>=4')
    report(df, '人気薄6+ 全体(基準)')

    print("\n=== combo>=3 年別安定性 ===")
    for y in (2024, 2025, 2026):
        report(df[(df['combo'] >= 3) & (df['day'] // 10000 == y)], f'combo>=3 {y}')

    print("\n[判定] combo≥4の複勝はCI下限>100%=統計的に+EV(3連単の壁と別物)。"
          "3着内エッジ×効率の低い複勝プールで歪みが残る。要: 長い履歴での再確認・ワイド検証・オッズ帯最適化。")


if __name__ == '__main__':
    main()
