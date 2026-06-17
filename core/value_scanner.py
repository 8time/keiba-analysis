# -*- coding: utf-8 -*-
"""
妙味レース・妙味馬スキャナの中核ロジック（純粋関数／スクレイピング無し）。
Race Scanner(バッチ)から1日のカードを横断し「買えるレース×妙味馬」を抽出する。

設計方針(資料 Data_Driven_Racing / 危険な人気馬の解体新書 を検証して採用):
- 見送りレース判定 = 新馬/未勝利1戦/2歳/障害/少頭数/単勝1倍台大本命(資料の「情報量・妙味欠如」)
- 妙味度スコア(race-level) = 頭数/1番人気オッズ/1-3番人気オッズ差/オッズばらつき
  ＋構造条件(ハンデ/フルゲート/不良馬場/ローカル芝/オープン以上/芝短ダ長) の集約。
  現スキャナのスコア差gap判定の上位互換。
- 単複乖離(検証済): 単勝≥10倍 かつ 複勝(mid)≤3.0倍 → 勝率2.5%→7%・勝利残差+0.017・単勝回収+17pp
  (scripts のバックテスト 90年代n=13.5万で確認。単純比率≥7は逆効果のため不採用)。
- 馬ごとの＋/−ファクターは強適消去エンジン([[project-elimination-engine]])と同一定義を流用。

すべて測ってから採用(測定=scripts/elimination_backtest.py, dangerfav_backtest.py, 本ファイル冒頭の単複乖離検証)。
"""
import re
from datetime import datetime

LOCAL_JYO = {'01', '02', '03', '04', '07', '10'}  # 札幌函館福島新潟中京小倉
OPEN_CLASSES = {'オープン', 'G1', 'G2', 'G3', 'GI', 'GII', 'GIII', 'L', 'リステッド'}


# ───────────────────────── 見送りレース判定 ─────────────────────────
def race_skip_reasons(meta, n_horses, surface='', race_name='', min_win_odds=None):
    """見送り(購入非推奨)理由のリストを返す。空なら検討可。
    資料: 新馬/未勝利1戦/2歳/障害=情報不足、少頭数=妙味なし、単勝1倍台=リターン不足。"""
    reasons = []
    cls = str((meta or {}).get('class', '') or '')
    rn = str(race_name or (meta or {}).get('RaceName', '') or '')
    surf = str(surface or '')
    blob = cls + ' ' + rn
    if '障' in surf or '障害' in blob:
        reasons.append('障害戦')
    if '新馬' in blob:
        reasons.append('新馬戦')
    if '未勝利' in blob:
        reasons.append('未勝利戦')
    if re.search(r'2歳|２歳', blob):
        reasons.append('2歳戦')
    if n_horses and n_horses <= 10:
        reasons.append(f'少頭数({n_horses}頭)')
    if min_win_odds is not None and min_win_odds < 2.0:
        reasons.append(f'単勝1倍台の大本命({min_win_odds:.1f})')
    return reasons


# ───────────────────────── 妙味度スコア(race-level) ─────────────────────────
def race_value_score(odds_list, meta=None, jyo='', surface='', dist=None, n_horses=None,
                     pace_z=None):
    """1レースの妙味度(0-100目安)とラベル/内訳を返す。
    odds_list: 単勝オッズの list[float]（人気順に並んでなくてよい）。
    高いほど『荒れ＝1番人気が信頼しにくく中穴妙味が出やすい』。
    pace_z: 事前ペース強度z(pace_map.predict_pace_intensity の z・高い=ハイ想定)。
            検証(pace_predict_backtest 2021-25): ハイ想定は1番人気オッズ層を固定しても
            荒れ率を押す(中層リフト1.11・事後ペース天井1.15に肉薄)。中程度のエッジゆえ
            加点も中程度に留める。スロー想定は前残りで堅め=減点。"""
    meta = meta or {}
    odds = sorted([float(o) for o in (odds_list or []) if o and float(o) > 0])
    breakdown = []
    score = 0.0

    # --- オッズ分布(市場の確信度) ---
    fav = odds[0] if odds else None
    if fav is not None:
        # 1番人気オッズ: 3.0倍以上=人気割れ(資料・危険1番人気)。高いほど加点。
        if fav >= 5.0:
            score += 24; breakdown.append(f'1番人気{fav:.1f}倍=混戦(+24)')
        elif fav >= 3.5:
            score += 18; breakdown.append(f'1番人気{fav:.1f}倍=人気割れ(+18)')
        elif fav >= 2.5:
            score += 10; breakdown.append(f'1番人気{fav:.1f}倍(+10)')
        elif fav < 1.5:
            score -= 12; breakdown.append(f'1番人気{fav:.1f}倍=鉄板(-12)')
    if len(odds) >= 3:
        # 1-3番人気の差が小さい=上位拮抗=荒れやすい
        spread = odds[2] - odds[0]
        if spread <= 1.5:
            score += 16; breakdown.append(f'上位3頭拮抗(差{spread:.1f}・+16)')
        elif spread <= 3.0:
            score += 8; breakdown.append(f'上位やや拮抗(差{spread:.1f}・+8)')
    # 中穴ゾーン(単勝5-15倍=黄金ゾーン)の頭数: 多いほど狙い目が多い
    midfield = sum(1 for o in odds if 5.0 <= o <= 15.0)
    if midfield >= 4:
        score += 12; breakdown.append(f'中穴黄金ゾーン{midfield}頭(+12)')
    elif midfield >= 2:
        score += 6; breakdown.append(f'中穴ゾーン{midfield}頭(+6)')

    # --- 構造条件(資料: 1番人気が崩れる/荒れる条件) ---
    n = n_horses or len(odds)
    if n >= 16:
        score += 12; breakdown.append(f'フルゲート({n}頭・+12)')
    elif n >= 14:
        score += 6; breakdown.append(f'多頭数({n}頭・+6)')
    if meta.get('is_handicap') or meta.get('weight_rule') == 'ハンデ':
        score += 10; breakdown.append('ハンデ戦(+10)')
    cond = str(meta.get('condition', '') or '')
    if cond in ('不良', '重'):
        score += 8; breakdown.append(f'{cond}馬場(+8)')
    cls = str(meta.get('class', '') or '')
    if any(c in cls for c in OPEN_CLASSES):
        score += 6; breakdown.append('オープン級(+6)')
    surf = str(surface or '')
    if str(jyo) in LOCAL_JYO and '芝' in surf:
        score += 6; breakdown.append('ローカル芝(+6)')
    try:
        d = int(dist) if dist else 0
        if '芝' in surf and 0 < d <= 1400:
            score += 5; breakdown.append('芝短距離(+5)')
        elif 'ダ' in surf and d >= 2400:
            score += 5; breakdown.append('ダート長距離(+5)')
    except Exception:
        pass

    # --- 事前ペース強度(テン速力ベース・検証済の荒れ寄与) ---
    if pace_z is not None:
        if pace_z >= 0.7:
            score += 9; breakdown.append(f'🌀ハイペース想定(z{pace_z:+.1f}・差し台頭で荒れ寄り+9)')
        elif pace_z >= 0.2:
            score += 4; breakdown.append(f'ややハイペース想定(z{pace_z:+.1f}・+4)')
        elif pace_z <= -0.5:
            score -= 6; breakdown.append(f'🏁スローペース想定(z{pace_z:+.1f}・前残り堅め-6)')

    score = max(0.0, min(100.0, score))
    if score >= 55:
        label = 'S 大荒れ妙味'
    elif score >= 40:
        label = 'A 荒れ妙味'
    elif score >= 25:
        label = 'B 中庸'
    elif score >= 12:
        label = 'C やや堅い'
    else:
        label = 'D 鉄板(妙味薄)'
    return {'score': round(score, 1), 'label': label, 'breakdown': breakdown, 'fav_odds': fav}


# ───────────────────────── 単複乖離(検証済の妙味馬シグナル) ─────────────────────────
def tanpuku_divergence(win_odds, place_mid):
    """単複乖離の強さを返す。
    win_odds≥10 かつ place_mid≤3.0 で『単勝が過小評価された妙味馬』(検証済)。
    戻り値: (level:int 0-2, text:str)。0=該当なし。"""
    try:
        w = float(win_odds); p = float(place_mid)
    except (TypeError, ValueError):
        return 0, ''
    if w < 10 or p <= 0:
        return 0, ''
    if p <= 2.0:
        return 2, f'単複乖離(単{w:.0f}÷複{p:.1f})'
    if p <= 3.0:
        return 1, f'単複乖離(単{w:.0f}÷複{p:.1f})'
    return 0, ''


# ───────────────────────── オッズ断層(検証済の堅め妙味) ─────────────────────────
def odds_gap_anchors(odds_by_um, ratio=2.0, max_rank=6, max_odds=30.0):
    """『断層直前＝強グループの末端馬』の馬番set を返す。
    単勝オッズ昇順で、次の馬のオッズが ratio 倍以上に跳ねる直前の馬。
    検証(90年代): 3着内残差+0.039(z+12.3)。ただし人気帯別で再検証した結果、
    エッジは人気上位に集中（人気1-3=+0.068 z+14.3 / 人気4-6=+0.033 z+4.8 / 人気7+=+0.004 効果なし）、
    オッズ≤10=+0.049/10-30=+0.030/30超=弱。→ 人気≤max_rank かつ オッズ≤max_odds の anchor のみ採用。
    ※オッズDBが90年代のみのため要・現代再検証。"""
    items = sorted([(u, float(o)) for u, o in (odds_by_um or {}).items()
                    if o and float(o) > 0], key=lambda x: x[1])
    anchors = set()
    for i in range(len(items) - 1):
        if items[i + 1][1] / items[i][1] >= ratio:
            rank = i + 1  # オッズ昇順＝人気順位
            if rank <= max_rank and items[i][1] <= max_odds:
                anchors.add(items[i][0])
    return anchors


# ───────────────────────── 馬ごとの＋/−ファクター(消去エンジンと同一) ─────────────────────────
def horse_value_factors(row, jj, jyo, surface, dist, month, min_year, place_mid=None,
                        date_val='', gap_anchor=False):
    """1頭の検証済み＋(妙味)/−(危険)ファクターを判定。
    row: get_race_data の1行(dict-like; Name/Jockey/SexAge/WeightCarried/Weight/Popularity/Odds)。
    jj : core.jockey_jv モジュール。戻り値: dict。"""
    name = str(row.get('Name', '') or '')
    jky = str(row.get('Jockey', '') or '')
    sa = str(row.get('SexAge', '') or '')
    pop = _num(row.get('Popularity'))
    odds = _num(row.get('Odds'))
    pos, neg = [], []
    try:
        kt, tc = jj.resolve_horse(name)
    except Exception:
        kt, tc = None, None

    g = jj.jockey_trainer_combo(jky, tc) if tc else None
    if g and g.get('rides', 0) >= 10 and g.get('top2', 0) >= 0.40:
        pos.append(f"黄金ライン(連対{g['top2']:.0%}/{g['rides']})")
    cs = jj.trainer_course_winrate(tc, jyo, surface, min_year=min_year) if tc else None
    if cs and cs.get('runs', 0) >= 10 and (cs.get('win_rate') or 0) >= 0.20:
        pos.append(f"厩舎当ｺｰｽ{cs['win_rate']:.0%}")

    ctx = jj.horse_recent_context(kt) if kt else None
    if ('牝' in sa) and month in (12, 1, 2, 3, 4, 5):
        neg.append('牝' + ('冬' if month in (12, 1, 2) else '春') + 'ﾌｪｰﾄﾞ')
    if ctx and ctx.get('prev_dist') and dist and abs(dist - ctx['prev_dist']) >= 400:
        neg.append('大幅距離変更')
    if ('ダ' in str(surface)) and ctx and ctx.get('dirt_runs', 0) == 0:
        neg.append('初ダート')
    if ctx and ctx.get('prev_ninki') and ctx.get('prev_chaku') \
            and ctx['prev_ninki'] >= 6 and ctx['prev_chaku'] <= 3:
        neg.append('前走フロック')
    pvj = (ctx or {}).get('prev_jockey')
    if ctx and pvj and jj.jockey_is_top(pvj) and not _same_jk(_njk(jky), _njk(pvj)):
        neg.append('トップ騎手乗替')
    try:
        fk = float(row.get('WeightCarried'))
        bwm = re.match(r'(\d+)', str(row.get('Weight', '')))
        if bwm and int(bwm.group(1)) > 0 and fk / int(bwm.group(1)) >= 0.126:
            neg.append('斤量比≥12.6%')
    except (TypeError, ValueError):
        pass
    # 注: 半年休み明けは jravan.db の直近(2025-26)収録が疎で休養日数を過大算出し誤爆するため、
    # スキャナでは不採用(元々 z-1.7 で有意でない。date_val/prev_date は他用途で温存)。
    if ctx and ctx.get('prev_kyaku') == '1':
        neg.append('前走逃げ')

    # 🔥末脚救出(独立シグナル): 人気薄(6番人気以下)×末脚指数≥0.8×2走以上。
    # 検証(scripts/spurt_index_backtest.py 2021-25): 6番人気以下×末脚指数≥0.8で
    # 複勝率13.2%/単ROI69%(ベース9.4%/66.4%)。単複乖離とはANDで掛けない独立救出。
    si = (ctx or {}).get('spurt_index')
    sr = (ctx or {}).get('spurt_runs', 0)
    if pop and pop >= 6 and si is not None and si >= 0.8 and sr >= 2:
        pos.append(f"🔥末脚救出(指数{si:.1f})")

    # 単複乖離(妙味)
    div_level, div_text = (0, '')
    if place_mid is not None:
        div_level, div_text = tanpuku_divergence(odds, place_mid)
        if div_text:
            pos.append(div_text)

    # オッズ断層上位(堅め妙味・90s検証)
    if gap_anchor:
        pos.append('オッズ断層上位')

    return {
        'pos': pos, 'neg': neg, 'has_pos': bool(pos), 'has_neg': bool(neg),
        'div_level': div_level, 'anchor': bool(gap_anchor),
        'pop': int(pop) if pop == pop and pop else None,
        'odds': float(odds) if odds == odds and odds else None,
    }


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float('nan')


def _njk(s):
    return ''.join(str(s or '').split())


def _same_jk(a, b):
    return bool(a and b and (a == b or (len(a) >= 2 and len(b) >= 2
                and (a.startswith(b) or b.startswith(a)))))
