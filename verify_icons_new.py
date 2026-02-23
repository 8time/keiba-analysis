import pandas as pd
import calculator

def verify_icons():
    # Mock data with diverse OguraIndex values
    data = [
        {'Name': 'Horse A', 'OguraIndex': 85.0, 'AgariRank': 2, 'PastRuns': []},
        {'Name': 'Horse B', 'OguraIndex': 82.0, 'AgariRank': 1, 'PastRuns': []},
        {'Name': 'Horse C', 'OguraIndex': 80.0, 'AgariRank': 3, 'PastRuns': []},
        {'Name': 'Horse D', 'OguraIndex': 75.0, 'AgariRank': 4, 'PastRuns': []},
        {'Name': 'Horse E', 'OguraIndex': 70.0, 'AgariRank': 5, 'PastRuns': []},
        {'Name': 'Horse F', 'OguraIndex': 65.0, 'AgariRank': 6, 'PastRuns': []},
        {'Name': 'Horse G', 'OguraIndex': 60.0, 'AgariRank': 7, 'PastRuns': []},
        {'Name': 'Horse H', 'OguraIndex': 55.0, 'AgariRank': 8, 'PastRuns': []},
        {'Name': 'Horse I', 'OguraIndex': 50.0, 'AgariRank': 9, 'PastRuns': []},
        {'Name': 'Horse J', 'OguraIndex': 45.0, 'AgariRank': 10, 'PastRuns': []},
    ]
    
    df = pd.DataFrame(data)
    # Mock current distance for BattleScore calculation
    df['CurrentDistance'] = 1600
    
    # Run calculation
    # Note: calculate_battle_score also calls calculate_ogura_index internally, 
    # but here we provide OguraIndex manually to test the icon logic specifically.
    df = calculator.calculate_battle_score(df)
    
    # Sort for display as the app does
    print(df[['Name', 'OguraIndex', 'BattleScore', 'AgariRank', 'Alert']])

if __name__ == "__main__":
    verify_icons()
