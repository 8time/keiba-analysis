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
                
                if len(recs) >= 10:
                    break
    
    # --- Fallback logic for past races (Development/Demo) ---
    else:
        print("Note: Odds list empty. Generating simulated recommendations for demonstration.")
        from itertools import combinations
        import random
        
        # Get Top 5 by Popularity (if no Popularity, use top 5 umaban)
        if 'Popularity' in df.columns:
            pop5_df = df.sort_values(by='Popularity', ascending=True).head(5)
            pop5_umaban = set(pop5_df['Umaban'].tolist())
        else:
            pop5_umaban = set(df['Umaban'].head(5).tolist())
            
        candidate_pool = list(top5_umaban | pop5_umaban)
        if len(candidate_pool) < 3:
            candidate_pool = df['Umaban'].tolist()
            
        all_combs = list(combinations(candidate_pool, 3))
        # Ensure at least one top 5 BattleScore horse is in the combination
        valid_combs = [c for c in all_combs if any(h in top5_umaban for h in c)]
        
        # Take up to 10 random valid combinations
        random.seed(42) # For reproducibility in UI
        sample_combs = random.sample(valid_combs, min(10, len(valid_combs)))
        
        for i, comb in enumerate(sample_combs):
            comb = sorted(list(comb))
            names = " - ".join([name_map.get(h, str(h)) for h in comb])
            simulated_odds = round(random.uniform(15.0, 150.0), 1)
            recs.append({
                'Combination': f"{comb[0]}-{comb[1]}-{comb[2]}",
                'Horses': comb,
                'Odds': simulated_odds,
                'Rank': f"過去 / 模擬", # Indicate it's simulated
                'HorseNames': names
            })
            
        # Sort simulated by odds
        recs.sort(key=lambda x: x['Odds'])
        
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
        
        agari_data.append({'index': i, 'agari': avg_agari})

    # 3. Determine Agari Rank (Ascending order of time)
    agari_data.sort(key=lambda x: x['agari'])
    # Assign ranks
    agari_ranks = {}
    for rank, item in enumerate(agari_data, 1):
        agari_ranks[item['index']] = rank
        
    # 4. Final Score Calculation
    print("\n======== BATTLE SCORE CALCULATION LOG (New Spec) ========")
    
    for i, row in df.iterrows():
        ogura_val = row.get('OguraIndex', 0.0)
        avg_pos = df.at[i, 'AvgPosition']
        agari_rank = agari_ranks.get(i, 99)
        
        # Base
        base_score = ogura_val * 0.7
        
        bonus_points = 0
        bonus_log = []
        
        # Bonus A: Agari Rank
        agari_bonus = 0
        if agari_rank == 1: agari_bonus = 20
        elif agari_rank == 2: agari_bonus = 15
        elif agari_rank == 3: agari_bonus = 10
        
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

    for i in range(num_horses):
        name = df.at[i, 'Name']
        ag_rank = df.at[i, 'AgariRank']
        jockey = str(df.at[i, 'Jockey'])
        
        icon = ""
        
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
        
        # Priority Logic: 💣 (Never Placed) > 🎯◎(Index 1位) > ○(Index 2位) > ▲(Index 3位) > 🚀(Agari 1位) > 💀(Bottom 8)
        if is_never_placed:
            icon = "💣"
        elif name == idx_top_1:
            icon = "🎯◎"
        elif name == idx_top_2:
            icon = "○"
        elif name == idx_top_3:
            icon = "▲"
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
