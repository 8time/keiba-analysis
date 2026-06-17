# -*- coding: utf-8 -*-
"""
PCI乖離は消去フィルターに使えるか? の検証。
仮説: 各馬の事前平均PCIが「フィールド平均PCI」「想定RPCI」から大きく乖離する馬は
      想定ペースに不適合で3着内に来にくい → 消去候補。

方法: jravan.db results+races。各馬の今走PCIを算出→ketto_num/日付順に
      過去走(直近5走)の平均PCI=事前AvgPCIを作成(hindsight漏れ防止: 今走は含めない)。
      レース毎にフィールド平均PCIと想定RPCI(逃げ寄り=最小事前PCI側の代理)を算出。
      乖離量と複勝率(chakujun<=3)の関係を見る。必ず人気補正残差で priced-in を確認。
"""
import sqlite3, sys
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

DB = 'data/jravan.db'
YEARS = (2021, 2025)


def parse_time(s):
    """jravan time '1369' -> 96.9秒。'1分36秒9'。失敗時 NaN。"""
    try:
        s = str(s).strip()
        if not s or not s.isdigit():
            return np.nan
        tenths = int(s[-1]) / 10.0
        secs = int(s[-3:-1])
        mins = int(s[:-3]) if len(s) > 3 else 0
        v = mins * 60 + secs + tenths
        return v if v > 0 else np.nan
    except Exception:
        return np.nan


def calc_pci(t, a, d):
    """走破秒, 上がり3F秒, 距離m -> PCI。"""
    try:
        if not (a > 0 and d > 600):
            return np.nan
        fb = (d / 200.0) - 3.0
        if fb <= 0:
            return np.nan
        pci = (t - a) / fb * 3.0 / a * 100.0 - 50.0
        if 20.0 <= pci <= 100.0:
            return pci
        return np.nan
    except Exception:
        return np.nan


def main():
    con = sqlite3.connect(DB)
    q = f"""
        SELECT r.race_key, r.year, r.monthday, r.ketto_num, r.chakujun,
               r.win_odds, r.ninki, r.ato3f, r.time, ra.kyori, ra.surface
        FROM results r JOIN races ra ON r.race_key = ra.race_key
        WHERE r.year BETWEEN {YEARS[0]} AND {YEARS[1]}
          AND r.chakujun IS NOT NULL AND r.chakujun > 0
          AND r.ato3f IS NOT NULL AND r.ato3f > 0
          AND r.time IS NOT NULL AND ra.kyori IS NOT NULL
          AND r.ketto_num IS NOT NULL AND r.ninki IS NOT NULL AND r.ninki > 0
    """
    df = pd.read_sql(q, con)
    con.close()
    print(f"raw rows: {len(df):,}")

    df['t_sec'] = df['time'].map(parse_time)
    df['a_sec'] = pd.to_numeric(df['ato3f'], errors='coerce') / 10.0
    df['kyori'] = pd.to_numeric(df['kyori'], errors='coerce')
    df['pci'] = df.apply(lambda r: calc_pci(r['t_sec'], r['a_sec'], r['kyori']), axis=1)
    df['date'] = df['year'].astype(str) + df['monthday'].astype(str).str.zfill(4)
    df = df.dropna(subset=['pci'])
    print(f"with valid PCI: {len(df):,}")

    # 事前AvgPCI: 馬ごとに日付順、直近5走の平均(今走は除く=shift)
    df = df.sort_values(['ketto_num', 'date'])
    g = df.groupby('ketto_num')['pci']
    df['pre_avg_pci'] = (g.shift(1).groupby(df['ketto_num'])
                          .rolling(5, min_periods=1).mean()
                          .reset_index(level=0, drop=True))
    df['pre_runs'] = (g.shift(1).groupby(df['ketto_num'])
                       .rolling(5, min_periods=1).count()
                       .reset_index(level=0, drop=True))

    # 過去走2走以上ある馬に限定(事前PCIが安定)
    bt = df[df['pre_runs'] >= 2].copy()
    print(f"horses w/ >=2 past PCI runs: {len(bt):,}")

    # レース毎 フィールド平均PCI と 想定RPCI(逃げ寄り=事前PCI下位の代理)
    grp = bt.groupby('race_key')['pre_avg_pci']
    bt['field_avg_pci'] = grp.transform('mean')
    # 想定RPCI: 逃げ馬=前傾(低PCI)になりやすい → フィールドの下位25%平均を簡易RPCIとする
    bt['rpci'] = grp.transform(lambda s: s.quantile(0.25))

    bt['dev_field'] = (bt['pre_avg_pci'] - bt['field_avg_pci']).abs()
    bt['dev_rpci'] = (bt['pre_avg_pci'] - bt['rpci']).abs()
    bt['fuku'] = (bt['chakujun'] <= 3).astype(int)

    print(f"\nfinal n = {len(bt):,}  全体複勝率 = {bt['fuku'].mean()*100:.2f}%")

    # 人気別ベース複勝率 (残差算出用)
    base = bt.groupby('ninki')['fuku'].mean()

    def residual(sub):
        exp = sub['ninki'].map(base)
        return (sub['fuku'].mean() - exp.mean()) * 100  # pp

    def report(col, label, edges):
        print(f"\n=== {label} ===")
        bt['_bin'] = pd.cut(bt[col], bins=edges, include_lowest=True)
        for b, sub in bt.groupby('_bin', observed=True):
            if len(sub) < 200:
                continue
            print(f"  {str(b):>18}  n={len(sub):>7,}  "
                  f"複勝率={sub['fuku'].mean()*100:5.2f}%  "
                  f"人気補正残差={residual(sub):+5.2f}pp")

    report('dev_field', '|事前AvgPCI − フィールド平均PCI| の乖離量', [0, 1, 2, 3, 4, 6, 100])
    report('dev_rpci', '|事前AvgPCI − 想定RPCI| の乖離量', [0, 1, 2, 3, 5, 8, 100])

    # 致命的ペース不一致(コード is_pci_fatal 相当)の検証:
    #  前傾戦(rpci<=49.5)で瞬発型(pre>rpci+1.5) / 後傾戦(rpci>=56)で前傾型(pre<rpci-1.5)
    fatal = (((bt['rpci'] <= 49.5) & (bt['pre_avg_pci'] > bt['rpci'] + 1.5)) |
             ((bt['rpci'] >= 56.0) & (bt['pre_avg_pci'] < bt['rpci'] - 1.5)))
    print(f"\n=== 致命的ペース不一致フラグ(is_pci_fatal相当) ===")
    for name, mask in [('該当(fatal)', fatal), ('非該当', ~fatal)]:
        sub = bt[mask]
        if len(sub):
            print(f"  {name:>10}  n={len(sub):>7,}  "
                  f"複勝率={sub['fuku'].mean()*100:5.2f}%  残差={residual(sub):+5.2f}pp")

    # 人気薄限定(>=6番人気)で乖離大が効くか(穴消去/穴妙味の切り分け)
    print(f"\n=== 人気薄(6番人気以下)× フィールド乖離 ===")
    pop = bt[bt['ninki'] >= 6]
    for lo, hi in [(0, 2), (2, 4), (4, 100)]:
        sub = pop[(pop['dev_field'] >= lo) & (pop['dev_field'] < hi)]
        if len(sub) >= 200:
            print(f"  乖離[{lo},{hi})  n={len(sub):>7,}  "
                  f"複勝率={sub['fuku'].mean()*100:5.2f}%  残差={residual(sub):+5.2f}pp")


if __name__ == '__main__':
    main()
