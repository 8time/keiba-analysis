# -*- coding: utf-8 -*-
"""穴馬ハンター × 競馬俗説ハンター  重複馬の3着内率バックテスト

対象: 2026年5月（1ヶ月分）
データ: jravan.db + horse_races.csv + folklore_lib.evaluate_race()
"""
import os, sys, json, math, sqlite3
import warnings
warnings.filterwarnings('ignore')

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from scipy import stats as sp_stats

# ── プロジェクトルートを追加 ──
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PROJECT_ROOT)

from core import folklore_lib as fl

# ── 設定 ──
TARGET_YEAR = '2026'
TARGET_MONTH = '05'
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'jravan.db')
CSV_PATH = os.path.join(PROJECT_ROOT, 'data', 'export', 'horse_races.csv')
VH_PARAM_PATH = os.path.join(PROJECT_ROOT, 'data', 'value_hunter_light.json')

# VH閾値読み込み
with open(VH_PARAM_PATH, encoding='utf-8') as f:
    vh_params = json.load(f)
VH_ELITE_THRESHOLD = vh_params['ops']['recall0.5']   # 🎯精鋭
VH_NET_THRESHOLD = vh_params['ops']['recall0.7']      # 🕸️広域網
VH_NINKI_MIN = 6   # 穴馬ハンター対象: 6番人気以下

print(f"=== 穴馬ハンター × 俗説ハンター 重複馬バックテスト ===")
print(f"対象: {TARGET_YEAR}年{TARGET_MONTH}月")
print(f"VH精鋭閾値: {VH_ELITE_THRESHOLD:.4f}")
print(f"VH広域網閾値: {VH_NET_THRESHOLD:.4f}")
print()

# ══════════════════════════════════════════════════════════════
# Step 1: jravan.db からデータ取得
# ══════════════════════════════════════════════════════════════
print("Step 1: データ取得中...")
conn = sqlite3.connect(DB_PATH)

# レース一覧
races_df = pd.read_sql_query(
    f"""SELECT r.race_key, r.race_id, r.race_name, r.grade, r.shubetsu,
               r.kigo, r.juryo, r.kyori, r.surface, r.jyo,
               r.tenko, r.baba_shiba, r.baba_dirt,
               r.shusso_tosu, r.year, r.monthday
        FROM races r
        WHERE r.year = '{TARGET_YEAR}' AND r.monthday LIKE '{TARGET_MONTH}%'
        ORDER BY r.race_key""",
    conn
)
print(f"  対象レース数: {len(races_df)}")

# 全出走馬データ
results_df = pd.read_sql_query(
    f"""SELECT res.race_key, res.race_id, res.umaban, res.waku, res.ketto_num,
               res.bamei, res.sex, res.age, res.futan, res.blinker,
               res.jockey_code, res.jockey_name, res.trainer_code,
               res.bataiju, res.zogen, res.win_odds, res.ninki,
               res.chakujun, res.ato3f, res.corner1, res.corner2,
               res.corner3, res.corner4, res.ijo, res.time
        FROM results res
        WHERE res.year = '{TARGET_YEAR}' AND res.monthday LIKE '{TARGET_MONTH}%'
        ORDER BY res.race_key, res.umaban""",
    conn
)
print(f"  対象出走数: {len(results_df)}")

# 馬の血統情報
horse_ids = results_df['ketto_num'].unique().tolist()
# バッチ取得
horses_df = pd.read_sql_query(
    f"SELECT ketto_num, sire, dam, bms FROM horses WHERE ketto_num IN ({','.join(['?']*len(horse_ids))})",
    conn,
    params=horse_ids,
)
print(f"  血統情報取得: {len(horses_df)} 頭")

# ══════════════════════════════════════════════════════════════
# Step 2: 各馬の過去5走を取得
# ══════════════════════════════════════════════════════════════
print("\nStep 2: 過去走データ取得中...")

def get_past_runs_batch(conn, ketto_nums, target_year, target_month):
    """全対象馬の過去走を一括取得"""
    # 対象月の初日より前のレース結果を取得
    target_date = f"{target_year}{target_month}01"
    
    # 一括で全馬の過去走を取得
    placeholders = ','.join(['?'] * len(ketto_nums))
    query = f"""
        SELECT res.ketto_num, res.race_key, res.race_id, res.umaban, res.chakujun,
               res.ato3f, res.corner1, res.corner2, res.corner3, res.corner4,
               res.win_odds, res.ninki, res.futan, res.bataiju, res.zogen,
               res.jockey_name, res.time,
               r.kyori, r.surface, r.grade, r.race_name, r.shusso_tosu,
               r.year, r.monthday, r.jyo,
               r.baba_shiba, r.baba_dirt
        FROM results res
        JOIN races r ON res.race_key = r.race_key
        WHERE res.ketto_num IN ({placeholders})
          AND (r.year || r.monthday) < ?
        ORDER BY res.ketto_num, r.year DESC, r.monthday DESC
    """
    df = pd.read_sql_query(query, conn, params=ketto_nums + [target_date])
    return df

past_df = get_past_runs_batch(conn, horse_ids, TARGET_YEAR, TARGET_MONTH)
print(f"  過去走レコード: {len(past_df)}")

# 馬ごとに過去走を最大5件のdict listに整理
past_runs_map = {}  # ketto_num -> list of PastRuns dicts
for ketto_num, group in past_df.groupby('ketto_num'):
    runs = []
    for _, row in group.head(5).iterrows():
        # 通過順文字列の構築
        corners = []
        for c in ['corner1', 'corner2', 'corner3', 'corner4']:
            v = row.get(c)
            if v and v > 0:
                corners.append(str(int(v)))
        passing = '-'.join(corners)
        
        # 馬場状態
        surf_str = str(row.get('surface') or '')
        if 'ダ' in surf_str:
            baba_val = str(row.get('baba_dirt') or '')
        else:
            baba_val = str(row.get('baba_shiba') or '')
        
        # 着差（秒）の計算 - 簡略化
        margin = None  # jravan.dbにmarginカラムが直接ない場合
        
        # 日付構築
        date_str = f"{row['year']}.{row['monthday'][:2]}.{row['monthday'][2:]}"
        
        # 上り3F（jravan: 1/10秒単位 → 秒）
        ato3f_val = row.get('ato3f')
        agari = float(ato3f_val) / 10.0 if ato3f_val and ato3f_val > 0 else None
        
        grade_str = str(row.get('grade') or '')
        race_name = str(row.get('race_name') or '')
        # クラス推定
        if not grade_str:
            grade_str = race_name
        
        runs.append({
            'Rank': int(row['chakujun']) if row['chakujun'] and row['chakujun'] > 0 else None,
            'Popularity': int(row['ninki']) if row.get('ninki') and row['ninki'] > 0 else None,
            'Distance': int(row['kyori']) if row.get('kyori') else None,
            'Surface': surf_str,
            'Agari': agari,
            'Passing': passing,
            'Margin': margin,
            'RaceId': str(row.get('race_id') or ''),
            'Grade': grade_str,
            'Date': date_str,
            'PrevJockey': str(row.get('jockey_name') or ''),
            'FieldSize': int(row.get('shusso_tosu') or 0),
            'PrevUmaban': int(row.get('umaban') or 0),
            'Baba': baba_val,
            'Weight': float(row.get('futan') or 0) / 10.0 if row.get('futan') else None,
            'RaceName': race_name,
        })
    past_runs_map[ketto_num] = runs

print(f"  過去走マップ構築: {len(past_runs_map)} 頭")

# ══════════════════════════════════════════════════════════════
# Step 3: horse_races.csv から combo / vh2_score 取得
# ══════════════════════════════════════════════════════════════
print("\nStep 3: combo/vh2_score 取得中...")
hr_df = pd.read_csv(CSV_PATH, usecols=['race_key', 'umaban', 'ninki', 'combo', 'vh2_score', 'chakujun', 'top3', 'win'])

# race_keyの形式を統一 (jravan: 16桁, csv: 16桁)
hr_df['race_key'] = hr_df['race_key'].astype(str)
results_df['race_key'] = results_df['race_key'].astype(str)

# 2026年5月のみ
hr_month = hr_df[hr_df['race_key'].str[:8].str.startswith(TARGET_YEAR + TARGET_MONTH)]
print(f"  horse_races.csv 2026/05: {len(hr_month)} 行")

# race_key + umaban でマージ用キー作成
hr_month = hr_month.copy()
hr_month['merge_key'] = hr_month['race_key'].astype(str) + '_' + hr_month['umaban'].astype(str)

# vh2_score と combo をマッピング
vh_map = {}  # (race_key, umaban) -> {'vh2_score': ..., 'combo': ...}
for _, row in hr_month.iterrows():
    rk = str(row['race_key'])
    um = int(row['umaban'])
    vh_map[(rk, um)] = {
        'vh2_score': row.get('vh2_score'),
        'combo': row.get('combo'),
    }
print(f"  VHスコアマップ: {len(vh_map)} 件")

conn.close()

# ══════════════════════════════════════════════════════════════
# Step 4: 各レースについてランキング生成
# ══════════════════════════════════════════════════════════════
print("\nStep 4: 各レースのランキング生成中...")

# 血統辞書
sire_map = dict(zip(horses_df['ketto_num'], horses_df['sire']))
bms_map = dict(zip(horses_df['ketto_num'], horses_df['bms']))

# 性別コード→文字列
sex_map = {'1': '牡', '2': '牝', '3': 'セ'}

def build_race_df(race_row, runners):
    """1レース分の出馬表DataFrameを構築（folklore_lib.build_snaps 用）"""
    rows = []
    for _, r in runners.iterrows():
        ketto = str(r.get('ketto_num') or '')
        sex_str = sex_map.get(str(r.get('sex') or ''), '牡')
        age_val = r.get('age') or 3
        sex_age = f"{sex_str}{age_val}"
        
        # 馬体重文字列
        bw = r.get('bataiju')
        zg = r.get('zogen')
        if bw and bw > 0:
            if zg is not None:
                zg_int = int(zg) if not pd.isna(zg) else 0
                weight_str = f"{int(bw)}({zg_int:+d})"
            else:
                weight_str = str(int(bw))
        else:
            weight_str = ''
        
        # 斤量（jravanでは×10）
        futan_val = r.get('futan')
        futan_str = str(futan_val / 10.0) if futan_val else ''
        
        past = past_runs_map.get(ketto, [])
        
        rows.append({
            'Umaban': int(r['umaban']),
            'Waku': int(r.get('waku') or 0),
            'Name': str(r.get('bamei') or ''),
            'Popularity': int(r['ninki']) if r.get('ninki') and r['ninki'] > 0 else None,
            'Odds': float(r['win_odds']) if r.get('win_odds') else None,
            'SexAge': sex_age,
            'Weight': weight_str,
            'WeightCarried': futan_str,
            'Jockey': str(r.get('jockey_name') or ''),
            'Trainer': '',
            'Tozai': str(r.get('tozai') or ''),
            'Blinker': int(r.get('blinker') or 0),
            'sire': sire_map.get(ketto, ''),
            'broodmareSire': bms_map.get(ketto, ''),
            'CurrentDistance': int(race_row.get('kyori') or 0),
            'CurrentSurface': str(race_row.get('surface') or ''),
            'PastRuns': past,
            'HorseId': ketto,
        })
    
    return pd.DataFrame(rows)


def build_meta(race_row):
    """レースのメタ情報"""
    surface = str(race_row.get('surface') or '')
    is_dirt = 'ダ' in surface
    baba = str(race_row.get('baba_dirt') or '') if is_dirt else str(race_row.get('baba_shiba') or '')
    
    race_name = str(race_row.get('race_name') or '')
    grade = str(race_row.get('grade') or '')
    juryo = str(race_row.get('juryo') or '')
    kigo = str(race_row.get('kigo') or '')
    shubetsu = str(race_row.get('shubetsu') or '')
    
    # クラス判定
    class_str = grade if grade else race_name
    
    # 日付
    year = str(race_row.get('year') or '')
    md = str(race_row.get('monthday') or '')
    date_val = f"{year}{md}" if year and md else ''
    
    # ハンデ戦・牝馬限定戦
    is_handicap = 'ハンデ' in juryo or 'ハンデ' in race_name
    is_fillies = '牝' in kigo or '牝' in race_name
    
    return {
        'condition': baba,
        'RaceName': race_name,
        'class': class_str,
        'date_val': date_val,
        'is_handicap': is_handicap,
        'is_fillies': is_fillies,
    }


def filter_effective_results(results):
    """folklore_hunter.py の _filter_effective_results と同等"""
    eff_results = []
    for r in (results or []):
        hits_eff = [h for h in (r.get('hits') or []) if h.get('verdict') == fl.VERDICT_EFFECTIVE]
        n_pos = sum(1 for h in hits_eff if h.get('sign', fl.SIGN_POS) > 0)
        n_neg = sum(1 for h in hits_eff if h.get('sign', fl.SIGN_POS) < 0)
        score = n_pos - n_neg
        by_cat = {}
        for x in hits_eff:
            cat = x.get('category', 'その他')
            by_cat[cat] = by_cat.get(cat, 0) + 1
        eff_r = dict(r)
        eff_r.update({
            'hits': hits_eff,
            'hits_pos': [h for h in hits_eff if h.get('sign', fl.SIGN_POS) > 0],
            'hits_neg': [h for h in hits_eff if h.get('sign', fl.SIGN_POS) < 0],
            'n_total': len(hits_eff),
            'n_pos': n_pos,
            'n_neg': n_neg,
            'score': score,
            'n_effective': len(hits_eff),
            'n_rejected': 0,
            'n_unverified': 0,
            'by_category': by_cat,
            'balance': f"＋{n_pos} / −{n_neg} → {fl.fmt_signed(score)}",
        })
        eff_results.append(eff_r)
    return eff_results


# ──────────────────────────────────────────────────
# メインループ: 各レースの分析
# ──────────────────────────────────────────────────
all_records = []  # 全出走馬の分析結果

success_count = 0
fail_count = 0

for idx, (_, race) in enumerate(races_df.iterrows()):
    race_key = str(race['race_key'])
    race_id = str(race.get('race_id') or '')
    
    # このレースの出走馬
    runners = results_df[results_df['race_key'] == race_key].copy()
    if runners.empty:
        fail_count += 1
        continue
    
    # 除外・中止馬を除く
    runners = runners[runners['ijo'].isin(['0', 0, None, '']) | runners['ijo'].isna()].copy()
    if len(runners) < 2:
        fail_count += 1
        continue
    
    try:
        # 出馬表DataFrame構築
        df_race = build_race_df(race, runners)
        meta = build_meta(race)
        
        # 俗説ハンター: evaluate_race (enrich=Falseでパドック等を省略)
        fl_results = fl.evaluate_race(df_race, race_id=race_id, meta=meta, enrich=False)
        
        if not fl_results:
            fail_count += 1
            continue
        
        # ── 各種ランキング生成 ──
        # 通常ランキング
        pos5 = fl.top_pos(fl_results, 5)     # 🟢 ポジティブ材料 TOP5
        neg5 = fl.top_neg(fl_results, 5)     # 🔴 マイナス材料 TOP5
        sc5 = fl.top_score(fl_results, 5)    # ⭐ 総合 TOP5
        
        # 実戦のみランキング
        eff_results = filter_effective_results(fl_results)
        eff_pos5 = fl.top_pos(eff_results, 5)   # 🟢 ポジティブ TOP5（実戦のみ）
        eff_neg5 = fl.top_neg(eff_results, 5)   # 🔴 マイナス TOP5（実戦のみ）
        eff_sc5 = fl.top_score(eff_results, 5)   # ⭐ 総合 TOP5（実戦のみ）
        
        # ランキングの馬番setを作成
        pos5_uma = {r['umaban'] for r in pos5}
        neg5_uma = {r['umaban'] for r in neg5}
        sc5_uma = {r['umaban'] for r in sc5}
        eff_pos5_uma = {r['umaban'] for r in eff_pos5}
        eff_neg5_uma = {r['umaban'] for r in eff_neg5}
        eff_sc5_uma = {r['umaban'] for r in eff_sc5}
        
        # 全俗説ランキング（通常） = pos5 or neg5 or sc5
        all_folk_uma = pos5_uma | neg5_uma | sc5_uma
        # 実戦俗説ランキング = eff_pos5 or eff_neg5 or eff_sc5
        all_eff_folk_uma = eff_pos5_uma | eff_neg5_uma | eff_sc5_uma
        
        # ── 各馬のレコードを記録 ──
        for _, runner in runners.iterrows():
            um = int(runner['umaban'])
            ketto = str(runner.get('ketto_num') or '')
            ninki = int(runner['ninki']) if runner.get('ninki') and runner['ninki'] > 0 else None
            chakujun = int(runner['chakujun']) if runner.get('chakujun') and runner['chakujun'] > 0 else None
            
            # VHスコア取得
            vh_info = vh_map.get((race_key, um), {})
            vh2_score = vh_info.get('vh2_score')
            combo_val = vh_info.get('combo')
            
            # 穴馬ハンター候補判定
            is_ana_target = ninki is not None and ninki >= VH_NINKI_MIN
            
            # VHスコアベース
            is_vh_elite = is_ana_target and vh2_score is not None and vh2_score >= VH_ELITE_THRESHOLD
            is_vh_net = is_ana_target and vh2_score is not None and vh2_score >= VH_NET_THRESHOLD
            is_vh_candidate = is_vh_elite or is_vh_net  # 精鋭 or 広域網
            
            # comboベース（代替指標）
            is_combo2plus = is_ana_target and combo_val is not None and combo_val >= 2
            
            # 着順判定
            top3 = chakujun is not None and 1 <= chakujun <= 3
            win = chakujun == 1
            place2 = chakujun == 2
            place3 = chakujun == 3
            
            record = {
                'race_key': race_key,
                'race_id': race_id,
                'umaban': um,
                'ketto_num': ketto,
                'name': str(runner.get('bamei') or ''),
                'ninki': ninki,
                'win_odds': runner.get('win_odds'),
                'chakujun': chakujun,
                'top3': top3,
                'win': win,
                'place2': place2,
                'place3': place3,
                # 穴馬ハンター
                'is_ana_target': is_ana_target,
                'vh2_score': vh2_score,
                'combo': combo_val,
                'is_vh_candidate': is_vh_candidate,
                'is_vh_elite': is_vh_elite,
                'is_vh_net': is_vh_net,
                'is_combo2plus': is_combo2plus,
                # 俗説ランキング（通常）
                'in_pos5': um in pos5_uma,
                'in_neg5': um in neg5_uma,
                'in_sc5': um in sc5_uma,
                'in_folk_any': um in all_folk_uma,
                # 俗説ランキング（実戦のみ）
                'in_eff_pos5': um in eff_pos5_uma,
                'in_eff_neg5': um in eff_neg5_uma,
                'in_eff_sc5': um in eff_sc5_uma,
                'in_eff_folk_any': um in all_eff_folk_uma,
            }
            all_records.append(record)
        
        success_count += 1
    except Exception as e:
        fail_count += 1
        if fail_count <= 3:
            print(f"  ⚠ レース {race_key}: {e}")

    if (idx + 1) % 50 == 0:
        print(f"  処理: {idx+1}/{len(races_df)} (成功: {success_count}, 失敗: {fail_count})")

print(f"\n  完了: 成功 {success_count} / 失敗 {fail_count}")

# ══════════════════════════════════════════════════════════════
# Step 5: 集計
# ══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("Step 5: 集計結果")
print("="*70)

df = pd.DataFrame(all_records)

# 着順が有効なレコードのみ
df_valid = df[df['chakujun'].notna() & (df['chakujun'] > 0)].copy()

def calc_stats(subset, label):
    """集計統計を算出"""
    n = len(subset)
    if n == 0:
        return {'label': label, 'n': 0, 'top3_n': 0, 'top3_rate': 0,
                'win_rate': 0, 'p2_rate': 0, 'p3_rate': 0, 'fukusho_rate': 0,
                'ci_low': 0, 'ci_high': 0}
    
    top3_n = subset['top3'].sum()
    win_n = subset['win'].sum()
    p2_n = subset['place2'].sum()
    p3_n = subset['place3'].sum()
    
    top3_rate = top3_n / n
    win_rate = win_n / n
    p2_rate = p2_n / n
    p3_rate = p3_n / n
    
    # ウィルソン信頼区間（95%）
    z = 1.96
    denom = 1 + z**2 / n
    center = (top3_rate + z**2 / (2*n)) / denom
    spread = z * math.sqrt((top3_rate * (1 - top3_rate) + z**2 / (4*n)) / n) / denom
    ci_low = max(0, center - spread)
    ci_high = min(1, center + spread)
    
    return {
        'label': label,
        'n': n,
        'top3_n': int(top3_n),
        'top3_rate': top3_rate,
        'win_rate': win_rate,
        'p2_rate': p2_rate,
        'p3_rate': p3_rate,
        'fukusho_rate': top3_rate,  # 複勝率 ≒ 3着内率
        'ci_low': ci_low,
        'ci_high': ci_high,
    }

# ── パターン別集計 ──

# A: 穴馬ハンター単独（VHスコアベース）
ana_only = df_valid[df_valid['is_vh_candidate'] == True]

# B: 穴馬ハンター ∩ 俗説ランキング（全TOP5のいずれか）
ana_folk = df_valid[(df_valid['is_vh_candidate'] == True) & (df_valid['in_folk_any'] == True)]

# C: 穴馬ハンター ∩ 実戦俗説ランキング
ana_eff_folk = df_valid[(df_valid['is_vh_candidate'] == True) & (df_valid['in_eff_folk_any'] == True)]

# D: 穴馬ハンター ∩ 🟢ポジティブTOP5（実戦のみ）
ana_pos = df_valid[(df_valid['is_vh_candidate'] == True) & (df_valid['in_eff_pos5'] == True)]

# E: 穴馬ハンター ∩ ⭐総合TOP5（実戦のみ）
ana_sc = df_valid[(df_valid['is_vh_candidate'] == True) & (df_valid['in_eff_sc5'] == True)]

# F: 🟢ポジティブTOP5 ∩ ⭐総合TOP5（実戦のみ）
pos_sc = df_valid[(df_valid['in_eff_pos5'] == True) & (df_valid['in_eff_sc5'] == True)]

# G: 穴馬ハンター ∩ 🟢ポジティブ ∩ ⭐総合（3重複）
ana_pos_sc = df_valid[(df_valid['is_vh_candidate'] == True) &
                       (df_valid['in_eff_pos5'] == True) &
                       (df_valid['in_eff_sc5'] == True)]

# 参考: 全出走馬（ベースライン）
all_valid = df_valid

# 参考: 6番人気以下全体
pop6plus = df_valid[df_valid['ninki'] >= VH_NINKI_MIN]

# combo >= 2 も集計
combo2 = df_valid[df_valid['is_combo2plus'] == True]

patterns = [
    calc_stats(all_valid, '全出走馬（ベースライン）'),
    calc_stats(pop6plus, '6番人気以下（全体）'),
    calc_stats(ana_only, '穴馬ハンター候補（精鋭+広域網）'),
    calc_stats(combo2, '穴馬ハンター候補（combo≥2）'),
    calc_stats(ana_folk, '穴馬ハンター ∩ 俗説ランキング'),
    calc_stats(ana_eff_folk, '穴馬ハンター ∩ 実戦俗説ランキング'),
    calc_stats(ana_pos, '穴馬ハンター ∩ 🟢ポジティブTOP5'),
    calc_stats(ana_sc, '穴馬ハンター ∩ ⭐総合TOP5'),
    calc_stats(pos_sc, '🟢ポジティブTOP5 ∩ ⭐総合TOP5'),
    calc_stats(ana_pos_sc, '穴馬 ∩ 🟢ポジティブ ∩ ⭐総合'),
]

# ── 結果表示 ──
print()
header = f"{'パターン':　<30s} {'件数':>5s} {'3着内':>5s} {'3着内率':>8s} {'1着率':>7s} {'2着率':>7s} {'3着率':>7s} {'95%CI':>16s}"
print(header)
print("-" * len(header))

for p in patterns:
    ci_str = f"[{p['ci_low']:.1%}-{p['ci_high']:.1%}]" if p['n'] > 0 else "---"
    print(f"{p['label']:　<30s} {p['n']:>5d} {p['top3_n']:>5d} {p['top3_rate']:>7.1%} {p['win_rate']:>7.1%} {p['p2_rate']:>7.1%} {p['p3_rate']:>7.1%} {ci_str:>16s}")

# ══════════════════════════════════════════════════════════════
# Step 6: 統計的有意差検定
# ══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("Step 6: 統計的有意差検定")
print("="*70)

def fisher_test(subset_a, subset_b, label_a, label_b):
    """フィッシャーの正確検定で3着内率の差を検定"""
    na = len(subset_a)
    nb = len(subset_b)
    if na == 0 or nb == 0:
        return
    
    sa = int(subset_a['top3'].sum())
    sb = int(subset_b['top3'].sum())
    fa = na - sa
    fb = nb - sb
    
    table = [[sa, fa], [sb, fb]]
    try:
        odds_ratio, p_value = sp_stats.fisher_exact(table, alternative='two-sided')
    except Exception:
        p_value = 1.0
        odds_ratio = 0
    
    rate_a = sa / na if na > 0 else 0
    rate_b = sb / nb if nb > 0 else 0
    diff = rate_a - rate_b
    
    sig = "★有意(p<.05)" if p_value < 0.05 else "有意差なし"
    if na < 20 or nb < 20:
        sig += " ※サンプル少"
    
    print(f"\n  比較: {label_a} vs {label_b}")
    print(f"    {label_a}: {sa}/{na} = {rate_a:.1%}")
    print(f"    {label_b}: {sb}/{nb} = {rate_b:.1%}")
    print(f"    差: {diff:+.1%}  p値: {p_value:.4f}  {sig}")

# 比較①: 穴馬ハンター単独 vs 穴馬+俗説重複
fisher_test(ana_folk, ana_only, '穴馬＋俗説重複', '穴馬ハンター単独')

# 比較②: 穴馬+ポジティブ vs 穴馬+総合
fisher_test(ana_pos, ana_sc, '穴馬＋ポジティブ', '穴馬＋総合')

# 比較③: 穴馬+俗説 vs ポジティブ+総合
fisher_test(ana_folk, pos_sc, '穴馬＋俗説重複', 'ポジティブ＋総合')

# 比較④: 穴馬単独 vs 穴馬+ポジティブ+総合
fisher_test(ana_pos_sc, ana_only, '穴馬＋ポジ＋総合', '穴馬ハンター単独')

# 比較⑤: 6番人気以下全体 vs 穴馬ハンター候補
fisher_test(ana_only, pop6plus, '穴馬ハンター候補', '6番人気以下全体')

# ══════════════════════════════════════════════════════════════
# Step 7: 結論
# ══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("Step 7: 結論・考察")
print("="*70)

# ベースラインとの比較
base_rate = pop6plus['top3'].mean() if len(pop6plus) > 0 else 0

print(f"\n  6番人気以下の3着内率（ベースライン）: {base_rate:.1%}")

for p in patterns[2:]:  # 穴馬ハンター以降
    if p['n'] > 0:
        diff = p['top3_rate'] - base_rate
        ratio = p['top3_rate'] / base_rate if base_rate > 0 else 0
        sufficient = "◎十分" if p['n'] >= 30 else "△不十分" if p['n'] >= 10 else "✕極少"
        print(f"  {p['label']}: {p['top3_rate']:.1%} (差: {diff:+.1%}, 倍率: {ratio:.2f}倍) [{sufficient}: n={p['n']}]")

print("\n  === 加点材料としての評価 ===")
for p in patterns[2:]:
    if p['n'] >= 10:
        rate = p['top3_rate']
        if rate >= base_rate * 1.5 and p['n'] >= 30:
            verdict = "✅ 加点候補として有望"
        elif rate >= base_rate * 1.3 and p['n'] >= 20:
            verdict = "🔶 傾向は見えるが要追加検証"
        elif rate >= base_rate * 1.1:
            verdict = "⬜ 微差のため現時点では採用しない"
        else:
            verdict = "❌ 効果なしまたは逆効果"
        print(f"  {p['label']}: {verdict}")
    elif p['n'] > 0:
        print(f"  {p['label']}: ⚠ サンプル不足（n={p['n']}）のため判断保留")

print("\n=== 完了 ===")
