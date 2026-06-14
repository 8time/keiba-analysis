# -*- coding: utf-8 -*-
"""
コーナー別・想定位置取りマップ（展開マップ）。

JRA-VAN実データ（jravan.db: 過去走のコーナー別通過順位・上がり3F）があれば
各馬の「コーナーごとの実際の動き方」（テンの速さ・マクリ・直線の伸び）から
局面別の想定隊列を推定する。なければ脚質スコアと馬番のヒューリスティックに
フォールバック。

座標系:
  X = 前後（右が前方・先頭）
  Y = 内外（下が内ラチ、上が外）
"""
import os
import math
import sqlite3

JV_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db'
)

# 馬番→開催場（race_id の5-6桁目）
VENUE_CODES = {
    '01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
    '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉',
}
LEFT_TURN_VENUES = {'東京', '中京', '新潟'}

STYLE_COLORS = {
    '逃げ': '#E63946', '先行': '#F4A261',
    '差し': '#457B9D', '追込': '#6A4C93', '不明': '#8d8d8d',
}

# ──────────────────────────────────────────────
# コースレイアウト諸元（目安値）
# ──────────────────────────────────────────────

# 最後の直線の長さ（m・目安）: (開催場, 芝/ダ) → m。芝の内/外回りは距離で分岐
_STRAIGHT_LEN = {
    ('札幌', '芝'): 266, ('札幌', 'ダ'): 264,
    ('函館', '芝'): 262, ('函館', 'ダ'): 260,
    ('福島', '芝'): 292, ('福島', 'ダ'): 296,
    ('新潟', 'ダ'): 354,
    ('東京', '芝'): 525, ('東京', 'ダ'): 502,
    ('中山', '芝'): 310, ('中山', 'ダ'): 308,
    ('中京', '芝'): 412, ('中京', 'ダ'): 410,
    ('京都', 'ダ'): 329,
    ('阪神', 'ダ'): 353,
    ('小倉', '芝'): 293, ('小倉', 'ダ'): 291,
}

# スタート→最初のコーナーまでの距離（m・目安）。主要コースのみ
_FIRST_CORNER = {
    ('東京', '芝', 1600): 540, ('東京', '芝', 1800): 160,
    ('東京', '芝', 2000): 130, ('東京', '芝', 2400): 350,
    ('東京', 'ダ', 1600): 640, ('東京', 'ダ', 2100): 240,
    ('中山', '芝', 1200): 275, ('中山', '芝', 1600): 240,
    ('中山', '芝', 2000): 405,
    ('中山', 'ダ', 1200): 500, ('中山', 'ダ', 1800): 375,
    ('阪神', '芝', 1600): 444, ('阪神', '芝', 2200): 525,
    ('阪神', 'ダ', 1800): 300,
    ('京都', '芝', 1200): 600, ('京都', '芝', 1600): 710,
    ('京都', '芝', 2000): 310, ('京都', 'ダ', 1800): 285,
    ('中京', '芝', 1600): 315, ('中京', '芝', 2000): 315,
    ('中京', 'ダ', 1800): 290,
    ('新潟', '芝', 1600): 550,
    ('福島', '芝', 1200): 410,
    ('小倉', '芝', 1200): 480,
}


def get_course_layout(venue, surface, distance):
    """
    コースレイアウト諸元を返す（目安値）。
    戻り値: {'first_corner': m|None, 'straight': m|None,
             'straight_course': bool, 'notes': [str, ...]}
    """
    try:
        d = int(distance)
    except Exception:
        d = 0
    surf = 'ダ' if 'ダ' in str(surface) else '芝'

    # 新潟芝1000m 直線競馬
    if venue == '新潟' and surf == '芝' and d == 1000:
        return {'first_corner': None, 'straight': 1000,
                'straight_course': True,
                'notes': ['直線1000m競馬: コーナーなし。枠（外有利傾向）とテンのダッシュ力が全て']}

    # 直線長: 芝の内/外回りを距離で近似
    straight = None
    if venue == '新潟' and surf == '芝':
        straight = 659 if d in (1400, 1600, 1800, 2000) else 359
    elif venue == '京都' and surf == '芝':
        straight = 404 if (d >= 1400 and d != 2000) else 328
    elif venue == '阪神' and surf == '芝':
        straight = 474 if d in (1600, 1800, 2400, 2600) else 356
    else:
        straight = _STRAIGHT_LEN.get((venue, surf))

    fc = _FIRST_CORNER.get((venue, surf, d))
    notes = []
    if fc is not None:
        if fc < 200:
            notes.append(f"最初のコーナーまで約{fc}m＝極端に短い。枠の有利不利大・ペース上がりにくい（内枠先行有利）")
        elif fc >= 550:
            notes.append(f"最初のコーナーまで約{fc}m＝長い。先行争いが長引きやすくハイペース化注意。枠の差は小さい")
    if straight is not None and not (venue == '新潟' and d == 1000):
        if straight < 330:
            notes.append(f"直線約{straight}m＝短い。3角からのロングスパート戦になりやすく内・先行有利。追込は届きにくい")
        elif straight >= 450:
            notes.append(f"直線約{straight}m＝長い。直線の瞬発力勝負になりやすく差し・追込の不利が小さい")
    return {'first_corner': fc, 'straight': straight,
            'straight_course': False, 'notes': notes}


def venue_from_race_id(race_id):
    """12桁レースIDから開催場名を返す。不明なら ''"""
    try:
        return VENUE_CODES.get(str(race_id)[4:6], '')
    except Exception:
        return ''


def course_profile_label(venue, surface, distance):
    """
    競馬場×芝ダ×距離（内/外回りは距離で近似）から、適性カテゴリ3種のラベルを返す。
    get_course_layout の実測直線長ベースなので、東京ダ短距離と東京芝長距離、
    京都/阪神の内回り/外回りを正しく区別できる（従来の競馬場コード単独判定より精緻）。
    calculate_strength_suitability が見る『直線が長い』『小回り』の語を含む。
    """
    lay = get_course_layout(venue, surface, distance)
    s = lay.get('straight')
    if s is None:
        return '✨ 標準 (バランス)'
    if s >= 400:
        return '✨ 直線が長い・差し有利 (東京/外回り 等)'
    if s <= 335:
        return '✨ 小回り・先行有利 (中山/小倉/札幌 等)'
    return '✨ 標準 (バランス)'


def infer_turn(venue):
    """開催場名から回り方向（'右' / '左'）を返す。"""
    return '左' if venue in LEFT_TURN_VENUES else '右'


def score_from_pastruns(past_runs, max_runs=5):
    """
    PastRuns（scraper形式）から脚質スコアを推定するフォールバック。
    Passing '3-3-2-1' の最終コーナー値の平均 / 14頭想定 で 0〜1 に正規化。
    """
    vals = []
    for run in (past_runs or [])[:max_runs]:
        passing = str(run.get('Passing', '') or '')
        nums = [int(x) for x in passing.replace('→', '-').split('-') if x.strip().isdigit()]
        if nums:
            vals.append(nums[-1])
    if not vals:
        return 0.5
    avg = sum(vals) / len(vals)
    return max(0.05, min(0.95, avg / 14.0))


def style_from_score(score):
    if score < 0.18:
        return '逃げ'
    if score < 0.42:
        return '先行'
    if score < 0.72:
        return '差し'
    return '追込'


def _parse_jv_time(s):
    """JVの走破タイム '1330' → 93.0（秒）。'MSSt'（分秒秒0.1秒）形式。失敗時 None。"""
    s = str(s or '').strip()
    if not s.isdigit() or int(s) == 0:
        return None
    tenths = int(s[-1])
    secs = int(s[-3:-1] or 0)
    mins = int(s[:-3] or 0)
    return mins * 60 + secs + tenths / 10.0


# kyakushitsu（JV公式脚質） → 想定ポジション素点 0〜1（0=先頭）
_KYAKU_POS = {'1': 0.06, '2': 0.30, '3': 0.62, '4': 0.85}


def fetch_jv_profiles(names, db_path=None, max_runs=5,
                      surface=None, distance=None, before_key=None):
    """
    JRA-VAN DB から各馬の「コーナー別 実トラジェクトリ＋テン速力＋脚質」を取得する。

    names: 馬名リスト（netkeibaのカタカナ表記。JVのbameiと一致する）
    surface/distance: 指定すると、テン速力は同馬場・距離±400mの過去走を優先採用する。
    before_key: race_key 文字列。指定するとそれ未満の過去走のみ使う（バックテスト用に
                「未来のデータ」を遮断する。Noneなら全走歴）。
    戻り値: {name: {
        'c1','c2','c3','c4': コーナー別平均位置 0〜1（0=先頭, None=データなし）,
        'ten': テン位置（最初に記録があるコーナーの平均・0〜1）,
        'ten_speed': テン速力（秒/600m換算。小さいほどテンが速い=前に行く）,
        'nige_rate','senko_rate': 逃げ率・先行(逃げ含む)率（kyakushitsu基準 0〜1）,
        'kyaku_pos': 脚質コードから推定する平均ポジション 0〜1（0=逃げ）,
        'front3_rate': 過去走で道中3番手以内だった割合 0〜1,
        'agari': 上がり3F相対順位 0〜1（0=メンバー最速）,
        'agari_time','agari_best': 上がり3F平均/自己ベスト（秒）,
        'n_runs': 使用過去走数,
    }}
    """
    db = db_path or JV_DB_PATH
    if not os.path.exists(db):
        return {}
    surf = None
    if surface is not None:
        surf = 'ダ' if 'ダ' in str(surface) else '芝'
    try:
        dist = int(distance) if distance else None
    except Exception:
        dist = None

    out = {}
    try:
        con = sqlite3.connect(db)
        cur = con.cursor()
        for raw_name in names:
            name = str(raw_name).strip().replace('　', '').replace(' ', '')
            if not name:
                continue
            params = [name]
            where = "r.bamei = ? AND r.chakujun > 0"
            if before_key:
                where += " AND r.race_key < ?"
                params.append(str(before_key))
            params.append(max_runs)
            rows = cur.execute(
                f"""SELECT r.corner1, r.corner2, r.corner3, r.corner4, r.ato3f,
                          ra.shusso_tosu, r.race_key, r.time, ra.kyori, ra.surface,
                          r.kyakushitsu, r.chakujun
                   FROM results r JOIN races ra ON ra.race_key = r.race_key
                   WHERE {where}
                   ORDER BY r.race_key DESC LIMIT ?""",
                params,
            ).fetchall()
            if not rows:
                continue
            sums = {k: [0.0, 0] for k in ('c1', 'c2', 'c3', 'c4', 'agari', 'agari_time', 'finish')}
            agari_best = None
            ten_speeds = []          # (ten_speed, 条件一致度) のリスト
            kyaku_counts = {'1': 0, '2': 0, '3': 0, '4': 0}
            kyaku_total = 0
            front3 = [0, 0]          # [3番手以内回数, 判定可能回数]
            for idx, (c1, c2, c3, c4, ato, tosu, rkey, rtime, rkyori, rsurf, kyaku, chaku) in enumerate(rows):
                tosu = tosu or 0
                if tosu < 2:
                    continue
                # 走ごとの重み: 条件類似度（同馬場・距離近接）× 直近重み（新しい走ほど重い）
                cond_w = 1.0
                if surf is not None and rsurf:
                    cond_w *= 1.6 if surf in str(rsurf) else 0.5
                if dist is not None and rkyori:
                    cond_w *= 1.4 if abs(rkyori - dist) <= 400 else 0.6
                run_w = cond_w * (0.82 ** idx)   # idx=0 が最新走
                for key, val in (('c1', c1), ('c2', c2), ('c3', c3), ('c4', c4)):
                    if val and val > 0:
                        sums[key][0] += min(1.0, (val - 1) / max(tosu - 1, 1)) * run_w
                        sums[key][1] += run_w
                # 着順履歴（能力proxy: 過去の相対着順 0=勝利。条件・直近重み付き）
                if chaku and chaku > 0:
                    sums['finish'][0] += min(1.0, (chaku - 1) / max(tosu - 1, 1)) * run_w
                    sums['finish'][1] += run_w
                # 道中3番手以内（最初に記録のあるコーナーの実順位で判定）
                early_rank = next((v for v in (c1, c2, c3, c4) if v and v > 0), None)
                if early_rank is not None:
                    front3[1] += 1
                    if early_rank <= 3:
                        front3[0] += 1
                # 上がり3F（相対順位は加重、実タイムは素のまま平均）
                if ato and ato > 0:
                    faster = cur.execute(
                        "SELECT COUNT(*) FROM results WHERE race_key=? AND ato3f>0 AND ato3f<?",
                        (rkey, ato),
                    ).fetchone()[0]
                    sums['agari'][0] += min(1.0, faster / max(tosu - 1, 1)) * run_w
                    sums['agari'][1] += run_w
                    sums['agari_time'][0] += ato / 10.0
                    sums['agari_time'][1] += 1
                    if agari_best is None or ato / 10.0 < agari_best:
                        agari_best = ato / 10.0
                # テン速力: (走破タイム − 上がり3F) / (距離−600) × 600
                t = _parse_jv_time(rtime)
                if t is not None and ato and ato > 0 and rkyori and rkyori > 700:
                    ts = (t - ato / 10.0) / (rkyori - 600) * 600.0
                    if 25.0 < ts < 60.0:  # 異常値ガード
                        ten_speeds.append((ts, run_w))
                # 脚質
                k = str(kyaku or '').strip()
                if k in kyaku_counts:
                    kyaku_counts[k] += 1
                    kyaku_total += 1
            prof = {}
            for k in ('c1', 'c2', 'c3', 'c4', 'agari', 'agari_time', 'finish'):
                prof[k] = round(sums[k][0] / sums[k][1], 3) if sums[k][1] else None
            prof['finish_hist'] = prof.pop('finish')   # 過去相対着順（能力proxy・0=勝利）
            prof['agari_best'] = round(agari_best, 2) if agari_best is not None else None
            prof['ten'] = next((prof[k] for k in ('c1', 'c2', 'c3', 'c4') if prof[k] is not None), None)
            prof['n_runs'] = len(rows)
            if ten_speeds:
                wsum = sum(w for _, w in ten_speeds)
                prof['ten_speed'] = round(sum(ts * w for ts, w in ten_speeds) / wsum, 3)
            else:
                prof['ten_speed'] = None
            if kyaku_total:
                prof['nige_rate'] = round(kyaku_counts['1'] / kyaku_total, 3)
                prof['senko_rate'] = round((kyaku_counts['1'] + kyaku_counts['2']) / kyaku_total, 3)
                prof['kyaku_pos'] = round(
                    sum(_KYAKU_POS[k] * c for k, c in kyaku_counts.items()) / kyaku_total, 3)
            else:
                prof['nige_rate'] = prof['senko_rate'] = prof['kyaku_pos'] = None
            prof['front3_rate'] = round(front3[0] / front3[1], 3) if front3[1] else None
            # テン位置・テン速力・脚質のいずれかがあれば採用
            if prof['ten'] is not None or prof['ten_speed'] is not None or prof['kyaku_pos'] is not None:
                out[str(raw_name)] = prof
        con.close()
    except Exception:
        return out
    return out


def phases_for_distance(distance):
    """距離からフェーズ構成を決める。短距離はバックストレッチ発走で1-2角なし。"""
    try:
        d = int(distance)
    except Exception:
        d = 0
    if 0 < d <= 1400:
        return ['スタート', '3角', '4角', '直線']
    return ['スタート', '1角', '2角', '3角', '4角', '直線']


# フェーズごとの (脚質ブレンド率, 隊列ストレッチ, 差し馬の進出度, 外回し度)
# ※ JVプロファイルがない馬のフォールバック用
_PHASE_PARAMS = {
    'スタート': (0.40, 0.55, 0.00, 0.0),
    '1角':      (0.80, 0.90, 0.00, 0.2),
    '2角':      (0.90, 1.00, 0.00, 0.1),
    '3角':      (0.95, 1.00, 0.10, 0.6),
    '4角':      (1.00, 0.90, 0.22, 1.0),
    '直線':     (1.00, 0.75, 0.35, 1.3),
}

# フェーズ → JVプロファイルのコーナーキー（フォールバック順）
_PHASE_PROF_KEYS = {
    '1角': ('c1', 'c2', 'c3'),
    '2角': ('c2', 'c1', 'c3'),
    '3角': ('c3', 'c2', 'c4'),
    '4角': ('c4', 'c3', 'c2'),
}


def _phase_frac(phase, prof, score, gate_frac, gate_w=0.45, straight_push=0.45):
    """
    1頭の馬の、指定フェーズでの想定位置 0〜1（0=先頭）を返す。
    JVプロファイル（過去走の実コーナー通過位置）があればそれを使い、
    なければ脚質スコアのヒューリスティック。
    gate_w: スタート時の枠の影響度（1角まで短いコースほど大きい）
    straight_push: 直線での上がり3F押し上げ係数（直線が長いほど大きい）
    """
    if prof:
        if phase == 'スタート':
            ten = prof.get('ten')
            if ten is not None:
                # ゲート直後は枠の影響が残る（コースの1角までの距離で可変）
                return (1 - gate_w) * ten + gate_w * gate_frac
        elif phase == '直線':
            base = prof.get('c4')
            if base is None:
                base = next((prof.get(k) for k in ('c3', 'c2', 'c1') if prof.get(k) is not None), None)
            if base is not None:
                agari = prof.get('agari')
                if agari is not None:
                    # 上がり最速級(agari→0)は直線で位置を押し上げる（直線長で可変）
                    base = base - (0.5 - agari) * straight_push
                return max(0.0, min(1.0, base))
        else:
            for key in _PHASE_PROF_KEYS.get(phase, ()):
                if prof.get(key) is not None:
                    return prof[key]
    # フォールバック: 脚質スコア
    w_style, _, advance, _ = _PHASE_PARAMS[phase]
    if phase == 'スタート':
        w_style = 1 - gate_w
    f = w_style * score + (1 - w_style) * gate_frac
    f -= max(0.0, score - 0.55) * advance
    return max(0.0, min(1.0, f))


def _zscore_map(d):
    """{key: value|None} → {key: z|None}。値が少なすぎる場合は全て0。"""
    vals = [v for v in d.values() if v is not None]
    if len(vals) < 2:
        return {k: (0.0 if v is not None else None) for k, v in d.items()}
    m = sum(vals) / len(vals)
    sd = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5 or 1e-9
    return {k: ((v - m) / sd if v is not None else None) for k, v in d.items()}


# フォワード度の重み・相互作用パラメータ（pace_backtest で較正した既定値）
# 知見: 4角順位の最有力シグナルは「条件類似度・直近重み付きのコーナー履歴」。
# テン速力は先頭(ハナ)予測を小さく改善。相互作用はランキングへの寄与は小さいが
# マップ表示とハナ確定の明瞭化に有効なため軽めに残す。
_PACE_TUNE = {
    # コーナー履歴ブレンド（4角想定の最有力シグナル・後半コーナーほど重視）
    'ch_c4': 1.0, 'ch_c3': 0.55, 'ch_c2': 0.20, 'ch_c1': 0.12, 'ch_ten': 0.0,
    # forward 合成の各シグナル重み
    'w_corner': 3.0,    # コーナー履歴（最重要）
    'w_ten': 0.25,      # テン速力 z-score（ハナ予測を改善）
    'w_kyaku': 0.20,    # 脚質コード平均位置
    'w_score': 0.25,    # app由来の脚質スコア（フォールバック）
    'ten_z_k': 0.16,    # テン速力 z → frac 係数
    # 相互作用（pos4 への補正・小さく保つ）
    'int_leader_cap': 0.05,   # ハナ馬をこの値以下へ
    'int_contested': 0.03,    # ハイで番手争い馬を後退
    'int_slow_pow': 1.04,     # スローの前残り誇張指数
    'int_adjacent': 0.0,      # 同型隣接ペナルティ
}


def build_pace_context(horses, profiles=None, distance=None, surface=None,
                       layout=None, wind=None, tune=None):
    """
    出走各馬の「フォワード度」(0=逃げ〜1=最後方) を推定し、ハナ確定・ペース分類・
    4角想定隊列(相互作用込み)までを解決して返す。estimate_pace_map とバックテストが共用。

    戻り値: {
      'forward': {umaban: 0〜1}, 'pos4': {umaban: 0〜1},
      'leader': umaban|None, 'pace': 'スロー'|'ミドル'|'ハイ',
      'front_ratio': float, 'contested': bool, 'nige_umas': [umaban,...], 'wind': wind,
    }
    """
    t = dict(_PACE_TUNE)
    if tune:
        t.update(tune)
    horses = [h for h in horses if h.get('umaban')]
    profiles = profiles or {}
    layout = layout or {}
    n = len(horses)
    ctx = {'forward': {}, 'pos4': {}, 'leader': None, 'pace': 'ミドル',
           'front_ratio': 0.0, 'contested': False, 'nige_umas': [], 'wind': wind}
    if n < 2:
        return ctx

    # ── 1. フォワード度（道中の基本ポジション 0=先頭） ──
    ten_speed = {h['umaban']: (profiles.get(h.get('name', '')) or {}).get('ten_speed')
                 for h in horses}
    z_ten = _zscore_map(ten_speed)
    forward = {}
    for h in horses:
        u = h['umaban']
        prof = profiles.get(h.get('name', '')) or {}
        # コーナー履歴ブレンド（実績ベースの最有力シグナル: 後半コーナーほど重視）
        ch_parts, ch_w = [], []
        for key, wk in (('c4', t['ch_c4']), ('c3', t['ch_c3']), ('c2', t['ch_c2']),
                        ('c1', t['ch_c1']), ('ten', t['ch_ten'])):
            if wk and prof.get(key) is not None:
                ch_parts.append(prof[key])
                ch_w.append(wk)
        corner_hist = (sum(p * w for p, w in zip(ch_parts, ch_w)) / sum(ch_w)
                       if ch_parts else None)

        parts, weights = [], []
        if corner_hist is not None:
            parts.append(corner_hist)
            weights.append(t['w_corner'])
        if z_ten.get(u) is not None and ten_speed.get(u) is not None:
            parts.append(min(0.97, max(0.03, 0.5 + z_ten[u] * t['ten_z_k'])))
            weights.append(t['w_ten'])
        if prof.get('kyaku_pos') is not None:
            parts.append(prof['kyaku_pos'])
            weights.append(t['w_kyaku'])
        sc = h.get('score')
        if sc is not None:
            parts.append(float(sc))
            weights.append(t['w_score'] if parts else 1.0)
        forward[u] = (sum(p * w for p, w in zip(parts, weights)) / sum(weights)
                      if parts else 0.5)
    ctx['forward'] = {u: round(v, 3) for u, v in forward.items()}

    # ── 2. 逃げ候補とペース分類 ──
    order = sorted(forward, key=lambda u: (forward[u], u))
    nige_umas = [u for u in order if forward[u] < 0.20] or order[:1]
    ctx['nige_umas'] = nige_umas
    ctx['contested'] = len(nige_umas) >= 2

    # 前3番手率: JV実績(front3_rate)が十分あれば優先、なければフォワード度で代替
    fr_vals = [(profiles.get(h.get('name', '')) or {}).get('front3_rate') for h in horses]
    judgeable = [v for v in fr_vals if v is not None]
    if len(judgeable) >= max(3, n * 0.5):
        front_ratio = sum(1 for v in judgeable if v >= 0.5) / len(judgeable)
    else:
        front_ratio = sum(1 for u in forward if forward[u] < 0.30) / n
    ctx['front_ratio'] = round(front_ratio, 3)

    if front_ratio >= 0.40 or len(nige_umas) >= 3:
        pace = 'ハイ'
    elif front_ratio < 0.30 and len(nige_umas) <= 1:
        pace = 'スロー'
    else:
        pace = 'ミドル'
    if len(nige_umas) >= 4:   # Lohengrinのパラドックス: 共倒れ予見→相互牽制で落ち着く
        pace = 'ミドル'
    ctx['pace'] = pace

    # ── 3. ハナ確定（テン速い→内枠優先で1頭に） ──
    leader = sorted(nige_umas,
                    key=lambda u: (forward[u],
                                   ten_speed.get(u) if ten_speed.get(u) is not None else 99, u))[0]
    ctx['leader'] = leader

    # ── 4. 4角想定位置（相互作用込み・補正は小さく保つ） ──
    pos4 = dict(forward)
    if t['int_leader_cap']:
        pos4[leader] = min(pos4[leader], t['int_leader_cap'])
    if t['int_contested'] and ctx['contested'] and pace == 'ハイ':
        for u in nige_umas[1:]:
            pos4[u] = min(0.97, pos4[u] + t['int_contested'])
    if t['int_slow_pow'] and pace == 'スロー':
        for u in pos4:
            pos4[u] = pos4[u] ** t['int_slow_pow']
    if t['int_adjacent']:
        senko_set = {u for u in forward if forward[u] < 0.42}
        for u in list(senko_set):
            if (u - 1 in senko_set) or (u + 1 in senko_set):
                pos4[u] = min(0.97, pos4[u] + t['int_adjacent'])
    ctx['pos4'] = {u: round(min(0.99, max(0.01, v)), 3) for u, v in pos4.items()}
    return ctx


def predict_corner_order(horses, profiles=None, distance=None, surface=None,
                         layout=None, tune=None):
    """4角想定隊列を {umaban: 0〜1（0=先頭）} で返す。バックテスト・外部評価用の薄いラッパ。"""
    return build_pace_context(horses, profiles, distance, surface, layout,
                              tune=tune).get('pos4', {})


# 直線(到達=着順)位置の合成重み（pace_backtest の着順評価で較正）
# 知見: 旧来の「直線=4角位置」は実着順との相関0.16で最悪。着順履歴・決め手・適性に加え、
# 人気/単勝オッズ（市場の総意＝最も分かりやすく強い単一指標）を足すとさらに改善。
# w_apt は JV単独では検証不可（均一=定数オフセットでランキング不変）だが、ライブの
# 強適Ranking Table(適性Suitability)で効くため保持。
_FINISH_TUNE = {
    'w_pos4': 0.4,        # 4角のトラック位置（前にいる利）
    'w_kick': 0.5,        # 決め手（上がり3F・差し脚）
    'w_apt': 0.4,         # 適性（このコース・条件への向き／ライブのみ）
    'w_power': 0.8,       # 総合力（着順履歴 or 総合戦闘力）
    'w_pop': 1.4,         # 人気/単勝オッズ（市場の総意。最強の単一指標・約40%）
    'reach_penalty': 0.3,  # 4角で離れすぎ＋決め手平凡なら届かない物理補正
}
# 注: 着順予測の精度だけなら w_pop を上げ「人気のみ」(spearman0.55)に寄せるほど高いが、
# 適性・決め手で穴馬(例:アウダーシア人気8で1着)を前方に出す余地を残すため約40%に抑制。


def _rank_norm(d):
    """{u: value|None} → {u: 0〜1（0=最小値）}。値が少なければ全0.5。Noneは0.5。"""
    items = [(u, v) for u, v in d.items() if v is not None]
    if len(items) < 2:
        return {u: 0.5 for u in d}
    order = sorted(items, key=lambda kv: (kv[1], kv[0]))
    n = len(order)
    rn = {u: i / (n - 1) for i, (u, _) in enumerate(order)}
    for u in d:
        rn.setdefault(u, 0.5)
    return rn


def predict_finish(horses, profiles=None, ctx=None, extras=None, tune=None):
    """
    直線での到達位置（≒着順）を {umaban: 0〜1（0=勝ち）} で推定する。
    4角のトラック位置(pos4) に、決め手(上がり3F)・適性・総合力を合成し、
    「後方から決め手で差し込む馬」を直線で前方へ押し上げる。

    extras[umaban] = {'kick','apt','power','pop'}（各 値で小さいほど良い / None=欠損）。
      app側で 強適Ranking Table（AvgAgari=決め手, Suitability=適性, BattleScore=総合力,
      Popularity=人気）を渡せる。kick/power/pop は JV実データ（agari相対・finish_hist・
      ninki）でも代替可。各シグナルは内部で順位正規化(0=最良)される。
    """
    t = dict(_FINISH_TUNE)
    if tune:
        t.update(tune)
    horses = [h for h in horses if h.get('umaban')]
    profiles = profiles or {}
    extras = extras or {}
    ctx = ctx or {}
    pos4 = ctx.get('pos4', {})
    name_of = {h['umaban']: h.get('name', '') for h in horses}
    us = [h['umaban'] for h in horses]
    if len(us) < 2:
        return {u: pos4.get(u, 0.5) for u in us}

    def _from(field_extra, field_prof):
        out = {}
        for u in us:
            e = extras.get(u, {})
            if e.get(field_extra) is not None:
                out[u] = e[field_extra]
            else:
                out[u] = (profiles.get(name_of[u]) or {}).get(field_prof)
        return out

    kick_n = _rank_norm(_from('kick', 'agari'))
    power_raw = _from('power', 'finish_hist')
    power_n = (_rank_norm(power_raw) if any(v is not None for v in power_raw.values())
               else {u: 0.5 for u in us})
    apt_raw = {u: extras.get(u, {}).get('apt') for u in us}
    apt_n = (_rank_norm(apt_raw) if any(v is not None for v in apt_raw.values())
             else {u: 0.5 for u in us})
    pop_raw = {u: extras.get(u, {}).get('pop') for u in us}
    pop_n = (_rank_norm(pop_raw) if any(v is not None for v in pop_raw.values())
             else {u: 0.5 for u in us})

    wsum = t['w_pos4'] + t['w_kick'] + t['w_apt'] + t['w_power'] + t['w_pop']
    finish = {}
    for u in us:
        p4 = pos4.get(u, 0.5)
        base = (t['w_pos4'] * p4 + t['w_kick'] * kick_n[u] + t['w_apt'] * apt_n[u]
                + t['w_power'] * power_n[u] + t['w_pop'] * pop_n[u]) / wsum
        # 物理: 4角で大きく離れ(>0.6)かつ決め手が平凡(>0.5)なら届かず後退
        if p4 > 0.6 and kick_n[u] > 0.5:
            base += (p4 - 0.6) * (kick_n[u] - 0.5) * t['reach_penalty']
        finish[u] = max(0.0, min(1.0, base))
    return finish


# 各フェーズで「4角想定位置(pos4)」へどれだけ寄せるか（スタートは枠・forward主体）
_PHASE_TO4 = {'スタート': 0.0, '1角': 0.5, '2角': 0.78, '3角': 0.93, '4角': 1.0, '直線': 1.0}


def estimate_pace_map(horses, distance=None, profiles=None, layout=None,
                      surface=None, wind=None, extras=None):
    """
    horses: [{'umaban': int, 'name': str, 'score': float, 'style': str}, ...]
    profiles: fetch_jv_profiles の戻り値（name→プロファイル）。任意。
    layout: get_course_layout の戻り値（コース諸元による補正）。任意。
    surface/wind: テン速力フィルタ・直線の風補正に使用（任意）。
    extras: predict_finish 用の {umaban: {'kick','apt','power'}}（強適Ranking Table由来）。任意。
    戻り値: {phase: [{'umaban','name','style','score','x','y','jv'}, ...]}
    """
    horses = [h for h in horses if h.get('umaban')]
    n = len(horses)
    if n < 2:
        return {}
    profiles = profiles or {}
    layout = layout or {}

    ctx = build_pace_context(horses, profiles, distance, surface, layout, wind)
    forward = ctx['forward']
    pos4 = ctx['pos4']
    wind_eff = wind_effect(wind) if wind else None
    # 直線=到達(着順)位置: 4角位置＋決め手＋適性＋総合力で「差し込み」を表現
    finish = predict_finish(horses, profiles, ctx, extras=extras)

    # コース補正: 1角までの距離 → 枠の影響度
    fc = layout.get('first_corner')
    if fc is not None:
        gate_w = 0.62 if fc < 200 else 0.50 if fc < 350 else 0.40 if fc < 550 else 0.28
    else:
        gate_w = 0.45
    # 直線の長さ → 上がり3Fの押し上げ係数
    straight = layout.get('straight')
    if straight is not None:
        straight_push = 0.28 if straight < 330 else 0.45 if straight < 450 else 0.60
    else:
        straight_push = 0.45

    max_uma = max(h['umaban'] for h in horses)
    gate_fracs = {h['umaban']: (h['umaban'] - 1) / max(max_uma - 1, 1) for h in horses}

    if layout.get('straight_course'):
        phases = ['スタート', '直線']
    else:
        phases = phases_for_distance(distance)
    out = {}
    prev_fracs = {}
    for phase in phases:
        _, stretch, _, drift = _PHASE_PARAMS[phase]
        w4 = _PHASE_TO4.get(phase, 0.0)
        fracs = {}
        for h in horses:
            u = h['umaban']
            prof = profiles.get(h.get('name', '')) or {}
            if phase == 'スタート':
                base = (1 - gate_w) * forward[u] + gate_w * gate_fracs[u]
            elif phase == '直線':
                base = finish[u]   # 到達(着順)位置: 決め手・適性・総合力で押し上げ済み
                if wind_eff:       # 風: 有利脚質を前方へ、不利脚質を後方へ
                    base += wind_eff['shift'].get(h.get('style', '不明'), 0.0)
            else:
                base = (1 - w4) * forward[u] + w4 * pos4[u]
            fracs[u] = max(0.0, min(1.0, base))

        # 隊列の縦長/一団をX全長に反映（位置のばらつきが大きい=縦長）
        spread = max(fracs.values()) - min(fracs.values())
        span = (n - 1) * stretch * (0.65 + spread * 0.9)

        # 集団分け: fracが近い馬は同じ縦列（横並びの馬群）として扱う
        sorted_u = sorted(fracs, key=lambda u: (fracs[u], u))
        max_w = 2 if n <= 9 else 3
        gap_eps = max(0.015, spread * 0.9 / max(n - 1, 1))
        cols = []
        for u in sorted_u:
            if cols and len(cols[-1]) < max_w and fracs[u] - fracs[cols[-1][-1]] <= gap_eps:
                cols[-1].append(u)
            else:
                cols.append([u])

        # 列X: 実際のfrac差を馬群の間隔に反映（重なり防止に最低0.95は離す）
        pos_of = {}
        xs = []
        prev_f = 0.0
        for i, col in enumerate(cols):
            f = sum(fracs[u] for u in col) / len(col)
            if i == 0:
                x = span
            else:
                x = xs[-1] - max(0.95, (f - prev_f) / max(spread, 1e-9) * span)
            xs.append(x)
            prev_f = f
            # 列内の内外: 前の局面で前にいた馬ほどラチ沿い（押し上げ中の馬は外）
            for lane, u in enumerate(sorted(col, key=lambda u: (prev_fracs.get(u, fracs[u]), u))):
                pos_of[u] = (i, lane, x)
        # 後方の列が x<0 にはみ出した分は全体を右へ平行移動
        x_shift = -min(0.0, min(xs))

        rows = []
        for h in horses:
            u = h['umaban']
            ci, lane, x = pos_of[u]
            x += x_shift
            if phase == 'スタート':
                # ゲート: 内外は枠なり
                y = 0.35 + (u - 1) / max(max_uma - 1, 1) * 3.4
            else:
                # 前の馬ほどラチ沿い。位置を押し上げ中の馬（前フェーズより前進）は外を回す
                gain = max(0.0, prev_fracs.get(u, fracs[u]) - fracs[u])
                y = (0.35 + lane * 1.05
                     + ci / max(len(cols) - 1, 1) * 0.55
                     + min(gain * drift * 5.5, 2.2)
                     + (0.10 if u % 2 == 0 else 0.0))
            rows.append({
                'umaban': u, 'name': h.get('name', ''), 'style': h.get('style', '不明'),
                'score': round(h['score'], 3), 'x': round(x, 2), 'y': round(y, 2),
                'jv': bool(profiles.get(h.get('name', ''))),
            })
        out[phase] = rows
        prev_fracs = fracs
    return out


# ──────────────────────────────────────────────
# Phase 5: 風（流体動力学）補正
# ──────────────────────────────────────────────

# 競馬場の緯度経度（気象API用・目安）
_VENUE_COORDS = {
    '札幌': (43.06, 141.40), '函館': (41.78, 140.78), '福島': (37.74, 140.46),
    '新潟': (37.94, 139.075), '東京': (35.66, 139.48), '中山': (35.72, 140.00),
    '中京': (35.13, 136.99), '京都': (34.91, 135.71), '阪神': (34.71, 135.36),
    '小倉': (33.86, 130.84),
}

# 各場でホームストレッチ走行中に馬が向く方位（度・0=北, 90=東。目安）
_VENUE_STRAIGHT_BEARING = {
    '札幌': 80, '函館': 250, '福島': 200, '新潟': 110, '東京': 300,
    '中山': 340, '中京': 40, '京都': 70, '阪神': 110, '小倉': 250,
}


def wind_effect(wind):
    """
    風が直線で各脚質に与える影響を返す。風速5m/s未満・横風は影響なし。
    wind: {'speed': m/s, 'mode': 'tail'|'head'|'none'} で手動指定、または
          {'speed': m/s, 'dir_deg': 風の吹いてくる方位(度), 'venue': 場名} で自動判定。
    戻り値: {'favor','shift':{style:frac_shift},'note','kind'} または None。
    """
    if not wind:
        return None
    speed = float(wind.get('speed', 0) or 0)
    kind = wind.get('mode')
    if kind not in ('tail', 'head', 'none'):
        bearing = _VENUE_STRAIGHT_BEARING.get(wind.get('venue'))
        d = wind.get('dir_deg')
        if bearing is None or d is None:
            kind = 'none'
        else:
            diff = abs(((d - bearing + 180) % 360) - 180)
            kind = 'head' if diff <= 60 else 'tail' if diff >= 120 else 'none'
    if speed < 5.0 or kind == 'none':
        return {'favor': None, 'shift': {}, 'kind': 'none',
                'note': f"風 {speed:.0f}m/s: 直線への影響は小さい（5m/s未満 or 横風）"}
    # ※過去1479R(2023-24芝)のバックテストで直線風成分と着順の相関は r=+0.049＝ほぼ無効。
    #   よって位置補正は「見た目のヒント」程度に縮小（情報表示は維持）。データに無い補正は弱める。
    mag = min(0.03, 0.012 + (speed - 5.0) * 0.004)
    if kind == 'tail':
        return {'favor': '差し・追込（※統計的根拠は弱い）', 'kind': 'tail',
                'shift': {'差し': -mag, '追込': -mag * 1.1, '先行': mag * 0.4, '逃げ': mag * 0.5},
                'note': f"直線追い風 {speed:.0f}m/s（理論上は差し有利だが実データでは着順への影響ほぼ無し）"}
    return {'favor': '逃げ・先行（※統計的根拠は弱い）', 'kind': 'head',
            'shift': {'差し': mag, '追込': mag * 1.1, '先行': -mag * 0.5, '逃げ': -mag * 0.4},
            'note': f"直線向かい風 {speed:.0f}m/s（理論上は前有利だが実データでは着順への影響ほぼ無し）"}


def wind_weight_bonus(weight, wind_eff):
    """向かい風時に馬体重500kg超を加点・460kg未満を減点する係数（0中心）。app側でbataijuに適用。"""
    if not wind_eff or wind_eff.get('kind') != 'head' or not weight:
        return 0.0
    try:
        w = int(weight)
    except Exception:
        return 0.0
    if w >= 500:
        return min(0.06, (w - 500) * 0.0008 + 0.02)
    if w < 460:
        return -0.03
    return 0.0


def fetch_wind(venue, lat=None, lon=None):
    """Open-Meteoで現在の風を取得（任意）。ネットワーク不可なら None。手動指定を推奨。"""
    if lat is None or lon is None:
        coords = _VENUE_COORDS.get(venue)
        if not coords:
            return None
        lat, lon = coords
    try:
        import urllib.request
        import json as _json
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
               f"&current=wind_speed_10m,wind_direction_10m&wind_speed_unit=ms")
        with urllib.request.urlopen(url, timeout=6) as r:
            j = _json.loads(r.read().decode('utf-8'))
        cur = j.get('current', {})
        return {'speed': cur.get('wind_speed_10m'),
                'dir_deg': cur.get('wind_direction_10m'), 'venue': venue}
    except Exception:
        return None


def sashikiri_table(pace_map, profiles, lengths_per_rank=1.4):
    """
    差し切り限界ライン（1秒≒6馬身、1馬身≒0.17秒）。

    4角の想定隊列順位から先頭との馬身差を推定し、各馬の平均上がり3F実タイムで
    「先頭馬を物理的に差し切れるか」を判定する。
    戻り値: [{'umaban','name','rank4','gap_len','my_agari','need_agari','margin','reach'}]
    """
    last_corner = '4角' if '4角' in pace_map else ('3角' if '3角' in pace_map else None)
    if not last_corner:
        return []
    rows4 = sorted(pace_map[last_corner], key=lambda r: -r['x'])  # 先頭から
    if len(rows4) < 2:
        return []
    leader = rows4[0]
    leader_agari = (profiles.get(leader['name']) or {}).get('agari_time')
    if leader_agari is None:
        return []
    out = []
    for rank, r in enumerate(rows4):
        if rank == 0:
            continue
        prof = profiles.get(r['name']) or {}
        my_agari = prof.get('agari_time')
        if my_agari is None:
            continue
        my_best = prof.get('agari_best') or my_agari
        gap_len = rank * lengths_per_rank          # 先頭との推定馬身差
        need = leader_agari - gap_len * 0.17       # 差し切りに必要な上がり
        margin_avg = round(need - my_agari, 2)     # 平均上がり基準
        margin_best = round(need - my_best, 2)     # 自己ベスト基準
        # 判定: 平均で届く=◎ / ベストなら届く=△ / ベストでも届かない=✕
        if margin_avg >= 0:
            verdict = 'reach'        # 平常運転で届く
        elif margin_best >= 0:
            verdict = 'best_only'    # 自己ベストを出せば届く
        else:
            verdict = 'no'           # 物理的に届かない
        out.append({
            'umaban': r['umaban'], 'name': r['name'],
            'rank4': rank + 1, 'gap_len': round(gap_len, 1),
            'my_agari': round(my_agari, 2), 'my_best': round(my_best, 2),
            'need_agari': round(need, 2),
            'margin': margin_best, 'verdict': verdict,
            'reach': margin_best >= 0,
        })
    return out


V_BABA_PATTERNS = ['フラット', '内2頭目まで荒れ', '内4頭目まで荒れ']
V_PACE_PATTERNS = ['スロー', 'ミドル', 'ハイ']

# Vエリア判定: (馬場, ペース) → (有利な通り列 0=内 1=中 2=外, 有利な位置行 0=前 1=中 2=後)
_V_COL = {'フラット': 0, '内2頭目まで荒れ': 1, '内4頭目まで荒れ': 2}
_V_ROW = {'スロー': 0, 'ミドル': 1, 'ハイ': 2}


def build_v_matrix(horses, profiles=None, pace='ミドル', baba='フラット'):
    """
    3×3マトリクス（横軸=トラックバイアス 内/中/外、縦軸=隊列位置 前/中/後）に
    出走馬をプロットし、馬場×ペースの組み合わせから導かれる
    Vエリア（最も恵まれるポジション）をハイライトする。

    戻り値: (plotly Figure, Vエリア該当馬リスト [{'umaban','name','style'}])
    """
    import plotly.graph_objects as go

    horses = [h for h in horses if h.get('umaban')]
    if len(horses) < 2:
        return None, []
    profiles = profiles or {}
    max_uma = max(h['umaban'] for h in horses)

    pts = []
    for h in horses:
        prof = profiles.get(h.get('name', ''))
        # 縦: 隊列位置（テンの位置取り 0=前）
        pos = prof['ten'] if prof and prof.get('ten') is not None else h['score']
        # 横: 想定の通り（枠ベース。先行できる馬ほど内に潜り込める）
        gate = (h['umaban'] - 1) / max(max_uma - 1, 1)
        lane = 0.65 * gate + 0.35 * pos
        pts.append({
            'umaban': h['umaban'], 'name': h.get('name', ''),
            'style': h.get('style', '不明'),
            'x': lane * 3.0,            # 0..3（内→外）
            'y': (1.0 - pos) * 3.0,     # 0..3（後→前）
            'jv': bool(prof),
        })

    v_col = _V_COL.get(baba, 0)
    v_row = _V_ROW.get(pace, 1)
    # 行: 前=y[2,3] 中=[1,2] 後=[0,1]
    vy0, vy1 = (2.0, 3.0) if v_row == 0 else (1.0, 2.0) if v_row == 1 else (0.0, 1.0)
    vx0, vx1 = float(v_col), float(v_col) + 1.0

    v_horses = [p for p in pts
                if vx0 <= p['x'] <= vx1 and vy0 <= p['y'] <= vy1]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[p['x'] for p in pts], y=[p['y'] for p in pts],
        mode='markers+text',
        text=[str(p['umaban']) for p in pts],
        textfont=dict(color='white', size=12, family='Arial Black'),
        marker=dict(
            size=30,
            color=[STYLE_COLORS.get(p['style'], '#8d8d8d') for p in pts],
            line=dict(
                color=['#FFD700' if (vx0 <= p['x'] <= vx1 and vy0 <= p['y'] <= vy1)
                       else 'white' for p in pts],
                width=[3 if (vx0 <= p['x'] <= vx1 and vy0 <= p['y'] <= vy1)
                       else 1.2 for p in pts],
            ),
        ),
        hovertext=[f"{p['umaban']}番 {p['name']}<br>脚質: {p['style']}"
                   f"<br>{'📊 JV実データ' if p['jv'] else '⚙️ 推定'}" for p in pts],
        hoverinfo='text',
    ))

    grid_shapes = [
        dict(type='line', x0=x, x1=x, y0=0, y1=3,
             line=dict(color='#666', width=1, dash='dot'))
        for x in (1.0, 2.0)
    ] + [
        dict(type='line', x0=0, x1=3, y0=y, y1=y,
             line=dict(color='#666', width=1, dash='dot'))
        for y in (1.0, 2.0)
    ] + [
        # Vエリアハイライト
        dict(type='rect', x0=vx0, x1=vx1, y0=vy0, y1=vy1,
             line=dict(color='#E63946', width=3),
             fillcolor='rgba(230,57,70,0.13)'),
    ]
    fig.update_layout(
        title=dict(
            text=f"Vエリア・マトリクス ｜ 馬場: {baba} × ペース: {pace}",
            font=dict(size=14)),
        xaxis=dict(range=[-0.15, 3.15], fixedrange=True,
                   tickvals=[0.5, 1.5, 2.5], ticktext=['内', '中', '外'],
                   title='トラックバイアス（通り）', showgrid=False, zeroline=False),
        yaxis=dict(range=[-0.15, 3.15], fixedrange=True,
                   tickvals=[0.5, 1.5, 2.5], ticktext=['後方', '中団', '前'],
                   title='隊列ポジション', showgrid=False, zeroline=False),
        height=430,
        margin=dict(l=10, r=10, t=45, b=10),
        plot_bgcolor='#20262e',
        paper_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
        shapes=grid_shapes,
        annotations=[
            dict(x=(vx0 + vx1) / 2, y=vy1 - 0.12, text='🏆 Vエリア',
                 showarrow=False, font=dict(color='#E63946', size=13)),
        ],
    )
    return fig, [{'umaban': p['umaban'], 'name': p['name'], 'style': p['style']}
                 for p in sorted(v_horses, key=lambda p: p['umaban'])]


def describe_pace(horses, pace_map=None, profiles=None, layout=None, pace_ctx=None):
    """展開の1行コメントを生成。JVプロファイル/フォワード度でペースを再判定。
    pace_ctx（build_pace_context の戻り値）があればペース判定・ハナ馬を反映。"""
    if not horses:
        return ''
    profiles = profiles or {}
    forward = (pace_ctx or {}).get('forward', {})

    def _eff(h):
        """有効ポジション値: フォワード度→JVテン位置→脚質スコアの順で優先"""
        u = h.get('umaban')
        if u in forward:
            return forward[u]
        prof = profiles.get(h.get('name', ''))
        if prof and prof.get('ten') is not None:
            return prof['ten']
        return h['score']

    nige = [h for h in horses if _eff(h) < 0.18]
    senko = [h for h in horses if 0.18 <= _eff(h) < 0.42]
    oikomi = [h for h in horses if _eff(h) >= 0.72]
    parts = []
    if pace_ctx:
        _leader = pace_ctx.get('leader')
        _lh = next((h for h in horses if h.get('umaban') == _leader), None)
        _pace = pace_ctx.get('pace', 'ミドル')
        _fr = pace_ctx.get('front_ratio', 0.0)
        _lead_txt = f"{_lh['umaban']}番{_lh['name']}" if _lh else "不明"
        parts.append(f"想定ペース【{_pace}】（前向き率{_fr*100:.0f}%）・ハナ予想は{_lead_txt}")
    if len(nige) == 0:
        if senko:
            u = min(senko, key=_eff)
            parts.append(f"明確な逃げ馬不在。{u['umaban']}番{u['name']}がハナを叩く可能性 → スロー濃厚・前残り警戒")
        else:
            parts.append("逃げ・先行馬不在の特殊な隊列。ペースは落ち着きやすい")
    elif len(nige) == 1:
        u = nige[0]
        parts.append(f"{u['umaban']}番{u['name']}の単騎逃げ濃厚 → マイペース駆けの前残り警戒")
    elif len(nige) >= 3:
        nums = "・".join(str(h['umaban']) for h in nige[:4])
        parts.append(f"逃げ候補{len(nige)}頭（{nums}番）でハナ争い激化 → ハイペース・差し有利")
    else:
        nums = "・".join(str(h['umaban']) for h in nige)
        parts.append(f"逃げ候補2頭（{nums}番）。先行争い次第でペース上昇")
    if len(senko) >= 5:
        parts.append(f"先行勢{len(senko)}頭で隊列は密集 → 揉まれ弱い馬は割引")
    if len(oikomi) >= 4:
        parts.append(f"追込勢{len(oikomi)}頭 → 上がり勝負なら外差し台頭")
    # コースレイアウト由来の注記
    if layout:
        parts.extend(layout.get('notes', []))
    return "。".join(parts) + "。"


# ──────────────────────────────────────────────
# コース全体図（インセット）
# ──────────────────────────────────────────────

_TRACK_A = 0.55   # 直線部の半長
_TRACK_B = 0.42   # コーナー半径


def _stadium_points(a=_TRACK_A, b=_TRACK_B, seg=28):
    """スタジアム形（両端半円のオーバル）の周回座標を返す。"""
    pts = []
    # 下の直線: 左→右
    for i in range(seg + 1):
        pts.append((-a + 2 * a * i / seg, -b))
    # 右半円: -90°→+90°
    for i in range(seg + 1):
        phi = -math.pi / 2 + math.pi * i / seg
        pts.append((a + b * math.cos(phi), b * math.sin(phi)))
    # 上の直線: 右→左
    for i in range(seg + 1):
        pts.append((a - 2 * a * i / seg, b))
    # 左半円: 90°→270°
    for i in range(seg + 1):
        phi = math.pi / 2 + math.pi * i / seg
        pts.append((-a + b * math.cos(phi), b * math.sin(phi)))
    return pts


def _phase_anchors(phases, turn, a=_TRACK_A, b=_TRACK_B):
    """
    各フェーズのコース全体図上の位置を返す。
    左回り: ゴール後に右下→1角→右上→2角→向こう正面→3角(左上)→4角(左下)→直線。
    右回りは左右ミラー。
    """
    c = 0.71
    pos = {
        '1角': (a + b * c, -b * c),
        '2角': (a + b * c, b * c),
        '3角': (-a - b * c, b * c),
        '4角': (-a - b * c, -b * c),
        '直線': (-0.12, -b),
        'ゴール': (0.26, -b),
    }
    # スタート位置: 1角があるレースは正面発走、短距離は向こう正面発走
    if '1角' in phases:
        pos['スタート'] = (a * 0.95, -b)
    else:
        pos['スタート'] = (0.0, b)
    if turn == '右':
        pos = {k: (-x, y) for k, (x, y) in pos.items()}
    return pos


def build_figure(pace_map, turn='右', title='想定展開マップ'):
    """
    pace_map（estimate_pace_map の出力）から、フェーズ切替スライダー付き
    Plotly Figure を生成する。右上にコース全体図インセットを表示し、
    現在見ている局面（コーナー）を赤マーカーでハイライトする。
    """
    import plotly.graph_objects as go

    phases = list(pace_map.keys())
    if not phases:
        return None
    n = len(pace_map[phases[0]])
    x_max = max(max(r['x'] for r in rows) for rows in pace_map.values())

    anchors = _phase_anchors(phases, turn)
    track = _stadium_points()

    def _trace(rows):
        return go.Scatter(
            x=[r['x'] for r in rows],
            y=[r['y'] for r in rows],
            mode='markers+text',
            text=[str(r['umaban']) for r in rows],
            textfont=dict(color='white', size=13, family='Arial Black'),
            marker=dict(
                size=34,
                color=[STYLE_COLORS.get(r['style'], '#8d8d8d') for r in rows],
                line=dict(color='white', width=1.5),
            ),
            hovertext=[
                f"{r['umaban']}番 {r['name']}<br>脚質: {r['style']} (score {r['score']})"
                f"<br>{'📊 JV-VAN実データ' if r.get('jv') else '⚙️ 推定（実データなし）'}"
                for r in rows
            ],
            hoverinfo='text',
        )

    def _highlight(phase):
        hx, hy = anchors.get(phase, (0, 0))
        return go.Scatter(
            x=[hx], y=[hy], mode='markers',
            marker=dict(size=17, color='rgba(230,57,70,0.95)',
                        line=dict(color='white', width=2), symbol='circle'),
            hovertext=[f"現在の局面: {phase}"], hoverinfo='text',
            xaxis='x2', yaxis='y2',
        )

    # 静的トレース: コース外形・フェーズラベル・ゴール
    t_track = go.Scatter(
        x=[p[0] for p in track], y=[p[1] for p in track],
        mode='lines', line=dict(color='#4a8f55', width=9),
        hoverinfo='skip', xaxis='x2', yaxis='y2',
    )
    lbl_items = [(ph, anchors[ph]) for ph in phases if ph in anchors]
    t_labels = go.Scatter(
        x=[p[0] for _, p in lbl_items],
        y=[p[1] * 1.0 for _, p in lbl_items],
        mode='markers+text',
        marker=dict(size=5, color='#cfd8cf'),
        text=[ph for ph, _ in lbl_items],
        textposition=['top center' if p[1] >= 0 else 'bottom center' for _, p in lbl_items],
        textfont=dict(size=9, color='#e8e8e8'),
        hoverinfo='skip', xaxis='x2', yaxis='y2',
    )
    gx, gy = anchors['ゴール']
    t_goal = go.Scatter(
        x=[gx], y=[gy], mode='markers+text',
        marker=dict(size=9, color='#111111', symbol='square',
                    line=dict(color='white', width=1)),
        text=['ゴール'], textposition='bottom center',
        textfont=dict(size=9, color='#ffd166'),
        hoverinfo='skip', xaxis='x2', yaxis='y2',
    )

    # data: [0]=馬, [1]=コース, [2]=ラベル, [3]=ゴール, [4]=ハイライト
    fig = go.Figure(
        data=[_trace(pace_map[phases[0]]), t_track, t_labels, t_goal,
              _highlight(phases[0])],
        frames=[
            go.Frame(name=ph, data=[_trace(pace_map[ph]), _highlight(ph)],
                     traces=[0, 4])
            for ph in phases
        ],
    )

    steps = [
        dict(method='animate', label=ph,
             args=[[ph], dict(mode='immediate',
                              frame=dict(duration=900, redraw=False),
                              transition=dict(duration=800, easing='cubic-in-out'))])
        for ph in phases
    ]
    # 向こう正面の進行方向矢印（左回り: 右→左 / 右回り: 左→右）
    _arr_dx = 28 if turn == '左' else -28
    fig.update_layout(
        title=dict(text=f"{title}（{turn}回り）", font=dict(size=15)),
        xaxis=dict(visible=False, range=[-1.2, x_max + 1.6], fixedrange=True,
                   domain=[0.0, 1.0]),
        yaxis=dict(visible=False, range=[-1.1, 5.6], fixedrange=True,
                   domain=[0.0, 0.74]),
        xaxis2=dict(visible=False, range=[-1.35, 1.35], fixedrange=True,
                    domain=[0.56, 1.0], anchor='y2'),
        yaxis2=dict(visible=False, range=[-0.95, 0.80], fixedrange=True,
                    domain=[0.76, 1.0], anchor='x2'),
        height=540,
        margin=dict(l=10, r=10, t=45, b=10),
        plot_bgcolor='#1d3320',
        paper_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
        sliders=[dict(
            active=0, steps=steps, x=0.08, len=0.84, y=-0.02,
            currentvalue=dict(prefix='局面: ', font=dict(size=14)),
            font=dict(size=12),
        )],
        updatemenus=[dict(
            type='buttons', showactive=False, x=0.0, y=-0.02, xanchor='left',
            buttons=[
                dict(
                    label='▶ 再生',
                    method='animate',
                    # redraw=False でscatter座標がトゥイーン補間され、
                    # 馬がゆっくり次のコーナー位置へ滑らかに移動する
                    args=[None, dict(frame=dict(duration=2200, redraw=False),
                                     transition=dict(duration=1800, easing='cubic-in-out'),
                                     fromcurrent=True, mode='immediate')],
                ),
                dict(
                    label='⏸',
                    method='animate',
                    args=[[None], dict(frame=dict(duration=0, redraw=False),
                                       transition=dict(duration=0), mode='immediate')],
                ),
            ],
        )],
        shapes=[
            # メインマップ: 内ラチ（下）と外ラチ（上）
            dict(type='line', xref='x', yref='y',
                 x0=-1.2, x1=x_max + 1.6, y0=-0.45, y1=-0.45,
                 line=dict(color='#cfcfcf', width=3)),
            dict(type='line', xref='x', yref='y',
                 x0=-1.2, x1=x_max + 1.6, y0=5.1, y1=5.1,
                 line=dict(color='#cfcfcf', width=1.5, dash='dash')),
        ],
        annotations=[
            dict(x=x_max + 1.3, y=-0.8, xref='x', yref='y', text='内ラチ',
                 showarrow=False, font=dict(color='#cfcfcf', size=11),
                 xanchor='right'),
            dict(x=x_max + 1.3, y=5.4, xref='x', yref='y', text='外',
                 showarrow=False, font=dict(color='#cfcfcf', size=11),
                 xanchor='right'),
            dict(x=x_max + 0.6, y=2.4, ax=-60, ay=0, xref='x', yref='y',
                 text='進行方向', showarrow=True, arrowhead=2,
                 arrowcolor='#eeeeee', font=dict(color='#eeeeee', size=12)),
            # インセット: 向こう正面の進行方向矢印
            dict(x=0.0, y=_TRACK_B, xref='x2', yref='y2', text='',
                 showarrow=True, arrowhead=2, arrowcolor='#ffd166',
                 ax=_arr_dx, ay=0),
            dict(x=0.0, y=0.72, xref='x2', yref='y2', text='コース全体図',
                 showarrow=False, font=dict(color='#cfd8cf', size=10)),
        ],
    )
    return fig
