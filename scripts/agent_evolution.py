# -*- coding: utf-8 -*-
"""🧬 エージェント進化シミュレーション — scripts/agent_evolution.py

2025年の全レースを時系列で回し、エージェントに予想→結果→学習→淘汰を繰り返させる。

仕組み:
  1. 各エージェントに仮想資金10万円
  2. 1レースずつ予想（◎○▲）を出す
  3. 結果と照合して仮想ベット精算（複勝ベース）
  4. 外れたら「なぜ外れたか」をLLMで振り返り→教訓を蓄積
  5. 資金ゼロ以下のエージェントは死亡（消滅）→新エージェント誕生
  6. 10レースごとに全員で失敗分析討論
  7. 生き残ったエージェントの教訓 = 自然淘汰で残った知識

Usage:
  python scripts/agent_evolution.py --n-agents 5 --max-races 100 --year 2025
  python scripts/agent_evolution.py --resume  # 前回の続きから
"""
import os
import sys
import json
import time
import sqlite3
import argparse
import random
import re
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from core.agent_forum import (
    generate_agents, _build_system_with_knowledge, _ollama_chat,
    load_horse_history, build_race_prompt,
    _parse_confidence, check_ollama, OLLAMA_MODEL,
    _STYLES, _FOCUS,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JV_DB = os.path.join(_ROOT, 'data', 'jravan.db')
_STATE_FILE = os.path.join(_ROOT, 'data', 'agent_evolution_state.json')
_LEDGER_FILE = os.path.join(_ROOT, 'data', 'agent_evolution_ledger.json')

INITIAL_BANKROLL = 100_000
BET_AMOUNT = 1_000
DEATH_THRESHOLD = 0
REFLECT_PROBABILITY = 0.3
GROUP_REVIEW_INTERVAL = 10


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DB queries
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _get_races(year=2025, jyo=None, limit=None):
    con = sqlite3.connect(f'file:{_JV_DB}?mode=ro', uri=True, timeout=10)
    q = '''SELECT DISTINCT ra.race_id, ra.race_key, ra.race_name, ra.surface, ra.kyori,
                  ra.jyo, ra.shusso_tosu, ra.baba_shiba, ra.baba_dirt, ra.tenko,
                  ra.kigo, ra.juryo, ra.grade
           FROM races ra
           WHERE ra.year = ? AND ra.shusso_tosu >= 5
    '''
    params = [year]
    if jyo:
        q += ' AND ra.jyo = ?'
        params.append(jyo)
    q += ' ORDER BY ra.race_id'
    if limit:
        q += f' LIMIT {int(limit)}'
    rows = con.execute(q, params).fetchall()
    con.close()
    return rows


def _get_race_csv(race_key):
    """レースの出走馬をCSV形式で取得（事前情報のみ = リーク防止）。"""
    con = sqlite3.connect(f'file:{_JV_DB}?mode=ro', uri=True, timeout=10)
    rows = con.execute('''
        SELECT r.umaban, r.bamei, r.ninki, r.win_odds, r.futan, r.bataiju, r.zogen,
               r.ato3f, r.corner3, r.corner4, r.chakujun,
               h.sire, h.bms
        FROM results r
        LEFT JOIN horses h ON r.ketto_num = h.ketto_num
        WHERE r.race_key = ? AND r.ninki > 0
        ORDER BY r.umaban
    ''', (race_key,)).fetchall()
    con.close()
    if not rows:
        return '', [], []

    lines = ['馬番,馬名,人気,単勝オッズ,斤量,馬体重,増減,父,母父']
    results_top3 = []
    all_results = []
    for r in rows:
        uma, name, nk, odds, futan, weight, zogen, a3f, c3, c4, chaku, sire, bms = r
        f_s = f'{futan/10:.0f}' if futan else ''
        w_s = str(weight) if weight else ''
        z_s = str(zogen) if zogen else ''
        o_s = f'{odds:.1f}' if odds else ''
        # CSV行は事前情報のみ（上がり3F = 結果データなのでCSVからは除外）
        lines.append(f'{uma},{name},{nk},{o_s},{f_s},{w_s},{z_s},{sire or ""},{bms or ""}')
        all_results.append({
            'umaban': uma, 'name': name, 'pop': nk, 'chakujun': chaku,
            'odds': odds, 'agari': a3f,
        })
        if chaku and chaku <= 3:
            results_top3.append({
                'umaban': uma, 'name': name, 'pop': nk, 'odds': odds,
            })

    return '\n'.join(lines), results_top3, all_results


def _get_fuku_odds(race_key, umaban):
    """複勝オッズを取得。なければ人気からざっくり推定。"""
    con = sqlite3.connect(f'file:{_JV_DB}?mode=ro', uri=True, timeout=10)
    row = con.execute(
        "SELECT payout FROM payouts WHERE race_key=? AND bet_type='複勝' LIMIT 1",
        (race_key,)).fetchone()
    con.close()
    if row and row[0]:
        return max(row[0] / 100, 1.1)
    return 2.0


def _get_payouts(race_key):
    con = sqlite3.connect(f'file:{_JV_DB}?mode=ro', uri=True, timeout=10)
    rows = con.execute(
        "SELECT bet_type, payout FROM payouts WHERE race_key=? AND bet_type='3連複'",
        (race_key,)).fetchall()
    con.close()
    return rows[0][1] if rows else 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# prediction / settlement
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _parse_prediction(text):
    picks = {}
    for mark, key in [('◎', 'honmei'), ('○', 'taikou'), ('▲', 'anaume')]:
        m = re.search(rf'{mark}\s*(\d+)\s*番', text)
        if not m:
            m = re.search(rf'{mark}(\d+)', text)
        if m:
            picks[key] = int(m.group(1))
    picks['confidence'] = _parse_confidence(text)
    return picks


def _settle_bet(picks, top3_umaban):
    """◎が3着内なら複勝的中。配当は一律2倍（簡易）。"""
    honmei = picks.get('honmei')
    if not honmei:
        return 0, 'no_pick'
    if honmei in set(top3_umaban):
        return BET_AMOUNT, 'hit_fuku'
    return -BET_AMOUNT, 'miss'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# reflection / discussion
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _reflect(agent, picks, top3, all_results, model=None):
    """外れた場合、LLMに1行反省を生成させる。"""
    honmei = picks.get('honmei')
    winner = next((r for r in all_results if r.get('chakujun') == 1), None)
    if not winner:
        return ''
    sys_prompt = (
        f'あなたは{agent["name"]}。予想を外した。'
        'なぜ外れたか30文字以内で1行反省し、次回の教訓を1つ述べよ。合計60文字以内。'
    )
    user_prompt = (
        f'あなたの◎: {honmei}番→3着外\n'
        f'勝ち馬: {winner["name"]}({winner.get("pop",0)}人気)\n'
        f'3着内: {[f"{r["name"]}({r["pop"]}人気)" for r in top3]}'
    )
    reply = _ollama_chat(sys_prompt, user_prompt, model=model, timeout=60)
    return (reply or '').strip()[:80]


def _group_review(alive_agents, recent_ledger, model=None):
    """10レース分の結果を全員で振り返り討論→全員に教訓を配る。"""
    if not recent_ledger:
        return

    summary_lines = []
    for entry in recent_ledger[-10:]:
        summary_lines.append(
            f'{entry["race_name"]}: 勝ち馬={entry["winner"]}({entry["winner_pop"]}人気) '
            f'3着内={entry["top3"]}'
        )
    summary = '\n'.join(summary_lines)

    sys_prompt = (
        'あなたは競馬予想の評論家。直近10レースの結果を見て、全体的な傾向を分析せよ。'
        '人気馬vs穴馬、コースバイアス、騎手傾向など。50文字以内で3つの教訓を箇条書きで。'
    )
    reply = _ollama_chat(sys_prompt, f'直近結果:\n{summary}', model=model, timeout=60)
    if not reply:
        return

    lesson = reply.strip()[:120]
    print(f'\n  📋 グループ振り返り: {lesson[:60]}...')

    for ag in alive_agents:
        ag['lessons'].append(f'[全体]{lesson[:60]}')
        ag['lessons'] = ag['lessons'][-20:]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# agent lifecycle
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _spawn_new_agent(gen_counter):
    style = random.choice(_STYLES)
    focus = random.choice(_FOCUS)
    truth = random.choice(['none', 'minimal', 'full'])
    return {
        'id': f'evo_{gen_counter}',
        'name': f'新生{gen_counter}号',
        'trip': f'◆Evo{gen_counter:03d}',
        'icon': '🌱',
        'truth_level': truth,
        'system': (f'あなたは競馬予想エージェント「新生{gen_counter}号」。'
                   f'{focus}を重視。口調は{style}。'
                   '人気順に従うな。データから独自の視点を出せ。'),
        'bankroll': INITIAL_BANKROLL,
        'wins': 0,
        'losses': 0,
        'lessons': [],
        'alive': True,
    }


def _init_agents(n_agents):
    """generate_agentsからシリアライズ可能な形に変換。"""
    raw = generate_agents(n_agents)
    out = []
    for ag in raw:
        out.append({
            'id': ag['id'],
            'name': ag['name'],
            'trip': ag['trip'],
            'icon': ag['icon'],
            'bankroll': INITIAL_BANKROLL,
            'wins': 0,
            'losses': 0,
            'lessons': [],
            'alive': True,
            'truth_level': ag.get('truth_level', 'minimal'),
            'system': ag['system'],
        })
    return out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# persistence
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_state():
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_state(state):
    with open(_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def save_ledger(ledger):
    with open(_LEDGER_FILE, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, ensure_ascii=False, indent=1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# main simulation loop
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_simulation(n_agents=5, max_races=50, year=2025, model=None, resume=False):
    if not check_ollama():
        print('ERROR: Ollama not running')
        return

    state = load_state() if resume else None
    if state:
        agents_state = state['agents']
        processed = set(state.get('processed_races', []))
        gen_counter = state.get('gen_counter', 100)
        ledger = state.get('ledger', [])
        deaths = state.get('deaths', 0)
        births = state.get('births', 0)
        print(f'Resuming: {len(processed)} races done, '
              f'{sum(1 for a in agents_state if a["alive"])} agents alive')
    else:
        agents_state = _init_agents(n_agents)
        processed = set()
        gen_counter = 100
        ledger = []
        deaths = 0
        births = 0

    races = _get_races(year, limit=max_races)
    total = len(races)
    print(f'Simulation: {total} races, {len(agents_state)} agents, '
          f'bankroll={INITIAL_BANKROLL:,}円')
    print('=' * 70)

    race_count = 0
    t_start = time.time()

    for race in races:
        race_id, race_key, race_name, surface, dist, jyo, n_horses, *_ = race
        if race_id in processed:
            continue

        csv_text, top3, all_results = _get_race_csv(race_key)
        if not csv_text or not top3:
            processed.add(race_id)
            continue

        race_count += 1
        top3_umaban = [r['umaban'] for r in top3]
        winner = next((r for r in all_results if r.get('chakujun') == 1), {})

        meta_text = f'{race_name} {surface}{dist}m @{jyo}'
        meta = {'jyo': jyo, 'surface': surface, 'distance': str(dist)}

        alive_agents = [a for a in agents_state if a['alive']]
        if not alive_agents:
            print('\n💀 ALL AGENTS DEAD. Simulation over.')
            break

        elapsed_min = (time.time() - t_start) / 60
        print(f'\n[{race_count}/{total}] {race_id} {meta_text} ({n_horses}頭) '
              f'[{elapsed_min:.0f}min]')

        horse_history = load_horse_history(csv_text, max_runs=3)
        prompt = build_race_prompt(csv_text, meta_text, horse_history)

        for ag in alive_agents:
            # 教訓をsystem promptに注入
            lessons_text = ''
            if ag['lessons']:
                recent = ag['lessons'][-5:]
                lessons_text = ('\n\n【あなたの過去の教訓（外れから学んだこと）】\n'
                                + '\n'.join(f'・{l}' for l in recent))

            sys_prompt = ag['system'] + lessons_text
            sys_prompt += ('\n\n人気順に従うだけの予想は価値がない。データから独自の視点を出せ。'
                           '\n◎XX番(馬名)理由 / ○XX番(馬名)理由 / ▲XX番(馬名)理由 + 自信度XX%')

            reply = _ollama_chat(sys_prompt, prompt, model=model, timeout=90)
            if not reply:
                continue

            picks = _parse_prediction(reply)
            pnl, result_type = _settle_bet(picks, top3_umaban)
            ag['bankroll'] += pnl

            if result_type == 'hit_fuku':
                ag['wins'] += 1
                symbol = '✅'
            elif result_type == 'miss':
                ag['losses'] += 1
                symbol = '❌'
                if random.random() < REFLECT_PROBABILITY:
                    lesson = _reflect(ag, picks, top3, all_results, model=model)
                    if lesson:
                        ag['lessons'].append(lesson)
                        ag['lessons'] = ag['lessons'][-20:]
            else:
                symbol = '⚪'

            honmei = picks.get('honmei', '?')
            conf = picks.get('confidence', 50)
            print(f'  {symbol} {ag["icon"]}{ag["name"]}: ◎{honmei}番 conf={conf}% '
                  f'残金{ag["bankroll"]:,}円 ({ag["wins"]}W{ag["losses"]}L)')

            if ag['bankroll'] <= DEATH_THRESHOLD and ag['alive']:
                ag['alive'] = False
                deaths += 1
                print(f'  💀 {ag["name"]} 死亡！'
                      f'（{ag["wins"]}W{ag["losses"]}L 教訓{len(ag["lessons"])}件）')
                if ag['lessons']:
                    print(f'    遺言: {ag["lessons"][-1]}')

                gen_counter += 1
                new_ag = _spawn_new_agent(gen_counter)
                agents_state.append(new_ag)
                births += 1
                print(f'  🌱 {new_ag["name"]} 誕生！')

        ledger.append({
            'race_id': race_id,
            'race_name': race_name,
            'top3': top3_umaban,
            'winner': winner.get('name', ''),
            'winner_pop': winner.get('pop', 0),
        })
        processed.add(race_id)

        # 定期グループ振り返り
        if race_count % GROUP_REVIEW_INTERVAL == 0:
            _group_review(alive_agents, ledger, model=model)

        # 定期保存
        if race_count % 10 == 0:
            save_state({
                'agents': agents_state,
                'processed_races': list(processed),
                'gen_counter': gen_counter,
                'ledger': ledger,
                'deaths': deaths,
                'births': births,
            })
            alive_n = sum(1 for a in agents_state if a['alive'])
            print(f'\n  💾 SAVED: {race_count}R | alive={alive_n} '
                  f'deaths={deaths} births={births}')

    # 最終保存
    save_state({
        'agents': agents_state,
        'processed_races': list(processed),
        'gen_counter': gen_counter,
        'ledger': ledger,
        'deaths': deaths,
        'births': births,
    })
    save_ledger(ledger)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 結果サマリー
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    elapsed_total = (time.time() - t_start) / 60
    print('\n' + '=' * 70)
    print(f'SIMULATION COMPLETE: {race_count} races in {elapsed_total:.1f}min')
    print(f'Deaths: {deaths} / Births: {births}')

    print('\n🏆 SURVIVORS (ranked by bankroll):')
    alive = sorted([a for a in agents_state if a['alive']],
                   key=lambda a: -a['bankroll'])
    for rank, a in enumerate(alive, 1):
        total_bets = a['wins'] + a['losses']
        wr = a['wins'] / max(total_bets, 1) * 100
        roi = (a['bankroll'] - INITIAL_BANKROLL) / max(total_bets * BET_AMOUNT, 1) * 100
        print(f'  #{rank} {a["icon"]} {a["name"]}: {a["bankroll"]:,}円 '
              f'({a["wins"]}W{a["losses"]}L 的中率{wr:.0f}% ROI{roi:+.0f}%) '
              f'教訓{len(a["lessons"])}件')
        if a['lessons']:
            for l in a['lessons'][-3:]:
                print(f'    → {l}')

    if deaths > 0:
        print(f'\n💀 DEAD ({deaths}体):')
        dead = [a for a in agents_state if not a['alive']]
        for a in dead:
            print(f'  {a["icon"]} {a["name"]}: {a["wins"]}W{a["losses"]}L '
                  f'教訓{len(a["lessons"])}件')

    # 最優秀エージェントの教訓を別ファイルに保存
    if alive:
        best = alive[0]
        best_lessons_file = os.path.join(_ROOT, 'data', 'best_agent_lessons.json')
        with open(best_lessons_file, 'w', encoding='utf-8') as f:
            json.dump({
                'name': best['name'],
                'bankroll': best['bankroll'],
                'wins': best['wins'],
                'losses': best['losses'],
                'lessons': best['lessons'],
                'simulation': {
                    'year': year,
                    'races': race_count,
                    'deaths': deaths,
                    'births': births,
                },
            }, f, ensure_ascii=False, indent=2)
        print(f'\n📝 Best agent lessons saved to {best_lessons_file}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Agent Evolution Simulation')
    parser.add_argument('--n-agents', type=int, default=5)
    parser.add_argument('--max-races', type=int, default=50)
    parser.add_argument('--year', type=int, default=2025)
    parser.add_argument('--model', type=str, default=None)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()

    run_simulation(
        n_agents=args.n_agents,
        max_races=args.max_races,
        year=args.year,
        model=args.model,
        resume=args.resume,
    )
