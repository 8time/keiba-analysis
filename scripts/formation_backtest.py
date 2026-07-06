# -*- coding: utf-8 -*-
"""3連単フォーメーション 実配当ROIバックテスト(買い方研究)。

CSV特徴ストア(scripts/csv_data)＋DBのpayouts表(実際の3連単配当)で、買い方を実配当で直接対決:
  Rank源 : 人気(ninki) vs 実力(ability_score=LTR・強適Rankのオフライン代理)
  買い方 : F_tight(堅・Rank1軸) / F_jai(じゃい式・広角多点) / F_arare(荒れ用・妙味馬1着) / 可変AI
検証したい核心:
  ①Rank(実力)軸は人気軸よりROIが高いか(市場とのズレ=エッジがあるか)
  ②レース確信度(arare_prob)で買い方を可変+見送りにすると資金効率が上がるか
  ③荒れレースで1着に妙味馬(combo)を入れると高配当を拾えるか

正直な限界: 強適Rankは実スクレイプ依存でオフライン再現不可→ability_score(LTR recall@7=0.936)で代理。
  3連単は分散が巨大(最大¥5,836万)→平均ROIは大穴数本で膨らむ。中央値/的中率/holdout/最大DDで見る。
  train≤2024で確信度しきい値を決めholdout2025で検証(過学習防止)。控除率25%の壁は本質的に厳しい。
"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import csv_data as cd
from core import jockey_jv as jj
from core import value_scanner as vs

MIN_HORSES = 8   # 少頭数は3連単の妙味薄→除外


def load_trifecta_payouts():
    """{race_key: ((w1,w2,w3), payout)} 実際の3連単配当。"""
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = {}
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type='3連単'"):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            out[rk] = ((int(c[:2]), int(c[2:4]), int(c[4:6])), float(pay))
    con.close()
    return out


def trifecta_points(col1, col2, col3):
    """順序付き3連単の点数(1着∈col1,2着∈col2,3着∈col3・3頭相異)。"""
    n = 0
    for a in col1:
        for b in col2:
            if b == a:
                continue
            for c in col3:
                if c == a or c == b:
                    continue
                n += 1
    return n


def hit(win, col1, col2, col3):
    w1, w2, w3 = win
    return (w1 in col1) and (w2 in col2) and (w3 in col3)


def formations(rank_umas, ana_umas):
    """Rank順の馬番list(rank_umas[0]=Rank1)と妙味馬list から各買い方の(col1,col2,col3)を返す。"""
    R = rank_umas
    def top(k):
        return R[:k]
    F = {}
    # 堅: Rank1を1着固定・相手少なめ
    F['tight'] = (top(1), top(3), top(5))
    # じゃい式: 上位2頭を1着・広角多点
    F['jai'] = (top(2), top(4), top(7))
    # 荒れ用: 1着に妙味馬(combo)＋Rank2-3を入れる・2/3着は広く
    c1 = []
    for u in (ana_umas[:2] + top(3)[1:3]):   # 妙味上位2＋Rank2,3
        if u not in c1:
            c1.append(u)
    c1 = c1[:3] or top(2)
    F['arare'] = (c1, top(5), top(7))
    return F


def main():
    print("payouts(3連単実配当) 読み込み...")
    payout = load_trifecta_payouts()
    print(f"  {len(payout):,}レース")
    df = cd.load_horses(cols=['race_key', 'day', 'ninki', 'win_odds', 'ability_score',
                              'combo', 'chakujun', 'umaban', 'is_handi1'])
    df = df[df['ability_score'].notna() & df['umaban'].notna()]
    by_race = defaultdict(list)
    for r in df.itertuples(index=False):
        by_race[str(r.race_key)].append(r)   # CSVはint64・payoutはstr→strで統一

    # period -> filt -> ranksrc -> strat -> [cost, ret, hits, points_sum, n, ret_capped]
    # filt = 参加フィルタ: all=全レース / vedge=検証済み荒れ条件(ハンデ/16頭/●大穴・verified_arare) /
    #        ap62=荒れ確率≥0.62 のレースだけ参加。ret_capped=配当¥200k頭打ち(巨大配当の変動除去)。
    CAP = 200000.0
    STRATS = ('tight', 'jai', 'arare', 'variable', 'variable_skip')
    FILTS = ('all', 'vedge', 'ap62')
    agg = {p: {ft: {rs: {s: [0.0, 0.0, 0, 0, 0, 0.0] for s in STRATS}
                    for rs in ('ninki', 'ability')} for ft in FILTS}
           for p in ('train', 'holdout', 'other')}
    regime_n = {p: defaultdict(int) for p in ('train', 'holdout', 'other')}
    vedge_n = {p: 0 for p in ('train', 'holdout', 'other')}
    # holdoutの主要セルは per-race (cost,ret) を貯めてbootstrapでROIの信頼区間を出す
    # (¥200k capは荒れの大穴を切りすぎ=保守的すぎるので、raw ROIの分布そのものを見る)
    boot = defaultdict(list)

    for rk, rows in by_race.items():
        if rk not in payout or len(rows) < MIN_HORSES:
            continue
        period = 'train' if rows[0].day // 10000 <= cd.TRAIN_END else (
            'holdout' if rows[0].day // 10000 == cd.HOLDOUT_YEAR else 'other')
        # 'other'(2026)も除外しない: フォーメーションはデータにfitしないので全年プールでCIを狭める
        win, pay = payout[rk]
        odds_list = [r.win_odds for r in rows if r.win_odds and r.win_odds > 0]
        if len(odds_list) < 3:
            continue
        ap = vs.arare_prob(odds_list, {'is_handicap': bool(rows[0].is_handi1)}, len(rows))
        if ap is None:
            continue
        # レジーム(確信度): 荒れ確率で堅/中/荒れ
        if ap < 0.42:
            regime = 'tight'
        elif ap < 0.60:
            regime = 'jai'
        else:
            regime = 'arare'
        regime_n[period][regime] += 1
        skip_zone = 0.46 <= ap <= 0.54   # 中庸デッドゾーン=見送り候補

        # 参加フィルタ判定: 検証済み荒れ条件(ハンデ/フルゲート16頭/●大穴本命不在=verified_arare)
        no_fav = vs.no_favorite_flag(odds_list) is not None
        is_vedge = bool(rows[0].is_handi1) or len(rows) >= 16 or no_fav
        if is_vedge:
            vedge_n[period] += 1
        filts_hit = ['all'] + (['vedge'] if is_vedge else []) + (['ap62'] if ap >= 0.62 else [])

        # 妙味馬(人気薄6+×combo≥2)
        ana = [int(r.umaban) for r in sorted(rows, key=lambda x: -(x.combo or 0))
               if r.ninki and r.ninki >= 6 and (r.combo or 0) >= 2]

        for rs in ('ninki', 'ability'):
            if rs == 'ninki':
                ranked = sorted(rows, key=lambda x: (x.ninki if x.ninki else 99))
            else:
                # ability_score=4シグナルpct平均・低い=良い(export_features_csv)→昇順でRank1=最強
                ranked = sorted(rows, key=lambda x: (x.ability_score if x.ability_score is not None else 1e9))
            rank_umas = [int(r.umaban) for r in ranked]
            F = formations(rank_umas, ana)

            def apply(strat, cols):
                pts = trifecta_points(*cols)
                if pts <= 0:
                    return
                _hit = hit(win, *cols)
                for ft in filts_hit:
                    a = agg[period][ft][rs][strat]
                    a[0] += pts * 100        # cost
                    a[1] += pay if _hit else 0.0              # return(raw)
                    a[2] += 1 if _hit else 0                  # hits
                    a[3] += pts              # points
                    a[4] += 1                # participated
                    a[5] += min(pay, CAP) if _hit else 0.0    # return(capped¥200k)
                    if rs == 'ninki' and strat in ('variable', 'variable_skip'):
                        boot[(ft, strat)].append((pts * 100, pay if _hit else 0.0))  # 全年プール

            apply('tight', F['tight'])
            apply('jai', F['jai'])
            apply('arare', F['arare'])
            # 可変AI: レジームで買い方切替
            apply('variable', F[regime])
            # 可変+見送り: 中庸デッドゾーンは参加しない
            if not skip_zone:
                apply('variable_skip', F[regime])

    _FILT_LABEL = {'all': '全レース', 'vedge': '検証荒れ(ハンデ/16頭/●大穴)', 'ap62': '荒れ確率≥62%'}

    def show(period):
        print(f"\n{'='*78}\n=== {period} (train≤{cd.TRAIN_END}/holdout{cd.HOLDOUT_YEAR}) ===")
        print(f"  レジーム分布: {dict(regime_n[period])} / 検証荒れレース {vedge_n[period]}件")
        for ft in FILTS:
            print(f"\n  ── 参加フィルタ: {_FILT_LABEL[ft]} ──")
            print(f"  {'Rank源':7s} {'買い方':13s} {'参加':>6s} {'的中率':>7s} {'点数':>5s} {'購入':>7s} "
                  f"{'回収率':>7s} {'頑健ROI':>7s}")
            for rs in ('ninki', 'ability'):
                for s in STRATS:
                    cost, ret, hits, pts, n, retc = agg[period][ft][rs][s]
                    if n < 50:
                        continue
                    roi = ret / cost if cost else 0
                    roic = retc / cost if cost else 0
                    star = ' ★' if roic >= 0.80 else ''
                    print(f"  {rs:7s} {s:13s} {n:6d} {hits/n:6.1%} {pts/n:5.1f} "
                          f"¥{pts/n*100:6.0f} {roi:7.1%} {roic:7.1%}{star}")

    show('train')
    show('holdout')

    # ── bootstrap: raw ROIの90%信頼区間(荒れ大穴を切らずに分布で判定) ──
    import random
    random.seed(42)
    print(f"\n{'='*78}\n=== 全年プール(2021-2026) ninki軸 raw ROI ブートストラップ(1000回・レース再抽出) ===")
    print("  75%(控除率壁)を90%CI下限が越えれば『レース選択で市場を出し抜く』が有意に成立。")
    print(f"  {'買い方(フィルタ)':28s} {'参加':>5s} {'ROI中央':>8s} {'90%CI下限':>9s} {'上限':>8s}")
    for (ft, strat), recs in sorted(boot.items()):
        if len(recs) < 100:
            continue
        rois = []
        m = len(recs)
        for _ in range(1000):
            samp = [recs[random.randrange(m)] for _ in range(m)]
            c = sum(x[0] for x in samp)
            r = sum(x[1] for x in samp)
            rois.append(r / c if c else 0)
        rois.sort()
        lo, mid, hi = rois[50], rois[500], rois[950]
        # 75%=控除率floor(=無情報ベット). 100%=損益分岐(利益). この2段で判定。
        if lo > 1.0:
            verdict = ' ★★利益(100%超)'
        elif lo > 0.75:
            verdict = ' ★floor超(スキル有だが<100%=長期負け)'
        elif hi < 0.75:
            verdict = ' floor未達(市場並以下)'
        else:
            verdict = ' 75%を跨ぐ=不確実'
        print(f"  {strat+'/'+_FILT_LABEL[ft]:28s} {m:5d} {mid:7.1%} {lo:8.1%} {hi:7.1%}{verdict}")
    print("  ※75%=控除率floor(無情報ベットの期待値)。100%=損益分岐。floor超=選択にスキル有だが、"
          "ROI中央が<100%なら長期では負け(利益化には未到達)。")

    print("\n[判定] 検証荒れ/荒れ確率≥62%のフィルタで頑健ROIが75%(控除率壁)を越えるか。"
          "越えれば『レース選択で市場を出し抜く』が成立(★=頑健ROI≥80%)。越えなければ荒れ選択も"
          "priced-in=買い方でなく見送りでの資金効率改善に留まる。ninki軸が本命(win slotで人気>実力代理)。")


if __name__ == '__main__':
    main()
