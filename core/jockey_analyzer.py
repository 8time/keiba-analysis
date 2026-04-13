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
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import numpy as np

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

# JRA競馬場コード
VENUE_CODES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}


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
    """回収率向けのベイズ推定。"""
    return bayesian_estimate(observed_return, sample_size, prior_return, prior_n)


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
            # 1着, 2着, 3着, 着外, 勝率, 連対率, 複勝率, 単回, 複回
            if len(cell_texts) >= 8:
                try:
                    nums = []
                    for ct in cell_texts:
                        m = re.search(r'[\d,.]+', ct.replace(',', ''))
                        if m:
                            nums.append(m.group())

                    if len(nums) >= 4:
                        stats['wins'] = int(nums[0])
                        stats['seconds'] = int(nums[1])
                        stats['thirds'] = int(nums[2])
                        stats['unplaced'] = int(nums[3])
                        stats['total'] = stats['wins'] + stats['seconds'] + stats['thirds'] + stats['unplaced']
                        if stats['total'] > 0:
                            stats['win_rate'] = stats['wins'] / stats['total']
                            stats['top2_rate'] = (stats['wins'] + stats['seconds']) / stats['total']
                            stats['top3_rate'] = (stats['wins'] + stats['seconds'] + stats['thirds']) / stats['total']
                    # 回収率（末尾2列）
                    if len(nums) >= 6:
                        stats['win_return'] = float(nums[-2])
                        stats['place_return'] = float(nums[-1])
                except (ValueError, IndexError):
                    pass
        return stats

    # テーブル検索: 本年/通算
    tables = soup.select('table.nk_tb_common, table.race_table_01')
    year_stats = _parse_stats_table(tables[0]) if len(tables) > 0 else {}
    career_stats = _parse_stats_table(tables[1]) if len(tables) > 1 else {}

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

    # --- ① pid=jockey_select で競馬場別ページを試みる ---
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

            # 単勝オッズ
            odds_val = 0.0
            try:
                odds_str = cell_texts[9]
                m_odds = re.match(r'^(\d+\.\d+)$', odds_str)
                if m_odds:
                    odds_val = float(m_odds.group(1))
            except IndexError:
                pass

            if venue_name not in venue_stats:
                venue_stats[venue_name] = {'wins': 0, 'seconds': 0, 'thirds': 0, 'total': 0, 'odds_sum': 0.0, 'win_odds_count': 0}
            
            venue_stats[venue_name]['total'] += 1
            if pos == 1:
                venue_stats[venue_name]['wins'] += 1
                if odds_val > 0:
                    venue_stats[venue_name]['odds_sum'] += odds_val * 100
                    venue_stats[venue_name]['win_odds_count'] += 1
            elif pos == 2:
                venue_stats[venue_name]['seconds'] += 1
            elif pos == 3:
                venue_stats[venue_name]['thirds'] += 1

                if not venue_name:
                    continue

                # 単勝オッズを取得（あれば）
                odds_val = 0.0
                for ct in cell_texts:
                    odds_m = re.match(r'^(\d+\.\d+)$', ct)
                    if odds_m:
                        odds_val = float(odds_m.group(1))
                        break

                if venue_name not in venue_stats:
                    venue_stats[venue_name] = {'wins': 0, 'seconds': 0, 'thirds': 0, 'total': 0, 'odds_sum': 0.0, 'win_odds_count': 0}
                venue_stats[venue_name]['total'] += 1
                if pos == 1:
                    venue_stats[venue_name]['wins'] += 1
                    if odds_val > 0:
                        venue_stats[venue_name]['odds_sum'] += odds_val * 100
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
            # 推定回収率: 勝利時オッズの平均 * 勝率 * 100（粗い推定）
            if vs['win_odds_count'] > 0:
                avg_win_odds = vs['odds_sum'] / vs['win_odds_count']
                win_return = avg_win_odds * win_rate
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

    # メイン: 複数URLを試行
    for url_suffix in [
        f"https://db.netkeiba.com/jockey/result/{jockey_id}/?pid=jockey_select&list=track",
        f"https://db.netkeiba.com/jockey/result/{jockey_id}/",
    ]:
        html = _fetch_html_safe(url_suffix)
        if html:
            r = _try_parse_venue_from_html(html)
            if r:
                logger.info(f"[JockeyAnalyzer] コース別成績取得: {jockey_id} {len(r)}会場 (静的HTML)")
                return r

    # フォールバック: 詳細成績ページから集計
    logger.info(f"[JockeyAnalyzer] コース別成績静的HTML取得失敗 → 詳細ページ集計: {jockey_id}")
    r = _aggregate_from_search(jockey_id)
    if r:
        logger.info(f"[JockeyAnalyzer] 詳細集計完了: {jockey_id} {len(r)}会場")
    return r


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
            for sel in ['td.Trainer a', 'td.trainer a', 'a[href*="/trainer/"]']:
                trainer_el = row.select_one(sel)
                if trainer_el:
                    trainer_name = trainer_el.get_text(strip=True)
                    break

            # 人気・オッズ（あれば）
            popularity = 99
            odds = 0.0
            for sel in ['td.Popular span', 'span.OddsPeople', 'td.ninki']:
                pop_el = row.select_one(sel)
                if pop_el:
                    m_p = re.search(r'(\d+)', pop_el.get_text(strip=True))
                    if m_p:
                        popularity = int(m_p.group(1))
                    break
            for sel in ['td.Odds span', 'span.Odds', 'td.odds']:
                odds_el = row.select_one(sel)
                if odds_el:
                    m_o = re.search(r'([\d.]+)', odds_el.get_text(strip=True))
                    if m_o:
                        odds = float(m_o.group(1))
                    break

            if not horse_name and not jockey_name:
                continue

            entries.append({
                'umaban': umaban,
                'horse_name': horse_name,
                'jockey_id': jockey_id,
                'jockey_name': jockey_name,
                'trainer_name': trainer_name,
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
    return sorted(unique_entries, key=lambda x: x['umaban'])


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

    # ② 各騎手のコース別成績＆プロフィールを取得
    total = len(entries)
    enriched = []
    heatmap_rows = []

    for i, entry in enumerate(entries):
        if progress_callback:
            progress_callback(1 + i, total + 3,
                              f"騎手データ取得中: {entry.get('jockey_name', '')} ({i+1}/{total})")

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

        # 当該コースの成績を特定
        venue_stat = None
        for cs in course_stats:
            if cs['venue'] == venue:
                venue_stat = cs
                break

        # フラグ判定
        flags = judge_flags_for_entry(entry, course_stats, venue)

        enriched.append({
            **entry,
            'flags': flags,
            'venue_stats': venue_stat,
            'jockey_profile': profile,
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

        rows.append({
            '馬番': e.get('umaban', 0),
            '馬名': e.get('horse_name', ''),
            '騎手': e.get('jockey_name', ''),
            '厩舎': e.get('trainer_name', ''),
            '人気': e.get('popularity', 99),
            'オッズ': e.get('odds', 0.0),
            '期待値アラート': flag_text,
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
