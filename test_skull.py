import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import scraper
import calculator

df = scraper.get_race_data("202608020605")
df = calculator.calculate_battle_score(df)

speed_bottom8 = set(df.sort_values('OguraIndex', ascending=True).head(8)['Name'].tolist())
battle_bottom8 = set(df.sort_values('BattleScore', ascending=True).head(8)['Name'].tolist())
pop_top8_set = set(df.sort_values('Odds', ascending=True).head(8)['Name'].tolist())

for num in df['Name'].tolist():
    if num in ['ピアリッツ', 'モナート', 'エイシンイクサボシ']:
        print(f"Horse: {num}")
        print(f"  Speed in Bottom8: {num in speed_bottom8}, Battle in Bottom8: {num in battle_bottom8}")
        print(f"  Top 8 Popular (Odds): {num in pop_top8_set}")
        row = df[df['Name'] == num].iloc[0]
        # Skip alert to avoid encoding errors
        print(f"  Odds: {row.get('Odds', '')}, OguraIndex: {row.get('OguraIndex', '')}, BattleScore: {row.get('BattleScore', '')}")
