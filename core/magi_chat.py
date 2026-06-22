# -*- coding: utf-8 -*-
"""
MAGI おしゃべりルーム (Post-race interview-style learning)

レース後、3人格(MELCHIOR/BALTHASAR/CASPER)が競馬初心者のユーザーに
「やさしい質問」を1つずつ投げかけ、ユーザーは普通の言葉で答えるだけ。
裏側で会話を構造化して回顧台帳(data/retro_ledger.json)に学習データとして蓄積する。

設計思想:
- UIはチャット1往復ずつ。画面のテキストは最小限(質問は2文以内)。
- 3人格 = それぞれ検証済みエッジの担当:
    MELCHIOR (🔴 危険な人気馬を見抜く)
    BALTHASAR(🟢 見落とした勝ち馬を拾う ← 中核目標: 過小評価の勝ち馬)
    CASPER  (🔵 レースの流れ・荒れを読む)
- ガードレール: 1回の会話で重みは変えない。タグは「3回以上 + バックテスト」で初めて採用検討
  (core/elim_reasons.py の『条件タグ3回』方式を踏襲)。
- 検証で否定された俗説(初ブリ/距離短縮/季節/ショッカー/展開恩恵/巻き返し 等)に当たるタグは
  隔離フラグ(quarantined)を立て、安易な採用を止める。
"""
import os
import json
import re
import time
from datetime import datetime

LEDGER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'retro_ledger.json'
)

PERSONAS = {
    'melchior': {'emoji': '🔴', 'name': 'MELCHIOR', 'jp': 'メルキオール', 'color': '#e74c3c',
                 'role': '危険な人気馬を見抜く（科学者）', 'dialect': '関西弁'},
    'balthasar': {'emoji': '🟢', 'name': 'BALTHASAR', 'jp': 'バルタザール', 'color': '#2ecc71',
                  'role': '見落とした勝ち馬を拾う（母）', 'dialect': '京都弁'},
    'casper': {'emoji': '🔵', 'name': 'CASPER', 'jp': 'キャスパー', 'color': '#3498db',
               'role': 'レースの流れ・荒れを読む（女）', 'dialect': '標準語'},
}

# 検証で否定済み = タグが当たったら隔離する俗説キーワード(memory参照)
_QUARANTINE_KEYWORDS = [
    '初ブリンカー', '初ブリ', 'ブリンカー', '距離短縮', '短縮', 'お帰り', '休み明け',
    '季節', '初ダート', 'ショッカー', 'Mの法則', '展開恩恵', '好位', '巻き返し',
    '圧勝', 'PCI', '脚質',
]


# ─────────────────────────────────────────────────────────────
#  コンテキスト構築（コンパクト・LLM用）
# ─────────────────────────────────────────────────────────────
def build_context(df=None, magi_pred=None, actual_result=None, meta=None):
    """会話セッション全体で使う、短いレースコンテキスト文字列を作る。"""
    meta = meta or {}
    lines = []

    # 実結果 上位
    actual_top = []
    if actual_result and actual_result.get('horses'):
        horses_sorted = sorted(
            actual_result['horses'].items(),
            key=lambda x: x[1].get('Rank', 99)
        )
        for ub, h in horses_sorted[:5]:
            actual_top.append({
                'rank': h.get('Rank', '?'), 'umaban': ub,
                'name': h.get('Name', f'馬番{ub}'),
                'pop': h.get('Popularity', '-'),
                'agari': h.get('Agari', '-'),
                'passing': h.get('Passing', '-'),
            })
    if actual_top:
        lines.append('【実際の結果】')
        for h in actual_top:
            lines.append(
                f"  {h['rank']}着 {h['name']}（{h['pop']}番人気 / 上がり{h['agari']} / 通過{h['passing']}）"
            )

    # MAGI事前予測 TOP3
    pred_ubs = []
    if magi_pred and magi_pred.get('final_prediction'):
        ph = magi_pred['final_prediction'].get('horses', [])
        if ph:
            lines.append('【MAGIが本命にした馬(事前)】')
            for h in ph[:3]:
                lines.append(f"  馬番{h.get('umaban')} {h.get('name','?')}")
                pred_ubs.append(str(h.get('umaban')))

    # 取りこぼし候補: 人気薄(5番人気以下)で3着内に来た馬
    missed = [h for h in actual_top
              if str(h['rank']).isdigit() and int(h['rank']) <= 3
              and str(h['pop']).isdigit() and int(h['pop']) >= 5]
    if missed:
        lines.append('【穴で来た馬(人気薄なのに上位)】')
        for h in missed:
            lines.append(f"  {h['rank']}着 {h['name']}（{h['pop']}番人気）")

    return {
        'text': "\n".join(lines) if lines else '（レース情報なし）',
        'actual_top': actual_top,
        'pred_ubs': pred_ubs,
        'missed': missed,
    }


def result_one_line(ctx):
    """画面上部に出す1行サマリー。"""
    at = ctx.get('actual_top') or []
    if not at:
        return '結果を取得できませんでした'
    parts = []
    for h in at[:3]:
        parts.append(f"{h['rank']}着 {h['name']}({h['pop']}人気)")
    return '　→　'.join(parts)


# ─────────────────────────────────────────────────────────────
#  LLM 呼び出し
# ─────────────────────────────────────────────────────────────
def _gen(prompt, api_key, system=None, temperature=0.6, max_tokens=400):
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


def _parse_json(raw):
    if not raw:
        return None
    cleaned = re.sub(r'```(?:json)?', '', raw).strip()
    s = cleaned.find('{')
    e = cleaned.rfind('}')
    if s == -1 or e <= s:
        return None
    try:
        return json.loads(cleaned[s:e + 1])
    except Exception:
        return None


_TURN_SYSTEM = """あなたは競馬AI「MAGIシステム」。3つの人格が、競馬初心者のユーザーとレース後におしゃべりします。
目的は、初心者が友人との競馬談義についていけるよう、レースで「何が起きたか」「どんなサインがあったか」を
やさしい質問でそっと引き出すことです。

人格の担当と話し方:
- melchior(🔴): 人気だったのに負けた馬の「危険サイン」に気づけたか。関西弁で話す（例:「〜やねん」「〜やろ？」「ほんま」「あかん」「ちゃう」）
- balthasar(🟢): 穴で来た(人気薄なのに上位の)馬の「見抜けるヒント」がなかったか ← 一番大事。京都弁で話す（例:「〜どすえ」「〜はりますか？」「よろしおすなぁ」「〜どすなぁ」「えらい」）
- casper(🔵): レースの流れ・展開・荒れ方で驚いたこと。標準語（東京）で話す（丁寧だがフランクな口調）

ルール:
- 1回につき1人格だけが、短い質問を1つだけする(2文以内)。専門用語は噛み砕く。
- 各人格は必ず自分の方言・話し方で質問する。方言を混ぜずに一貫させる。
- 初心者がYes/Noか具体例で気軽に答えられる質問にする。説教・長文・複数質問は禁止。
- すでに聞いた話は繰り返さない。会話が4往復ほど進んだら、誰かがやさしく締める(done=true)。
- 締めるときの message は「今日はここまで。お疲れさま」程度の一言でよい（各自の方言で）。

出力は必ず次のJSONのみ(```不要):
{"persona":"melchior|balthasar|casper","message":"質問文(2文以内)","done":false}"""


def magi_turn(ctx, chat, api_key):
    """次に話す人格と、短い質問を1つ生成して返す。

    Args:
        ctx: build_context の戻り
        chat: [{'role':'magi'/'user','persona':..,'message':..}, ...]
    Returns: {'persona':str,'message':str,'done':bool}
    """
    convo = []
    for m in chat:
        if m.get('role') == 'user':
            convo.append(f"ユーザー: {m['message']}")
        else:
            p = PERSONAS.get(m.get('persona'), {})
            convo.append(f"{p.get('name','MAGI')}: {m['message']}")
    convo_text = "\n".join(convo) if convo else "（まだ会話なし。最初の質問をする）"

    prompt = (
        f"━ レース概要 ━\n{ctx.get('text','')}\n\n"
        f"━ ここまでの会話 ━\n{convo_text}\n\n"
        "次に話す人格を1つ選び、ユーザーへの短い質問を1つ作ってJSONで出力せよ。"
    )
    raw = _gen(prompt, api_key, system=_TURN_SYSTEM, temperature=0.7, max_tokens=300)
    obj = _parse_json(raw)
    if not obj or obj.get('persona') not in PERSONAS:
        # フォールバック: 中核目標のbalthasarが安全な質問をする
        return {'persona': 'balthasar',
                'message': 'このレースで「あれっ?」と思ったことや、気になった馬はいた?',
                'done': False}
    return {
        'persona': obj['persona'],
        'message': str(obj.get('message', '')).strip() or 'どう感じた?',
        'done': bool(obj.get('done', False)),
    }


_EXTRACT_SYSTEM = """あなたは競馬の学習アシスタント。レース後のおしゃべりログから、
あとで検証(バックテスト)するための学習メモを抽出します。
ユーザーは初心者なので、本人の言葉(原文)を大切にしつつ、検証できる短い名詞句タグに整理してください。
誇張や決めつけはしない。会話に無い情報を創作しない。

出力は必ず次のJSONのみ(```不要):
{
 "key_takeaways": ["学んだこと(短文, 最大3)"],
 "missed_winner_signs": ["穴で来た勝ち馬の事前サイン(あれば)"],
 "danger_popular_signs": ["危険だった人気馬のサイン(あれば)"],
 "user_observations": ["ユーザー本人の気づき原文(最大3)"],
 "signal_tags": ["検証候補の短いタグ(名詞句, 最大5)"]
}"""


def extract_learning(ctx, chat, api_key):
    """会話から学習レコードを抽出する。"""
    convo = []
    for m in chat:
        if m.get('role') == 'user':
            convo.append(f"ユーザー: {m['message']}")
        else:
            p = PERSONAS.get(m.get('persona'), {})
            convo.append(f"{p.get('name','MAGI')}: {m['message']}")
    prompt = (
        f"━ レース概要 ━\n{ctx.get('text','')}\n\n"
        f"━ おしゃべりログ ━\n" + "\n".join(convo) + "\n\n"
        "上記からJSONで学習メモを抽出せよ。"
    )
    try:
        raw = _gen(prompt, api_key, system=_EXTRACT_SYSTEM, temperature=0.2, max_tokens=600)
        obj = _parse_json(raw) or {}
    except Exception as e:
        obj = {'_error': str(e)}
    for k in ('key_takeaways', 'missed_winner_signs', 'danger_popular_signs',
              'user_observations', 'signal_tags'):
        obj.setdefault(k, [])
    return obj


# ─────────────────────────────────────────────────────────────
#  台帳の保存・集計（3回ルール / 隔離）
# ─────────────────────────────────────────────────────────────
def _load_ledger():
    if not os.path.exists(LEDGER_PATH):
        return []
    try:
        with open(LEDGER_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def is_quarantined(tag):
    t = str(tag)
    return any(kw in t for kw in _QUARANTINE_KEYWORDS)


def save_record(race_id, meta, ctx, chat, learning):
    """1セッションを台帳に追記し、保存後のタグ集計を返す。"""
    ledger = _load_ledger()
    rec = {
        'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'race_id': str(race_id),
        'date': (meta or {}).get('date', ''),
        'place': (meta or {}).get('place', ''),
        'name': (meta or {}).get('name', ''),
        'actual_top': ctx.get('actual_top', []),
        'pred_ubs': ctx.get('pred_ubs', []),
        'chat': chat,
        'learning': learning,
    }
    ledger.append(rec)
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    with open(LEDGER_PATH, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
    return rec, tag_summary(ledger)


def tag_summary(ledger=None):
    """全台帳の signal_tags を集計して {tag: {'count','quarantined','ready'}} を返す。
    ready = 3回以上たまった(=バックテスト検討の入口)。"""
    if ledger is None:
        ledger = _load_ledger()
    counts = {}
    for rec in ledger:
        for tag in (rec.get('learning', {}) or {}).get('signal_tags', []) or []:
            t = str(tag).strip()
            if not t:
                continue
            counts[t] = counts.get(t, 0) + 1
    out = {}
    for t, c in counts.items():
        out[t] = {'count': c, 'quarantined': is_quarantined(t), 'ready': c >= 3 and not is_quarantined(t)}
    return dict(sorted(out.items(), key=lambda x: -x[1]['count']))
