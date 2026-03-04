import scraper
import calculator

race_id = "202605010811"
print(f"Testing Never Placed Logic on Race: {race_id}")
df = scraper.get_race_data(race_id)

if not df.empty:
    df = calculator.calculate_battle_score(df)
    
    print("\n--- Horses flagged as Never Placed (BOMB) ---")
    flagged = df[df['IsNeverPlaced'] == True]
    
    # Print condition details for manual review
    print("\n[Debug] Condition Details for All Horses:")
    for i, row in df.iterrows():
        # Re-evaluate locally just to print
        name = row['Name']
        jockey = str(row['Jockey'])
        top_jockeys = ["ルメール", "川田", "戸崎", "横山武", "松山", "岩田望", "武豊", "坂井", "鮫島克", "モレイラ", "レーン", "Ｍデム", "菅原明", "西村淳", "藤岡佑", "三浦", "田辺", "横山和", "丹内", "佐々木"]
        is_top = any(tj in jockey for tj in top_jockeys)
        d_pop = not is_top
        
        print(f"[{row['Umaban']}] {name}: jockey({jockey}, bot_pop={d_pop}) speed({row['OguraIndex']}, bot5=?) odds({row['Odds']}, bot5=?) battle({row['BattleScore']}, bot5=?) -> BOMB: {row['IsNeverPlaced']}")

    if not flagged.empty:
        for i, row in flagged.iterrows():
            print(f"[{row['Umaban']}] {row['Name']} - Jockey: {row['Jockey']}, "
                  f"Speed: {row['OguraIndex']:.1f}, "
                  f"Odds: {row['Odds']:.1f}, "
                  f"BattleScore: {row['BattleScore']:.1f}")
    print("\n--- Horses flagged as Death (SKULL) ---")
    death_flagged = df[df['Alert'] == '💀']
    if not death_flagged.empty:
        for i, row in death_flagged.iterrows():
            print(f"[{row['Umaban']}] {row['Name']} - Speed: {row['OguraIndex']:.1f}, BattleScore: {row['BattleScore']:.1f}")
    else:
        print("No horses flagged with SKULL.")
        
else:
    print("Failed to fetch data.")
