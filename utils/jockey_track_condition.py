# -*- coding: utf-8 -*-
"""
馬場状態リアルタイム取得モジュール
====================================
当日のJRA全会場の馬場発表（良/稍重/重/不良）を取得し、
タブ1「騎手×コース×脚質」のフィルタに自動適用する。

取得元:
  1. JRA公式サイト（www.jra.go.jp）
  2. netkeibaレースリストページ
  3. フォールバック: 手動入力に委ねる

N指数は使用しない。
"""

import re
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TrackCondition:
    """馬場状態データ"""
    venue: str        # "東京" / "中山" / "阪神" 等
    surface: str      # "芝" / "ダート"
    condition: str    # "良" / "稍重" / "重" / "不良"
    updated_at: str   # 取得時刻


# JRA開催場コード → 場名
_JRA_VENUE_MAP = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}


def _fetch_html_safe(url: str) -> Optional[str]:
    """core/scraper.py の fetch_robust_html を呼ぶラッパー"""
    try:
        from core.scraper import fetch_robust_html
        return fetch_robust_html(url)
    except Exception as e:
        logger.debug(f"[TrackCondition] HTML取得失敗: {url} → {e}")
        return None


def fetch_track_conditions_jra() -> List[TrackCondition]:
    """
    JRA公式サイトから馬場状態を取得する。

    JRA公式はHTMLが比較的静的なので、Fetcherで取得可能な可能性が高い。
    """
    from bs4 import BeautifulSoup
    from datetime import datetime

    results = []
    url = "https://www.jra.go.jp/keiba/baba/"

    html = _fetch_html_safe(url)
    if not html:
        logger.debug("[TrackCondition] JRA公式からの取得失敗")
        return results

    soup = BeautifulSoup(html, 'html.parser')
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # JRA公式の馬場状態ページ: テーブルに「場名 / 芝 / ダート / 状態」の形式
    # 複数のパターンを試行
    for table in soup.select('table'):
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all(['td', 'th'])
            cell_texts = [c.get_text(strip=True) for c in cells]

            # 場名を検出
            venue = None
            for ct in cell_texts:
                if ct in _JRA_VENUE_MAP.values():
                    venue = ct
                    break

            if not venue:
                continue

            # 馬場状態を検出
            for ct in cell_texts:
                if ct in ["良", "稍重", "重", "不良"]:
                    # 芝/ダートの判定
                    surface = "芝"  # デフォルト
                    for ct2 in cell_texts:
                        if "ダ" in ct2 or "ダート" in ct2:
                            surface = "ダート"
                            break

                    results.append(TrackCondition(
                        venue=venue,
                        surface=surface,
                        condition=ct,
                        updated_at=now_str,
                    ))
                    break

    # テーブルが見つからない場合、テキストから正規表現で抽出を試みる
    if not results:
        text = soup.get_text()
        # パターン: "東京 芝 良" や "中山 ダート 重"
        pattern = re.compile(
            r'(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)\s*'
            r'(芝|ダート|ダ)\s*[:：]?\s*(良|稍重|重|不良)'
        )
        for m in pattern.finditer(text):
            venue = m.group(1)
            surface = "ダート" if "ダ" in m.group(2) else "芝"
            condition = m.group(3)
            results.append(TrackCondition(
                venue=venue,
                surface=surface,
                condition=condition,
                updated_at=now_str,
            ))

    if results:
        logger.info(f"[TrackCondition] JRA公式から{len(results)}件の馬場状態を取得")

    return results


def fetch_track_conditions_netkeiba() -> List[TrackCondition]:
    """
    netkeibaのレースリストから馬場状態を推定する。

    開催日のレースリストページで馬場状態が記載される場合がある。
    """
    from bs4 import BeautifulSoup
    from datetime import datetime

    results = []
    today = datetime.now().strftime("%Y%m%d")
    url = f"https://race.netkeiba.com/top/race_list.html?kaisai_date={today}"

    html = _fetch_html_safe(url)
    if not html:
        return results

    soup = BeautifulSoup(html, 'html.parser')
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # netkeibaレースリスト: 馬場状態が記載される要素を探す
    for el in soup.select('.RaceList_Item, .JyoName, .RaceData01, .Track, span'):
        text = el.get_text(strip=True)

        # パターン検出
        pattern = re.compile(
            r'(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉).*?'
            r'(芝|ダ).*?(良|稍重|重|不良)'
        )
        m = pattern.search(text)
        if m:
            venue = m.group(1)
            surface = "ダート" if m.group(2) == "ダ" else "芝"
            condition = m.group(3)

            # 重複チェック
            already = any(
                r.venue == venue and r.surface == surface
                for r in results
            )
            if not already:
                results.append(TrackCondition(
                    venue=venue,
                    surface=surface,
                    condition=condition,
                    updated_at=now_str,
                ))

    if results:
        logger.info(f"[TrackCondition] netkeibaから{len(results)}件の馬場状態を取得")

    return results


def fetch_track_conditions() -> List[TrackCondition]:
    """
    全ソースから馬場状態を取得する。

    優先順位:
    1. JRA公式
    2. netkeiba
    3. 空リスト（手動入力に委ねる）

    Returns:
        TrackConditionのリスト。取得失敗時は空リスト。
    """
    # JRA公式
    results = fetch_track_conditions_jra()
    if results:
        return results

    # netkeiba
    results = fetch_track_conditions_netkeiba()
    if results:
        return results

    logger.info("[TrackCondition] 馬場状態の自動取得失敗。手動入力を促す。")
    return []


def get_condition_for_venue(
    conditions: List[TrackCondition],
    venue: str,
    surface: Optional[str] = None,
) -> Optional[str]:
    """
    特定の会場の馬場状態を取得する。

    Args:
        conditions: fetch_track_conditions() の結果
        venue: 会場名（"東京" 等）
        surface: "芝" or "ダート"（Noneなら区別しない）

    Returns:
        "良" / "稍重" / "重" / "不良" / None（該当なし）
    """
    for c in conditions:
        if c.venue == venue:
            if surface is None or c.surface == surface:
                return c.condition
    return None
