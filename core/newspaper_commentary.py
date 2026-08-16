# -*- coding: utf-8 -*-
"""🎭 新聞のAIコメント欄 — 5人格が"それぞれ別のシグナル"を担当して予想する読み物コーナー。

【設計方針(2026-07-23 改訂)】
旧版は「合議の結論をなぞって80字で解説させるだけ」だった。俗説の捏造を防ぐ狙いは
正しかったが、渡す情報を結論だけに絞り+80字1文+思考OFFにしたため、構造的に中身の
薄いコメントしか出せなかった(ユーザー評価:「全然ダメ」)。

新版の考え方 ―― LLMに自由に予想させるのでも、結論をなぞらせるのでもなく、
**人格ごとに「見る列」を変える**。このアプリには互いに独立した検証済みシグナルが
複数あり、それらは実際に別々の馬を推す(末脚top3 ≠ 補正Ttop3 ≠ LTR上位)。
よって予想は捏造なしに自然に割れる。各人格には
  ・フルCSV(全108列) ・データ辞書 ・自分の担当列と有効な人気帯
を渡し、担当列だけを根拠に◎を1頭選ばせる。

⚠ 正直な前提: 各人格単独の◎は「それ単体で儲かる」と検証されたものではない。
検証済みなのは『独立シグナルが一致すると複勝率が上がる』(votes=3で複勝27%)という点。
よって紙面での価値は一致/不一致にあり、ナギ(まとめ役)の集計はPython側で決定的に行う
(LLMに数えさせない)。個々の◎を「買え」と読ませる作りにはしないこと。

俗説キーワードの判定リストは magi_chat.py の _QUARANTINE_KEYWORDS を使い回す。

コスト管理: SRA解析時には自動実行しない。ボタンを押した時だけAPIが走り、結果は
data/newspaper/{race_id}.commentary.json に保存して再利用する。
1レース≒4円想定(gemini-3.5-flash-lite・入力$0.30/1M・出力$2.50/1M)。
"""
import os
import re
import json
import time

from core.magi_chat import _QUARANTINE_KEYWORDS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NP_DIR = os.path.join(ROOT, 'data', 'newspaper')

# Gemini 3.x系。3.5-flash-liteは公式に「ペルソナの一貫性」と「表形式データ処理」が
# 向上したモデルとされており、この用途(人格×表読み)に合う。1M context/64k output。
MODEL_CHAIN = ('gemini-3.5-flash-lite', 'gemini-3.6-flash')
# 思考レベル。Gemini 3.xでは thinking_budget が thinking_level(文字列)に置き換わった。
# 表を読んで1頭選ぶ判断が要るため MINIMAL では浅い → LOW を既定にする。
THINKING_LEVEL = 'LOW'

# ── 5人格。それぞれ「担当する検証済みシグナル(lens)」と「有効な人気帯(rule)」を持つ ──
# rule はデータ辞書に書かれた検証結果をそのまま人格の行動制約にしたもの。
# これがあるので、例えばゴウが人気馬を◎にすることはない(末脚は人気薄限定のエッジ)。
COMMENTATORS = {
    'gou': {
        'emoji': '🔥', 'name': 'ゴウ', 'role': '攻め派。人気薄の妙味馬を熱く語る',
        'dialect': '熱血・タメ口', 'mode': 'pick',
        'lens': 'SpurtIdx(末脚指数) / Lap33(33ラップ) / 🧩シグナル重複数',
        'band': 'longshot',
        'rule': 'これらは6番人気以下でのみ有効な検証済みエッジ(人気上位では市場に織込み済みで効果ゼロ)。'
                'よって◎は必ず6番人気以下から選ぶこと。5番人気以内を選んではいけない。',
    },
    'shizu': {
        'emoji': '🛡️', 'name': 'シズ', 'role': '堅実派。軸の信頼度を慎重に見る',
        'dialect': '丁寧語・落ち着いた口調', 'mode': 'pick',
        'lens': 'CorrectedT(補正T) / JPower(騎手力) / Trainer末尾の🔴(厩舎当コース勝率)',
        'band': 'favorite',
        'rule': '補正Tは人気上位の「本命補強」に有効(+5pp)で人気薄には弱い(+1pp)。'
                'よって◎は5番人気以内から選ぶこと。ただし危険材料が付いた馬は軸にしない。',
    },
    'kazu': {
        'emoji': '📊', 'name': 'カズ', 'role': 'データ派。市場とモデルの評価を淡々と読む',
        'dialect': '理系・簡潔・断定調', 'mode': 'pick',
        'lens': 'LTR(検証AI) / Odds / OddsGap(オッズ断層) / Popularity',
        'band': 'all',
        'rule': 'LTRとオッズは市場情報を内包する(=人気と近い動きをする)。'
                'その前提を自覚した上で、市場が最も高く評価している馬を◎にすること。'
                '妙味を語る役ではない。数値の読み上げに徹する。',
    },
    'yomi': {
        'emoji': '🔍', 'name': 'ヨミ', 'role': '消し屋。危険な人気馬を指摘する',
        'dialect': '皮肉屋・鋭い', 'mode': 'cut',
        'lens': '危険材料 / RiskFlags / Stress / 合議役割の✖切る',
        'band': 'cut',
        'rule': 'あなただけは買う馬ではなく「軸にすべきでない人気馬」を1頭挙げる。'
                '危険材料は複勝残差-5pp級だが来る確率も45-60%残るため、'
                '「消し」ではなく「軸回避」と表現すること。5番人気以内から選ぶ。',
    },
    'nagi': {
        'emoji': '🌊', 'name': 'ナギ', 'role': '初心者向けに全体をやさしくまとめる',
        'dialect': '柔らかい口調・専門用語を使わない', 'mode': 'summary',
        'lens': '他4人の結論(Python側で集計済み)',
        'rule': '自分では予想しない。4人の意見が割れたか一致したかだけを伝える。',
    },
}

_COST_PER_CALL_YEN = 0.0  # 実費は使用量で変動するため金額は明示しない(回数のみ返す)
_MAX_COMMENT_CHARS = 160  # 紙面枠の安全弁(旧90字→拡大)。意味の改変でなく単純truncate


def _gen(prompt, api_key, system=None, temperature=None, max_tokens=1500,
         as_json=False):
    """Gemini呼び出し。Gemini 3.x のAPI変更に対応済み。

    ⚠ temperature は Gemini 3.x で非推奨(APIに無視され、将来世代では400エラー)。
      呼び出し側の互換のため引数は残すが**使用しない**。出力の振れ幅は
      system指示(人格・口調)で作ること。
    ⚠ thinking_budget も Gemini 3.x で thinking_level(文字列)に置き換わった。
      旧モデルへフォールバックした時のために両方を試す。
    """
    import google.genai as genai
    from google.genai import types as gt
    client = genai.Client(api_key=api_key)
    cfg_kwargs = dict(max_output_tokens=max_tokens)
    if system:
        cfg_kwargs['system_instruction'] = system
    if as_json:
        # 思考テキストが混ざってJSONパースが壊れるのを防ぐ(3.xは思考を完全OFFにできない)
        cfg_kwargs['response_mime_type'] = 'application/json'
    from core import gemini_compat as _gc
    last = None
    for model in MODEL_CHAIN:
        # 思考設定はモデル世代で引数が違う(core/gemini_compat.py)。フォールバックで
        # 世代が混ざるためcfgはモデルごとに作る。
        cfg = _gc.apply_thinking(gt.GenerateContentConfig(**cfg_kwargs), gt, model,
                                 level=THINKING_LEVEL)
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


def _tidy(text):
    """モデルの独り言を落とす。改行を潰し、末尾の自己申告(例「（97文字）」)を除去。"""
    t = re.sub(r'\s*\n+\s*', ' ', str(text or '')).strip()
    t = re.sub(r'[（(]\s*\d+\s*文字\s*[)）]\s*$', '', t).strip()
    return t


def _parse_json(text):
    """モデル出力からJSONを取り出す。response_mime_type指定でも保険を掛ける。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r'\{.*\}', str(text), re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


_PICK_SYSTEM = """あなたは競馬新聞のコメンテーター「{name}」({role})。口調: {dialect}。

【あなたの担当データ】
{lens}

【あなたの行動制約(検証結果に基づく・必ず守る)】
{rule}

【絶対に守ること】
1. 添付CSVのうち**担当データの列だけ**を根拠に判断すること。担当外の列を主な理由にしない。
   他の人格が別の列を担当しているので、あなたは自分の持ち場に徹すればよい。
2. 次のキーワードを理由にしてはいけない(大規模検証で否定済みの俗説):
   {banned}
3. データに無いこと(調子・気配・厩舎コメント等)を想像で語らない。
4. コメントは1〜2文・120文字以内。**馬名だけを書き、馬番は書かない**
   (馬番は編集部が正しいものを付けるため、あなたが書くと二重になる)。
5. 出力は次のJSONのみ。horse は候補リストの馬名を**一字一句そのまま**書くこと:
   {{"horse": "<馬名>", "comment": "<コメント>"}}
"""

_SUMMARY_SYSTEM = """あなたは競馬新聞のまとめ役「ナギ」。口調: 柔らかく、専門用語を使わない。

【役割】
4人のコメンテーターがそれぞれ違うデータを見て出した結論を、競馬初心者に一言で伝える。
あなた自身は予想しない。「誰の意見が合ったか/割れたか」だけを伝える。

【絶対に守ること】
1. 渡された集計結果の数字を変えない。自分で数え直さない。
2. 意見が割れている場合は「難しいレース」、一致している場合は「わかりやすいレース」と伝える。
   ただし「儲かる」「当たる」等の断定はしない。
3. 1〜2文・120文字以内。専門用語(残差・エッジ・シグナル等)を使わない。
4. 出力はコメント本文のみ(JSONにしない)。
"""


def _load_race_payload(race_id):
    """LLMに渡す材料。フルCSV + データ辞書 + 合議の結論(参考)。

    旧版は合議の結論だけを渡していたため各人格が同じ結論をなぞるしかなかった。
    フルCSVを渡すことで、人格ごとに別の列を根拠にできるようになる。
    """
    from core import newspaper as npr
    try:
        csv_bytes, n_rows, n_cols = npr.build_csv_bytes(race_id)
    except Exception:
        csv_bytes, n_rows, n_cols = None, 0, 0
    if not csv_bytes:
        return None
    try:
        csv_text = csv_bytes.decode('utf-8-sig')
    except Exception:
        csv_text = csv_bytes.decode('utf-8', errors='replace')
    return {
        'csv': csv_text, 'n_rows': n_rows, 'n_cols': n_cols,
        'dict': npr.csv_data_dictionary(),
        'names': _names_map(race_id),
    }


def _names_map(race_id):
    """{馬番: 馬名} 。集計結果の表示に使う。"""
    from core import newspaper as npr
    try:
        v = npr.load_view(race_id)
        return npr._names_by_um((v or {}).get('records') or [])
    except Exception:
        return {}


def _pop_map(race_id):
    """{馬番: 人気(int)} 。人気帯ルールをPython側で強制するために使う。"""
    from core import newspaper as npr
    out = {}
    try:
        v = npr.load_view(race_id)
        for r in ((v or {}).get('records') or []):
            try:
                um = int(r.get('Umaban'))
            except (TypeError, ValueError):
                continue
            m = re.search(r'\d+', str(r.get('Popularity') or ''))
            if m:
                out[um] = int(m.group(0))
    except Exception:
        pass
    return out


def _clean_name(nm):
    """馬名から表示装飾(🔥/💎/括弧)を落とす。同一性の照合用。"""
    s = re.sub(r'[（(].*?[)）]', '', str(nm or ''))
    return re.sub(r'[\s\U0001F300-\U0001FAFF☆★◎〇○▲△✖✕]+', '', s)


def _resolve_umaban(horse, cands):
    """LLMが返した馬名 → 馬番。候補リスト内でのみ照合する(表記ゆれは装飾除去で吸収)。
    見つからなければ None(呼び元が再生成する)。"""
    key = _clean_name(horse)
    if not key:
        return None
    for um, nm in cands:
        if _clean_name(nm) == key:
            return um
    for um, nm in cands:           # 部分一致(モデルが装飾を足した場合の保険)
        c = _clean_name(nm)
        if c and (c in key or key in c):
            return um
    return None


def _candidates(mode, names, pops):
    """人格の有効人気帯に合う候補馬だけを返す。

    検証済みの帯限定ルール(末脚/33ラップ=6番人気以下、補正T=5番人気以内)は
    LLMの遵守に任せず**Python側で候補を絞って**強制する。実測で、帯を口頭で
    指示しただけでは違反した(シズが11番人気を選んだ)ため。
    戻り値: [(馬番, 馬名)...] 人気順。
    """
    items = []
    for um, nm in names.items():
        p = pops.get(um)
        if p is None:
            continue
        if mode == 'longshot' and p < 6:
            continue
        if mode in ('favorite', 'cut') and p > 5:
            continue
        items.append((p, um, _clean_name(nm)))
    items.sort()
    return [(um, nm) for _p, um, nm in items]


def _tally(picks):
    """Python側で決定的に集計する(LLMに数えさせない)。

    picks: [{'persona','mode','umaban'}...]
    戻り値: {'agree_um': 最多一致の馬番 or None, 'agree_n': 一致人数,
             'split': bool(意見が割れたか), 'buyers': 買い判断の人数}
    """
    from collections import Counter
    buy = [p['umaban'] for p in picks
           if p.get('mode') == 'pick' and p.get('umaban') is not None]
    if not buy:
        return {'agree_um': None, 'agree_n': 0, 'split': True, 'buyers': 0}
    c = Counter(buy).most_common(1)[0]
    return {'agree_um': c[0], 'agree_n': c[1], 'split': c[1] < 2, 'buyers': len(buy)}


def estimate_cost(n_races, n_personas=None):
    """発行前にユーザーへ見せる概算コール数。金額は変動するため回数のみ返す。
    戻り値: {'calls': int, 'n_races': int, 'n_personas': int}"""
    n_personas = n_personas or len(COMMENTATORS)
    return {'calls': int(n_races) * int(n_personas),
            'n_races': int(n_races), 'n_personas': int(n_personas)}


def generate_commentary(race_id, api_key, personas=None):
    """5人格にそれぞれ別のシグナルを担当させて予想させる。

    戻り値: [{'persona','name','emoji','comment','umaban','pick_name','lens','mode'}...]
    (旧版の 'persona'/'name'/'emoji'/'comment' キーは維持しているので既存の紙面
     レンダラーはそのまま動く。umaban等は追加分)

    俗説キーワードを含む発言は1回だけ生成し直し、それでも含まれる場合はスキップ。
    API呼び出し失敗は該当人格をスキップして継続する。
    """
    payload = _load_race_payload(race_id)
    if not payload:
        return []
    personas = personas or COMMENTATORS
    banned = '、'.join(_QUARANTINE_KEYWORDS)
    names = payload['names']
    pops = _pop_map(race_id)
    base = (f"【データ辞書】\n{payload['dict']}\n\n"
            f"【今回のレース全データ({payload['n_rows']}頭×{payload['n_cols']}列)】\n"
            f"{payload['csv']}")

    out, picks = [], []
    # ── 1st pass: 予想する人格(pick/cut) ──
    for pid, p in personas.items():
        if p.get('mode') == 'summary':
            continue
        # 有効人気帯の候補をPython側で確定させる。CSVは予測順(Rank)で並ぶため
        # 馬番と行位置の取り違えが起きる(実測: シズが3番の馬名で馬番2を返した)。
        # 選択肢を明示し、帯違反と取り違えは下の検証で機械的に弾く。
        cands = _candidates(p.get('band', 'all'), names, pops)
        if not cands:
            continue
        allow = {um for um, _nm in cands}
        cand_txt = '、'.join(f"{um}番{nm}" for um, nm in cands)
        system = _PICK_SYSTEM.format(
            name=p['name'], role=p['role'], dialect=p['dialect'],
            lens=p['lens'], rule=p['rule'], banned=banned)
        verb = ('軸にすべきでない人気馬を1頭' if p.get('mode') == 'cut'
                else '◎(本命)を1頭')
        prompt = (f"{base}\n\n【あなたが選べる馬(この中から必ず選ぶこと)】\n{cand_txt}\n\n"
                  f"上記から、あなたの担当データだけを根拠に{verb}選び、JSONで答えてください。"
                  f"馬番と馬名の対応を間違えないこと。")
        rec = None
        for _attempt in range(2):
            try:
                raw = _gen(prompt, api_key, system=system, as_json=True)
            except Exception:
                break
            d = _parse_json(raw)
            if not d:
                continue
            cmt = _tidy(d.get('comment'))
            if len(cmt) > _MAX_COMMENT_CHARS:
                cmt = cmt[:_MAX_COMMENT_CHARS - 1] + '…'
            if not cmt or _contains_quarantined(cmt):
                continue
            # 馬名→馬番はPython側で引く。LLMに馬番を答えさせると取り違える
            # (実測: umaban=8 と答えつつコメントは「14番ミヤラティーニ」)。
            # 馬名は一意なので、名前で受けて番号をこちらで付ければ整合が保証される。
            um = _resolve_umaban(d.get('horse'), cands)
            if um is None or um not in allow:   # 候補外/解決不能 → 再生成
                continue
            # 保険: コメント本文に"他馬"の名前が混ざっていないか
            mine = _clean_name(names.get(um, ''))
            others = [_clean_name(n) for u, n in names.items()
                      if u != um and len(_clean_name(n)) >= 3]
            body = _clean_name(cmt)
            if any(o and o in body for o in others) and mine not in body:
                continue
            rec = {'persona': pid, 'name': p['name'], 'emoji': p['emoji'],
                   'comment': cmt, 'umaban': um,
                   'pick_name': names.get(um, ''),
                   'pop': pops.get(um),
                   'lens': p['lens'], 'mode': p.get('mode')}
            break
        if rec:
            out.append(rec)
            picks.append(rec)

    # ── 2nd pass: まとめ役(集計はPythonで確定させ、LLMは言い換えるだけ) ──
    sm = personas.get('nagi')
    if sm and picks:
        t = _tally(picks)
        agree_nm = names.get(t['agree_um'], '') if t['agree_um'] is not None else ''
        lines = [f"{p['name']}({'軸回避' if p.get('mode') == 'cut' else '本命'}): "
                 f"{p['umaban']}番{p['pick_name']}" for p in picks]
        stat = (f"買いの本命を出したのは{t['buyers']}人。"
                + (f"うち{t['agree_n']}人が{t['agree_um']}番{agree_nm}で一致。"
                   if t['agree_n'] >= 2 else "全員バラバラで一致なし。"))
        prompt = ("【4人の結論】\n" + '\n'.join(lines)
                  + f"\n\n【集計(この数字は変えないこと)】\n{stat}\n\n"
                    "初心者向けに一言でまとめてください。")
        try:
            cmt = _tidy(_gen(prompt, api_key, system=_SUMMARY_SYSTEM, max_tokens=600))
            if len(cmt) > _MAX_COMMENT_CHARS:
                cmt = cmt[:_MAX_COMMENT_CHARS - 1] + '…'
            if cmt and not _contains_quarantined(cmt):
                out.append({'persona': 'nagi', 'name': sm['name'], 'emoji': sm['emoji'],
                            'comment': cmt, 'umaban': None, 'pick_name': '',
                            'lens': sm['lens'], 'mode': 'summary',
                            'tally': t})
        except Exception:
            pass
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
