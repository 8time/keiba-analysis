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




# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 検証済みシグナル担当の知識パック(2026-07再設計)
# 旧ペルソナ(血統単体/展開単体/調教単体/距離単体/強制逆張り)は単体でpriced-inと
# 確定済みのため廃止し、実際にholdoutで残差有意と確認済みのモジュールへ差し替え。
# ここから下の関数は core/ の検証済みモジュールを直接呼ぶ(新規ロジックは作らない)。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _parse_horse_rows(csv_text):
    """CSVから馬ごとの{name,umaban,waku,pop,jockey}を返す(名前解決の材料集め用)。"""
    import io, csv as csvmod
    out = []
    if not csv_text:
        return out
    try:
        reader = csvmod.DictReader(io.StringIO(csv_text))
        for row in reader:
            nm = (row.get('馬名') or row.get('Name') or '').strip()
            if not nm or nm == '-':
                continue
            def _num(key):
                v = (row.get(key) or '').strip()
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return None
            out.append({
                'name': nm, 'umaban': _num('馬番'), 'waku': _num('枠'),
                'pop': _num('人気'), 'jockey': (row.get('騎手') or '').strip(),
            })
    except Exception:
        pass
    return out


def _knowledge_corrected_time(csv_text='', meta=None):
    """🔵補正Tオタク: 直近7走×同一馬場の最高補正タイム(検証済み最強シグナル・holdout z+10.4)。"""
    from core import corrected_time as _ct
    from core import jockey_jv as _jj
    surf = (meta or {}).get('surface', '')
    rows = _parse_horse_rows(csv_text)
    lines = []
    for h in rows:
        kt, _ = _jj.resolve_horse(h['name'])
        if not kt:
            continue
        fig = _ct.get_figure(kt, surface=surf)
        if fig and fig.get('fig') is not None:
            lines.append(f"{h.get('umaban', '?')}番{h['name']}: 補正T {fig['fig']:.0f}"
                         f"({fig.get('runs', 0)}走)")
    base = (
        '\n【あなたの専門知識: 補正タイム(検証済み最強シグナル・荒れ予報holdout z+10.4)】\n'
        '・補正タイム=直近7走×同一馬場の最高値(高いほど速い)。数値が高い馬ほど信頼できる。\n'
        '・本命の補強に強く効く(+5pp)。穴には弱い(+1pp)ので過信しすぎない。\n'
    )
    if lines:
        base += '\n【今回の補正タイム(DB)】\n' + '\n'.join(lines) + '\n'
    return base


def _knowledge_lap33(csv_text='', meta=None):
    """🌀33ラップ使いのラプ: 中盤3F-上がり3Fの適合判定(人気薄6+でholdout z+3.3〜+6.8)。"""
    from core import lap33 as _l3
    from core import jockey_jv as _jj
    surf = (meta or {}).get('surface', '')
    try:
        kyori = int((meta or {}).get('distance') or 0)
    except (TypeError, ValueError):
        kyori = 0
    rows = _parse_horse_rows(csv_text)
    course = _l3.course_avg33(surf, kyori) if (surf and kyori) else None
    lines = []
    for h in rows:
        kt, _ = _jj.resolve_horse(h['name'])
        if not kt:
            continue
        fit = _l3.horse_fit33(kt)
        if fit.get('avg_lap33') is None:
            continue
        match_txt = ''
        if course and course.get('avg'):
            m = _l3.fit_match(fit['avg_lap33'], course['avg'])
            match_txt = {'True': '⚡適合', 'False': '不適合'}.get(str(m), '')
        lines.append(f"{h.get('umaban', '?')}番{h['name']}: 33ラップ{fit['avg_lap33']:+.2f}"
                     f"({fit.get('lean', '?')}) {match_txt}")
    base = (
        '\n【あなたの専門知識: 33ラップ理論(検証済み・人気薄6番人気以下限定でz+3.3〜+6.8)】\n'
        '・馬の得意ペース型(瞬発力型/持久力型)とコース平均が一致(適合)する馬は人気薄で来やすい。\n'
        '・人気上位馬では独立エッジ無し(織込み済み)。適合の話は人気薄の馬でのみ意味を持つ。\n'
    )
    if lines:
        base += '\n【今回の33ラップ適合(DB)】\n' + '\n'.join(lines) + '\n'
    return base


def _knowledge_spurt(csv_text='', meta=None):
    """🔥末脚読みハヤ: 上がり3Fがスロー由来か(信頼)/ハイ由来か(バテ差し注意・z≈0)。"""
    from core import pace_spurt as _ps
    from core import jockey_jv as _jj
    rows = _parse_horse_rows(csv_text)
    lines = []
    for h in rows:
        kt, _ = _jj.resolve_horse(h['name'])
        if not kt:
            continue
        q = _ps.spurt_quality(kt)
        if q.get('tag'):
            lines.append(f"{h.get('umaban', '?')}番{h['name']}: {q['tag']}"
                         f"(スロー{q['slow']}/ハイ{q['high']})")
    base = (
        '\n【あなたの専門知識: 末脚指数(検証済み)】\n'
        '・前走スローペースで上がり上位だった馬(🐢)は次走も信頼できる(z+3.8〜8.5)。\n'
        '・ハイペース由来の上がり上位(⚡)は次走では効果なし(z≈0・バテ差し注意)。\n'
        '・ペースの中身を見ずに「上がりが速い」だけで判断すると同じ罠にはまる。\n'
    )
    if lines:
        base += '\n【今回の末脚判定(DB)】\n' + '\n'.join(lines) + '\n'
    return base


def _knowledge_jpower(csv_text='', meta=None):
    """🏇騎手力屋パワ: 騎手のみの力(JPower偏差値・50=平均・実力として持続確認済み)。"""
    from core import jockey_jv as _jj
    rows = _parse_horse_rows(csv_text)
    lines = []
    for h in rows:
        if not h.get('jockey'):
            continue
        jp = _jj.jockey_power(h['jockey'])
        if jp.get('jpower') is not None:
            lines.append(f"{h.get('umaban', '?')}番{h['name']}: 騎手{h['jockey']} "
                         f"JPower{jp['jpower']:.0f}({jp.get('rides', 0)}騎乗)")
    base = (
        '\n【あなたの専門知識: 騎手力JPower(検証済み・holdout方向維持z+2.0)】\n'
        '・JPower=騎手のみの力を偏差値化(50が平均)。数値が高い騎手ほど実力として持続する。\n'
        '・効果量は小さめ(比較用)。予測を全部これで決めるほどの強さではない点は正直に伝えよ。\n'
    )
    if lines:
        base += '\n【今回のJPower(DB)】\n' + '\n'.join(lines) + '\n'
    return base


def _knowledge_dirt_draw(csv_text='', meta=None):
    """🎰枠信号師ワク: ダート枠順バイアス(外枠×1-3人気+4.5pp/内枠×4-5人気-3.9pp・検証済)。"""
    from core import track_bias as _tb
    surf = str((meta or {}).get('surface', '') or '')
    if 'ダ' not in surf:
        return (
            '\n【あなたの専門知識: 枠順(ダート限定のエッジ)】\n'
            '・検証済みの枠順エッジはダート戦限定(外枠×1-3人気/内枠×4-5人気)。\n'
            '・今回は芝またはダート以外のため、このエッジは対象外。無理に枠を語らない。\n'
        )
    race_id = str((meta or {}).get('race_id', '') or '')
    jyo = race_id[4:6] if len(race_id) >= 6 else None
    try:
        kyori = int((meta or {}).get('distance') or 0) or None
    except (TypeError, ValueError):
        kyori = None
    rows = _parse_horse_rows(csv_text)
    lines = []
    for h in rows:
        if h.get('waku') is None or h.get('pop') is None:
            continue
        sig = _tb.dirt_draw_signal(h['waku'], h['pop'], 'ダート', jyo=jyo, kyori=kyori)
        if sig:
            tag = '🟢外枠軸補強' if sig['type'] == 'boost' else '🔻内枠危険'
            lines.append(f"{h.get('umaban', '?')}番{h['name']}: 枠{h['waku']} {tag}")
    base = (
        '\n【あなたの専門知識: ダート枠順バイアス(検証済み)】\n'
        '・外枠(6-8)×1-3番人気=複勝残差+4.5pp(z+9.4)。軸に向く強い材料。\n'
        '・内枠(1-3)×4-5番人気=複勝残差-3.9pp(z-6.0)。軸から外す目安。\n'
    )
    if lines:
        base += '\n【今回の枠信号(DB)】\n' + '\n'.join(lines) + '\n'
    else:
        base += '\n該当する枠信号の馬は今回いない。無理に枠の話を作らないこと。\n'
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
        # actual_topはdict想定だが、旧形式/NARで馬番intのみの記録が混在する場合がある(要ガード)
        actual = [a for a in (rec.get('actual_top', []) or []) if isinstance(a, dict)]
        if not actual:
            continue
        actual_top3 = [a['umaban'] for a in actual[:3] if 'umaban' in a]
        hit = set(pred) & set(actual_top3)
        missed = set(actual_top3) - set(pred)
        winner = actual[0] if actual else {}
        winner_pop = winner.get('pop', 0)
        lesson = f'レース{rec.get("race_id","?")}:'
        if missed:
            missed_info = []
            for a in actual[:3]:
                if a.get('umaban') in missed:
                    missed_info.append(f'{a.get("name","?")}({a.get("umaban","?")}番/{a.get("pop","?")}人気/上{a.get("agari",0)})')
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

# ── ペルソナ構成(2026-07再設計) ──
# 旧構成は「人気を見るな」という縛りが全ペルソナ共通で入っていた(このファイル自身が
# _VERIFIED_TRUTHに『予測精度の92%は人気の力』と書いているのに矛盾)うえ、多くの
# knowledge_fnが使い回し(血統師ケイ/道悪博士ヌマが同一knowledge_fn等)で個性が
# 見た目だけだった。→ 各ペルソナに実際にholdoutで残差有意と確認済みのモジュールを
# 1つずつ割り当て、「人気無視」の強制をやめ「担当シグナルを主軸に、市場と一致するなら
# 素直に一致を報告」という自然な個性に変更(repo/opus_brief_agent_forum_redesign.md参照)。
BASE_AGENTS = [
    {'id': 'ken', 'name': '保守派ケン', 'trip': '◆KenHoshu', 'icon': '🛡️',
     'knowledge_fn': _knowledge_conservative, 'truth_level': 'full',
     'system': 'あなたは競馬予想エージェント「保守派ケン」。市場(人気・オッズ)を基準に、'
               '他のエージェントの逆張りが行き過ぎていないかブレーキ役を務める。'
               '人気上位馬(1-3番人気)を軸にする。リスクを指摘し穴馬への過信を戒める。落ち着いた敬語。'},
    {'id': 'hoseiT', 'name': '補正Tオタク', 'trip': '◆HoseiT', 'icon': '🔵',
     'knowledge_fn': _knowledge_corrected_time, 'truth_level': 'full',
     'system': 'あなたは競馬予想エージェント「補正Tオタク」。補正タイム(荒れ予報最強シグナル・'
               '検証z+10.4)を主軸に語る。数値が高い馬を評価するが、市場(人気)と一致するなら'
               '素直にそう報告せよ。無理に逆張りする必要はない。オタク気質で数値を熱く語る。'},
    {'id': 'lap33', 'name': '33ラップ使いのラプ', 'trip': '◆Lap33', 'icon': '🌀',
     'knowledge_fn': _knowledge_lap33, 'truth_level': 'full',
     'system': 'あなたは競馬予想エージェント「33ラップ使いのラプ」。33ラップ理論(人気薄6番人気'
               '以下限定で検証z+3.3〜+6.8)を主軸に語る。人気上位馬では効かないと正直に言う。'
               '職人気質で簡潔。'},
    {'id': 'hayaSpurt', 'name': '末脚読みハヤ', 'trip': '◆HayaSpurt', 'icon': '🔥',
     'knowledge_fn': _knowledge_spurt, 'truth_level': 'full',
     'system': 'あなたは競馬予想エージェント「末脚読みハヤ」。末脚指数(スロー由来の上がりのみ'
               '信頼・検証z+3.8〜8.5)を主軸に語る。ハイペース由来の上がりは効かないと正直に'
               '言う。熱血でテンポ良く話す。'},
    {'id': 'powerJk', 'name': '騎手力屋パワ', 'trip': '◆PowerJk', 'icon': '🏇',
     'knowledge_fn': _knowledge_jpower, 'truth_level': 'full',
     'system': 'あなたは競馬予想エージェント「騎手力屋パワ」。騎手力JPower(検証済み・'
               '実力として持続確認済みだが効果量は小さめ)を主軸に語る。過信せず控えめに'
               '評価すること。理系・淡々とした口調。'},
    {'id': 'wakuDirt', 'name': '枠信号師ワク', 'trip': '◆WakuDirt', 'icon': '🎰',
     'knowledge_fn': _knowledge_dirt_draw, 'truth_level': 'full',
     'system': 'あなたは競馬予想エージェント「枠信号師ワク」。ダート枠順バイアス'
               '(外枠×1-3人気+4.5pp/内枠×4-5人気-3.9pp・検証済)を主軸に語る。'
               '芝レースやダート以外ではこのエッジは使えないと正直に言う。老練で簡潔。'},
]

_EXTRA_AGENTS = []  # 旧エキストラ(血統/展開/調教/距離単体・強制逆張り)は全てpriced-in
                    # 確定済みのため廃止。追加人格が必要になった場合はBASE_AGENTSと同じ
                    # 「検証済みモジュール1つを担当」方針で追加すること(単体要因の復活は禁止)。

_STYLES = ['断定的で強気', '慎重で疑い深い', 'ぶっきらぼうだが鋭い', '冷静沈着で理論派',
           '感情的で熱い', '皮肉屋', '楽観的', '悲観的', 'ユーモア交じり', '哲学的']
_FOCUS = ['補正タイム', '33ラップ適合', '末脚指数', '騎手力', 'ダート枠信号', '市場(人気)基準']


# 各knowledge_fnが与える「情報の切り口」ラベル(人格選択UIで多様性=脱相関を見える化)
_KNOWLEDGE_FOCUS = {
    '_knowledge_conservative': '人気・市場基準',
    '_knowledge_corrected_time': '補正タイム',
    '_knowledge_lap33': '33ラップ適合',
    '_knowledge_spurt': '末脚指数',
    '_knowledge_jpower': '騎手力(JPower)',
    '_knowledge_dirt_draw': 'ダート枠信号',
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
        # BASE_AGENTS(6体)を超えて要求された分は既存6人格の担当を再利用する
        # (旧: 血統/展開/調教単体等priced-in確定済みの知識関数を使い回していた不具合を修正。
        #  単体要因の復活を禁止する方針のため、ここも検証済みモジュールのみで循環させる)。
        _kfns = [_knowledge_conservative, _knowledge_corrected_time, _knowledge_lap33,
                 _knowledge_spurt, _knowledge_jpower, _knowledge_dirt_draw]
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
        '\n\n重要: あなたの担当シグナルを主軸に述べよ。市場(人気・オッズ)と一致するなら'
        'それも正直に報告せよ。無理に人気を無視したり逆張りする必要はない'
        '(このアプリの検証では予測精度の大半は人気の力であることが分かっている)。\n'
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
    戻り値: aggregate_predictions と同形式の sorted[(um, dict)]。

    ※2026-07ペルソナ再設計との移行安全性: 旧agent_id(ken/kei/riku等・廃止済み)の
    過去精算は data/agent_retrospective.json に残したまま削除していない
    (agent_weights()もそのまま計算する)。ただし新ペルソナのid(hoseiT/lap33等)は
    現行のsession_postsにしか登場しないため、旧idの重みはdefault_w(平均重み)の
    算出にのみ寄与し、新ペルソナ全員が同じdefault_wを受け取る=実質均等スタートになる。
    新ペルソナの実績が台帳に貯まるにつれ、自然にBrier加重が効いてくる設計。"""
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
