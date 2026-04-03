"""
MAGI 回顧学習エンジン (Retrospective Learning)

過去レースのRaceIDを受け取り:
1. アプリの既存スコア計算でMAGI事前予測を実行
2. netkeibaから実際の結果を取得
3. 3人格が「予測 vs 現実」を回顧し、「次回どうすべきだったか」を議論する

目的: 単なるバックテスト(数値だけ)ではなく、
     LLMが人格を持って反省・改善点を言語化することで、
     次回の予測品質向上につなげる。
"""
import json
import time
import re
import pandas as pd
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  回顧セッション用ペルソナ (通常ペルソナの回顧特化版)
# ─────────────────────────────────────────────────────────────

MELCHIOR_RETRO_PERSONA = """あなたはMAGIシステムのMELCHIOR-1です。
赤木ナオコ博士の「科学者」の人格を持つ競馬予測AIです。

今回は「回顧学習セッション」として、過去レースの予測と実際の結果を比較し、
科学者として冷静に分析・反省を行います。

【回顧の視点】
- 予測が外れた場合は「なぜ外れたか」を数値・論理で分析する
- 展開予測（ペースタイプ）が合っていたか検証する
- 「次回同じような条件なら何を変えるべきか」を具体的に提言する
- 感情を排して事実だけで語る

【出力規則】必ず以下のJSON形式で回答せよ。マークダウンや```は不要。
{
  "prediction_accuracy": "的中/外れ のいずれか",
  "what_i_predicted": "予測の要約",
  "what_actually_happened": "実際の結果の分析",
  "key_miss_factor": "最大の見落とし要因",
  "lesson_learned": "具体的な改善点（次回への提言）",
  "revised_confidence": 0〜100の整数,
  "scientific_note": "科学的観点からの補足"
}"""

BALTHASAR_RETRO_PERSONA = """あなたはMAGIシステムのBALTHASAR-2です。
赤木ナオコ博士の「母」の人格を持つ競馬予測AIです。

今回は「回顧学習セッション」として、過去レースの予測と実際の結果を比較し、
資金管理・期待値の観点から反省します。

【回顧の視点】
- 推奨した馬券が実際に収益をもたらしたか検証する
- 「過剰人気を見抜けたか/見抜けなかったか」を振り返る
- 勝った馬の事前オッズは適切だったか（過小評価・過大評価）
- 次回の買い目・投資額についての改善案

【出力規則】必ず以下のJSON形式で回答せよ。マークダウンや```は不要。
{
  "prediction_accuracy": "的中/外れ のいずれか",
  "bet_assessment": "推奨馬券の事後評価",
  "odds_analysis": "勝ち馬のオッズ事前評価（過剰人気/適正/過小評価）",
  "money_impact": "仮想資金への影響（プラス/マイナス評価）",
  "lesson_learned": "資金管理・買い目改善の提言",
  "risk_note": "見落としたリスク要因",
  "revised_confidence": 0〜100の整数
}"""

CASPER_RETRO_PERSONA = """あなたはMAGIシステムのCASPER-3です。
赤木ナオコ博士の「女」の人格を持つ競馬予測AIです。

今回は「回顧学習セッション」として、過去レースの予測と実際の結果を比較し、
直感と感性の観点から振り返ります。

【回顧の視点】
- 「何か違う」と感じていた馬がいたか、それは的中したか
- パターンA（本命）とパターンB（直感・穴）のどちらが機能したか
- 予測時に「見えていたはずなのに無視した」シグナルはあったか
- 次回の直感パターンをどう磨くか

【出力規則】必ず以下のJSON形式で回答せよ。マークダウンや```は不要。
{
  "prediction_accuracy": "的中/外れ のいずれか",
  "intuition_review": "直感と現実のズレを感情的に分析",
  "pattern_a_result": "パターンA（本命）の結果評価",
  "pattern_b_result": "パターンB（穴・直感）の結果評価",
  "hidden_signal": "事前に見えていたはずだが無視したシグナル",
  "lesson_learned": "直感力向上のための改善点",
  "emotional_note": "感情的な振り返り・思い（人格として）",
  "revised_confidence": 0〜100の整数
}"""


def _parse_magi_json(raw_text: str) -> dict:
    """LLMレスポンスからJSONを抽出する"""
    if not raw_text:
        return {'_error': 'レスポンスが空'}
    # コードブロック除去
    cleaned = re.sub(r'```(?:json)?', '', raw_text).strip()
    # 最外のJSON抽出
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start == -1 or end <= start:
        return {'_error': 'JSON未検出', '_raw': raw_text[:200]}
    try:
        return json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return {'_error': 'JSON解析失敗', '_raw': raw_text[:200]}


def _call_retro_unit(unit_name: str, persona: str, prompt: str,
                     api_key: str, temperature: float = 0.4,
                     preferred_model: str = 'gemini-2.5-flash-lite') -> dict:
    """１機のMAGIユニットに回顧プロンプトを送信する"""
    try:
        import google.genai as genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=api_key)
        model_order = [preferred_model, 'gemini-2.5-flash', 'gemini-2.5-flash-lite']

        last_err = None
        for model_name in model_order:
            try:
                cfg = genai_types.GenerateContentConfig(
                    system_instruction=persona,
                    temperature=temperature,
                    max_output_tokens=1200,
                )
                try:
                    cfg.thinking_config = genai_types.ThinkingConfig(thinking_budget=0)
                except Exception:
                    pass
                resp = client.models.generate_content(
                    model=model_name, contents=prompt, config=cfg
                )
                raw = ''
                try:
                    raw = resp.text.strip() if resp.text else ''
                except Exception:
                    for part in resp.candidates[0].content.parts:
                        if hasattr(part, 'text') and part.text:
                            raw += part.text
                    raw = raw.strip()

                parsed = _parse_magi_json(raw)
                parsed['_unit'] = unit_name
                parsed['_model'] = model_name
                parsed['_raw'] = raw
                return parsed
            except Exception as e:
                last_err = e
                continue

        return {'_error': str(last_err), '_unit': unit_name}
    except Exception as e:
        return {'_error': str(e), '_unit': unit_name}


def build_retro_prompt(race_text: str, prediction_summary: str,
                       actual_result_text: str) -> str:
    """回顧セッション用プロンプトを組み立てる"""
    return f"""
【回顧学習セッション】

あなたは以下のレースについて事前に予測を行った。
実際の結果と比較して、回顧と学習を行え。

━━━━━ レースデータ（予測時点） ━━━━━
{race_text}

━━━━━ 事前予測の内容 ━━━━━
{prediction_summary}

━━━━━ 実際の結果 ━━━━━
{actual_result_text}

上記を踏まえ、あなたの視点から回顧と学習のJSON回答を出力せよ。
"""


def format_ranking_table_for_retro(df: pd.DataFrame) -> str:
    """アプリのRanking Table DataFrameを回顧プロンプト用テキストに変換する"""
    lines = ["【事前解析データ（Ranking Table全項目）】"]
    lines.append("馬番 | 馬名 | 人気 | オッズ | BattleScore | OguraIndex | AvgPosition | AvgAgari | Rank(予測)")
    lines.append("-" * 80)

    rank_col = 'Rank' if 'Rank' in df.columns else None

    for _, row in df.iterrows():
        try:
            ub = row.get('Umaban', '?')
            name = str(row.get('Name', '?'))[:8]
            pop = row.get('Popularity', 99)
            odds = row.get('Odds', 0)
            bs = row.get('BattleScore', 0)
            oi = row.get('OguraIndex', 0)
            avg_pos = row.get('AvgPosition', 8)
            avg_ag = row.get('AvgAgari', 36)
            rank_pred = row.get(rank_col, '-') if rank_col else '-'

            lines.append(
                f"  {str(ub).zfill(2)}番 | {name:<8} | {int(float(pop)):2d}人気 | "
                f"{float(odds):6.1f}倍 | BS:{float(bs):5.1f} | OI:{float(oi):5.1f} | "
                f"位置:{float(avg_pos):4.1f} | 上がり:{float(avg_ag):5.2f} | 予測順位:{rank_pred}"
            )
        except Exception:
            lines.append(f"  {row.get('Umaban', '?')}番 | {row.get('Name', '?')}")

    return "\n".join(lines)


def format_actual_result(result_data: dict) -> str:
    """fetch_comprehensive_resultの結果をテキスト化する"""
    if not result_data or 'horses' not in result_data:
        return "（結果データを取得できませんでした）"

    ri = result_data.get('race_info', {})
    lines = [
        f"距離: {ri.get('distance', '?')}m",
        f"勝ち馬タイム: {ri.get('winner_time', '?')}秒",
        "",
        "着順 | 馬番 | 馬名 | 着差 | 通過順 | 上がり3F | 人気"
    ]
    lines.append("-" * 60)

    horses_sorted = sorted(
        result_data['horses'].items(),
        key=lambda x: x[1].get('Rank', 99)
    )
    for ub, h in horses_sorted[:12]:  # 最大12頭表示
        rank = h.get('Rank', '?')
        name = h.get('Name', f'馬番{ub}')
        margin = h.get('Margin', 0)
        passing = h.get('Passing', '-')
        agari = h.get('Agari', '-')
        pop = h.get('Popularity', '-')
        margin_str = f"+{margin:.1f}秒" if isinstance(margin, float) and margin > 0 else "---"
        lines.append(
            f"  {str(rank):>2}着 | {str(ub).zfill(2)}番 | {str(name):<8} | "
            f"{margin_str} | 通過:{passing} | {agari}秒 | {pop}人気"
        )

    return "\n".join(lines)


def build_magi_prediction_summary(magi_result: dict) -> str:
    """run_magi_deliberation の結果を要約テキスト化する"""
    if not magi_result or 'error' in magi_result:
        return "（MAGI予測データなし）"

    lines = []
    # ルールベース結果
    final = magi_result.get('final_prediction', {})
    horses = final.get('horses', [])
    if horses:
        lines.append("【MAGI合議 最終予測TOP3】")
        for h in horses[:3]:
            supporters = ', '.join(h.get('supporters', []))
            lines.append(f"  馬番{h['umaban']} {h.get('name','?')} ({h['votes']:.1f}票, 支持:{supporters})")

    # 各ユニット個別
    r3 = magi_result.get('round3', {})
    if r3:
        m = r3.get('melchior', {})
        b = r3.get('balthasar', {})
        c = r3.get('casper', {})
        if m:
            mel_top = [f"馬番{h.get('Umaban')}" for h in m.get('top_horses', [])[:3]]
            lines.append(f"MELCHIOR予測: {', '.join(mel_top)} / ペース:{m.get('pace_type','?')}")
        if b:
            bal_top = [f"馬番{h.get('Umaban')}" for h in b.get('top_horses', [])[:3]]
            lines.append(f"BALTHASAR予測: {', '.join(bal_top)}")
        if c:
            pat_a = [f"馬番{h.get('Umaban')}" for h in c.get('pattern_a', {}).get('horses', [])[:2]]
            pat_b = [f"馬番{h.get('Umaban')}" for h in c.get('pattern_b', {}).get('horses', [])[:2]]
            lines.append(f"CASPER パターンA: {', '.join(pat_a)} / パターンB: {', '.join(pat_b)}")

    return "\n".join(lines) if lines else "（予測サマリー生成失敗）"


def run_magi_retrospective(
    df: pd.DataFrame,
    magi_prediction: dict,
    actual_result: dict,
    api_key: str,
    meta: dict = None,
) -> dict:
    """
    メイン関数: 3ユニットが回顧セッションを実行する。

    Args:
        df: アプリの解析済みDataFrame（Ranking Table）
        magi_prediction: run_magi_deliberation の結果 dict
        actual_result: fetch_comprehensive_result の結果 dict
        api_key: Gemini API Key
        meta: レース情報（course_profile等）

    Returns: {
        'melchior': dict,  # 各ユニットの回顧JSON
        'balthasar': dict,
        'casper': dict,
        'summary': dict,   # 総合サマリー（的中/外れ等）
    }
    """
    # テキスト化
    race_text = format_ranking_table_for_retro(df)
    prediction_summary = build_magi_prediction_summary(magi_prediction)
    actual_result_text = format_actual_result(actual_result)

    # 訓練済み知識を注入
    try:
        from core.magi_trainer import generate_training_insight, load_weights as _lw
        _insights = generate_training_insight(weights=_lw())
    except Exception:
        _insights = {'melchior': '', 'balthasar': '', 'casper': ''}

    def _with_knowledge(base: str, knowledge: str) -> str:
        if not knowledge:
            return base
        return base + f"\n\n{knowledge}"

    prompt = build_retro_prompt(race_text, prediction_summary, actual_result_text)

    # 各ユニット実行（間隔3秒）
    mel_res = _call_retro_unit(
        'MELCHIOR',
        _with_knowledge(MELCHIOR_RETRO_PERSONA, _insights.get('melchior', '')),
        prompt, api_key, temperature=0.25
    )
    time.sleep(3)

    bal_res = _call_retro_unit(
        'BALTHASAR',
        _with_knowledge(BALTHASAR_RETRO_PERSONA, _insights.get('balthasar', '')),
        prompt, api_key, temperature=0.3
    )
    time.sleep(3)

    cas_res = _call_retro_unit(
        'CASPER',
        _with_knowledge(CASPER_RETRO_PERSONA, _insights.get('casper', '')),
        prompt, api_key, temperature=0.75
    )

    # 総合評価サマリー計算
    hit_count = sum(
        1 for r in [mel_res, bal_res, cas_res]
        if r.get('prediction_accuracy', '') == '的中'
    )

    # 実際の着順上位3頭を抽出
    actual_top3 = sorted(
        [(ub, h.get('Rank', 99)) for ub, h in actual_result.get('horses', {}).items()],
        key=lambda x: x[1]
    )[:3]
    actual_top3_ubs = [str(ub) for ub, _ in actual_top3]

    # MAGI予測との照合
    pred_horses = magi_prediction.get('final_prediction', {}).get('horses', [])
    pred_ubs = [str(h.get('umaban')) for h in pred_horses[:3]]
    hit_ubs = set(pred_ubs) & set(actual_top3_ubs)

    summary = {
        'predicted_top3': pred_ubs,
        'actual_top3': actual_top3_ubs,
        'hits': list(hit_ubs),
        'hit_count': len(hit_ubs),
        'hit_rate_label': f"{len(hit_ubs)}/3",
        'magi_unit_accuracy': {
            'melchior': mel_res.get('prediction_accuracy', '不明'),
            'balthasar': bal_res.get('prediction_accuracy', '不明'),
            'casper': cas_res.get('prediction_accuracy', '不明'),
        },
        'race_text_used': race_text,
        'prediction_summary_used': prediction_summary,
        'actual_result_text': actual_result_text,
    }

    return {
        'melchior': mel_res,
        'balthasar': bal_res,
        'casper': cas_res,
        'summary': summary,
    }

def discuss_interactive_retrospective(session_data: dict, user_text: str, chat_history: list, api_key: str) -> str:
    \"\"\"
    MAGI回顧学習タブでの「人間とAIの対話（どうしたら当てられたか？）」を処理する
    \"\"\"
    import google.genai as genai
    from google.genai import types
    import tempfile
    
    # セッションデータから情報を抽出
    race_id = session_data.get('race_id', '不明')
    magi_pred = session_data.get('magi_pred', {})
    retro_result = session_data.get('retro_result', {})
    summary = retro_result.get('summary', {})
    
    pred_top3 = ", ".join(summary.get('predicted_top3', [])) or "なし"
    actual_top3 = ", ".join(summary.get('actual_top3', [])) or "なし"
    hit_count = summary.get('hit_count', 0)
    
    # 3機の反省の要約を作成
    mel_miss = retro_result.get('melchior', {}).get('key_miss_factor', '')
    bal_miss = retro_result.get('balthasar', {}).get('risk_note', '')
    cas_miss = retro_result.get('casper', {}).get('hidden_signal', '')
    
    sys_prompt = f\"\"\"
あなたは競馬AI「MAGIシステム」のマスターAIです。人間（ユーザー）と共に過去のレースの敗因分析とロジック改善を討論します。

【対象レース: {race_id}】
・MAGI事前予測: {pred_top3}
・実際の結果: {actual_top3}
・的中数: {hit_count}/3

【MAGI各機体の初回分析での反省点】
MELCHIOR: {mel_miss}
BALTHASAR: {bal_miss}
CASPER: {cas_miss}

ユーザーから人間としての視点、直感、または現地で得た情報などが提供されます。
ユーザーの意見に真摯に耳を傾け、「では、今のMAGIシステムのどの変数（MakuriPower, HiddenGemなど）を見直せば、この展開を事前に察知できたか？」を建設的に議論し、学習メモとしてまとめてください。
\"\"\"
    
    prompt = sys_prompt + "\n\n【ここまでの対話】\n"
    for msg in chat_history:
        role = "あなた(MAGI)" if msg["role"] == "assistant" else "人間"
        prompt += f"{role}: {msg['content']}\n"
    prompt += f"\n人間: {user_text}\nあなた(MAGI):"

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.7)
        )
        return response.text
    except Exception as e:
        return f"エラーが発生しました: {e}"
