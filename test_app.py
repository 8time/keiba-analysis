import pandas as pd
import sys
import os
import traceback

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from core import scraper, calculator

def test():
    try:
        df = scraper.get_race_data('202606020701')
        print(f"Shapes initially: {df.shape}")
        
        # Test app.py logic
        df = calculator.calculate_battle_score(df)
        df = calculator.calculate_n_index(df)
        print(f"Shapes after basic calculation: {df.shape}")
        
        # Odds missing logic
        _pop_missing = 'Popularity' in df.columns and (pd.to_numeric(df['Popularity'], errors='coerce') >= 99).any()
        _odds_missing = 'Odds' in df.columns and ((pd.to_numeric(df['Odds'], errors='coerce') <= 0) | (pd.to_numeric(df['Odds'], errors='coerce') >= 9999.0)).any()
        print(f"Pop missing: {_pop_missing}, Odds missing: {_odds_missing}")
        
        chaos_data = calculator.evaluate_race_chaos_v3(df)
        print(f"Chaos logic OK: {bool(chaos_data)}")
        
        # Test derived column creation
        from datetime import datetime
        def calc_derived_cols(target_df):
            res = target_df.copy()
            if 'Popularity' in res.columns and 'Odds' in res.columns:
                gap_df = res.sort_values('Popularity').copy()
                gap_df['PrevOdds'] = gap_df['Odds'].shift(1)
                gap_df['OddsGap'] = gap_df.apply(lambda r: "⚠断層" if r['PrevOdds'] > 0 and r['Odds']/r['PrevOdds'] >= 1.5 else "-", axis=1)
                res = res.merge(gap_df[['Umaban', 'OddsGap']], on='Umaban', how='left')
            else:
                res['OddsGap'] = "-"
            
            risks, corners, weight_raw, prev_agari, jockey_flag = [], [], [], [], []
            current_surf = str(res['CurrentSurface'].iloc[0]) if 'CurrentSurface' in res.columns and not res.empty else "芝"
            for _, row in res.iterrows():
                p_runs = row.get('PastRuns', [])
                r_list, c_val, a_val, j_flag = [], "-", "-", "-"
                today_w = str(row.get('Weight', ''))
                w_val = today_w if today_w and today_w not in ('', '-', '発走前のため未公開') else "未公開"
                if p_runs:
                    last_run = p_runs[0]
                    c_val = last_run.get('Passing', "-")
                    a_val = f"{last_run.get('Agari', 0.0):.1f}" if last_run.get('Agari', 0.0) > 0 else "-"
                    current_jockey = str(row.get('Jockey', ''))
                    prev_jockey = str(last_run.get('PrevJockey', ''))
                    if current_jockey and prev_jockey and current_jockey != prev_jockey and prev_jockey != "-":
                        j_flag = "乗替"
                    if 'ダ' in current_surf and not any('ダ' in str(pr.get('Surface', '')) for pr in p_runs): r_list.append("初ダ")
                    try:
                        last_date = datetime.strptime(last_run.get('Date', '2000.01.01'), "%Y.%m.%d")
                        if (datetime.now() - last_date).days > 180: r_list.append("休明")
                    except: pass
                risks.append(", ".join(r_list) if r_list else "-")
                corners.append(c_val)
                weight_raw.append(w_val)
                prev_agari.append(a_val)
                jockey_flag.append(j_flag)
            res['RiskFlags'], res['PrevCorners'], res['WeightHistory'], res['PrevAgari'], res['JockeyChange'] = \
                risks, corners, weight_raw, prev_agari, jockey_flag
            return res
            
        df = calc_derived_cols(df)
        print("Derived columns done.")
        
        # Test formatting
        view_df = df.copy()
        if 'Popularity' in df.columns:
            def fmt_pop_name(row):
                name = row['Name']
                try:
                    pop = int(row['Popularity'])
                    if pop <= 3: return f"{name} (🔥)"
                except: pass
                return name
            view_df['Name'] = view_df.apply(fmt_pop_name, axis=1)
            if 'Jockey' in view_df.columns:
                view_df = calculator.apply_jockey_icons(view_df)
                
        print("Display formatting done.")
        print("All processes succeeded!")
    except Exception as e:
        traceback.print_exc()

if __name__ == "__main__":
    test()
