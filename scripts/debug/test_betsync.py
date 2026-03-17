import pandas as pd

def test_betsync_logic():
    print("Testing BetSync Logic...")
    
    # Constants
    ROKU_UNITS = [100, 200, 300, 400, 500, 600]
    TICKET_COUNT = {"3連複（15点）": 15, "馬連（5点）": 5}
    ROKU_THRESHOLDS = {
        "3連複（15点）": [0, 1500, 4500, 9000, 15000, 22500],
        "馬連（5点）": [0, 500, 1500, 3000, 5000, 7500],
    }

    # Session State Mock
    _ss = {
        'bs_bankroll': 20000,
        'bs_init_bet': 100,
        'bs_target': 50,
        'bs_strategy': "[稼働中] 6連サバイバル",
        'bs_ticket': "3連複（15点）",
        'bs_races': [
            {'win': False, 'ret': 0, 'decided': True},
            {'win': True, 'ret': 2000, 'decided': True},
            {'win': False, 'ret': 0, 'decided': False} # Pending
        ]
    }

    def _roku_step_from_deficit(deficit, thresholds):
        if deficit <= 0:
            return 0
        for i, t in enumerate(thresholds[1:], 1):
            if deficit <= t:
                return i
        return 6

    # Logic
    bankroll = _ss['bs_bankroll']
    init_bet = _ss['bs_init_bet']
    strategy = "6連法（サバイバル）" # Simplified for test
    ticket = _ss['bs_ticket']
    n_tickets = TICKET_COUNT[ticket]
    races = _ss['bs_races']

    computed = []
    cum_bet = 0
    cycle_deficit = 0

    decided_races = [r for r in races if r.get('decided', True)]

    for i, r in enumerate(races):
        if not r.get('decided', True):
            continue
        
        prev = computed[-1] if computed else None
        
        # Strategy Logic (Simplified)
        thresholds = ROKU_THRESHOLDS[ticket]
        step = _roku_step_from_deficit(cycle_deficit, thresholds)
        step = min(step, 5)
        unit = ROKU_UNITS[step]

        bet = unit * n_tickets
        cum_bet += bet
        ret = r.get('ret', 0) if r['win'] else 0
        cycle_deficit = cycle_deficit + bet - ret

        overall_profit = sum((rr.get('ret', 0) if rr['win'] else 0) for rr in decided_races[:len(computed)+1]) - cum_bet
        balance = bankroll + overall_profit

        if ret == 0: result_type = "MISS"
        elif ret > bet: result_type = "PLUS"
        else: result_type = "GAMI"

        if cycle_deficit <= 0: cycle_deficit = 0

        computed.append({
            'race_idx': i,
            'win': r['win'],
            'unit': unit,
            'step': step,
            'bet': bet,
            'cum_bet': cum_bet,
            'ret': ret,
            'profit': overall_profit,
            'balance': balance,
            'cycle_deficit': cycle_deficit,
            'result_type': result_type,
        })
        print(f"Race {i+1}: Result={result_type}, Unit={unit}, Profit={overall_profit}, Balance={balance}")

    # Next race calc
    _th = ROKU_THRESHOLDS[ticket]
    _nd_step = min(_roku_step_from_deficit(cycle_deficit, _th), 5)
    _nd_unit = ROKU_UNITS[_nd_step]
    _nd_bet = _nd_unit * n_tickets
    print(f"Next Race: Step={_nd_step+1}, Unit={_nd_unit}, Bet={_nd_bet}")

    print("Test finished successfully.")

if __name__ == "__main__":
    test_betsync_logic()
