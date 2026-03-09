import unittest
import pandas as pd
from core.odds_analyzer import OddsAnalyzer
import json

class TestOddsAnalyzer(unittest.TestCase):
    
    def setUp(self):
        self.analyzer = OddsAnalyzer()

    def test_detect_rank_diff(self):
        # Case: Show rank is 3+ better than Win rank
        data = {
            'Umaban': [1, 2, 3],
            'Win Odds': [10.0, 5.0, 20.0],
            'Popularity': [5, 2, 8], # Horse 1 is 5th favorite in Win
            'Show Odds (Min)': [2.0, 1.5, 4.0],
            'show_rank': [2, 1, 5]     # Horse 1 is 2nd favorite in Show
        }
        df = pd.DataFrame(data)
        alerts = self.analyzer.detect_abnormal_odds(df)
        
        # Horse 1: win_rank(5) - show_rank(2) = 3 -> show_abnormal
        h1_alerts = [a for a in alerts if a['horse_number'] == 1]
        self.assertTrue(any(a['alert_type'] == 'show_abnormal' for a in h1_alerts))
        print("Rank Diff Test: Passed")

    def test_detect_ratio_anomaly(self):
        # Case: Ratio >= 5.5 and Win >= 10.0
        data = {
            'Umaban': [8],
            'Win Odds': [18.0],
            'Popularity': [7],
            'Show Odds (Min)': [2.5], # 18.0 / 2.5 = 7.2 (ratio_abnormal)
            'show_rank': [4]
        }
        df = pd.DataFrame(data)
        alerts = self.analyzer.detect_abnormal_odds(df)
        
        h8_alerts = [a for a in alerts if a['horse_number'] == 8]
        self.assertTrue(any(a['alert_type'] == 'ratio_abnormal' for a in h8_alerts))
        print("Ratio Anomaly Test: Passed")

    def test_detect_sudden_drop(self):
        # Case: Drop >= 30%
        history_data = [
            {"umaban": 5, "odds_type": "win", "odds_value": 10.0, "timestamp": "2026-03-09 10:00:00"},
            {"umaban": 5, "odds_type": "win", "odds_value": 6.5, "timestamp": "2026-03-09 10:10:00"} # Drop = 35%
        ]
        history_df = pd.DataFrame(history_data)
        alerts = self.analyzer.analyze_time_series(history_df)
        
        h5_alerts = [a for a in alerts if a['horse_number'] == 5]
        self.assertTrue(any(a['alert_type'] == 'sudden_drop' for a in h5_alerts))
        print("Sudden Drop Test: Passed")

if __name__ == '__main__':
    unittest.main()
