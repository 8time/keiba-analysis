# -*- coding: utf-8 -*-
"""
騎手分析Pro — バックエンドエンジン
==================================
netkeibaから騎手×コース / 騎手×厩舎 / 騎手×馬の相性データを取得し、
ベイズ推定で補正した期待値・回収率を算出するモジュール。

N指数は使用しない。代わりに回収率・連対率をダイレクトな評価軸とする。

データソース:
  - db.netkeiba.com/jockey/{jockey_id}/  （騎手プロフィール・基本成績）
  - db.netkeiba.com/jockey/result/recent/{jockey_id}/  （直近成績）
  - netkeiba出馬表 → 騎手名・厩舎名・コース情報を抽出

判定ロジック（フラグ）:
  🔴 鉄板フラグ: 連対率≥40% かつ 騎乗回数≥30
  🟡 妙味フラグ: 単勝回収率≥120% かつ 騎乗回数≥15
  🔵 危険フラグ: 人気1-3位 かつ コース連対率<15%
"""

import os
import sys
import re
import json
import logging
import time
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import numpy as np
from core.scraper import VENUE_NAMES as VENUE_CODES


logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 定数
# ──────────────────────────────────────────────

# ベイズ推定の事前分布パラメータ（JRA全体の平均的な数値）
PRIOR_WIN_RATE = 0.08        # 全騎手平均勝率 約8%
PRIOR_TOP2_RATE = 0.16       # 全騎手平均連対率 約16%
PRIOR_TOP3_RATE = 0.24       # 全騎手平均複勝率 約24%
PRIOR_WIN_RETURN = 80.0      # 全騎手平均単勝回収率 約80%
PRIOR_PLACE_RETURN = 80.0    # 全騎手平均複勝回収率 約80%
PRIOR_SAMPLE_SIZE = 20       # 事前分布のサンプルサイズ（重み）

# フラグ判定閾値
FLAG_TEPPAN_TOP2_RATE = 0.40     # 🔴 鉄板: 連対率 40%以上
FLAG_TEPPAN_MIN_RIDES = 30       # 🔴 鉄板: 最低騎乗回数
FLAG_MYOMI_WIN_RETURN = 120.0    # 🟡 妙味: 単勝回収率 120%以上
FLAG_MYOMI_MIN_RIDES = 15        # 🟡 妙味: 最低騎乗回数
FLAG_KIKEN_TOP2_RATE = 0.15      # 🔵 危険: 連対率 15%未満
FLAG_KIKEN_MAX_POPULARITY = 3    # 🔵 危険: 人気 1-3位

# netkeiba 騎手ID → 名前のキャッシュ（セッション中のみ）
_JOCKEY_CACHE: Dict[str, dict] = {}

# PW指数キャッシュ（セッション中に1回だけ取得）
_PW_INDEX_CACHE: Dict[str, float] = {}  # {騎手名（正規化済み）: PW指数}
_PW_INDEX_FETCHED: bool = False

# db-keiba ボーナスキャッシュ（騎手IDごと）
_DBKEIBA_BONUS_CACHE: Dict[str, dict] = {}  # {jockey_id: bonus_dict}

# ──────────────────────────────────────────────
# 主要騎手 傾向マッピングDB（db-keiba 2021-2025 傾向まとめ準拠）
# 出典: https://db-keiba.com/jockey-XXX/
# ──────────────────────────────────────────────
JOCKEY_TENDENCY_DB: Dict[str, dict] = {
    "00666": {  # 武豊
        "name": "武豊",
        "add_100": ["7人気", "札幌ダートコース", "芝コース逃げ"],
        "add_90":  ["芝5枠", "ダート3枠", "ハーツクライ"],
        "sub_60":  ["4人気", "芝3枠", "芝4枠", "芝8枠", "ダート2枠",
                    "東京芝コース", "函館ダートコース"],
        "sub_70":  ["3人気", "3勝クラス", "1勝クラス", "ダート5枠",
                    "中京芝コース", "松永幹夫", "松本好雄", "インゼルレーシング",
                    "ディープインパクト"],
    },
    "01167": {  # 川田将雅
        "name": "川田将雅",
        "add_100": ["芝", "東京", "良馬場", "G1", "G2"],
        "add_90":  ["中山", "阪神", "中距離", "オープン"],
        "sub_60":  ["ダート", "重馬場", "不良馬場"],
        "sub_70":  ["障害", "未勝利", "1勝クラス"],
    },
    "05339": {  # C.ルメール
        "name": "C.ルメール",
        "add_100": ["芝", "東京", "中山", "G1", "良馬場", "中距離"],
        "add_90":  ["阪神", "マイル", "オープン", "G2", "G3"],
        "sub_60":  ["ダート", "障害"],
        "sub_70":  ["重馬場", "不良馬場", "未勝利"],
    },
    "01088": {  # M.デムーロ
        "name": "M.デムーロ",
        "add_100": ["芝", "東京", "中山", "G1", "G2", "中距離"],
        "add_90":  ["阪神", "マイル", "良馬場"],
        "sub_60":  ["ダート", "障害"],
        "sub_70":  ["重馬場", "不良馬場", "未勝利", "1勝クラス"],
    },
    "01116": {  # 横山典弘
        "name": "横山典弘",
        "add_100": ["中山", "東京", "芝", "長距離"],
        "add_90":  ["中距離", "良馬場", "オープン"],
        "sub_60":  ["ダート", "短距離"],
        "sub_70":  ["未勝利", "1勝クラス", "重馬場"],
    },
    "01154": {  # 横山武史
        "name": "横山武史",
        "add_100": ["芝", "東京", "中山", "中距離", "G1"],
        "add_90":  ["良馬場", "オープン", "G2", "G3", "マイル"],
        "sub_60":  ["ダート", "障害"],
        "sub_70":  ["重馬場", "不良馬場", "未勝利"],
    },
    "01147": {  # 松山弘平
        "name": "松山弘平",
        "add_100": ["芝", "阪神", "京都", "中距離"],
        "add_90":  ["良馬場", "マイル", "G3", "オープン"],
        "sub_60":  ["ダート", "障害", "重馬場"],
        "sub_70":  ["不良馬場", "未勝利"],
    },
    "01118": {  # 岩田康誠
        "name": "岩田康誠",
        "add_100": ["阪神", "京都", "ダート", "短距離"],
        "add_90":  ["芝", "中距離", "良馬場"],
        "sub_60":  ["東京", "障害"],
        "sub_70":  ["重馬場", "G1", "未勝利"],
    },
    "01161": {  # 岩田望来
        "name": "岩田望来",
        "add_100": ["阪神", "京都", "芝", "中距離"],
        "add_90":  ["ダート", "良馬場", "マイル"],
        "sub_60":  ["障害", "重馬場"],
        "sub_70":  ["不良馬場", "G1"],
    },
    "01078": {  # 戸崎圭太
        "name": "戸崎圭太",
        "add_100": ["東京", "中山", "芝", "中距離", "良馬場"],
        "add_90":  ["マイル", "G2", "G3", "オープン"],
        "sub_60":  ["障害", "ダート重馬場"],
        "sub_70":  ["未勝利", "1勝クラス", "不良馬場"],
    },
    "01077": {  # 浜中俊
        "name": "浜中俊",
        "add_100": ["阪神", "京都", "芝", "中距離"],
        "add_90":  ["良馬場", "マイル"],
        "sub_60":  ["ダート", "重馬場", "障害"],
        "sub_70":  ["東京", "未勝利"],
    },
    "01103": {  # 池添謙一
        "name": "池添謙一",
        "add_100": ["阪神", "京都", "芝", "中距離"],
        "add_90":  ["良馬場", "G3"],
        "sub_60":  ["ダート", "重馬場"],
        "sub_70":  ["未勝利", "1勝クラス"],
    },
    "01126": {  # 三浦皇成
        "name": "三浦皇成",
        "add_100": ["東京", "中山", "芝", "マイル"],
        "add_90":  ["良馬場", "中距離"],
        "sub_60":  ["ダート重馬場", "障害"],
        "sub_70":  ["G1", "未勝利"],
    },
    "01125": {  # 田辺裕信
        "name": "田辺裕信",
        "add_100": ["中山", "東京", "ダート", "短距離"],
        "add_90":  ["芝", "良馬場", "マイル"],
        "sub_60":  ["障害", "G1"],
        "sub_70":  ["重馬場", "不良馬場"],
    },
    "01155": {  # 坂井瑠星
        "name": "坂井瑠星",
        "add_100": ["芝", "東京", "中山", "中距離"],
        "add_90":  ["良馬場", "マイル", "G3"],
        "sub_60":  ["ダート", "障害"],
        "sub_70":  ["重馬場", "未勝利"],
    },
    "01165": {  # 西村淳也
        "name": "西村淳也",
        "add_100": ["芝", "阪神", "京都", "中距離"],
        "add_90":  ["良馬場", "マイル"],
        "sub_60":  ["ダート", "重馬場"],
        "sub_70":  ["未勝利", "障害"],
    },
    "01163": {  # 団野大成
        "name": "団野大成",
        "add_100": ["芝", "阪神", "中距離"],
        "add_90":  ["良馬場", "京都", "マイル"],
        "sub_60":  ["ダート重馬場", "障害"],
        "sub_70":  ["重馬場", "G1"],
    },
    "01164": {  # 菅原明良
        "name": "菅原明良",
        "add_100": ["東京", "中山", "芝", "マイル"],
        "add_90":  ["良馬場", "中距離"],
        "sub_60":  ["ダート", "障害"],
        "sub_70":  ["重馬場", "G1"],
    },
    "01153": {  # 鮫島克駿
        "name": "鮫島克駿",
        "add_100": ["阪神", "京都", "芝"],
        "add_90":  ["良馬場", "中距離", "マイル"],
        "sub_60":  ["ダート", "重馬場"],
        "sub_70":  ["未勝利", "障害"],
    },
    "01162": {  # 永野猛蔵
        "name": "永野猛蔵",
        "add_100": ["阪神", "芝", "中距離"],
        "add_90":  ["良馬場", "京都"],
        "sub_60":  ["ダート重馬場", "障害"],
        "sub_70":  ["重馬場", "G1", "G2"],
    },
}


def get_tendency_suggestion(jockey_id: str) -> List[dict]:
    """
    騎手IDに対応する傾向マッピングから add/sub 条件リストを返す。
    Returns: [{'type': 'add_100', 'condition': '芝', 'memo': '...'}, ...]
    """
    tendency = JOCKEY_TENDENCY_DB.get(jockey_id, {})
    suggestions = []
    for typ in ('add_100', 'add_90', 'sub_70', 'sub_60'):
        for cond in tendency.get(typ, []):
            suggestions.append({
                'type': typ,
                'condition': cond,
                'memo': f"db-keiba 2021-2025傾向 ({tendency.get('name', jockey_id)})",
            })
    return suggestions


def get_tendency_as_bonus_dict(jockey_id: str) -> dict:
    """
    傾向マッピングを fetch_dbkeiba_bonuses と同じ形式の辞書で返す。
    load_bonus_csv と組み合わせてキャッシュに自動登録するために使用。
    """
    tendency = JOCKEY_TENDENCY_DB.get(jockey_id, {})
    if not tendency:
        return {}
    d = {
        'add_100': list(tendency.get('add_100', [])),
        'add_90':  list(tendency.get('add_90', [])),
        'sub_70':  list(tendency.get('sub_70', [])),
        'sub_60':  list(tendency.get('sub_60', [])),
        'bonus_score': 0.0,
        'penalty_score': 0.0,
        'matched_bonus': [],
        'matched_penalty': [],
    }
    d['bonus_score']   = len(d['add_100']) * 15.0 + len(d['add_90']) * 8.0
    d['penalty_score'] = len(d['sub_70']) * (-8.0) + len(d['sub_60']) * (-15.0)
    return d


# VENUE_CODES is imported from core.scraper as alias to VENUE_NAMES


# ──────────────────────────────────────────────
# ベイズ推定ユーティリティ
# ──────────────────────────────────────────────

def bayesian_estimate(observed_rate: float, sample_size: int,
                      prior_rate: float = PRIOR_WIN_RATE,
                      prior_n: int = PRIOR_SAMPLE_SIZE) -> float:
    """
    ベイズ推定による補正値を返す。
    サンプルが少ないほど全体平均（事前分布）に引き寄せられ、
    サンプルが増えるほど実績値を強く反映する。

    式: (prior_rate * prior_n + observed_rate * sample_size) / (prior_n + sample_size)

    Args:
        observed_rate: 観測された勝率/連対率
        sample_size: 観測されたサンプル数（騎乗回数）
        prior_rate: 事前分布の平均（全騎手平均）
        prior_n: 事前分布のサンプルサイズ（重み）

    Returns:
        補正後の推定値
    """
    if sample_size <= 0:
        return prior_rate
    return (prior_rate * prior_n + observed_rate * sample_size) / (prior_n + sample_size)


def bayesian_return_estimate(observed_return: float, sample_size: int,
                             prior_return: float = PRIOR_WIN_RETURN,
                             prior_n: int = PRIOR_SAMPLE_SIZE) -> float:
    """
    回収率向けのベイズ推定。
    サンプルが少ないほど全体平均（80%）に強く引き寄せる。
    上限は騎乗数に応じて動的に設定（少ない=厳しく制限）。
      - 10戦未満: 上限120%
      - 30戦未満: 上限150%
      - 30戦以上: 上限200%（実績として信頼できる範囲）
    """
    estimated = bayesian_estimate(observed_return, sample_size, prior_return, prior_n)
    if sample_size < 10:
        cap = 120.0
    elif sample_size < 30:
        cap = 150.0
    else:
        cap = 200.0
    return min(estimated, cap)


# ──────────────────────────────────────────────
# データ取得（netkeibaスクレイピング）
# ──────────────────────────────────────────────

def _fetch_html_safe(url: str) -> Optional[str]:
    """scraper.py の fetch_robust_html を呼ぶラッパー（import循環回避）"""
    try:
        from core.scraper import fetch_robust_html
        return fetch_robust_html(url)
    except Exception as e:
        logger.error(f"[JockeyAnalyzer] HTML取得失敗: {url} → {e}")
        return None


def _normalize_jockey_name(name: str) -> str:
    """騎手名を正規化（スペース除去・全角→半角）してマッチング精度を上げる"""
    name = name.strip()
    # 全角スペース・半角スペースを除去
    name = re.sub(r'[\s\u3000]+', '', name)
    # 全角英数字→半角
    name = name.translate(str.maketrans(
        'ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ'
        'ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ'
        '０１２３４５６７８９',
        'abcdefghijklmnopqrstuvwxyz'
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        '0123456789'
    ))
    return name


def fetch_race_meta(race_id: str) -> dict:
    """
    netkeiba の出馬表ページからレース基本情報を取得する。

    Returns:
        {
            'surface': '芝' | 'ダート' | '障害',
            'distance': 1600,        # メートル整数
            'condition': '良' | '稍重' | '重' | '不良',
            'weather': '晴' | '曇' | '雨' | '小雨' | '雪',
            'race_class': 'G1' | 'G2' | 'G3' | 'オープン' | '3勝' | '2勝' | '1勝' | '未勝利' | '新馬',
            'venue': '東京',         # 開催場名
            'venue_code': '05',
            'race_number': 11,       # Rナンバー
            'race_name': '日本ダービー',
            'direction': '右' | '左' | '直線',
            'grade': 'G1' | '',
        }
    """
    from bs4 import BeautifulSoup
    from core.scraper import VENUE_NAMES as _VENUE_NAMES

    # race_id からコード抽出
    venue_code = race_id[4:6] if len(race_id) >= 6 else ""
    race_num = int(race_id[10:12]) if len(race_id) >= 12 else 0
    venue_name = _VENUE_NAMES.get(venue_code, "不明")

    meta = {
        'surface': '芝',
        'distance': 1600,
        'condition': '',
        'weather': '',
        'race_class': '',
        'venue': venue_name,
        'venue_code': venue_code,
        'race_number': race_num,
        'race_name': '',
        'direction': '',
        'grade': '',
    }

    urls_to_try = [
        f"https://race.netkeiba.com/race/shutuba_past.html?race_id={race_id}",
        f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}",
        f"https://db.netkeiba.com/race/{race_id}/",
    ]
    html = None
    for url in urls_to_try:
        h = _fetch_html_safe(url)
        if h:
            html = h
            break
    if not html:
        logger.warning(f"[RaceMeta] HTML取得失敗: {race_id}")
        return meta

    soup = BeautifulSoup(html, 'html.parser')

    try:
        # RaceData01: 距離・コース種別・馬場状態・天候
        d01_el = soup.find('div', class_='RaceData01')
        if d01_el:
            t01 = d01_el.get_text(strip=True)
            # 距離・コース種別 例: 芝1600m / ダ1200m / 障3390m
            m_surf = re.search(r'([芝ダ障]).*?(\d{3,4})m', t01)
            if m_surf:
                surf_char = m_surf.group(1)
                meta['surface'] = {'芝': '芝', 'ダ': 'ダート', '障': '障害'}.get(surf_char, '芝')
                meta['distance'] = int(m_surf.group(2))
            # 馬場状態
            m_cond = re.search(r'馬場:(\S+)', t01)
            if m_cond:
                meta['condition'] = m_cond.group(1)
            # 天候
            m_weather = re.search(r'天候:(\S+)', t01)
            if m_weather:
                meta['weather'] = m_weather.group(1)
            # 回り方向
            for direction in ['右', '左', '直線', '右外', '左外']:
                if direction in t01:
                    meta['direction'] = direction
                    break

        # RaceData02: クラス・グレード
        d02_el = soup.find('div', class_='RaceData02')
        if d02_el:
            t02 = d02_el.get_text(strip=True)
            for grade in ['GI', 'GII', 'GIII', 'G1', 'G2', 'G3']:
                if grade in t02:
                    meta['grade'] = grade.replace('GI', 'G1').replace('GII', 'G2').replace('GIII', 'G3')
                    break
            for cls in ['新馬', '未勝利', '1勝クラス', '2勝クラス', '3勝クラス', 'オープン',
                        'G3', 'G2', 'G1', 'GIII', 'GII', 'GI']:
                if cls in t02:
                    meta['race_class'] = cls
                    break

        # レース名
        name_el = (soup.find('div', class_='RaceName') or
                   soup.find('h1', class_='RaceName') or
                   soup.find('span', class_='RaceName'))
        if name_el:
            meta['race_name'] = name_el.get_text(strip=True)

    except Exception as e:
        logger.warning(f"[RaceMeta] パースエラー: {e}")

    logger.info(
        f"[RaceMeta] {race_id}: {meta['surface']} {meta['distance']}m "
        f"馬場={meta['condition']} 場={meta['venue']} クラス={meta['race_class']}"
    )
    return meta


def match_bonus_conditions(bonuses: dict, race_meta: dict, entry: dict) -> dict:
    """
    db-keiba から取得したボーナス/減点条件をレース情報・出走馬情報と照合し、
    発動した条件を bonuses に追記して返す（元の bonuses を直接変更しない）。

    照合対象キーワード（条件文に含まれているか検索）:
        コース種別:  芝 / ダート / 障害
        距離区分:    短距離(~1400) / マイル(1400-1800) / 中距離(1800-2400) / 長距離(2400~)
                     具体的な距離: 1200m, 1600m など
        馬場状態:    良 / 稍重 / 重 / 不良
        天候:        晴 / 曇 / 雨
        開催場:      東京 / 阪神 / 中山 / 京都 など
        クラス:      新馬 / 未勝利 / 1勝 / 2勝 / 3勝 / オープン / G3 / G2 / G1
        枠番:        1枠 / 2枠 … 8枠
        厩舎名:      trainer_name が含まれるか
        馬主名:      owner_name が含まれるか
    """
    surface  = race_meta.get('surface', '')
    distance = race_meta.get('distance', 0)
    condition = race_meta.get('condition', '')
    weather  = race_meta.get('weather', '')
    venue    = race_meta.get('venue', '')
    race_cls = race_meta.get('race_class', '')
    grade    = race_meta.get('grade', '')
    waku     = entry.get('waku', 0)
    trainer  = entry.get('trainer_name', '')
    owner    = entry.get('owner_name', '')

    # 距離カテゴリ
    if distance <= 1400:
        dist_cat = '短距離'
    elif distance <= 1800:
        dist_cat = 'マイル'
    elif distance <= 2400:
        dist_cat = '中距離'
    else:
        dist_cat = '長距離'

    # 照合に使うトークンセット（条件文テキストに含まれるか検索）
    race_tokens = set(filter(None, [
        surface, dist_cat, condition, weather, venue, race_cls, grade,
        f"{distance}m", f"{waku}枠", trainer, owner,
        str(distance),  # 数字のみの記述にも対応
    ]))
    # グレードの別表記も追加
    if grade == 'G1': race_tokens.add('GI')
    if grade == 'G2': race_tokens.add('GII')
    if grade == 'G3': race_tokens.add('GIII')

    def _check_cond_list(cond_list: list) -> list:
        """条件リストの中からレース情報にマッチするものを返す"""
        matched = []
        for cond in cond_list:
            cond_norm = re.sub(r'[\s\u3000]+', '', cond)
            for token in race_tokens:
                if token and token in cond_norm:
                    matched.append(cond)
                    break
        return matched

    result = dict(bonuses)  # shallow copy
    result['matched_bonus']   = (
        _check_cond_list(bonuses.get('add_100', [])) +
        _check_cond_list(bonuses.get('add_90', []))
    )
    result['matched_penalty'] = (
        _check_cond_list(bonuses.get('sub_60', [])) +
        _check_cond_list(bonuses.get('sub_70', []))
    )

    # マッチした条件のみでスコアを再計算
    matched_add100 = _check_cond_list(bonuses.get('add_100', []))
    matched_add90  = _check_cond_list(bonuses.get('add_90', []))
    matched_sub70  = _check_cond_list(bonuses.get('sub_70', []))
    matched_sub60  = _check_cond_list(bonuses.get('sub_60', []))

    result['matched_add_100'] = matched_add100
    result['matched_add_90']  = matched_add90
    result['matched_sub_70']  = matched_sub70
    result['matched_sub_60']  = matched_sub60

    result['matched_bonus_score'] = (
        len(matched_add100) * 15.0 +
        len(matched_add90)  * 8.0
    )
    result['matched_penalty_score'] = (
        len(matched_sub70) * (-8.0) +
        len(matched_sub60) * (-15.0)
    )

    logger.debug(
        f"[BonusMatch] {entry.get('jockey_name','')} "
        f"加算={result['matched_bonus_score']:+.0f} 減点={result['matched_penalty_score']:+.0f} "
        f"tokens={race_tokens}"
    )
    return result


def fetch_pw_index_all() -> Dict[str, float]:
    """
    http://xweb.in.arena.ne.jp/detail/quic/jockey_leading_all.html
    から全騎手のPW指数を取得してキャッシュする。

    Returns:
        {正規化済み騎手名: PW指数(float)}
    """
    global _PW_INDEX_CACHE, _PW_INDEX_FETCHED
    if _PW_INDEX_FETCHED:
        return _PW_INDEX_CACHE

    from bs4 import BeautifulSoup

    url = "http://xweb.in.arena.ne.jp/detail/quic/jockey_leading_all.html"
    html = _fetch_html_safe(url)
    if not html:
        logger.warning("[PW] HTML取得失敗: PW指数は使用できません")
        _PW_INDEX_FETCHED = True
        return _PW_INDEX_CACHE

    soup = BeautifulSoup(html, 'html.parser')
    result: Dict[str, float] = {}

    # テーブルを全探索（クラス名が不明なため）
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if len(rows) < 2:
            continue

        # ヘッダー行からPW指数列のインデックスを特定
        header_cells = rows[0].find_all(['th', 'td'])
        header_texts = [c.get_text(strip=True) for c in header_cells]

        pw_col = None
        name_col = None
        for i, h in enumerate(header_texts):
            h_norm = re.sub(r'\s+', '', h)
            if 'PW' in h_norm or 'ＰＷ' in h_norm:
                pw_col = i
            if '騎手' in h_norm or '名前' in h_norm or 'ジョッキー' in h_norm:
                name_col = i

        # ヘッダーに騎手列が見つからなければ2列目を仮定
        if pw_col is None:
            continue
        if name_col is None:
            name_col = 1  # 一般的に2列目が名前

        logger.debug(f"[PW] テーブル発見: name_col={name_col} pw_col={pw_col} header={header_texts}")

        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) <= max(name_col, pw_col):
                continue
            try:
                name_raw = cells[name_col].get_text(strip=True)
                pw_raw   = cells[pw_col].get_text(strip=True).replace(',', '')
                pw_val   = float(pw_raw)
                name_key = _normalize_jockey_name(name_raw)
                if name_key:
                    result[name_key] = pw_val
            except (ValueError, IndexError):
                continue

        if result:
            logger.info(f"[PW] {len(result)}名のPW指数を取得")
            break

    _PW_INDEX_CACHE = result
    _PW_INDEX_FETCHED = True
    return result


def get_pw_index(jockey_name: str) -> Optional[float]:
    """
    騎手名からPW指数を返す。キャッシュがなければ取得を試みる。
    名前の表記ゆれに対応するため部分一致も試みる。
    """
    pw_map = fetch_pw_index_all()
    if not pw_map:
        return None

    key = _normalize_jockey_name(jockey_name)

    # 完全一致
    if key in pw_map:
        return pw_map[key]

    # 部分一致（短い名前が長い名前の一部になっている場合）
    for k, v in pw_map.items():
        if key in k or k in key:
            logger.debug(f"[PW] 部分一致: '{jockey_name}' → '{k}' = {v}")
            return v

    logger.debug(f"[PW] '{jockey_name}' のPW指数が見つかりません")
    return None


def load_bonus_csv(csv_path: str) -> None:
    """
    ボーナス条件CSVを読み込んで _DBKEIBA_BONUS_CACHE に格納する。
    app.py の起動時 or CSVインポート時に呼ぶ。

    CSVフォーマット（UTF-8、1行1条件）:
        jockey_id, type, condition
        01167, add_100, 芝
        01167, add_90,  阪神
        01167, sub_70,  ダート
        01167, sub_60,  新馬
    typeは add_100 / add_90 / sub_70 / sub_60 のいずれか。
    """
    global _DBKEIBA_BONUS_CACHE
    if not os.path.exists(csv_path):
        logger.info(f"[BonusCSV] ファイルなし: {csv_path}")
        return
    try:
        df = pd.read_csv(csv_path, dtype=str, encoding='utf-8-sig').fillna('')
        # カラム名の空白を除去
        df.columns = [c.strip() for c in df.columns]
        if not {'jockey_id', 'type', 'condition'}.issubset(df.columns):
            logger.warning(f"[BonusCSV] 必要カラムなし: {list(df.columns)}")
            return
        loaded = 0
        for _, row in df.iterrows():
            jid  = str(row['jockey_id']).strip()
            typ  = str(row['type']).strip()
            cond = str(row['condition']).strip()
            if not jid or not typ or not cond:
                continue
            if jid not in _DBKEIBA_BONUS_CACHE:
                _DBKEIBA_BONUS_CACHE[jid] = {
                    'add_100': [], 'add_90': [], 'sub_70': [], 'sub_60': [],
                    'bonus_score': 0.0, 'penalty_score': 0.0,
                    'matched_bonus': [], 'matched_penalty': [],
                }
            if typ in ('add_100', 'add_90', 'sub_70', 'sub_60'):
                if cond not in _DBKEIBA_BONUS_CACHE[jid][typ]:
                    _DBKEIBA_BONUS_CACHE[jid][typ].append(cond)
                    loaded += 1

        # スコア再計算
        for jid, d in _DBKEIBA_BONUS_CACHE.items():
            d['bonus_score'] = len(d['add_100']) * 15.0 + len(d['add_90']) * 8.0
            d['penalty_score'] = len(d['sub_70']) * (-8.0) + len(d['sub_60']) * (-15.0)

        logger.info(f"[BonusCSV] {loaded}件読み込み完了: {csv_path}")
    except Exception as e:
        logger.error(f"[BonusCSV] 読み込みエラー: {e}", exc_info=True)


def fetch_dbkeiba_bonuses(jockey_id: str) -> dict:
    """
    キャッシュからボーナス条件を返す（CSVインポート済みが前提）。
    未登録の騎手IDは空dictを返す。
    """
    empty = {
        'add_100': [], 'add_90': [], 'sub_70': [], 'sub_60': [],
        'bonus_score': 0.0, 'penalty_score': 0.0,
        'matched_bonus': [], 'matched_penalty': [],
    }
    return _DBKEIBA_BONUS_CACHE.get(jockey_id, empty)


def fetch_jockey_profile(jockey_id: str) -> dict:
    """
    db.netkeiba.com から騎手プロフィールと基本成績を取得する。

    Args:
        jockey_id: netkeiba騎手ID (例: "01170" = C.ルメール)

    Returns:
        {
            'jockey_id': str,
            'name': str,
            'name_kana': str,
            'affiliation': str,   # 所属 ("美浦" or "栗東")
            'year_stats': {       # 本年度成績
                'wins': int, 'seconds': int, 'thirds': int, 'unplaced': int,
                'total': int, 'win_rate': float, 'top2_rate': float, 'top3_rate': float,
            },
            'career_stats': {...}  # 通算成績（同構造）
        }
    """
    if jockey_id in _JOCKEY_CACHE:
        return _JOCKEY_CACHE[jockey_id]

    from bs4 import BeautifulSoup

    url = f"https://db.netkeiba.com/jockey/{jockey_id}/"
    html = _fetch_html_safe(url)
    if not html:
        return {"jockey_id": jockey_id, "name": "不明", "error": "取得失敗"}

    soup = BeautifulSoup(html, 'html.parser')

    # 名前取得
    name = "不明"
    name_el = soup.select_one('h1.Name, .db_head_name h1, .Name_En')
    if name_el:
        name = name_el.get_text(strip=True)
    # クリーンアップ（英名と日本名が並んでいる場合）
    name = re.sub(r'\s+', ' ', name).strip()

    # 所属
    affiliation = ""
    for td in soup.select('td, span'):
        txt = td.get_text(strip=True)
        if txt in ["美浦", "栗東"]:
            affiliation = txt
            break

    # 成績テーブル解析
    def _parse_stats_table(table_el) -> dict:
        """成績テーブルの行をパースする"""
        stats = {
            'wins': 0, 'seconds': 0, 'thirds': 0, 'unplaced': 0,
            'total': 0, 'win_rate': 0.0, 'top2_rate': 0.0, 'top3_rate': 0.0,
            'win_return': 0.0, 'place_return': 0.0,
        }
        if not table_el:
            return stats

        rows = table_el.find_all('tr')
        for row in rows:
            cells = row.find_all(['td', 'th'])
            cell_texts = [c.get_text(strip=True) for c in cells]
            # ヘッダー行はスキップ
            if any(t in cell_texts for t in ['1着', '勝率', '年度', '通算']):
                continue
            # 1着, 2着, 3着, 着外, (出走), 勝率, 連対率, 複勝率, 単回, 複回
            if len(cell_texts) >= 8:
                try:
                    nums = []
                    for ct in cell_texts:
                        # カンマ区切り数値・小数点・%除去
                        cleaned = ct.replace(',', '').replace('%', '').strip()
                        m = re.search(r'^(\d+(?:\.\d+)?)$', cleaned)
                        if m:
                            nums.append(m.group(1))

                    if len(nums) >= 4:
                        wins_v = int(float(nums[0]))
                        secs_v = int(float(nums[1]))
                        thr_v  = int(float(nums[2]))
                        unpl_v = int(float(nums[3]))
                        total_v = wins_v + secs_v + thr_v + unpl_v
                        if total_v == 0:
                            continue
                        stats['wins']     = wins_v
                        stats['seconds']  = secs_v
                        stats['thirds']   = thr_v
                        stats['unplaced'] = unpl_v
                        stats['total']    = total_v
                        stats['win_rate']  = wins_v / total_v
                        stats['top2_rate'] = (wins_v + secs_v) / total_v
                        stats['top3_rate'] = (wins_v + secs_v + thr_v) / total_v
                    # 回収率（末尾から2列目・1列目）
                    if len(nums) >= 6:
                        try:
                            wr = float(nums[-2])
                            pr = float(nums[-1])
                            # 回収率は通常50〜200程度。範囲外は0.0にしない
                            stats['win_return']   = wr
                            stats['place_return'] = pr
                        except (ValueError, IndexError):
                            pass
                    # データが取れた最初の行を採用（年度別テーブルの場合は最初の行が当年）
                    if stats['total'] > 0:
                        break
                except (ValueError, IndexError):
                    pass
        return stats

    # テーブル検索: 本年/通算（複数クラスに対応）
    tables = soup.select(
        'table.nk_tb_common, table.race_table_01, table.db_h_race_results'
    )
    logger.debug(f"[JockeyProfile] jockey_id={jockey_id} テーブル数={len(tables)}")
    for _ti, _tbl in enumerate(tables[:3]):
        _rows = _tbl.find_all('tr')
        for _ri, _row in enumerate(_rows[:4]):
            _cells = _row.find_all(['td','th'])
            logger.debug(f"[JockeyProfile]   table{_ti} row{_ri}: {[c.get_text(strip=True)[:15] for c in _cells]}")

    # 全テーブルを対象に成績テーブルを探す（クラス名が異なる場合も含めて）
    all_tables = soup.find_all('table')
    logger.debug(f"[JockeyProfile] 全テーブル数={len(all_tables)}, クラス一覧={[t.get('class',[]) for t in all_tables[:5]]}")

    # 最初のテーブルに年度別成績が入っている場合、最初の行(当年)を本年成績として使う
    year_stats = _parse_stats_table(tables[0]) if len(tables) > 0 else {}
    # テーブルが取れなかった場合は全テーブルから試みる
    if not year_stats.get('total') and all_tables:
        for _t in all_tables:
            _ys_try = _parse_stats_table(_t)
            if _ys_try.get('total', 0) > 0:
                year_stats = _ys_try
                logger.debug(f"[JockeyProfile] 全テーブルサーチで本年成績発見: total={_ys_try['total']}")
                break
    career_stats = _parse_stats_table(tables[1]) if len(tables) > 1 else {}
    logger.debug(f"[JockeyProfile] year_stats={year_stats}, career_stats={career_stats}")

    result = {
        'jockey_id': jockey_id,
        'name': name,
        'affiliation': affiliation,
        'year_stats': year_stats,
        'career_stats': career_stats,
    }

    _JOCKEY_CACHE[jockey_id] = result
    return result


def fetch_jockey_course_stats(jockey_id: str) -> List[dict]:
    """
    騎手の競馬場別成績を取得する。

    取得方法:
    1. db.netkeiba.com/jockey/result/{jid}/?pid=jockey_select&list=track  (競馬場別専用URL)
    2. 直近成績ページ: db.netkeiba.com/jockey/recent/{jid}/ から手動集計
    いずれも静的HTMLから取得可能

    Returns:
        [
            {
                'venue': '東京',
                'rides': 150, 'wins': 25, 'seconds': 20, 'thirds': 18,
                'win_rate': 0.167, 'top2_rate': 0.300, 'top3_rate': 0.420,
                'win_return': 95.0, 'place_return': 88.0,
                # ベイズ補正値
                'adj_win_rate': float, 'adj_top2_rate': float,
                'adj_win_return': float,
            },
            ...
        ]
    """
    from bs4 import BeautifulSoup
    import time as _time

    # --- ① data_racetrack ページを試みる (最も正確な競馬場別統計) ---
    def _try_parse_data_racetrack(jockey_id: str) -> List[dict]:
        url = f"https://db.netkeiba.com/jockey/data_racetrack/{jockey_id}/"
        html = _fetch_html_safe(url)
        if not html:
            return []
        
        soup_l = BeautifulSoup(html, 'html.parser')
        res_list = []
        for table in soup_l.select('table.nk_tb_common, table.DataTable, table#table_freq_data'):
            for tr in table.find_all('tr'):
                cells = tr.find_all(['td', 'th'])
                if len(cells) < 10:
                    continue
                v_name = cells[0].get_text(strip=True)
                if v_name not in VENUE_CODES.values():
                    continue
                
                try:
                    # 1着, 2着, 3着, 4着下, 出走, 勝率, 連対, 複勝, 単回, 複回
                    c_txt = [c.get_text(strip=True).replace(',', '').replace('%', '') for c in cells]
                    wins = int(c_txt[1])
                    seconds = int(c_txt[2])
                    thirds = int(c_txt[3])
                    total = int(c_txt[5])
                    
                    win_rate = float(c_txt[6]) / 100.0 if '.' in c_txt[6] else float(c_txt[6])
                    top2_rate = float(c_txt[7]) / 100.0 if '.' in c_txt[7] else float(c_txt[7])
                    top3_rate = float(c_txt[8]) / 100.0 if '.' in c_txt[8] else float(c_txt[8])
                    # パーセント表記でない場合の補正
                    if win_rate > 1.0: win_rate /= 100.0
                    if top2_rate > 1.0: top2_rate /= 100.0
                    if top3_rate > 1.0: top3_rate /= 100.0

                    win_return = float(c_txt[9])
                    place_return = float(c_txt[10])

                    logger.debug(f"[racetrack] {v_name}: wins={wins} total={total} win_return={win_return} adj={round((80*20+win_return*total)/(20+total),1)}")
                    res_list.append({
                        'venue': v_name,
                        'rides': total,
                        'wins': wins,
                        'seconds': seconds,
                        'thirds': thirds,
                        'win_rate': round(win_rate, 4),
                        'top2_rate': round(top2_rate, 4),
                        'top3_rate': round(top3_rate, 4),
                        'win_return': win_return,
                        'place_return': place_return,
                        'adj_win_rate': round(bayesian_estimate(win_rate, total, PRIOR_WIN_RATE), 4),
                        'adj_top2_rate': round(bayesian_estimate(top2_rate, total, PRIOR_TOP2_RATE), 4),
                        'adj_win_return': round(bayesian_return_estimate(win_return, total), 1),
                    })
                except Exception as e:
                    logger.debug(f"[JockeyAnalyzer] racetrackパースエラー: {e}")
                    continue
        return res_list

    # --- ② 旧方式: pid=jockey_select で競馬場別ページを試みる (互換性維持) ---
    def _try_parse_venue_from_html(html: str) -> List[dict]:
        soup_l = BeautifulSoup(html, 'html.parser')
        results_l = []
        for table in soup_l.select('table'):
            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'th'])
                if len(cells) < 8:
                    continue
                cell_texts = [c.get_text(strip=True) for c in cells]
                venue_name = cell_texts[0]
                if venue_name not in VENUE_CODES.values():
                    continue
                try:
                    nums = []
                    for ct in cell_texts[1:]:
                        m = re.search(r'[\d]+', ct.replace(',', ''))
                        if m:
                            nums.append(m.group())
                    if len(nums) < 4:
                        continue
                    wins = int(nums[0])
                    seconds = int(nums[1])
                    thirds = int(nums[2])
                    unplaced = int(nums[3])
                    total = wins + seconds + thirds + unplaced
                    if total == 0:
                        continue
                    win_rate = wins / total
                    top2_rate = (wins + seconds) / total
                    top3_rate = (wins + seconds + thirds) / total
                    win_return = float(nums[-2]) if len(nums) >= 6 else 0.0
                    place_return = float(nums[-1]) if len(nums) >= 6 else 0.0
                    results_l.append({
                        'venue': venue_name,
                        'rides': total,
                        'wins': wins,
                        'seconds': seconds,
                        'thirds': thirds,
                        'win_rate': round(win_rate, 4),
                        'top2_rate': round(top2_rate, 4),
                        'top3_rate': round(top3_rate, 4),
                        'win_return': win_return,
                        'place_return': place_return,
                        'adj_win_rate': round(bayesian_estimate(win_rate, total, PRIOR_WIN_RATE), 4),
                        'adj_top2_rate': round(bayesian_estimate(top2_rate, total, PRIOR_TOP2_RATE), 4),
                        'adj_win_return': round(bayesian_return_estimate(win_return, total), 1),
                    })
                except (ValueError, IndexError) as e:
                    logger.debug(f"[JockeyAnalyzer] 競馬場行パースエラー: {e}")
                    continue
        return results_l

    # ② 直近成績ページから集計（全期間・競馬場別フィルタの代用として直近数十戦）
    def _aggregate_from_search(jockey_id: str) -> List[dict]:
        """
        db.netkeiba.com の直近成績ページを集計する。
        URL: https://db.netkeiba.com/jockey/result/recent/{jid}/
        """
        from bs4 import BeautifulSoup
        venue_stats: dict = {}  # {venue_name: {'wins':0,'seconds':0,'thirds':0,'total':0,'odds_sum':0,'win_count_for_odds':0}}

        url = f"https://db.netkeiba.com/jockey/result/recent/{jockey_id}/"
        html = _fetch_html_safe(url)
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        rows = soup.select('table.nk_tb_common tr, table.race_table_01 tr')
        
        for tr in rows:
            cells = tr.find_all(['td', 'th'])
            if len(cells) < 8:
                continue
            
            cell_texts = [c.get_text(strip=True) for c in cells]
            
            # 着順 (12番目の列付近になることが多いが、先頭付近の場合もあるので注意)
            # 直近レース一覧の場合は [日付, 開催(ここ!), 天気, R, レース名...] となる
            # 開催文字列（例: '1中山7' などから場所を取り出す）
            venue_name = None
            venue_raw = cell_texts[1]
            for vc, vname in VENUE_CODES.items():
                if vname in venue_raw:
                    venue_name = vname
                    break
            
            if not venue_name:
                continue

            # 着順を探す (列名や数字の並びから)
            pos = -1
            try:
                # 一般的な構造では、人気、着順の順に並ぶ
                # ['...','単勝', '人気', '着順', '馬名', ...]
                pos_str = cell_texts[11]
                m_pos = re.search(r'(\d+)', pos_str)
                if m_pos:
                    pos = int(m_pos.group(1))
            except IndexError:
                continue

            if pos < 1:
                continue

            # 単勝オッズ（1.0〜500倍の小数点1桁の値を探す）
            odds_val = 0.0
            for _oi in [11, 10, 12, 9]:
                try:
                    m_odds = re.match(r'^(\d{1,3}\.\d)$', cell_texts[_oi].strip())
                    if m_odds:
                        o_cand = float(m_odds.group(1))
                        if 1.0 <= o_cand <= 500.0:
                            odds_val = o_cand
                            break
                except IndexError:
                    pass

            if venue_name not in venue_stats:
                venue_stats[venue_name] = {'wins': 0, 'seconds': 0, 'thirds': 0, 'total': 0, 'odds_sum': 0.0, 'win_odds_count': 0}
            
            venue_stats[venue_name]['total'] += 1
            if pos == 1:
                venue_stats[venue_name]['wins'] += 1
                if odds_val > 0:
                    venue_stats[venue_name]['odds_sum'] += odds_val  # 倍率のまま積む
                    venue_stats[venue_name]['win_odds_count'] += 1
            elif pos == 2:
                venue_stats[venue_name]['seconds'] += 1
            elif pos == 3:
                venue_stats[venue_name]['thirds'] += 1

        # 削除: 古いページネーションループの残り

        results_agg = []
        for venue_name, vs in venue_stats.items():
            total = vs['total']
            if total == 0:
                continue
            wins = vs['wins']
            seconds = vs['seconds']
            thirds = vs['thirds']
            win_rate = wins / total
            top2_rate = (wins + seconds) / total
            top3_rate = (wins + seconds + thirds) / total
            # 推定回収率(%): 平均単勝オッズ(倍率) × 勝率 × 100
            # 例: オッズ5.5倍, 勝率15% → 5.5 * 0.15 * 100 = 82.5%
            if vs['win_odds_count'] > 0:
                avg_win_odds = vs['odds_sum'] / vs['win_odds_count']
                win_return = avg_win_odds * win_rate * 100
            else:
                win_return = PRIOR_WIN_RETURN
            results_agg.append({
                'venue': venue_name,
                'rides': total,
                'wins': wins,
                'seconds': seconds,
                'thirds': thirds,
                'win_rate': round(win_rate, 4),
                'top2_rate': round(top2_rate, 4),
                'top3_rate': round(top3_rate, 4),
                'win_return': round(win_return, 1),
                'place_return': 0.0,
                'adj_win_rate': round(bayesian_estimate(win_rate, total, PRIOR_WIN_RATE), 4),
                'adj_top2_rate': round(bayesian_estimate(top2_rate, total, PRIOR_TOP2_RATE), 4),
                'adj_win_return': round(bayesian_return_estimate(win_return, total), 1),
            })
        return results_agg

    # --- ② 旧方式: 直近成績ページから手動集計 (無料・制限なし) ---
    def _aggregate_from_recent_robust(jockey_id: str) -> List[dict]:
        from bs4 import BeautifulSoup
        venue_stats_map: dict = {} # {venue: {wins, seconds, thirds, total, odds_sum, win_count}}
        
        # 直近100戦程度（4ページ分）を取得を試みる
        for page in range(1, 3): # 2ページ分=40走でも十分傾向は出る
            url = f"https://db.netkeiba.com/jockey/result/recent/{jockey_id}/?page={page}"
            html = _fetch_html_safe(url)
            if not html: break
            
            soup = BeautifulSoup(html, 'html.parser')
            rows = soup.select('table.nk_tb_common tr, table.race_table_01 tr')
            if len(rows) <= 1: break
            
            for tr in rows[1:]:
                cells = tr.find_all(['td', 'th'])
                if len(cells) < 15: continue
                c_txt = [c.get_text(strip=True) for c in cells]
                
                # 開催(会場)
                v_raw = c_txt[1]
                v_name = None
                for _, vn in VENUE_CODES.items():
                    if vn in v_raw:
                        v_name = vn
                        break
                if not v_name: continue
                
                # 着順とオッズ取得
                try:
                    # 着順: 複数インデックスを試行（HTMLレイアウト差異対応）
                    pos = None
                    for _pi in [11, 10, 12]:
                        if _pi < len(c_txt):
                            m_p = re.search(r'^(\d{1,2})$', c_txt[_pi].strip())
                            if m_p:
                                pos = int(m_p.group(1))
                                break
                    if pos is None: continue

                    if v_name not in venue_stats_map:
                        venue_stats_map[v_name] = {'wins': 0, 'seconds': 0, 'thirds': 0, 'total': 0, 'odds_sum': 0.0, 'win_odds_count': 0}

                    venue_stats_map[v_name]['total'] += 1
                    if pos == 1:
                        venue_stats_map[v_name]['wins'] += 1
                        # 単勝オッズを取得
                        # netkeibaの直近成績ページは列構成:
                        # [日付,開催,天気,R,レース名,馬名,性齢,斤量,騎手,タイム,着差,単勝,人気,着順,馬体重,...]
                        # → 単勝オッズは概ね11列目(index=11)付近
                        # まず固定位置を試し、ダメなら前後をスキャン
                        odds_found = False
                        for _oi in [11, 10, 12, 9]:
                            if _oi < len(c_txt):
                                # 単勝オッズは 1.0〜999.9 の範囲、小数点1桁
                                m_o = re.match(r'^(\d{1,3}\.\d)$', c_txt[_oi].strip())
                                if m_o:
                                    o_val = float(m_o.group(1))
                                    # オッズとして妥当な範囲（1.0〜500倍）
                                    if 1.0 <= o_val <= 500.0:
                                        venue_stats_map[v_name]['odds_sum'] += o_val
                                        venue_stats_map[v_name]['win_odds_count'] += 1
                                        odds_found = True
                                        logger.debug(f"[RecentRobust] 1着オッズ取得: col={_oi} val={o_val}")
                                        break
                    elif pos == 2: venue_stats_map[v_name]['seconds'] += 1
                    elif pos == 3: venue_stats_map[v_name]['thirds'] += 1
                except:
                    continue
        
        results_agg = []
        for vn, vs in venue_stats_map.items():
            total = vs['total']
            win_rate = vs['wins'] / total
            top2_rate = (vs['wins'] + vs['seconds']) / total
            top3_rate = (vs['wins'] + vs['seconds'] + vs['thirds']) / total
            
            # 単回収率: 勝利時オッズの平均 × 勝率 × 100 で推定
            if vs.get('win_odds_count', 0) > 0:
                avg_odds = vs['odds_sum'] / vs['win_odds_count']
                win_return_est = avg_odds * win_rate * 100
            else:
                win_return_est = PRIOR_WIN_RETURN
            results_agg.append({
                'venue': vn,
                'rides': total,
                'wins': vs.get('wins', 0),
                'seconds': vs.get('seconds', 0),
                'thirds': vs.get('thirds', 0),
                'win_rate': round(win_rate, 4),
                'top2_rate': round(top2_rate, 4),
                'top3_rate': round(top3_rate, 4),
                'win_return': round(win_return_est, 1),
                'place_return': 0.0,
                'adj_win_rate': round(bayesian_estimate(win_rate, total, PRIOR_WIN_RATE), 4),
                'adj_top2_rate': round(bayesian_estimate(top2_rate, total, PRIOR_TOP2_RATE), 4),
                'adj_win_return': round(bayesian_return_estimate(win_return_est, total), 1),
            })
        return results_agg

    # メイン: まずは公式集計を試みる（マスクされている可能性あり）
    official_results = _try_parse_data_racetrack(jockey_id)
    
    # マスク判定: 連対率などが極端に低い or 0 の場所が多い場合はマスクとみなす
    is_masked = False
    if official_results:
        # 有料会員でない場合、数値が ** になっているか 0.0 になっている
        valid_count = sum(1 for r in official_results if r['top2_rate'] > 0)
        if valid_count < 2 and len(official_results) > 5:
            is_masked = True
            
    if not official_results or is_masked:
        logger.info(f"[JockeyAnalyzer] 公式成績がマスクまたは取得不可 → 直近成績から集計: {jockey_id}")
        return _aggregate_from_recent_robust(jockey_id)

    return official_results


def extract_jockey_ids_from_race(race_id: str) -> List[dict]:
    """
    出馬表から出走馬ごとの騎手ID/名前/厩舎名を抽出する。

    取得先の優先順位:
    1. race.netkeiba.com/race/shutuba_past.html  (静的HTML、過去レース)
    2. race.netkeiba.com/race/shutuba.html       (JS依存、当日レース)
    3. db.netkeiba.com/race/{race_id}/           (完了済みレース)

    Returns:
        [
            {
                'umaban': int,
                'horse_name': str,
                'jockey_id': str,
                'jockey_name': str,
                'trainer_name': str,
                'popularity': int,
                'odds': float,
            },
            ...
        ]
    """
    from bs4 import BeautifulSoup
    from core.scraper import _is_nar, fetch_robust_html

    is_nar = _is_nar(race_id)
    domain = "nar.netkeiba.com" if is_nar else "race.netkeiba.com"

    # 取得URL候補（静的HTML優先）
    url_candidates = [
        f"https://{domain}/race/shutuba_past.html?race_id={race_id}",
        f"https://{domain}/race/shutuba.html?race_id={race_id}",
        f"https://db.netkeiba.com/race/{race_id}/",
    ]

    html = None
    for url in url_candidates:
        html = fetch_robust_html(url)
        if html and len(html) > 5000:
            logger.info(f"[JockeyAnalyzer] 出馬表取得: {url}")
            break

    if not html:
        return []

    soup = BeautifulSoup(html, 'html.parser')
    entries = []

    # セレクタを複数試行（ページ種別によってクラスが異なる）
    row_selectors = [
        'tr.HorseList',
        'tr.HorseList_Past',
        'table.race_table_01 tr',
        'table.Shutuba_Table tr',
    ]
    horse_rows = []
    for sel in row_selectors:
        horse_rows = soup.select(sel)
        if horse_rows:
            logger.debug(f"[JockeyAnalyzer] セレクタ '{sel}' → {len(horse_rows)}行")
            break

    for row in horse_rows:
        try:
            # 馬番
            uma_el = row.select_one(
                'td.Umaban, td[class*="Umaban"], td.waku, td:nth-child(2)'
            )
            if not uma_el:
                cells = row.find_all('td')
                if len(cells) < 4:
                    continue
                uma_el = cells[1]  # 2列目を馬番として試行

            uma_text = uma_el.get_text(strip=True)
            m_uma = re.search(r'(\d+)', uma_text)
            if not m_uma:
                continue
            umaban = int(m_uma.group(1))
            if umaban < 1 or umaban > 28:
                continue

            # 馬名
            horse_name = ""
            for sel in ['span.HorseName a', 'td.HorseInfo a', 'td.horse_info a',
                        'a[href*="/horse/"]']:
                horse_el = row.select_one(sel)
                if horse_el:
                    horse_name = horse_el.get_text(strip=True)
                    break

            # 騎手（href=/jockey/ から取得）
            jockey_id = ""
            jockey_name = ""
            for sel in ['td.Jockey a', 'td.jockey a', 'a[href*="/jockey/"]']:
                jockey_el = row.select_one(sel)
                if jockey_el:
                    href = jockey_el.get('href', '')
                    # /jockey/result/ は騎手成績ページなので除外
                    if 'result' in href and not 'result/recent' in href:
                        continue
                    if 'top.html' in href:
                        continue
                    jockey_name = jockey_el.get_text(strip=True)
                    # 修正: recent/00422 などのパターンに対応
                    m_j = re.search(r'/jockey/(?:result/recent/)?(\d{5})/?', href)
                    if m_j:
                        jockey_id = m_j.group(1)
                    break

            # 厩舎
            trainer_name = ""
            trainer_id = ""
            for sel in ['td.Trainer a', 'td.trainer a', 'a[href*="/trainer/"]']:
                trainer_el = row.select_one(sel)
                if trainer_el:
                    trainer_name = trainer_el.get_text(strip=True)
                    m_tr = re.search(r'/trainer/(\w+)/', trainer_el.get('href', ''))
                    if m_tr:
                        trainer_id = m_tr.group(1)
                    break

            # 馬主
            owner_name = ""
            for sel in ['td.Owner a', 'td.owner a', 'a[href*="/owner/"]']:
                owner_el = row.select_one(sel)
                if owner_el:
                    owner_name = owner_el.get_text(strip=True)
                    break

            # 馬ID
            horse_id = ""
            for sel in ['span.HorseName a', 'td.HorseInfo a', 'td.horse_info a', 'a[href*="/horse/"]']:
                horse_el = row.select_one(sel)
                if horse_el:
                    m_h = re.search(r'/horse/(\d{10})/', horse_el.get('href', ''))
                    if m_h:
                        horse_id = m_h.group(1)
                    break

            # 人気・オッズ（あれば）
            popularity = 99
            odds = 0.0
            # 人気: shutuba_past/shutuba/db形式を網羅
            for sel in [
                'td.Popular span', 'td.Popular',
                'span.OddsPeople', 'td.Ninki', 'td.ninki',
                'td[class*="Popular"]', 'td[class*="ninki"]',
            ]:
                pop_el = row.select_one(sel)
                if pop_el:
                    m_p = re.search(r'^(\d{1,2})$', pop_el.get_text(strip=True))
                    if m_p:
                        popularity = int(m_p.group(1))
                        break
                    # span内にネストされている場合
                    inner = pop_el.find('span')
                    if inner:
                        m_p2 = re.search(r'^(\d{1,2})$', inner.get_text(strip=True))
                        if m_p2:
                            popularity = int(m_p2.group(1))
                            break
            for sel in [
                'td.Odds span', 'td.Odds', 'span.Odds',
                'td.odds', 'td[class*="Odds"]',
            ]:
                odds_el = row.select_one(sel)
                if odds_el:
                    txt = odds_el.get_text(strip=True)
                    m_o = re.search(r'(\d+\.\d+)', txt)
                    if m_o:
                        odds = float(m_o.group(1))
                        break

            # 枠
            waku = 0
            waku_el = row.select_one('td:first-child span[class*="waku"]')
            if waku_el:
                m_w = re.search(r'waku(\d+)', waku_el.get('class', [""])[0])
                if m_w: waku = int(m_w.group(1))
            else:
                # クラス指定がない場合
                txt = row.select_one('td:first-child').get_text(strip=True)
                if txt.isdigit():
                    waku = int(txt)

            if not horse_name and not jockey_name:
                continue

            entries.append({
                'umaban': umaban,
                'waku': waku,
                'horse_name': horse_name,
                'horse_id': horse_id,
                'jockey_id': jockey_id,
                'jockey_name': jockey_name,
                'trainer_name': trainer_name,
                'trainer_id': trainer_id,
                'owner_name': owner_name,
                'popularity': popularity,
                'odds': odds,
            })
        except Exception as e:
            logger.debug(f"[JockeyAnalyzer] 出馬表行パースエラー: {e}")
            continue

    # 重複馬番を除去
    seen = set()
    unique_entries = []
    for e in entries:
        if e['umaban'] not in seen:
            seen.add(e['umaban'])
            unique_entries.append(e)

    logger.info(f"[JockeyAnalyzer] 出馬表: {len(unique_entries)}頭抽出 (race_id={race_id})")
    sorted_entries = sorted(unique_entries, key=lambda x: x['umaban'])

    # ── オッズAPI補完: 人気/オッズがHTMLから取れなかった場合、リアルタイムAPIで上書き ──
    try:
        from core.scraper import fetch_realtime_odds_api
        pop_missing = any(e['popularity'] >= 99 for e in sorted_entries)
        odds_missing = any(e['odds'] == 0.0 for e in sorted_entries)
        if pop_missing or odds_missing:
            logger.info(f"[JockeyAnalyzer] 人気/オッズ未取得 → オッズAPIで補完試行 (race_id={race_id})")
            api_data = fetch_realtime_odds_api(race_id)
            if api_data:
                for e in sorted_entries:
                    key = str(e['umaban']).zfill(2)
                    if key in api_data:
                        if e['popularity'] >= 99:
                            e['popularity'] = int(api_data[key].get('Popularity', 99))
                        if e['odds'] == 0.0:
                            e['odds'] = float(api_data[key].get('Odds', 0.0))
                logger.info(f"[JockeyAnalyzer] オッズAPI補完完了: {len(api_data)}頭分")
    except Exception as _e:
        logger.warning(f"[JockeyAnalyzer] オッズAPI補完失敗: {_e}")

    return sorted_entries


# ──────────────────────────────────────────────
# フラグ判定エンジン
# ──────────────────────────────────────────────

def judge_flags(
    top2_rate: float,
    rides: int,
    win_return: float,
    popularity: int = 99,
) -> List[str]:
    """
    騎手×条件のデータに対してフラグを判定する。

    Returns:
        フラグのリスト。例: ["🔴 鉄板"], ["🟡 妙味"], ["🔵 危険"], []
    """
    flags = []

    # 🔴 鉄板フラグ
    if top2_rate >= FLAG_TEPPAN_TOP2_RATE and rides >= FLAG_TEPPAN_MIN_RIDES:
        flags.append("🔴 鉄板")

    # 🟡 妙味フラグ
    if win_return >= FLAG_MYOMI_WIN_RETURN and rides >= FLAG_MYOMI_MIN_RIDES:
        flags.append("🟡 妙味")

    # 🔵 危険フラグ
    if popularity <= FLAG_KIKEN_MAX_POPULARITY and top2_rate < FLAG_KIKEN_TOP2_RATE and rides >= 10:
        flags.append("🔵 危険")

    return flags


def judge_flags_for_entry(entry: dict, course_stats: List[dict], venue: str) -> List[str]:
    """
    出馬表の1エントリに対してフラグ判定を行う。

    Args:
        entry: extract_jockey_ids_from_race() の返り値の1要素
        course_stats: fetch_jockey_course_stats() の返り値
        venue: 競馬場名 (例: "東京")

    Returns:
        フラグのリスト
    """
    # 当該コースの成績を検索
    venue_stat = None
    for cs in course_stats:
        if cs['venue'] == venue:
            venue_stat = cs
            break

    if not venue_stat:
        return []

    return judge_flags(
        top2_rate=venue_stat.get('adj_top2_rate', venue_stat.get('top2_rate', 0)),
        rides=venue_stat.get('rides', 0),
        win_return=venue_stat.get('adj_win_return', venue_stat.get('win_return', 0)),
        popularity=entry.get('popularity', 99),
    )


# ──────────────────────────────────────────────
# 高度指標: PRB / 条件別 / Recent Form
# ──────────────────────────────────────────────

PRIOR_PRB = 0.50


def _calculate_prb(finish: int, runners: int) -> float:
    if runners <= 1:
        return 0.5
    return (runners - finish) / (runners - 1)


def _classify_distance(dist: int) -> str:
    if dist <= 1400:
        return '~1400m'
    elif dist <= 2000:
        return '1600-2000m'
    else:
        return '2000m~'


def _classify_gate(umaban: int) -> str:
    if umaban <= 4:
        return '内枠(1-4)'
    elif umaban <= 8:
        return '中枠(5-8)'
    else:
        return '外枠(9~)'


def _classify_class(race_name: str) -> str:
    for g in ['(G1)', '(G2)', '(G3)', 'G1', 'G2', 'G3', '(GI)', '(GII)', '(GIII)']:
        if g in race_name:
            return '重賞'
    for cls in ['オープン', 'OP', 'リステッド']:
        if cls in race_name:
            return 'OP/L'
    return '条件戦'


def _classify_odds_band(odds: float) -> str:
    if odds <= 3.0:
        return '~3.0倍'
    elif odds <= 10.0:
        return '3.1~10倍'
    elif odds <= 30.0:
        return '10.1~30倍'
    else:
        return '30.1倍~'


def _aggregate_race_group(races: list, key_func) -> dict:
    groups: Dict[str, list] = {}
    for r in races:
        key = key_func(r)
        if key is None:
            continue
        groups.setdefault(key, []).append(r)

    result = {}
    for key, grp in groups.items():
        prbs = [r['prb'] for r in grp if 'prb' in r]
        wins = sum(1 for r in grp if r.get('finish') == 1)
        top3 = sum(1 for r in grp if r.get('finish', 99) <= 3)
        n = len(grp)
        result[key] = {
            'prb': round(float(np.mean(prbs)), 3) if prbs else 0.5,
            'win_rate': round(wins / n, 3) if n else 0,
            'top3_rate': round(top3 / n, 3) if n else 0,
            'sample': n,
        }
    return result


# USM（馬力絞り出しメーター）用 期待値テーブル
# (max_odds, expected_win_rate, expected_top2_rate, expected_top3_rate)
_USM_EXPECTED_RATES = [
    (1.4, 0.675, 0.800, 0.900),
    (1.9, 0.476, 0.650, 0.750),
    (2.9, 0.322, 0.500, 0.620),
    (3.9, 0.245, 0.400, 0.520),
    (4.9, 0.180, 0.320, 0.430),
    (6.9, 0.125, 0.240, 0.340),
    (9.9, 0.085, 0.170, 0.250),
    (14.9, 0.063, 0.120, 0.190),
    (19.9, 0.052, 0.095, 0.150),
    (29.9, 0.035, 0.065, 0.105),
    (49.9, 0.023, 0.040, 0.070),
    (99.9, 0.010, 0.020, 0.035),
    (float('inf'), 0.003, 0.005, 0.010),
]

def calculate_usm(races: List[dict]) -> dict:
    """
    USM（馬力絞り出しメーター）を計算する。
    実際の成績 ÷ 期待成績 × 100 で算出。
    """
    expected_win = 0.0
    expected_top2 = 0.0
    expected_top3 = 0.0
    actual_win = 0
    actual_top2 = 0
    actual_top3 = 0
    
    valid_races = [r for r in races if r.get('odds') is not None and r.get('finish') is not None]
    if not valid_races:
        return {'win_usm': '-', 'top2_usm': '-', 'top3_usm': '-'}
        
    for r in valid_races:
        odds = float(r['odds'])
        finish = int(r['finish'])
        
        # 期待値の取得
        e_win, e_top2, e_top3 = 0.0, 0.0, 0.0
        for max_odds, w, t2, t3 in _USM_EXPECTED_RATES:
            if odds <= max_odds:
                e_win, e_top2, e_top3 = w, t2, t3
                break
                
        expected_win += e_win
        expected_top2 += e_top2
        expected_top3 += e_top3
        
        if finish == 1:
            actual_win += 1
            actual_top2 += 1
            actual_top3 += 1
        elif finish == 2:
            actual_top2 += 1
            actual_top3 += 1
        elif finish == 3:
            actual_top3 += 1
            
    win_usm = int(round((actual_win / expected_win) * 100)) if expected_win > 0 else 100
    top2_usm = int(round((actual_top2 / expected_top2) * 100)) if expected_top2 > 0 else 100
    top3_usm = int(round((actual_top3 / expected_top3) * 100)) if expected_top3 > 0 else 100
    
    return {
        'win_usm': win_usm,
        'top2_usm': top2_usm,
        'top3_usm': top3_usm
    }


def fetch_jockey_advanced_stats(jockey_id: str) -> dict:
    """
    騎手の直近成績ページから高度指標を算出する。

    算出指標:
      PRB (Percentage of Rivals Beaten), 条件別成績, Recent Form (Hot/Cold),
      オッズ帯別複勝率, 斤量帯別, 脚質傾向
    """
    from bs4 import BeautifulSoup
    from datetime import timedelta

    today = datetime.now()
    races: List[dict] = []

    for page_num in range(1, 4):
        url = f"https://db.netkeiba.com/jockey/result/recent/{jockey_id}/?page={page_num}"
        html = _fetch_html_safe(url)
        if not html:
            break

        soup = BeautifulSoup(html, 'html.parser')
        tables = soup.select('table.nk_tb_common, table.race_table_01')
        if not tables:
            break

        rows = tables[0].find_all('tr')
        if len(rows) <= 1:
            break

        header_cells = rows[0].find_all(['td', 'th'])
        h_texts = [c.get_text(strip=True) for c in header_cells]

        col: Dict[str, int] = {}
        for i, ht in enumerate(h_texts):
            ht_n = ht.strip()
            if '日付' in ht_n:
                col['date'] = i
            elif '開催' in ht_n:
                col['venue'] = i
            elif '頭数' in ht_n:
                col['runners'] = i
            elif ht_n in ('枠番', '枠'):
                col.setdefault('waku', i)
            elif ht_n == '馬番':
                col['umaban'] = i
            elif 'オッズ' in ht_n or ht_n == '単勝':
                col['odds'] = i
            elif '人気' in ht_n:
                col['popularity'] = i
            elif '着順' in ht_n or ht_n == '着':
                col['finish'] = i
            elif '距離' in ht_n:
                col['distance'] = i
            elif '馬場' in ht_n:
                col['condition'] = i
            elif '斤量' in ht_n:
                col['weight_carried'] = i
            elif 'レース' in ht_n:
                col.setdefault('race_name', i)
            elif '通過' in ht_n:
                col['passing'] = i

        if 'finish' not in col:
            for fi in range(min(13, len(h_texts) - 1), 7, -1):
                col['finish'] = fi
                break
            else:
                continue

        for tr in rows[1:]:
            cells = tr.find_all(['td', 'th'])
            if len(cells) < 8:
                continue
            c_txt = [c.get_text(strip=True) for c in cells]

            race: Dict[str, Any] = {}

            if 'date' in col and col['date'] < len(c_txt):
                d_str = c_txt[col['date']].replace('/', '-')
                for fmt in ('%Y-%m-%d', '%Y-%m-%d(%a)', '%Y/%m/%d'):
                    try:
                        race['date'] = datetime.strptime(re.sub(r'\(.\)', '', d_str), '%Y-%m-%d')
                        break
                    except ValueError:
                        pass

            if 'venue' in col and col['venue'] < len(c_txt):
                v_raw = c_txt[col['venue']]
                for _, vn in VENUE_CODES.items():
                    if vn in v_raw:
                        race['venue'] = vn
                        break

            if 'runners' in col and col['runners'] < len(c_txt):
                m_r = re.search(r'(\d+)', c_txt[col['runners']])
                if m_r:
                    race['runners'] = int(m_r.group(1))

            if 'finish' in col and col['finish'] < len(c_txt):
                m_f = re.search(r'^(\d{1,2})$', c_txt[col['finish']].strip())
                if m_f:
                    race['finish'] = int(m_f.group(1))
                else:
                    continue
            else:
                continue

            if 'distance' in col and col['distance'] < len(c_txt):
                m_d = re.search(r'([芝ダ障])(\d{3,4})', c_txt[col['distance']])
                if m_d:
                    race['surface'] = {'芝': '芝', 'ダ': 'ダート', '障': '障害'}.get(m_d.group(1), '芝')
                    race['distance'] = int(m_d.group(2))

            if 'condition' in col and col['condition'] < len(c_txt):
                cond_raw = c_txt[col['condition']].strip()
                for c_label in ['良', '稍重', '重', '不良']:
                    if c_label in cond_raw:
                        race['condition'] = c_label
                        break

            if 'umaban' in col and col['umaban'] < len(c_txt):
                m_u = re.search(r'(\d+)', c_txt[col['umaban']])
                if m_u:
                    race['umaban'] = int(m_u.group(1))

            if 'odds' in col and col['odds'] < len(c_txt):
                m_o = re.match(r'^(\d{1,4}\.\d)$', c_txt[col['odds']].strip())
                if m_o:
                    race['odds'] = float(m_o.group(1))

            if 'popularity' in col and col['popularity'] < len(c_txt):
                m_p = re.search(r'^(\d{1,2})$', c_txt[col['popularity']].strip())
                if m_p:
                    race['popularity'] = int(m_p.group(1))

            if 'race_name' in col and col['race_name'] < len(c_txt):
                race['race_name'] = c_txt[col['race_name']]

            if 'weight_carried' in col and col['weight_carried'] < len(c_txt):
                m_wc = re.search(r'(\d+\.?\d*)', c_txt[col['weight_carried']])
                if m_wc:
                    race['weight_carried'] = float(m_wc.group(1))

            if 'passing' in col and col['passing'] < len(c_txt):
                pass_raw = c_txt[col['passing']].strip()
                m_pass = re.findall(r'(\d+)', pass_raw)
                if m_pass:
                    race['passing'] = [int(x) for x in m_pass]

            if 'finish' in race and 'runners' in race:
                race['prb'] = round(_calculate_prb(race['finish'], race['runners']), 3)

            if race.get('finish'):
                races.append(race)

        time.sleep(0.5)

    empty_result: Dict[str, Any] = {
        'prb_overall': 0.5, 'sample_size': 0,
        'recent_form': {}, 'hot_cold': '—',
        'by_distance': {}, 'by_condition': {}, 'by_gate': {},
        'by_class': {}, 'by_odds_band': {}, 'by_weight': {},
        'riding_style': '—',
        'form_score': 0.0,
    }
    if not races:
        return empty_result

    prbs = [r['prb'] for r in races if 'prb' in r]
    prb_overall = float(np.mean(prbs)) if prbs else 0.5

    recent_form: Dict[str, dict] = {}
    for days, label in [(14, '14d'), (30, '30d'), (90, '90d')]:
        cutoff = today - timedelta(days=days)
        recent = [r for r in races if r.get('date') and r['date'] >= cutoff]
        if recent:
            r_prbs = [r['prb'] for r in recent if 'prb' in r]
            r_top3 = sum(1 for r in recent if r.get('finish', 99) <= 3)
            recent_form[label] = {
                'prb': round(float(np.mean(r_prbs)), 3) if r_prbs else 0.5,
                'top3_rate': round(r_top3 / len(recent), 3),
                'sample': len(recent),
            }

    hot_cold = '—'
    if '30d' in recent_form and recent_form['30d']['sample'] >= 3:
        diff = recent_form['30d']['prb'] - prb_overall
        if diff > 0.08:
            hot_cold = 'HOT'
        elif diff < -0.08:
            hot_cold = 'COLD'

    by_distance = _aggregate_race_group(
        [r for r in races if 'distance' in r],
        lambda r: _classify_distance(r['distance']))

    by_condition = _aggregate_race_group(
        [r for r in races if 'condition' in r],
        lambda r: r['condition'])

    by_gate = _aggregate_race_group(
        [r for r in races if 'umaban' in r],
        lambda r: _classify_gate(r['umaban']))

    by_class = _aggregate_race_group(
        [r for r in races if 'race_name' in r],
        lambda r: _classify_class(r['race_name']))

    by_odds_band = _aggregate_race_group(
        [r for r in races if 'odds' in r],
        lambda r: _classify_odds_band(r['odds']))

    by_weight = _aggregate_race_group(
        [r for r in races if 'weight_carried' in r],
        lambda r: '軽量(~53kg)' if r['weight_carried'] <= 53 else
                  '標準(54-56kg)' if r['weight_carried'] <= 56 else '重斤(57kg~)')

    riding_style = '—'
    passing_samples = [r for r in races if 'passing' in r and r['passing']]
    if len(passing_samples) >= 5:
        avg_first_pos = float(np.mean([r['passing'][0] for r in passing_samples]))
        runners_avg = float(np.mean([r.get('runners', 14) for r in passing_samples]))
        ratio = avg_first_pos / runners_avg if runners_avg > 0 else 0.5
        if ratio <= 0.25:
            riding_style = '逃げ・番手'
        elif ratio <= 0.45:
            riding_style = '先行'
        elif ratio <= 0.65:
            riding_style = '中団'
        else:
            riding_style = '差し・追込'

    # === 📈 騎手調子スコア（調子P）の算出 ===
    form_score = 0.0
    valid_form_count = 0
    for r in races:
        if valid_form_count >= 10:
            break
        pop = r.get('popularity')
        fin = r.get('finish')
        if pop is not None and fin is not None:
            try:
                pop_val = int(pop)
                fin_val = int(fin)
                # 基本ポイント: 人気 - 着順
                base_pt = float(pop_val - fin_val)
                # 補正ルール
                if pop_val <= 3 and fin_val >= 4:
                    # 人気馬の裏切りペナルティ: マイナスを1.5倍にする
                    base_pt = base_pt * 1.5
                elif pop_val >= 6 and fin_val <= 3:
                    # 穴馬の激走ボーナス: +5
                    base_pt += 5.0
                elif pop_val >= 10 and fin_val >= 4:
                    # 超大穴の着外切り捨て: 一律 -1.0 とする
                    base_pt = -1.0
                form_score += base_pt
                valid_form_count += 1
            except (ValueError, TypeError):
                continue

    return {
        'prb_overall': round(prb_overall, 3),
        'sample_size': len(races),
        'recent_form': recent_form,
        'hot_cold': hot_cold,
        'by_distance': by_distance,
        'by_condition': by_condition,
        'by_gate': by_gate,
        'by_class': by_class,
        'by_odds_band': by_odds_band,
        'by_weight': by_weight,
        'riding_style': riding_style,
        'usm': calculate_usm(races),
        'form_score': round(form_score, 1),
    }


def get_matched_advanced_stats(adv: dict, race_meta: dict, entry: dict) -> dict:
    """
    高度指標から今レースの条件にマッチするPRB/複勝率を抽出する。
    """
    result = {
        'prb_overall': adv.get('prb_overall', 0.5),
        'hot_cold': adv.get('hot_cold', '—'),
        'riding_style': adv.get('riding_style', '—'),
    }

    dist = race_meta.get('distance', 0)
    if dist > 0:
        dist_key = _classify_distance(dist)
        d_stat = adv.get('by_distance', {}).get(dist_key)
        if d_stat:
            result['prb_distance'] = d_stat['prb']
            result['top3_distance'] = d_stat['top3_rate']
            result['sample_distance'] = d_stat['sample']

    cond = race_meta.get('condition', '')
    if cond:
        c_stat = adv.get('by_condition', {}).get(cond)
        if c_stat:
            result['prb_condition'] = c_stat['prb']
            result['top3_condition'] = c_stat['top3_rate']
            result['sample_condition'] = c_stat['sample']

    umaban = entry.get('umaban', 0)
    if umaban > 0:
        gate_key = _classify_gate(umaban)
        g_stat = adv.get('by_gate', {}).get(gate_key)
        if g_stat:
            result['prb_gate'] = g_stat['prb']
            result['top3_gate'] = g_stat['top3_rate']
            result['sample_gate'] = g_stat['sample']

    wc = entry.get('weight_carried', 0)
    if wc > 0:
        w_key = ('軽量(~53kg)' if wc <= 53 else
                 '標準(54-56kg)' if wc <= 56 else '重斤(57kg~)')
        w_stat = adv.get('by_weight', {}).get(w_key)
        if w_stat:
            result['prb_weight'] = w_stat['prb']

    odds = entry.get('odds', 0)
    if odds > 0:
        o_key = _classify_odds_band(odds)
        o_stat = adv.get('by_odds_band', {}).get(o_key)
        if o_stat:
            result['top3_odds_band'] = o_stat['top3_rate']
            result['sample_odds_band'] = o_stat['sample']

    return result


# ──────────────────────────────────────────────
# 統合分析パイプライン
# ──────────────────────────────────────────────

def analyze_race(race_id: str, progress_callback=None) -> dict:
    """
    レースの出馬表に対して騎手分析Proの全処理を実行する。

    Args:
        race_id: netkeibaレースID
        progress_callback: (current, total, message) を受け取るコールバック

    Returns:
        {
            'race_id': str,
            'venue': str,
            'entries': [
                {
                    'umaban': int,
                    'horse_name': str,
                    'jockey_name': str,
                    'jockey_id': str,
                    'trainer_name': str,
                    'popularity': int,
                    'odds': float,
                    'flags': List[str],         # 判定フラグ
                    'venue_stats': dict | None, # 当該コースでの騎手成績
                    'jockey_profile': dict,      # 騎手プロフィール
                },
                ...
            ],
            'heatmap_data': dict,  # ヒートマップ用データ
        }
    """
    from core.scraper import VENUE_NAMES

    # ① 出馬表から騎手情報を抽出
    if progress_callback:
        progress_callback(0, 4, "出馬表を取得中...")
    entries = extract_jockey_ids_from_race(race_id)
    if not entries:
        return {'race_id': race_id, 'venue': '', 'entries': [], 'heatmap_data': {}, 'error': '出馬表を取得できませんでした'}

    venue_code = race_id[4:6] if len(race_id) >= 6 else ""
    venue = VENUE_NAMES.get(venue_code, "不明")

    # レース基本情報を取得（コース種別・距離・馬場状態など）
    if progress_callback:
        progress_callback(0, 4, "レース情報を取得中...")
    race_meta = fetch_race_meta(race_id)

    # ② 各騎手のコース別成績＆プロフィールを取得
    total = len(entries)
    enriched = []
    heatmap_rows = []

    for i, entry in enumerate(entries):
        if progress_callback:
            progress_callback(1 + i, total + 3,
                              f"騎手データ+高度指標取得中: {entry.get('jockey_name', '')} ({i+1}/{total})")

        jockey_id = entry.get('jockey_id', '')
        if not jockey_id:
            enriched.append({
                **entry,
                'flags': [],
                'venue_stats': None,
                'jockey_profile': {},
            })
            continue

        # プロフィール取得
        profile = fetch_jockey_profile(jockey_id)

        # コース別成績取得
        course_stats = fetch_jockey_course_stats(jockey_id)

        # 当該コースの成績を特定 (見つからない場合は本年成績を会場成績の暫定ベースとして利用)
        venue_stat = None
        for cs in course_stats:
            if cs['venue'] == venue:
                venue_stat = cs
                break
        
        if not venue_stat:
            y_stats = profile.get('year_stats', {})
            total_y = y_stats.get('total', 0)
            target_win = y_stats.get('win_rate', PRIOR_WIN_RATE)
            target_top2 = y_stats.get('top2_rate', PRIOR_TOP2_RATE)
            
            # 統計的に「不明」な状態を避けるため、全国平均をベースにベイズ補正
            venue_stat = {
                'venue': venue,
                'rides': total_y,
                'win_rate': target_win,
                'top2_rate': target_top2,
                'adj_win_rate': round(bayesian_estimate(target_win, total_y, PRIOR_WIN_RATE), 4),
                'adj_top2_rate': round(bayesian_estimate(target_top2, total_y, PRIOR_TOP2_RATE), 4),
                'adj_win_return': PRIOR_WIN_RETURN,
                'is_fallback': True
            }

        # フラグ判定
        # venue_stat が確定しているので、judge_flags_for_entry を介さず直接判定も可能だが、
        # 互換性のため course_stats に fallback を追加して呼ぶ
        fallback_course_stats = course_stats + [venue_stat] if venue_stat not in course_stats else course_stats
        flags = judge_flags_for_entry(entry, fallback_course_stats, venue)

        # PW指数を取得
        pw_idx = get_pw_index(entry.get('jockey_name', ''))

        # db-keiba ボーナス/減点条件を取得し、レース情報と照合
        bonuses_raw = fetch_dbkeiba_bonuses(entry.get('jockey_id', ''))
        bonuses = match_bonus_conditions(bonuses_raw, race_meta, entry)

        # 高度指標 (PRB / Recent Form / 条件別)
        try:
            adv_stats = fetch_jockey_advanced_stats(jockey_id)
            matched_adv = get_matched_advanced_stats(adv_stats, race_meta, entry)
        except Exception as _adv_err:
            logger.warning(f"[AdvStats] {entry.get('jockey_name','')} 取得失敗: {_adv_err}")
            adv_stats = {'prb_overall': 0.5, 'sample_size': 0, 'recent_form': {},
                         'hot_cold': '—', 'by_distance': {}, 'by_condition': {},
                         'by_gate': {}, 'by_class': {}, 'by_odds_band': {},
                         'by_weight': {}, 'riding_style': '—'}
            matched_adv = {'prb_overall': 0.5, 'hot_cold': '—', 'riding_style': '—'}

        # 単回収率をadv_statsから補完（既存値がPRIOR_WIN_RETURNフォールバックの場合）
        if (venue_stat and venue_stat.get('adj_win_return') == PRIOR_WIN_RETURN
                and adv_stats.get('sample_size', 0) > 0):
            _adv_odds = adv_stats.get('by_odds_band', {})
            if _adv_odds:
                _total_w = sum(d['sample'] for d in _adv_odds.values())
                _weighted_prb = sum(d['prb'] * d['sample'] for d in _adv_odds.values())
                if _total_w > 0:
                    _est_wr = (_weighted_prb / _total_w) * 2 * 100
                    venue_stat['adj_win_return'] = round(
                        bayesian_return_estimate(_est_wr, _total_w), 1)
                    venue_stat['win_return_source'] = 'adv_prb'

        enriched.append({
            **entry,
            'flags': flags,
            'venue_stats': venue_stat,
            'jockey_profile': profile,
            'pw_index': pw_idx,
            'bonuses': bonuses,
            'race_meta': race_meta,
            'advanced_stats': adv_stats,
            'matched_adv': matched_adv,
        })

        # ヒートマップ用データ
        if venue_stat:
            heatmap_rows.append({
                'jockey': entry.get('jockey_name', ''),
                'venue': venue,
                'top2_rate': venue_stat.get('adj_top2_rate', 0),
                'win_return': venue_stat.get('adj_win_return', 0),
                'rides': venue_stat.get('rides', 0),
            })

        # レートリミット
        time.sleep(0.5)

    if progress_callback:
        progress_callback(total + 3, total + 3, "分析完了！")

    return {
        'race_id': race_id,
        'venue': venue,
        'entries': enriched,
        'heatmap_data': heatmap_rows,
        'race_meta': race_meta,
    }


def create_result_dataframe(analysis_result: dict) -> pd.DataFrame:
    """
    analyze_race() の結果をStreamlitで表示するためのDataFrameに変換する。
    """
    rows = []
    for e in analysis_result.get('entries', []):
        vs = e.get('venue_stats') or {}
        profile = e.get('jockey_profile') or {}
        year_stats = profile.get('year_stats') or {}
 
        # フラグテキスト
        flags = e.get('flags', [])
        flag_text = " ".join(flags) if flags else "—"
 
        adv = e.get('advanced_stats', {})
        usm = adv.get('usm', {})
        win_usm = usm.get('win_usm', '-')
        top2_usm = usm.get('top2_usm', '-')
        top3_usm = usm.get('top3_usm', '-')
 
        rows.append({
            '馬番': e.get('umaban', 0),
            '馬名': e.get('horse_name', ''),
            '騎手': e.get('jockey_name', ''),
            '厩舎': e.get('trainer_name', ''),
            '人気': e.get('popularity', 99),
            'オッズ': e.get('odds', 0.0),
            '調子P': adv.get('form_score', 0.0),
            '期待値アラート': flag_text,
            '単勝USM': f"{win_usm}%" if isinstance(win_usm, int) else "-",
            '連対USM': f"{top2_usm}%" if isinstance(top2_usm, int) else "-",
            '複勝USM': f"{top3_usm}%" if isinstance(top3_usm, int) else "-",
            # コース別データ (ベイズ補正済み)
            f'{analysis_result.get("venue", "")}連対率': f"{vs.get('adj_top2_rate', 0) * 100:.1f}%" if vs else "—",
            f'{analysis_result.get("venue", "")}単回': f"{vs.get('adj_win_return', 0):.0f}%" if vs else "—",
            f'{analysis_result.get("venue", "")}騎乗数': vs.get('rides', 0) if vs else 0,
            # 今年度成績
            '本年勝率': f"{year_stats.get('win_rate', 0) * 100:.1f}%" if year_stats else "—",
            '本年連対率': f"{year_stats.get('top2_rate', 0) * 100:.1f}%" if year_stats else "—",
        })
 
    df = pd.DataFrame(rows)
    if not df.empty:
        # 人気順ソート
        df = df.sort_values('馬番', ascending=True)
    return df


def calculate_jockey_metrics(entry: dict, venue: str) -> dict:
    """
    騎手個別の各種指数を算出する。
    """
    vs = entry.get('venue_stats') or {}
    profile = entry.get('jockey_profile') or {}
    year_stats = profile.get('year_stats') or {}
    
    # --- 1. 総合騎手力 (Base Power) ---
    # リーディング順位や直近の連対率から算出
    # 本年連対率をベースに、騎乗数ボラティリティを考慮
    y_top2 = year_stats.get('top2_rate', 0.15) # 不明時は平均15%
    total_rides = year_stats.get('total', 0)
    
    # 基礎点: 連対率 * 400 (30% -> 120, 15% -> 60)
    base_power = y_top2 * 400
    # 経験ボーナス: 騎乗数が多いほど信頼度アップ
    experience_bonus = math.log10(total_rides + 1) * 10
    total_power = round(base_power + experience_bonus, 1)
 
    # --- 2. 相性偏差値 (Compatibility) ---
    # 会場連対率 / 本年連対率 をベースにする
    v_top2 = vs.get('adj_top2_rate', vs.get('top2_rate', 0))
    if y_top2 > 0 and v_top2 > 0:
        ratio = v_top2 / y_top2
        comp_score = 50 + (ratio - 1.0) * 40 # 1.5倍なら70
    else:
        comp_score = 50.0
    comp_score = min(99.9, max(0.0, comp_score))
 
    # --- 3. 騎手勝ち指数 (Jockey Win Index) ---
    # 総合力 + 相性ボーナス + フラグ加算
    win_index = total_power + (comp_score - 50) * 2
    
    flags = entry.get('flags', [])
    if "🔴 鉄板" in flags: win_index += 50
    if "🟡 妙味" in flags: win_index += 30
    if "🔵 危険" in flags: win_index -= 40
    
    # 人気薄での好走傾向などがあればさらに加点（簡易実装）
    if vs.get('adj_win_return', 0) > 100:
        win_index += (vs.get('adj_win_return', 100) - 100) / 2

    # 調子P（Form Score）の加減算補正（1:1で勝ち指数を微調整。好調騎手を後押し、不振を減点）
    form_score = entry.get('advanced_stats', {}).get('form_score', 0.0)
    win_index += form_score
 
    return {
        'total_power': total_power,
        'comp_score': round(comp_score, 1),
        'win_index': round(win_index, 1),
    }
 
 
def create_jockey_ranking_dataframe(analysis_result: dict) -> pd.DataFrame:
    """
    「騎手強適 Ranking Table」用のデータを生成する。
    """
    rows = []
    venue = analysis_result.get('venue', '')
    
    for e in analysis_result.get('entries', []):
        metrics = calculate_jockey_metrics(e, venue)
        vs = e.get('venue_stats') or {}
        
        # 最終評価
        idx = metrics['win_index']
        if idx >= 150: eval_label = "◎"
        elif idx >= 120: eval_label = "○"
        elif idx >= 90: eval_label = "▲"
        elif idx >= 60: eval_label = "△"
        else: eval_label = "×"
 
        # 加点要因タグ
        factors = []
        if "🔴 鉄板" in e.get('flags', []): factors.append(f"{venue}強勢")
        if "🟡 妙味" in e.get('flags', []): factors.append("回収特化")
        if vs.get('adj_top2_rate', 0) > 0.3: factors.append("コース巧者")
        if metrics['comp_score'] > 65: factors.append("相性抜抜")
        
        # 現在状態 (簡易)
        recent_win_rate = e.get('jockey_profile', {}).get('year_stats', {}).get('win_rate', 0)
        status = "◎好調" if recent_win_rate > 0.1 else "○安定"
        
        # 馬番/枠
        waku_val = e.get('waku', 0)
        waku_label = ""
        if waku_val > 0:
            if waku_val <= 2: waku_label = f"内{waku_val}"
            elif waku_val >= 7: waku_label = f"外{waku_val}"
            else: waku_label = str(waku_val)
        
        # オッズ断層 (簡易)
        odds = e.get('odds', 0)
        pop = e.get('popularity', 99)
        odds_gap = "-"
        if odds > 0 and pop <= 5:
            # 1つ下の人気との差を見る（ここでは単体オッズから簡易判定）
            if odds > 15: odds_gap = "▲断層"
            elif odds < 3: odds_gap = "◎支持"
 
        adv = e.get('advanced_stats', {})
        form_score = adv.get('form_score', 0.0)
        usm = adv.get('usm', {})
        win_usm = usm.get('win_usm', '-')
        top2_usm = usm.get('top2_usm', '-')
        top3_usm = usm.get('top3_usm', '-')
 
        rows.append({
            '騎手': e.get('jockey_name', ''),
            '騎乗馬': e.get('horse_name', ''),
            '人気': e.get('popularity', 99),
            '馬番/枠': f"{e.get('umaban', 0)} ({waku_label})" if waku_label else str(e.get('umaban', 0)),
            '調子P': form_score,
            '騎手シグナル': " ".join(e.get('flags', [])),
            '騎手勝ち指数': metrics['win_index'],
            '総合騎手力': metrics['total_power'],
            '相性偏差値': metrics['comp_score'],
            '平均位置取り': "-", # プロフィール等から取れれば後で追加
            'オッズ断層': odds_gap,
            '単勝USM': f"{win_usm}%" if isinstance(win_usm, int) else "-",
            '連対USM': f"{top2_usm}%" if isinstance(top2_usm, int) else "-",
            '複勝USM': f"{top3_usm}%" if isinstance(top3_usm, int) else "-",
            '現在状態': status,
            '加点要因': ", ".join(factors) if factors else "-",
            '最終評価': eval_label,
            # hidden for sorting/linking
            '馬番': e.get('umaban', 0),
            '_win_index': metrics['win_index']
        })
 
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values('_win_index', ascending=False).reset_index(drop=True)
        df['Rank'] = range(1, len(df) + 1)
        
        # カラム順の強制
        cols = [
            'Rank', '騎手', '騎乗馬', '人気', '馬番/枠', '調子P', '騎手シグナル', 
            '騎手勝ち指数', '総合騎手力', '相性偏差値', '平均位置取り', 
            'オッズ断層', '単勝USM', '連対USM', '複勝USM', '現在状態', '加点要因', '最終評価'
        ]
        # '馬番'は連動用に内部で使うため残すが、表示側で制御
        df = df[cols + ['馬番']] 
    return df


