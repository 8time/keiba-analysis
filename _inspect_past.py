import scraper, calculator, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

RACE_ID = '202605010811'
df = scraper.get_race_data(RACE_ID)
if df.empty:
    print("Empty - race not found")
else:
    df = calculator.calculate_battle_score(df)
    print(f"Race: {df['RaceName'].iloc[0]}, venue={df['Venue'].iloc[0]}, dist={df['CurrentDistance'].iloc[0]}, surface={df['CurrentSurface'].iloc[0]}")
    print()
    for _, row in df.iterrows():
        name = row.get('Name', '?')
        uban = row.get('Umaban', '?')
        past = row.get('PastRuns', [])
        ogura = row.get('OguraIndex', 0)
        avg_pos = row.get('AvgPosition', 9)
        avg_agari = row.get('AvgAgari', 36)
        
        # Dist match at 1600m
        dist_runs = [r for r in past[:12] if abs(r.get('Distance', 0) - 1600) <= 200]
        dist_wins = sum(1 for r in dist_runs if r.get('Rank', 99) <= 3)
        
        # Surface (dirt = ダ)
        surf_runs = [r for r in past[:12] if 'ダ' in str(r.get('Surface', ''))]
        surf_wins = sum(1 for r in surf_runs if r.get('Rank', 99) <= 3)
        
        # How many past runs total
        total_past = len(past)
        
        cond0 = past[0].get('Condition', '?') if past else '?'
        surf0 = past[0].get('Surface', '?') if past else '?'
        
        print(f"{uban:2} {name[:8]}: Ogura={ogura:.1f} Pos={avg_pos:.1f} Agari={avg_agari:.1f} | distMatch={len(dist_runs)}({dist_wins}win) surfMatch={len(surf_runs)}({surf_wins}win) | surf0={surf0}")
