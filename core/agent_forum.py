# -*- coding: utf-8 -*-
"""🏛️ 集合知エージェント掲示板 — core/agent_forum.py

複数のLLMエージェント（個性違い）にレースデータ＋DB実データを渡し、
3ラウンドの討論→合議結果を出す。
各エージェントは「知らないこと」が違う＝それが個性。

LLMバックエンド: Ollama (localhost:11434)
"""
import os
import re
import json
import time
import sqlite3
import requests
from datetime import datetime

OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:7b')
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BLOOD_DB = os.path.join(_ROOT, 'data', 'blood_dict.db')
_JV_DB = os.path.join(_ROOT, 'data', 'jravan.db')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 全検証済みバックテスト結果 — エージェントの「世界の真実」
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_VERIFIED_TRUTH = """
【検証済みの真実 — エビデンスに基づく競馬の法則】

■ 市場効率性
・単勝ROIは全条件・全オッズ帯で+ROIポケットゼロ。単勝で勝てる条件は存在しない。
・予測精度の92%は人気(オッズ=市場の集合知)の力。BattleScore単体の寄与は小さい。
・Projected Score = BattleScore×1.0 + Popularity×1.5 が最適。他の重みは全て0(検証済)。

■ 検証で否定された俗説（=過剰人気・実装してはいけない）
・初ブリンカー/距離短縮/お帰り/季節/初ダート → 全て過剰人気。
・脚質(逃げ/差し/追込): 人気に完全織込み。軸の複勝率をほぼ動かさない。
・巻き返し候補(バイアス逆転): 穴妙味ではなく、1-3番人気の信頼度UPのみ。穴帯ROI 66-68%。
・展開恩恵(好位妙味): 大標本で残差≈0。展開向く×人気薄はむしろ過剰人気。
・PCI乖離: 消去妙味なし(残差-0.5pp)
・5走前理論(ROI219%説)/前走0.6秒差Alpha/Mの法則ショッカー: 全否定。
・牝馬限定/ダート: 織込み済み

■ 検証で確認された実在のエッジ
・単複乖離(単勝≥10倍×複勝≤3倍): 勝率2.5→7%(検証済)。
・末脚偏差top3×6番人気以下: ベース超ROI。5-10倍では効かない。
・ハンデ戦: ②穴型+7.9pp/z5.2。穴党の主戦場。
・フルゲート16頭以上: 荒れやすい(z5.9)。
・少頭数8-10頭: 堅い(+8.4pp)。
・厩舎の当コース勝率≥20%: 妙味あり。全体勝率は織込み済み。
・道悪×血統: FADE群(ディープ系)は芝道悪で崩落。POWER群(米国型)はダ稍重+7.2pp。
・前走圧勝馬の人気馬: 最良の軸(複勝率72.3%)。
・補正タイム: 穴に弱く本命補強に+5pp。
・当日バイアス逆張り: 外有利日×内枠×1-3人気=危険人気(-4.6pp/z-3.8)。
・消去クロス: 弱点フラグ重複↑で複勝率31→10%。
・3連複②型(人気-穴-穴): 最頻46%でROI最高。
・ボーダー残し: 3着取りこぼし15→10%。
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DB動的データ取得 — レース固有の実データをエージェントに注入
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _safe_jv(query, params=(), max_rows=50):
    if not os.path.exists(_JV_DB):
        return []
    try:
        con = sqlite3.connect(f'file:{_JV_DB}?mode=ro', uri=True, timeout=5)
        rows = con.execute(query, params).fetchmany(max_rows)
        con.close()
        return rows
    except Exception:
        return []


def _safe_blood(query, params=(), max_rows=30):
    if not os.path.exists(_BLOOD_DB):
        return []
    try:
        con = sqlite3.connect(f'file:{_BLOOD_DB}?mode=ro', uri=True, timeout=5)
        rows = con.execute(query, params).fetchmany(max_rows)
        con.close()
        return rows
    except Exception:
        return []


def _parse_horse_names(csv_text):
    import io, csv as csvmod
    names = []
    try:
        reader = csvmod.DictReader(io.StringIO(csv_text))
        for row in reader:
            for k in ['馬名', 'Name', 'name', 'bamei']:
                if row.get(k) and row[k].strip() != '-':
                    names.append(row[k].strip())
                    break
    except Exception:
        pass
    return names


def _parse_csv_field(csv_text, *field_names):
    import io, csv as csvmod
    vals = []
    try:
        reader = csvmod.DictReader(io.StringIO(csv_text))
        for row in reader:
            for k in field_names:
                v = row.get(k, '').strip()
                if v and v != '-' and v not in vals:
                    vals.append(v)
    except Exception:
        pass
    return vals


def load_horse_history(csv_text, max_runs=5):
    """出走馬の過去走をjravan.dbから取得。"""
    names = _parse_horse_names(csv_text)
    if not names:
        return ''
    lines = []
    for name in names:
        rows = _safe_jv(
            """SELECT ra.race_name, ra.surface, ra.kyori,
                      r.chakujun, r.ninki, r.win_odds, r.ato3f, r.futan, r.bataiju, r.zogen,
                      ra.baba_shiba, ra.baba_dirt, ra.year, ra.monthday
               FROM results r
               JOIN races ra ON r.race_key = ra.race_key
               WHERE r.bamei = ?
               ORDER BY ra.year DESC, ra.monthday DESC
               LIMIT ?""",
            (name, max_runs),
        )
        if rows:
            lines.append(f'\n▼ {name} (直近{len(rows)}走)')
            for row in rows:
                rn, sf, dist, chaku, nk, odds, a3f, futan, weight, zogen, bs, bd, yr, md = row
                baba = bs if sf == '芝' else bd
                baba_str = {'1': '良', '2': '稍', '3': '重', '4': '不',
                            1: '良', 2: '稍', 3: '重', 4: '不'}.get(baba, '')
                a3f_s = f'{a3f/10:.1f}' if a3f and a3f > 0 else '-'
                w_s = f'{weight}kg' if weight else '-'
                z_s = f'({zogen:+d})' if zogen else ''
                lines.append(
                    f'  {yr}/{md} {rn or "?"} {sf}{dist}m{baba_str} '
                    f'{chaku}着/{nk}人気 上{a3f_s} {futan/10:.0f}kg {w_s}{z_s}'
                )
    return '\n'.join(lines) if lines else ''


def load_blood_stats(csv_text):
    """出走馬の父・母父の条件別成績。"""
    sires = _parse_csv_field(csv_text, '父', 'sire')
    bms_list = _parse_csv_field(csv_text, '母父', 'broodmareSire')
    if not sires and not bms_list:
        return ''
    lines = []
    for s in sires:
        rows = _safe_blood(
            'SELECT surface, dist_band, runs, place_rate, win_rate, win_roi '
            'FROM sire_stats WHERE parent=? ORDER BY runs DESC LIMIT 5', (s,))
        if rows:
            lines.append(f'【父】{s}:')
            for r in rows:
                lines.append(f'  {r[0]}{r[1]}: {r[2]}走 複{r[3]:.0f}% 勝{r[4]:.1f}% 回{r[5]:.0f}%')
    for b in bms_list:
        rows = _safe_blood(
            'SELECT surface, dist_band, runs, place_rate, win_rate, win_roi '
            'FROM bms_stats WHERE parent=? ORDER BY runs DESC LIMIT 3', (b,))
        if rows:
            lines.append(f'【母父】{b}:')
            for r in rows:
                lines.append(f'  {r[0]}{r[1]}: {r[2]}走 複{r[3]:.0f}% 勝{r[4]:.1f}% 回{r[5]:.0f}%')
    return '\n'.join(lines) if lines else ''


def load_course_pace(jyo, surface, distance, limit=20):
    """同コース直近レースのペース傾向。"""
    if not jyo:
        return ''
    rows = _safe_jv(
        """SELECT mae3f, ato3f, shusso_tosu
           FROM races
           WHERE jyo=? AND surface=? AND kyori=?
           ORDER BY year DESC, monthday DESC
           LIMIT ?""",
        (jyo, surface, distance, limit),
    )
    if not rows:
        return ''
    paces = [(r[0]/10, r[1]/10, r[0]/10 - r[1]/10, r[2])
             for r in rows if r[0] and r[1] and r[0] > 0 and r[1] > 0]
    if not paces:
        return ''
    avg_mae = sum(p[0] for p in paces) / len(paces)
    avg_ato = sum(p[1] for p in paces) / len(paces)
    avg_diff = sum(p[2] for p in paces) / len(paces)
    avg_tosu = sum(p[3] for p in paces) / len(paces)
    result = (
        f'同コース({surface}{distance}m@{jyo})直近{len(paces)}R:\n'
        f'  平均前3F {avg_mae:.1f}秒 / 後3F {avg_ato:.1f}秒 / '
        f'差 {avg_diff:+.1f}秒 / 平均頭数 {avg_tosu:.0f}頭\n'
    )
    if avg_diff > 0.5:
        result += '  → ハイペース傾向 → 差し/追込み有利\n'
    elif avg_diff < -0.5:
        result += '  → スロー傾向 → 前残り有利\n'
    else:
        result += '  → 平均ペース\n'
    return result


def load_trainer_jockey_course(csv_text, jyo='', surface=''):
    """騎手のコース成績。"""
    names = _parse_horse_names(csv_text)
    if not names or not jyo:
        return ''
    lines = []
    for name in names:
        rows = _safe_jv(
            """SELECT r2.jockey_name,
                      COUNT(*) as runs,
                      SUM(CASE WHEN r2.chakujun <= 3 THEN 1 ELSE 0 END) as top3,
                      SUM(CASE WHEN r2.chakujun = 1 THEN 1 ELSE 0 END) as wins
               FROM results r2
               JOIN races ra2 ON r2.race_key = ra2.race_key
               WHERE r2.jockey_name IN (
                   SELECT r3.jockey_name FROM results r3
                   WHERE r3.bamei = ? ORDER BY r3.race_key DESC LIMIT 1
               ) AND ra2.jyo = ? AND ra2.surface = ?
               GROUP BY r2.jockey_name""",
            (name, jyo, surface),
        )
        if rows:
            for r in rows:
                jname, runs, t3, w = r
                if runs >= 5:
                    lines.append(
                        f'{name}の騎手({jname}): {jyo}{surface} {runs}騎 '
                        f'勝{w/runs*100:.0f}% 複{t3/runs*100:.0f}%')
    return '\n'.join(lines[:15]) if lines else ''


def load_training_data(csv_text):
    """直近調教データ。"""
    names = _parse_horse_names(csv_text)
    if not names:
        return ''
    lines = []
    for name in names:
        rows = _safe_jv(
            """SELECT t.cho_date, t.t3f, t.t2f, t.center
               FROM training t
               JOIN horses h ON t.ketto_num = h.ketto_num
               WHERE h.bamei = ?
               ORDER BY t.cho_date DESC LIMIT 3""",
            (name,),
        )
        if rows:
            parts = []
            for r in rows:
                dt, t3f, t2f, center = r
                loc = '栗東' if center == '0' else '美浦' if center == '1' else '?'
                t3s = f'{t3f/10:.1f}' if t3f and t3f > 0 else '-'
                t2s = f'{t2f/10:.1f}' if t2f and t2f > 0 else '-'
                parts.append(f'{dt}({loc})3F{t3s}/2F{t2s}')
            lines.append(f'{name}: {" → ".join(parts)}')
    return '\n'.join(lines) if lines else ''


def load_payout_patterns(jyo, surface, distance):
    """同コースの過去配当傾向。"""
    rows = _safe_jv(
        """SELECT p.bet_type, p.payout
           FROM payouts p
           JOIN races ra ON p.race_key = ra.race_key
           WHERE ra.jyo=? AND ra.surface=? AND ra.kyori=?
             AND p.bet_type IN ('単勝','複勝','3連複')
           ORDER BY ra.year DESC, ra.monthday DESC
           LIMIT 90""",
        (jyo, surface, distance),
    )
    if not rows:
        return ''
    tan = [r[1] for r in rows if r[0] == '単勝' and r[1] > 0]
    sanfuku = [r[1] for r in rows if r[0] == '3連複' and r[1] > 0]
    lines = [f'同コース配当傾向(直近{len(tan)}R):']
    if tan:
        lines.append(f'  単勝: 平均{sum(tan)//len(tan)}円 / 中央値{sorted(tan)[len(tan)//2]}円 / 万馬券率{sum(1 for t in tan if t>=10000)/len(tan)*100:.0f}%')
    if sanfuku:
        lines.append(f'  3連複: 平均{sum(sanfuku)//len(sanfuku)}円 / 万馬券率{sum(1 for s in sanfuku if s>=10000)/len(sanfuku)*100:.0f}%')
    return '\n'.join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 知識パック（専門性ごとに異なるデータ）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _knowledge_conservative(csv_text='', meta=None):
    return (
        '\n【あなたの専門知識: 俗説を見破る目】\n'
        '・初ブリンカー/距離短縮/お帰り/季節/初ダート → 全て過剰人気。根拠にするな。\n'
        '・前走圧勝馬の人気馬は最良の軸(複勝率72.3%)。「罠」は単勝限定。\n'
        '・脚質は織込み済み。巻き返し候補は穴妙味なし(ROI 66-68%)。\n'
        '・少頭数(8-10頭)は堅い(+8.4pp)。補正タイムは本命補強+5pp。\n'
        '・ショッカー/0.6秒差Alpha/5走前理論: 全否定。信じるな。\n'
    )


def _knowledge_longshot(csv_text='', meta=None):
    return (
        '\n【あなたの専門知識: 穴馬シグナル】\n'
        '・単複乖離(単≥10×複≤3): 勝率2.5→7%。最強穴シグナル。\n'
        '・末脚偏差top3×6番人気以下: ベース超ROI。5-10倍では効かない。\n'
        '・ハンデ戦: +7.9pp/z5.2。フルゲート16+: z5.9。\n'
        '・1番人気抜け(オッズ比≥1.8): 穴型+3.9pp。\n'
        '・3連複②型(人気-穴-穴): 最頻46%でROI最高。\n'
    )


def _knowledge_blood(csv_text='', meta=None):
    blood_data = load_blood_stats(csv_text) if csv_text else ''
    base = (
        '\n【あなたの専門知識: 血統】\n'
        '・血統は予測に完全織込み。唯一の妙味=道悪×血統×人気上位帯。\n'
        '  FADE群(ディープ/サンデー系): 芝道悪で崩落。\n'
        '  POWER群(米国型): ダ稍重+7.2pp。\n'
    )
    if blood_data:
        base += f'\n【今回の出走馬の血統成績(DB)】\n{blood_data}\n'
    return base


def _knowledge_pace(csv_text='', meta=None):
    pace_data = ''
    if meta:
        jyo, sf, dist = meta.get('jyo', ''), meta.get('surface', ''), meta.get('distance', '')
        if jyo and sf and dist:
            try:
                pace_data = load_course_pace(jyo, sf, int(dist))
            except Exception:
                pass
    base = (
        '\n【あなたの専門知識: 展開】\n'
        '・展開恩恵は織込み済み。当日バイアス合致馬も妙味ゼロ。\n'
        '・逆張り=外有利日×内枠×1-3人気=危険(-4.6pp/z-3.8)。\n'
        '・ハイペース→差し有利。スロー→前残り。上がり3Fはレース内top3順位が重要。\n'
    )
    if pace_data:
        base += f'\n{pace_data}\n'
    return base


def _knowledge_data(csv_text='', meta=None):
    payout_data = ''
    if meta:
        jyo, sf, dist = meta.get('jyo', ''), meta.get('surface', ''), meta.get('distance', '')
        if jyo and sf and dist:
            try:
                payout_data = load_payout_patterns(jyo, sf, int(dist))
            except Exception:
                pass
    base = (
        '\n【あなたの専門知識: 統計】\n'
        '・予測精度の92%は人気。単勝+ROIポケットなし。\n'
        '・厩舎当コース勝率≥20%のみ妙味。消去クロス重複で複勝率31→10%。\n'
        '・ストレス: 小柄×馬体減-2pp/芝×後方ぐせ-1.5ppのみ。\n'
    )
    if payout_data:
        base += f'\n{payout_data}\n'
    return base


def _knowledge_training(csv_text='', meta=None):
    training_data = load_training_data(csv_text) if csv_text else ''
    base = (
        '\n【あなたの専門知識: 調教】\n'
        '・調教A-D単体は妙味にならない(織込み可能性大)。\n'
        '・重要: 普段より動いているか。前回比3F 0.5秒↑は注目。\n'
    )
    if training_data:
        base += f'\n【直近調教(DB)】\n{training_data}\n'
    return base


def _knowledge_waku(csv_text='', meta=None):
    return (
        '\n【あなたの専門知識: 枠順】\n'
        '・枠順はLTR重み0(織込み済み)。バイアス×内枠で危険人気検出。\n'
        '・短距離: 内枠やや有利。長距離: 枠の影響薄。\n'
        '・新潟外/東京: 外枠不利少。中山/阪神内: 内枠有利傾向。\n'
    )


def _knowledge_roi(csv_text='', meta=None):
    return (
        '\n【あなたの専門知識: 回収率】\n'
        '・単勝+ROI不可能。勝つには見送り/券種最適化/点数絞り。\n'
        '・3連複②型(人気-穴-穴)が最良。ハンデ戦+7.9ppが本物エッジ。\n'
        '・1人気複勝≈65%。1人気切りはハイリスク。\n'
    )


def _knowledge_contrarian(csv_text='', meta=None):
    return (
        '\n【あなたの専門知識: 過剰人気検知】\n'
        '・初ブリ/距離短縮/お帰り/前走好時計 = 過剰人気パターン(全否定済み)。\n'
        '・外有利日の内枠人気馬 = 複勝-4.6pp。\n'
        '・4-5番人気帯 = 中途半端な危険人気ゾーン。\n'
    )


def _knowledge_jockey(csv_text='', meta=None):
    jk_data = ''
    if csv_text and meta:
        jyo, sf = meta.get('jyo', ''), meta.get('surface', '')
        if jyo and sf:
            jk_data = load_trainer_jockey_course(csv_text, jyo, sf)
    base = (
        '\n【あなたの専門知識: 騎手】\n'
        '・騎手全体勝率はLTR重み0(織込み済み)。コース限定成績で見よ。\n'
        '・トップ騎手の乗替わり(降ろされ)は危険材料。\n'
        '・連敗ストリークは予測に効かない(検証済み誤謬)。\n'
    )
    if jk_data:
        base += f'\n【騎手コース成績(DB)】\n{jk_data}\n'
    return base


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 回顧学習 (Self-Evolving Agent) — 的中/外れを記録→次回注入
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_RETRO_FILE = os.path.join(_ROOT, 'data', 'agent_retrospective.json')


def load_retrospective(limit=10):
    """過去の予測結果を読み込む。直近limit件。"""
    if not os.path.exists(_RETRO_FILE):
        return []
    try:
        with open(_RETRO_FILE, 'r', encoding='utf-8') as f:
            records = json.load(f)
        return records[-limit:]
    except Exception:
        return []


def save_prediction(race_id, meta_text, consensus, agent_picks):
    """予測を保存（結果記入前）。"""
    records = []
    if os.path.exists(_RETRO_FILE):
        try:
            with open(_RETRO_FILE, 'r', encoding='utf-8') as f:
                records = json.load(f)
        except Exception:
            pass
    records.append({
        'race_id': race_id,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'meta': meta_text,
        'consensus': consensus,
        'agent_picks': agent_picks,
        'result': None,
    })
    with open(_RETRO_FILE, 'w', encoding='utf-8') as f:
        json.dump(records[-100:], f, ensure_ascii=False, indent=1)


def record_result(race_id, top3_umaban):
    """レース結果（3着内馬番）を記録し、各エージェントの的中を判定。"""
    if not os.path.exists(_RETRO_FILE):
        return
    try:
        with open(_RETRO_FILE, 'r', encoding='utf-8') as f:
            records = json.load(f)
    except Exception:
        return
    for rec in records:
        if rec.get('race_id') == race_id and rec.get('result') is None:
            top3 = set(top3_umaban)
            rec['result'] = {
                'top3': list(top3_umaban),
                'consensus_hit': bool(set(rec.get('consensus', {}).get('top3_umaban', [])) & top3),
            }
            if rec.get('agent_picks'):
                for ag_id, picks in rec['agent_picks'].items():
                    honmei = picks.get('honmei')
                    rec['agent_picks'][ag_id]['hit'] = honmei in top3 if honmei else False
            break
    with open(_RETRO_FILE, 'w', encoding='utf-8') as f:
        json.dump(records[-100:], f, ensure_ascii=False, indent=1)


def _build_retrospective_prompt():
    """過去の的中/外れ履歴からエージェントへの教訓テキストを生成。"""
    records = load_retrospective(10)
    if not records:
        return ''
    lessons = []
    hit = miss = 0
    for rec in records:
        res = rec.get('result')
        if not res:
            continue
        top3 = res.get('top3', [])
        cons = rec.get('consensus', {})
        meta = rec.get('meta', '')
        if cons.get('top3_umaban'):
            c_picks = cons['top3_umaban']
            matched = [u for u in c_picks if u in top3]
            if matched:
                hit += 1
            else:
                miss += 1
                lessons.append(f'外れ: {meta[:30]}… 合議={c_picks} 結果={top3}')
        elif res.get('consensus_hit'):
            hit += 1
        else:
            miss += 1
    if not (hit + miss):
        return ''
    rate = hit / (hit + miss) * 100
    text = f'\n【過去の成績】直近{hit+miss}戦: 的中{hit} 外れ{miss} (的中率{rate:.0f}%)\n'
    if lessons:
        text += '直近の外れ:\n' + '\n'.join(f'  ・{l}' for l in lessons[-3:]) + '\n'
        text += '→ 過去の失敗を繰り返すな。外れた条件では慎重に判断せよ。\n'
    return text


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAGI回顧台帳 — 過去の回顧から教訓を注入
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MAGI_LEDGER = os.path.join(_ROOT, 'data', 'retro_ledger.json')


def _build_magi_retrospective():
    """MAGI回顧台帳から過去の教訓を生成。"""
    if not os.path.exists(_MAGI_LEDGER):
        return ''
    try:
        with open(_MAGI_LEDGER, 'r', encoding='utf-8') as f:
            records = json.load(f)
    except Exception:
        return ''
    if not records:
        return ''
    lessons = []
    for rec in records[-5:]:
        pred = [int(x) for x in rec.get('pred_ubs', []) if str(x).isdigit()]
        actual = rec.get('actual_top', [])
        if not actual:
            continue
        actual_top3 = [a['umaban'] for a in actual[:3]]
        hit = set(pred) & set(actual_top3)
        missed = set(actual_top3) - set(pred)
        winner = actual[0] if actual else {}
        winner_pop = winner.get('pop', 0)
        lesson = f'レース{rec.get("race_id","?")}:'
        if missed:
            missed_info = []
            for a in actual[:3]:
                if a['umaban'] in missed:
                    missed_info.append(f'{a["name"]}({a["umaban"]}番/{a["pop"]}人気/上{a.get("agari",0)})')
            lesson += f' 取りこぼし={",".join(missed_info)}'
        if winner_pop and winner_pop >= 5:
            lesson += f' 勝ち馬は{winner_pop}人気の穴馬{winner.get("name","")}'
        lessons.append(lesson)
        # MAGIチャットから具体的な教訓を抽出
        chat = rec.get('chat', [])
        for msg in chat:
            text = msg.get('message', '')
            if any(kw in text for kw in ['教訓', '学び', '反省', 'エッジ', '見逃', '注目']):
                lessons.append(f'  → {text[:80]}')
        learning = rec.get('learning', {})
        for sign in learning.get('missed_winner_signs', []):
            lessons.append(f'  → 見逃しサイン: {sign}')
        for sign in learning.get('danger_popular_signs', []):
            lessons.append(f'  → 危険人気サイン: {sign}')
    if not lessons:
        return ''
    return '\n【MAGI回顧からの教訓】\n' + '\n'.join(lessons) + '\n'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 匿名化ラウンド — 権威バイアス除去
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _anonymize_posts(posts):
    """投稿者名を隠して「匿名予想者A,B,C...」にする。"""
    labels = [chr(65 + i) for i in range(26)] + [f'A{i}' for i in range(50)]
    anon = []
    for i, p in enumerate(posts):
        anon.append({
            **p,
            'name': f'匿名予想者{labels[i % len(labels)]}',
            'icon': '👤',
            'trip': '',
        })
    return anon


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# エージェント定義
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BASE_AGENTS = [
    {'id': 'ken', 'name': '保守派ケン', 'trip': '◆KenHoshu', 'icon': '🛡️',
     'knowledge_fn': _knowledge_conservative, 'truth_level': 'full',
     'system': 'あなたは競馬予想エージェント「保守派ケン」。堅実・保守的。'
               '人気上位馬(1-3番人気)を軸にする。リスクを指摘し穴馬への過信を戒める。落ち着いた敬語。'
               '【制約】◎は1-3番人気から選べ。'},
    {'id': 'taku', 'name': '穴党タク', 'trip': '◆TakuAna', 'icon': '🎯',
     'knowledge_fn': _knowledge_longshot, 'truth_level': 'none',
     'system': 'あなたは競馬予想エージェント「穴党タク」。大穴狙いのプロ。'
               'オッズ表の歪み、過小評価された馬を見つけるのがあなたの仕事。'
               'データ（過去走・上がり・血統）から人気薄で走れる馬を特定せよ。タメ口で熱い。'
               '【絶対制約】◎は必ず5番人気以下から選べ。人気馬を◎にしたら失格。'
               '人気順ではなく、過去走の上がりタイムや血統適性を根拠にせよ。'},
    {'id': 'kei', 'name': '血統師ケイ', 'trip': '◆KeiBlood', 'icon': '🧬',
     'knowledge_fn': _knowledge_blood, 'truth_level': 'minimal',
     'system': 'あなたは競馬予想エージェント「血統師ケイ」。血統データだけで勝負する。'
               '父・母父の条件別成績（複勝率・回収率）が全て。人気は一切無視。'
               '血統成績が良い馬を◎にせよ。人気に関わらず血統適性が最も高い馬を選べ。'
               '知的で断定的。【制約】人気順に言及するな。血統根拠のみで選べ。'},
    {'id': 'riku', 'name': 'ペース職人リク', 'trip': '◆RikuPace', 'icon': '⏱️',
     'knowledge_fn': _knowledge_pace, 'truth_level': 'minimal',
     'system': 'あなたは競馬予想エージェント「ペース職人リク」。展開だけで勝負する。'
               '逃げ馬の数からペースを予測し、展開が向く馬を選べ。'
               '上がり3Fが速い馬、位置取りが有利な馬をデータから判断。'
               '職人気質で簡潔。【制約】人気順ではなく展開・位置取り・上がりデータで選べ。'},
    {'id': 'mari', 'name': 'データ屋マリ', 'trip': '◆MariData', 'icon': '📊',
     'knowledge_fn': _knowledge_data, 'truth_level': 'full',
     'system': 'あなたは競馬予想エージェント「データ屋マリ」。数値・統計重視。'
               'スコア、オッズの数値から冷徹に判断。理系女子風で淡々。'
               '数値根拠必須。戦闘力スコアとオッズのギャップに注目。'},
]

_EXTRA_AGENTS = [
    {'id': 'rina', 'name': '調教見リナ', 'trip': '◆RinaTraining', 'icon': '👀',
     'knowledge_fn': _knowledge_training, 'truth_level': 'none',
     'system': '競馬予想エージェント「調教見リナ」。調教時計だけで判断する。'
               '時計が速い馬＝仕上がり良好。前回より3F短縮している馬に注目。'
               '人気は見るな。調教データだけで◎を選べ。元気で直感的。'},
    {'id': 'waku', 'name': '枠順師ワク', 'trip': '◆WakuMaster', 'icon': '🎰',
     'knowledge_fn': _knowledge_waku, 'truth_level': 'minimal',
     'system': '競馬予想エージェント「枠順師ワク」。枠番とコース形態だけで判断。'
               '内枠有利/外枠有利をコースから判断し、有利な枠の馬を選べ。老練。'
               '【制約】人気順ではなく枠順の有利不利で選べ。'},
    {'id': 'numa', 'name': '道悪博士ヌマ', 'trip': '◆NumaDirt', 'icon': '🌧️',
     'knowledge_fn': _knowledge_blood, 'truth_level': 'minimal',
     'system': '競馬予想エージェント「道悪博士ヌマ」。馬場状態と血統の相性だけで判断。'
               '良馬場ならパワー不要、道悪ならパワー系血統。研究者風。'},
    {'id': 'sou', 'name': '回収率鬼ソウ', 'trip': '◆SouROI', 'icon': '💹',
     'knowledge_fn': _knowledge_roi, 'truth_level': 'full',
     'system': '競馬予想エージェント「回収率鬼ソウ」。'
               'オッズと実力の乖離を探す。人気馬のオッズが低すぎれば危険、人気薄のオッズが高すぎれば妙味。'
               '戦闘力スコアとオッズを比較し、割安な馬を◎にせよ。ドライ。'},
    {'id': 'michi', 'name': '距離鑑定士ミチ', 'trip': '◆MichiDist', 'icon': '📏',
     'knowledge_fn': _knowledge_data, 'truth_level': 'none',
     'system': '競馬予想エージェント「距離鑑定士ミチ」。過去走の距離実績だけで判断。'
               '同距離での好走歴がある馬を◎にせよ。人気は無視。過去走データを読め。物静か。'},
    {'id': 'jin', 'name': '騎手読みジン', 'trip': '◆JinJockey', 'icon': '🏇',
     'knowledge_fn': _knowledge_jockey, 'truth_level': 'none',
     'system': '競馬予想エージェント「騎手読みジン」。騎手のコース成績だけで判断。'
               '当該コースでの勝率が高い騎手の馬を◎にせよ。人気は無視。競馬記者風。'},
    {'id': 'amano', 'name': '逆張り師アマノ', 'trip': '◆AmanoContra', 'icon': '🔄',
     'knowledge_fn': _knowledge_contrarian, 'truth_level': 'none',
     'system': '競馬予想エージェント「逆張り師アマノ」。天邪鬼。'
               '1番人気を絶対に◎にするな。人気薄で過小評価されている馬を探せ。'
               '過去走で好走しているのに人気が低い馬がいないか？挑発的。'
               '【絶対制約】◎は4番人気以下から選べ。'},
    {'id': 'zun', 'name': '統計オタクズン', 'trip': '◆ZunStats', 'icon': '🤓',
     'knowledge_fn': _knowledge_data, 'truth_level': 'full',
     'system': '競馬予想エージェント「統計オタクズン」。数値の異常値を探す。'
               '戦闘力スコアが人気より高い馬、上がり3Fが際立つ馬を見つけろ。オタク風。'},
    {'id': 'yuu', 'name': 'メンタル読みユウ', 'trip': '◆YuuMental', 'icon': '🧠',
     'knowledge_fn': _knowledge_conservative, 'truth_level': 'minimal',
     'system': '競馬予想エージェント「メンタル読みユウ」。'
               '馬体重の変化、休み明け、輸送の影響を重視。大幅増減の馬は危険。'
               '安定した馬体重の馬を◎にせよ。共感的。'},
    {'id': 'kiri', 'name': '配当計算キリ', 'trip': '◆KiriPayout', 'icon': '🧮',
     'knowledge_fn': _knowledge_roi, 'truth_level': 'full',
     'system': '競馬予想エージェント「配当計算キリ」。'
               '3連複の配当構造から最も効率的な3頭を逆算。'
               '人気馬1頭+穴馬2頭の組み合わせが最も配当効率が良い。計算機的。'},
]

_STYLES = ['断定的で強気', '慎重で疑い深い', 'ぶっきらぼうだが鋭い', '冷静沈着で理論派',
           '感情的で熱い', '皮肉屋', '楽観的', '悲観的', 'ユーモア交じり', '哲学的']
_FOCUS = ['オッズの歪み', '過去成績', 'コース実績', '距離実績', '馬体重変化',
          '前走内容', 'ローテーション', '同条件相性', '相手関係', '展開利']


# 各knowledge_fnが与える「情報の切り口」ラベル(人格選択UIで多様性=脱相関を見える化)
_KNOWLEDGE_FOCUS = {
    '_knowledge_conservative': '人気・リスク',
    '_knowledge_longshot': '穴・オッズ歪み',
    '_knowledge_blood': '血統',
    '_knowledge_pace': '展開・ペース',
    '_knowledge_data': 'データ・統計',
    '_knowledge_training': '調教',
    '_knowledge_waku': '枠順・コース',
    '_knowledge_roi': '回収率・オッズ乖離',
    '_knowledge_jockey': '騎手',
    '_knowledge_contrarian': '逆張り',
}


def _agent_focus(ag):
    fn = ag.get('knowledge_fn')
    return _KNOWLEDGE_FOCUS.get(getattr(fn, '__name__', ''), '総合')


def agent_roster():
    """選択可能な名前付き人格の名簿。戻り: [{id,name,icon,focus}]。
    focus=その人格が与える情報の切り口(=多様性の軸)。同じfocusを並べると相関が上がる。"""
    out = []
    for ag in (BASE_AGENTS + _EXTRA_AGENTS):
        out.append({'id': ag['id'], 'name': ag['name'], 'icon': ag.get('icon', '🤖'),
                    'focus': _agent_focus(ag)})
    return out


def agents_by_ids(ids, models=None):
    """指定id(順序保持)の人格だけで討論班を組む。人格・情報の切り口をユーザーが選ぶ用。
    未知idは無視。models複数なら異種モデルを割当。"""
    lut = {ag['id']: ag for ag in (BASE_AGENTS + _EXTRA_AGENTS)}
    agents = [dict(lut[i]) for i in (ids or []) if i in lut]
    if models and len(models) > 1:
        for k, ag in enumerate(agents):
            ag['model'] = models[k % len(models)]
    return agents


def generate_agents(n=5, csv_text='', meta=None, models=None):
    """n体のエージェントリストを生成。modelsが複数あれば異種混合で割り当て。"""
    agents = list(BASE_AGENTS[:min(n, len(BASE_AGENTS))])
    if n <= len(agents):
        agents = agents[:n]
    else:
        extras_needed = n - len(agents)
        for i in range(min(extras_needed, len(_EXTRA_AGENTS))):
            agents.append(dict(_EXTRA_AGENTS[i]))
        remaining = n - len(agents)
        _kfns = [_knowledge_conservative, _knowledge_longshot, _knowledge_data,
                 _knowledge_pace, _knowledge_contrarian, _knowledge_roi,
                 _knowledge_blood, _knowledge_training, _knowledge_waku, _knowledge_jockey]
        for j in range(remaining):
            style = _STYLES[j % len(_STYLES)]
            focus = _FOCUS[j % len(_FOCUS)]
            kfn = _kfns[j % len(_kfns)]
            agents.append({
                'id': f'gen_{j}', 'name': f'予想屋{j+16}号',
                'trip': f'◆Gen{j+16:03d}', 'icon': '🤖',
                'knowledge_fn': kfn,
                'system': f'あなたは競馬予想エージェント「予想屋{j+16}号」。{focus}重視。口調は{style}。',
            })
    if models and len(models) > 1:
        for i, ag in enumerate(agents):
            ag['model'] = models[i % len(models)]
    return agents


AGENTS = BASE_AGENTS


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Ollama通信
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _ollama_chat(system_prompt, user_prompt, model=None, timeout=120):
    model = model or OLLAMA_MODEL
    try:
        r = requests.post(
            f'{OLLAMA_URL}/api/chat',
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt},
                ],
                'stream': False,
                'options': {'temperature': 0.8, 'num_predict': 600},
            },
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json().get('message', {}).get('content', '')
    except requests.ConnectionError:
        return None
    except Exception as e:
        return f'[エラー: {e}]'


def check_ollama():
    try:
        r = requests.get(f'{OLLAMA_URL}/api/tags', timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def get_available_models():
    try:
        r = requests.get(f'{OLLAMA_URL}/api/tags', timeout=5)
        if r.status_code == 200:
            return [m['name'] for m in r.json().get('models', [])]
    except Exception:
        pass
    return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# プロンプト構築
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_TRUTH_MINIMAL = """
【注意事項】
・初ブリンカー/距離短縮/お帰り/季節/初ダートを根拠にするな（検証で否定済み）。
・データ（過去走・上がり・血統成績・調教時計）に基づいて判断せよ。
"""

_TRUTH_FULL = _VERIFIED_TRUTH


def _build_system_with_knowledge(agent, csv_text='', meta=None):
    base = agent['system']
    knowledge = ''
    if agent.get('knowledge_fn'):
        knowledge = agent['knowledge_fn'](csv_text, meta)
    base += knowledge
    retro = _build_retrospective_prompt()
    if retro:
        base += retro
    magi_retro = _build_magi_retrospective()
    if magi_retro:
        base += magi_retro
    truth_level = agent.get('truth_level', 'minimal')
    if truth_level == 'full':
        base += '\n\n' + _TRUTH_FULL
    elif truth_level == 'minimal':
        base += '\n\n' + _TRUTH_MINIMAL
    base += (
        '\n\n重要: 人気順に従うだけの予想は価値がない。あなたの専門性に基づいた独自の視点を出せ。\n'
        'データ（過去走の着順・上がり3F・馬体重・血統成績・調教時計）を読み、根拠を述べよ。\n'
        '予想形式:\n'
        '◎XX番（馬名）理由 / ○XX番（馬名）理由 / ▲XX番（馬名）理由\n'
        '自信度: XX%'
    )
    return base


def build_race_prompt(csv_text, meta_text='', horse_history=''):
    prompt = '以下のレースデータを分析して予想してください。\n\n'
    if meta_text:
        prompt += f'【レース情報】\n{meta_text}\n\n'
    prompt += f'【出走馬データ】\n{csv_text}\n\n'
    if horse_history:
        prompt += f'【出走馬の過去走(DB実データ)】\n{horse_history}\n\n'
    prompt += (
        '上記データと専門知識に基づいて予想。\n'
        '形式: ◎XX番（馬名）理由 / ○XX番（馬名）理由 / ▲XX番（馬名）理由\n'
        '200文字以内。根拠明確。俗説(検証で否定されたもの)を根拠にしないこと。'
    )
    return prompt


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3ラウンド討論
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_discussion(csv_text, meta_text='', agents=None, model=None,
                   progress_cb=None, meta=None):
    """第1ラウンド: 各自の独立予想。"""
    agents = agents or AGENTS
    horse_history = load_horse_history(csv_text)
    prompt = build_race_prompt(csv_text, meta_text, horse_history)
    posts = []
    for i, ag in enumerate(agents):
        if progress_cb:
            progress_cb(i, len(agents), ag['name'])
        sys_prompt = _build_system_with_knowledge(ag, csv_text, meta)
        ag_model = ag.get('model', model)
        t = time.time()
        reply = _ollama_chat(sys_prompt, prompt, model=ag_model)
        elapsed = time.time() - t
        posts.append({
            'no': i + 1, 'agent_id': ag['id'], 'name': ag['name'],
            'trip': ag['trip'], 'icon': ag['icon'],
            'model': ag_model or OLLAMA_MODEL,
            'content': reply or '[Ollama未接続]',
            'timestamp': datetime.now().strftime('%Y/%m/%d %H:%M:%S'),
            'elapsed': round(elapsed, 1),
        })
    return posts


def run_debate(posts, csv_text, meta_text='', agents=None, model=None,
               progress_cb=None, meta=None, anonymous=True):
    """第2ラウンド: 他者の予想を見て反論・修正。anonymous=Trueで匿名化。"""
    agents = agents or AGENTS
    display_posts = _anonymize_posts(posts) if anonymous else posts
    board_text = '\n'.join(
        f">> {p['no']} {p['icon']}{p['name']}: {p['content']}" for p in display_posts)
    anon_note = '(※発言者は匿名化されています。誰が言ったかではなく内容で判断せよ)\n' if anonymous else ''
    debate_prompt = (
        f'{anon_note}他の予想者たちの意見:\n\n{board_text}\n\n'
        f'【レースデータ】\n{csv_text}\n\n'
        '他の意見を踏まえ、自分の最終予想を出せ。\n'
        '同意/反論を明確に。>>番号で言及OK。俗説根拠の予想には反論せよ。\n'
        '最終予想: ◎○▲形式 + 自信度XX%。150文字以内。'
    )
    debate_posts = []
    for i, ag in enumerate(agents):
        if progress_cb:
            progress_cb(i, len(agents), ag['name'])
        sys_prompt = _build_system_with_knowledge(ag, csv_text, meta)
        ag_model = ag.get('model', model)
        t = time.time()
        reply = _ollama_chat(sys_prompt, debate_prompt, model=ag_model)
        elapsed = time.time() - t
        debate_posts.append({
            'no': len(posts) + i + 1, 'agent_id': ag['id'], 'name': ag['name'],
            'trip': ag['trip'], 'icon': ag['icon'],
            'model': ag_model or OLLAMA_MODEL,
            'content': reply or '[Ollama未接続]',
            'timestamp': datetime.now().strftime('%Y/%m/%d %H:%M:%S'),
            'elapsed': round(elapsed, 1),
        })
    return debate_posts


def run_final_defense(all_prior_posts, csv_text, meta_text='', agents=None,
                      model=None, progress_cb=None, meta=None):
    """第3ラウンド: 最終弁論。全意見+中間集計を見て最終回答。"""
    agents = agents or AGENTS
    board_text = '\n'.join(
        f">> {p['no']} {p['icon']}{p['name']}: {p['content']}"
        for p in all_prior_posts[-len(agents)*2:]
    )
    agg = aggregate_predictions(all_prior_posts)
    consensus_text = ''
    if agg:
        consensus_text = '中間集計: ' + ' / '.join(
            f'{um}番={v["total"]}pt(自信{v.get("avg_conf", 0):.0f}%)' for um, v in agg[:5])
    final_prompt = (
        f'これまでの議論:\n{board_text}\n\n{consensus_text}\n\n'
        '【最終弁論】全員の議論を踏まえた最終回答を1つだけ出せ。\n'
        '変更理由があれば述べよ。なければ「維持」。\n'
        '最終: ◎XX番 ○XX番 ▲XX番 + 自信度XX% (100文字以内)'
    )
    final_posts = []
    for i, ag in enumerate(agents):
        if progress_cb:
            progress_cb(i, len(agents), ag['name'])
        sys_prompt = _build_system_with_knowledge(ag, csv_text, meta)
        ag_model = ag.get('model', model)
        t = time.time()
        reply = _ollama_chat(sys_prompt, final_prompt, model=ag_model)
        elapsed = time.time() - t
        final_posts.append({
            'no': len(all_prior_posts) + i + 1, 'agent_id': ag['id'],
            'name': ag['name'], 'trip': ag['trip'], 'icon': ag['icon'],
            'model': ag_model or OLLAMA_MODEL,
            'content': reply or '[Ollama未接続]',
            'timestamp': datetime.now().strftime('%Y/%m/%d %H:%M:%S'),
            'elapsed': round(elapsed, 1),
        })
    return final_posts


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 集計
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _parse_confidence(text):
    """テキストから自信度(%)を抽出。見つからなければ50。"""
    m = re.search(r'自信度?\s*[:：]?\s*(\d{1,3})\s*%', text)
    if m:
        return min(int(m.group(1)), 100)
    m = re.search(r'(\d{1,3})\s*%\s*(?:の自信|自信度)', text)
    if m:
        return min(int(m.group(1)), 100)
    return 50


def aggregate_predictions(all_posts):
    """自信度で重み付けした集計。"""
    votes = {}
    for p in all_posts:
        text = p.get('content', '')
        conf = _parse_confidence(text)
        conf_weight = conf / 100.0
        for mark, key, base_weight in [('◎', 'honmei', 3), ('○', 'taikou', 2), ('▲', 'anaume', 1)]:
            m = re.search(rf'{mark}\s*(\d+)\s*番', text)
            if not m:
                m = re.search(rf'{mark}(\d+)', text)
            if m:
                um = int(m.group(1))
                if um not in votes:
                    votes[um] = {'honmei': 0, 'taikou': 0, 'anaume': 0,
                                 'total': 0, 'weighted': 0.0,
                                 'conf_sum': 0.0, 'conf_n': 0,
                                 'agents': []}
                votes[um][key] += 1
                votes[um]['total'] += base_weight
                votes[um]['weighted'] += base_weight * conf_weight
                votes[um]['conf_sum'] += conf
                votes[um]['conf_n'] += 1
                votes[um]['agents'].append(f"{p['icon']}{mark}")
    for v in votes.values():
        v['avg_conf'] = v['conf_sum'] / v['conf_n'] if v['conf_n'] else 50
    return sorted(votes.items(), key=lambda x: -x[1]['weighted'])


def extract_agent_picks(all_posts):
    """各エージェントの◎○▲を辞書で返す（回顧学習保存用）。"""
    picks = {}
    for p in all_posts:
        text = p.get('content', '')
        agent_pick = {}
        for mark, key in [('◎', 'honmei'), ('○', 'taikou'), ('▲', 'anaume')]:
            m = re.search(rf'{mark}\s*(\d+)\s*番', text)
            if not m:
                m = re.search(rf'{mark}(\d+)', text)
            if m:
                agent_pick[key] = int(m.group(1))
        agent_pick['confidence'] = _parse_confidence(text)
        picks[p.get('agent_id', p.get('name', ''))] = agent_pick
    return picks


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# エージェントBrier加重（カード8=進化的集合知・当たらないペルソナを減衰）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def agent_track_record(records=None):
    """各エージェントの精算済み成績を集計。
    ◎(honmei)が3着内なら hit=1。Brier=平均(1-hit)（p=1のカテゴリ予測のBrier）。
    戻り値: {agent_id: {'n','hits','hit_rate','brier'}}。台帳空なら {}。"""
    if records is None:
        records = load_retrospective(100)
    acc = {}
    for rec in records:
        if not rec.get('result'):
            continue
        for ag_id, picks in (rec.get('agent_picks') or {}).items():
            if 'hit' not in picks:
                continue
            d = acc.setdefault(ag_id, {'n': 0, 'hits': 0})
            d['n'] += 1
            d['hits'] += 1 if picks['hit'] else 0
    out = {}
    for ag_id, d in acc.items():
        hr = d['hits'] / d['n'] if d['n'] else 0.0
        out[ag_id] = {'n': d['n'], 'hits': d['hits'], 'hit_rate': hr, 'brier': 1.0 - hr}
    return out


def agent_weights(records=None, lam=1.0, prior_n=10):
    """Brier加重 w_i ∝ exp(-λ·Brier_i)。低nはプール平均へ収縮(prior_n擬似数)。
    ⚠ 安全性: λ=0 で全員均等・台帳が空でも全員均等(=単純平均に縮退)。
    戻り値: {agent_id: weight}（合計1に正規化）。台帳空なら {}（呼び手が均等扱い）。"""
    tr = agent_track_record(records)
    if not tr or lam <= 0:
        # 均等（台帳無し or λ=0）。keyだけは返す。
        n = len(tr)
        return {ag: 1.0 / n for ag in tr} if n else {}
    pooled_brier = sum(d['brier'] * d['n'] for d in tr.values()) / max(
        sum(d['n'] for d in tr.values()), 1)
    raw = {}
    for ag, d in tr.items():
        # 収縮Brier: 実測とプール平均を n:prior_n で混合
        sb = (d['brier'] * d['n'] + pooled_brier * prior_n) / (d['n'] + prior_n)
        raw[ag] = __import__('math').exp(-lam * sb)
    s = sum(raw.values()) or 1.0
    return {ag: w / s for ag, w in raw.items()}


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = sum((a - mx) ** 2 for a in xs)
    sy = sum((b - my) ** 2 for b in ys)
    if sx <= 0 or sy <= 0:
        return None  # どちらか定数=相関定義不能
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    return cov / (sx ** 0.5 * sy ** 0.5)


def agent_pick_correlation(records=None):
    """エージェント同士の予想相関を測る(アンサンブルが効くのは低相関の時=記事の効かない条件)。
    ◎=3/○=2/▲=1でスコア化し、ペアの"どちらかが印を付けた馬"上でPearson相関を蓄積。
    結果(hit)は不要=予想だけで測れる。戻り値:
      {'pairs':[{a,b,corr,honmei_agree,n}], 'redundancy':{agent:平均相関},
       'mean_corr':float|None, 'n_races':int, 'note':str}。
    高相関(>0.7)=人格が冗長=平均する意味が薄い([[project_magi_consensus]]偽アンサンブルの罠)。"""
    from collections import defaultdict as _dd
    if records is None:
        records = load_retrospective(100)
    pair_cells = _dd(list)      # (a,b) -> [(scoreA,scoreB)...]
    pair_honmei = _dd(lambda: [0, 0])
    n_races = 0
    for rec in records:
        picks = rec.get('agent_picks') or {}
        ags = [a for a in picks
               if any(picks[a].get(k) for k in ('honmei', 'taikou', 'anaume'))]
        if len(ags) < 2:
            continue
        n_races += 1

        def _score(a):
            d = {}
            for mark, val in (('honmei', 3), ('taikou', 2), ('anaume', 1)):
                u = picks[a].get(mark)
                if u:
                    try:
                        d[int(u)] = val
                    except (TypeError, ValueError):
                        pass
            return d
        sc = {a: _score(a) for a in ags}
        for i in range(len(ags)):
            for j in range(i + 1, len(ags)):
                a, b = sorted((ags[i], ags[j]))
                ua, ub = sc[a], sc[b]
                uni = set(ua) | set(ub)          # どちらかが印を付けた馬(ペア固有)
                if len(uni) < 3:
                    continue
                for u in uni:
                    pair_cells[(a, b)].append((ua.get(u, 0), ub.get(u, 0)))
                ha, hb = picks[a].get('honmei'), picks[b].get('honmei')
                if ha and hb:
                    pair_honmei[(a, b)][1] += 1
                    if str(ha) == str(hb):
                        pair_honmei[(a, b)][0] += 1

    pairs = []
    red = _dd(lambda: [0.0, 0])
    for (a, b), cells in pair_cells.items():
        r = _pearson([c[0] for c in cells], [c[1] for c in cells])
        hm = pair_honmei[(a, b)]
        pairs.append({'a': a, 'b': b, 'corr': r,
                      'honmei_agree': (hm[0] / hm[1]) if hm[1] else None, 'n': hm[1]})
        if r is not None:
            for x in (a, b):
                red[x][0] += r
                red[x][1] += 1
    pairs.sort(key=lambda p: (p['corr'] is None, -(p['corr'] or 0)))
    redundancy = {a: (v[0] / v[1]) for a, v in red.items() if v[1]}
    corrs = [p['corr'] for p in pairs if p['corr'] is not None]
    mean_corr = sum(corrs) / len(corrs) if corrs else None
    note = ('データ不足(数レース分の予想を集合知で保存すると相関が出ます)'
            if n_races < 3 or not corrs else
            '相関>0.7=人格が冗長=平均の効果薄→同データのLLM人格を増やさず直交エッジに紐付けよ')
    return {'pairs': pairs, 'redundancy': redundancy, 'mean_corr': mean_corr,
            'n_races': n_races, 'note': note}


def weighted_consensus(all_posts, weights=None):
    """aggregate_predictions のエージェント重み付き版(カード8)。
    weights={agent_id: w}。未知/欠損エージェントは平均重みで中立。
    weights=None or 空 → 全員均等(=aggregate_predictionsと同結果)。
    戻り値: aggregate_predictions と同形式の sorted[(um, dict)]。"""
    weights = weights or {}
    default_w = (sum(weights.values()) / len(weights)) if weights else 1.0
    votes = {}
    for p in all_posts:
        text = p.get('content', '')
        conf_weight = _parse_confidence(text) / 100.0
        aw = weights.get(p.get('agent_id', p.get('name', '')), default_w)
        for mark, key, base_weight in [('◎', 'honmei', 3), ('○', 'taikou', 2), ('▲', 'anaume', 1)]:
            m = re.search(rf'{mark}\s*(\d+)\s*番', text) or re.search(rf'{mark}(\d+)', text)
            if not m:
                continue
            um = int(m.group(1))
            v = votes.setdefault(um, {'honmei': 0, 'taikou': 0, 'anaume': 0,
                                      'total': 0, 'weighted': 0.0, 'agents': []})
            v[key] += 1
            v['total'] += base_weight
            v['weighted'] += base_weight * conf_weight * aw
            v['agents'].append(f"{p.get('icon', '')}{mark}")
    return sorted(votes.items(), key=lambda x: -x[1]['weighted'])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 分科会方式 (Divide-and-Conquer) — 15体超の大規模討論用
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_group_discussion(csv_text, meta_text='', agents=None, model=None,
                         progress_cb=None, meta=None, group_size=5):
    """大規模エージェント用の分科会方式。
    1) agents を group_size ごとにグループ分け
    2) 各グループ内で R1 独立予想
    3) グループ内で R2 議論
    4) 各グループの代表（◎最多得票）を集め、代表者会議を開催
    戻り値: (group_posts_list, representative_posts, final_ranking)
    """
    agents = agents or AGENTS
    n = len(agents)
    if n <= group_size:
        r1 = run_discussion(csv_text, meta_text, agents, model, progress_cb, meta)
        r2 = run_debate(r1, csv_text, meta_text, agents, model, progress_cb, meta)
        ranking = aggregate_predictions(r1 + r2)
        return [r1], r2, ranking

    groups = [agents[i:i+group_size] for i in range(0, n, group_size)]
    all_group_posts = []
    group_summaries = []
    post_counter = 0

    for gi, group in enumerate(groups):
        if progress_cb:
            progress_cb(0, len(groups), f'グループ{gi+1}/{len(groups)} 討論中')
        def _gcb(i, total, name):
            if progress_cb:
                progress_cb(i, total, f'G{gi+1}: {name}')
        g_r1 = run_discussion(csv_text, meta_text, group, model, _gcb, meta)
        for p in g_r1:
            post_counter += 1
            p['no'] = post_counter
            p['name'] = f'[G{gi+1}] {p["name"]}'
        g_r2 = run_debate(g_r1, csv_text, meta_text, group, model, _gcb, meta, anonymous=True)
        for p in g_r2:
            post_counter += 1
            p['no'] = post_counter
            p['name'] = f'[G{gi+1}] {p["name"]}'
        all_group_posts.extend(g_r1 + g_r2)
        g_agg = aggregate_predictions(g_r1 + g_r2)
        if g_agg:
            top = g_agg[0]
            group_summaries.append(
                f'グループ{gi+1}({len(group)}体): '
                f'◎{top[0]}番({top[1]["total"]}pt/自信{top[1].get("avg_conf",50):.0f}%)')

    summary_text = '\n'.join(group_summaries)
    rep_prompt = (
        f'各分科会の結論:\n{summary_text}\n\n'
        f'【レースデータ】\n{csv_text}\n\n'
        '全分科会の結論を踏まえた最終予想を出せ。\n'
        '分科会の多数派に同意するか、異なる結論か、根拠を添えて。\n'
        '最終: ◎XX番 ○XX番 ▲XX番 + 自信度XX%'
    )
    rep_agents = [groups[i][0] for i in range(len(groups)) if groups[i]]
    rep_posts = []
    for i, ag in enumerate(rep_agents):
        if progress_cb:
            progress_cb(i, len(rep_agents), f'代表者会議: {ag["name"]}')
        sys_prompt = _build_system_with_knowledge(ag, csv_text, meta)
        ag_model = ag.get('model', model)
        t = time.time()
        reply = _ollama_chat(sys_prompt, rep_prompt, model=ag_model)
        elapsed = time.time() - t
        post_counter += 1
        rep_posts.append({
            'no': post_counter, 'agent_id': ag['id'],
            'name': f'[代表] {ag["name"]}', 'trip': ag['trip'], 'icon': '👑',
            'model': ag_model or OLLAMA_MODEL,
            'content': reply or '[Ollama未接続]',
            'timestamp': datetime.now().strftime('%Y/%m/%d %H:%M:%S'),
            'elapsed': round(elapsed, 1),
        })

    final_ranking = aggregate_predictions(all_group_posts + rep_posts)
    return all_group_posts, rep_posts, final_ranking
