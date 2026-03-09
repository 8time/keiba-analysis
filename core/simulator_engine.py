
import pandas as pd
import numpy as np
import kagglehub
from kagglehub import KaggleDatasetAdapter
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class BacktestSimulator:
    def __init__(self, initial_capital=100000):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.history = []
        self.dataset_id = "noriyukifurufuru/japan-horse-racing-2010-2025"
        
    def load_data(self, start_date=None, end_date=None, bet_type='単勝'):
        """Kaggle からデータをロードしてシミュレーション用に整形する"""
        try:
            logger.info("ROBUST_PD_READ_MODE: Enabled (manual pd.read_csv with on_bad_lines=skip)")
            logger.info(f"Downloading/Loading dataset for {bet_type}...")
            # データセットのダウンロード（ローカルパス取得）
            dataset_path = kagglehub.dataset_download(self.dataset_id)
            
            # 堅牢な読み込み用ヘルパー
            def read_csv_safe(filename):
                full_path = os.path.join(dataset_path, filename)
                # エラー回避のため on_bad_lines='skip' を追加
                return pd.read_csv(
                    full_path, 
                    encoding='utf-8', 
                    on_bad_lines='skip', 
                    engine='python'
                )

            # 各CSVの読み込み
            df_races = read_csv_safe("keiba_races.csv")
            df_results = read_csv_safe("keiba_results.csv")
            df_payouts = read_csv_safe("keiba_payouts.csv")
            
            # 日付フィルタ
            df_races['date'] = pd.to_datetime(df_races['date'], errors='coerce')
            if start_date:
                df_races = df_races[df_races['date'] >= pd.to_datetime(start_date)]
            if end_date:
                df_races = df_races[df_races['date'] <= pd.to_datetime(end_date)]
            
            # 馬券種フィルタ
            df_target_payouts = df_payouts[df_payouts['bet_type'] == bet_type].copy()
            
            # レース情報と結果をマージ
            df = df_results.merge(df_races[['race_id', 'date', 'race_class', 'distance', 'course_type']], on='race_id', how='inner')
            
            # 払戻情報のマージ
            if bet_type in ['単勝', '複勝']:
                df_target_payouts['horse_num'] = pd.to_numeric(df_target_payouts['horse_num'], errors='coerce')
                df = df.merge(
                    df_target_payouts[['race_id', 'horse_num', 'payout']], 
                    left_on=['race_id', 'number'], 
                    right_on=['race_id', 'horse_num'], 
                    how='left'
                )
            else:
                # 3連複などの場合は race_id 単位で払戻を取得
                df_race_payouts = df_target_payouts.groupby('race_id').first().reset_index()
                df = df.merge(
                    df_race_payouts[['race_id', 'payout']], 
                    on='race_id', 
                    how='left'
                )
            
            df['payout'] = df['payout'].fillna(0)
            df = df.sort_values(['date', 'race_id', 'number']).reset_index(drop=True)

            # 詳細分析（PastRuns）用に全結果データを保持
            self.full_results = df_results.merge(df_races[['race_id', 'date', 'race_class', 'distance', 'course_type']], on='race_id', how='inner')
            
            return df
        except Exception as e:
            logger.error(f"Error loading Kaggle data directly: {e}")
            raise e

    def _prepare_analysis_df(self, race_df):
        """Kaggleデータをアプリ分析形式に変換、過去走(PastRuns)を付与"""
        # calculator.py が期待するカラム名に統一
        analysis_df = race_df.copy()
        analysis_df = analysis_df.rename(columns={
            'horse_name': 'Name',
            'number': 'Umaban',
            'odds': 'Odds',
            'popularity': 'Popularity',
            'distance': 'CurrentDistance',
            'course_type': 'CurrentSurface',
            'jockey_name': 'Jockey',
            'race_id': 'RaceID'
        })

        # 各馬の過去走を構築
        past_runs_all = []
        for _, row in analysis_df.iterrows():
            horse_id = row['horse_id']
            race_date = row['date']
            
            # 当該馬の過去の結果を取得
            horse_history = self.full_results[
                (self.full_results['horse_id'] == horse_id) & 
                (self.full_results['date'] < race_date)
            ].sort_values('date', ascending=False).head(10)

            past_runs = []
            for _, h in horse_history.iterrows():
                try:
                    # タイム(例 1:32.8) を秒に変換
                    t_str = str(h['time'])
                    t_sec = 0
                    if ':' in t_str:
                        m, s = t_str.split(':')
                        t_sec = int(m) * 60 + float(s)
                    else:
                        t_sec = float(t_str)

                    past_runs.append({
                        'Rank': int(h['rank']) if str(h['rank']).isdigit() else 99,
                        'Grade': str(h['race_class']),
                        'Date': h['date'].strftime('%Y.%m.%d'),
                        'Time': t_sec,
                        'Distance': int(h['distance']),
                        'Surface': str(h['course_type']),
                        'Margin': float(h['margin']) if pd.notna(h['margin']) else 0.0,
                        'Weight': float(h['weight']),
                        'Agari': float(h['last_3f']) if pd.notna(h['last_3f']) else 35.0,
                        'Passing': str(h['passing']),
                        'TimeIndexRank': 99 # 不明
                    })
                except: continue
            past_runs_all.append(past_runs)
        
        analysis_df['PastRuns'] = past_runs_all
        return analysis_df

    def classify_race(self, race_df):
        if race_df.empty: return "unknown"
        try:
            # odds を数値に変換（エラーは NaN になり、min() で無視される）
            odds_series = pd.to_numeric(race_df['odds'], errors='coerce')
            fav_odds = odds_series.min()
            if pd.isna(fav_odds): return "unknown"
        except: return "unknown"
        
        if fav_odds < 2.5: return "solid"
        elif fav_odds >= 3.5: return "rough"
        else: return "standard"

    def run_simulation(self, df, strategy='fixed', bet_type='単勝', n_tickets=1, init_unit=100, race_filter='all'):
        from core import calculator
        self.capital = self.initial_capital
        self.history = []
        
        # 戦略ごとの内部状態
        cycle_deficit = 0
        _3d_seq = [1, 1, 1]
        _win_seq = []
        _win_consec_loss = 0
        current_unit = init_unit
        
        # 定数 (6連法)
        ROKU_UNITS = [100, 200, 300, 400, 500, 600]
        ROKU_THRESHOLDS = {
            "3連複": [0, 1500, 4500, 9000, 15000, 22500],
            "馬連": [0, 500, 1500, 3000, 5000, 7500],
            "ワイド": [0, 300, 900, 1800, 3000, 4500],
            "default": [0, 1000, 3000, 6000, 10000, 15000]
        }
        
        race_groups = df.groupby('race_id', sort=False)
        
        for race_id, race_df in race_groups:
            if self.capital <= 0: break
            
            # --- アプリロジックによる分析実行 (app_logic 用) ---
            analysis_df = None
            if strategy == 'app_logic_top5' or race_filter != 'all':
                analysis_df = self._prepare_analysis_df(race_df)
                analysis_df = calculator.calculate_battle_score(analysis_df)
            
            # レース質フィルタ (calculator.evaluate_race_chaos を使用)
            if race_filter != 'all' and analysis_df is not None:
                chaos_res = calculator.evaluate_race_chaos_v2(analysis_df)
                race_type = chaos_res['rank'] # S, A, B, C
                if race_filter == 'solid' and race_type not in ['B', 'C']: continue
                if race_filter == 'rough' and race_type not in ['S', 'A']: continue
            else:
                # 簡易判定
                race_type = self.classify_race(race_df)
                if race_filter == 'solid' and race_type != 'solid': continue
                if race_filter == 'rough' and race_type != 'rough': continue
            
            # 結果データの準備（着順を馬番キーの辞書にする）
            actual_results = dict(zip(race_df['number'].astype(int), race_df['rank'].astype(str)))
            winning_trio = sorted([k for k, v in actual_results.items() if str(v) in ['1', '2', '3']])
            
            # --- 戦略に基づくユニット・買い目決定 ---
            is_hit = False
            win_amount = 0
            bet = 0
            strategy_detail = ""

            if strategy == 'app_logic_top5':
                # 分析結果の上位5頭を使用
                top5_umaban = analysis_df.sort_values('BattleScore', ascending=False).head(5)['Umaban'].tolist()
                bet = init_unit * n_tickets
                
                if bet_type == '単勝':
                    target = top5_umaban[0]
                    is_hit = (str(actual_results.get(target, 99)) == '1')
                elif bet_type == '複勝':
                    target = top5_umaban[0]
                    is_hit = (str(actual_results.get(target, 99)) in ['1', '2', '3'])
                elif bet_type == '3連複':
                    # top5 ボックス想定 (10点)
                    from itertools import combinations
                    box_tickets = list(combinations(top5_umaban, 3))
                    # シミュレーター設定の点数に制限
                    box_tickets = box_tickets[:n_tickets]
                    bet = init_unit * len(box_tickets)
                    
                    for t in box_tickets:
                        if sorted(t) == winning_trio:
                            is_hit = True
                            payout_raw = float(race_df['payout'].iloc[0])
                            win_amount += (payout_raw / 100.0) * init_unit
                    strategy_detail = f"AppLogic(Top5Box {len(box_tickets)}点)"
                
                if bet_type in ['単勝', '複勝'] and is_hit:
                    payout_raw = float(race_df[race_df['number'] == top5_umaban[0]]['payout'].iloc[0])
                    win_amount = (payout_raw / 100.0) * init_unit
                
                strategy_detail = f"AppTop5({bet_type})" if not strategy_detail else strategy_detail

            elif strategy == 'pro_formation':
                # プロ仕様フォーメーション (固定予算 = init_unit * 15点分)
                target_budget = init_unit * 15
                res = calculator.calculate_pro_formation_betting(race_df, target_budget)
                
                if 'tickets' in res:
                    bet = res['actual_total_bet']
                    for t in res['tickets']:
                        # 的中判定 (3連複)
                        if sorted(t['horses']) == winning_trio:
                            is_hit = True
                            # Payout is per 100 units in Kaggle
                            payout_raw = float(race_df['payout'].iloc[0])
                            win_amount += (payout_raw / 100.0) * t['amount']
                    strategy_detail = f"ProForm({len(res['tickets'])}点)"
                else:
                    bet = 0
            else:
                # 従来戦略（単勝・複勝・軸1頭流し想定）
                target_horse = race_df.loc[race_df['odds'].idxmin()]
                
                if strategy == 'fixed':
                    unit = init_unit
                elif strategy == 'martingale':
                    unit = current_unit
                elif strategy == '3d_recovery':
                    _3d_mult = (_3d_seq[0] + _3d_seq[-1]) if len(_3d_seq) >= 2 else _3d_seq[0]
                    unit = max(100, (_3d_mult * (init_unit//2) // 100) * 100)
                elif strategy == 'winners':
                    if _win_seq:
                        unit = _win_seq[0] * 2 * 100
                    else: unit = 100
                elif strategy == 'roku_survival':
                    th = ROKU_THRESHOLDS.get(bet_type, ROKU_THRESHOLDS["default"])
                    step = min(_roku_step_from_deficit(cycle_deficit, th), 5)
                    unit = ROKU_UNITS[step]
                else:
                    unit = init_unit

                bet = unit * n_tickets
                
                # 的中判定
                if bet_type == '単勝':
                    is_hit = (target_horse['rank'] == 1 or target_horse['rank'] == '1')
                elif bet_type == '複勝':
                    is_hit = (target_horse['rank'] in [1, 2, 3, '1', '2', '3'])
                else:
                    is_hit = (target_horse['rank'] == 1 or target_horse['rank'] == '1')
                
                payout_raw = float(target_horse['payout']) if is_hit else 0
                win_amount = (payout_raw / 100.0) * unit
                strategy_detail = f"Unit:{unit}"

            if bet > self.capital: bet = self.capital
            if bet <= 0: continue

            net_profit = win_amount - bet
            self.capital += net_profit
            
            res_type = "MISS"
            if win_amount > 0:
                res_type = "PLUS" if win_amount > bet else "GAMI"

            # 状態更新 (pro_formationの場合も一旦マーチンゲール等のロジックを回すが、
            # 基本的には unit 固定または cycle_deficit 管理のみ)
            if strategy == 'martingale':
                if res_type == "MISS": current_unit *= 2
                else: current_unit = init_unit
            elif strategy == '3d_recovery' and strategy != 'pro_formation':
                # 3Dの状態更新ロジック... (略)
                pass 
            elif strategy == 'roku_survival':
                cycle_deficit = max(0, cycle_deficit + bet - win_amount)

            self.history.append({
                'race_id': race_id,
                'date': race_df['date'].iloc[0],
                'race_type': race_type,
                'bet': bet,
                'payout': win_amount,
                'profit': net_profit,
                'balance': self.capital,
                'hit': is_hit,
                'strategy_info': strategy_detail
            })

        return self.get_summary()

    def get_summary(self):
        if not self.history: return None
        hist_df = pd.DataFrame(self.history)
        total_bet = hist_df['bet'].sum()
        total_profit = hist_df['profit'].sum()
        max_drawdown = (hist_df['balance'].cummax() - hist_df['balance']).max()
        
        # 連敗計算
        hit_series = hist_df['hit']
        consecutive_losses = (hit_series == False).astype(int).groupby(hit_series.cumsum()).cumsum()
        max_losses = consecutive_losses.max()

        return {
            'initial_capital': self.initial_capital,
            'final_balance': self.capital,
            'total_profit': total_profit,
            'roi': (total_profit / total_bet * 100) if total_bet > 0 else 0,
            'hit_rate': (hist_df['hit'].sum() / len(self.history) * 100),
            'max_drawdown': max_drawdown,
            'max_consecutive_losses': max_losses,
            'race_count': len(self.history),
            'is_bankrupt': self.capital <= 0,
            'history_df': hist_df
        }

def _roku_step_from_deficit(deficit, thresholds):
    if deficit <= 0: return 0
    for i, t in enumerate(thresholds[1:], 1):
        if deficit <= t: return i
    return 6
