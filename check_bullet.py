import pandas as pd
import io

df = pd.read_csv('result.csv', encoding='utf-8-sig')
bullet_horses = df[df['trainer_bullet_flag'] == True]
print(f"Total entries with bullet: {len(bullet_horses)}")
print(bullet_horses[['date', 'trainer', 'race_number', 'horse_name', 'special_marks']].to_string())
