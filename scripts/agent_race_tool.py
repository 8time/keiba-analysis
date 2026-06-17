# -*- coding: utf-8 -*-
"""
AUTOMATA エージェント用 レース調査ツール（ブリッジ）

SkyOfficeのAIエージェント（デスクA/B）がこのスクリプトをサブプロセスとして呼び出し、
レースIDから出馬表・指数・ペース・オッズを取得してJSONで返す。

Usage:
    python scripts/agent_race_tool.py <race_id>

Output: stdout に JSON（1行）。エラー時も {"error": "..."} をJSONで返す。

既存の core.scraper / core.calculator をそのまま利用（関数シグネチャ変更なし）。
"""
import sys
import os
import io
import json

# ── UTF-8固定（cp932対策） ──────────────────────────────────────────
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ── keiba_analysis ルートを import パスに追加 ──────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def clean_name(s):
    if not isinstance(s, str):
        return str(s) if s is not None else ''
    for emoji in ['💪', '🧬', '⚡', '🔥', '🎯', '◎', '○', '▲', '△']:
        s = s.replace(emoji, '')
    return s.strip()


def safe(v):
    """NaN や numpy 型を JSON 安全な値に変換。"""
    try:
        import math
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    try:
        import numpy as np
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            f = float(v)
            return None if f != f else round(f, 2)
    except Exception:
        pass
    if isinstance(v, float):
        return round(v, 2)
    return v


def analyze_race(race_id):
    """レースIDから出馬表・指数・ペースを解析して dict を返す（CLI/API共通ロジック）。
    エラー時も {"error": ...} を含む dict を返す。"""
    race_id = str(race_id).strip()

    # 12桁の数字を抽出（URLや文章が渡された場合に対応）
    import re
    m = re.search(r'(\d{12})', race_id)
    if m:
        race_id = m.group(1)
    elif not race_id.isdigit():
        return {"error": f"invalid race_id: {race_id}"}

    result = {"raceId": race_id, "horses": [], "pace": None, "meta": {}, "source": "keiba_analysis"}

    try:
        from core import scraper, calculator
    except Exception as e:
        return {"error": f"import failed: {e}", "raceId": race_id}

    # ── 出馬表取得 ──
    try:
        df = scraper.get_race_data(race_id)
    except Exception as e:
        return {"error": f"get_race_data failed: {e}", "raceId": race_id}

    if df is None or len(df) == 0:
        return {"error": "no race data found", "raceId": race_id}

    # ── 指数計算（各ステップを try で保護） ──
    try:
        df = calculator.calculate_battle_score(df)
    except Exception as e:
        result["meta"]["battle_score_error"] = str(e)[:120]
    try:
        df = calculator.calculate_n_index(df)
    except Exception as e:
        result["meta"]["n_index_error"] = str(e)[:120]

    # ── ペース分析 ──
    try:
        pace = calculator.analyze_pace_profile(df)
        if isinstance(pace, dict):
            result["pace"] = {k: safe(v) for k, v in pace.items() if not isinstance(v, (list, dict))}
    except Exception as e:
        result["meta"]["pace_error"] = str(e)[:120]

    # ── レースメタ情報 ──
    for col in ['RaceName', 'CurrentDistance', 'CurrentSurface', 'Venue']:
        if col in df.columns:
            try:
                val = df.iloc[0].get(col)
                result["meta"][col] = safe(val)
            except Exception:
                pass

    # ── 馬ごとのデータ抽出 ──
    name_col = 'Name' if 'Name' in df.columns else None
    useful_cols = ['Umaban', 'Odds', 'Popularity', 'OguraIndex', 'BattleScore',
                   'NIndex', 'SiteIndex', 'Weight', 'Jockey', 'Trainer']

    for _, row in df.iterrows():
        horse = {}
        if name_col:
            horse['name'] = clean_name(row.get(name_col))
        for col in useful_cols:
            if col in df.columns:
                horse[col] = safe(row.get(col))
        result["horses"].append(horse)

    # 馬番でソート
    try:
        result["horses"].sort(key=lambda h: (h.get('Umaban') is None, h.get('Umaban') or 999))
    except Exception:
        pass

    return result


def main():
    if len(sys.argv) < 2:
        print("@@@AGENT_JSON@@@" + json.dumps({"error": "race_id required"}, ensure_ascii=False))
        return
    result = analyze_race(sys.argv[1])
    # マーカー付きで出力（scraper/calculatorのデバッグ出力と区別するため）
    print('@@@AGENT_JSON@@@' + json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
