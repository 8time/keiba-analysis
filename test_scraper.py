import sys
import scraper
import pandas as pd
import calculator

try:
    # 2026 Kyoto Kinen (Feb 15)
    # User requested test ID
    race_id = "202610010811" 
    print(f"Fetching data for race ID: {race_id}")
    df = scraper.get_race_data(race_id)
    
    df = calculator.calculate_battle_score(df)
    
    # --- Verify Alert Logic ---
    df = df.sort_values(by='BattleScore', ascending=False).reset_index(drop=True)
    total = len(df)
    cutoff = total - 8 if total >= 10 else total
    
    for i in range(total):
        df.at[i, 'Alert'] = ""
        r = df.at[i, 'AgariRank']
        trust = df.at[i, 'AgariTrust']
        
        if i < 2:
            df.at[i, 'Alert'] = "🎯◎"
        elif r == 1 and trust:
            df.at[i, 'Alert'] = "🚀(末脚)"
        elif i >= cutoff:
            df.at[i, 'Alert'] = "💀(消)"
            
    print("\n--- Detailed Stats ---")
    cols = ['Name', 'BattleScore', 'Alert', 'AvgAgari', 'AgariRank', 'AgariTrust']
    # Filter columns that exist
    cols = [c for c in cols if c in df.columns]
    
    # Sort by AgariRank to see who is #1
    df_agari = df.sort_values(by='AgariRank')
    
    for i, row in df_agari.iterrows():
        name = row['Name']
        # Safe print for name
        try:
             name_disp = name.encode('cp932', 'replace').decode('cp932')
        except:
             name_disp = "???"
             
        alert = row.get('Alert', '')
        # Remove unicode icons for printing if standard stdout
        alert_safe = alert.replace('🎯◎', '[Target]').replace('🚀(末脚)', '[Rocket]').replace('💀(消)', '[Delete]')
        
        
        print(f"Rank {row.get('AgariRank')}: [{row.get('Umaban')}] {name_disp} | Agari={row.get('AvgAgari')} | Pos={row.get('AvgPosition')} | Ogura={row.get('OguraIndex')} | Score={row.get('BattleScore')} | Alert={alert_safe}")

    # Debug Specific Target Horses for Calibration
    targets = [7, 9, 13, 16] 
    print("\n--- Target Calibration Data ---")
    for t in targets:
        rows = df[df['Umaban'].astype(str) == str(t)]
        if not rows.empty:
            r = rows.iloc[0]
            try: name_d = r['Name'].encode('cp932', 'replace').decode('cp932')
            except: name_d = r['Name']
            print(f"#{t} {name_d}: Ogura={r.get('OguraIndex')} | AvgAgari={r.get('AvgAgari')} | AvgPos={r.get('AvgPosition')} | BattleScore={r.get('BattleScore')}")
            
            # Print Past Runs
            if t in [7, 13]:
                print(f"   Past Runs for #{t}:")
                for run in r.get('PastRuns', []):
                     print(f"   - Date={run.get('Date')} Pos={run.get('Passing')} Agari={run.get('Agari')} (Raw: {run.get('Weight')})")
    print("ロジック修復完了")
except Exception as e:
    print(f"Error: {e}")
