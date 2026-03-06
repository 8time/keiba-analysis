import pandas as pd
from calculator import calculate_ogura_index

def test_logic():
    # Mock Data
    mock_data = [
        {
            'Name': 'Strong Horse (G1 Winner, Recent)',
            'Past_Runs': [
                {'Rank': 1, 'Grade': 'GI', 'IsRecent': True, 'RaceName': 'Arima Kinen'}, # 100 * 2 * 1.2 = 240
            ]
        },
        {
            'Name': 'Average Horse (G2, Recent)',
            'Past_Runs': [
                {'Rank': 1, 'Grade': 'GII', 'IsRecent': True, 'RaceName': 'Kyoto Kinen'}, # 100 * 1 * 1.2 = 120
            ]
        },
        {
            'Name': 'Good Old Horse (G1, Old)',
            'Past_Runs': [
                {'Rank': 1, 'Grade': 'GI', 'IsRecent': False, 'RaceName': 'Derby'}, # 100 * 2 * 1 = 200
            ]
        },
        {
            'Name': 'Weak Horse (Recent 10th)',
            'Past_Runs': [
                {'Rank': 10, 'Grade': None, 'IsRecent': True, 'RaceName': 'Maiden'}, # (100 - 45) = 55 * 1.2 = 66
            ]
        }
    ]
    
    df = pd.DataFrame(mock_data)
    df = calculate_ogura_index(df)
    
    print(df[['Name', 'OguraIndex']])

if __name__ == "__main__":
    test_logic()
