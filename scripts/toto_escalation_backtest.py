# -*- coding: utf-8 -*-
"""3連複10点×追い上げ(マーチンゲール風)の現実検証。
ユーザー資料: 36倍固定toto風の10段エスカレーション(1点stake=100,100,100,200,200,300,500,600,900,1200/
累積最大42,000円・10連敗で全損)。これを3連複10点(1番人気軸5頭流し=相手2-6番人気のC(5,2)=10点)に適用。
『配当36倍(=払戻3600以上)で当たればプラス、それ以下/不的中は負け』。

検証する真実: ①≥36倍が10点内に来る実確率 ②連敗分布(10連敗=破産が起きるか) ③net P/L
④レースサーチ(value_scanner.trio_lean)で②穴妙味/中立レースに絞ると破産が減るか。
※追い上げはEVを変えない。本BTは『窓を超える連敗で全損する』を数字で示すのが目的。"""
import os
import sys
import sqlite3
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import value_scanner as vs

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
YEARS = ('2021', '2022', '2023', '2024', '2025')

# 10段: 1点stake (×10点=購入額)
STAKE = [100, 100, 100, 200, 200, 300, 500, 600, 900, 1200]
BUY = [s * 10 for s in STAKE]
CUM = []
_c = 0
for b in BUY:
    _c += b; CUM.append(_c)   # [1000,2000,3000,5000,7000,10000,15000,21000,30000,42000]
WIN_THRESH = 3600  # 36倍(払戻/100円)


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
    yf = " OR ".join(["ra.year=?"] * len(YEARS))
    rrows = con.execute(
        f"""SELECT ra.race_id, ra.race_key, ra.shusso_tosu, ra.juryo, ra.kyori,
                   ra.surface, ra.baba_shiba, ra.baba_dirt, r.umaban, r.ninki, r.win_odds
            FROM races ra JOIN results r ON r.race_key=ra.race_key
            WHERE ({yf}) AND ra.shubetsu IN ('11','12','13','14')
              AND ra.shusso_tosu>=8 AND r.chakujun>0""", YEARS).fetchall()
    prows = con.execute(
        f"""SELECT p.race_id, p.combo, p.payout FROM payouts p
            WHERE p.bet_type='3連複' AND (p.race_id LIKE '2021%' OR p.race_id LIKE '2022%'
              OR p.race_id LIKE '2023%' OR p.race_id LIKE '2024%' OR p.race_id LIKE '2025%')""").fetchall()
    con.close()

    pay = {}
    for rid, combo, p in prows:
        try:
            tri = frozenset(int(combo[i:i+2]) for i in range(0, 6, 2))
            pay[rid] = (tri, p)
        except Exception:
            continue

    races = {}
    for (rid, rk, tosu, juryo, kyori, surf, bsh, bdt, um, ninki, wo) in rrows:
        d = races.setdefault(rid, {'tosu': tosu, 'juryo': juryo or '', 'kyori': kyori or 0,
                                   'baba': str((bsh if (surf or '') == '芝' else bdt) or ''),
                                   'horses': []})
        d['horses'].append({'um': um, 'ninki': ninki or 99, 'wo': wo or 0})

    _BABA = {'3': '重', '4': '不良'}
    recs = []  # (race_id, hit_bool, payout, ge36_bool, lean)
    for rid in sorted(races):
        d = races[rid]
        if rid not in pay:
            continue
        win_tri, pp = pay[rid]
        by_ninki = {h['ninki']: h['um'] for h in d['horses']}
        if 1 not in by_ninki:
            continue
        fav = by_ninki[1]
        partners = [by_ninki[n] for n in (2, 3, 4, 5, 6) if n in by_ninki]
        if len(partners) < 5:
            continue
        # 1番人気軸5頭流し(相手2-6番人気)の10点 = {fav}+2 of partners
        hit = (fav in win_tri) and ((win_tri - {fav}) <= set(partners))
        odds = [h['wo'] for h in d['horses'] if h['wo'] and h['wo'] > 0]
        lean = vs.trio_lean(meta={'is_handicap': d['juryo'] == '1'}, n_horses=d['tosu'],
                            fav_odds=min(odds) if odds else None, dist=d['kyori'],
                            baba=_BABA.get(d['baba']), odds_list=odds)['lean']
        recs.append((rid, hit, pp, pp >= WIN_THRESH, lean))

    # ── 基礎統計 ──
    n = len(recs)
    n_hit = sum(1 for r in recs if r[1])
    n_ge36 = sum(1 for r in recs if r[1] and r[3])   # 当たって≥36倍
    print(f"対象レース n={n:,} (2021-25 平地 tosu>=8・3連複払戻あり)")
    print(f"1番人気軸5頭流し(2-6番)の的中率: {n_hit/n*100:.1f}%  "
          f"うち≥36倍(prof条件)的中率: {n_ge36/n*100:.2f}%")
    print(f"  → 追い上げ表は『≤10回で≥36倍が1回来る』前提。実際の≥36倍率={n_ge36/n*100:.2f}%"
          f"＝平均 {n/max(n_ge36,1):.0f}レースに1回\n")

    def simulate(subset, label):
        """subset(時系列) に追い上げを適用。'当たり'=的中かつ≥36倍。"""
        step = 0
        bankroll = 0          # 累積損益
        bankrupt = 0
        wins = 0
        miss_streak = 0
        max_streak = 0
        worst = 0
        for (rid, hit, pp, ge36, lean) in subset:
            bankroll -= BUY[step]               # この回の購入額
            if hit and ge36:
                bankroll += pp * (STAKE[step] // 100)   # 当たり点の払戻
                wins += 1
                step = 0
                miss_streak = 0
            else:
                miss_streak += 1
                max_streak = max(max_streak, miss_streak)
                step += 1
                if step >= len(STAKE):          # 10連敗=破産(窓を使い切る)
                    bankrupt += 1
                    step = 0
                    miss_streak = 0
            worst = min(worst, bankroll)
        bet_races = len(subset)
        print(f"[{label}] 賭けレース={bet_races:,}  ≥36倍的中={wins}  破産(10連敗)={bankrupt}回  "
              f"最大連敗={max_streak}  最終損益={bankroll:+,}円  最大ドローダウン={worst:+,}円")

    print("=== 追い上げシミュレーション(時系列・全期間連続) ===")
    simulate(recs, "S1 全レース(本命5頭流し)")
    simulate([r for r in recs if r[4] != '本線向き'], "S2 ②/中立のみ(堅レース回避)")
    simulate([r for r in recs if r[4] == '②穴妙味向き'], "S3 ②穴妙味向きのみ")
    print("\n※追い上げはEVを変えない。破産回数>0=『窓を超える連敗が現実に起きる』証拠。")
    print("  S2/S3で破産が減り損益が改善するなら『レースサーチで荒れに絞る』効果あり。")


if __name__ == '__main__':
    main()
