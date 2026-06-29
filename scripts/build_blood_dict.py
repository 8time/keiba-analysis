# -*- coding: utf-8 -*-
"""
③ 血統辞書ビルダー（種牡馬 × 条件 × 回収率/複勝率）

40年データを「特徴量の辞書」として使う中核（前回議論の結論）。
horses(血統) × results(成績) × payouts(複勝) を JOIN し、
種牡馬(sire)・母父(bms) ごとに 芝/ダート×距離帯 の複勝率・単勝回収率を集計して
blood_dict.sqlite（恒久資産）に書き出す。解約後もこの辞書だけで血統適性が引ける。

前提: jravan.db に horses テーブル（UM取込済み）が必要。
  ※UMはDIFFデータ種別。RACE全履歴取込の完走後に
    `python scripts/jvlink_ingest.py --dataspec DIFF --from 19860101000000 --option 4`
    （32bit）で取得 → horses が埋まる。

実行: py -3.14 scripts/build_blood_dict.py
出力: data/blood_dict.db （sire_stats / bms_stats）
"""
import sys, io, os, re, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'blood_dict.db')

JRA = "('01','02','03','04','05','06','07','08','09','10')"

def normalize_parent_name(name):
    """名前バリアント統合: 英語名+国コード除去、ローマ数字→全角"""
    if not name:
        return name
    s = name.strip()
    s = re.sub(r'\s*[\(（][^)）]{1,3}[\)）]\s*$', '', s)
    if re.search(r'[぀-ヿ一-鿿]', s):
        last_jp = -1
        for i, c in enumerate(s):
            if '぀' <= c <= 'ヿ' or '一' <= c <= '鿿' or c in '０１２３４５６７８９':
                last_jp = i
        if last_jp >= 0:
            rest = s[last_jp+1:]
            s = s[:last_jp+1]
            m = re.match(r'^(IV|III|II)', rest)
            if m:
                s += {'IV':'４','III':'３','II':'２'}[m.group(1)]
    return s

def dist_band(kyori):
    if kyori is None: return '不明'
    if kyori <= 1300: return '短距離'
    if kyori <= 1899: return 'マイル'
    if kyori <= 2200: return '中距離'
    return '長距離'

def build(parent_col, out_table, con, out):
    """parent_col = 'sire' or 'bms'。条件別(芝ダ×距離帯)に集計。名前正規化で統合。"""
    out.execute(f"DROP TABLE IF EXISTS {out_table}")
    out.execute(f"""CREATE TABLE {out_table} (
        parent TEXT, surface TEXT, dist_band TEXT,
        runs INTEGER, top3 INTEGER, wins INTEGER,
        place_rate REAL, win_rate REAL, win_roi REAL,
        PRIMARY KEY (parent, surface, dist_band))""")
    q = f"""
    SELECT h.{parent_col} AS parent, ra.surface AS surface, ra.kyori AS kyori,
      r.chakujun AS chakujun,
      CASE WHEN pw.payout>0 THEN pw.payout ELSE 0 END AS win_ret
    FROM results r
    JOIN races ra ON ra.race_key=r.race_key
    JOIN horses h ON h.ketto_num=r.ketto_num
    LEFT JOIN payouts pw ON pw.race_key=r.race_key AND pw.bet_type='単勝' AND CAST(pw.combo AS INTEGER)=r.umaban
    WHERE r.chakujun>=1 AND ra.jyo IN {JRA} AND h.{parent_col}!='' AND ra.surface IN ('芝','ダート')
    """
    agg = {}
    for row in con.execute(q):
        norm = normalize_parent_name(row['parent'])
        key = (norm, row['surface'], dist_band(row['kyori']))
        a = agg.setdefault(key, [0, 0, 0, 0])  # runs, top3, wins, win_ret
        a[0] += 1
        if row['chakujun'] <= 3: a[1] += 1
        if row['chakujun'] == 1: a[2] += 1
        a[3] += row['win_ret']
    rows = 0
    for (parent, surf, band), (runs, top3, wins, wret) in agg.items():
        if runs < 30:  # サンプル不足は捨てる（信頼性確保）
            continue
        out.execute(f"INSERT OR REPLACE INTO {out_table} VALUES (?,?,?,?,?,?,?,?,?)",
                    (parent, surf, band, runs, top3, wins,
                     round(top3/runs*100, 1), round(wins/runs*100, 1), round(wret/(runs*100)*100, 1)))
        rows += 1
    out.commit()
    return rows

def main():
    if not os.path.exists(SRC):
        print("jravan.db が無い"); return
    con = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True, timeout=120)
    con.row_factory = sqlite3.Row
    nh = con.execute("SELECT COUNT(*) FROM horses").fetchone()[0] if \
        con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='horses'").fetchone() else 0
    print(f"horses テーブル: {nh:,} 件")
    if nh == 0:
        print("⚠ horses が空。UM(DIFF)未取込。RACE完走後にDIFFを取得してください:")
        print("   python scripts/jvlink_ingest.py --dataspec DIFF --from 19860101000000 --option 4")
        con.close(); return

    out = sqlite3.connect(OUT)
    ns = build('sire', 'sire_stats', con, out)
    nb = build('bms', 'bms_stats', con, out)
    print(f"種牡馬辞書: {ns} 行 / 母父辞書: {nb} 行 → {OUT}")

    # サンプル表示: 芝中距離の種牡馬 複勝率トップ
    print("\n■ 芝・中距離 種牡馬 複勝率トップ10（30走以上）")
    for parent, runs, place_rate, win_roi in out.execute("""SELECT parent,runs,place_rate,win_roi FROM sire_stats
        WHERE surface='芝' AND dist_band='中距離' ORDER BY place_rate DESC LIMIT 10"""):
        print(f"  {parent:<16} {runs:>5}走 複勝率{place_rate:5.1f}% 単回収{win_roi:6.1f}%")
    con.close(); out.close()

if __name__ == '__main__':
    main()
