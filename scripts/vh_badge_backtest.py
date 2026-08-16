# -*- coding: utf-8 -*-
"""穴馬ハンター候補の中でバッジ数(検証済みシグナル数)が選別に使えるか検証。

問い: VH精鋭/広域網の中でバッジが多い馬を選ぶと、VHスコア1位をそのまま選ぶより当たるか？
バッジ = 🔵補正T上位/🔥末脚top3/⚡33ラップ/👑騎手top3/🧬血統top3/💰血統回収/🏠厩舎
(⭐黄金ライン/🟢道悪軸はCSV未収録で除外=7種)

使用データ: data/export/horse_races.csv (leak-free)
分割: train ≤ 2024 / holdout 2025-2026
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import numpy as np

df = pd.read_csv('data/export/horse_races.csv')
print(f"全体: {len(df):,} 頭 / {df['race_key'].nunique():,} R")

# --- 穴馬のみ(6番人気以下) ---
ana = df[df['ninki'] >= 6].copy()
print(f"穴馬(6人気+): {len(ana):,} 頭 / {ana['race_key'].nunique():,} R")

# --- バッジ計算 ---
# 1. 🔵補正T上位: h7_rank <= 3
ana['b_time'] = (ana['h7_rank'] <= 3).astype(int)

# 2. 🔥末脚top3: レース内spurt_idx上位3
ana['_sp_rank'] = ana.groupby('race_key')['spurt_idx'].rank(ascending=False, method='min')
ana['b_spurt'] = (ana['_sp_rank'] <= 3).astype(int)

# 3. ⚡33ラップ適合
ana['b_lap33'] = ana['lap_fit_bin'].fillna(0).astype(int)

# 4. 👑騎手top3: レース内jk_race_pct上位3
ana['_jk_rank'] = ana.groupby('race_key')['jk_race_pct'].rank(ascending=False, method='min')
ana['b_jockey'] = (ana['_jk_rank'] <= 3).astype(int)

# 5. 🧬血統top3: レース内blood_race_pct上位3
ana['_bl_rank'] = ana.groupby('race_key')['blood_race_pct'].rank(ascending=False, method='min')
ana['b_blood'] = (ana['_bl_rank'] <= 3).astype(int)

# 6. 💰血統回収100%+
ana['b_sire_roi'] = (ana['sire_winroi'] >= 100).astype(int)

# 7. 🏠厩舎当コース
ana['b_trainer'] = (ana['trainer_jyo_t3'] >= 0.18).astype(int)

badge_cols = ['b_time', 'b_spurt', 'b_lap33', 'b_jockey', 'b_blood', 'b_sire_roi', 'b_trainer']
ana['badge_n'] = ana[badge_cols].sum(axis=1)

# --- 年カラム ---
ana['year'] = ana['day'].astype(str).str[:4].astype(int)

# =============================================================
# テスト1: バッジ数 vs 3着内率 (全穴馬)
# =============================================================
print("\n" + "=" * 60)
print("テスト1: バッジ数 vs 3着内率 (全穴馬・6人気以下)")
print("=" * 60)
for period, mask in [("train(≤2024)", ana['year'] <= 2024),
                     ("holdout(2025+)", ana['year'] >= 2025)]:
    sub = ana[mask]
    print(f"\n--- {period} ({len(sub):,}頭) ---")
    for bn in sorted(sub['badge_n'].unique()):
        g = sub[sub['badge_n'] == bn]
        t3 = g['top3'].mean() * 100
        n = len(g)
        print(f"  badge={int(bn)}: top3={t3:5.1f}%  n={n:>6,}")

# =============================================================
# テスト2: VH精鋭内でバッジ数が選別に使えるか
# =============================================================
# VH精鋭 ≈ vh2_score上位(recall0.5相当)。CSVのvh2_scoreでレース内順位を取り
# 穴馬内で上位N頭を精鋭とする。
print("\n" + "=" * 60)
print("テスト2: VH精鋭(穴馬内vh2_score上位)でバッジ数が選別に使えるか")
print("=" * 60)

# 穴馬内でvh2_scoreの順位
ana['_vh_rank'] = ana.groupby('race_key')['vh2_score'].rank(ascending=False, method='first')

# 精鋭 = 穴馬内vh2_score上位3頭(実運用でも精鋭は概ね2-4頭)
ELITE_K = 3
elite = ana[ana['_vh_rank'] <= ELITE_K].copy()
print(f"精鋭(穴馬内VH上位{ELITE_K}): {len(elite):,}頭")

for period, mask in [("train(≤2024)", elite['year'] <= 2024),
                     ("holdout(2025+)", elite['year'] >= 2025)]:
    sub = elite[mask]
    print(f"\n--- {period} ({len(sub):,}頭) ---")
    for bn in sorted(sub['badge_n'].unique()):
        g = sub[sub['badge_n'] == bn]
        t3 = g['top3'].mean() * 100
        n = len(g)
        print(f"  badge={int(bn)}: top3={t3:5.1f}%  n={n:>6,}")

# =============================================================
# テスト3: レースごとに「バッジ最多を選ぶ」vs「VH1位を選ぶ」
# =============================================================
print("\n" + "=" * 60)
print("テスト3: レースごとの1頭選び比較")
print("=" * 60)

results = []
for rk, grp in elite.groupby('race_key'):
    if len(grp) < 2:
        continue
    yr = grp['year'].iloc[0]
    # VH1位 = vh2_score最大
    vh1 = grp.sort_values('vh2_score', ascending=False).iloc[0]
    # バッジ最多(同数ならvh2_score上位)
    badge_max = grp.sort_values(['badge_n', 'vh2_score'], ascending=[False, False]).iloc[0]
    results.append({
        'race_key': rk, 'year': yr,
        'vh1_top3': int(vh1['top3']),
        'badge_top3': int(badge_max['top3']),
        'vh1_badge_n': int(vh1['badge_n']),
        'badge_max_n': int(badge_max['badge_n']),
        'same_horse': int(vh1['umaban'] == badge_max['umaban']),
    })

rdf = pd.DataFrame(results)
print(f"比較レース数: {len(rdf):,}")
print(f"同一馬率: {rdf['same_horse'].mean()*100:.1f}%")

for period, mask in [("train(≤2024)", rdf['year'] <= 2024),
                     ("holdout(2025+)", rdf['year'] >= 2025)]:
    sub = rdf[mask]
    diff_sub = sub[sub['same_horse'] == 0]
    print(f"\n--- {period} ({len(sub):,} R / 別馬{len(diff_sub):,} R) ---")
    print(f"  VH1位選び:    top3={sub['vh1_top3'].mean()*100:.1f}%")
    print(f"  バッジ最多選び: top3={sub['badge_top3'].mean()*100:.1f}%")
    if len(diff_sub) > 0:
        print(f"  [別馬のみ] VH1位: {diff_sub['vh1_top3'].mean()*100:.1f}%  "
              f"バッジ最多: {diff_sub['badge_top3'].mean()*100:.1f}%")

# =============================================================
# テスト4: バッジ0の精鋭 vs バッジ1+の精鋭
# =============================================================
print("\n" + "=" * 60)
print("テスト4: バッジ0 vs 1+ vs 2+ の精鋭")
print("=" * 60)
for period, mask in [("train(≤2024)", elite['year'] <= 2024),
                     ("holdout(2025+)", elite['year'] >= 2025)]:
    sub = elite[mask]
    for label, cond in [("badge=0", sub['badge_n'] == 0),
                        ("badge≥1", sub['badge_n'] >= 1),
                        ("badge≥2", sub['badge_n'] >= 2),
                        ("badge≥3", sub['badge_n'] >= 3)]:
        g = sub[cond]
        if len(g) == 0:
            continue
        t3 = g['top3'].mean() * 100
        print(f"  {period} {label}: top3={t3:5.1f}% n={len(g):>5,}")

# =============================================================
# テスト5: 個別バッジの寄与(精鋭内)
# =============================================================
print("\n" + "=" * 60)
print("テスト5: 個別バッジの寄与(精鋭内)")
print("=" * 60)
badge_labels = ['🔵補正T', '🔥末脚', '⚡33ラップ', '👑騎手', '🧬血統', '💰血統回収', '🏠厩舎']
for period, mask in [("train(≤2024)", elite['year'] <= 2024),
                     ("holdout(2025+)", elite['year'] >= 2025)]:
    sub = elite[mask]
    base = sub['top3'].mean() * 100
    print(f"\n--- {period} (base top3={base:.1f}%) ---")
    for col, lbl in zip(badge_cols, badge_labels):
        on = sub[sub[col] == 1]
        off = sub[sub[col] == 0]
        if len(on) < 10:
            continue
        t3_on = on['top3'].mean() * 100
        t3_off = off['top3'].mean() * 100
        diff = t3_on - t3_off
        z = (t3_on/100 - t3_off/100) / max(
            np.sqrt(base/100*(1-base/100)*(1/len(on)+1/len(off))), 1e-9)
        print(f"  {lbl}: ON={t3_on:5.1f}%({len(on):>5,}) OFF={t3_off:5.1f}%({len(off):>5,}) "
              f"差={diff:+5.1f}pp z={z:+.2f}")

print("\n完了")
