# -*- coding: utf-8 -*-
"""🎭 新聞のAIコメント欄 — 合議結果(cv.json)を4〜6人格が"解説"する読み物コーナー。

【重要な設計方針】
このモジュールは新しい予想を作らない。core/consensus_view.integrate()が既に出した
結論(本命/相手/穴/消し)をなぞって、各人格の口調で"なぜその判定か"を説明させるだけ。
渡した数値(軸◎〇/穴候補/危険理由/combo数/vh_tier/ダート枠信号等)だけを根拠に語らせ、
展開・脚質・調子等の独自の主観判断(=検証で否定済みの俗説と同型)を作らせない。

生成はGemini API直接呼び出し(core/magi_chat.py::_genと同じ形。取り回しを独立させる
ため本体は変更せず、このモジュールに同型の関数をコピーして使う)。俗説キーワードの
判定リストは magi_chat.py の _QUARANTINE_KEYWORDS を import して使い回す(定義重複回避)。

コスト管理: 生成はSRA解析時に自動実行しない。ユーザーがボタンを押した時だけ
API呼び出しが走り、結果は data/newspaper/{race_id}.commentary.json に保存して
再利用する(同じレースを何度紙面化してもAPIを叩き直さない)。
"""
import os
import re
import json
import time

from core.magi_chat import _QUARANTINE_KEYWORDS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NP_DIR = os.path.join(ROOT, 'data', 'newspaper')

# ── 4〜6人格の定義。役割は「合議結果の解説」に限定(独自予想はさせない) ──
# MAGI回顧(melchior/balthasar/casper)とは別の新規人格セット(用途が異なるため使い回さない)。
COMMENTATORS = {
    'gou':   {'emoji': '🔥', 'name': 'ゴウ',   'role': '攻め派。穴・妙味馬を熱く語る',
              'dialect': '熱血・タメ口'},
    'shizu': {'emoji': '🛡️', 'name': 'シズ',   'role': '堅実派。軸の信頼度とリスクを慎重に語る',
              'dialect': '丁寧語・落ち着いた口調'},
    'kazu':  {'emoji': '📊', 'name': 'カズ',   'role': 'データ派。数値(combo/オッズ/係数)を淡々と読む',
              'dialect': '理系・簡潔'},
    'yomi':  {'emoji': '🔍', 'name': 'ヨミ',   'role': '危険人気馬・消去理由を読む役',
              'dialect': '皮肉屋・鋭い'},
    'nagi':  {'emoji': '🌊', 'name': 'ナギ',   'role': '初心者向けにやさしく全体を要約',
              'dialect': '柔らかい口調・初心者にわかりやすく'},
}

_COST_PER_CALL_YEN = 0.0  # Gemini flash-lite想定の目安(実費は使用量で変動・厳密な単価は明示しない)


def _gen(prompt, api_key, system=None, temperature=0.7, max_tokens=120):
    """core/magi_chat.py::_gen と同じ形。取り回しを独立させるためコピー
    (magi_chat.py本体は回顧機能の別用途のため変更しない)。"""
    import google.genai as genai
    from google.genai import types as gt
    client = genai.Client(api_key=api_key)
    cfg_kwargs = dict(temperature=temperature, max_output_tokens=max_tokens)
    if system:
        cfg_kwargs['system_instruction'] = system
    cfg = gt.GenerateContentConfig(**cfg_kwargs)
    try:
        cfg.thinking_config = gt.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass
    last = None
    for model in ('gemini-2.5-flash-lite', 'gemini-2.5-flash'):
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
            return (resp.text or '').strip()
        except Exception as e:
            last = e
            continue
    raise last if last else RuntimeError('LLM呼び出し失敗')


def _contains_quarantined(text):
    """検証で否定済みの俗説キーワードが含まれるか。"""
    t = str(text or '')
    return any(kw in t for kw in _QUARANTINE_KEYWORDS)


_SYSTEM_TEMPLATE = """あなたは競馬新聞のコメンテーター「{name}」({role})。口調: {dialect}。

【絶対に守ること】
1. あなたは予想家ではない。渡された『合議の結論』(本命/相手/穴/消し)を変えてはいけない。
   その結論に至った根拠(渡された数値・シグナルのみ)を、あなたの役割の視点で解説するだけ。
2. 独自の予想根拠(展開・脚質・調子・血統の主観判断等)を作らないこと。
   渡されていない情報を根拠にしてはいけない。
3. 次のキーワードを理由として使ってはいけない(検証済みで否定済みの俗説):
   {banned}
4. **必ず1文・改行なし・80文字以内**で出力すること。長文・複数段落は厳禁。
   紙面の小さな枠に入る短いコメントであることを常に意識せよ。
   全馬に言及する必要はない。最も語りたい1〜2頭だけに絞ってよい。
"""

_MAX_COMMENT_CHARS = 90


def _build_context(race_id):
    """cv.jsonから合議結果の要約テキストを組み立てる(プロンプトに渡す材料)。"""
    from core import newspaper as npr
    cv = npr.load_consensus(race_id)
    if not cv:
        return None
    records = []
    try:
        v = npr.load_view(race_id)
        records = (v or {}).get('records') or []
    except Exception:
        pass
    by_um = npr._names_by_um(records) if records else {}
    groups = cv.get('groups') or {}
    aim = cv.get('aim') or {}
    danger_reasons = aim.get('danger_reasons') or {}
    edge_reasons = aim.get('edge_reasons') or {}

    def _nm(u):
        try:
            return by_um.get(int(u), '')
        except Exception:
            return ''

    def _list(key):
        return ', '.join(f"{u}{_nm(u)}" for u in (groups.get(key) or []))

    lines = [
        f"レジーム(決着傾向): {cv.get('regime', '')}",
        f"本命: {_list('honmei')}",
        f"相手: {_list('aite')}",
        f"穴: {_list('ana')}",
        f"消し: {_list('keshi')}",
    ]
    if danger_reasons:
        dr = '; '.join(f"{u}番:{'/'.join(v)}" for u, v in list(danger_reasons.items())[:5])
        lines.append(f"危険理由: {dr}")
    if edge_reasons:
        er = '; '.join(f"{u}番:{'/'.join(v)}" for u, v in list(edge_reasons.items())[:5])
        lines.append(f"妙味の根拠: {er}")
    return '\n'.join(lines)


def estimate_cost(n_races, n_personas=None):
    """発行前にユーザーへ見せる概算コール数。金額は変動するため回数のみ返す。
    戻り値: {'calls': int, 'n_races': int, 'n_personas': int}"""
    n_personas = n_personas or len(COMMENTATORS)
    return {'calls': int(n_races) * int(n_personas),
            'n_races': int(n_races), 'n_personas': int(n_personas)}


def generate_commentary(race_id, api_key, personas=None):
    """合議結果を人格ごとに解説させる。戻り値: [{'persona','name','emoji','comment'}...]。

    俗説キーワードを含む発言は1回だけ生成し直し、それでも含まれる場合はその発言を
    スキップする(コメント欄に出さない)。API呼び出し失敗は該当人格をスキップし継続。
    """
    ctx = _build_context(race_id)
    if not ctx:
        return []
    personas = personas or COMMENTATORS
    banned = '、'.join(_QUARANTINE_KEYWORDS)
    out = []
    for pid, p in personas.items():
        system = _SYSTEM_TEMPLATE.format(
            name=p['name'], role=p['role'], dialect=p['dialect'], banned=banned)
        prompt = f"【今回の合議結果】\n{ctx}\n\n上記だけを根拠に、あなたの役割でコメントしてください。"
        comment = None
        for _attempt in range(2):
            try:
                text = _gen(prompt, api_key, system=system)
            except Exception:
                text = None
                break
            if text:
                # 改行を除去し、紙面の小さな枠に収まるよう長さの安全弁として切り詰める
                # (モデルが指示より長く書くことがあるため・意味の改変ではなく単純truncate)
                text = re.sub(r'\s*\n+\s*', ' ', text).strip()
                if len(text) > _MAX_COMMENT_CHARS:
                    text = text[:_MAX_COMMENT_CHARS - 1] + '…'
            if text and not _contains_quarantined(text):
                comment = text
                break
        if comment:
            out.append({'persona': pid, 'name': p['name'], 'emoji': p['emoji'],
                       'comment': comment})
    return out


def _commentary_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.commentary.json")


def write_commentary_snapshot(race_id, comments):
    if not race_id or not comments:
        return
    try:
        os.makedirs(NP_DIR, exist_ok=True)
        with open(_commentary_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(), 'comments': comments},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def load_commentary(race_id):
    p = _commentary_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None
