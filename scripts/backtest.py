# -*- coding: utf-8 -*-
"""
① バックテスト＆最適化エンジン（jravan.db / 64bit）

買い目戦略を過去データで「回収率(ROI)・的中率・最大ドローダウン」で検証。
重要: 時系列(年)順で評価＝データリーク防止。コンセプトドリフト確認のため年代別も集計。
払戻は payouts の実配当(100円あたり)で精算。書込み中DBと共存するため read-only + timeout。

使い方:
  py -3.14 scripts/backtest.py
ライブラリ:
  from backtest import simulate, roi_by_segment
"""
import sys, io, os, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scratch_backtest.txt')
STAKE = 100

def connect_ro():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120)
    con.row_factory = sqlite3.Row
    return con

def _fmt(bets, hits, ret):
    if not bets: return "(該当なし)"
    staked = bets * STAKE
    return f"投票{bets:>7,}  的中{hits/bets*100:5.1f}%  回収率{ret/staked*100:6.1f}%  収支{ret-staked:+,}円"

# ── 人気別 単勝/複勝 回収率（年代別ドリフトを1パスSQLで） ──
def popularity_drift(con, ranks=(1,2,3,5,10)):
    q = """
    SELECT (CAST(r.year AS INTEGER)/10)*10 AS dec, r.ninki AS ninki,
      COUNT(*) AS bets,
      SUM(CASE WHEN pw.payout>0 THEN 1 ELSE 0 END) AS win_hits,
      SUM(COALESCE(pw.payout,0)) AS win_ret,
      SUM(CASE WHEN pp.payout>0 THEN 1 ELSE 0 END) AS plc_hits,
      SUM(COALESCE(pp.payout,0)) AS plc_ret
    FROM results r
    LEFT JOIN payouts pw ON pw.race_key=r.race_key AND pw.bet_type='単勝' AND CAST(pw.combo AS INTEGER)=r.umaban
    LEFT JOIN payouts pp ON pp.race_key=r.race_key AND pp.bet_type='複勝' AND CAST(pp.combo AS INTEGER)=r.umaban
    WHERE r.ninki BETWEEN 1 AND 18 AND r.chakujun>=1
      AND r.jyo IN ('01','02','03','04','05','06','07','08','09','10')
    GROUP BY dec, r.ninki
    """
    data = {}  # (dec,ninki) -> row
    allagg = {}  # ninki -> aggregated across decades
    for row in con.execute(q):
        data[(row['dec'], row['ninki'])] = row
        a = allagg.setdefault(row['ninki'], {'bets':0,'wh':0,'wr':0,'ph':0,'pr':0})
        a['bets'] += row['bets']; a['wh'] += row['win_hits']; a['wr'] += row['win_ret']
        a['ph'] += row['plc_hits']; a['pr'] += row['plc_ret']
    return data, allagg

# ── オッズ帯別 単勝（ロングショットバイアス） ──
def oddsband(con):
    q = """
    SELECT CASE
      WHEN r.win_odds<3 THEN '1:1.0-3.0倍'
      WHEN r.win_odds<7 THEN '2:3-7倍'
      WHEN r.win_odds<15 THEN '3:7-15倍'
      WHEN r.win_odds<50 THEN '4:15-50倍'
      ELSE '5:50倍超' END AS band,
      COUNT(*) AS bets,
      SUM(CASE WHEN pw.payout>0 THEN 1 ELSE 0 END) AS hits,
      SUM(COALESCE(pw.payout,0)) AS ret
    FROM results r
    LEFT JOIN payouts pw ON pw.race_key=r.race_key AND pw.bet_type='単勝' AND CAST(pw.combo AS INTEGER)=r.umaban
    WHERE r.win_odds IS NOT NULL AND r.win_odds>0 AND r.chakujun>=1
      AND r.jyo IN ('01','02','03','04','05','06','07','08','09','10')
    GROUP BY band ORDER BY band
    """
    return list(con.execute(q))

# ── ドローダウン: 1番人気単勝を時系列で買い続けた累積収支 ──
def drawdown_fav_win(con):
    q = """
    SELECT r.year, r.monthday,
      SUM(COALESCE(pw.payout,0) - 100) AS daily_pl
    FROM results r
    LEFT JOIN payouts pw ON pw.race_key=r.race_key AND pw.bet_type='単勝' AND CAST(pw.combo AS INTEGER)=r.umaban
    WHERE r.ninki=1 AND r.chakujun>=1
      AND r.jyo IN ('01','02','03','04','05','06','07','08','09','10')
    GROUP BY r.year, r.monthday ORDER BY r.year, r.monthday
    """
    cum = 0; peak = 0; maxdd = 0
    for row in con.execute(q):
        cum += (row['daily_pl'] or 0)
        peak = max(peak, cum); maxdd = min(maxdd, cum - peak)
    return cum, maxdd

# ── 汎用シミュレータ（任意戦略・後の拡張用） ──
def simulate(strategy, con=None, year_from='1986', year_to='2026'):
    """strategy(race)->[(bet_type,umaban)] を時系列で評価。{'bets','hits','staked','returned','roi'}"""
    own = con is None
    if own: con = connect_ro()
    from collections import defaultdict
    res_by_race = defaultdict(list)
    races = {}
    for r in con.execute("SELECT race_key,year,jyo,surface,kyori FROM races WHERE year BETWEEN ? AND ?",
                         (year_from, year_to)):
        races[r['race_key']] = dict(r); races[r['race_key']]['horses'] = []
    for r in con.execute("SELECT race_key,umaban,ninki,win_odds,chakujun,kyakushitsu,waku,jockey_code FROM results WHERE year BETWEEN ? AND ?",
                         (year_from, year_to)):
        if r['race_key'] in races: races[r['race_key']]['horses'].append(dict(r))
    pay = {}
    for p in con.execute("""SELECT p.race_key,p.bet_type,p.combo,p.payout FROM payouts p
                            JOIN races ra ON ra.race_key=p.race_key WHERE ra.year BETWEEN ? AND ? AND p.bet_type IN ('単勝','複勝')""",
                         (year_from, year_to)):
        try: uma=int(p['combo'])
        except: continue
        pay.setdefault(p['race_key'],{}).setdefault(p['bet_type'],{})[uma]=p['payout']
    bets=hits=staked=returned=0
    for rk, race in races.items():
        for bet_type, umaban in strategy(race):
            ret = pay.get(rk,{}).get(bet_type,{}).get(umaban,0)
            bets+=1; staked+=STAKE; returned+=ret
            if ret>0: hits+=1
    if own: con.close()
    return {'bets':bets,'hits':hits,'staked':staked,'returned':returned,
            'roi': (returned/staked*100 if staked else 0)}

def main():
    L=[]; p=lambda *a: L.append(' '.join(str(x) for x in a))
    con = connect_ro()
    nr = con.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    nres = con.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    yr = con.execute("SELECT MIN(year),MAX(year) FROM races").fetchone()
    p("="*74); p("① バックテスト・エンジン（jravan.db 実データ・時系列評価）"); p("="*74)
    p(f"対象 {nr:,}レース / {nres:,}頭  期間 {yr[0]}〜{yr[1]}  (1点{STAKE}円)")

    DECS = [1980,1990,2000,2010,2020]
    data, allagg = popularity_drift(con)
    for rank in (1,2,3,5,10):
        p(f"\n■ {rank}番人気を買い続けた回収率（年代別ドリフト）")
        a = allagg.get(rank)
        if a:
            p(f"  単勝 全期間: {_fmt(a['bets'],a['wh'],a['wr'])}")
            p(f"  複勝 全期間: {_fmt(a['bets'],a['ph'],a['pr'])}")
            line=[]
            for d in DECS:
                row=data.get((d,rank))
                if row and row['bets']>0:
                    line.append(f"{d}s 単{row['win_ret']/(row['bets']*STAKE)*100:.0f}%/複{row['plc_ret']/(row['bets']*STAKE)*100:.0f}%")
            p("  年代別(単/複回収率): " + "  ".join(line))

    p("\n■ 単勝オッズ帯別 回収率（全期間・ロングショットバイアス）")
    for row in oddsband(con):
        p(f"  {row['band'][2:]:>10}: {_fmt(row['bets'],row['hits'],row['ret'])}")

    cum, maxdd = drawdown_fav_win(con)
    p(f"\n■ 1番人気・単勝を全期間買い続けた場合")
    p(f"  最終収支: {cum:+,}円   最大ドローダウン: {maxdd:+,}円")
    p("  → 控除率の壁で右肩下がり。単純戦略では勝てない＝「歪み(妙味)」を選別する必要があることの実証")

    con.close()
    open(OUT,'w',encoding='utf-8').write('\n'.join(L))
    print("レポート出力:", OUT)

if __name__ == '__main__':
    main()
