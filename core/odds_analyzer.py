import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime

# UTF-8 Enforcement for Windows
import sys
# sys.stdout.reconfigure(encoding='utf-8') # Uncomment if running as standalone script

logger = logging.getLogger(__name__)

class OddsAnalyzer:
    """
    異常オッズ・大口投票（インサイダー）検知クラス
    """
    
    def __init__(self):
        pass

    def detect_abnormal_odds(self, df):
        """
        現在の DataFrame から異常数値を検知する (ロジックA & B)
        期待されるカラム: horse_number, win_odds, win_rank, show_odds_min, show_rank
        """
        alerts = []
        
        # カラム名のマッピング（入力に柔軟に対応するため）
        # app.py で使われているカラム名に合わせる
        mapping = {
            'Umaban': 'horse_number',
            'Win Odds': 'win_odds',
            'Popularity': 'win_rank',
            'Show Odds (Min)': 'show_odds_min',
            'Show Rank': 'show_rank' # これは calculator で計算する必要があるかもしれない
        }
        
        # 内部処理用にコピー
        working_df = df.copy()
        
        # 必要なカラムの存在確認と型変換
        try:
            # カラム名が Umaban 等の場合は変換
            for old, new in mapping.items():
                if old in working_df.columns:
                    working_df[new] = working_df[old]
            
            # 型変換
            cols_to_convert = ['win_odds', 'win_rank', 'show_odds_min']
            for col in cols_to_convert:
                if col in working_df.columns:
                    working_df[col] = pd.to_numeric(working_df[col], errors='coerce')
            
            # 複勝人気 (show_rank) がない場合は生成
            if 'show_rank' not in working_df.columns and 'show_odds_min' in working_df.columns:
                working_df['show_rank'] = working_df['show_odds_min'].rank(method='min', ascending=True)

            # 欠損値のある行を除外
            valid_df = working_df.dropna(subset=['win_odds', 'win_rank', 'show_odds_min', 'show_rank'])

            for _, row in valid_df.iterrows():
                h_num = int(row['horse_number'])
                w_odds = row['win_odds']
                w_rank = int(row['win_rank'])
                s_odds_min = row['show_odds_min']
                s_rank = int(row['show_rank'])
                
                # 1. 人気順位の乖離 (Rank Gap)
                rank_diff = w_rank - s_rank
                if rank_diff >= 3:
                    alerts.append({
                        "horse_number": h_num,
                        "alert_type": "show_abnormal",
                        "severity": "high",
                        "reason": f"複勝人気が単勝より{rank_diff}ランク高い (単:{w_rank}人気 -> 複:{s_rank}人気)"
                    })
                elif rank_diff <= -3:
                    alerts.append({
                        "horse_number": h_num,
                        "alert_type": "win_insider",
                        "severity": "medium",
                        "reason": f"単勝のみ異常に売れています (単:{w_rank}人気 -> 複:{s_rank}人気)"
                    })

                # 2. オッズ倍率の歪み (Ratio Anomaly)
                if s_odds_min > 0:
                    odds_ratio = w_odds / s_odds_min
                    
                    # 複勝ドカ売れ
                    if odds_ratio >= 5.5 and w_odds >= 10.0:
                        alerts.append({
                            "horse_number": h_num,
                            "alert_type": "ratio_abnormal",
                            "severity": "critical",
                            "reason": f"単複比率 {odds_ratio:.1f}倍の異常値 (単:{w_odds} / 複:{s_odds_min})。複勝への大口投票の可能性大。"
                        })
                    # 危険な人気馬
                    elif odds_ratio <= 1.8 and w_odds <= 5.0:
                        alerts.append({
                            "horse_number": h_num,
                            "alert_type": "danger_favorite",
                            "severity": "high",
                            "reason": f"過剰人気。単勝売れすぎに対し複勝が売れていません (比率:{odds_ratio:.1f}倍)。"
                        })
        
        except Exception as e:
            logger.error(f"Error in detect_abnormal_odds: {e}")
            
        return alerts

    def analyze_time_series(self, history_df):
        """
        時系列データから急落を検知する
        """
        alerts = []
        if history_df.empty:
            return alerts
            
        try:
            # タイムスタンプでソート
            df = history_df.copy()
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values(['umaban', 'timestamp'])
            
            for umaban in df['umaban'].unique():
                h_df = df[df['umaban'] == umaban]
                if len(h_df) < 2:
                    continue
                
                # 最新と最古（または一定時間前）を比較
                # ここでは最新の2つの記録を比較する
                latest = h_df.iloc[-1]
                previous = h_df.iloc[-2]
                
                # 単勝の急落をチェック
                if latest['odds_type'] == 'win' and previous['odds_type'] == 'win':
                    l_val = latest['odds_value']
                    p_val = previous['odds_value']
                    
                    if p_val > 0:
                        drop_rate = (p_val - l_val) / p_val
                        if drop_rate >= 0.3: # 30%以上の下落
                            alerts.append({
                                "horse_number": int(umaban),
                                "alert_type": "sudden_drop",
                                "severity": "critical",
                                "reason": f"直近で単勝オッズが急落！ {p_val} -> {l_val} (下落率: {drop_rate*100:.1f}%)"
                            })
                            
        except Exception as e:
            logger.error(f"Error in analyze_time_series: {e}")
            
        return alerts

def export_alerts_to_json(alerts, file_path):
    """
    アラート結果をJSONとして出力する
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(alerts, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to export alerts: {e}")
        return False
