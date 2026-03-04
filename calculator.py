import sys, io
try:
    # sys.stdout.reconfigure(encoding='utf-8')
    pass
except:
    pass

import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta

# Standard Times (Approximations) based on netkeiba usage
STANDARD_TIMES = {
    '芝': {
        1000: 57.5, 1200: 68.3, 1400: 81.0, 1600: 93.5,
        1800: 107.5, 2000: 120.0, 2200: 132.5, 2400: 145.5,
        2500: 152.0, 3000: 184.0, 3200: 198.0, 3400: 215.0
    },
    'ダ': {
        1000: 59.5, 1200: 71.8, 1400: 84.8, 1600: 98.5,
        1700: 105.5, 1800: 112.5, 1900: 119.0, 2000: 126.0, 
        2100: 133.0, 2400: 154.0
    }
}
DEFAULT_STD = STANDARD_TIMES['芝']

def calculate_solid_race(df):
    """Placeholder for Solid Race (Low Difficulty) logic."""
    return df

def calculate_predicted_difficulty(df):
    """
    Predicts race difficulty (Class S/A/B/C) based on score distribution (BattleScore or OguraIndex).
    - Class C (Solid): Large gap between 1st and 2nd.
    - Class A/S (Rough): Top 5 scores are closely packed (low standard deviation).
    - Class B (Normal): Intermediate state.
    """
    if df.empty or len(df) < 5:
        return "B"

    # Use BattleScore for distribution analysis
    scores = df.sort_values('BattleScore', ascending=False)['BattleScore'].head(5).values
    
    # 1. Class C (Solid/堅い)
    # If gap between 1st and 2nd is >= 10
    if (scores[0] - scores[1]) >= 10:
        return "C"
    
    # 2. Class A/S (Rough/荒れ)
    # Check standard deviation of top 5
    std_val = np.std(scores)
    
    if std_val < 2.0: # Extremely packed
        return "S"
    elif std_val < 4.0: # Packed
        return "A"
    
    return "B"

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
                # 1. Get Time (e.g. 1:12.3 -> 72.3)
                time_str = str(run.get('TimeStr', ''))
                if not time_str:
                    # Fallback to Time (seconds) if available
                    time_sec = float(run.get('Time', 0))
                else:
                    parts = time_str.split(':')
                    if len(parts) == 2:
                        time_sec = int(parts[0]) * 60 + float(parts[1])
                    else:
                        time_sec = float(parts[0])
                
                # 2. Get Distance & Surface
                dist = int(run.get('Distance', 0))
                surf = '芝' if '芝' in str(run.get('Surface', '')) else 'ダ'
                
                # 3. Get Standard Time
                std_times = STANDARD_TIMES.get(surf, {})
                std_time = std_times.get(dist)
                
                if std_time and time_sec > 0:
                    # DIY Index Calculation
                    val = (std_time - time_sec) * 0.8 + 50
                    index_vals.append(val)
                elif time_sec > 0:
                    # Fallback approach if distance-specific standard time is missing
                    # We can use a rough estimate: 1200m -> 72s approx, etc.
                    # Or just skip if we want high accuracy.
                    # User requested fallback: let's use a very rough one or just neutral 50.
                    index_vals.append(50.0) 
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
        if field_std == 0: field_std = 1.0
        
        for i, row in df.iterrows():
            a = row.get('_tmp_avg_agari')
            if pd.notna(a):
                # Standardized score: (mean - value) because lower agari is better
                t_score = 50 + 10 * (field_mean - a) / field_std
                df.at[i, 'DIY2_Index'] = round(t_score, 1)
            else:
                df.at[i, 'DIY2_Index'] = 50.0
    else:
        df['DIY2_Index'] = 50.0

    if '_tmp_avg_agari' in df.columns:
        df = df.drop(columns=['_tmp_avg_agari'])
        
    return df

def calculate_n_index(df):
    """
    N-Index Logic (2026-02-22):
    Points are calculated for the last 10 races + current race:
    - Popularity <= 3: +1 pt
    - G1 & Rank <= 3: +3 pts
    - G2 & Rank <= 3: +2 pts
    - G3 & Rank == 1: +1 pt
    - Time Index Rank <= 3 (Marker or Rank): +1 pt
    
    Final N-Index = Total Points
    """
    if df.empty:
        if 'NIndex' not in df.columns: df['NIndex'] = 0
        return df
    
    if 'NIndex' not in df.columns: df['NIndex'] = 0
    
    for i, row in df.iterrows():
        points = 0
        
        # 1. Current Race Data
        cur_pop = row.get('Popularity', 99)
        cur_ti_rank = row.get('TimeIndexRank', 99)
        
        if cur_pop <= 3: points += 1
        if cur_ti_rank <= 3: points += 1
        
        # 2. Past Races (Last 10)
        past = row.get('PastRuns', [])
        for run in past[:10]:
            r_rank = run.get('Rank', 99)
            r_pop = run.get('Popularity', 99)
            r_ti_rank = run.get('TimeIndexRank', 99)
            r_grade = str(run.get('Grade', 'OP')).upper()
            
            # Popularity
            if r_pop <= 3: points += 1
            
            # Time Index
            if r_ti_rank <= 3: points += 1
            
            # Grades
            if (r_grade == 'G1' or r_grade == 'GI') and r_rank <= 3:
                points += 3
            elif (r_grade == 'G2' or r_grade == 'GII') and r_rank <= 3:
                points += 2
            elif (r_grade == 'G3' or r_grade == 'GIII') and r_rank == 1:
                points += 1
                
        df.at[i, 'NIndex'] = points
        
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
    
    # Process actual odds if available
    if odds_list:
        for item in odds_list:
            horses = item['Horses']  # [h1, h2, h3]
            # Check if any horse in the combination is in top5_umaban
            if any(h in top5_umaban for h in horses):
                names = " - ".join([name_map.get(h, str(h)) for h in horses])
                item_copy = item.copy()
                item_copy['HorseNames'] = names
                recs.append(item_copy)
                
                if len(recs) >= 200:
                    break
                    
    return recs

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
            
            # Position
            p_str = str(run.get('Passing', '8'))
            try:
                match = re.search(r'^(\d+)', p_str)
                if match:
                    pos_vals.append(int(match.group(1)))
                else:
                    pos_vals.append(8)
            except:
                pos_vals.append(8)
                
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
    
    print("\n======== BATTLE SCORE CALCULATION LOG (New Spec) ========")
    
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
        
        # Save score breakdown for high-res logging
        df.at[i, 'ScoreBaseOgura'] = round(base_score, 1)
        df.at[i, 'ScoreTimeIndex'] = 0.0
        df.at[i, 'ScoreMakuri'] = 0.0
        df.at[i, 'ScoreTraining'] = 0.0
        df.at[i, 'ScoreWeight'] = 0.0
        df.at[i, 'ScoreBloodline'] = 0.0
        
        try:
             horse_name = df.at[i, 'Name']
             print(f"{horse_name}: Base({base_score:.1f}) + Bonus({bonus_points})[{', '.join(bonus_log)}] = {total_score:.1f}")
        except: pass

    print("====================================================\n")
    
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
        import scraper # Local import
        try:
            rid = temp_df['RaceID'].iloc[0] if 'RaceID' in temp_df.columns else None
            if rid:
                results = scraper.fetch_race_result(rid)
                if results:
                    mapped_odds = temp_df['Name'].map(lambda n: results.get(n, {}).get('ResultOdds', 0.0))
                    temp_df['Odds'] = mapped_odds
                    print(f"Debug [NeverPlaced]: Fetched odds for {len(results)} horses.")
        except Exception as e:
            print(f"Debug [NeverPlaced] Error fetching odds: {e}")

    temp_df['Odds'] = pd.to_numeric(temp_df['Odds'], errors='coerce').fillna(9999.0)
    temp_df.loc[temp_df['Odds'] == 0, 'Odds'] = 9999.0
    
    # Calculate Popularity from Odds to ensure it's always available (especially for past races)
    temp_df['Popularity'] = temp_df['Odds'].rank(method='min', ascending=True)
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
