import pandas as pd
import sys
import os
import argparse
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core import scraper
from scripts.signals import pipeline, models

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="20260321", help="Target date YYYYMMDD")
    parser.add_argument("--venue", default="06", help="Venue code (e.g. 06 for Nakayama)")
    args = parser.parse_args()

    date_str = args.date
    v_code = args.venue
    
    # Get races for venue
    races = scraper.get_race_list_for_date(date_str)
    venue_races = [r for r in races if r['race_id'].startswith(date_str[0:4] + v_code)]
    
    if not venue_races:
        print(f"No races found for date {date_str} and venue {v_code}")
        return
        
    print(f"--- Phase 6: Single venue regression test ---")
    print(f"Venue: {v_code} / Number of races: {len(venue_races)}")
    
    total_entries = 0
    missing_trainers = 0
    missing_jockeys = 0
    
    entries = []
    
    for r in venue_races:
        rid = r['race_id']
        print(f"Scraping {rid}...")
        df = scraper.get_race_data(rid)
        if df.empty:
            continue
            
        total_entries += len(df)
        
        for idx, row in df.iterrows():
            trainer = row.get('Trainer')
            jockey = row.get('Jockey')
            
            if not trainer or trainer in ('-', '不明', ''):
                missing_trainers += 1
            if not jockey or jockey in ('-', '不明', ''):
                missing_jockeys += 1
                
            entries.append(models.Entry(
                date=date_str,
                venue=v_code,
                race_id=rid,
                race_number=int(rid[-2:]),
                field_size=len(df),
                horse_number=int(row.get('Umaban', 0)),
                horse_name=str(row.get('Name', '')),
                jockey=str(jockey),
                trainer=str(trainer),
                odds=float(row.get('Odds', 0.0)),
                odds_rank=int(row.get('Popularity', 99))
            ))
            
    print(f"\n--- Validation Results ---")
    print(f"Total Entries: {total_entries}")
    print(f"Missing Trainers: {missing_trainers} ({missing_trainers/max(1,total_entries)*100:.1f}%)")
    print(f"Missing Jockeys: {missing_jockeys} ({missing_jockeys/max(1,total_entries)*100:.1f}%)")
    
    # Run pipeline
    print(f"\n--- Running Pipeline ---")
    result_entries = pipeline.run_special_signal_pipeline(entries)
    
    # Group results
    dc_trainer_count = sum(1 for e in result_entries if e.trainer_double_circle_flag)
    bt_trainer_count = sum(1 for e in result_entries if e.trainer_bullet_flag)
    
    print(f"Entries with Trainer ◎ : {dc_trainer_count}")
    print(f"Entries with Trainer ● : {bt_trainer_count}")
    
if __name__ == "__main__":
    main()
