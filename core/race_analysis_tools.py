import re
import pandas as pd
import numpy as np

# ─────────────────────────────────────────────────────────────────
# 1. コーナー通過順位パース（netkeiba独自記号 完全対応）
# ─────────────────────────────────────────────────────────────────
def parse_corner_passing(passing_str: str) -> dict:
    """
    netkeiba独自記号を含むコーナー通過順位1件をパースし、密集度・不利スコアを定量化する。

    記号定義 (netkeiba 仕様):
      ()  → 1馬身未満の密集（進路制限・物理的不利。+2.0 pt）
      *   → 馬群内の先頭（スペースあり・不利なし。-1.0 pt）
      ,   → 1〜2馬身差（やや近接。+0.5 pt）
      -   → 2〜5馬身差（適正間隔。-1.0 pt）
      =   → 5馬身以上差（大きく離れ。-2.0 pt）

    Returns dict:
      positions    : 通過順位の数値リスト
      density_score: 物理的不利込み密集スコア（高いほど窮屈）
      is_dense     : ()密集区間を含むか
      is_leader    : *（先頭）を含むか
      penalty_mult : 密集ペナルティ乗数（1.5 if is_dense else 1.0）
      raw          : 元の文字列
    """
    if not passing_str or (isinstance(passing_str, float) and np.isnan(passing_str)) or str(passing_str).strip() in ('-', ''):
        return {"positions": [], "density_score": 0.0, "is_dense": False, "is_leader": False, "penalty_mult": 1.0, "raw": ''}

    ps = str(passing_str)

    # 数値リスト抽出
    positions = [int(n) for n in re.findall(r'\d+', ps)]

    # 記号別スコア積算
    density_points = 0.0
    density_points += ps.count('(') * 2.0   # 密集ペナルティ
    density_points += ps.count('*') * -1.0  # 先頭余裕
    density_points += ps.count(',') * 0.5   # 近接
    density_points += ps.count('-') * -1.0  # 適正間隔
    density_points += ps.count('=') * -2.0  # 大きく離れ

    is_dense = '(' in ps
    is_leader = '*' in ps
    # 密集内にいた場合は物理的不利としてペナルティ乗数1.5を付与
    penalty_mult = 1.5 if is_dense else 1.0

    return {
        "positions": positions,
        "density_score": round(density_points, 1),
        "is_dense": is_dense,
        "is_leader": is_leader,
        "penalty_mult": penalty_mult,
        "raw": ps,
    }


def analyze_field_density_with_symbols(df: 'pd.DataFrame', positional_map: dict) -> dict:
    """
    フィールド全体の「記号パース込み物理的不利補正密集率」を計算する。

    アルゴリズム:
      - 先行/逃げ想定馬の過去走コーナー通過記号を解析
      - ()密集区間があれば密集ペナルティ乗数 1.5 を適用
      - * があれば先頭スペース乗数 0.7 を適用
      - 補正後密集率 = Σ(physical_disadvantage) / 馬数

    Returns dict:
      raw_density_pct         : 記号なし単純密集率(%)
      corrected_density_pct   : 物理的不利補正後密集率(%)
      dense_penalty_horses    : ()密集ペナルティ適用馬数
      leader_star_horses      : * 先頭判定馬数
    """
    total = len(df)
    if total == 0:
        return {"raw_density_pct": 0.0, "corrected_density_pct": 0.0, "dense_penalty_horses": 0, "leader_star_horses": 0}

    front_labels = {'逃げ', '先行'}
    dense_penalty_count = 0
    leader_star_count = 0
    raw_front_count = 0
    corrected_sum = 0.0

    for _, row in df.iterrows():
        uma = int(row.get('Umaban', 0))
        label = positional_map.get(uma, '不明')
        if label not in front_labels:
            continue

        raw_front_count += 1
        corrected_sum += 1.0  # ベース

        past = row.get('PastRuns', [])
        if not past:
            continue

        # 直近3走のコーナー通過記号を集計
        dense_seen = False
        leader_seen = False
        for run in past[:3]:
            p_info = parse_corner_passing(str(run.get('Passing', '-')))
            if p_info['is_dense']:
                dense_seen = True
            if p_info['is_leader']:
                leader_seen = True

        if dense_seen:
            corrected_sum += 0.5  # 密集補正 +50%
            dense_penalty_count += 1
        if leader_seen:
            corrected_sum -= 0.3  # 先頭スペース補正 -30%
            leader_star_count += 1

    raw_density_pct = round(raw_front_count / max(total, 1) * 100, 1)
    corrected_density_pct = round(corrected_sum / max(total, 1) * 100, 1)

    return {
        "raw_density_pct": raw_density_pct,
        "corrected_density_pct": corrected_density_pct,
        "dense_penalty_horses": dense_penalty_count,
        "leader_star_horses": leader_star_count,
    }


# ─────────────────────────────────────────────────────────────────
# 2. PCI（ペースチェンジ指数）計算クラス
# ─────────────────────────────────────────────────────────────────
class PCICalculator:
    """
    PCI（ペースチェンジ指数）の計算・分類・集計クラス。
    公式: (走破タイム − 上がり3F) ÷ ((距離÷200) − 3) × 3 ÷ 上がり3F × 100 − 50

    PCI 解釈:
      >= 56 : 後傾型（瞬発戦・スロー向き）
      50〜55.9: 持続型（イーブン向き）
      <= 49.9: 前傾型（消耗戦・前残り向き）
    """

    @staticmethod
    def _to_seconds(time_val) -> float:
        """タイム値を秒数(float)に変換。1:23.4 形式も対応。"""
        if time_val is None:
            return 0.0
        s = str(time_val).strip()
        try:
            if ':' in s:
                parts = s.split(':')
                return float(parts[0]) * 60 + float(parts[1])
            return float(s)
        except Exception:
            return 0.0

    @classmethod
    def calculate_pci(cls, time, agari, distance) -> float:
        """単一レースのPCIを計算する。"""
        try:
            t = cls._to_seconds(time)
            a = float(agari)
            d = float(distance)
            if a <= 0 or d <= 600:
                return 50.0
            furlongs_before_600 = (d / 200.0) - 3.0
            if furlongs_before_600 <= 0:
                return 50.0
            # 公式厳密版
            pci = (t - a) / furlongs_before_600 * 3.0 / a * 100.0 - 50.0
            return round(pci, 1)
        except Exception:
            return 50.0

    @staticmethod
    def get_pci_type(pci: float) -> str:
        """PCI値から脚質タイプを返す。"""
        if pci >= 56.0:
            return "後傾型（瞬発戦）"
        elif pci >= 50.0:
            return "持続型"
        else:
            return "前傾型（消耗戦）"

    @classmethod
    def analyze_horse_pci(cls, past_runs: list, n_runs: int = 5) -> dict:
        """過去走リストから平均PCI・タイプを算出する。"""
        pcis = []
        for run in (past_runs or [])[:n_runs]:
            try:
                time = run.get('Time') or run.get('TimeStr')
                agari = run.get('Agari')
                dist = run.get('Distance')
                if time and agari and dist:
                    pci = cls.calculate_pci(time, agari, dist)
                    if 20.0 <= pci <= 100.0:  # 異常値除外
                        pcis.append(pci)
            except Exception:
                continue
        if not pcis:
            return {"avg_pci": 50.0, "pci_type": "不明", "pci_list": [], "pci_std": 0.0}
        avg_pci = round(float(np.mean(pcis)), 1)
        pci_std = round(float(np.std(pcis)), 1) if len(pcis) > 1 else 0.0
        return {
            "avg_pci": avg_pci,
            "pci_type": cls.get_pci_type(avg_pci),
            "pci_list": pcis,
            "pci_std": pci_std,
        }


# ─────────────────────────────────────────────────────────────────
# 3. DF全馬PCI一括計算
# ─────────────────────────────────────────────────────────────────
def get_pci_summary(df: 'pd.DataFrame') -> 'pd.DataFrame':
    """
    全馬のAvgPCI・PCITypeをDFに付与して返す。
    合わせて「PCILabel」（持続型(52.3)形式）も生成。
    """
    calc = PCICalculator()
    for i, row in df.iterrows():
        past = row.get('PastRuns', []) or []
        stats = calc.analyze_horse_pci(past)
        df.at[i, 'AvgPCI'] = stats['avg_pci']
        df.at[i, 'PCIType'] = stats['pci_type']
        # 画像の「持続型(52.3)」形式のラベルを生成
        short_type = stats['pci_type'].split('（')[0]  # "後傾型" / "持続型" / "前傾型"
        df.at[i, 'PCILabel'] = f"{short_type}({stats['avg_pci']:.1f})"
    return df


def calculate_all_deploy_scores(
    df: 'pd.DataFrame',
    positional_map: dict,
    position_score_map: dict,
    rpci: float = 51.0,
    front_collapse_risk: float = 0.0,
) -> 'pd.DataFrame':
    """
    各馬の「展開適合度スコア（DeployScore）」と「前崩れ影響度（FrontCollapseEffect）」を一括計算する。

    展開適合度スコア算出式（画像v2.02に準拠）:
      展開適合度 = (位置取りスコア × 0.40)
                + (PCIマッチ率 × 0.35)
                + (密集ペナルティ補正 × 0.25)

    位置取りスコア（0〜100）:
      - 前崩れリスクが高い → 差し/追込有利 = 後方ほど高スコア
      - 前崩れリスクが低い → 先行/逃げ有利 = 前方ほど高スコア
    PCIマッチ率（0〜100）:
      - RPCIと各馬のAvgPCIの乖離が少ないほど高スコア
    密集ペナルティ補正（0〜100）:
      - DensityScore > 0（密集被り）→ マイナス補正
      - DensityScore < 0（先頭/余裕） → プラス補正

    前崩れ影響度（FrontCollapseEffect）:
      - 逃げ/先行 + 前崩れリスク高 → '▲高（不利）'
      - 差し/追込 + 前崩れリスク高 → '◎恩恵大'
      - 逃げ/先行 + 前崩れリスク低 → '○恩恵大（先行残り）'
      - 差し/追込 + 前崩れリスク低 → '△不利（脚余り）'
      - ミドル                   → '－（中立）'
    """
    df = df.copy()
    total = len(df)

    for i, row in df.iterrows():
        uma = int(row.get('Umaban', 0))
        pos_score = position_score_map.get(uma, 0.5)   # 0〜1、小=前方
        label = positional_map.get(uma, '不明')
        avg_pci = float(row.get('AvgPCI', 50.0))
        density_score = float(row.get('DensityScore', 0.0))

        # ── 位置取りスコア（0〜100） ──
        # front_collapse_risk >= 3.5 → 後方有利（pos_score大ほど高評価）
        # front_collapse_risk <= 2.0 → 前方有利（pos_score小ほど高評価）
        if front_collapse_risk >= 3.5:
            # 後方有利：より後ろにいるほど高スコア
            pos_pts = min(100.0, pos_score * 100.0)
        elif front_collapse_risk <= 2.0:
            # 前方有利：より前にいるほど高スコア
            pos_pts = max(0.0, 100.0 - pos_score * 100.0)
        else:
            # 中立：中団（pos_score≒0.5）が最適
            pos_pts = max(0.0, 100.0 - abs(pos_score - 0.5) * 200.0)

        # ── PCIマッチ率（0〜100）＆ 致命的ペース不一致判定 ──
        is_pci_fatal = False
        # 前傾戦（消耗戦）：自分より速いペースにはついていけない（追走バテ）
        if rpci <= 49.5 and avg_pci > rpci + 1.5:
            is_pci_fatal = True
        # 後傾戦（瞬発力戦）：自分より遅いペースではキレ負けする
        elif rpci >= 50.5 and avg_pci < rpci - 1.5:
            is_pci_fatal = True
        # ミドルペース：極端に離れている場合は不適
        elif 49.5 < rpci < 50.5 and abs(avg_pci - rpci) > 3.0:
            is_pci_fatal = True

        if is_pci_fatal:
            pci_match = 0.0  # 致命的ミスマッチは0点
        else:
            pci_diff = abs(avg_pci - rpci)
            pci_match = max(0.0, 100.0 - pci_diff * 5.0)

        # ── 密集ペナルティ補正（0〜100） ──
        # density_score: 負=先頭/余裕(高評価)、正=窮屈(低評価)
        # 0.0(通常の間隔)で80点となるようベースを底上げ
        density_pts = max(0.0, min(100.0, 80.0 - density_score * 15.0))

        # ── 総合展開適合度スコア ──
        deploy_score = round(pos_pts * 0.40 + pci_match * 0.35 + density_pts * 0.25, 1)

        # ★評価（85以上=★、70以上=★なし）
        star = '★' if deploy_score >= 80 else ''
        df.at[i, 'DeployScore'] = deploy_score
        df.at[i, 'DeployScoreLabel'] = f"{deploy_score:.1f}{star}"

        # ── 前崩れ影響度 ──
        is_front = label in ('逃げ', '先行')
        is_back  = label in ('差し', '追込')
        high_risk = front_collapse_risk >= 3.5
        low_risk  = front_collapse_risk <= 2.0

        if high_risk and is_front:
            effect = '▲高（不利）'
        elif high_risk and is_back:
            effect = '◎恩恵大' if deploy_score >= 75 else '○恩恵(小)'
        elif low_risk and is_front:
            effect = '◎恩恵大(前残)' if deploy_score >= 75 else '○恩恵(小)'
        elif low_risk and is_back:
            effect = '△不利（脚余り）'
        else:
            effect = '－（中立）'
            
        # ── [NEW] ペース完全不一致(追走バテ・キレ負け)は「▲不利」として上書き ──
        if is_pci_fatal:
            effect = '▲不利(ペース不適)'
        df.at[i, 'FrontCollapseEffect'] = effect

        # ── DensityPenaltyLabel（-1.2 密集 バッジ用） ──
        if density_score > 0:
            df.at[i, 'DensityPenaltyLabel'] = f"+{density_score:.1f} 密集"
        elif density_score < 0:
            df.at[i, 'DensityPenaltyLabel'] = f"{density_score:.1f} 余裕"
        else:
            df.at[i, 'DensityPenaltyLabel'] = "0.0"

    return df


# ─────────────────────────────────────────────────────────────────
# 4. レース展開適合率（RPCI vs 各馬PCI）
# ─────────────────────────────────────────────────────────────────
def get_deployment_match_rate(
    df: 'pd.DataFrame',
    positional_map: dict,
    pace_label: str = 'ミドル',
) -> dict:
    """
    RPCI（逃げ馬PCI）と各馬の過去平均PCIを比較し、展開適合率を算出する。

    展開適合ロジック:
      - RPCI >= 56（後傾ペース）→ 後傾型 or 持続型の馬が適合
      - RPCI <= 49（前傾ペース）→ 前傾型 or 持続型の馬が適合
      - その他ミドル            → 持続型が最適。後傾/前傾も半適合

    Returns dict:
      rpci            : 逃げ馬の平均PCI（逃げ馬不在時は pace_label から推定）
      rpci_type       : 逃げ馬のPCIタイプ
      match_rate_pct  : フィールド全体との展開適合率(%)
      match_horses    : 適合馬リスト [{umaban, name, pci, match_level}]
    """
    calc = PCICalculator()

    # 逃げ馬のPCI算出
    leader_pcis = []
    for _, row in df.iterrows():
        uma = int(row.get('Umaban', 0))
        if positional_map.get(uma) != '逃げ':
            continue
        past = row.get('PastRuns', []) or []
        stats = calc.analyze_horse_pci(past)
        if stats['pci_list']:
            leader_pcis.extend(stats['pci_list'][:3])  # 直近3走のみ

    if leader_pcis:
        rpci = round(float(np.mean(leader_pcis)), 1)
    else:
        # 逃げ馬不在時はペースラベルから推定
        rpci = {'超ハイ': 43.0, 'ハイ': 47.0, 'ミドル': 51.0, 'スロー': 56.0}.get(pace_label, 51.0)
    rpci_type = PCICalculator.get_pci_type(rpci)

    # 各馬の展開適合判定
    match_horses = []
    matched = 0
    total = len(df)
    for _, row in df.iterrows():
        uma = int(row.get('Umaban', 0))
        name = str(row.get('Name', ''))
        avg_pci = float(row.get('AvgPCI', 50.0))
        pci_type = str(row.get('PCIType', '不明'))

        # 適合判定（競馬のペース非対称性を考慮した厳密判定）
        if rpci <= 49.5:  # 前傾戦（消耗戦）
            if avg_pci > rpci + 1.5:
                level = '△ 不向き'  # 追走で脚をなくす
            elif avg_pci >= rpci - 2.5:
                level = '◎ 適合'
                matched += 1
            else:
                level = '○ やや適合'  # 余裕はあるが掛かるリスクあり
                matched += 0.5
        elif rpci >= 50.5:  # 後傾戦（瞬発力戦）
            if avg_pci < rpci - 1.5:
                level = '△ 不向き'  # 上がり勝負でキレ負けする
            elif avg_pci <= rpci + 2.5:
                level = '◎ 適合'
                matched += 1
            else:
                level = '○ やや適合'
                matched += 0.5
        else:  # ミドル
            pci_diff = abs(avg_pci - rpci)
            if pci_diff <= 1.5:
                level = '◎ 適合'
                matched += 1
            elif pci_diff <= 3.0:
                level = '○ やや適合'
                matched += 0.5
            else:
                level = '△ 不向き'

        match_horses.append({'馬番': uma, '馬名': name, 'AvgPCI': avg_pci, 'PCIタイプ': pci_type, '適合度': level})

    match_rate_pct = round(matched / max(total, 1) * 100, 1)

    return {
        'rpci': rpci,
        'rpci_type': rpci_type,
        'match_rate_pct': match_rate_pct,
        'match_horses': match_horses,
    }


# ─────────────────────────────────────────────────────────────────
# 5. 残り600m位置推測（個別ラップ不要版）
# ─────────────────────────────────────────────────────────────────
def estimate_pos_600m(race_agari_3f: float, horse_agari_3f: float, margin_time: float) -> float:
    """
    残り600m地点での「先頭との秒差」を推測する。
    式: レース上がり3F − 対象馬上がり3F + 勝ち馬との着差タイム

    正値 = 後方にいた（追い込み）
    負値 = 前方にいた（先行）
    0付近 = 先頭付近
    """
    try:
        diff = float(race_agari_3f) - float(horse_agari_3f) + float(margin_time)
        return round(diff, 2)
    except Exception:
        return 0.0


def estimate_pos_600m_for_past_run(run: dict) -> float:
    """
    過去走1件から残り600m位置（秒差）を推測する。
    run には以下が必要:
      - Agari     : 対象馬の上がり3F (秒)
      - RaceAgari : そのレースの上りベスト（秒、なければAgariで代用)
      - Margin    : 着差(秒)  ※ 勝ち馬なら 0.0
    """
    try:
        horse_agari = float(run.get('Agari', 0))
        race_agari  = float(run.get('RaceAgari') or run.get('Agari', 0))
        margin      = float(run.get('Margin', 0))
        if horse_agari <= 0:
            return 0.0
        return estimate_pos_600m(race_agari, horse_agari, margin)
    except Exception:
        return 0.0


def add_pos600m_column(df: 'pd.DataFrame') -> 'pd.DataFrame':
    """
    DFに「Pos600m」列（最終走の残り600m位置推測）を追加して返す。
    正値が大きいほど後方から追い込んでいた馬。
    """
    vals = []
    for _, row in df.iterrows():
        past = row.get('PastRuns', []) or []
        if not past:
            vals.append(None)
            continue
        pos = estimate_pos_600m_for_past_run(past[0])
        vals.append(pos)
    df = df.copy()
    df['Pos600m'] = vals
    return df


# ─────────────────────────────────────────────────────────────────
# 6. ユーティリティ（残存互換）
# ─────────────────────────────────────────────────────────────────
def extract_anom_rushers(df: 'pd.DataFrame', threshold_sec: float = 1.0) -> list:
    """
    過去走で「残り600mで先頭から1秒以上後方から追い込んだ馬」を抽出する。
    次走注目馬の自動ピックアップに利用。
    """
    notable = []
    for _, row in df.iterrows():
        past = row.get('PastRuns', []) or []
        for run in past[:1]:  # 最終走のみチェック
            pos = estimate_pos_600m_for_past_run(run)
            if pos >= threshold_sec:
                notable.append({
                    '馬番': int(row.get('Umaban', 0)),
                    '馬名': str(row.get('Name', '')),
                    '残り600m秒差': pos,
                    '備考': '展開逆らい次走注目',
                })
    return notable


def classify_running_style(pitch: float, stride: float) -> str:
    """完歩ピッチ・ストライド長から走法タイプを分類する（将来拡張用）。"""
    if pitch > 2.3 and stride < 7.2:
        return "ピッチ走法（小回り・急加速得意）"
    if stride > 7.5:
        return "ストライド走法（広コース・後半持続得意）"
    return "バランス型"


def calculate_distance_corrected_time(time: float, distance: float, corner_loss: float = 0.0) -> float:
    """距離補正走破タイム（コーナーロス差し引き）。"""
    corrected = float(time) - float(corner_loss)
    return round(corrected, 2)
