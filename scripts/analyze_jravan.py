# -*- coding: utf-8 -*-
"""data/jravan.db を読んで6領域のデモ分析。レポートをUTF-8で出力（64bitでOK）。"""
import sys, io, os, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scratch_analysis.txt')

JYO = {'01':'札幌','02':'函館','03':'福島','04':'新潟','05':'東京','06':'中山','07':'中京','08':'京都','09':'阪神','10':'小倉',
       '30':'門別','35':'盛岡','36':'水沢','42':'浦和','43':'船橋','44':'大井','45':'川崎','46':'金沢','47':'笠松','48':'名古屋',
       '50':'園田','51':'姫路','54':'高知','55':'佐賀','3F':'帯広(ば)'}
KYAKU = {'1':'逃げ','2':'先行','3':'差し','4':'追込','0':'不明'}

def main():
    con = sqlite3.connect(DB)
    c = con.cursor()
    L = []
    def p(*a): L.append(' '.join(str(x) for x in a))

    nr = c.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    nres = c.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    npay = c.execute("SELECT COUNT(*) FROM payouts").fetchone()[0]
    p("="*70)
    p("JRA-VAN 取込データ 分析デモ")
    p("="*70)
    p(f"レース数={nr}  出走頭数={nres}  払戻組={npay}")
    dr = c.execute("SELECT MIN(year||monthday), MAX(year||monthday) FROM races").fetchone()
    p(f"期間: {dr[0]} 〜 {dr[1]}")

    # 競馬場別
    p("\n■ 競馬場別レース数")
    for jyo, n in c.execute("SELECT jyo, COUNT(*) FROM races GROUP BY jyo ORDER BY COUNT(*) DESC"):
        p(f"  {JYO.get(jyo, jyo)}({jyo}): {n}")

    # 馬場/距離
    p("\n■ 馬場別レース数")
    for surf, n in c.execute("SELECT surface, COUNT(*) FROM races GROUP BY surface ORDER BY COUNT(*) DESC"):
        p(f"  {surf or '不明'}: {n}")

    # ── 人気別 単勝/複勝 回収率（回収率・的中率の核心）──
    p("\n■ 人気別成績（単勝・複勝回収率） ※有効出走のみ")
    p("  人気  頭数   勝率   複勝率(3着内)  単勝回収率  複勝回収率")
    q = """
    SELECT r.ninki,
      COUNT(*) n,
      SUM(CASE WHEN r.chakujun=1 THEN 1 ELSE 0 END) wins,
      SUM(CASE WHEN r.chakujun BETWEEN 1 AND 3 THEN 1 ELSE 0 END) top3,
      SUM(CASE WHEN r.chakujun=1 THEN COALESCE(pw.payout,0) ELSE 0 END) win_ret,
      SUM(COALESCE(pp.payout,0)) place_ret
    FROM results r
    LEFT JOIN payouts pw ON pw.race_key=r.race_key AND pw.bet_type='単勝' AND CAST(pw.combo AS INTEGER)=r.umaban
    LEFT JOIN payouts pp ON pp.race_key=r.race_key AND pp.bet_type='複勝' AND CAST(pp.combo AS INTEGER)=r.umaban
    WHERE r.chakujun>=1 AND r.ninki>=1
    GROUP BY r.ninki ORDER BY r.ninki
    """
    for ninki, n, wins, top3, win_ret, place_ret in c.execute(q):
        if ninki > 18: continue
        wr = wins/n*100
        t3 = top3/n*100
        win_roi = win_ret/(n*100)*100
        place_roi = place_ret/(n*100)*100
        p(f"  {ninki:>3}  {n:>5}  {wr:5.1f}%   {t3:5.1f}%       {win_roi:6.1f}%    {place_roi:6.1f}%")

    # ── 脚質別 複勝率（トラックバイアスproxy）──
    p("\n■ 脚質別 複勝率（コース傾向）")
    p("  脚質    頭数   勝率   複勝率")
    for ky, n, wins, top3 in c.execute("""
        SELECT kyakushitsu, COUNT(*), SUM(CASE WHEN chakujun=1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN chakujun BETWEEN 1 AND 3 THEN 1 ELSE 0 END)
        FROM results WHERE chakujun>=1 GROUP BY kyakushitsu ORDER BY kyakushitsu"""):
        p(f"  {KYAKU.get(ky,ky):>4}  {n:>6}  {wins/n*100:5.1f}%  {top3/n*100:5.1f}%")

    # ── 枠順別 複勝率（枠バイアス）──
    p("\n■ 枠順別 複勝率")
    p("  枠   頭数   複勝率")
    for waku, n, top3 in c.execute("""
        SELECT waku, COUNT(*), SUM(CASE WHEN chakujun BETWEEN 1 AND 3 THEN 1 ELSE 0 END)
        FROM results WHERE chakujun>=1 AND waku BETWEEN 1 AND 8 GROUP BY waku ORDER BY waku"""):
        p(f"  {waku}  {n:>5}  {top3/n*100:5.1f}%")

    # ── 騎手別 成績（騎乗数上位）──
    p("\n■ 騎手別成績（騎乗数上位15）")
    p("  騎手          騎乗  勝率   複勝率")
    for jk, n, wins, top3 in c.execute("""
        SELECT jockey_name, COUNT(*), SUM(CASE WHEN chakujun=1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN chakujun BETWEEN 1 AND 3 THEN 1 ELSE 0 END)
        FROM results WHERE chakujun>=1 AND jockey_name!=''
        GROUP BY jockey_name HAVING COUNT(*)>=10 ORDER BY COUNT(*) DESC LIMIT 15"""):
        p(f"  {jk:<12} {n:>4}  {wins/n*100:5.1f}%  {top3/n*100:5.1f}%")

    open(OUT, 'w', encoding='utf-8').write('\n'.join(L))
    con.close()
    print("レポート出力:", OUT)

if __name__ == '__main__':
    main()
