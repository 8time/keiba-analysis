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
def _extract_signals(df, actual_top):
    """解析df(SRA保存 or calculate_battle_score)から、アプリが実際に出したシグナルを抽出。
    検証済みエッジ(末脚/危険人気馬)は✅、それ以外は⚪参考として分け、俗説強化を防ぐ。
    実結果(actual_top)と突き合わせて『当たってたか外したか』も付す。"""
    if df is None or not hasattr(df, 'columns') or getattr(df, 'empty', True):
        return {'verified': [], 'info': [], 'text': ''}
    import pandas as pd

    def has(c):
        return c in df.columns

    res_rank = {}
    for h in (actual_top or []):
        try:
            res_rank[int(h['umaban'])] = int(h['rank'])
        except Exception:
            pass

    verified, info = [], []
    for _, r in df.iterrows():
        try:
            um = int(pd.to_numeric(r.get('Umaban'), errors='coerce'))
        except Exception:
            continue
        nm = str(r.get('Name', f'馬番{um}'))
        pop = pd.to_numeric(r.get('Popularity'), errors='coerce')
        rank = res_rank.get(um)
        came = (rank is not None and rank <= 3)
        # 末脚エッジ(✅検証済み): 人気薄(>=6番)×上がり上位(AgariRank<=3) — verified_spurt_index
        ar = pd.to_numeric(r.get('AgariRank'), errors='coerce') if has('AgariRank') else None
        if ar is not None and ar == ar and ar <= 3 and pop == pop and pop >= 6:
            tag = '→実際に馬券圏内に来た✅' if came else '→今回は届かず'
            verified.append(f"末脚エッジ点灯(人気薄×上がり上位): {um}番{nm}({int(pop)}人気) {tag}")
        # 危険人気馬(✅検証済み): 人気<=3 × Alert(💣/💀)
        al = str(r.get('Alert', '')) if has('Alert') else ''
        if ('💣' in al or '💀' in al) and pop == pop and pop <= 3:
            tag = '→実際に飛んだ✅' if (rank is None or rank > 3) else '→今回は来てしまった'
            verified.append(f"危険人気馬フラグ: {um}番{nm}({int(pop)}人気) {tag}")

    # 総合上位(⚪参考・買い材料として過信しない)
    sc = 'Projected Score' if has('Projected Score') else ('BattleScore' if has('BattleScore') else None)
    if sc:
        t = df.copy()
        t['_s'] = pd.to_numeric(t[sc], errors='coerce')
        names = []
        for _, r in t.sort_values('_s', ascending=False).head(3).iterrows():
            try:
                names.append(f"{int(pd.to_numeric(r.get('Umaban'), errors='coerce'))}番{r.get('Name','')}")
            except Exception:
                pass
        if names:
            info.append("アプリの総合スコア上位: " + " / ".join(names))

    lines = []
    if verified:
        lines.append('【✅アプリが事前に出した検証済みエッジ(自分から具体的に触れてよい)】')
        lines += ['  ' + v for v in verified]
    if info:
        lines.append('【⚪参考情報(買い材料として過信しない)】')
        lines += ['  ' + i for i in info]
    return {'verified': verified, 'info': info, 'text': "\n".join(lines)}


def _horse_table(df, actual_result):
    """全出走馬のコンパクトな表(厩舎/上がり/人気/オッズ/スコア/通過/着順)。
    人格が『厩舎は?』『上がりは?』『結果知らなかったら?』に答えられる素材。"""
    if df is None or not hasattr(df, 'columns') or getattr(df, 'empty', True):
        return ''
    import pandas as pd

    def has(c):
        return c in df.columns

    res = {}
    if actual_result and actual_result.get('horses'):
        for ub, h in actual_result['horses'].items():
            try:
                res[int(ub)] = h
            except Exception:
                pass
    sc_col = 'Projected Score' if has('Projected Score') else ('BattleScore' if has('BattleScore') else None)
    rows = []
    for _, r in df.iterrows():
        try:
            um = int(pd.to_numeric(r.get('Umaban'), errors='coerce'))
        except Exception:
            continue
        nm = str(r.get('Name', ''))[:10]
        tr = str(r.get('Trainer', '') or '')[:8] if has('Trainer') else '-'
        pop = pd.to_numeric(r.get('Popularity'), errors='coerce')
        od = pd.to_numeric(r.get('Odds'), errors='coerce')
        sc = pd.to_numeric(r.get(sc_col), errors='coerce') if sc_col else None
        rr = res.get(um, {})
        rank = rr.get('Rank', '-')
        agari = rr.get('Agari', '-')
        passing = rr.get('Passing', '-')
        rows.append({
            'rank': rank if str(rank).isdigit() else 99, 'um': um, 'nm': nm, 'tr': tr,
            'pop': int(pop) if pop == pop else 99, 'od': round(float(od), 1) if od == od else '-',
            'sc': round(float(sc), 1) if (sc is not None and sc == sc) else '-',
            'agari': agari, 'passing': passing,
        })
    if not rows:
        return ''
    rows.sort(key=lambda x: (x['rank'], x['pop']))
    out = ['【出走馬データ(事前=人気/オッズ/厩舎/スコア, 結果=着順/上がり3F/通過)】',
           '着|馬番|馬名|人気|オッズ|厩舎|スコア|上3F|通過']
    for r in rows:
        rk = r['rank'] if r['rank'] != 99 else '-'
        pp = r['pop'] if r['pop'] != 99 else '-'
        out.append(f"{rk}|{r['um']}|{r['nm']}|{pp}|{r['od']}|{r['tr']}|{r['sc']}|{r['agari']}|{r['passing']}")
    return "\n".join(out)


def _c4_pos(passing):
    """通過順の最後の数字＝4角付近の位置。取れなければ None。"""
    parts = re.findall(r'\d+', str(passing or ''))
    return int(parts[-1]) if parts else None


def _parse_body_weight(raw):
    """'480(+8)' → (480, +8)。取れなければ None。"""
    m = re.search(r'(\d{3})\s*[\(（]\s*([+-]?\d+)\s*[\)）]', str(raw or ''))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _review_class_notes(meta, df=None, actual_result=None):
    """クラスごとの注意（買い指示ではない。次走の相手が変わりやすい、という確認用）。"""
    meta = meta or {}
    info = (actual_result or {}).get('race_info') or {}
    blob = ' '.join(str(x or '') for x in (
        meta.get('RaceName'), meta.get('race_name'), meta.get('class'),
        info.get('race_name'),
    ))
    surf = str(meta.get('surface') or meta.get('CurrentSurface') or '')
    if df is not None and hasattr(df, 'columns') and 'CurrentSurface' in df.columns and not df.empty:
        surf = surf or str(df['CurrentSurface'].iloc[0] or '')
    notes = []
    is_new = ('新馬' in blob)
    is_maid = ('未勝利' in blob) or is_new
    is_2yo = bool(re.search(r'2歳|２歳', blob))
    is_dirt = ('ダ' in surf) or ('dirt' in surf.lower())
    if is_new and is_dirt:
        notes.append('ダート新馬：芝を使いにくい馬が集まりやすく、メンバーの厚みが読みにくい')
    elif is_maid or is_2yo:
        notes.append('2歳・新馬・未勝利：次走で相手が一気に強くなることがある（今回の着順だけで次を決めない）')
    if re.search(r'G1|G2|G3|GI|GII|GIII|重賞|オープン|リステッド', blob):
        notes.append('オープン・重賞：次走のクラスがバラバラになりやすい（相手関係を改めて見る）')
    if meta.get('is_fillies') or ('牝' in blob and '限定' in blob):
        notes.append('牝馬戦：混合戦と牝馬限定では力関係が違うことがある')
    return notes


def _review_checklist(df=None, actual_result=None, meta=None):
    """回顧の下準備（事実の確認リスト）。次走の買い目は作らない。

    映像・裁決はデータに無いので「ユーザーに聞いてよい」と明記する。
    展開逆行の次走狙い・距離短縮一変・着外狙い は入れない。
    """
    meta = meta or {}
    info = (actual_result or {}).get('race_info') or {}
    lines = ['【回顧の確認リスト】（事実の整理。次走の買い指示ではない）']

    cond = str(meta.get('condition') or '')
    surf = str(meta.get('surface') or meta.get('CurrentSurface') or '')
    if df is not None and hasattr(df, 'columns') and not getattr(df, 'empty', True):
        if not surf and 'CurrentSurface' in df.columns:
            surf = str(df['CurrentSurface'].iloc[0] or '')
    if surf or cond:
        lines.append(f"・馬場: {surf or '—'} {cond or ''}".rstrip())
    else:
        lines.append('・馬場: データなし → 内伸び／外伸び、前残りか差しが届いたかをユーザーに聞いてよい')

    dist = info.get('distance') or meta.get('distance')
    if dist is None and df is not None and hasattr(df, 'columns') and not getattr(df, 'empty', True):
        if 'CurrentDistance' in df.columns:
            try:
                import pandas as _pd
                dist = int(_pd.to_numeric(df['CurrentDistance'].iloc[0], errors='coerce'))
            except Exception:
                dist = None
    splits = info.get('pace_splits') or {}
    if splits:
        lines.append(f"・ハロン（通過タイム）: {splits}")
    elif dist:
        band = '前半600mあたり' if int(dist) <= 1600 else '前半1000mあたり'
        lines.append(f"・流れ: 距離{int(dist)}m。{band}が速かったか遅かったかをユーザーに聞いてよい")

    horses = (actual_result or {}).get('horses') or {}
    placed = []
    for ub, h in horses.items():
        try:
            rk = int(h.get('Rank', 99))
        except (TypeError, ValueError):
            continue
        if rk <= 3:
            placed.append((rk, ub, h))
    placed.sort()
    if placed:
        n_field = int(info.get('field_size') or len(horses) or 0) or None
        front = rear = 0
        bits = []
        for rk, ub, h in placed:
            c4 = _c4_pos(h.get('Passing'))
            where = ''
            if c4 is not None and n_field:
                if c4 <= 3 or (c4 / n_field) <= 0.28:
                    where = '前め'
                    front += 1
                elif (c4 / n_field) >= 0.65:
                    where = '後ろめ'
                    rear += 1
                else:
                    where = '中団'
            bits.append(
                f"{rk}着 {h.get('Name', f'馬番{ub}')} 通過{h.get('Passing') or '—'}{('=' + where) if where else ''}")
        lines.append('・上位の位置取り: ' + ' / '.join(bits))
        if front >= 2:
            lines.append('・印象: 上位は前めが多め（前が残った感じ）')
        elif rear >= 2:
            lines.append('・印象: 上位は後ろめが多め（後ろから来た感じ）')
    else:
        lines.append('・上位の位置取り: 結果の通過順がまだ無い')

    notes = _review_class_notes(meta, df, actual_result)
    if notes:
        lines.append('・クラスの注意（次走を即決めしない）: ' + '／'.join(notes))

    wt_bits = []
    if df is not None and hasattr(df, 'columns') and not getattr(df, 'empty', True) and 'Weight' in df.columns:
        import pandas as _pd
        for _, r in df.iterrows():
            parsed = _parse_body_weight(r.get('Weight'))
            if not parsed:
                continue
            _kg, dlt = parsed
            if abs(dlt) >= 8:
                try:
                    um = int(_pd.to_numeric(r.get('Umaban'), errors='coerce'))
                except Exception:
                    continue
                wt_bits.append(f"{um}番{str(r.get('Name', '') or '')[:8]}({dlt:+d}kg)")
    if wt_bits:
        lines.append('・馬体重の増減が大きい馬: ' + ' / '.join(wt_bits) + '（事実の確認。増減だけで買い・消しにしない）')
    else:
        lines.append('・馬体重の増減・休み・裁決の不利／鼻出血: データに無い分はユーザーに聞いてよい')

    lines.append('・映像で見た印象（狭まった・外を回された等）はユーザーの言葉をそのまま聞く。次走の狙いにはしない')
    return lines


def build_context(df=None, magi_pred=None, actual_result=None, meta=None, review_bundle=None):
    """会話セッション全体で使う、短いレースコンテキスト文字列を作る。

    review_bundle がある場合、購入前判断(A)と事後再計算(C)を混同しない。
    """
    meta = meta or {}
    lines = []
    pre = (review_bundle or {}).get('pre_race_snapshot') or {}
    used_pre = pre.get('status') == 'available'
    settled = (review_bundle or {}).get('settled_result') if review_bundle else None

    if review_bundle is not None:
        if used_pre:
            lines.append('【A. 購入前記録（PRE-RACE SNAPSHOT）※当時の判断はここを正とする】')
            if pre.get('summary_text'):
                lines.append(pre['summary_text'])
            diff = pre.get('diff') or {}
            if diff.get('summary'):
                lines.append(f"推奨と実購入の差分: {diff.get('summary')}")
        else:
            lines.append('【A. 購入前記録】 pre_race_snapshot = unavailable（推測復元なし）')

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
        hdr = '【B. 確定結果（SETTLED RESULT）】' if review_bundle is not None else '【実際の結果】'
        lines.append(hdr)
        for h in actual_top:
            lines.append(
                f"  {h['rank']}着 {h['name']}（{h['pop']}番人気 / 上がり{h['agari']} / 通過{h['passing']}）"
            )

    if settled and settled.get('bets'):
        lines.append('【B. 実購入・精算】')
        for b in settled['bets']:
            lines.append(
                f"  {b.get('bet_type')} {b.get('bamei')} ¥{b.get('stake')} "
                f"→ {b.get('settlement_state')} 払戻¥{b.get('payout') or 0}")
        lines.append(
            f"  レース損益: ¥{settled.get('race_pnl', 0)} "
            f"(購入¥{settled.get('total_stake', 0)} / 払戻¥{settled.get('total_payout', 0)})")

    # MAGI予測（review_bundle 時は事後再計算として明示）
    pred_ubs = []
    if magi_pred and magi_pred.get('final_prediction'):
        ph = magi_pred['final_prediction'].get('horses', [])
        if ph:
            if review_bundle is not None:
                lines.append('【C. 事後MAGI deliberation（POST-RACE RECALCULATION）】')
            else:
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

    chk = _review_checklist(df, actual_result, meta)
    if chk:
        lines.append('')
        lines.extend(chk)

    sig = _extract_signals(df, actual_top)
    if sig['text']:
        lines.append('')
        if review_bundle is not None:
            lines.append('【C. レース後再取得dfのシグナル（POST-RACE RECALCULATION）】')
        lines.append(sig['text'])
    tbl = _horse_table(df, actual_result)
    if tbl:
        lines.append('')
        if review_bundle is not None:
            lines.append('【C. レース後再取得df（出走馬表）】')
        lines.append(tbl)

    return {
        'text': "\n".join(lines) if lines else '（レース情報なし）',
        'actual_top': actual_top,
        'pred_ubs': pred_ubs,
        'missed': missed,
        'signals': sig,
        'review_bundle': review_bundle,
        'used_pre_race_snapshot': used_pre if review_bundle is not None else None,
        'used_post_race_recalculation': bool(
            df is not None and not getattr(df, 'empty', True))
        if review_bundle is not None else None,
        'review_checklist': chk,
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
    cfg_kwargs = dict(max_output_tokens=max_tokens)
    if system:
        cfg_kwargs['system_instruction'] = system
    last = None
    for model in ('gemini-2.5-flash-lite', 'gemini-2.5-flash'):
        # 思考設定はモデル世代で受け付ける引数が違い(2.5系=thinking_budget /
        # 3.5以降=thinking_level・逆を渡すと400)、フォールバックで世代が混ざりうるため
        # cfgをモデルごとに作る。詳細は core/gemini_compat.py
        from core import gemini_compat as _gc
        # temperatureも効く世代(2.5系)にだけ渡す
        cfg = _gc.apply_thinking(
            gt.GenerateContentConfig(**cfg_kwargs,
                                     **_gc.sampling_kwargs(model, temperature=temperature)),
            gt, model, level='MINIMAL')
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


_TURN_SYSTEM = """あなたは競馬AI「MAGIシステム」。3人格がレース後、競馬初心者のユーザーと“回顧の会議”をします。
質問の羅列ではなく、人格どうしも短く意見を交わしながら、会話を積み上げて「このレースから何を学べるか」へ寄せます。

人格の担当と話し方:
- melchior(🔴): 人気だったのに負けた馬の「危険サイン」。関西弁（例:「〜やねん」「〜やろ？」「ほんま」「あかん」「ちゃう」）
- balthasar(🟢): 穴で来た(人気薄なのに上位の)馬の「見抜けるヒント」← 一番大事。京都弁（例:「〜どすえ」「〜どすなぁ」「〜はりましたか？」「えらい」）
- casper(🔵): レースの流れ・展開・荒れ方。標準語（東京・丁寧だがフランク）

アプリのシグナル(重要・最優先):
- コンテキストに【✅アプリが事前に出した検証済みエッジ】があれば、その馬・サインを“MAGIから具体的に”挙げて話を始める。ユーザーに「何かサインあった?」と丸投げしない。
- 【⚪参考情報】(総合スコア上位など)は買い材料として過信せず補助にとどめる。

回顧の進め方（【回顧の確認リスト】があるとき）:
- 会話の前半は、リストの順番を意識する。1ターンで全部聞かない。1項目だけやさしく聞く。
  1) 馬場と流れ（内／外、前が残ったか差しが届いたか）
  2) 上位の位置取り（通過の数字）
  3) メンバーの厚み（手薄か、実績馬が揃っていたか）
  4) 馬体重の増減・休み・裁決の不利や鼻出血（データに無いことはユーザーに聞く）
  5) クラスの注意があれば「次走の相手が変わりやすい」とだけ触れる
- 映像はこちらに無い。狭まった・外を回された等は、ユーザーが言った言葉をそのまま受け止める。
- 次走の即買いを勧めない。1回の回顧で買い方は変えない。

言ってはいけない（検証で否定／隔離）:
- 展開やバイアスに逆行した馬を次走狙え
- 折り合いを欠いた馬は距離短縮で一変する
- 勝った馬は狙うな／5〜6着以下こそ次走の狙い目
- 通過順や「不利あり」だけで次走の妙味を断言する

データの使い方(質問に必ずデータで答える):
- 【出走馬データ】表に各馬の 人気/オッズ/厩舎/スコア/上がり3F/通過順/着順 がある。ユーザーが「厩舎は?」「上がり3Fは?」「○番はどうだった?」と聞いたら、必ずこの表の数字を引いて具体的に答える。「分からない」で逃げない。
- 「結果を知らなかったらどの馬が3着内に入ると思う?」と聞かれたら、着順や上がり(結果列)は見ないふりをして、事前情報(人気/オッズ/スコア/シグナル/厩舎)だけから各人格が予想を1〜2頭ずつ挙げ、最後に実際の結果と答え合わせをする(予想ゲーム)。

1ターンの作り方(重要):
- このターンで 2〜3人の人格が短く発言する（turns配列）。人格どうしが相手の名前を呼んで反応してよい（例: balthasarが「メルキオールの言う通り〜」）。
- 直前のユーザーの答えがあれば、最初の発言でその言葉を具体的に拾って受け止める。
- ユーザーに呼びかける時は、与えられた呼び名があればそれを使う（無ければ「あなた」）。
- 配列の最後の発言は、ユーザーが一言で答えられる“やさしい問いかけ”で終える（done=false時）。
- 各発言は1〜2文・専門用語は噛み砕く・方言は各自一貫。説教/長文禁止。同じ話の繰り返し禁止。

締め方(done):
- 会話は基本 done=false で続ける（ユーザーが話したいだけ続けられる。無理に早く締めない）。
- ただしユーザーが「終わり」「もういい」等で切り上げたそうな時、または話が完全に出尽くした時だけ done=true。
- done=true の時は、今回の馬・展開の固有名に触れた“回顧の総括”を最後の発言で述べる（中身のない「お疲れさま」だけは禁止・問いかけ不要）。

出力は必ず次のJSONのみ(```不要):
{"turns":[{"persona":"melchior|balthasar|casper","message":"発言(1〜2文)"}, ...2〜3件...],"done":false}"""


def _format_convo(chat):
    convo = []
    for m in chat:
        if m.get('role') == 'user':
            convo.append(f"ユーザー: {m['message']}")
        else:
            p = PERSONAS.get(m.get('persona'), {})
            convo.append(f"{p.get('name','MAGI')}: {m['message']}")
    return "\n".join(convo) if convo else "（まだ会話なし。最初の話題を切り出す）"


def magi_turn(ctx, chat, api_key, force_done=False, user_name=None):
    """このターンで話す2〜3人格の発言(人格どうしの会話含む)をまとめて返す。

    Args:
        ctx: build_context の戻り
        chat: [{'role':'magi'/'user','persona':..,'message':..}, ...]
        force_done: Trueなら総括して締める指示を出す(往復の上限到達時)
        user_name: ユーザーの呼び名(人格が呼びかける時に使う)
    Returns: {'turns':[{'persona':str,'message':str},...], 'done':bool}
    """
    convo_text = _format_convo(chat)
    extra = ("\n\n※今回が最終ターン。これまでの話を踏まえ、最後の発言で今回の馬・展開の固有名に触れた"
             "回顧の総括を述べて締めよ(done=true・問いかけ不要)。" if force_done else "")
    name_line = (f"\nユーザーの呼び名は「{user_name}」。呼びかける時はこの名前を使う。\n"
                 if user_name and user_name != 'あなた' else "")
    prompt = (
        f"━ レース概要 ━\n{ctx.get('text','')}\n{name_line}\n"
        f"━ ここまでの会話 ━\n{convo_text}\n\n"
        f"このターンの発言(turns 2〜3件)をJSONで出力せよ。{extra}"
    )
    raw = _gen(prompt, api_key, system=_TURN_SYSTEM, temperature=0.7, max_tokens=520)
    obj = _parse_json(raw)
    turns = []
    if obj and isinstance(obj.get('turns'), list):
        for t in obj['turns']:
            p = t.get('persona')
            msg = str(t.get('message', '')).strip()
            if p in PERSONAS and msg:
                turns.append({'persona': p, 'message': msg})
    if not turns:
        turns = [{'persona': 'balthasar',
                  'message': 'このレースで「あれっ?」と思ったことや、気になった馬はいた?'}]
    done = bool(obj.get('done', False)) if obj else False
    return {'turns': turns[:3], 'done': done or force_done}


_EXTRACT_SYSTEM = """あなたは競馬の学習アシスタント。レース後のおしゃべりログから、
あとで検証(バックテスト)するための学習メモを抽出します。
ユーザーは初心者なので、本人の言葉(原文)を大切にしつつ、検証できる短い名詞句タグに整理してください。
誇張や決めつけはしない。会話に無い情報を創作しない。
「展開逆行を次走狙え」「距離短縮で一変」「着外が狙い目」はタグにしない。

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


def races_done(race_id, ledger=None):
    """指定race_idの回顧記録(実施日時ts/レース日/場/レース名)を返す。二度手間防止用。"""
    if ledger is None:
        ledger = _load_ledger()
    rid = str(race_id).strip()
    return [{'ts': r.get('ts', ''), 'date': r.get('date', ''),
             'place': r.get('place', ''), 'name': r.get('name', '')}
            for r in ledger if str(r.get('race_id', '')).strip() == rid]


def recent_races(ledger=None, limit=20):
    """回顧済みレースをrace_id単位で集約(最新ts順)。戻り: [{race_id,date,place,name,ts,count}]。"""
    if ledger is None:
        ledger = _load_ledger()
    agg = {}
    for r in ledger:
        rid = str(r.get('race_id', '')).strip()
        if not rid:
            continue
        e = agg.setdefault(rid, {'race_id': rid, 'date': '', 'place': '',
                                 'name': '', 'ts': '', 'count': 0})
        e['count'] += 1
        if r.get('ts', '') >= e['ts']:            # 最新tsのメタを保持
            e['ts'] = r.get('ts', '')
            e['date'] = r.get('date', '') or e['date']
            e['place'] = r.get('place', '') or e['place']
            e['name'] = r.get('name', '') or e['name']
    return sorted(agg.values(), key=lambda x: x['ts'], reverse=True)[:limit]


def retro_calendar(ledger=None):
    """回顧をレース日(YYYY-MM-DD)ごとに集約=カレンダー可視化用。
    戻り: {'by_date': {日付: [{race_id,place,name,count,ts}]}, 'undated': [同形式]}。
    同じ日に違うレースが並ぶ。日付はrecordの'date'を正規化(不明はundatedへ)。"""
    import re as _re
    if ledger is None:
        ledger = _load_ledger()
    by_date, undated = {}, {}
    for r in ledger:
        rid = str(r.get('race_id', '')).strip()
        if not rid:
            continue
        m = _re.match(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', str(r.get('date', '')).strip())
        if m:
            key = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            bucket = by_date.setdefault(key, {})
        else:
            bucket = undated
        e = bucket.setdefault(rid, {'race_id': rid, 'place': '', 'name': '',
                                    'count': 0, 'ts': ''})
        e['count'] += 1
        if r.get('ts', '') >= e['ts']:
            e['ts'] = r.get('ts', '')
            e['place'] = r.get('place', '') or e['place']
            e['name'] = r.get('name', '') or e['name']
    out = {k: sorted(v.values(), key=lambda x: (x['place'], x['name']))
           for k, v in by_date.items()}
    return {'by_date': out,
            'undated': sorted(undated.values(), key=lambda x: x['ts'], reverse=True)}


def is_quarantined(tag):
    t = str(tag)
    return any(kw in t for kw in _QUARANTINE_KEYWORDS)


def save_record(race_id, meta, ctx, chat, learning, scanner_review=None, scanner_pred=None,
                audit_review_meta=None):
    """1セッションを台帳に追記し、保存後のタグ集計を返す。

    scanner_review: {'actual_class': '堅い|通常|波乱|大荒れ',
                      'sanrenpuku_payout': int|None, 'sanrentan_payout': int|None}
        会話開始前にユーザーへ必須で答えさせる、Race Scannerの荒れ予測の答え合わせ。
    scanner_pred: build_context前(審議開始時)に計算したScanner(trio_lean)の事前予測。
        {'label': str, 'score': float, 'detail': str} or None。
    """
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
        'scanner_review': scanner_review,
        'scanner_pred': scanner_pred,
        'audit_review': audit_review_meta,
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


def hypothesis_export(ledger=None):
    """回顧台帳の学習タグ→検証可能仮説へ変換(カード7)。
    3回ルール/隔離ガードレールの下流。ready(3回以上・非俗説)タグのみを
    hypothesis_schemaで検証し、通ったものだけ『検証キュー候補』にする。
    戻り値: {'exported':[候補dict...], 'isolated':[{'tag','reason'}...]}。
    ⚠ここは投入資格の門番のみ。採否はauto_feature_search/backtestのholdoutが決める。"""
    from core import hypothesis_schema as hs
    summ = tag_summary(ledger)
    exported, isolated = [], []
    for tag, info in summ.items():
        # 二重の隔離: magiの俗説キーワード + hypothesis_schemaの却下リスト
        folk, reason = hs.is_folk_belief(tag)
        if info['quarantined'] or folk:
            isolated.append({'tag': tag, 'reason': reason or '俗説隔離(magi台帳)'})
            continue
        if not info['ready']:
            continue  # 3回未満は投入資格なし
        hyp = hs.make_hypothesis(tag, note=f'MAGI回顧{info["count"]}回')
        ok, why = hs.validate_hypothesis(hyp)
        if ok:
            exported.append(hs.to_feature_candidate(hyp))
        else:
            isolated.append({'tag': tag, 'reason': why})
    return {'exported': exported, 'isolated': isolated}
