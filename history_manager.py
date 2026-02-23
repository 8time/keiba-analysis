import pandas as pd
import os
import sys
import scraper
from datetime import datetime

# Enforce UTF-8 output
# sys.stdout.reconfigure(encoding='utf-8')

HISTORY_FILE = "race_history.csv"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            return pd.read_csv(HISTORY_FILE, encoding='utf-8')
        except:
            return pd.DataFrame()
    return pd.DataFrame()

def save_race_data(df, race_id):
    """
    Saves analysis data to history CSV.
    Cols: RaceID, Date, RaceName, HorseName, OguraIndex, TimeIndexMax, Status, SiteIndex, ActualRank(initially NaN)
    """
    if df.empty:
        return

    # Load existing to check for duplicates
    existing_df = load_history()
    
    # Duplicate Check Mechanism
    if not existing_df.empty:
        # Check if this RaceID already exists
        if str(race_id) in existing_df['RaceID'].astype(str).unique():
            print(f"Skipping {race_id}: Already exists.")
            return "Duplicate"

    # Prepare DataFrame for saving
    save_df = df.copy()
    save_df['RaceID'] = str(race_id)
    
    # Date Processing
    # STRICT: Do not default to today if RaceDate is missing/None.
    r_date = None
    if 'RaceDate' in save_df.columns and pd.notna(save_df['RaceDate'].iloc[0]) and str(save_df['RaceDate'].iloc[0]).strip() != "":
        r_date = str(save_df['RaceDate'].iloc[0])
        save_df['Date'] = r_date
    else:
        # leave as None or set to empty
        save_df['Date'] = None
        
    # Split Date -> Year, Month, Day
    if r_date:
        try:
            # support both YYYY/MM/DD and YYYY-MM-DD
            r_date = r_date.replace("-", "/")
            dt = datetime.strptime(r_date, "%Y/%m/%d")
            save_df['Year'] = dt.year
            save_df['Month'] = dt.month
            save_df['Day'] = dt.day
            save_df['Date'] = r_date # ensure slash format
        except:
            save_df['Year'] = None
            save_df['Month'] = None
            save_df['Day'] = None
    else:
        save_df['Year'] = None
        save_df['Month'] = None
        save_df['Day'] = None

    # RaceNum
    # Infer from ID last 2 digits
    try:
         save_df['RaceNum'] = int(str(race_id)[-2:])
    except:
         save_df['RaceNum'] = 0

    # Ensure columns exist
    cols_to_keep = ['RaceID', 'Date', 'Year', 'Month', 'Day', 'RaceTitle', 'Venue', 'RaceNum', 'Distance', 'Condition', 'Name', 'OguraIndex', 'Status', 'SiteIndex', 'Popularity', 'Odds', 'Weight']
    
    # Handle missing cols efficiently
    for col in cols_to_keep:
        if col not in save_df.columns:
            save_df[col] = None
            
    # Add 'ActualRank' if not exists
    if 'ActualRank' not in save_df.columns:
        save_df['ActualRank'] = None
    
    # Add ResultOdds/Agari if not exists
    if 'ResultOdds' not in save_df.columns:
        save_df['ResultOdds'] = None
    if 'Agari' not in save_df.columns:
        save_df['Agari'] = None
        
    # Add Alert if not exists
    if 'Alert' not in save_df.columns:
        save_df['Alert'] = None
    if 'AlertText' not in save_df.columns:
        save_df['AlertText'] = None
        
    cols_to_keep_final = cols_to_keep + ['ActualRank', 'ResultOdds', 'Agari', 'Alert', 'AlertText']
    # Ensure they exist (handle if they were not in cols_to_keep)
    for c in ['ResultOdds', 'Agari', 'Alert', 'AlertText']:
        if c not in save_df.columns:
             save_df[c] = None

    final_df = save_df[cols_to_keep_final]
    
    # Append
    if not existing_df.empty:
        updated_df = pd.concat([existing_df, final_df], ignore_index=True)
    else:
        updated_df = final_df
        
    updated_df.to_csv(HISTORY_FILE, index=False, encoding='utf-8')
    print(f"Saved entry to {HISTORY_FILE}")
    return "Saved"

def register_past_races(race_ids):
    """
    Registers past races by fetching data AND results, then saving.
    """
    import calculator
    
    log = []
    
    # Pre-check duplicates to avoid wasted scraping?
    # Or rely on save_race_data to skip. 
    # Better to check inside save_race_data to keep logic centralized, 
    # BUT scraping takes time.
    # Let's check duplicate first.
    existing = load_history()
    existing_ids = []
    if not existing.empty:
        existing_ids = existing['RaceID'].astype(str).unique()
    
    for rid in race_ids:
        rid = rid.strip()
        if not rid: continue
        
        # Check Duplicate
        if str(rid) in existing_ids:
            log.append(f"⚠️ ID: {rid} は登録済みのため、重複を避けるためスキップしました。")
            continue
            
        # 1. Check Result Availability
        results = scraper.fetch_race_result(rid)
        if not results:
            log.append(f"❌ {rid}: No results found (or error).")
            continue
            
        # 2. Get Race Data (Pre-race info for index calc)
        df = scraper.get_race_data(rid)
        if df.empty:
            log.append(f"❌ {rid}: Could not fetch race metadata.")
            continue
            
        # 3. Calculate Index
        df = calculator.calculate_ogura_index(df)
        
        # 4. Merge Results
        # results is {Name: {Rank, ResultOdds, Agari}}
        ranks = []
        r_odds = []
        agaris = []
        
        for name in df['Name']:
            if name in results:
                data = results[name]
                ranks.append(data['Rank'])
                r_odds.append(data['ResultOdds'])
                agaris.append(data['Agari'])
            else:
                ranks.append(None)
                r_odds.append(None)
                agaris.append(None)
                
        df['ActualRank'] = ranks
        df['ResultOdds'] = r_odds
        df['Agari'] = agaris
        
        # 5. Save
        res = save_race_data(df, rid)
        if res == "Duplicate":
             log.append(f"⚠️ {rid}: Duplicate detected during save.")
        else:
             log.append(f"✅ {rid}: Registered successfully.")
        
    return log

def update_history_with_results():
    # ... (existing function kept for compatibility if needed, or we can use the pipeline) ...
    # We can keep it simple: Just refetch rank for existing IDs.
    # But now fetch_race_result returns dict. We need to adapt this function if we keep it.
    # Let's update it to use the new return format.
    
    df = load_history()
    if df.empty:
        return "No history found."
        
    race_ids = df['RaceID'].unique()
    updated_count = 0
    
    for rid in race_ids:
        results = scraper.fetch_race_result(rid) # Now returns dict of dicts
        if not results:
            continue
            
        mask = df['RaceID'].astype(str) == str(rid)
        rows_to_update = df[mask]
        
        for idx, row in rows_to_update.iterrows():
            if row['Name'] in results:
                # Update cols
                data = results[row['Name']]
                df.at[idx, 'ActualRank'] = data['Rank']
                if 'ResultOdds' in df.columns:
                     df.at[idx, 'ResultOdds'] = data['ResultOdds']
                if 'Agari' in df.columns:
                     df.at[idx, 'Agari'] = data['Agari']
                
                updated_count += 1
                
    if updated_count > 0:
        df.to_csv(HISTORY_FILE, index=False)
        return f"Updated {updated_count} records."
    else:
        return "No new results."
