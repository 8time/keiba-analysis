import math
import re

class RMHSAnalyzer:
    """
    R/M/H/S Theory Analyzer based on race result data.
    """
    
    @staticmethod
    def calculate_pace(first_half, second_half):
        """
        Classifies pace based on first and second half times.
        HIGH: diff <= -0.8
        SLOW: diff >= +0.8
        MID: otherwise
        """
        if not first_half or not second_half:
            return "UNKNOWN", 0.0
            
        pace_diff = first_half - second_half
        if pace_diff <= -0.8:
            return "HIGH", pace_diff
        elif pace_diff >= 0.8:
            return "SLOW", pace_diff
        else:
            return "MID", pace_diff

    @staticmethod
    def get_thresholds(field_size):
        """Returns drop_big and gain_big (rebound_big) thresholds."""
        if not field_size or field_size < 1:
            return 3, 3
        val = max(3, math.ceil(field_size * 0.20))
        return val, val

    @staticmethod
    def analyze_horse(horse_data, race_info):
        """
        Analyzes a single horse for R/M/H/S patterns.
        horse_data: {
            'umaban': int, 'finish_position': int, 'time': float, 
            'pos_1c': int, 'pos_2c': int, 'pos_3c': int, 'pos_4c': int,
            'sectional_last3f': float, 'last3f_rank': int
        }
        race_info: {
            'winner_time': float, 'field_size': int, 'pace_class': str, 
            'pace_diff': float, 'leaders': list, 'closers': list
        }
        """
        field_size = race_info.get('field_size', 0)
        winner_time = race_info.get('winner_time', 0.0)
        pace_class = race_info.get('pace_class', 'UNKNOWN')
        
        # 1. Delta Time
        delta_sec = horse_data.get('time', 0.0) - winner_time
        if horse_data.get('margin_sec') is not None:
            delta_sec = horse_data['margin_sec']
            
        within_limit = delta_sec <= 1.2
        
        res = {
            'umaban': horse_data.get('umaban'),
            'delta_sec': round(delta_sec, 2),
            'R': {'flag': False, 'score': 0, 'features': {}},
            'M': {'flag': False, 'score': 0, 'features': {}},
            'H': {'flag': False, 'score': 0, 'features': {}},
            'S': {'flag': False, 'score': 0, 'features': {}}
        }
        
        if not within_limit:
            return res # All theories require within 1.2s

        drop_th, gain_th = RMHSAnalyzer.get_thresholds(field_size)
        
        pos_list = [
            horse_data.get('pos_1c'), horse_data.get('pos_2c'),
            horse_data.get('pos_3c'), horse_data.get('pos_4c')
        ]
        pos_list = [p for p in pos_list if p is not None and p > 0]
        pos_4c = horse_data.get('pos_4c')
        finish_pos = horse_data.get('finish_position')
        
        if not pos_4c or not finish_pos:
             # Basic corner info missing
             for theory in ['R', 'M', 'H', 'S']:
                 res[theory]['flag'] = 'UNKNOWN'
             return res

        # --- R Theory ---
        # 1. delta_sec <= 1.2 (checked globally above)
        # 2. drop_amount >= drop_big
        # 3. rebound_amount >= rebound_big and rebound_amount > 0
        if len(pos_list) >= 2:
            # P = corner parsing list, excluding pos_4c for best_early
            early_positions = pos_list[:-1] # pos_1c, pos_2c, pos_3c as available
            
            if early_positions:
                best_early = min(early_positions)
                worst_mid = max(pos_list) # can include pos_4c
                drop_amount = worst_mid - best_early
                rebound_amount = pos_4c - finish_pos
                
                if drop_amount >= drop_th and rebound_amount >= gain_th and rebound_amount > 0:
                    res['R']['flag'] = True
                    res['R']['score'] = 85
                    res['R']['features'] = {
                        'best_early': best_early,
                        'worst_mid': worst_mid,
                        'drop_amount': drop_amount,
                        'pos_4c': pos_4c,
                        'finish_position': finish_pos,
                        'rebound_amount': rebound_amount,
                        'drop_big': drop_th,
                        'rebound_big': gain_th
                    }

        # --- M Theory ---
        # 1. 道中で大きく順位を上げている (例えば、gain_th以上の順位上昇)
        # 2. 最終着順が4角通過順位よりも悪い
        if len(pos_list) >= 2:
            advances = [pos_list[i] - pos_list[-1] for i in range(len(pos_list)-1)]
            max_advance = max(advances) if advances else 0
            fade = finish_pos > pos_4c
            if max_advance >= gain_th and fade:
                res['M']['flag'] = True
                res['M']['score'] = 80
                res['M']['features'] = {'max_advance': max_advance, 'fade_diff': finish_pos - pos_4c}

        # --- H Theory ---
        # 1. ペースがHIGH または UNKNOWN
        # 2. 4角が1〜4番手
        # 3. 4角4番手以内の馬の中で最先着
        if pace_class in ['HIGH', 'UNKNOWN']:
            if pos_4c <= 4:
                front_finish = race_info.get('front_finish', [])
                if front_finish and finish_pos == min(front_finish):
                    res['H']['flag'] = True
                    res['H']['score'] = 90
                    res['H']['features'] = {'pace': pace_class, 'pos_4c': pos_4c, 'finish_pos': finish_pos}

        # --- S Theory ---
        # 1. ペースがSLOW または UNKNOWN
        # 2. 4角順位が半分より後ろ
        # 3. 上がり3Fが1〜2位
        # 4. 1着ではない (2着以下)
        if pace_class in ['SLOW', 'UNKNOWN']:
            if pos_4c > field_size / 2:
                last3f_rank = horse_data.get('last3f_rank', 99)
                not_win = finish_pos > 1
                if last3f_rank <= 2 and not_win:
                    res['S']['flag'] = True
                    res['S']['score'] = 85
                    res['S']['features'] = {'pace': pace_class, 'last3f_rank': last3f_rank, 'finish_pos': finish_pos}

        return res

    @staticmethod
    def parse_passing(passing_str):
        """Parses '8-8-7-7' into [8, 8, 7, 7]."""
        if not passing_str or passing_str == 'UNKNOWN':
            return []
        parts = re.split(r'[,\-()]+', passing_str)
        return [int(p) for p in parts if p.strip().isdigit()]

    @staticmethod
    def analyze_past_run_for_r(run_data):
        """
        Scans a single past run dictionary for R-Theory matches.
        run_data should have: 'Passing' (str), 'Rank' (int), 'Margin'/'Time' (to derive delta_sec if possible)
        This uses a simplified threshold if field size is unknown (defaults to 3).
        """
        passing_str = run_data.get('Passing', '')
        pos_list = RMHSAnalyzer.parse_passing(passing_str)
        finish_pos = run_data.get('Rank', 99)
        field_size = run_data.get('FieldSize', 0) # if available
        
        # In past runs, we often only have Margin string, e.g. "0.6". Scraper doesn't extract absolute margin strictly yet for past runs.
        # We will assume past runs that are 2nd or worse are "惜敗" if they meet the strict drop/rebound.
        # Ideally, we should also enforce delta_sec <= 1.2 if we can parse it from run_data.
        
        if len(pos_list) < 2 or finish_pos == 99:
            return False
            
        drop_th, gain_th = RMHSAnalyzer.get_thresholds(field_size)
        
        early_positions = pos_list[:-1]
        pos_4c = pos_list[-1]
        
        if not early_positions:
            return False
            
        best_early = min(early_positions)
        worst_mid = max(pos_list)
        
        drop_amount = worst_mid - best_early
        rebound_amount = pos_4c - finish_pos
        
        # Fallback delta sec check if available in run_data. If not, we just rely on the shape.
        has_delta_limit = True
        if 'Margin' in run_data and run_data['Margin']:
            try:
                margin_val = float(run_data['Margin'])
                if margin_val > 1.2: has_delta_limit = False
            except: pass
            
        return (drop_amount >= drop_th) and (rebound_amount >= gain_th) and (rebound_amount > 0) and has_delta_limit
