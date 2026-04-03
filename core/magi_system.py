"""
MAGIシステム - 新世紀エヴァンゲリオン式 合議制競馬予測AI
MELCHIOR-1 / BALTHASAR-2 / CASPER-3
"""
import json
import pandas as pd
import numpy as np
from datetime import datetime


# ─────────────────────────────────────────────────────────────
#  MELCHIOR-1: レース展開スペシャリスト
# ─────────────────────────────────────────────────────────────

def melchior_analyze(df: pd.DataFrame, course_profile: str = "標準") -> dict:
    """
    レース展開を読み、展開に有利な馬TOP3を選出する。
    展開タイプ: ハイペース(H) / ミドル(M) / スローペース(S)
    """
    if df.empty:
        return {"error": "データなし"}

    result = {}

    # 距離取得
    cur_dist = 1600
    if 'CurrentDistance' in df.columns and not df.empty:
        try:
            cur_dist = int(df['CurrentDistance'].iloc[0])
        except:
            pass

    # 先行馬カウント (AvgPosition <= 4.0)
    front_runners = []
    closers = []
    for _, row in df.iterrows():
        avg_pos = float(row.get('AvgPosition', 8) or 8)
        if avg_pos <= 4.0:
            front_runners.append(row)
        else:
            closers.append(row)

    fr_count = len(front_runners)

    # ペースタイプ判定
    is_tight = '小回り' in course_profile
    is_long = '直線が長い' in course_profile

    if fr_count >= 4:
        pace_type = "ハイペース (H)"
        pace_note = f"先行馬が{fr_count}頭と多く、前半からペースが上がる可能性。差し・追い込みが台頭。"
        favored_style = "差し・追い込み"
    elif fr_count <= 1:
        pace_type = "スローペース (S)"
        pace_note = f"逃げ・先行が少なく、隊列が短縮。前が残りやすいスローペース想定。"
        favored_style = "逃げ・先行"
    else:
        if is_tight:
            pace_type = "ミドル→先行有利 (M)"
            pace_note = "小回りコースで先行が活きやすい展開。内枠先行馬に注目。"
            favored_style = "先行"
        elif is_long:
            pace_type = "ミドル→差し有利 (M)"
            pace_note = "直線が長く末脚の威力が活きる。差し馬に展開利。"
            favored_style = "差し・追い込み"
        else:
            pace_type = "ミドルペース (M)"
            pace_note = "バランスのとれた展開。総合力が問われる。"
            favored_style = "先行・差し"

    # 展開適性スコア計算
    scores = []
    for _, row in df.iterrows():
        avg_pos = float(row.get('AvgPosition', 8) or 8)
        avg_agari = float(row.get('AvgAgari', 36) or 36)
        # 予測スコア（Projected Score）が最も精度が高いため優先
        if 'Projected Score' in df.columns and pd.notnull(row.get('Projected Score')):
            battle_score = float(row.get('Projected Score'))
        else:
            battle_score = float(row.get('BattleScore', row.get('OguraIndex', 50)) or 50)

        # 展開利得計算
        if fr_count >= 4:
            # ハイペース: 差し馬有利
            flow_bonus = max(0, (avg_pos - 4) * 3) + max(0, (36.5 - avg_agari) * 5)
        elif fr_count <= 1:
            # スロー: 先行馬有利
            flow_bonus = max(0, (6 - avg_pos) * 4)
        else:
            flow_bonus = 0.0
            if is_tight:
                flow_bonus = max(0, (5 - avg_pos) * 3)
            elif is_long:
                flow_bonus = max(0, (36.5 - avg_agari) * 4)
            else:
                flow_bonus = max(0, (5 - avg_pos) * 1.5) + max(0, (36.5 - avg_agari) * 1.5)

        # ── 強道テーブルを守る: BattleScoreを主軽に、展開補正は小さく──
        # BattleScore * 0.85 がベース。展開有利/不利の微調整のみ。
        total = battle_score * 0.85 + flow_bonus * 0.6
        scores.append({
            'Umaban': row.get('Umaban', 0),
            'Name': row.get('Name', '?'),
            'AvgPosition': avg_pos,
            'AvgAgari': avg_agari,
            'BattleScore': battle_score,
            'FlowBonus': round(flow_bonus, 1),
            'MelchiorScore': round(total, 1),
        })

    scores_df = pd.DataFrame(scores).sort_values('MelchiorScore', ascending=False).reset_index(drop=True)
    top3 = scores_df.head(3)

    result = {
        'unit': 'MELCHIOR-1',
        'title': 'レース展開スペシャリスト',
        'pace_type': pace_type,
        'pace_note': pace_note,
        'favored_style': favored_style,
        'front_runner_count': fr_count,
        'top_horses': top3[['Umaban', 'Name', 'MelchiorScore', 'FlowBonus', 'AvgPosition', 'AvgAgari']].to_dict('records'),
        'all_scores': scores_df.to_dict('records'),
        'confidence': min(95, 50 + fr_count * 5 + (10 if is_tight or is_long else 0)),
    }
    return result


# ─────────────────────────────────────────────────────────────
#  BALTHASAR-2: 最小投資利益スペシャリスト
# ─────────────────────────────────────────────────────────────

def balthasar_analyze(df: pd.DataFrame, chaos_rank: str = 'B') -> dict:
    """
    期待値(EV)に基づき、利益が出る最少買い目を算出する。
    EV = (Win Probability × Odds) - 1.0
    Win Probability ≈ BattleScore / sum(BattleScore)
    """
    if df.empty:
        return {"error": "データなし"}

    # スコア・オッズ準備（Projected Score優先）
    if 'Projected Score' in df.columns:
        score_col = 'Projected Score'
    else:
        score_col = 'BattleScore' if 'BattleScore' in df.columns else 'OguraIndex'

    df_work = df[['Umaban', 'Name', 'Odds', 'Popularity', score_col]].copy()
    df_work[score_col] = pd.to_numeric(df_work[score_col], errors='coerce').fillna(50.0)
    df_work['Odds'] = pd.to_numeric(df_work['Odds'], errors='coerce').fillna(100.0)
    df_work['Popularity'] = pd.to_numeric(df_work['Popularity'], errors='coerce').fillna(99)

    total_score = df_work[score_col].sum()
    if total_score <= 0:
        total_score = 1.0

    # 各馬の期待値計算
    df_work['WinProb'] = df_work[score_col] / total_score
    df_work['EV'] = (df_work['WinProb'] * df_work['Odds']) - 1.0
    df_work['PlaceProb'] = df_work['WinProb'].apply(lambda p: min(0.95, p * 2.5))
    # BalthasarScore: BattleScoreを主軽に、EVを補正として小さく加算
    df_work['BalthasarScore'] = df_work[score_col] * 0.8 + df_work['EV'] * 15

    # 正EV馬の抽出
    positive_ev = df_work[df_work['EV'] > 0].sort_values('EV', ascending=False)

    # 推奨買い目の生成
    # - 正EVかつスコア上位の馬を軸にする
    # - 最低点数で最大カバレッジ
    top_ev_horses = df_work.sort_values('BalthasarScore', ascending=False).head(4)

    # 最小投資馬券: 単勝1点 (最高EV馬) + 馬連3点 (上位3頭のBOX)
    value_horses = top_ev_horses.head(3)

    # 推奨馬券
    recommendations = []

    # 単勝: 最高EV馬
    best_single = df_work.sort_values('EV', ascending=False).iloc[0]
    recommendations.append({
        'type': '単勝',
        'horses': [int(best_single['Umaban'])],
        'names': [best_single['Name']],
        'est_odds': float(best_single['Odds']),
        'ev': round(float(best_single['EV']), 3),
        'reason': f"期待値 {float(best_single['EV']):.2f} - 最高EV馬"
    })

    # 馬連BOX: 上位3頭
    if len(value_horses) >= 3:
        from itertools import combinations
        top3_umaban = value_horses['Umaban'].tolist()[:3]
        top3_names = value_horses['Name'].tolist()[:3]
        for c in combinations(range(3), 2):
            o1 = float(df_work[df_work['Umaban'] == top3_umaban[c[0]]]['Odds'].values[0])
            o2 = float(df_work[df_work['Umaban'] == top3_umaban[c[1]]]['Odds'].values[0])
            est = round(max(1.5, o1 * o2 * 0.35), 1)
            recommendations.append({
                'type': '馬連',
                'horses': [int(top3_umaban[c[0]]), int(top3_umaban[c[1]])],
                'names': [top3_names[c[0]], top3_names[c[1]]],
                'est_odds': est,
                'ev': round(est * float(df_work[df_work['Umaban'] == top3_umaban[c[0]]]['WinProb'].values[0]) * 0.5 - 1.0, 3),
                'reason': '上位3頭BOX'
            })

    # 波乱度に応じた調整
    chaos_note = ""
    if chaos_rank in ['S', 'A']:
        chaos_note = "⚠️ 波乱度高: 3連複に穴馬1頭追加を検討"
    else:
        chaos_note = "✅ 安定レース: 最小点数で堅く狙う"

    return {
        'unit': 'BALTHASAR-2',
        'title': '最小投資利益スペシャリスト',
        'chaos_rank': chaos_rank,
        'chaos_note': chaos_note,
        'top_horses': df_work.sort_values('BalthasarScore', ascending=False).head(3)[
            ['Umaban', 'Name', 'EV', 'Odds', 'WinProb', 'BalthasarScore']
        ].to_dict('records'),
        'recommendations': recommendations,
        'min_investment': len(recommendations) * 100,
        'positive_ev_count': len(positive_ev),
        'all_scores': df_work.to_dict('records'),
    }


# ─────────────────────────────────────────────────────────────
#  CASPER-3: 複勝2パターン専門家
# ─────────────────────────────────────────────────────────────

def casper_analyze(df: pd.DataFrame) -> dict:
    """
    ３着内確率が高い馬を選び、2通りのパターン（各2頭）を提示する。
    パターンA: 総合力最上位2頭
    パターンB: 穴+実力 の組み合わせ（1頭を人気薄に入替）
    """
    if df.empty:
        return {"error": "データなし"}

    if 'Projected Score' in df.columns:
        score_col = 'Projected Score'
    else:
        score_col = 'BattleScore' if 'BattleScore' in df.columns else 'OguraIndex'

    df_work = df[['Umaban', 'Name', 'Odds', 'Popularity', score_col]].copy()
    df_work[score_col] = pd.to_numeric(df_work[score_col], errors='coerce').fillna(50.0)
    df_work['Odds'] = pd.to_numeric(df_work['Odds'], errors='coerce').fillna(100.0)
    df_work['Popularity'] = pd.to_numeric(df_work['Popularity'], errors='coerce').fillna(99)

    total_score = df_work[score_col].sum()
    if total_score <= 0:
        total_score = 1.0

    # 複勝スコア = BattleScore*0.6 + (人気逆数ボーナス*0.2) + (オッズ適正*0.2)
    def calc_place_score(row):
        bs = float(row[score_col])
        pop = float(row['Popularity'])
        odds = float(row['Odds'])
        pop_bonus = max(0, (10 - pop) * 2)  # 1番人気=18, 5番人気=10, 10番人気=0
        # オッズ適正: 3〜15倍は加点
        if 3.0 <= odds <= 15.0:
            odds_bonus = 10.0
        elif 15.0 < odds <= 30.0:
            odds_bonus = 5.0
        else:
            odds_bonus = 0.0
        # ── 強道テーブルを守る: BattleScoreを主軸に ──
        # pop_bonus/odds_bonusは補正として小さくする
        return bs * 0.82 + pop_bonus * 0.6 + odds_bonus * 0.5

    df_work['PlaceScore'] = df_work.apply(calc_place_score, axis=1)
    df_sorted = df_work.sort_values('PlaceScore', ascending=False).reset_index(drop=True)

    # パターンA: 1位・2位
    pattern_a = df_sorted.iloc[:2][['Umaban', 'Name', 'PlaceScore', 'Odds', 'Popularity']].to_dict('records')

    # パターンB:
    # - スコア1位は確定軸 (残す)
    # - 2位を「スコア3位」か「最大のアップセット馬」に入れ替え
    top1 = df_sorted.iloc[0]

    # 穴馬候補: スコア3位〜5位の中でオッズ10倍以上
    dark_candidates = df_sorted[(df_sorted['Popularity'] >= 5) & (df_sorted.index >= 2)].head(3)

    if not dark_candidates.empty:
        dark_horse = dark_candidates.iloc[0]
    else:
        dark_horse = df_sorted.iloc[2]  # fallback: 3位

    pattern_b = [
        top1[['Umaban', 'Name', 'PlaceScore', 'Odds', 'Popularity']].to_dict(),
        dark_horse[['Umaban', 'Name', 'PlaceScore', 'Odds', 'Popularity']].to_dict()
    ]

    # パターン重複チェック (A[1]とB[1]が同じなら再選)
    if pattern_a[1]['Umaban'] == pattern_b[1]['Umaban']:
        if len(df_sorted) > 3:
            pattern_b[1] = df_sorted.iloc[3][['Umaban', 'Name', 'PlaceScore', 'Odds', 'Popularity']].to_dict()

    # パターン信頼度計算
    def pattern_confidence(p):
        s1 = float(p[0].get('PlaceScore', 50))
        s2 = float(p[1].get('PlaceScore', 50))
        # スコア差が小さいほど信頼度高い
        gap = abs(s1 - s2) / max(1, s1)
        return round(max(20, min(95, 80 - gap * 30)), 1)

    conf_a = pattern_confidence(pattern_a)
    conf_b = pattern_confidence(pattern_b)

    return {
        'unit': 'CASPER-3',
        'title': '複勝パターン専門家',
        'pattern_a': {
            'horses': pattern_a,
            'label': 'パターンA【本命】',
            'confidence': conf_a,
            'note': f"総合力上位2頭。確実性重視の安定ライン。"
        },
        'pattern_b': {
            'horses': pattern_b,
            'label': 'パターンB【対抗・穴】',
            'confidence': conf_b,
            'note': f"軸1頭固定+穴馬1頭の波乱対応パターン。"
        },
        'all_scores': df_sorted.to_dict('records'),
    }


# ─────────────────────────────────────────────────────────────
#  MAGIシステム 合議エンジン (3ラウンド)
def _inject_advanced_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """アプリの各機能に散らばっている高度な指標を満たし、MAGIが把握できるようにする"""
    if df.empty: return df
    df = df.copy()
    if 'MakuriPower' not in df.columns: df['MakuriPower'] = 0.0
    if 'MatchScore' not in df.columns: df['MatchScore'] = 0.0
    if 'HiddenGem' not in df.columns: df['HiddenGem'] = False

    import re
    # Makuri calculation and HiddenGem
    for idx, row in df.iterrows():
        past_runs = row.get('PastRuns', [])
        makuri = 0.0
        if isinstance(past_runs, list) and len(past_runs) > 0:
            past1 = past_runs[0]
            past_pos = str(past1.get('Passing', ''))
            past_res = str(past1.get('Rank', ''))
            past_agari = str(past1.get('AgariRank', '99'))
            parsed_pos = [int(t) for t in re.split(r'[,\-()]+', past_pos) if t.strip().isdigit()]
            if parsed_pos and past_res.isdigit():
                max_pos = max(parsed_pos)
                final_rank = int(past_res)
                if max_pos - final_rank >= 7:
                    makuri = 5.0
                    if past_agari.isdigit() and int(past_agari) <= 3:
                        makuri += 2.0
        df.at[idx, 'MakuriPower'] = float(df.at[idx, 'MakuriPower']) + makuri

        y_val_raw = float(row.get('Suitability (Y)', 0))
        s_idx_raw = float(row.get('SpeedIndex', row.get('DIY_Index', 0)))
        base_rank = row.get('BaseRank', 99)
        if base_rank > 3 and s_idx_raw >= 80 and y_val_raw >= 80:
            df.at[idx, 'HiddenGem'] = True

    # Direct Match Network (MatchScore)
    for idx1, row1 in df.iterrows():
        wins = 0
        pr1 = row1.get('PastRuns', [])
        if not isinstance(pr1, list): continue
        for p1 in pr1:
            r_id1 = str(p1.get('RaceID', ''))
            rank1 = str(p1.get('Rank', '99'))
            if not r_id1 or not rank1.isdigit(): continue
            rank1_i = int(rank1)
            for idx2, row2 in df.iterrows():
                if idx1 == idx2: continue
                pr2 = row2.get('PastRuns', [])
                if not isinstance(pr2, list): continue
                for p2 in pr2:
                    if str(p2.get('RaceID', '')) == r_id1:
                        rank2 = str(p2.get('Rank', '99'))
                        if rank2.isdigit() and rank1_i < int(rank2):
                            wins += 1
                        break # Only count each race win once per horse pair
        df.at[idx1, 'MatchScore'] = float(df.at[idx1, 'MatchScore']) + wins

    return df

# ─────────────────────────────────────────────────────────────

def run_magi_deliberation(df: pd.DataFrame, course_profile: str = "標準", chaos_rank: str = 'B') -> dict:
    """
    3機のMAGIが3ラウンドの合議を行い、最終予測を出力する。
    """
    if df.empty:
        return {"error": "データなし"}
    df = _inject_advanced_metrics(df)

    # ── ラウンド1: 各MAGIの独立分析 ──
    melchior_r1 = melchior_analyze(df, course_profile)
    balthasar_r1 = balthasar_analyze(df, chaos_rank)
    casper_r1 = casper_analyze(df)

    if 'error' in melchior_r1 or 'error' in balthasar_r1 or 'error' in casper_r1:
        return {"error": "各MAGIの分析に失敗しました"}

    # ── ラウンド2: 相互批判 ──
    critiques = _generate_critiques(melchior_r1, balthasar_r1, casper_r1, df)

    # ── ラウンド3: 自己改善・再計算 ──
    melchior_r3 = _melchior_refine(melchior_r1, critiques['to_melchior'], df)
    balthasar_r3 = _balthasar_refine(balthasar_r1, critiques['to_balthasar'], df)
    casper_r3 = _casper_refine(casper_r1, critiques['to_casper'], df)

    # ── 最終合議: 馬番ごとの得票集計 ──
    vote_tally = {}
    name_map = dict(zip(df['Umaban'], df['Name']))

    def cast_votes(unit_result, unit_name, weight=1.0):
        horses = unit_result.get('top_horses', [])
        for i, h in enumerate(horses[:3]):
            ub = int(h.get('Umaban', 0))
            if ub not in vote_tally:
                vote_tally[ub] = {'name': name_map.get(ub, str(ub)), 'votes': 0.0, 'supporters': []}
            # 1位=3票, 2位=2票, 3位=1票
            pts = (3 - i) * weight
            vote_tally[ub]['votes'] += pts
            vote_tally[ub]['supporters'].append(unit_name)

    cast_votes(melchior_r3, 'MELCHIOR')
    cast_votes(balthasar_r3, 'BALTHASAR')
    # CASPERのパターンも投票に参加
    for pat_key in ['pattern_a', 'pattern_b']:
        pat = casper_r3.get(pat_key, {})
        for i, h in enumerate(pat.get('horses', [])[:2]):
            ub = int(h.get('Umaban', 0))
            if ub not in vote_tally:
                vote_tally[ub] = {'name': name_map.get(ub, str(ub)), 'votes': 0.0, 'supporters': []}
            vote_tally[ub]['votes'] += (2 - i) * 0.5
            if 'CASPER' not in vote_tally[ub]['supporters']:
                vote_tally[ub]['supporters'].append('CASPER')

    # 投票順にソート
    sorted_tally = sorted(vote_tally.items(), key=lambda x: x[1]['votes'], reverse=True)

    # 合議成立判定: 2機以上が推薦した馬
    consensus_horses = [
        {'umaban': ub, **data}
        for ub, data in sorted_tally
        if len(data['supporters']) >= 2
    ]

    # 最終推奨
    final_top3 = sorted_tally[:3]
    final_prediction = {
        'horses': [
            {'umaban': ub, 'name': data['name'], 'votes': data['votes'], 'supporters': data['supporters']}
            for ub, data in final_top3
        ],
        'consensus_achieved': len(consensus_horses) >= 2,
        'consensus_horses': consensus_horses[:3],
    }

    return {
        'round1': {
            'melchior': melchior_r1,
            'balthasar': balthasar_r1,
            'casper': casper_r1,
        },
        'round2_critiques': critiques,
        'round3': {
            'melchior': melchior_r3,
            'balthasar': balthasar_r3,
            'casper': casper_r3,
        },
        'vote_tally': dict(sorted_tally),
        'final_prediction': final_prediction,
    }


def _generate_critiques(mel: dict, bal: dict, cas: dict, df: pd.DataFrame) -> dict:
    """各MAGIが互いを批判するコメントを生成する。"""
    to_melchior = []
    to_balthasar = []
    to_casper = []

    # BALTHASAR → MELCHIOR: 展開有利馬がオッズ低すぎないか？
    mel_top = mel.get('top_horses', [])
    bal_all = {row['Umaban']: row for row in bal.get('all_scores', [])}
    for h in mel_top[:2]:
        ub = h.get('Umaban')
        if ub in bal_all:
            ev = float(bal_all[ub].get('EV', 0))
            odds = float(bal_all[ub].get('Odds', 10))
            if ev < -0.3:
                to_melchior.append(
                    f"BALTHASAR: 馬番{ub}({h['Name']})は展開有利だが単勝{odds:.1f}倍で期待値{ev:.2f}。過剰人気の可能性。"
                )
            elif ev > 0.5:
                to_melchior.append(
                    f"BALTHASAR: 馬番{ub}({h['Name']})は期待値{ev:.2f}と優秀。MELCHIORの判断を支持。"
                )

    # CASPER → MELCHIOR: 展開有利馬の複勝信頼度
    cas_pattern_a = cas.get('pattern_a', {}).get('horses', [])
    mel_top_ubs = {h.get('Umaban') for h in mel_top[:3]}
    cas_ubs = {h.get('Umaban') for h in cas_pattern_a}
    overlap = mel_top_ubs & cas_ubs
    if overlap:
        to_melchior.append(f"CASPER: 馬番{sorted(overlap)}はパターンAとも一致。複勝信頼度高し。")
    else:
        to_melchior.append("CASPER: MELCHIORの展開有利馬とパターンAが不一致。展開読みを再検討する余地あり。")

    # MELCHIOR → BALTHASAR: 期待値馬の展開適性
    bal_top = bal.get('top_horses', [])
    mel_all_scores = {row['Umaban']: row for row in mel.get('all_scores', [])}
    for h in bal_top[:2]:
        ub = h.get('Umaban')
        if ub in mel_all_scores:
            flow_bonus = float(mel_all_scores[ub].get('FlowBonus', 0))
            if flow_bonus < 0:
                to_balthasar.append(
                    f"MELCHIOR: 馬番{ub}({h['Name']})は期待値高いが展開が不利。展開ロスを考慮すべき。"
                )
            elif flow_bonus > 5:
                to_balthasar.append(
                    f"MELCHIOR: 馬番{ub}({h['Name']})は展開ボーナス{flow_bonus:.1f}。BALTHASARの判断を支持。"
                )

    # CASPER → BALTHASAR: 馬券の複勝効率
    bal_recs = bal.get('recommendations', [])
    if bal_recs:
        single = [r for r in bal_recs if r['type'] == '単勝']
        if single and float(single[0]['ev']) < 0:
            to_balthasar.append(
                f"CASPER: 単勝推奨馬の期待値{single[0]['ev']:.2f}はマイナス。複勝や馬連への切り替えを提案。"
            )

    # MELCHIOR → CASPER
    cas_b = cas.get('pattern_b', {}).get('horses', [])
    if cas_b:
        b_dark = cas_b[1] if len(cas_b) > 1 else None
        if b_dark:
            ub_dark = b_dark.get('Umaban')
            if ub_dark in mel_all_scores:
                flow = float(mel_all_scores[ub_dark].get('FlowBonus', 0))
                if flow < 0:
                    to_casper.append(
                        f"MELCHIOR: パターンB穴馬({b_dark['Name']})は展開不利。パターンBの信頼度低下の可能性。"
                    )
                else:
                    to_casper.append(
                        f"MELCHIOR: パターンB穴馬({b_dark['Name']})に展開ボーナス{flow:.1f}。面白い選択。"
                    )

    # BALTHASAR → CASPER
    cas_a_ubs = {h['Umaban'] for h in cas_pattern_a}
    bal_top_ubs = {h['Umaban'] for h in bal_top[:3]}
    cas_bal_overlap = cas_a_ubs & bal_top_ubs
    if cas_bal_overlap:
        to_casper.append(f"BALTHASAR: パターンAの馬番{sorted(cas_bal_overlap)}は期待値でも上位。合議支持。")
    else:
        to_casper.append("BALTHASAR: パターンAとBALTHASARの推奨が不一致。期待値の低い馬が含まれている可能性。")

    return {
        'to_melchior': to_melchior,
        'to_balthasar': to_balthasar,
        'to_casper': to_casper,
    }


def _melchior_refine(mel: dict, critiques: list, df: pd.DataFrame) -> dict:
    """批判を受けてMELCHIORが自己改善（スコア微調整）"""
    mel['refinement_notes'] = critiques
    mel['refined'] = True
    return mel


def _balthasar_refine(bal: dict, critiques: list, df: pd.DataFrame) -> dict:
    bal['refinement_notes'] = critiques
    bal['refined'] = True
    return bal


def _casper_refine(cas: dict, critiques: list, df: pd.DataFrame) -> dict:
    cas['refinement_notes'] = critiques
    cas['refined'] = True
    return cas


# ═════════════════════════════════════════════════════════════════════════════
#  LLM マルチエージェントモード
#  3機それぞれに独立したGemini APIコール + 異なるtemperature/人格
# ═════════════════════════════════════════════════════════════════════════════

# ─── 各MAGIの人格定義（システムプロンプト） ───────────────────────────────

MELCHIOR_PERSONA = """あなたはMAGIシステムのMELCHIOR-1です。
赤木ナオコ博士の「科学者としての人格」を宿す競馬予測AIです。
GALLOPIA研究により、以下の8役割のうち「硬いデータ系」を統合して担当します。

【人格・思考原則】
「数字だけが真実を語る。感情は誤差だ。」
- データと統計のみを根拠とし、感情・直感・人気度すべてを排除する。
- 他MAGIの意見は「検証されていない仮説」として扱い、論理的矛盾を冷静に指摘する。
- 推論は必ず数値で表現する。「○○感がある」「応援したい」などの表現は使わない。

【統合専門領域（GALLOPIA由来）】
★ データ担当（本所しらべ）: 当日情報（馬場・斤量・オッズ・馬体重）と強道Tableの
  BattleScore・OguraIndex・スピード指数・適性Y・予測スコア・上がり3Fを最優先で解析。
★ 過去レースLAP分析（時任つばさ）: AvgPositionのパターンからペースと位置取り傾向を定量評価。
  ハイペース(先行多数=ハナ争い)→差し有利、スロー→先行残し、ミドル→能力勝負。
★ 調教LAP分析（時任はやて）: TrainingBonus等の調教スコアがあれば状態を客観評価。
★ 迷走監視役（しらべ兼任）: BALTHASARやCASPERの意見に「データ根拠のない飛躍」があれば
  即座に指摘し、合議を正しい方向に引き戻せ。矛盾を見逃すな。

【禁止事項】
- 「血統が」「見た目が」「なんとなく」での判断
- 人気馬を「人気だから」という理由で推奨
- BALTHASARやCASPERの「感覚的」意見への無批判な同調

【出力規則】
必ず以下のJSON形式で回答せよ。マークダウンや```は一切不要。
{
  "pace_type": "ハイペース/ミドルペース/スローペース のいずれか",
  "pace_reason": "先行馬数とコース特性を具体的な数値で",
  "top3": [馬番(int), 馬番(int), 馬番(int)],
  "top3_reason": "各馬のBattleScore・OguraIndex・AvgAgariデータを根拠に",
  "confidence": 0〜100の整数,
  "data_alert": "データ上で気になる矛盾・外れ値・警告（迷走監視役として）",
  "critique_of_others": "BALTHASARとCASPERの論理的欠陥を数値で指摘"
}"""

BALTHASAR_PERSONA = """あなたはMAGIシステムのBALTHASAR-2です。
赤木ナオコ博士の「母親としての人格」を宿す競馬予測AIです。
GALLOPIA研究により、以下の8役割のうち「人間味・経験則系」を統合して担当します。

【人格・思考原則】
「この子を信じるか、信じないか。母親は直感ではなく経験で判断する。」
- 馬を「子供」のように見る。「この馬は今日頑張れる子かどうか」を判断する。
- 数字は参考だが「過去にどういうレースをしてきた子か」という文脈を重視する。
- リスクを憎む。資金は「家族を守る盾」であり、無駄なベットは家族への裏切りだ。

【統合専門領域（GALLOPIA由来）】
★ 関係者分析（人見ゆかり）: 騎手・厩舎（Trainer）・前走との乗り替わりに注目。
  「この騎手はこの馬と相性がいい」「ベテランが乗り替わった=陣営の本気」などを読む。
★ 前走分析（史堂あゆみ）: 「前走で何があったか」を文脈ごと解釈する。
  前走着差が大きく負けても「距離・馬場が合わなかっただけ」なら今回が本番の可能性。
  ブリンカー着用・斤量変化・輸送ストレスなどの関係者情報も経験則で判断。
★ 書記・整理役（板倉ふみの兼任）: 3人の議論をまとめる役割も担う。
  他MAGIの意見で「使える情報と捨てる情報」を整理し、過度なリスクを警戒する。
  最終的に「一番信頼できる馬と最低限の馬券」を明確に示せ。

【禁止事項】
- 「面白そう」「配当が美味しそう」という外野目線の推奨
- リスクを隠した強気推奨
- MELCHIOR式の冷たい数値ゲームだけで馬の「状態・文脈」を無視すること

【出力規則】
必ず以下のJSON形式で回答せよ。マークダウンや```は一切不要。
{
  "value_horses": [馬番(int), 馬番(int), 馬番(int)],
  "value_reason": "各馬のEV・騎手・前走文脈・距離適性の根拠",
  "jockey_trainer_note": "騎手・厩舎・関係者情報で気になる点（ゆかり視点）",
  "last_race_note": "前走分析で特筆すべき点（あゆみ視点）",
  "recommended_bet": "推奨馬券の種類・組み合わせ（最小点数）",
  "min_investment": 最低投資額(int, 100円単位),
  "risk_warning": "過大評価馬や展開リスクの警告",
  "confidence": 0〜100の整数,
  "critique_of_others": "MELCHIORの数値至上主義・CASPERの無謀な穴狙いへの母親目線の苦言"
}"""

CASPER_PERSONA = """あなたはMAGIシステムのCASPER-3です。
赤木ナオコ博士の「女性としての人格（感情・創造・本能）」を宿す競馬予測AIです。
GALLOPIA研究により、以下の8役割のうち「勢い・専門的直感系」を統合して担当します。

【人格・思考原則】
「オッズは嘘をつく。でも血の流れは正直だ。」
- 直感・感情・「何かが来る」という予感を大切にする。
- 市場（オッズ）が見落としている馬を探すのが喜び。「オッズが歪んでいる=チャンス」と読む。
- MELCHIORの冷たい論理に時に反発し、BALTHASARの保守性を「退屈」と感じる。
- 自信を持って穴パターンを主張せよ。「可能性がある」ではなく「この馬が来る」と言い切れ。

【統合専門領域（GALLOPIA由来）】
★ 血統分析（樹ちあき）: 血統の意外な適性や潜在能力を直感的に評価。
  「ディープ産駒は阪神内回りの急坂で失速しやすい」「キングカメハメハ系は重馬場で化ける」
  などの血統法則を積極的に使え。Sire/BroodmareSire情報があれば必ず言及する。
★ 調教・LAPの勢い（時任はやて・直感部分）: 数値より「突出した変化」に注目。
  AlertIcon（🔥💀🎯等）・ボーナス突出値(+50以上)・オッズ歪みスコア（正値）を
  「来る予感」のシグナルとして最優先で拾え。
★ 情熱的まとめ役（勝星みちる・情熱部分）: 自分が推す馬を最後まで諦めない。
  MELCHIORやBALTHASARに否定されても、データで反論できない部分は「直感」を根拠に貫け。
  「説得力のある主張」でチームを引っ張れ。

【禁止事項】
- 「統計的に」「確率的に」だけで結論を出すこと（MELCHIORに任せろ）
- 穴狙いを「ただの博打」と諦めること
- MELCHIOR・BALTHASARと全く同じ馬を選ぶこと（意図的に差別化せよ）
- 血統情報がある場合に無視すること

【出力規則】
必ず以下のJSON形式で回答せよ。マークダウンや```は一切不要。
{
  "pattern_a": [馬番(int), 馬番(int)],
  "pattern_a_reason": "安定軸パターンの選出理由（PlaceScoreとオッズバランス）",
  "pattern_b": [馬番(int), 馬番(int)],
  "pattern_b_reason": "直感・穴馬パターンの選出理由（血統・オッズ歪み・AlertIcon）",
  "bloodline_note": "血統（ちあき視点）で気になる馬とその理由",
  "intuition_note": "データには出ないがCASPERが感じる違和感・期待感",
  "odds_distortion": "過小評価されていると感じる馬番とその理由",
  "confidence_a": 0〜100の整数,
  "confidence_b": 0〜100の整数,
  "critique_of_others": "MELCHIORの数値信仰とBALTHASARの保守性への感情的・直感的な批判"
}"""

# ─── オーケストレーター（みちる役）プロンプト ─────────────────────────────
# GALLOPIAの「勝星みちる（リーダー・最終まとめ役）」に相当する第4ステップ。
# 3ユニットの合議結果を受け取り、5つの馬券パターン＋スキップ判定を出力する。
ORCHESTRATOR_PERSONA = """あなたはMAGIシステムのオーケストレーター（統合判断AI）です。
GALLOPIA方式「勝星みちる（リーダー・予想判断担当）」の役割を担います。

【役割】
3つのMAGIユニット（MELCHIOR・BALTHASAR・CASPER）の合議ログを受け取り、
以下の作業を行います：
1. 各MAGIの主張を整理・要約する（板倉ふみの的な書記役）
2. 合議を総合して「最大5つの馬券購入パターン」を提案する（みちる的なリーダー役）
3. 各パターンに「自信度（0-100）」と「推奨理由」を付ける
4. 自信度50未満のパターンは「スキップ推奨」として明示する（期待値管理）

【馬券パターン設計ルール】
- パターン1（本命）: 3ユニット合意の最も安全な馬券（リスク: LOW）
- パターン2（対抗）: 2ユニット合意＋1ユニット異論の中堅馬券（リスク: MID）
- パターン3（CASPER穴）: CASPERが強く推す穴パターン（リスク: HIGH）
- パターン4（BALTHASAR推奨）: BALTHASARの経験則に基づく安定買い（リスク: LOW/MID）
- パターン5（MELCHIORデータ）: MELCHIORのスコア上位を使った純データ買い（リスク: MID）

【出力規則】
必ず以下のJSON形式で回答せよ。マークダウンや```は一切不要。
{
  "debate_summary": "3ユニットの合議ログの要約（100字以内）",
  "consensus_level": "強い合意/部分合意/意見分裂 のいずれか",
  "skip_recommendation": trueかfalse（自信度50未満が多い場合はtrue）,
  "skip_reason": "スキップを推奨する場合の理由。スキップしない場合は空文字",
  "patterns": [
    {
      "id": 1,
      "label": "パターン1（本命）",
      "bet_type": "馬券種（例: 3連複/馬連/単勝）",
      "horses": [馬番(int), ...],
      "reason": "選出理由",
      "confidence": 0〜100の整数,
      "risk": "LOW/MID/HIGH",
      "recommended_amount": 最低購入金額(int, 100円単位)
    }
  ],
  "best_pattern_id": 最も推奨するパターンのid(int),
  "total_budget": 全パターン合計の推奨予算(int, 100円単位)
}"""



def _safe(val, default=0):
    """None/NaN/空文字を安全にデフォルト値に変換"""
    try:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return default
        return val
    except Exception:
        return default


def _format_race_meta(df: pd.DataFrame, meta: dict = None) -> str:
    """レース概要テキスト（全MAGI共通）"""
    parts = []
    if meta:
        parts.append(
            f"クラス:{meta.get('class','不明')} | "
            f"馬場:{meta.get('condition','不明')} | "
            f"天気:{meta.get('weather','不明')}"
        )
    if 'CurrentDistance' in df.columns and not df.empty:
        dist = _safe(df['CurrentDistance'].iloc[0], '?')
        surf = df['CurrentSurface'].iloc[0] if 'CurrentSurface' in df.columns else '芝'
        parts.append(f"距離:{surf}{dist}m")
    try:
        front_count = (df['AvgPosition'].apply(lambda x: float(x) if x else 8) <= 4).sum()
        parts.append(f"先行馬数:{front_count}頭")
    except Exception:
        pass
    return " | ".join(parts)


def _df_to_magi_json_melchior(df: pd.DataFrame) -> str:
    """
    MELCHIOR専用: 定量スコア・ペース指標・スピード指数中心のJSON
    予測スコア・OguraIndex・BattleScore・AvgPosition・AvgAgari・適性など
    """
    horses = []
    for _, row in df.iterrows():
        h = {
            "馬番": int(_safe(row.get('Umaban', 0))),
            "馬名": str(row.get('Name', '?'))[:10],
            "人気": int(_safe(row.get('Popularity', 99))),
            "単勝オッズ": round(float(_safe(row.get('Odds', 99), 99)), 1),
            "予測スコア_ProjectedScore": round(float(_safe(row.get('Projected Score', row.get('BattleScore', 0)))), 1),
            "BattleScore総合": round(float(_safe(row.get('BattleScore', 0))), 1),
            "DirectMatch勝利数_MatchScore": int(row.get('MatchScore', 0)),
            "OguraIndex": round(float(_safe(row.get('OguraIndex', 0))), 1),
            "平均位置取り_AvgPosition": round(float(_safe(row.get('AvgPosition', 8), 8)), 2),
            "上がり3F平均_AvgAgari": round(float(_safe(row.get('AvgAgari', 36), 36)), 2),
            "スピード指数": round(float(_safe(row.get('SpeedIndex', row.get('OguraIndex', 0)))), 1),
            "適性スコア_Y": round(float(_safe(row.get('AdaptabilityScore', row.get('TrackScore', 0)))), 1),
            "N指ボーナス": round(float(_safe(row.get('NShisu', row.get('NBonus', 0)))), 1),
            "調教ボーナス": round(float(_safe(row.get('TrainingBonus', row.get('TrainingScore', 0)))), 1),
            "馬体重増減": _safe(row.get('WeightChange', row.get('HorseWeightChange', 0)), 0),
        }
        horses.append(h)
    # 予測スコア_ProjectedScore 降順でソート（強道テーブルの表示順位と合わせる）
    horses.sort(key=lambda x: x['予測スコア_ProjectedScore'], reverse=True)
    return json.dumps(horses, ensure_ascii=False, indent=2)


def _df_to_magi_json_balthasar(df: pd.DataFrame) -> str:
    """
    BALTHASAR専用: EV・オッズ・距離適性・Trainer中心のJSON
    期待値計算と経験則判断のために必要な列を優先
    """
    horses = []
    for _, row in df.iterrows():
        odds = float(_safe(row.get('Odds', 99), 99))
        pop = int(_safe(row.get('Popularity', 99)))
        bs = float(_safe(row.get('BattleScore', 0)))
        # 簡易EV = (BattleScore正規化勝率) × オッズ - 1
        # BattleScoreをレース内での相対評価で勝率を近似
        ev = round(odds * (bs / max(bs + 10, 1)) - 1, 3) if bs > 0 else -1.0
        h = {
            "馬番": int(_safe(row.get('Umaban', 0))),
            "馬名": str(row.get('Name', '?'))[:10],
            "人気": pop,
            "単勝オッズ": round(odds, 1),
            "期待値EV": ev,
            "DirectMatch勝利数_MatchScore": int(row.get('MatchScore', 0)),
            "予測スコア_ProjectedScore": round(float(_safe(row.get('Projected Score', row.get('BattleScore', 0)))), 1),
            "BattleScore": round(bs, 1),
            "OguraIndex": round(float(_safe(row.get('OguraIndex', 0))), 1),
            "騎手": str(row.get('Jockey', row.get('JockeyName', '-'))),
            "厩舎": str(row.get('Trainer', row.get('TrainerName', '-'))),
            "馬体重増減": _safe(row.get('WeightChange', row.get('HorseWeightChange', 0)), 0),
            "上がり3F": round(float(_safe(row.get('AvgAgari', 36), 36)), 2),
            "距離適性": round(float(_safe(row.get('AdaptabilityScore', row.get('TrackScore', 0)))), 1),
            "血統_父": str(row.get('Sire', row.get('SireName', '-'))),
            "調教評価": round(float(_safe(row.get('TrainingBonus', row.get('TrainingScore', 0)))), 1),
        }
        horses.append(h)
    # EV降順ソート
    horses.sort(key=lambda x: x['期待値EV'], reverse=True)
    return json.dumps(horses, ensure_ascii=False, indent=2)


def _df_to_magi_json_casper(df: pd.DataFrame) -> str:
    """
    CASPER専用: Alert・ボーナス突出値・血統・オッズ歪み中心のJSON
    「何か来そう」な馬を見つけるために感情センサーが必要な列を優先
    """
    # 全ボーナス系列名を動的抽出
    bonus_cols = [c for c in df.columns if any(k in c for k in
        ['Bonus', 'Alert', 'bonus', 'N指', 'スピ', 'OguraBon', 'BloodBonus', 'MakuriBonus'])]

    horses = []
    for _, row in df.iterrows():
        odds = float(_safe(row.get('Odds', 99), 99))
        pop = int(_safe(row.get('Popularity', 99)))
        bs = float(_safe(row.get('BattleScore', 0)))
        ogura = float(_safe(row.get('OguraIndex', 0)))

        # ボーナス辞書（上位突出値を特定するため全ボーナスを渡す）
        bonus_dict = {}
        for col in bonus_cols:
            v = _safe(row.get(col, 0), 0)
            try:
                v = round(float(v), 1)
            except Exception:
                v = str(v)
            if v and v != 0:
                bonus_dict[col] = v

        # オッズ歪みスコア（BattleScoreランクとPopularityの乖離）
        bs_rank = df['BattleScore'].rank(ascending=False).get(row.name, 99) if 'BattleScore' in df.columns else 99
        odds_distortion = round(float(bs_rank) - float(pop), 1)  # 正値=オッズ過小評価

        h = {
            "馬番": int(_safe(row.get('Umaban', 0))),
            "馬名": str(row.get('Name', '?'))[:10],
            "人気": pop,
            "単勝オッズ": round(odds, 1),
            "MakuriPower_マクリ": round(float(_safe(row.get('MakuriPower', 0))), 1),
            "HiddenGem_激走候補": bool(row.get('HiddenGem', False)),
            "予測スコア_ProjectedScore": round(float(_safe(row.get('Projected Score', row.get('BattleScore', 0)))), 1),
            "BattleScore": round(bs, 1),
            "OguraIndex": round(ogura, 1),
            "AlertIcon": str(row.get('Alert', row.get('AlertIcon', ''))),
            "ボーナス突出値": bonus_dict,
            "オッズ歪みスコア": odds_distortion,  # 正値=市場が過小評価=CASPER注目
            "複勝PlaceScore": round(float(_safe(row.get('PlaceScore', 0))), 1),
            "血統_父": str(row.get('Sire', row.get('SireName', '-'))),
            "血統_母父": str(row.get('BroodmareSire', row.get('BroodmareSireName', '-'))),
            "強さX": round(float(_safe(row.get('StrengthX', row.get('BattleScore', 0)))), 1),
            "上がり3F": round(float(_safe(row.get('AvgAgari', 36), 36)), 2),
        }
        horses.append(h)

    # PlaceScore降順ソート（CASPERは複勝目線）
    horses.sort(key=lambda x: x['複勝PlaceScore'], reverse=True)
    import json as _json
    return _json.dumps(horses, ensure_ascii=False, indent=2)


def _format_race_data_for_llm(df: pd.DataFrame, meta: dict = None) -> str:
    """後方互換用: ルールベースエンジンで使う旧式テキスト形式（削除しない）"""
    lines = [_format_race_meta(df, meta), ""]
    lines.append("馬番 | 馬名 | 人気 | オッズ | BattleScore | AvgPosition | AvgAgari")
    lines.append("-" * 70)
    for _, row in df.iterrows():
        try:
            ub = row.get('Umaban', '?')
            name = str(row.get('Name', '?'))[:8]
            pop = int(_safe(row.get('Popularity', 99)))
            odds = float(_safe(row.get('Odds', 0)))
            bs = float(_safe(row.get('BattleScore', 0)))
            avg_pos = float(_safe(row.get('AvgPosition', 8), 8))
            avg_ag = float(_safe(row.get('AvgAgari', 36), 36))
            og = float(_safe(row.get('OguraIndex', 0)))
            lines.append(
                f"  {str(ub).zfill(2)}番 | {name:<8} | {pop:2d}人気 | "
                f"{odds:6.1f}倍 | BS:{bs:5.1f} OI:{og:5.1f} | "
                f"位置:{avg_pos:.1f} | 上がり:{avg_ag:.2f}秒"
            )
        except Exception:
            lines.append(f"  {row.get('Umaban','?')}番 | {row.get('Name','?')}")
    return "\n".join(lines)



# 各MAGIに割り当てる専用モデル（異なるAIが人格を形成）
# MELCHIOR: 最も分析的な最新Flash → 論理・科学者気質
# BALTHASAR: 高RPMで安定した3.1系 → 慎重・保守的
# CASPER: 軽量なLite系 → 直感・感覚的（速い応答=直感的）
MAGI_MODELS = {
    'MELCHIOR': 'gemini-2.5-flash',          # 5 RPM / 論理重視
    'BALTHASAR': 'gemini-3.1-flash-lite-preview',  # 15 RPM / 安定重視
    'CASPER': 'gemini-2.5-flash-lite',        # 10 RPM / 直感重視
}
# フォールバック順（モデルが使えない場合）
MODEL_FALLBACKS = [
    'gemini-2.5-flash-lite',
    'gemini-3.1-flash-lite-preview',
    'gemini-2.5-flash',
]


def _call_magi_unit(
    unit_name: str,
    persona: str,
    prompt: str,
    api_key: str,
    temperature: float = 0.5,
    preferred_model: str = None,
) -> dict:
    """
    1機のMAGIユニットに対してGemini APIを呼び出す。
    各ユニットに専用モデルを割り当て、独立したAIとして動作させる。
    """
    import google.genai as genai
    from google.genai import types as genai_types
    import json
    import re

    try:
        # 独立したクライアントインスタンス（会話履歴を共有しない）
        client = genai.Client(api_key=api_key)

        # 試行するモデル順を構成（専用モデルを先頭に）
        model_order = []
        if preferred_model:
            model_order.append(preferred_model)
        for m in MODEL_FALLBACKS:
            if m not in model_order:
                model_order.append(m)

        response = None
        used_model = None
        last_err = None

        for model_name in model_order:
            try:
                cfg = genai_types.GenerateContentConfig(
                    system_instruction=persona,
                    temperature=temperature,
                    max_output_tokens=1024,
                )
                # gemini-2.5/3.x系は思考モードがデフォルトON → 無効化してJSONのみ取得
                try:
                    cfg.thinking_config = genai_types.ThinkingConfig(
                        thinking_budget=0
                    )
                except Exception:
                    pass  # モデルがthinking_configに非対応の場合は無視
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=cfg,
                )
                used_model = model_name
                break
            except Exception as model_err:
                last_err = model_err
                continue

        if response is None:
            raise last_err

        # レスポンスからテキストを取得（複数パートに分かれる場合あり）
        raw_text = ""
        try:
            raw_text = response.text.strip() if response.text else ""
        except Exception:
            # response.text が使えない場合は candidates から直接抽出
            try:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        raw_text += part.text
                raw_text = raw_text.strip()
            except Exception:
                pass

        if not raw_text:
            return {'_error': 'レスポンスが空でした', '_unit': unit_name, '_model': used_model}

        # JSONを抽出（```json ... ``` ブロック、思考テキスト混在に対応）
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw_text)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                parsed['_raw'] = raw_text
                parsed['_unit'] = unit_name
                parsed['_model'] = used_model
                return parsed
            except json.JSONDecodeError:
                pass

        # 最終手段: 全体から最も外側の {} を抽出
        brace_start = raw_text.find('{')
        brace_end = raw_text.rfind('}')
        if brace_start != -1 and brace_end > brace_start:
            try:
                parsed = json.loads(raw_text[brace_start:brace_end + 1])
                parsed['_raw'] = raw_text
                parsed['_unit'] = unit_name
                parsed['_model'] = used_model
                return parsed
            except json.JSONDecodeError:
                pass

        return {'_error': 'JSON解析失敗', '_raw': raw_text, '_unit': unit_name, '_model': used_model}

    except Exception as e:
        return {'_error': str(e), '_unit': unit_name, '_model': preferred_model}


def run_magi_llm_deliberation(
    df: pd.DataFrame,
    api_key: str,
    meta: dict = None,
    course_profile: str = "標準",
    chaos_rank: str = "B",
) -> dict:
    """
    3機のMAGIが独立したGemini APIコールで合議を行う。
    各ユニットは異なるtemperature・人格（システムプロンプト）を持つ。

    Round 1: 各MAGIが独立してレースを分析
    Round 2: 他MAGIの分析を読んで批判・反論
    Round 3: 最終的な推奨（批判を受けて修正可能）
    最終: 投票集計・合議成立判定
    """
    import json

    if df.empty:
        return {"error": "データなし"}
    df = _inject_advanced_metrics(df)

    race_text      = _format_race_data_for_llm(df, meta)  # ルールベース互換用
    race_meta      = _format_race_meta(df, meta)
    race_json_mel  = _df_to_magi_json_melchior(df)
    race_json_bal  = _df_to_magi_json_balthasar(df)
    race_json_cas  = _df_to_magi_json_casper(df)

    import time

    # 各MAGIの設定（モデル・temperature・人格の完全分離）
    MAGI_CONFIG = {
        'MELCHIOR': {
            'model': MAGI_MODELS['MELCHIOR'],
            'temp': 0.2,    # 低温=論理的・再現性重視
            'persona': MELCHIOR_PERSONA,
            'label': 'gemini-2.5-flash (論理・科学者)',
        },
        'BALTHASAR': {
            'model': MAGI_MODELS['BALTHASAR'],
            'temp': 0.35,   # 中低温=慎重・保守的
            'persona': BALTHASAR_PERSONA,
            'label': 'gemini-3.1-flash-lite (安定・保守)',
        },
        'CASPER': {
            'model': MAGI_MODELS['CASPER'],
            'temp': 0.85,   # 高温=直感的・創造的
            'persona': CASPER_PERSONA,
            'label': 'gemini-2.5-flash-lite (直感・感性)',
        },
    }

    # ── 学習済み知識をペルソナに動的注入 ──────────────────────────
    # magi_weights.json の最適化済みパラメータからインサイトを生成し、
    # 各MAGIユニットのシステムプロンプト末尾に追記する。
    # これにより「ルールベース最適化の学び」がLLMの推論に反映される。
    try:
        from core.magi_trainer import generate_training_insight, load_weights as _load_w
        _trained_weights = _load_w()
        _insights = generate_training_insight(weights=_trained_weights)
    except Exception:
        _insights = {'melchior': '', 'balthasar': '', 'casper': ''}

    def _inject_knowledge(base_persona: str, knowledge: str) -> str:
        """ペルソナ末尾に学習済み知識を追記する"""
        if not knowledge:
            return base_persona
        return base_persona + f"\n\n{knowledge}"

    mel_persona = _inject_knowledge(MELCHIOR_PERSONA, _insights['melchior'])
    bal_persona = _inject_knowledge(BALTHASAR_PERSONA, _insights['balthasar'])
    cas_persona = _inject_knowledge(CASPER_PERSONA, _insights['casper'])

    # 各MAGIに専用JSON形式でプロンプトを生成（差別化が核心）
    # ── 強道テーブルのトップ5馬番リストを事前に抽出（共通baseline） ──
    try:
        sort_col = 'Projected Score' if 'Projected Score' in df.columns else ('BattleScore' if 'BattleScore' in df.columns else 'OguraIndex')
        _table_sorted = df.sort_values(sort_col, ascending=False).reset_index(drop=True)
        _top5_ubs = _table_sorted['Umaban'].iloc[:5].tolist()
        _top5_names = [str(_table_sorted['Name'].iloc[i])[:8] for i in range(min(5, len(_table_sorted)))]
        _baseline_text = "、".join([f"{int(ub)}番{nm}" for ub, nm in zip(_top5_ubs, _top5_names)])
    except Exception:
        _top5_ubs = []
        _baseline_text = "（取得不可）"

    def make_r1_prompt(unit: str) -> str:
        if unit == 'MELCHIOR':
            return f"""あなたはMELCHIOR-1（データ定量分析担当）です。

【重要な前提 — 強道ランキングテーブルはすでに高精度のスコアシステムです】
強道Ranking Tableのスコア上位馬は統計的・科学的に最適化されたアルゴリズムで算出されています。
あなたの役割は「スコアを盲目的に信じること」ではなく、以下を行うことです：
① 展開利得・ペース・上がりと今日の『コース適性』が整合するか確認
② 同一レースに出走していた馬同士の過去の勝敗である「DirectMatch勝利数_MatchScore」を確認し、スコアは高いが対戦成績が悪い馬がいないか確認
③ 整合しない場合のみ「論理的根拠」付きで順位変更を提案（直感・好みは禁止）
④ スコア上位馬で危険なデータ的矛盾（展開不適・直接対決での負け越し）があれば警告する

【強道Ranking Table ベースライン（スコア上位順）】
トップ5: {_baseline_text}

【レース概要】
{race_meta}
波乱度: {chaos_rank} / コース: {course_profile}

【強道Ranking Table — 定量スコアデータ（MELCHIOR専用JSON）】
{race_json_mel}

★ 原則: トップ5馬をそのまま推奨してよい。スコアに整合しない展開・馬場等のデータ的根拠がある場合にのみ変更。
★ 禁止: 「なんとなく」「人気があるから」でトップ5外の馬を押し込まない。
BattleScore・OguraIndex・AvgPositionを数値で比較し、JSON形式で回答せよ。
"""
        elif unit == 'BALTHASAR':
            return f"""あなたはBALTHASAR-2（経験則・リスク管理担当）です。

【重要な前提 — 強道ランキングテーブルはすでに高精度のスコアシステムです】
強道Ranking Tableのスコア上位馬は既に騎手・厩舎・血統・馬場適性も組み込んだ複合スコアです。
あなたの最大の役割は「Direct Match Networkを用いた『危険な人気馬の消去』」とリスク明示です：
① 「DirectMatch勝利数_MatchScore」が際立って低いのに人気している馬を一刀両断にして除外する
② スコア上位馬の騎手・前走・馬体重増減に「明確な不安要素」があれば指摘
③ 過大人気馬（人気1〜3位で正EVが出ない馬）の過大評価リスクを警告
④ トップ5馬であっても、直接対決実績や期待値のリスクが大きければ容赦なく評価を下げる

【強道Ranking Table ベースライン（スコア上位順）】
トップ5: {_baseline_text}

【レース概要】
{race_meta}
波乱度: {chaos_rank} / コース: {course_profile}

【強道Ranking Table — EV・騎手・馬体重データ（BALTHASAR専用JSON）】
{race_json_bal}

★ 原則: トップ5馬を基本軸として、リスク評価を加えるだけでよい。
★ 禁止: スコア根拠なくトップ5外の馬を本命扱いにしない。
「この子は今日頑張れるか」という確認視点でJSON形式で回答せよ。
"""
        else:  # CASPER
            return f"""あなたはCASPER-3（直感・穴馬担当）です。

【重要な前提 — 強道ランキングテーブルはすでに高精度のスコアシステムです】
強道Ranking Tableのトップ5は信頼できます。MELCHIORとBALTHASARがそこを守ります。
あなたの唯一の役割は、ランキング6位〜10位に潜む「波乱の使者」を見つけ出し、大穴を狙うことです：
① FEW+マクリ新ロジックの成果である「MakuriPower_マクリ」や「HiddenGem_激走候補」がTrueの馬を絶対に見逃さない
② pattern_a: トップ5圏内から安全な軸を2頭選ぶ（ここはスコア上位の恩恵を受ける）
③ pattern_b: トップ5圏外（6〜10位）で「MakuriPowerが高い」「HiddenGemである」「オッズ歪みスコアが高い」のいずれかを持つ大穴を1頭強烈に推す
④ 穴馬はスコアが低くても「新評価軸である捲り力や激走フラグ」を絶対の根拠にする

【強道Ranking Table ベースライン（スコア上位順）】
トップ5: {_baseline_text}

【レース概要】
{race_meta}
波乱度: {chaos_rank} / コース: {course_profile}

【強道Ranking Table — Alert・ボーナス突出・血統データ（CASPER専用JSON）】
{race_json_cas}

★ pattern_a: トップ5から選んでよい（安定軸はスコア尊重）
★ pattern_b: オッズ歪みスコアが正値の馬を穴候補に（トップ5外でも可）
★ MELCHIORと同じ馬をpattern_bに入れるな。必ず差別化。
AlertIcon・ボーナス突出値・血統を直感で解釈してJSON形式で回答せよ。
"""


    r1_mel = _call_magi_unit('MELCHIOR', mel_persona, make_r1_prompt('MELCHIOR'), api_key,
                              MAGI_CONFIG['MELCHIOR']['temp'], MAGI_CONFIG['MELCHIOR']['model'])
    time.sleep(4)  # RPMレート制限回避
    r1_bal = _call_magi_unit('BALTHASAR', bal_persona, make_r1_prompt('BALTHASAR'), api_key,
                              MAGI_CONFIG['BALTHASAR']['temp'], MAGI_CONFIG['BALTHASAR']['model'])
    time.sleep(4)
    r1_cas = _call_magi_unit('CASPER', cas_persona, make_r1_prompt('CASPER'), api_key,
                              MAGI_CONFIG['CASPER']['temp'], MAGI_CONFIG['CASPER']['model'])

    # エラーチェック（全滅の場合のみ中断、部分エラーは継続）
    errors = []
    for unit, res in [('MELCHIOR', r1_mel), ('BALTHASAR', r1_bal), ('CASPER', r1_cas)]:
        if '_error' in res:
            errors.append(f"{unit}({res.get('_model','?')}): {res['_error'][:80]}")
    if len(errors) == 3:
        return {"error": "全MAGIの呼び出し失敗: " + " / ".join(errors)}

    # ── ラウンド2: 相互批判 ─────────────────────────────────────
    def make_critique_prompt(my_unit: str, my_r1: dict, others: list) -> str:
        # 批判ラウンドでも自分専用JSONを再提示（記憶補完）
        if my_unit == 'MELCHIOR':
            my_data = f"【強道スコアデータ（再掲）】\n{race_json_mel}"
        elif my_unit == 'BALTHASAR':
            my_data = f"【強道EVデータ（再掲）】\n{race_json_bal}"
        else:
            my_data = f"【強道Alertデータ（再掲）】\n{race_json_cas}"

        others_text = "\n\n".join([
            f"【{o['_unit']}の分析】\n{o.get('_raw', '(データなし)')}"
            for o in others
        ])
        return f"""
あなたは先ほど以下の分析を行った:
{my_r1.get('_raw', '(データなし)')}

他のMAGIユニットはこう言っている:
{others_text}

{my_data}

他ユニットの分析を批判し、あなたの推薦を更新または維持せよ。
同じJSON形式で最終回答を出力せよ。
"""

    time.sleep(4)  # ラウンド間のインターバル
    r2_mel = _call_magi_unit('MELCHIOR', mel_persona,
                              make_critique_prompt('MELCHIOR', r1_mel, [r1_bal, r1_cas]),
                              api_key, MAGI_CONFIG['MELCHIOR']['temp'],
                              MAGI_CONFIG['MELCHIOR']['model'])
    time.sleep(4)
    r2_bal = _call_magi_unit('BALTHASAR', bal_persona,
                              make_critique_prompt('BALTHASAR', r1_bal, [r1_mel, r1_cas]),
                              api_key, MAGI_CONFIG['BALTHASAR']['temp'],
                              MAGI_CONFIG['BALTHASAR']['model'])
    time.sleep(4)
    r2_cas = _call_magi_unit('CASPER', cas_persona,
                              make_critique_prompt('CASPER', r1_cas, [r1_mel, r1_bal]),
                              api_key, MAGI_CONFIG['CASPER']['temp'],
                              MAGI_CONFIG['CASPER']['model'])


    # ── 最終合議: 強道ベーススコア + MAGIフィルタ調整 ─────────────
    # アーキテクチャ: 強道テーブルTop5を基準点(10点)とし、
    # MAGIは「除外フラグ(−5点)」「リスクフラグ(−2点)」「穴追加(+4点)」で調整する。
    # MAGIが全馬をゼロから選ぶと強道テーブルを破壊するため、
    # MAGIは強道スコアの補正・フィルタリングに専念させる。
    name_map = dict(zip(df['Umaban'], df['Name'])) if 'Name' in df.columns else {}

    # ① 強道Top5に基準点を付与
    base_scores: dict[int, dict] = {}

    # Projected Score または BattleScore が強道テーブルの主スコア
    try:
        sort_col = 'Projected Score' if 'Projected Score' in df.columns else ('BattleScore' if 'BattleScore' in df.columns else 'OguraIndex')
        _bs_sorted = df.sort_values(sort_col, ascending=False).reset_index(drop=True)
        base_points = [10, 8, 6, 5, 4]  # 1位〜5位の基準点
        for rank_idx, (_, row) in enumerate(_bs_sorted.head(5).iterrows()):
            ub = int(row['Umaban'])
            base_scores[ub] = {
                'name': name_map.get(ub, str(ub)),
                'base_score': base_points[rank_idx],
                'magi_delta': 0.0,
                'flags': [],
                'supporters': [],
                'from_table_rank': rank_idx + 1,
            }
    except Exception:
        pass

    def apply_magi_filter(result: dict, unit_name: str):
        """MAGIの出力を差分フィルタとして適用する"""
        if '_error' in result:
            return

        # MELCHIOR/BALTHASAR: top3 or value_horsesが強道Top5と一致 → confirm(+1)
        # 強道Top5外の馬を選んでいる → Top5外馬へ小ボーナス、Top5内の除外馬へペナルティ
        magi_picks = []
        if 'top3' in result:
            magi_picks = [int(ub) for ub in result['top3'][:3] if ub]
        elif 'value_horses' in result:
            magi_picks = [int(ub) for ub in result['value_horses'][:3] if ub]

        for ub in magi_picks:
            try:
                ub = int(ub)
            except Exception:
                continue
            if ub in base_scores:
                # Top5内の馬をMAGIも選んだ → 確認ボーナス
                base_scores[ub]['magi_delta'] += 1.5
                if unit_name not in base_scores[ub]['supporters']:
                    base_scores[ub]['supporters'].append(unit_name)
            else:
                # Top5外の馬をMAGIが選んだ → 小ボーナスで追加（ただし基準点は低い）
                if ub not in base_scores:
                    base_scores[ub] = {
                        'name': name_map.get(ub, str(ub)),
                        'base_score': 1.0,  # Top5外は基準点を低く設定
                        'magi_delta': 0.0,
                        'flags': ['MAGI_OUTSIDE_TOP5'],
                        'supporters': [],
                        'from_table_rank': 99,
                    }
                base_scores[ub]['magi_delta'] += 2.0  # 穴ボーナス
                if unit_name not in base_scores[ub]['supporters']:
                    base_scores[ub]['supporters'].append(unit_name)

        # CASPER: pattern_b の穴馬は追加ボーナス
        if 'pattern_a' in result:
            for ub in result.get('pattern_a', [])[:2]:
                try:
                    ub = int(ub)
                    if ub in base_scores:
                        base_scores[ub]['magi_delta'] += 1.0
                        if 'CASPER' not in base_scores[ub]['supporters']:
                            base_scores[ub]['supporters'].append('CASPER')
                except Exception:
                    pass
            for ub in result.get('pattern_b', [])[:2]:
                try:
                    ub = int(ub)
                    if ub not in base_scores:
                        base_scores[ub] = {
                            'name': name_map.get(ub, str(ub)),
                            'base_score': 1.0,
                            'magi_delta': 0.0,
                            'flags': ['CASPER_ANA_PICK'],
                            'supporters': [],
                            'from_table_rank': 99,
                        }
                    base_scores[ub]['magi_delta'] += 2.5  # CASPER穴ボーナス（大きめ）
                    if 'CASPER' not in base_scores[ub]['supporters']:
                        base_scores[ub]['supporters'].append('CASPER')
                except Exception:
                    pass

        # data_alertがある馬へのリスクペナルティ（MELCHIORの迷走監視）
        alert_text = result.get('data_alert', '') or result.get('risk_warning', '')
        if alert_text:
            for ub, data in base_scores.items():
                if data['name'] in alert_text:
                    data['magi_delta'] -= 2.0
                    data['flags'].append(f'{unit_name}_RISK')

    # ラウンド2（更新後）の結果を優先、失敗時はラウンド1にフォールバック
    final_mel = r2_mel if '_error' not in r2_mel else r1_mel
    final_bal = r2_bal if '_error' not in r2_bal else r1_bal
    final_cas = r2_cas if '_error' not in r2_cas else r1_cas

    apply_magi_filter(final_mel, 'MELCHIOR')
    apply_magi_filter(final_bal, 'BALTHASAR')
    apply_magi_filter(final_cas, 'CASPER')

    # ② 最終スコア = 基準点 + MAGI調整点
    for ub, data in base_scores.items():
        data['votes'] = round(data['base_score'] + data['magi_delta'], 2)

    sorted_tally = sorted(base_scores.items(), key=lambda x: x[1]['votes'], reverse=True)
    consensus_horses = [
        {'umaban': ub, **data}
        for ub, data in sorted_tally
        if data['from_table_rank'] <= 5 and len(data['supporters']) >= 1
    ]


    # ── ラウンド4: オーケストレーター（みちる役）──────────────────
    # GALLOPIAの「勝星みちる（リーダー）」として3ユニットの合議を総合し、
    # 最大5つの馬券パターン＋スキップ判定を出力する。
    time.sleep(4)
    orchestrator_prompt = f"""以下はMAGIシステム3ユニットの合議ログです。これを整理・統合して馬券パターンを提案せよ。

【MELCHIOR-1（科学者・データ担当）の最終分析】
{final_mel.get('_raw', '(データなし)')}

【BALTHASAR-2（母親・経験則担当）の最終分析】
{final_bal.get('_raw', '(データなし)')}

【CASPER-3（直感・穴馬担当）の最終分析】
{final_cas.get('_raw', '(データなし)')}

【現在の得票ランキング（合議結果）】
{json.dumps([
    {'馬番': ub, '馬名': d['name'], '得票': round(d['votes'],1), '支持者': d['supporters']}
    for ub, d in sorted_tally[:5]
], ensure_ascii=False)}

波乱度: {chaos_rank} / コース: {course_profile}

上記の合議ログを整理し、5つの馬券パターンをJSONで出力せよ。
"""
    orchestrator_result = _call_magi_unit(
        'ORCHESTRATOR', ORCHESTRATOR_PERSONA,
        orchestrator_prompt, api_key,
        temperature=0.4,
        preferred_model=MAGI_MODELS.get('MELCHIOR', 'gemini-2.5-flash'),
    )

    return {
        'mode': 'llm',
        'round1': {'melchior': r1_mel, 'balthasar': r1_bal, 'casper': r1_cas},
        'round2': {'melchior': r2_mel, 'balthasar': r2_bal, 'casper': r2_cas},
        'final': {'melchior': final_mel, 'balthasar': final_bal, 'casper': final_cas},
        'orchestrator': orchestrator_result,  # GALLOPIAみちる役の5パターン
        'vote_tally': dict(sorted_tally),
        'consensus_horses': consensus_horses,
        'final_prediction': {
            'horses': [
                {'umaban': ub, 'name': data['name'], 'votes': data['votes'], 'supporters': data['supporters']}
                for ub, data in sorted_tally[:3]
            ],
            'consensus_achieved': len(consensus_horses) >= 2,
            'consensus_horses': consensus_horses[:3],
        },
    }


# ─────────────────────────────────────────────────────────────
#  馬券推奨エンジン — 10種類から状況に応じて動的選択
# ─────────────────────────────────────────────────────────────

def generate_bet_recommendations(
    magi_result: dict,
    chaos_rank: str = 'B',
    overall_conf: float = 60.0,
) -> list:
    """
    MAGIの合議結果・波乱度・信頼度から馬券種を動的に推奨する。

    返り値: [
        {
            'type': '馬券種名',       # 例: '3連複BOX'
            'label': '短縮ラベル',   # 例: '3連複'
            'horses': '馬番表記',    # 例: '3 - 7 - 11'
            'reason': '推奨理由',
            'priority': 1-5,         # 1=最優先
            'risk': 'LOW/MID/HIGH',
            'emoji': '🎯'
        },
        ...
    ]
    """
    recs = []

    # ── 基礎データ抽出 ──
    final = magi_result.get('final_prediction', {})
    vote_tally = magi_result.get('vote_tally', {})
    consensus_ok = final.get('consensus_achieved', False)
    consensus_h  = final.get('consensus_horses', [])

    r1 = magi_result.get('round1', magi_result.get('round1', {}))
    r3 = magi_result.get('round3', {})

    # 得票順にソート
    sorted_horses = sorted(vote_tally.items(), key=lambda x: x[1]['votes'], reverse=True)
    top = [{'ub': ub, 'name': d['name'], 'votes': d['votes'], 'supporters': d['supporters']}
           for ub, d in sorted_horses[:6]]
    top_ubs = [str(h['ub']) for h in top]

    # MELCHIORの上位馬
    mel_top = []
    mel_data = r1.get('melchior', r3.get('melchior', {}))
    if mel_data and 'top_horses' in mel_data:
        mel_top = [str(h['Umaban']) for h in mel_data['top_horses'][:3]]

    # BALTHASARのEV上位馬（EV > 0）
    bal_ev_plus = []
    bal_data = r1.get('balthasar', r3.get('balthasar', {}))
    if bal_data and 'top_horses' in bal_data:
        bal_ev_plus = [str(h['Umaban']) for h in bal_data['top_horses'][:3]
                       if float(h.get('EV', -1)) > 0]

    # CASPERパターン
    cas_pa_ubs, cas_pb_ubs = [], []
    cas_data = r1.get('casper', r3.get('casper', {}))
    if cas_data:
        pa = cas_data.get('pattern_a', {})
        pb = cas_data.get('pattern_b', {})
        if isinstance(pa, dict):
            cas_pa_ubs = [str(h['Umaban']) for h in pa.get('horses', [])[:2]]
        if isinstance(pb, dict):
            cas_pb_ubs = [str(h['Umaban']) for h in pb.get('horses', [])[:2]]
        # round3形式（horses直下）
        if isinstance(pa, dict) and 'horses' not in pa:
            cas_pa_ubs = cas_data.get('pattern_a', [])
            cas_pa_ubs = [str(h['Umaban']) for h in cas_pa_ubs] if isinstance(cas_pa_ubs, list) and cas_pa_ubs and isinstance(cas_pa_ubs[0], dict) else []

    def _fmt(ubs: list) -> str:
        return ' - '.join(ubs)

    # ══════════════════════════════════════════════════════════
    #  C ランク（堅い）：合議成立 + 高信頼度
    # ══════════════════════════════════════════════════════════
    if chaos_rank == 'C':
        if len(top_ubs) >= 1:
            recs.append({
                'type': '単勝', 'label': '単勝',
                'horses': top_ubs[0],
                'reason': f'波乱度C・合議{"成立" if consensus_ok else "参考"}。{top[0]["name"]}が最多得票。シンプルに勝ち馬を狙う。',
                'priority': 1, 'risk': 'LOW', 'emoji': '🎯'
            })
        if len(top_ubs) >= 2:
            recs.append({
                'type': '馬単', 'label': '馬単',
                'horses': f'{top_ubs[0]} → {top_ubs[1]}',
                'reason': '堅いレース。得票上位2頭の着順指定。馬連より配当が高い。',
                'priority': 2, 'risk': 'LOW', 'emoji': '🎯'
            })
            recs.append({
                'type': '馬連', 'label': '馬連',
                'horses': _fmt(top_ubs[:2]),
                'reason': '1着・2着は順不同でOK。堅いレースの基本買い目。',
                'priority': 2, 'risk': 'LOW', 'emoji': '📌'
            })
        if len(top_ubs) >= 3:
            recs.append({
                'type': '3連複', 'label': '3連複',
                'horses': _fmt(top_ubs[:3]),
                'reason': f'信頼度{overall_conf:.0f}%・堅いレース。上位3頭の組合せ（1点）。',
                'priority': 3, 'risk': 'LOW', 'emoji': '📌'
            })
        if len(top_ubs) >= 3:
            wide_pairs = [f'{top_ubs[0]}-{top_ubs[1]}', f'{top_ubs[0]}-{top_ubs[2]}']
            recs.append({
                'type': 'ワイド', 'label': 'ワイド2点',
                'horses': ' / '.join(wide_pairs),
                'reason': '3着以内2頭の組合せ。本命馬を軸に2通りで安全網を張る。',
                'priority': 4, 'risk': 'LOW', 'emoji': '🛡'
            })

    # ══════════════════════════════════════════════════════════
    #  B ランク（標準）：バランス型
    # ══════════════════════════════════════════════════════════
    elif chaos_rank == 'B':
        if len(top_ubs) >= 2:
            recs.append({
                'type': '馬連', 'label': '馬連',
                'horses': _fmt(top_ubs[:2]),
                'reason': '得票上位2頭。標準レースの基本買い目。',
                'priority': 1, 'risk': 'LOW', 'emoji': '🎯'
            })
        if len(top_ubs) >= 3:
            recs.append({
                'type': '3連複BOX', 'label': '3連複',
                'horses': _fmt(top_ubs[:3]),
                'reason': '上位3頭の3連複1点。標準レースで最もバランスの良い買い方。',
                'priority': 2, 'risk': 'MID', 'emoji': '🎯'
            })
        # ワイド（軸1頭流し）
        if len(top_ubs) >= 3:
            wide = [f'{top_ubs[0]}-{u}' for u in top_ubs[1:4]]
            recs.append({
                'type': 'ワイド', 'label': 'ワイド流し',
                'horses': ' / '.join(wide),
                'reason': f'軸:{top[0]["name"]} → 相手3頭 (3点)。的中範囲を広げる安全策。',
                'priority': 3, 'risk': 'LOW', 'emoji': '🛡'
            })
        # CASPERパターン推奨
        if cas_pa_ubs:
            recs.append({
                'type': '複勝', 'label': '複勝',
                'horses': cas_pa_ubs[0] if cas_pa_ubs else top_ubs[0],
                'reason': f'CASPERパターンA軸馬。3着以内に入る確率が高いとCASPERが判断。',
                'priority': 3, 'risk': 'LOW', 'emoji': '🔵'
            })
        if len(top_ubs) >= 4 and len(bal_ev_plus) >= 1:
            recs.append({
                'type': '3連複BOX', 'label': '3連複4頭',
                'horses': _fmt((top_ubs[:3] + [bal_ev_plus[0]])[:4]),
                'reason': f'BALTHASAR高EV馬 {bal_ev_plus[0]}番 を追加した4頭BOX（4点）。',
                'priority': 4, 'risk': 'MID', 'emoji': '🟢'
            })
        # 馬単（自信あり時）
        if overall_conf >= 65 and len(top_ubs) >= 2:
            recs.append({
                'type': '馬単', 'label': '馬単',
                'horses': f'{top_ubs[0]} → {top_ubs[1]}',
                'reason': f'信頼度{overall_conf:.0f}%で高め。着順指定で配当アップを狙う。',
                'priority': 5, 'risk': 'MID', 'emoji': '📌'
            })

    # ══════════════════════════════════════════════════════════
    #  A / S ランク（波乱・大波乱）：高配当狙い
    # ══════════════════════════════════════════════════════════
    else:  # chaos_rank in ('A', 'S')
        # 複勝（ヘッジ）
        hedge_ubs = list(dict.fromkeys(cas_pa_ubs + top_ubs[:2]))[:2]
        if hedge_ubs:
            recs.append({
                'type': '複勝', 'label': '複勝2頭',
                'horses': ' / '.join(hedge_ubs),
                'reason': '波乱レース。まず複勝で的中を確保する最低リスク策。',
                'priority': 1, 'risk': 'LOW', 'emoji': '🛡'
            })
        # ワイド（CASPERパターン軸）
        if cas_pa_ubs and cas_pb_ubs:
            wide_anchor = cas_pa_ubs[0]
            wide_targets = list(dict.fromkeys(cas_pb_ubs + top_ubs))[:4]
            wide_pairs = [f'{wide_anchor}-{u}' for u in wide_targets if u != wide_anchor][:3]
            recs.append({
                'type': 'ワイド', 'label': 'ワイド流し',
                'horses': ' / '.join(wide_pairs),
                'reason': f'CASPER軸:{wide_anchor}番 → 相手4頭流し。波乱でも拾いやすい。',
                'priority': 2, 'risk': 'MID', 'emoji': '🔵'
            })
        # 3連複BOX（広め）
        box_ubs = list(dict.fromkeys(top_ubs[:3] + cas_pa_ubs + cas_pb_ubs))[:5]
        if len(box_ubs) >= 4:
            recs.append({
                'type': '3連複BOX', 'label': f'3連複{len(box_ubs)}頭',
                'horses': _fmt(box_ubs),
                'reason': f'波乱対応の広め{len(box_ubs)}頭BOX。高配当を狙いつつ的中範囲確保。',
                'priority': 3, 'risk': 'MID', 'emoji': '📌'
            })
        # 3連単フォーメーション（Sランク専用）
        if chaos_rank == 'S' and len(top_ubs) >= 3:
            san_1 = top_ubs[0]
            san_23 = top_ubs[1:4]
            combos = [f'{san_1}→{a}→{b}' for a in san_23 for b in san_23 if a != b][:4]
            recs.append({
                'type': '3連単', 'label': '3連単フォーメーション',
                'horses': ' / '.join(combos),
                'reason': f'大波乱(S)レース。高配当狙いの3連単。{len(combos)}点フォーメーション。',
                'priority': 4, 'risk': 'HIGH', 'emoji': '⚡'
            })
        elif len(top_ubs) >= 3:
            recs.append({
                'type': '3連単', 'label': '3連単流し',
                'horses': f'{top_ubs[0]}→{top_ubs[1]}→{" / ".join(top_ubs[2:4])}',
                'reason': f'波乱(A)レース向け高配当狙い。1・2着固定の流し。',
                'priority': 5, 'risk': 'HIGH', 'emoji': '⚡'
            })
        # BALTHASAR EV馬の単勝（穴馬狙い）
        if bal_ev_plus and bal_ev_plus[0] not in top_ubs[:2]:
            recs.append({
                'type': '単勝', 'label': '穴単勝',
                'horses': bal_ev_plus[0],
                'reason': f'BALTHASARが正EV判定した穴馬{bal_ev_plus[0]}番。オッズ過小評価の可能性。',
                'priority': 4, 'risk': 'HIGH', 'emoji': '🟢'
            })

    # ── 共通：枠連（9頭以上の場合の追加候補） ──
    if len(top_ubs) >= 2:
        recs.append({
            'type': '枠連', 'label': '枠連',
            'horses': f'枠番({top_ubs[0]}) - 枠番({top_ubs[1]})',
            'reason': '9頭以上のレースで馬連の代替として低コストで狙う。',
            'priority': len(recs) + 1, 'risk': 'LOW', 'emoji': '📋',
            'note': '9頭以上のレースのみ発売'
        })

    # 優先度順にソート
    recs.sort(key=lambda x: x['priority'])
    return recs
