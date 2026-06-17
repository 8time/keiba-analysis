# -*- coding: utf-8 -*-
"""
波乱度（レース荒れ度）のデータ定量化  ※ロジック置き場 note1 の実装

「固い/通常/波乱/大荒れ」を主観でなく**オッズのエントロピー**で定義する。
各レースの単勝オッズから市場の含意確率 p_i=(1/odds_i)/Σ を出し、
正規化シャノンエントロピー hn=H/ln(頭数) を波乱度スコアとする（0=一強、1=横一線）。
hnの四分位で4段階に分け、各段階で「実際の決着の荒れ方」を集計＝データ駆動の4段階定義。

中央(JRA)・払戻ありレースのみ。read-only（取込と共存）。
実行: py -3.14 scripts/race_chaos.py
"""
import sys, io, os, sqlite3, math, statistics
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scratch_chaos.txt')
JRA = "('01','02','03','04','05','06','07','08','09','10')"

def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120)
    con.row_factory = sqlite3.Row
    L = []; p = lambda *a: L.append(' '.join(str(x) for x in a))

    # 中央・有効オッズのみ、race_key順で流す
    q = f"""SELECT r.race_key, r.win_odds, r.ninki, r.chakujun, r.kyakushitsu
            FROM results r JOIN races ra ON ra.race_key=r.race_key
            WHERE ra.jyo IN {JRA} AND r.win_odds IS NOT NULL AND r.win_odds>0 AND r.chakujun>=1
            ORDER BY r.race_key"""
    races = []   # {'hn','n','win_ninki','win_odds','win_kyaku'}
    cur_key = None; horses = []
    def flush(hs):
        n = len(hs)
        if n < 5: return
        inv = [1.0/h['win_odds'] for h in hs]
        Z = sum(inv)
        if Z <= 0: return
        ps = [x/Z for x in inv]
        H = -sum(pi*math.log(pi) for pi in ps if pi > 0)
        hn = H/math.log(n) if n > 1 else 0
        win = next((h for h in hs if h['chakujun'] == 1), None)
        if not win: return
        races.append({'hn': hn, 'n': n, 'win_ninki': win['ninki'],
                      'win_odds': win['win_odds'], 'win_kyaku': win['kyakushitsu']})
    for row in con.execute(q):
        if row['race_key'] != cur_key:
            if horses: flush(horses)
            horses = []; cur_key = row['race_key']
        horses.append(row)
    if horses: flush(horses)
    con.close()

    if not races:
        print("データなし"); return
    races.sort(key=lambda r: r['hn'])
    N = len(races)
    # 四分位で4段階
    q1, q2, q3 = races[N//4]['hn'], races[N//2]['hn'], races[3*N//4]['hn']
    def band(hn):
        if hn < q1: return '1:固い'
        if hn < q2: return '2:通常'
        if hn < q3: return '3:波乱'
        return '4:大荒れ'
    from collections import defaultdict
    agg = defaultdict(list)
    for r in races: agg[band(r['hn'])].append(r)

    p("="*74)
    p("波乱度のデータ定量化（オッズ・エントロピー / note1）")
    p("="*74)
    p(f"対象 {N:,} レース（中央・払戻あり）")
    p(f"エントロピー閾値: 固い<{q1:.3f} / 通常<{q2:.3f} / 波乱<{q3:.3f} / 大荒れ≥{q3:.3f}")
    p("")
    p("段階      レース数  1番人気勝率  勝馬平均人気  勝馬平均配当  差し追込決着率")
    for b in ('1:固い', '2:通常', '3:波乱', '4:大荒れ'):
        rs = agg[b]
        if not rs: continue
        n = len(rs)
        fav_win = sum(1 for r in rs if r['win_ninki'] == 1)/n*100
        avg_winpop = statistics.mean([r['win_ninki'] for r in rs if r['win_ninki']])
        avg_pay = statistics.mean([r['win_odds'] for r in rs]) * 100
        sashi = sum(1 for r in rs if r['win_kyaku'] in ('3', '4'))/n*100
        p(f"  {b:<8} {n:>8,}  {fav_win:8.1f}%   {avg_winpop:8.1f}番   {avg_pay:8.0f}円   {sashi:8.1f}%")

    p("")
    p("【読み方】波乱度が上がるほど 1番人気勝率↓・勝ち馬の人気↓・配当↑・差し追込決着↑ なら、")
    p("          このエントロピー指標が『荒れ』を正しく捉えている＝4段階を客観定義できた証拠。")
    p("【活用】出走前にこのhnを計算→『大荒れ』判定レースは穴・中穴の配分を厚く、")
    p("        『固い』判定レースは本命圧縮。パイプライン段1(妙味レース選別)の土台。")

    open(OUT, 'w', encoding='utf-8').write('\n'.join(L))
    print("レポート出力:", OUT)

if __name__ == '__main__':
    main()
