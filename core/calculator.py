import logging
logger = logging.getLogger(__name__)

import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta

# Standard Times (Approximations) based on netkeiba usage
STANDARD_TIMES = {
    '芝': {
        1000: 57.5, 1150: 67.0, 1200: 68.3, 1300: 76.5,
        1400: 81.0, 1500: 87.5, 1600: 93.5, 1650: 97.0,
        1700: 100.5, 1800: 107.5, 1900: 114.0, 2000: 120.0,
        2100: 126.5, 2200: 132.5, 2400: 145.5,
        2500: 152.0, 3000: 184.0, 3200: 198.0, 3400: 215.0
    },
    'ダ': {
        1000: 59.5, 1150: 69.5, 1200: 71.8, 1300: 79.0,
        1400: 84.8, 1500: 91.5, 1600: 98.5,
        1700: 105.5, 1800: 112.5, 1900: 119.0, 2000: 126.0,
        2100: 133.0, 2400: 154.0
    }
}
DEFAULT_STD = STANDARD_TIMES['芝']


def _get_std_time(surf, dist):
    """Return standard time for given surface+distance, interpolating if exact key missing."""
    std_times = STANDARD_TIMES.get(surf, STANDARD_TIMES['芝'])
    if dist in std_times:
        return std_times[dist]
    keys = sorted(std_times.keys())
    if dist <= keys[0]:
        # Extrapolate below minimum: pace-based
        return std_times[keys[0]] * dist / keys[0]
    if dist >= keys[-1]:
        return std_times[keys[-1]] * dist / keys[-1]
    # Linear interpolation between surrounding keys
    for i in range(len(keys) - 1):
        if keys[i] < dist < keys[i + 1]:
            t0, t1 = std_times[keys[i]], std_times[keys[i + 1]]
            d0, d1 = keys[i], keys[i + 1]
            return t0 + (t1 - t0) * (dist - d0) / (d1 - d0)
    return None

def calculate_solid_race(df):
    """Placeholder for Solid Race (Low Difficulty) logic."""
    return df

def evaluate_race_chaos_v2(df):
    """
    静的データ（スコア、人気、脚質）を用いて、レースの波乱度（S〜C）を多角的に判定する。
    
    評価基準:
    1. 過剰人気馬（1〜2番人気で指数が低い）の有無
    2. 展開崩壊（ハイペース）の危険性（先行馬の密集）
    3. 有力な伏兵（人気薄だが適性が高い）の数
    """
    # 判定用定数（閾値）
    CONFIG = {
        'FRONT_RUNNER_LIMIT': 3.5,    # 先行とみなす平均通過順位
        'PACE_COLLAPSE_COUNT': 3,     # 展開崩壊を引き起こす先行馬の数
        'OVERRATED_SCORE_MAX': 75.0,  # 人気馬が「実力不足」とみなされるスコア
        'DARK_HORSE_POP_MIN': 6,      # 伏兵とみなされる人気順位
        'DARK_HORSE_SCORE_MIN': 80.0, # 伏兵が「有力」とみなされるスコア
        'HIGH_AGARI_LIMIT': 35.5      # 上がりが速いとみなされる基準
    }

    if df.empty:
        return {'rank': 'B', 'reason': 'データ不足のため判定保留'}
    
    # 人気順データのチェック (NaNや欠損のハンドリング)
    if 'Popularity' not in df.columns or df['Popularity'].isna().all():
        return {'rank': 'B', 'reason': '人気順データが取得できていないため、標準的な波乱度として判定'}

    score_col = 'BattleScore' 
    reasons = []
    chaos_points = 0

    # 1. 過剰人気馬のチェック
    favorites = df[df['Popularity'] <= 2]
    overrated = favorites[favorites[score_col] < CONFIG['OVERRATED_SCORE_MAX']]
    if not overrated.empty:
        reasons.append("実力（指数）が伴わない過剰人気馬が存在します。")
        chaos_points += 2

    # 2. 展開崩壊（ハイペース）のチェック
    if 'AvgPosition' in df.columns:
        front_runners = df[df['AvgPosition'] <= CONFIG['FRONT_RUNNER_LIMIT']]
        if len(front_runners) >= CONFIG['PACE_COLLAPSE_COUNT']:
            reasons.append("先行馬が密集しており、激しいハナ争いによる展開崩壊（差し有利）の危険があります。")
            chaos_points += 2
        elif len(front_runners) <= 1:
             reasons.append("明確な逃げ馬が不在で、スローペースから前の馬が残る可能性があります。")
             # スローは波乱度は下がりやすい

    # 3. 有力な伏兵馬のチェック (適性(Y) または 上がり3F が極めて高い)
    # --- NEW: マクリ馬（捲り）のチェック ---
    makuri_horses = []
    for _, row in df.iterrows():
        past = row.get('PastRuns', [])
        for run in past[:5]:
            p_str = str(run.get('Passing', ''))
            p_list = [int(t) for t in re.split(r'[,\-()]+', p_str) if t.strip().isdigit()]
            rank = run.get('Rank', 99)
            if p_list and rank != 99:
                if max(p_list) - rank >= 7:
                    makuri_horses.append(row['Name'])
                    break
    
    if len(makuri_horses) >= 3:
        reasons.append(f"マクリ（捲り）癖のある馬が {len(makuri_horses)} 頭搭載されており、中盤からの激しい進出で展開が乱れる（波乱）可能性があります。")
        chaos_points += 2.0

    dark_horse_pop_min = CONFIG['DARK_HORSE_POP_MIN']
    dark_horse_df = df[df['Popularity'] >= dark_horse_pop_min]
    
    found_dark_horse = False
    if not dark_horse_df.empty:
        # 適性(Y) または 上がり3F をチェック
        high_suit = pd.Series([False] * len(dark_horse_df), index=dark_horse_df.index)
        if 'Suitability (Y)' in df.columns:
            high_suit = dark_horse_df['Suitability (Y)'] >= CONFIG['DARK_HORSE_SCORE_MIN']
        elif score_col in df.columns:
            high_suit = dark_horse_df[score_col] >= CONFIG['DARK_HORSE_SCORE_MIN']
            
        high_agari = pd.Series([False] * len(dark_horse_df), index=dark_horse_df.index)
        if 'AvgAgari' in df.columns:
            high_agari = dark_horse_df['AvgAgari'] <= CONFIG['HIGH_AGARI_LIMIT']
            
        target_dark_horses = dark_horse_df[high_suit | high_agari]
        if not target_dark_horses.empty:
            found_dark_horse = True
            if len(target_dark_horses) >= 3:
                reasons.append("適性または上がり性能が極めて高い穴馬が多数潜んでおり、大波乱の予感があります。")
                chaos_points += 3
            else:
                reasons.append("一発の可能性を秘めた有力な伏兵馬（人気薄・高適性）が存在します。")
                chaos_points += 1.5

    # 最終ランク判定
    if chaos_points >= 5: rank = 'S'
    elif chaos_points >= 3: rank = 'A'
    elif chaos_points >= 1: rank = 'B'
    else: rank = 'C'

    if not reasons:
        reasons.append("上位勢の信頼度が高く、データ上は順当な決着が予想されます。")

    return {
        'rank': rank,
        'reason': " ".join(reasons)
    }

def evaluate_race_chaos_v3(df):
    """
    高度なオッズ分析を含む統合波乱度判定ロジック。
    
    追加の判定項目 (オッズの歪み):
    1. 大混戦アラート: 1番人気の単勝オッズ >= 3.5
    2. 激走フラグ: (単勝人気 - 複勝人気) >= 3 (複勝が異常に売れている)
    3. インサイダー警戒: 単勝 >= 10.0 かつ (単勝 / 複勝(下限)比率) >= 5.5
    """
    # 既存の展開・適性ベースの判定をベースにする
    base_res = evaluate_race_chaos_v2(df)
    rank = base_res['rank']
    reasons = [base_res['reason']]
    
    if df.empty or 'Odds' not in df.columns:
        return base_res

    chaos_points = 0
    if rank == 'S': chaos_points += 5
    elif rank == 'A': chaos_points += 3
    elif rank == 'B': chaos_points += 1

    # --- ADVANCED ODDS ANALYSIS ---
    # Convert to numeric safely
    df['Odds'] = pd.to_numeric(df['Odds'], errors='coerce').fillna(999.0)
    
    # 1. 1番人気の単勝オッズチェック
    min_odds = df['Odds'].min()
    if min_odds >= 3.5:
        reasons.append(f"【混戦アラート】1番人気のオッズが {min_odds}倍 と高く、能力が拮抗した激戦が予想されます。")
        chaos_points += 2

    # 2. 単複人気・オッズ乖離のチェック (馬単位)
    anomaly_count = 0
    for _, row in df.iterrows():
        try:
            name = row['Name']
            win_odds = float(row['Odds'])
            win_pop = int(row['Popularity']) if pd.notna(row['Popularity']) else 99
            
            # Place popularity check (if available in df)
            # if 'PlacePop' in df.columns: ...
            
            # Note: OddsAnalyzer logic can be unified here
            # For now, we look for 'Show Odds (Min)' if present
            show_min = float(row.get('Show Odds (Min)', 0.0))
            show_pop = int(row.get('PlacePopularity', win_pop)) # Proxy if not explicit
            
            # 激走フラグ: 単勝人気 - 複勝人気 >= 3
            if (win_pop - show_pop) >= 3:
                reasons.append(f"【激走フラグ】馬番 {row['Umaban']} ({name}) の複勝が異常に売れています (人気差 {win_pop - show_pop})。")
                anomaly_count += 1
                chaos_points += 1
            
            # インサイダー警戒: 単勝 >= 10.0 かつ 比率 >= 5.5
            if win_odds >= 10.0 and show_min > 0:
                ratio = win_odds / show_min
                if ratio >= 5.5:
                    reasons.append(f"【インサイダー警戒】馬番 {row['Umaban']} ({name}) の単複比率が {ratio:.1f}倍 と極端に乖離しています。")
                    anomaly_count += 1
                    chaos_points += 1.5
        except:
            continue

    # Final Rank Adjustment
    new_rank = rank
    if chaos_points >= 6: new_rank = 'S'
    elif chaos_points >= 4: new_rank = 'A'
    elif chaos_points >= 2: new_rank = 'B'
    else: new_rank = 'C'

    return {
        'rank': new_rank,
        'reason': " ".join(reasons),
        'chaos_points': chaos_points,
        'anomaly_count': anomaly_count
    }

def calculate_predicted_difficulty(df):
    """Legacy wrapper for evaluate_race_chaos_v2 rank."""
    res = evaluate_race_chaos_v2(df)
    return res['rank']

def calculate_rough_race(df):
    """Placeholder for Rough Race (High Difficulty) logic."""
    return df

def calculate_ogura_index(df):
    """
    Calculates the Flat Ogura Index (Absolute Capability) based on a Points System.
    Logic (from test_calculator.py):
    - Base Score = 100 - (Rank - 1) * 5 (Min 0)
    - GI/G1 Multiplier: 2.0
    - Recent Multiplier (<= 180 days or IsRecent flag): 1.2
    - Final Index = Average of last 10 races
    """
    if df.empty:
        for col in ['OguraIndex', 'BattleScore', 'Alert', 'SpeedIndex']:
             if col not in df.columns: df[col] = 0.0 if col != 'Alert' else ''
        return df
    
    # Initialize Check
    if 'OguraIndex' not in df.columns: df['OguraIndex'] = 0.0
    if 'SpeedIndex' not in df.columns: df['SpeedIndex'] = 0.0
    if 'Status' not in df.columns: df['Status'] = 'No Data'
    if 'Alert' not in df.columns: df['Alert'] = ''
    
    now = datetime.now()
    
    for i, row in df.iterrows():
        # Handle both PastRuns and Past_Runs (for testing)
        past = row.get('PastRuns') or row.get('Past_Runs') or []
        if not past: continue
            
        points_list = []
        
        # Process last 10 races
        for run in past[:10]:
            rank = run.get('Rank', 99)
            grade = str(run.get('Grade', 'OP')).upper()
            date_str = run.get('Date', '2000.01.01')
            
            # 1. Base Points
            base = max(0, 100 - (rank - 1) * 5)
            
            # 2. Multipliers
            g_mult = 2.0 if (grade == 'G1' or grade == 'GI') else 1.0
            
            # Recency
            r_mult = 1.0
            is_recent = run.get('IsRecent', False)
            
            if is_recent:
                r_mult = 1.2
            else:
                try:
                    # date_str format is usually "2024.02.11"
                    r_date = datetime.strptime(date_str, "%Y.%m.%d")
                    if (now - r_date).days <= 180:
                        r_mult = 1.2
                except:
                    pass
            
            points = base * g_mult * r_mult
            points_list.append(points)
            
        if points_list:
            avg_points = np.mean(points_list)
            df.at[i, 'OguraIndex'] = round(avg_points, 1)
            df.at[i, 'SpeedIndex'] = round(avg_points, 1)
            
    return df


def calculate_diy_index(df):
    """
    Calculates the DIY Speed Index based on past runs.
    Formula: DIY指数 = (基準タイム - 走破タイム) * 0.8 + 50
    """
    if df.empty:
        if 'DIY_Index' not in df.columns: df['DIY_Index'] = 0.0
        return df
    
    if 'DIY_Index' not in df.columns: df['DIY_Index'] = 0.0
    
    for i, row in df.iterrows():
        past = row.get('PastRuns', [])
        if not past:
            df.at[i, 'DIY_Index'] = 0.0
            continue
            
        index_vals = []
        for run in past[:10]:
            try:
                # 1. Get Time (seconds)
                time_sec = float(run.get('Time', 0))
                if time_sec <= 0:
                    time_str = str(run.get('TimeStr', ''))
                    if ':' in time_str:
                        parts = time_str.split(':')
                        time_sec = int(parts[0]) * 60 + float(parts[1])
                    elif time_str:
                        time_sec = float(time_str)

                if time_sec <= 0:
                    continue

                # 2. Get Distance & Surface
                dist = int(run.get('Distance', 0))
                if dist <= 0:
                    continue
                surf = '芝' if '芝' in str(run.get('Surface', '')) else 'ダ'

                # 3. Get Standard Time (with interpolation for unlisted distances)
                std_time = _get_std_time(surf, dist)
                if std_time is None or std_time <= 0:
                    continue

                # 4. DIY Index: deviation from standard pace, bias-corrected per distance
                # Scale factor: larger distances need smaller multiplier for numeric stability
                scale = 100.0 / dist * 12.0  # normalise so 1200m gives ~0.8 equivalent
                val = (std_time - time_sec) * scale + 50
                index_vals.append(val)
            except:
                continue
                
        if index_vals:
            df.at[i, 'DIY_Index'] = round(np.mean(index_vals), 1)
        else:
            df.at[i, 'DIY_Index'] = 0.0
            
    return df

def calculate_diy2_index(df):
    """
    DIY2: Agari Speed Index (Deviation based on Last 3F times).
    1. Average 'Agari' times from past runs (Last 5).
    2. Normalize across the field into T-Scores (Deviation Values).
    3. Lower Agari time (faster) = Higher Score.
    """
    if df.empty:
        if 'DIY2_Index' not in df.columns: df['DIY2_Index'] = 50.0
        return df

    if 'DIY2_Index' not in df.columns: df['DIY2_Index'] = 50.0
    
    horse_avg_agari = []
    
    for i, row in df.iterrows():
        past = row.get('PastRuns', [])
        valid_agari = []
        
        for run in past:
            try:
                # Agari 3F is stored as float in 'Agari'
                r_agari = float(run.get('Agari', 0))
                if 20.0 < r_agari < 60.0: # Sanity check for Agari 3F
                    valid_agari.append(r_agari)
            except:
                continue
        
        if valid_agari:
            avg_a = np.mean(valid_agari)
            horse_avg_agari.append(avg_a)
            df.at[i, '_tmp_avg_agari'] = avg_a
        else:
            df.at[i, '_tmp_avg_agari'] = np.nan

    # Calculate T-Score (Deviation)
    # Higher score = faster finish (lower agari time)
    valid_field_agari = [a for a in horse_avg_agari if not np.isnan(a)]

    if len(valid_field_agari) >= 2:
        field_mean = np.mean(valid_field_agari)
        field_std = np.std(valid_field_agari)
        if field_std < 0.1: field_std = 0.5  # Avoid division by near-zero

        for i, row in df.iterrows():
            a = df.at[i, '_tmp_avg_agari'] if '_tmp_avg_agari' in df.columns else np.nan
            if pd.notna(a):
                t_score = 50 + 10 * (field_mean - a) / field_std
                # Clamp to reasonable range
                df.at[i, 'DIY2_Index'] = round(max(10.0, min(90.0, t_score)), 1)
            else:
                df.at[i, 'DIY2_Index'] = 50.0
    elif len(valid_field_agari) == 1:
        # Only one horse has data: give it a slightly above-average score
        for i, row in df.iterrows():
            a = df.at[i, '_tmp_avg_agari'] if '_tmp_avg_agari' in df.columns else np.nan
            df.at[i, 'DIY2_Index'] = 55.0 if pd.notna(a) else 50.0
    else:
        df['DIY2_Index'] = 50.0

    if '_tmp_avg_agari' in df.columns:
        df = df.drop(columns=['_tmp_avg_agari'])
        
    return df

def calculate_n_index(df):
    """
    N-Index Logic (2026-03-07):
    Calculates a custom rating using only free past run data (Class, Margin, Weight, Agari).
    
    Base Scores:
      G1=100, G2=95, G3=90, OP/L=85, 3勝=80, 2勝=75, 1勝=70, 新馬/未勝利=65
      
    Run Score = Base - (Margin * 10) + (Weight - 55.0) + (AgariRank <= 3 ? 2 : 0)
    
    Final N-Index = Weighted average of last 3 valid runs (50%, 30%, 20%).
    """
    if df.empty:
        if 'NIndex' not in df.columns: df['NIndex'] = 0.0
        return df
    
    if 'NIndex' not in df.columns: df['NIndex'] = 0.0
    
    base_scores = {
        'G1': 100, 'G2': 95, 'G3': 90, 'OP': 85,
        '3勝': 80, '2勝': 75, '1勝': 70, '未勝利': 65, '新馬': 65
    }
    
    weights = [0.5, 0.3, 0.2]
    
    for i, row in df.iterrows():
        past = row.get('PastRuns', [])
        run_scores = []
        
        for run in past:
            if len(run_scores) >= 3:
                break
                
            grade = run.get('Grade', 'OP')
            margin = run.get('Margin', 9.9)
            weight = run.get('Weight', 55.0)
            ti_rank = run.get('TimeIndexRank', 99)
            
            # Skip runs with invalid margin or weight if possible, but we use defaults 9.9 and 55.0
            if margin == 9.9:
                continue # Skip races where we couldn't properly extract margin (often means DNF or lacking data)
                
            base_score = base_scores.get(grade, 85)
            
            # Penalty for losing margin (e.g. 0.2s behind -> -2 points)
            # Bonus for winning margin (e.g. -0.2s ahead -> +2 points)
            margin_penalty = margin * 10
            
            # Weight diff bonus
            weight_diff = weight - 55.0
            
            # Agari Bonus (Time Index Rank proxy for late speed)
            agari_bonus = 2.0 if ti_rank <= 3 else 0.0
            
            score = (base_score - margin_penalty) + weight_diff + agari_bonus
            
            # Cap penalities
            score = max(score, base_score - 20)
            
            run_scores.append(score)
            
        if run_scores:
            # Calculate weighted average
            final_n_score = 0.0
            total_weight = 0.0
            for w, s in zip(weights, run_scores):
                final_n_score += s * w
                total_weight += w
            
            if total_weight > 0:
                final_n_score /= total_weight
                
            df.at[i, 'NIndex'] = round(final_n_score, 1)
        else:
            df.at[i, 'NIndex'] = 0.0
            
    return df

def get_sanrenpuku_recommendations(df, odds_list):
    """
    Returns up to 10 Sanrenpuku combinations.
    Requirements:
      1. Sourced from popularity-sorted odds_list.
      2. At least one horse in the combination must be in the top 5 of BattleScore.
    
    If odds_list is empty (e.g. past race), generates and returns 10 simulated combinations 
    based on Top 5 BattleScore and Top 5 Popularity horses for demonstration purposes.
    """
    if 'BattleScore' not in df.columns or df.empty:
        return []

    # Get Top 5 horses by BattleScore
    top5_df = df.sort_values(by='BattleScore', ascending=False).head(5)
    top5_umaban = set(top5_df['Umaban'].tolist())

    # Create mapping of Umaban -> Name
    name_map = dict(zip(df['Umaban'], df['Name']))

    recs = []
    # (Actual odds recommendation logic can be restored if needed, but for now we prioritize the requested 10-point strategy)
    return recs

def generate_10point_strategy(df, chaos_rank):
    """
    Generates specialized 10-point Sanrenpuku strategies based on Chaos Rank.
    1. B/C Rank (Solid): 1-4-4 Formation OR 5-Horse Box
    2. S/A Rank (Rough): 1-Axis Flux (Hole) OR Hole-Axis 1-4-4 Formation
    Includes 'Trigami' check (odds < 10.0).
    """
    if df.empty or len(df) < 5:
        return {"error": "分析データが不足しています（5頭以上必要です）"}

    # Define "High Index" as the sort order used in the Ranking Table
    # Priority: Projected Score > BattleScore
    sort_col = 'Projected Score' if 'Projected Score' in df.columns else 'BattleScore'
    sorted_df = df.sort_values(by=sort_col, ascending=False).reset_index(drop=True)
    
    # Mapping for easy lookup
    name_map = dict(zip(df['Umaban'], df['Name']))
    odds_map = dict(zip(df['Umaban'].astype(str), pd.to_numeric(df['Odds'], errors='coerce').fillna(10.0)))
    
    strategies = []

    def get_est_odds(combo):
        o1 = float(odds_map.get(str(combo[0]), 10.0))
        o2 = float(odds_map.get(str(combo[1]), 10.0))
        o3 = float(odds_map.get(str(combo[2]), 10.0))
        # 3-RENPUKU Estimated Odds logic (Approximate)
        return round(max(1.0, (o1 * o2 * o3) * 0.48), 1)

    if chaos_rank in ['B', 'C']:
        # --- B/C Rank: Solid ---
        
        # 1. 1-4-4 Formation (10 points)
        # 1st: Top 1, 2nd: 2 3 4 5, 3rd: 3 4 5 6
        h1 = sorted_df.iloc[0]['Umaban']
        r2 = sorted_df.iloc[1:5]['Umaban'].tolist()
        r3 = sorted_df.iloc[2:6]['Umaban'].tolist()
        
        tickets = []
        # Manual formation expansion to ensure exactly 10 points
        # (A, B, C) (A, B, D) (A, B, E) (A, B, F)
        # (A, C, D) (A, C, E) (A, C, F)
        # (A, D, E) (A, D, F)
        # (A, E, F)
        a = h1
        b, c, d, e = r2
        f = r3[-1] # This is the 6th horse
        
        # This matches the user's example: 1st:1, 2nd:2,3,4,5, 3rd:3,4,5,6
        # Combinations: 1-2-3, 1-2-4, 1-2-5, 1-2-6, 1-3-4, 1-3-5, 1-3-6, 1-4-5, 1-4-6, 1-5-6
        raw_list = [
            (a,b,c), (a,b,d), (a,b,e), (a,b,f), 
            (a,c,d), (a,c,e), (a,c,f), 
            (a,d,e), (a,d,f), 
            (a,e,f)
        ]
        for combo in raw_list:
            c_sorted = sorted(list(combo))
            est = get_est_odds(c_sorted)
            tickets.append({
                "horses": c_sorted,
                "names": " - ".join([name_map.get(h, str(h)) for h in c_sorted]),
                "odds": est,
                "trigami": est < 10.0
            })
        
        strategies.append({
            "name": "的中重視 1-4-4 フォーメーション",
            "type": "Formation",
            "tickets": tickets,
            "description": "軸が堅いレース向け。手堅く的中を狙います。"
        })

        # 2. 5-Horse Box (10 points)
        box_h = sorted_df.iloc[:5]['Umaban'].tolist()
        from itertools import combinations
        box_tickets = []
        for combo in combinations(box_h, 3):
            c_sorted = sorted(list(combo))
            est = get_est_odds(c_sorted)
            box_tickets.append({
                "horses": c_sorted,
                "names": " - ".join([name_map.get(h, str(h)) for h in c_sorted]),
                "odds": est,
                "trigami": est < 10.0
            })
        
        strategies.append({
            "name": "3連複 5頭ボックス",
            "type": "Box",
            "tickets": box_tickets,
            "description": "上位の実力が拮抗している順当なレース向け。安心感のある買い方です。"
        })

    else:
        # --- S/A Rank: Rough ---
        # "Hole Axis" = Highest Index among horses with Popularity >= 6
        hole_df = sorted_df[sorted_df['Popularity'] >= 6]
        if hole_df.empty:
            # Fallback to 5th or 6th top index if no popularity data or no holes
            hole_axis_idx = 4 if len(sorted_df) > 4 else 0
        else:
            hole_axis_idx = hole_df.index[0]
            
        h_axis = sorted_df.iloc[hole_axis_idx]['Umaban']
        
        # 1. 1-Head Axis Flux (10 points)
        # Axis: Hole, Opponents: Top 5 Favorites (usually sorted_df excluding hole axis)
        opponents = [h for h in sorted_df['Umaban'].tolist() if h != h_axis][:5]
        
        flux_tickets = []
        from itertools import combinations
        for combo in combinations(opponents, 2):
            c_sorted = sorted([h_axis] + list(combo))
            est = get_est_odds(c_sorted)
            flux_tickets.append({
                "horses": c_sorted,
                "names": " - ".join([name_map.get(h, str(h)) for h in c_sorted]),
                "odds": est,
                "trigami": est < 10.0
            })
            
        strategies.append({
            "name": "穴1頭軸流し",
            "type": "Flux",
            "tickets": flux_tickets,
            "description": "高指数・人気薄を軸に据え、オッズの歪み（高配当）を狙います。"
        })

        # 2. Hole-Axis 1-4-4 Formation (10 points)
        # Axis: Hole, 2nd/3rd: Combination of Top index and mid-range
        a = h_axis
        others = [h for h in sorted_df['Umaban'].tolist() if h != a]
        b, c, d, e = others[:4]
        f = others[4] if len(others) > 4 else others[-1]
        
        form_tickets = []
        raw_list = [
            (a,b,c), (a,b,d), (a,b,e), (a,b,f), 
            (a,c,d), (a,c,e), (a,c,f), 
            (a,d,e), (a,d,f), 
            (a,e,f)
        ]
        for combo in raw_list:
            c_sorted = sorted(list(combo))
            est = get_est_odds(c_sorted)
            form_tickets.append({
                "horses": c_sorted,
                "names": " - ".join([name_map.get(h, str(h)) for h in c_sorted]),
                "odds": est,
                "trigami": est < 10.0
            })
            
        strategies.append({
            "name": "穴軸 1-4-4 フォーメーション",
            "type": "Formation",
            "tickets": form_tickets,
            "description": "穴馬と有力馬をバランス良く組み合わせ、高配当の取りこぼしを防ぎます。"
        })

    return strategies

def get_as_race_recommendations(df, odds_list, axis_umaban=None, num_recs=30):
    """
    Special Sanrenpuku recommendations for High Difficulty (A/S) Races.
    Pattern: User-selected Axis (Top 2 default) + ALL remaining horses.
    """
    if df.empty or len(df) < 3:
        return []

    sort_col = 'Projected Score' if 'Projected Score' in df.columns else 'BattleScore'
    sorted_df = df.sort_values(by=sort_col, ascending=False)
    
    # Determine Axis
    if axis_umaban is not None and len(axis_umaban) == 2:
        valid_axis = [int(u) for u in axis_umaban]
    else:
        # Default to top 2 if not provided or invalid
        axis_df = sorted_df.head(2)
        valid_axis = [int(u) for u in axis_df['Umaban'].tolist()]
    
    # Determine Opponents (ALL remaining horses except Axis)
    target_opponents_df = sorted_df[~sorted_df['Umaban'].astype(int).isin(valid_axis)]
    target_umaban = [int(u) for u in target_opponents_df['Umaban'].tolist()]
    
    # Create the ideal combinations exactly (Axis 1 + Axis 2 + one of the Targets)
    from itertools import combinations
    ideal_combs = set()
    for opp in target_umaban:
        comb = tuple(sorted([axis_umaban[0], axis_umaban[1], opp]))
        ideal_combs.add(comb)

    name_map = {int(row['Umaban']): row['Name'] for _, row in df.iterrows()}
    recs = []
    
    # Process actual odds if available
    if odds_list:
        for item in odds_list:
            horses = tuple(sorted(item['Horses']))
            if horses in ideal_combs:
                names = " - ".join([name_map.get(h, str(h)) for h in horses])
                item_copy = item.copy()
                item_copy['HorseNames'] = names
                recs.append(item_copy)
                if len(recs) >= num_recs:
                    break

    return recs
def calculate_battle_score(df):
    """
    Battle Score Logic (2026-02-16 Spec):
    Score = (Ogura * 0.7) + AgariBonus + PosBonus
    
    Bonuses:
    - Agari (Rank within members): 1st(+20), 2nd(+15), 3rd(+10)
    - Position:
      - Dist <= 1400: AvgPos <= 5 -> +15
      - Dist >= 1600: AvgPos <= 5 -> +5
      
    Icons (Exclusive Priority):
    1. 🎯 (Target): Score Rank 1 or 2
    2. 🚀 (Rocket): Agari Rank 1 (Rescue)
    3. 💀 (Death):  Score Rank Bottom 8 (if not above)
    """
    if df.empty: return df
    
    # 0. Safety Reset
    df = df.reset_index(drop=True)
    
    # 1. Calculate Base (Flat Ogura Index)
    df = calculate_ogura_index(df)
    
    # --- NO SCALING HERE (Per new spec, use raw Ogura ~80 base) ---
    
    # 2. Statistics Collection for Bonuses
    current_dist = 1600
    # Try to get distance from first row or common value if possible, 
    # but here we process row by row or vectorised.
    # It's better to assume single race per DF usually.
    if 'CurrentDistance' in df.columns and not df.empty:
        try: current_dist = int(df['CurrentDistance'].iloc[0])
        except: pass
    
    # Prepare lists for ranking Agari
    agari_data = []

    for i, row in df.iterrows():
        past = row.get('PastRuns', [])
        
        # --- Stats Calculation (Avg Best 3 or All?) ---
        # The prompt says "Average of Best 3" in previous context, 
        # but 2026-02-16 spec doesn't explicitly restrict to "Best 3", 
        # however let's stick to "Average" of valid data for stability.
        # Wait, the prompt says "Agari 3F (Past Average)". Let's use simple average of recent runs.
        
        agari_vals = []
        pos_vals = []
        
        # Filter Runs: Distance (+/- 200m) AND Date (1 Year) [Keep this logic as it's good practice]
        now = datetime.now() # Use actual time or fixed ref?
        # Fixed ref for consistency if needed, but 'now' is fine.
        
        valid_runs = []
        for run in past:
            # Basic validation
            if run.get('Time', 0) == 0: continue
            
            # Date filter (1 year)
            r_date_str = run.get('Date', '2000.01.01')
            try:
                # Approximate check
                if '202' in r_date_str: # Simple check for recent years
                   valid_runs.append(run)
            except:
                pass
        
        # If no valid runs found by date, take all runs
        if not valid_runs: valid_runs = past
        
        agari_real_count = 0
        
        for run in valid_runs:
            # Agari
            a = run.get('Agari', 35.0)
            # Check if Real (not imputed)
            is_real = (run.get('AgariType') == 'Real')
            if is_real:
                agari_vals.append(a)
                agari_real_count += 1
            else:
                 # If imputed, maybe ignore for "Average" calculation to get True Ability?
                 # Spec says: "If missing, substitute 35.0". 
                 # This implies we use 35.0 for missing data points.
                 agari_vals.append(35.0)
            
            # Position (Improved: Average of all corners)
            p_str = str(run.get('Passing', '8'))
            try:
                p_parts = [int(t) for t in re.split(r'[,\-()]+', p_str) if t.strip().isdigit()]
                if p_parts:
                    pos_vals.append(np.mean(p_parts))
                else:
                    pos_vals.append(8.0)
            except:
                pos_vals.append(8.0)
                
        # Calculate Averages
        if agari_vals:
            avg_agari = np.mean(agari_vals)
        else:
            avg_agari = 35.0
            
        if pos_vals:
            avg_pos = np.mean(pos_vals)
        else:
            avg_pos = 8.0
            
        df.at[i, 'AvgAgari'] = round(avg_agari, 2)
        df.at[i, 'AvgPosition'] = round(avg_pos, 1)
        df.at[i, 'AgariTrust'] = (agari_real_count > 0)
        
    # 3. Determine Agari Rank
    # Only rank rows that actually have real Agari data to prevent dummies from taking top spots.
    df['AgariRank'] = 99
    trusted_mask = df['AgariTrust'] == True
    if trusted_mask.any():
        df.loc[trusted_mask, 'AgariRank'] = df.loc[trusted_mask, 'AvgAgari'].rank(method='min', ascending=True).fillna(99).astype(int)
        
    # 4. Final Score Calculation
    # [Placeholder] Separating logic by difficulty
    # df = calculate_solid_race(df) # or calculate_rough_race(df)
    
    logger.info("======== BATTLE SCORE CALCULATION LOG (New Spec) ========")
    
    for i, row in df.iterrows():
        speed_val = row.get('SpeedIndex', 0.0)
        avg_pos = df.at[i, 'AvgPosition']
        agari_rank = df.at[i, 'AgariRank']
        
        # Base
        base_score = float(speed_val) * 0.7
        
        bonus_points = 0
        bonus_log = []
        
        # Bonus A: Agari Rank
        # (Removed: The unconditional +20 positional bug has been abolished)
        agari_bonus = 0
        
        if agari_bonus > 0:
            bonus_points += agari_bonus
            bonus_log.append(f"AgariRank{agari_rank}(+{agari_bonus})")
            
        # Bonus B: Position
        pos_bonus = 0
        if current_dist <= 1400:
            if avg_pos <= 5.0:
                pos_bonus = 15
                bonus_log.append("PosSprint(+15)")
        elif current_dist >= 1600:
             if avg_pos <= 5.0:
                pos_bonus = 5
                bonus_log.append("PosMid(+5)")
        # 1401-1599: No bonus specified, so 0.
        
        bonus_points += pos_bonus
        
        total_score = base_score + bonus_points
        df.at[i, 'BattleScore'] = round(total_score, 1)
        df.at[i, 'AgariRank'] = agari_rank # Save for icon logic
        
        # Score Breakdown for High-Res Logging
        df.at[i, 'ScoreBaseOgura'] = round(base_score, 1)
        df.at[i, 'ScoreTimeIndex'] = 0.0
        
        # C. Makuri (Movement) Score Calculation
        makuri_pts = 0.0
        if past:
            latest_run = past[0] # Focus on latest performance
            lp_str = str(latest_run.get('Passing', ''))
            lp_parts = [int(t) for t in re.split(r'[,\-()]+', lp_str) if t.strip().isdigit()]
            l_rank = latest_run.get('Rank', 99)
            if lp_parts and l_rank != 99:
                max_lp = max(lp_parts)
                l_delta = max_lp - l_rank
                if l_delta >= 7:
                    makuri_pts += 5.0
                    l_agari_rank = latest_run.get('AgariRank', 99)
                    if l_agari_rank <= 3:
                        makuri_pts += 2.0
                        
        df.at[i, 'ScoreMakuri'] = round(makuri_pts, 1)
        df.at[i, 'ScoreTraining'] = 0.0
        df.at[i, 'ScoreWeight'] = 0.0
        df.at[i, 'ScoreBloodline'] = 0.0
        
        try:
             horse_name = df.at[i, 'Name']
             logger.info(f"{horse_name}: Base({base_score:.1f}) + Bonus({bonus_points})[{', '.join(bonus_log)}] = {total_score:.1f}")
        except: pass

    logger.info("====================================================")
    
    # 5. Sorting & Ranking
    df = df.sort_values('BattleScore', ascending=False).reset_index(drop=True)
    num_horses = len(df)
    
    # 6. UI Icons (Exclusive Logic - REVERTED TO TIME INDEX)
    # Priority: 🎯◎(Index 1位) > ○(Index 2位) > ▲(Index 3位) > 🚀(Agari 1位) > 💀(Bottom 8)
    
    df['Alert'] = ""
    
    # We need to rank by OguraIndex for the primary icons
    df_rank_idx = df.sort_values('OguraIndex', ascending=False).reset_index(drop=True)
    idx_top_1 = df_rank_idx.iloc[0]['Name'] if len(df_rank_idx) >= 1 else None
    idx_top_2 = df_rank_idx.iloc[1]['Name'] if len(df_rank_idx) >= 2 else None
    idx_top_3 = df_rank_idx.iloc[2]['Name'] if len(df_rank_idx) >= 3 else None

    # Top Jockeys for Condition 1 (Not a popular jockey)
    # This list represents leading jockeys.
    top_jockeys = [
        "ルメール", "川田", "戸崎", "横山武", "松山",
        "岩田望", "武豊", "坂井", "鮫島克", "モレイラ",
        "レーン", "Ｍデム", "菅原明", "西村淳", "藤岡佑",
        "三浦", "田辺", "横山和", "丹内", "佐々木"
    ]
    
    # Extract Win Odds (Fetch from results if needed for past races)
    temp_df = df.copy()
    if 'Odds' not in temp_df.columns:
        temp_df['Odds'] = 0.0
    
    if temp_df['Odds'].sum() == 0:
        from core import scraper # Local import
        try:
            rid = temp_df['RaceID'].iloc[0] if 'RaceID' in temp_df.columns else None
            if rid:
                results = scraper.fetch_race_result(rid)
                if results:
                    mapped_odds = temp_df['Name'].map(lambda n: results.get(n, {}).get('ResultOdds', 0.0))
                    temp_df['Odds'] = mapped_odds
                    logger.debug(f"Debug [NeverPlaced]: Fetched odds for {len(results)} horses.")
        except Exception as e:
            logger.debug(f"Debug [NeverPlaced] Error fetching odds: {e}")

    temp_df['Odds'] = pd.to_numeric(temp_df['Odds'], errors='coerce').fillna(9999.0)
    temp_df.loc[temp_df['Odds'] == 0, 'Odds'] = 9999.0
    
    # Calculate Popularity from Odds to ensure it's always available (especially for past races)
    valid_odds_df = temp_df[temp_df['Odds'] < 9999.0]
    if not valid_odds_df.empty:
        # Only overwrite Popularity for horses with valid odds
        temp_df.loc[temp_df['Odds'] < 9999.0, 'Popularity'] = valid_odds_df['Odds'].rank(method='min', ascending=True)
    
    # Ensure any remaining horses with 9999.0 odds don't get ranked 1st
    temp_df.loc[temp_df['Odds'] == 9999.0, 'Popularity'] = 99
    df['Popularity'] = temp_df['Popularity']
    
    # 1. Odds Sets
    odds_bottom5_set = set(temp_df.nlargest(5, 'Odds', keep='all')['Name'].tolist()) if len(temp_df) >= 5 else set(temp_df['Name'].tolist())
    df['Odds'] = temp_df['Odds']
    
    # NEW: Top 8 Popularity (Lowest Odds) - Includes ties
    pop_top8_set = set(temp_df.nsmallest(8, 'Odds', keep='all')['Name'].tolist()) if len(temp_df) >= 8 else set(temp_df['Name'].tolist())
    
    # 2. Death Icon Cutoff: Bottom 8 by Speed Index AND Bottom 9 by BattleScore - Includes ties
    speed_bottom8 = set(df.nsmallest(8, 'OguraIndex', keep='all')['Name'].tolist()) if len(df) >= 8 else set(df['Name'].tolist())
    battle_bottom9 = set(df.nsmallest(9, 'BattleScore', keep='all')['Name'].tolist()) if len(df) >= 9 else set(df['Name'].tolist())
    death_names = speed_bottom8.intersection(battle_bottom9)
    
    # Remove Top 8 popular horses from Death list
    death_names = death_names.difference(pop_top8_set)    
    # 3. Never Placed Conditions 2 & 4 Cutoffs
    ogura_bottom5_set = set(df.nsmallest(5, 'OguraIndex', keep='all')['Name'].tolist()) if len(df) >= 5 else set(df['Name'].tolist())
    battle_bottom5_set = set(df.nsmallest(5, 'BattleScore', keep='all')['Name'].tolist()) if len(df) >= 5 else set(df['Name'].tolist())

    df['IsNeverPlaced'] = False
    df['BattleScoreRank'] = df['BattleScore'].rank(ascending=False, method='min')

    for i in range(num_horses):
        name = df.at[i, 'Name']
        ag_rank = df.at[i, 'AgariRank']
        jockey = str(df.at[i, 'Jockey'])
        popularity = df.at[i, 'Popularity'] if pd.notna(df.at[i, 'Popularity']) else 99
        score_rank = df.at[i, 'BattleScoreRank']
        
        icon = ""
        
        # Check "Dark Horse" condition (🔥)
        is_dark_horse = False
        if popularity < 99 and (popularity - score_rank) >= 5:
            is_dark_horse = True

        # Check "Never Placed" conditions
        cond1_not_top_jockey = True
        for tj in top_jockeys:
            if tj in jockey:
                cond1_not_top_jockey = False
                break
                
        cond2_low_speed = name in ogura_bottom5_set
        cond3_low_odds = name in odds_bottom5_set
        cond4_low_battle = name in battle_bottom5_set
        
        is_never_placed = cond1_not_top_jockey and cond2_low_speed and cond3_low_odds and cond4_low_battle
        
        # Exception: Top 8 Popularity cannot be a bomb
        if name in pop_top8_set:
            is_never_placed = False
        
        if is_never_placed:
            df.at[i, 'IsNeverPlaced'] = True
        
        # Priority Logic: 💣 (Never Placed) > 🎯◎(Index 1位) > ○(Index 2位) > ▲(Index 3位) > 🔥(Dark Horse) > 🚀(Agari 1位) > 💀(Bottom 8)
        if is_never_placed:
            icon = "💣"
        elif name == idx_top_1:
            icon = "🎯◎"
        elif name == idx_top_2:
            icon = "○"
        elif name == idx_top_3:
            icon = "▲"
        elif is_dark_horse:
            icon = "🔥"
        elif ag_rank == 1:
            icon = "🚀"
        elif name in death_names:
            icon = "💀"
            
        # Missing Data Alert (⚠️)
        n_idx = df.at[i, 'NIndex'] if 'NIndex' in df.columns else 0.0
        b_score = df.at[i, 'BattleScore'] if 'BattleScore' in df.columns else 0.0
        if n_idx == 0 and b_score == 0:
            icon = "⚠️"
            
        df.at[i, 'Alert'] = icon

    return df

def get_direct_matches(df):
    """
    Analyzes past runs to find head-to-head matches between horses in the current race.
    Returns: List of (WinnerName, LoserName, MatchDetailsDict)
    """
    matches = []
    if df.empty: return matches
    
    horse_runs = {}
    for _, row in df.iterrows():
        name = row['Name']
        # Extract past runs, handle date
        past = row.get('PastRuns', [])
        for run in past:
            race_name = run.get('RaceName', 'Unknown')
            date_str = run.get('Date', '2000.01.01')
            rank = run.get('Rank', 99)
            
            key = f"{date_str}_{race_name}"
            if key not in horse_runs: horse_runs[key] = []
            horse_runs[key].append({'name': name, 'rank': rank, 'details': run})
            
    # Compare
    for key, participants in horse_runs.items():
        if len(participants) < 2: continue
        
        # Sort by rank
        participants.sort(key=lambda x: x['rank'])
        winner = participants[0]
        for loser in participants[1:]:
            if winner['rank'] < loser['rank']:
                matches.append((winner['name'], loser['name'], winner['details']))
                
    return matches

def get_betting_recommendation(df):
    """
    Generates betting advice based on the race analysis.
    """
    if df.empty: return None
    
    # Sort by BattleScore
    df_s = df.sort_values('BattleScore', ascending=False).reset_index(drop=True)
    if len(df_s) < 3: return None
    
    top_3 = df_s.head(3)['Umaban'].tolist()
    top_3_names = df_s.head(3)['Name'].tolist()
    
    return {
        "Type": "Box (3-Ren-Puku / Wide)",
        "Horses": ", ".join(map(str, top_3)),
        "Names": ", ".join(top_3_names),
        "Reason": "Top 3 horses by Battle Score show high reliability."
    }

def get_jockey_icon(name):
    """
    Returns performance icon for jockeys.
    """
    if not isinstance(name, str): return ""
    
    # Gold 🥇
    if any(x in name for x in ["ルメール", "川田", "C.ルメール"]): return "🥇"
    # Silver 🥈
    if any(x in name for x in ["戸崎", "武豊", "モレイラ", "J.モレイラ"]): return "🥈"
    # Bronze 🥉
    if any(x in name for x in ["坂井", "菅原", "横山武", "岩田望", "松山"]): return "🥉"
    
    return ""

def apply_jockey_icons(df):
    """
    Applies jockey icons to the Jockey column.
    """
    if 'Jockey' in df.columns:
        df['Jockey'] = df['Jockey'].apply(lambda x: f"{x} {get_jockey_icon(x)}")
    return df

def calculate_confidence(df):
    """
    Evaluates the quality of predictions for a race.
    Returns: (Score(0-100), Rating(S, A, B, C), Reasons(List))
    Logic:
    - High score if there's a strong Index leader.
    - Bonus if Top Index horse also has top Agari.
    - Bonus for front-runners.
    """
    if df.empty: return 0.0, "C", ["No Data"]
    
    reasons = []
    score = 50.0 # Base
    
    # 1. Index Gap Analysis
    # We sort by OguraIndex
    df_idx = df.sort_values('OguraIndex', ascending=False).reset_index(drop=True)
    top_horse_name = df_idx.iloc[0]['Name']
    
    if len(df_idx) >= 2:
        gap = df_idx.iloc[0]['OguraIndex'] - df_idx.iloc[1]['OguraIndex']
        if gap >= 15:
            score += 30
            reasons.append("Dominant Index Leader")
        elif gap >= 8:
            score += 20
            reasons.append("Strong Index Leader")
        elif gap >= 4:
            score += 10
            reasons.append("Clear Index Leader")
            
    # 2. Agari Consistency
    # AgariRank is in the DF
    top_agari_horse = df.sort_values('AvgAgari').iloc[0]
    if top_agari_horse['Name'] == top_horse_name:
        score += 15
        reasons.append("Speed & Agari Match")
        
    # 3. Position Stability
    top_pos_avg = top_agari_horse['AvgPosition']
    if top_pos_avg <= 5.0:
        score += 10
        reasons.append("Reliable Running Style")
        
    # Rating Mapping
    rating = "C"
    if score >= 85: rating = "🔥🔥 S"
    elif score >= 70: rating = "🔥 A"
    elif score >= 55: rating = "B"
    
    # Set Status for display/scanner
    # Reset all Status
    df['Status'] = 'Normal'
    # Set SS for the top recommended horse
    df.loc[df['Name'] == top_horse_name, 'Status'] = 'SS'

    return round(min(score, 100), 1), rating, reasons

def calculate_strength_suitability(df, course_profile):
    """
    Calculates the 2D scatter plot metrics: Strength (X) and Suitability (Y).
    Requires df to already have BattleScore, OguraIndex, AvgPosition, AvgAgari calculated.
    """
    if df.empty: return df
    
    # ─── Extract race context ───────────────────────────
    cur_dist    = int(df['CurrentDistance'].iloc[0]) if 'CurrentDistance' in df.columns else 1800
    cur_surface = str(df['CurrentSurface'].iloc[0]) if 'CurrentSurface' in df.columns else ''
    is_tight    = '小回り' in course_profile
    is_long     = '直線が長い' in course_profile
    
    # ─── STRENGTH (X-axis): Pure base ability ──────────
    def calc_strength_raw(row):
        past = row.get('PastRuns', [])
        
        # (A) BattleScore — composite ability score already computed (weight 50%)
        bs = float(row.get('BattleScore', 0) or 0)
        a_score = bs * 0.50
        
        # (B) Inverse Popularity: lower odds/popular = stronger perceived (weight 30%)
        pop = int(row.get('Popularity', 9) or 9)
        total_horses = max(len(df), 1)
        b_score = max(0, 30 * (1 - (pop - 1) / (total_horses - 1)))
        
        # (C) Grade class bonus — proven against top opponents (weight 20%)
        class_pts = 0
        for r in past[:12]:
            grade = str(r.get('Grade', '')).upper()
            rnk = r.get('Rank', 99)
            if 'G1' in grade or grade == 'GI':
                class_pts += 6 if rnk <= 3 else 2
            elif 'G2' in grade or grade == 'GII':
                class_pts += 4 if rnk <= 3 else 1
            elif 'G3' in grade or grade == 'GIII':
                class_pts += 2 if rnk <= 3 else 0
        c_score = min(20, class_pts)
        
        return a_score + b_score + c_score
    
    df['_strength_raw'] = df.apply(calc_strength_raw, axis=1)
    
    # Normalize with stronger spread using percentile anchoring
    s_vals = df['_strength_raw'].values
    s_p10, s_p90 = np.percentile(s_vals, 10), np.percentile(s_vals, 90)
    def _norm_s(v):
        if s_p90 == s_p10: return 50
        return max(5, min(98, (v - s_p10) / (s_p90 - s_p10) * 88 + 10))
    df['Strength (X)'] = df['_strength_raw'].apply(_norm_s)
    
    # ─── SUITABILITY (Y-axis): Condition fit ───────────
    def calc_suitability_raw(row):
        past = row.get('PastRuns', [])
        score = 0.0
        
        cur_s1 = cur_surface[:1] if cur_surface else ''
        
        # (A) Surface specialization — MOST IMPORTANT (weight 40%)
        total_past = len(past[:12])
        surf_runs = [r for r in past[:12] if cur_s1 and str(r.get('Surface',''))[:1] == cur_s1]
        total_sf = len(surf_runs)
        wins_sf  = sum(1 for r in surf_runs if r.get('Rank', 99) <= 3)
        
        if total_past == 0:
            score += 20  # no data = neutral
        elif total_sf == 0:
            score += 0   # NEVER ran on this surface = very low suitability
        else:
            surf_ratio = total_sf / total_past
            sf_wr = wins_sf / total_sf
            score += min(40, surf_ratio * 20 + sf_wr * 20)
        
        # (B) Distance match win rate (weight 30%)
        dist_runs = [r for r in past[:12] if abs(r.get('Distance', 0) - cur_dist) <= 200]
        total_d = len(dist_runs)
        wins_d  = sum(1 for r in dist_runs if r.get('Rank', 99) <= 3)
        if total_d == 0:
            score += 12  # neutral
        else:
            d_wr = wins_d / total_d
            score += min(30, d_wr * 20 + (total_d / 12 * 10))
        
        # (C) Pace profile / コース特性 (weight 20%)
        avg_pos = float(row.get('AvgPosition', 8) or 8)
        avg_agari = float(row.get('AvgAgari', 36) or 36)
        
        if is_tight:
            pace_score = max(0, 20 * (1 - (avg_pos - 1) / 9))
        elif is_long:
            pace_score = max(0, 20 * (1 - (avg_agari - 33) / 5))
        else:
            pace_score = max(0, 10 * (1 - (avg_pos - 1) / 9)) + max(0, 10 * (1 - (avg_agari - 33) / 5))
        score += min(20, pace_score)
        
        # (D) Recent momentum (weight 10%)
        momentum = 0
        for i, r in enumerate(past[:3]):
            rnk = r.get('Rank', 99)
            w = 3 - i
            if rnk == 1:   momentum += 3 * w
            elif rnk <= 3: momentum += 2 * w
            elif rnk <= 5: momentum += 1 * w
        score += min(10, momentum)
        
        return score
    
    df['_suit_raw'] = df.apply(calc_suitability_raw, axis=1)
    
    # Normalize suitability with percentile anchoring
    y_vals = df['_suit_raw'].values
    y_p10, y_p90 = np.percentile(y_vals, 10), np.percentile(y_vals, 90)
    def _norm_y(v):
        if y_p90 == y_p10: return 50
        return max(5, min(98, (v - y_p10) / (y_p90 - y_p10) * 88 + 10))
    df['Suitability (Y)'] = df['_suit_raw'].apply(_norm_y)
    
    # ─── Projected Score ────────────────────────────────
    df['Projected Score'] = df['BattleScore'] + (df['Strength (X)'] + df['Suitability (Y)']) * 0.25
    
    return df
def generate_race_summary(df):
    """
    強適 Ranking Table の結果から、人間が直感的に理解できるレースサマリーを生成する。
    """
    if df.empty:
        return ""

    # 1. 波乱性能の評価 (v2ロジック)
    chaos_res = evaluate_race_chaos_v2(df)
    overall_rank = chaos_res['rank']
    chaos_reason = chaos_res['reason']
    
    # 記号の付与
    rank_labels = {"S": "💥 極限波乱 (S)", "A": "⚠️ 波乱含み (A)", "B": "⚖️ 標準 (B)", "C": "🟢 順当 (C)"}
    display_rank = rank_labels.get(overall_rank, overall_rank)

    # 2. 予測されるレース展開 (詳細版)
    # 上位陣の脚質分布から展開を精密に判定
    top_pos_df = df.sort_values('BattleScore', ascending=False).head(5)
    front_runners = top_pos_df[top_pos_df['AvgPosition'] <= 4.0] if 'AvgPosition' in top_pos_df.columns else []
    stayers = top_pos_df[top_pos_df['AvgPosition'] >= 10.0] if 'AvgPosition' in top_pos_df.columns else []
    
    tenkai_text = ""
    if len(front_runners) >= 3:
        tenkai_text = "【🔥 ハイペース濃厚】先行勢が強力。激しい位置取り争いが発生し、最後はスタミナと決め手の勝負になります。差し馬の台頭を強く警戒。"
    elif len(front_runners) <= 1:
        tenkai_text = "【💤 スローペース有力】逃げ馬が楽をできる展開。道中のペースが上がらず、直線での立ち回りと加速力が重視される「前残り」に注意。"
    else:
        tenkai_text = "【⚔️ ミドルペース/平均的】バランスの取れたメンバー構成。大きな有利不利はなく、実力がストレートに反映されやすい展開です。"

    # 上がり最速候補の捕捉
    if 'AvgAgari' in df.columns:
        fastest_closer = df.sort_values('AvgAgari').iloc[0]
        if fastest_closer['AvgAgari'] < 36.0:
            tenkai_text += f"\n- **爆速の末脚**: 馬番 {int(fastest_closer['Umaban'])}（{fastest_closer['Name']}）は上がり性能が突出しており、展開次第で一気のごぼう抜きも。"

    # 3. 馬券構築のセオリー
    theory = ""
    if overall_rank in ["S", "A"]:
        theory = "人気を信じすぎず、適性上位の「穴馬」からワイドや3連複で高配当を狙うのが正解。点数を広げるだけの価値があるレースです。"
    elif overall_rank == "C":
        theory = "指数1位の信頼度が高め。軸に固定し、相手を3～5頭に絞って効率的に回収を目指しましょう。"
    else:
        theory = "基本は1位〜3位の序列通り。ただし、適性が僅差のため、パドックや馬体重の変化を確認してヒモを調整してください。"

    # 4. 特注ダークホース
    dark_horses = df[(df['Popularity'] >= 6) & (df['BattleScore'] >= 80)].copy()
    horse_list_md = ""
    if not dark_horses.empty:
        for _, h in dark_horses.head(2).iterrows():
            pop_text = f"{int(h['Popularity'])}人気" if pd.notna(h['Popularity']) else "人気不明"
            u_val = h['Umaban']
            u_text = f"{int(float(u_val))}" if pd.notna(u_val) else "??"
            horse_list_md += f"- 🐴 {u_text}番 **{h['Name']}** ({pop_text} / 指数 {int(h['BattleScore'])})\n"
    else:
        horse_list_md = "- 該当なし (上位人気が能力でも優勢です)"

    # Markdown生成 (UI)
    summary_md = f"""
### 📊 レース展開予測 & 波乱診断

| 項目 | 分析内容 |
| :--- | :--- |
| **総合波乱度** | **{display_rank}** |
| **判定の根拠** | {chaos_reason} |
| **展開の予想** | {tenkai_text} |
| **推奨戦略** | {theory} |

#### 🎯 激走期待の穴馬
{horse_list_md}
"""
    return summary_md

def analyze_odds_gaps(df):
    """
    単勝オッズの断層（隣り合う馬のオッズ比が1.5倍以上）を解析し、グループ分けを行う。
    """
    if df.empty or 'Odds' not in df.columns:
        return {'group_a': [], 'group_b': [], 'gaps': []}

    # オッズで昇順ソート
    df_sorted = df.copy()
    # 文字列の可能性を考慮して変換
    df_sorted['Odds'] = pd.to_numeric(df_sorted['Odds'], errors='coerce').fillna(999.0)
    df_sorted = df_sorted.sort_values('Odds')

    odds_list = df_sorted['Odds'].tolist()
    umaban_list = df_sorted['Umaban'].tolist()
    
    gaps = []
    for i in range(len(odds_list) - 1):
        if odds_list[i] > 0:
            ratio = odds_list[i+1] / odds_list[i]
            if ratio >= 1.5:
                gaps.append(i + 1) # 断層の位置（上位何頭目か）

    # グループ分け
    first_gap = gaps[0] if len(gaps) >= 1 else min(2, len(umaban_list))
    second_gap = gaps[1] if len(gaps) >= 2 else min(5, len(umaban_list))
    
    group_a = umaban_list[:first_gap]
    group_b = umaban_list[first_gap:second_gap]
    
    return {
        'group_a': group_a,
        'group_b': group_b,
        'gaps': gaps,
        'df_sorted': df_sorted
    }

def calculate_pro_formation_betting(df, total_budget):
    """
    プロ仕様の買い目構築・資金配分ロジック。
    1. オッズ断層によるグループ分け
    2. 3連複フォーメーション生成
    3. 合成オッズに基づく資金配分（トリガミ排除）
    """
    from itertools import combinations
    
    analysis = analyze_odds_gaps(df)
    group_a = analysis['group_a']
    group_b = analysis['group_b']
    df_sorted = analysis.get('df_sorted', df)
    
    if not group_a:
        # 断層が全くない場合の極端なフォールバック
        umaban_list = df_sorted['Umaban'].tolist()
        group_a = umaban_list[:1]
        group_b = umaban_list[1:3]

    # --- STEP 2: フォーメーション生成 ---
    # 軸馬（1列目）：Group Aの最上位
    col1 = [group_a[0]]
    # 相手（2列目）：Group A全体 + Group Bの上位（最大3頭程度）
    col2 = list(set([str(x) for x in (group_a + group_b[:2])]))
    # ヒモ（3列目）：Group A + Group B全体
    col3 = list(set([str(x) for x in (group_a + group_b)]))
    
    # 全組み合わせ生成
    raw_tickets = []
    for c1 in col1:
        for c2 in col2:
            if str(c1) == str(c2): continue
            for c3 in col3:
                if str(c3) == str(c1) or str(c3) == str(c2): continue
                # 三連複なのでソートして重複排除
                ticket = tuple(sorted([int(c1), int(c2), int(c3)]))
                if ticket not in raw_tickets:
                    raw_tickets.append(ticket)
    
    if not raw_tickets:
        return {'error': '条件に合う買い目が生成できませんでした。'}

    # --- STEP 3: 資金配分 ---
    # 推計三連複オッズ = (Win1 * Win2 * Win3) * 0.15 (補正係数)
    odds_map = dict(zip(df_sorted['Umaban'].astype(str), df_sorted['Odds']))
    
    ticket_data = []
    total_inv_odds = 0
    
    for t in raw_tickets:
        # 各馬の単勝オッズ取得
        o1 = float(odds_map.get(str(t[0]), 10.0))
        o2 = float(odds_map.get(str(t[1]), 10.0))
        o3 = float(odds_map.get(str(t[2]), 10.0))
        
        # 簡易合成オッズ
        est_odds = (o1 * o2 * o3) * 0.15
        inv_odds = 1.0 / est_odds if est_odds > 0 else 0
        
        ticket_data.append({
            'ticket': t,
            'est_odds': est_odds,
            'inv_odds': inv_odds
        })
        total_inv_odds += inv_odds
        
    # 重み付け配分 (100円単位)
    allocated_tickets = []
    actual_total_bet = 0
    
    if total_inv_odds > 0:
        for td in ticket_data:
            weight = td['inv_odds'] / total_inv_odds
            amount = round((total_budget * weight) / 100) * 100
            
            if amount >= 100:
                est_payout = (td['est_odds'] * amount / 100) * 100
                is_torigami = est_payout < total_budget
                
                allocated_tickets.append({
                    'horses': [int(x) for x in td['ticket']],
                    'amount': amount,
                    'est_payout': round(est_payout),
                    'is_torigami': is_torigami,
                    'est_odds': round(td['est_odds'], 1)
                })
                actual_total_bet += amount

    return {
        'col1': col1,
        'col2': col2,
        'col3': col3,
        'tickets': allocated_tickets,
        'actual_total_bet': actual_total_bet,
        'group_a': group_a,
        'group_b': group_b,
        'gaps_count': len(analysis['gaps'])
    }

def evaluate_chaos_level_strict(df):
    """
    1番人気の単勝オッズに基づき、S/A/B/C判定を厳格に行う。
    ・S判定（大荒れ）: 1番人気の単勝オッズが 4.0倍以上
    ・A判定（混戦）: 1番人気のオッズが 3.0倍〜3.9倍、または断層が極端に少ない場合
    ・B判定（標準）: 上記以外
    ・C判定（堅い）: 1番人気のオッズが 1.9倍以下
    """
    if df.empty or 'Odds' not in df.columns:
        return {'rank': 'B', 'reason': 'オッズデータ不足のためB判定'}

    # odds を数値に変換
    odds_series = pd.to_numeric(df['Odds'], errors='coerce').fillna(999.0)
    fav_odds = odds_series.min()
    
    # 断層解析
    analysis = analyze_odds_gaps(df)
    gaps_count = len(analysis['gaps'])
    
    rank = "B"
    reason_list = [f"1番人気単勝オッズ: {fav_odds:.1f}倍"]
    
    if fav_odds >= 4.0:
        rank = "S"
        reason_list.append("1番人気の支持が非常に低く、大波乱の可能性が極めて高いレースです。")
    elif fav_odds <= 1.9:
        rank = "C"
        reason_list.append("圧倒的な1番人気が存在し、順等に決着する可能性が高いレースです。")
    elif 3.0 <= fav_odds <= 3.9:
        rank = "A"
        reason_list.append("1番人気の信頼度が低く、上位勢が拮抗した混戦模様です。")
    elif gaps_count <= 1:
        rank = "A"
        reason_list.append("オッズ断層が少なく、実力が拮抗してどこからでも狙える波乱含みの構成です。")
    else:
        rank = "B"
        reason_list.append("標準的なオッズ分布です。")
        
    return {
        'rank': rank,
        'reason': " ".join(reason_list),
        'fav_odds': fav_odds,
        'gaps_count': gaps_count
    }

def generate_unified_sniper_pool(df, chaos_rank):
    """
    刷新された統合買い目生成ロジック (Ver 2.6)
    STEP 1: 買い目プールの統合生成
    """
    from itertools import combinations
    
    if df.empty:
        return {'error': 'データがありません'}

    # 1. 母集団の絞り込み (人気フィルター)
    # S・A: 全頭 (1〜18番人気) / B・C: 1〜11番人気のみ
    if chaos_rank in ['S', 'A']:
        df_filtered = df.dropna(subset=['Popularity']).copy()
    else:
        df_filtered = df[df['Popularity'] <= 11].copy()
    
    if len(df_filtered) < 3:
        return {'error': f'母集団の頭数が不足しています ({len(df_filtered)}頭)'}

    # スコア・オッズの準備
    score_col = 'Projected Score' if 'Projected Score' in df.columns else ('BattleScore' if 'BattleScore' in df.columns else 'temp_score')
    if score_col == 'temp_score' and 'temp_score' not in df.columns:
        df['temp_score'] = 100 - df['Popularity'].fillna(99).astype(float)

    # 予測スコア上位5頭の選定 (パターンの軸判定用)
    top_5_by_score = df.sort_values(score_col, ascending=False)['Umaban'].head(5).astype(int).tolist()
    pivot_set = set(top_5_by_score)
    
    odds_map = dict(zip(df['Umaban'].astype(str), pd.to_numeric(df['Odds'], errors='coerce').fillna(10.0)))
    name_map = dict(zip(df['Umaban'], df['Name']))
    score_map = dict(zip(df['Umaban'], df[score_col]))

    # 3. オッズフィルターの適用 (波乱度連動)
    ranges = {
        'S': (30.0, 500.0),
        'A': (50.0, 400.0),
        'B': (50.0, 300.0),
        'C': (10.0, 150.0)
    }
    # 5. 点数の下限保証 (S:8点, A:6点)
    limits = { 'S': 8, 'A': 6, 'B': 4, 'C': 2 }
    
    base_min, base_max = ranges.get(chaos_rank, (50.0, 300.0))
    min_required = limits.get(chaos_rank, 4)
    
    all_umaban = df_filtered['Umaban'].unique().tolist()
    all_combos = list(combinations(all_umaban, 3))
    
    retry_count = 0
    adj_min, adj_max = base_min, base_max
    exclusion_log = []
    
    while retry_count < 10:
        pattern_a = []
        pattern_b = []
        bonus_candidates = []
        
        for combo in all_combos:
            # 推計オッズ算出
            o1 = float(odds_map.get(str(combo[0]), 10.0))
            o2 = float(odds_map.get(str(combo[1]), 10.0))
            o3 = float(odds_map.get(str(combo[2]), 10.0))
            est_odds = max(1.0, (o1 * o2 * o3) * 0.48)
            
            # スコア合計値 (ソート用)
            total_score = sum(score_map.get(h, 0) for h in combo)
            item = {
                'horses': sorted(list(map(int, combo))),
                'names': [name_map.get(h, str(h)) for h in sorted(list(combo))],
                'est_odds': round(est_odds, 1),
                'total_score': total_score
            }

            c_set = set(map(int, combo))
            # スコア上位5頭との合致数
            match_count = len(c_set.intersection(pivot_set))

            if adj_min <= est_odds <= adj_max:
                if match_count >= 2:
                    item['type'] = 'A'
                    pattern_a.append(item)
                elif match_count == 1:
                    item['type'] = 'B'
                    pattern_b.append(item)
            elif est_odds > adj_max:
                bonus_candidates.append(item)
                if retry_count == 0:
                    exclusion_log.append(f"{combo}: オッズ上限超え ({est_odds:.1f}倍)")
            else:
                if retry_count == 0:
                    exclusion_log.append(f"{combo}: オッズ下限以下 ({est_odds:.1f}倍)")

        # 4. パターン分けとソート (予測スコア合計値が高い順、最大10点)
        pattern_a = sorted(pattern_a, key=lambda x: x['total_score'], reverse=True)[:10]
        pattern_b = sorted(pattern_b, key=lambda x: x['total_score'], reverse=True)[:10]
        
        total_main_count = len(pattern_a) + len(pattern_b)
        
        # 点数の下限保証
        if total_main_count >= min_required or retry_count >= 6:
            break
        
        # オッズフィルターのレンジを上下10%ずつ拡張
        adj_min *= 0.9
        adj_max *= 1.1
        retry_count += 1
        exclusion_log.append(f"再試行 {retry_count}: 下限点数未達のためレンジ拡張 ({adj_min:.1f}-{adj_max:.1f}倍)")

    # STEP2-2: ボーナス枠 (上限超えの最高スコア1点)
    bonus_item = None
    if bonus_candidates:
        bonus_item = sorted(bonus_candidates, key=lambda x: x['total_score'], reverse=True)[0]
        bonus_item['is_bonus'] = True
        bonus_item['type'] = 'Bonus'

    return {
        'pattern_a': pattern_a,
        'pattern_b': pattern_b,
        'bonus': bonus_item,
        'chaos_rank': chaos_rank,
        'odds_range': (round(adj_min, 1), round(adj_max, 1)),
        'exclusion_log': exclusion_log[:30],
        'base_count': len(df_filtered)
    }

def allocate_unified_budget(pool, total_budget):
    """
    統合買い目プールに対して、均等配分と端数調整を行う。
    """
    main_tickets = pool['pattern_a'] + pool['pattern_b']
    num_main = len(main_tickets)
    bonus_item = pool.get('bonus')
    bonus_budget = 100 if bonus_item else 0
    
    actual_total = 0
    unit_price = 0
    final_tickets = []

    if num_main > 0:
        available_budget = total_budget - bonus_budget
        if available_budget < num_main * 100:
            unit_price = 100
        else:
            unit_price = (available_budget // num_main // 100) * 100
        
        # 配分
        current_main_total = 0
        for t in main_tickets:
            t['amount'] = unit_price
            t['est_payout'] = int(t['amount'] * t['est_odds'])
            current_main_total += t['amount']
            
        # 端数処理: パターンAの1位（またはBの1位）に加算
        remainder = available_budget - current_main_total
        if remainder >= 100:
            main_tickets[0]['amount'] += (remainder // 100) * 100
            main_tickets[0]['est_payout'] = int(main_tickets[0]['amount'] * main_tickets[0]['est_odds'])
            current_main_total += (remainder // 100) * 100
        
        actual_total += current_main_total
        for t in main_tickets:
            t['type'] = 'A' if t in pool['pattern_a'] else 'B'
            final_tickets.append(t)

    # ボーナス追加 (メインがなくてもボーナスがあれば出す)
    if bonus_item:
        bonus_item['amount'] = 100
        bonus_item['est_payout'] = int(bonus_item['amount'] * bonus_item['est_odds'])
        actual_total += bonus_item['amount']
        final_tickets.append(bonus_item)
        
    return {
        'tickets': final_tickets,
        'actual_total': actual_total,
        'main_count': num_main,
        'unit_price': unit_price
    }
