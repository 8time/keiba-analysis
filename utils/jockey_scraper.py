# -*- coding: utf-8 -*-
"""
netkeibaデータ自動取得モジュール
================================
騎手×コース / 騎手×厩舎 / 騎手×馬 の成績を
db.netkeiba.com から取得し、jockey_stats テーブルに格納する。

既存の core/scraper.fetch_robust_html() を活用した多段フォールバック方式。
N指数は使用しない。
"""

import re
import time
import logging
from typing import List, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# リクエスト間隔（秒）— サーバー負荷軽減
REQUEST_INTERVAL = 2.0

# JRA競馬場コード → 名前（パース時の照合用）
VENUE_NAMES_SET = frozenset([
    "札幌", "函館", "福島", "新潟", "東京",
    "中山", "中京", "京都", "阪神", "小倉",
])

# リーディング上位騎手ID一覧（2024-2025年ベース）
TOP_JOCKEYS = {
    "05212": "C.ルメール",
    "01088": "川田将雅",
    "01170": "横山武史",
    "00666": "武豊",
    "01126": "戸崎圭太",
    "01166": "M.デムーロ",
    "01130": "松山弘平",
    "01098": "田辺裕信",
    "01191": "坂井瑠星",
    "01192": "横山和生",
    "01154": "岩田望来",
    "01018": "浜中俊",
    "01169": "菅原明良",
    "01175": "西村淳也",
    "01189": "鮫島克駿",
    "01143": "石橋脩",
    "01140": "石川裕紀人",
    "01019": "池添謙一",
    "01114": "三浦皇成",
    "01173": "藤岡佑介",
    "01011": "福永祐一",
    "01076": "内田博幸",
    "01174": "吉田隼人",
    "01190": "団野大成",
    "01186": "永野猛蔵",
    "01168": "丹内祐次",
    "01193": "角田大和",
    "01194": "小林脩斗",
    "01195": "佐々木大輔",
    "01196": "田口貫太",
}


def _fetch_html(url: str) -> Optional[str]:
    """core/scraper.py の fetch_robust_html を呼ぶラッパー"""
    try:
        from core.scraper import fetch_robust_html
        return fetch_robust_html(url)
    except Exception as e:
        logger.error(f"[JockeyScraper] HTML取得失敗: {url} → {e}")
        return None


def _safe_int(text: str, default: int = 0) -> int:
    """テキストから整数を安全に抽出"""
    m = re.search(r'[\d,]+', text.replace(',', ''))
    if m:
        try:
            return int(m.group().replace(',', ''))
        except ValueError:
            pass
    return default


def _safe_float(text: str, default: float = 0.0) -> float:
    """テキストから浮動小数点数を安全に抽出"""
    m = re.search(r'[\d,.]+', text.replace(',', ''))
    if m:
        try:
            return float(m.group().replace(',', ''))
        except ValueError:
            pass
    return default


class JockeyScraper:
    """netkeibaから騎手成績データを取得するクラス"""

    BASE_URL = "https://db.netkeiba.com"

    def __init__(self, interval: float = REQUEST_INTERVAL):
        self.interval = interval

    def fetch_jockey_name(self, jockey_id: str) -> str:
        """騎手IDから名前を取得する（キャッシュ目的）"""
        if jockey_id in TOP_JOCKEYS:
            return TOP_JOCKEYS[jockey_id]
        # netkeibaから取得
        from bs4 import BeautifulSoup
        url = f"{self.BASE_URL}/jockey/{jockey_id}/"
        html = _fetch_html(url)
        if not html:
            return jockey_id
        soup = BeautifulSoup(html, 'html.parser')
        name_el = soup.select_one('h1.Name, .db_head_name h1, .Name_En')
        if name_el:
            name = re.sub(r'\s+', ' ', name_el.get_text(strip=True))
            return name
        return jockey_id

    def fetch_jockey_course_stats(self, jockey_id: str) -> pd.DataFrame:
        """
        騎手×コース別成績を取得する。

        db.netkeiba.com/jockey/result/{jockey_id}/ のテーブルから
        競馬場別の成績を抽出する。

        Returns:
            DataFrame: columns = [jockey_id, jockey_name, target_type,
                target_id, target_name, ride_count, win_count, top2_count,
                top3_count, win_rate, top2_rate, top3_rate, return_win, return_place]
        """
        from bs4 import BeautifulSoup

        time.sleep(self.interval)
        url = f"{self.BASE_URL}/jockey/result/{jockey_id}/"
        html = _fetch_html(url)
        if not html:
            logger.warning(f"[JockeyScraper] コース成績取得失敗: {jockey_id}")
            return pd.DataFrame()

        jockey_name = self.fetch_jockey_name(jockey_id)
        soup = BeautifulSoup(html, 'html.parser')
        rows = []

        for table in soup.select('table'):
            for tr in table.find_all('tr'):
                cells = tr.find_all(['td', 'th'])
                if len(cells) < 8:
                    continue
                cell_texts = [c.get_text(strip=True) for c in cells]

                # 先頭セルが競馬場名か判定
                venue_name = cell_texts[0]
                if venue_name not in VENUE_NAMES_SET:
                    continue

                try:
                    nums = []
                    for ct in cell_texts[1:]:
                        m = re.search(r'[\d,.]+', ct.replace(',', ''))
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

                    rows.append({
                        "jockey_id": jockey_id,
                        "jockey_name": jockey_name,
                        "target_type": "course",
                        "target_id": venue_name,
                        "target_name": venue_name,
                        "ride_count": total,
                        "win_count": wins,
                        "top2_count": wins + seconds,
                        "top3_count": wins + seconds + thirds,
                        "win_rate": round(win_rate, 4),
                        "top2_rate": round(top2_rate, 4),
                        "top3_rate": round(top3_rate, 4),
                        "return_win": win_return,
                        "return_place": place_return,
                    })
                except (ValueError, IndexError) as e:
                    logger.debug(f"[JockeyScraper] パースエラー: {e}")
                    continue

        logger.info(f"[JockeyScraper] コース成績: {jockey_name} → {len(rows)}件")
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def fetch_jockey_trainer_stats(self, jockey_id: str) -> pd.DataFrame:
        """
        騎手×厩舎別成績を取得する。

        db.netkeiba.com/jockey/result/{jockey_id}/ のページ内で
        厩舎名パターン（「○○厩舎」または調教師っぽい名前）を持つ行を検出する。

        netkeibaではコース別と同一ページに厩舎別表が表示されるケースがあるが、
        ページ構造が異なる場合は空DataFrameを返す。

        Returns:
            DataFrame（コース成績と同カラム構成、target_type='trainer'）
        """
        from bs4 import BeautifulSoup

        time.sleep(self.interval)
        # 厩舎別成績ページを試行（netkeibaの内部パラメータ）
        url = f"{self.BASE_URL}/jockey/result/{jockey_id}/?pid=jockey_select&list=trainer"
        html = _fetch_html(url)
        if not html:
            # フォールバック: 通常のresultページ
            url = f"{self.BASE_URL}/jockey/result/{jockey_id}/"
            html = _fetch_html(url)
        if not html:
            logger.warning(f"[JockeyScraper] 厩舎成績取得失敗: {jockey_id}")
            return pd.DataFrame()

        jockey_name = self.fetch_jockey_name(jockey_id)
        soup = BeautifulSoup(html, 'html.parser')
        rows = []

        # 厩舎名パターン: 漢字2-4文字（競馬場名を除外）
        trainer_pattern = re.compile(r'^[一-龥ぁ-ゖァ-ヶ]{1,6}$')

        for table in soup.select('table'):
            table_rows = table.find_all('tr')
            for tr in table_rows:
                cells = tr.find_all(['td', 'th'])
                if len(cells) < 8:
                    continue
                cell_texts = [c.get_text(strip=True) for c in cells]

                first_cell = cell_texts[0]
                # 競馬場名は除外
                if first_cell in VENUE_NAMES_SET:
                    continue
                # 空やヘッダーは除外
                if not first_cell or first_cell in ["開催地", "コース", "距離", "クラス", "合計", ""]:
                    continue

                # 厩舎名っぽいか判定（リンク先が /trainer/ を含むか）
                first_a = tr.find('a', href=re.compile(r'/trainer/'))
                is_trainer = first_a is not None

                # リンクがない場合は名前パターンで推定
                if not is_trainer and trainer_pattern.match(first_cell):
                    # 数字行（距離: "1200" 等）を除外
                    if re.match(r'^\d+$', first_cell):
                        continue
                    is_trainer = True

                if not is_trainer:
                    continue

                try:
                    # トレーナーID取得
                    trainer_id = first_cell
                    if first_a:
                        m_tid = re.search(r'/trainer/(\d+)', first_a.get('href', ''))
                        if m_tid:
                            trainer_id = m_tid.group(1)

                    nums = []
                    for ct in cell_texts[1:]:
                        m = re.search(r'[\d,.]+', ct.replace(',', ''))
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

                    rows.append({
                        "jockey_id": jockey_id,
                        "jockey_name": jockey_name,
                        "target_type": "trainer",
                        "target_id": trainer_id,
                        "target_name": first_cell,
                        "ride_count": total,
                        "win_count": wins,
                        "top2_count": wins + seconds,
                        "top3_count": wins + seconds + thirds,
                        "win_rate": round(win_rate, 4),
                        "top2_rate": round(top2_rate, 4),
                        "top3_rate": round(top3_rate, 4),
                        "return_win": win_return,
                        "return_place": place_return,
                    })
                except (ValueError, IndexError) as e:
                    logger.debug(f"[JockeyScraper] 厩舎パースエラー: {e}")
                    continue

        logger.info(f"[JockeyScraper] 厩舎成績: {jockey_name} → {len(rows)}件")
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def fetch_jockey_horse_stats(self, jockey_id: str) -> pd.DataFrame:
        """
        騎手×馬別の直近成績を取得する。
        継続騎乗・乗り替わり判定に使用。

        db.netkeiba.com/jockey/result/recent/{jockey_id}/ の直近結果から
        同一馬名での騎乗回数を集計する。

        Returns:
            DataFrame（target_type='horse'）
        """
        from bs4 import BeautifulSoup

        time.sleep(self.interval)
        url = f"{self.BASE_URL}/jockey/result/recent/{jockey_id}/"
        html = _fetch_html(url)
        if not html:
            logger.warning(f"[JockeyScraper] 馬別成績取得失敗: {jockey_id}")
            return pd.DataFrame()

        jockey_name = self.fetch_jockey_name(jockey_id)
        soup = BeautifulSoup(html, 'html.parser')

        # 直近成績テーブルから馬名と着順を収集
        horse_results: Dict[str, List[int]] = {}  # {馬名: [着順リスト]}

        for table in soup.select('table.nk_tb_common, table.race_table_01'):
            for tr in table.find_all('tr'):
                cells = tr.find_all('td')
                if len(cells) < 8:
                    continue
                try:
                    # 馬名（リンクテキスト）
                    horse_a = tr.find('a', href=re.compile(r'/horse/'))
                    if not horse_a:
                        continue
                    horse_name = horse_a.get_text(strip=True)
                    if not horse_name:
                        continue

                    # 着順
                    pos_text = cells[0].get_text(strip=True) if cells else ""
                    pos_m = re.match(r'(\d+)', pos_text)
                    if pos_m:
                        pos = int(pos_m.group(1))
                    else:
                        pos = 99  # 除外・中止等

                    if horse_name not in horse_results:
                        horse_results[horse_name] = []
                    horse_results[horse_name].append(pos)
                except Exception:
                    continue

        # 集計してDataFrame化
        rows = []
        for horse_name, positions in horse_results.items():
            total = len(positions)
            wins = sum(1 for p in positions if p == 1)
            top2 = sum(1 for p in positions if p <= 2)
            top3 = sum(1 for p in positions if p <= 3)

            rows.append({
                "jockey_id": jockey_id,
                "jockey_name": jockey_name,
                "target_type": "horse",
                "target_id": horse_name,
                "target_name": horse_name,
                "ride_count": total,
                "win_count": wins,
                "top2_count": top2,
                "top3_count": top3,
                "win_rate": round(wins / total, 4) if total > 0 else 0.0,
                "top2_rate": round(top2 / total, 4) if total > 0 else 0.0,
                "top3_rate": round(top3 / total, 4) if total > 0 else 0.0,
                "return_win": 0.0,   # 直近結果からは回収率計算不可
                "return_place": 0.0,
            })

        logger.info(f"[JockeyScraper] 馬別成績: {jockey_name} → {len(rows)}件")
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def fetch_all_stats(self, jockey_id: str) -> Dict[str, pd.DataFrame]:
        """
        全カテゴリの成績を一括取得する。

        Args:
            jockey_id: netkeiba騎手ID（5桁）

        Returns:
            {"course": DataFrame, "trainer": DataFrame, "horse": DataFrame}
        """
        logger.info(f"[JockeyScraper] 全成績取得開始: {jockey_id}")
        result = {
            "course": self.fetch_jockey_course_stats(jockey_id),
            "trainer": self.fetch_jockey_trainer_stats(jockey_id),
            "horse": self.fetch_jockey_horse_stats(jockey_id),
        }
        total = sum(len(df) for df in result.values() if not df.empty)
        logger.info(f"[JockeyScraper] 全成績取得完了: {jockey_id} → 合計{total}件")
        return result

    def fetch_multiple_jockeys(
        self,
        jockey_ids: List[str],
        progress_callback=None,
    ) -> Dict[str, pd.DataFrame]:
        """
        複数騎手の成績を一括取得する（バッチ処理用）。

        Args:
            jockey_ids: 騎手IDリスト
            progress_callback: fn(current, total, msg) 進捗コールバック

        Returns:
            {"course": 結合DataFrame, "trainer": 結合DataFrame, "horse": 結合DataFrame}
        """
        all_course = []
        all_trainer = []
        all_horse = []
        total = len(jockey_ids)

        for i, jid in enumerate(jockey_ids):
            name = TOP_JOCKEYS.get(jid, jid)
            if progress_callback:
                progress_callback(i, total, f"取得中: {name} ({jid}) [{i+1}/{total}]")

            stats = self.fetch_all_stats(jid)
            if not stats["course"].empty:
                all_course.append(stats["course"])
            if not stats["trainer"].empty:
                all_trainer.append(stats["trainer"])
            if not stats["horse"].empty:
                all_horse.append(stats["horse"])

        result = {
            "course": pd.concat(all_course, ignore_index=True) if all_course else pd.DataFrame(),
            "trainer": pd.concat(all_trainer, ignore_index=True) if all_trainer else pd.DataFrame(),
            "horse": pd.concat(all_horse, ignore_index=True) if all_horse else pd.DataFrame(),
        }

        if progress_callback:
            total_records = sum(len(df) for df in result.values() if not df.empty)
            progress_callback(total, total, f"完了: {total_records}件取得")

        return result
