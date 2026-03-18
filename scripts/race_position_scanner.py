"""
RacePositionPatternScanner Pro v2.0
=====================================
netkeibaの出馬表から、騎手・厩舎の配置パターン（裏番、循環、同期等）を抽出し、
構造的な繋がりから穴馬を特定するシステム。

【実行環境】
PowerShell: [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; py race_position_scanner.py --seed-url <URL>
cmd:        chcp 65001 > nul && py race_position_scanner.py --seed-url <URL>
"""

import sys
import re
import time
import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional, Callable

import requests
from bs4 import BeautifulSoup
import pandas as pd

# ──────────────────────────────────────────────
# Encoding & Stdout Protection (Critical)
# ──────────────────────────────────────────────

# Force UTF-8 stdout if possible
try:
    if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError, OSError):
    pass

# Safe print to avoid recursion on reload or closed pipe issues
def safe_print(*args, **kwargs):
    try:
        import sys
        if sys.stdout is not None and not sys.stdout.closed:
            msg = " ".join(map(str, args))
            end = kwargs.get("end", "\n")
            sys.stdout.write(f"{msg}{end}")
            sys.stdout.flush()
    except (ValueError, OSError, AttributeError):
        pass

# Shadow the global print for this module only
print = safe_print

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}
SLEEP_SEC = 1.0

# ──────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────

@dataclass
class Horse:
    horse_number: int
    horse_name: str
    jockey: str
    trainer: str
    odds: float
    odds_rank: int
    ura_number: int = 0
    matched_details: List[str] = field(default_factory=list)
    matched_patterns: set = field(default_factory=set) # Set of pattern labels like 'P1', 'P2'

@dataclass
class Race:
    race_id: str
    race_number: int
    venue: str
    holding_day: int
    field_size: int
    horses: List[Horse] = field(default_factory=list)

    def compute_ura(self):
        for h in self.horses:
            h.ura_number = (self.field_size - h.horse_number) + 1

# ──────────────────────────────────────────────
# Scraping Core
# ──────────────────────────────────────────────

def _fetch_html(url: str) -> Optional[BeautifulSoup]:
    # Standard headers for both requests and curl_cffi
    headers = HEADERS.copy()
    headers.update({
        "sec-ch-ua": '"Not(A:Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1"
    })

    # 1. Try standard requests
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code == 200:
            # Netkeiba fix: apparent_encoding doesn't always work for EUC-JP bytes
            content = resp.content
            html_text = ""
            for enc in ['euc-jp', 'cp51932', 'utf-8', 'cp932']:
                try: 
                    html_text = content.decode(enc)
                    break
                except: continue
            return BeautifulSoup(html_text or resp.text, "html.parser")
    except Exception:
        pass

    # 2. Try curl_cffi (MUCH MORE ROBUST for Cloud/DataCenter IPs)
    try:
        from curl_cffi import requests as curl_requests
        resp2 = curl_requests.get(url, headers=headers, impersonate="chrome120", timeout=15)
        if resp2.status_code == 200:
            content = resp2.content
            html_text = ""
            for enc in ['euc-jp', 'cp51932', 'utf-8', 'cp932']:
                try:
                    html_text = content.decode(enc)
                    break
                except: continue
            return BeautifulSoup(html_text, "html.parser")
    except Exception:
        pass

    return None

def _fetch_odds_api(race_id: str) -> dict:
    """netkeiba オッズ API から単勝オッズ・人気を取得。
    戻り値: {馬番(int): (odds(float), rank(int)), ...}
    """
    result = {}
    try:
        api_url = f"https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={race_id}&type=1"
        h = HEADERS.copy()
        h["Referer"] = "https://race.netkeiba.com/"
        resp = requests.get(api_url, headers=h, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            win_odds = data.get("data", {}).get("odds", {}).get("1", {})
            for umaban_str, vals in win_odds.items():
                # vals = ["オッズ", "", "人気"]
                if isinstance(vals, list) and len(vals) >= 3:
                    try:
                        odds_val = float(vals[0]) if vals[0] else 0.0
                    except (ValueError, TypeError):
                        odds_val = 0.0
                    try:
                        rank_val = int(vals[2]) if vals[2] else 99
                    except (ValueError, TypeError):
                        rank_val = 99
                    result[int(umaban_str)] = (odds_val, rank_val)
    except Exception:
        pass
    return result


def _parse_float(val: str) -> float:
    try:
        m = re.search(r'(\d+\.\d+)', val)
        return float(m.group(1)) if m else 0.0
    except:
        return 0.0

def _parse_int(val: str) -> int:
    try:
        m = re.search(r'(\d+)', val)
        return int(m.group(1)) if m else 99
    except:
        return 99

def scrape_race(url: str) -> Optional[Race]:
    soup = _fetch_html(url)
    if not soup: return None

    # Extract ID and Number
    race_id_match = re.search(r'race_id=(\d+)', url)
    if not race_id_match: return None
    race_id = race_id_match.group(1)
    
    # race_number (last 2 digits)
    race_num = int(race_id[-2:])
    
    # venue code (digits 5-6)
    venue_code = race_id[4:6]
    
    # holding day (digits 9-10)
    holding_day = int(race_id[8:10])

    table = soup.select_one("#shutuba_table") or soup.select_one("table.Shutuba_Table")
    if not table: return None

    rows = table.select("tr.HorseList")
    horses = []
    
    # Field size (total horses listed, including potential scratches for numbering consistency)
    field_size = len(rows)

    for idx, row in enumerate(rows):
        # We need flexible selectors because classes like Umaban can be Umaban1, Umaban2...
        num_td = row.select_one("td[class^='Umaban']")
        name_td = row.select_one("td[class^='HorseInfo']") or row.select_one("td[class^='Horse_Info']")
        jock_td = row.select_one("td[class^='Jockey']")
        train_td = row.select_one("td[class^='Trainer']")
        # オッズ: span[id^='odds-'] を優先、fallback で td.Popular(非Ninki)
        odds_span = row.select_one("span[id^='odds-']")
        odds_td = odds_span.parent if odds_span else row.select_one("td[class^='Odds']")
        # 人気: span[id^='ninki-'] を優先、fallback で td.Popular_Ninki
        pop_span = row.select_one("span[id^='ninki-']")
        pop_td = pop_span.parent if pop_span else row.select_one("td.Popular_Ninki")

        if not (num_td and name_td):
            # Fallback to broader search if class prefix fails
            num_td = num_td or row.find("td", class_=re.compile(r"Umaban"))
            name_td = name_td or row.find("td", class_=re.compile(r"HorseInfo|Horse_Info"))
            jock_td = jock_td or row.find("td", class_=re.compile(r"Jockey"))
            train_td = train_td or row.find("td", class_=re.compile(r"Trainer"))
            if not odds_td:
                odds_td = row.find("td", class_=re.compile(r"Odds"))
            if not pop_td:
                pop_td = row.find("td", class_=re.compile(r"Popular_Ninki"))

        if not (num_td and name_td):
            continue

        h_name = name_td.text.strip()
        # Sometimes name includes breadcrumbs or meta, take the best part
        if "\n" in h_name: h_name = h_name.split("\n")[0].strip()

        horse = Horse(
            horse_number=int(num_td.text.strip()),
            horse_name=h_name,
            jockey=jock_td.text.strip() if (jock_td and jock_td.text.strip()) else "不明",
            trainer=train_td.text.strip() if (train_td and train_td.text.strip()) else "不明",
            odds=_parse_float(odds_span.text.strip() if odds_span else (odds_td.text.strip() if odds_td else "0")),
            odds_rank=_parse_int(pop_span.text.strip() if pop_span else (pop_td.text.strip() if pop_td else "99"))
        )
        horses.append(horse)

    race = Race(
        race_id=race_id,
        race_number=race_num,
        venue=venue_code,
        holding_day=holding_day,
        field_size=field_size,
        horses=horses
    )
    race.compute_ura()

    # 出馬表HTMLではオッズが動的ロードのため取れない → API で補完
    needs_odds = any(h.odds == 0.0 or h.odds_rank == 99 for h in race.horses)
    if needs_odds:
        odds_map = _fetch_odds_api(race_id)
        if odds_map:
            for h in race.horses:
                if h.horse_number in odds_map:
                    o, r = odds_map[h.horse_number]
                    h.odds = o
                    h.odds_rank = r

    return race

# ──────────────────────────────────────────────
# Pattern Logic (Ver 2.0)
# ──────────────────────────────────────────────

def detect_and_record(ha: Horse, ra: Race, hb: Horse, rb: Race, entity_label: str):
    """
    ra.race_number is the target race (base). rb.race_number is the comparison race.
    """
    m_label = f"[{entity_label}] {rb.race_number}R({hb.horse_number}番)"

    # P1: 裏同士 (Back-to-Back)
    # 頭数が違う場合に裏番が一致 (同頭数のレースは対象外)
    if ra.field_size != rb.field_size and ha.ura_number == hb.ura_number:
        ha.matched_details.append(f"{m_label} - 裏同士")
        ha.matched_patterns.add("P1")

    # P2: 裏表逆 (Reverse)
    if ha.ura_number == hb.horse_number or ha.horse_number == hb.ura_number:
        ha.matched_details.append(f"{m_label} - 裏表逆")
        ha.matched_patterns.add("P2")

    # P3: 1の位が同じ (Ones Match)
    # 馬番が違う場合に1の位が一致 (同じ馬番、例:11番同士は対象外。表からのみ)
    if ha.horse_number != hb.horse_number and (ha.horse_number % 10 == hb.horse_number % 10):
        ha.matched_details.append(f"{m_label} - 1の位一致")
        ha.matched_patterns.add("P3")

    # P4: 片方循環 (Cycle)
    # 頭数が違う場合に対象 (同頭数のレースは対象外)
    if ra.field_size != rb.field_size:
        # Smaller race scale
        smaller_f = min(ra.field_size, rb.field_size)
        
        # 1. Forward Cycle (表循環): Larger race horse number projects onto smaller race horse number
        # 2. Backward Cycle (裏循環): Larger race horse number projects onto smaller race ura_number
        
        # We need to check if target horse in larger race projects onto smaller race horse's position
        if ra.field_size > rb.field_size:
            target_num = ha.horse_number
            projected = ((target_num - 1) % smaller_f) + 1
            # Case A: Matches smaller race horse_number
            if projected == hb.horse_number:
                ha.matched_details.append(f"{m_label} - 片方循環(表)")
                ha.matched_patterns.add("P4")
            # Case B: Matches smaller race ura_number
            if projected == hb.ura_number:
                ha.matched_details.append(f"{m_label} - 片方循環(裏)")
                ha.matched_patterns.add("P4")
        else: # ra.field_size < rb.field_size
            target_num = hb.horse_number
            projected = ((target_num - 1) % smaller_f) + 1
            # Case A: Matches smaller race (ours) horse_number
            if projected == ha.horse_number:
                ha.matched_details.append(f"{m_label} - 片方循環(表)")
                ha.matched_patterns.add("P4")
            # Case B: Matches smaller race (ours) ura_number
            if projected == ha.ura_number:
                ha.matched_details.append(f"{m_label} - 片方循環(裏)")
                ha.matched_patterns.add("P4")

# ──────────────────────────────────────────────
# Main Engine
# ──────────────────────────────────────────────

class RacePositionScanner:
    def __init__(self, entity_mode: str = "jockey", min_patterns: int = 1):
        self.entity_mode = entity_mode # jockey, trainer, both
        self.min_patterns = min_patterns

    def scan(self, urls: List[str], progress_callback: Optional[Callable] = None):
        races: List[Race] = []
        for idx, url in enumerate(urls):
            msg = f"Fetching [{idx+1}/{len(urls)}]..."
            print(msg)
            if progress_callback: progress_callback(idx, len(urls), msg)
            
            r = scrape_race(url)
            if r: races.append(r)
            time.sleep(SLEEP_SEC)

        if not races:
            return pd.DataFrame()

        # Cross-comparison
        for ra in races:
            # Bonus: Trainer multiple entry (in same race)
            trainer_counts = defaultdict(int)
            for h in ra.horses: trainer_counts[h.trainer] += 1
            
            for ha in ra.horses:
                # Scoring against other races
                for rb in races:
                    if ra.race_id == rb.race_id: continue # Don't compare with same race patterns
                    
                    for hb in rb.horses:
                        # Check entity match
                        match_jockey = (self.entity_mode in ["jockey", "both"]) and (ha.jockey == hb.jockey)
                        match_trainer = (self.entity_mode in ["trainer", "both"]) and (ha.trainer == hb.trainer)
                        
                        if match_jockey or match_trainer:
                            old_len = len(ha.matched_details)
                            if match_jockey:
                                detect_and_record(ha, ra, hb, rb, "騎手")
                            if match_trainer:
                                detect_and_record(ha, ra, hb, rb, "厩舎")
                            if len(ha.matched_details) > old_len:
                                pass

        # Compile Results
        results = []
        # 日付を推定 (race_id の先頭8桁 YYYYMMDD ではなく YYYY+場+回+日 形式)
        # race_id例: 202506010811 → 2025年 場06 01回 08日目 11R
        # 日付はスキャン対象日 = 全レース共通と仮定
        scan_date = ""
        if races:
            rid = races[0].race_id
            scan_date = rid[:4] + rid[4:6] + rid[6:8]  # 簡易日付キー

        for ra in races:
            # Re-check trainer multiple entry for scoring
            trainer_counts = defaultdict(int)
            for h in ra.horses: trainer_counts[h.trainer] += 1

            for h in ra.horses:
                if len(h.matched_details) < self.min_patterns: continue

                # --- SCORING (Ver 2.0) ---
                score = 0
                # Base: +1 per evidence recorded
                score += len(h.matched_details)

                # Bonus 1 (Overlap): +2 if >= 2 distinct types (P1~P4)
                if len(h.matched_patterns) >= 2:
                    score += 2

                # Bonus 2 (Trainer Entry): +2 if same trainer has 2+ in this race
                if trainer_counts[h.trainer] >= 2:
                    score += 2

                # Bonus 3 (Longshot): +1 if odds_rank >= 7 or odds >= 20.0
                if h.odds_rank >= 7 or h.odds >= 20.0:
                    score += 1

                results.append({
                    "race_number": ra.race_number,
                    "horse_number": h.horse_number,
                    "horse_name": h.horse_name,
                    "jockey": h.jockey,
                    "trainer": h.trainer,
                    "score": score,
                    "patterns_detected": ",".join(sorted(list(h.matched_patterns))),
                    "match_details": " | ".join(h.matched_details),
                    "odds": h.odds,
                    "odds_rank": h.odds_rank,
                    # ◎●シグナル用メタ (後で上書き)
                    "field_size": ra.field_size,
                    "venue": ra.venue,
                    "race_id": ra.race_id,
                    "date": scan_date,
                })

        df = pd.DataFrame(results)
        if not df.empty:
            # --- ◎●シグナル統合 ---
            try:
                from scripts.signals.models import Entry as SigEntry
                from scripts.signals.pipeline import run_special_signal_pipeline
                from scripts.signals.output import (
                    build_double_circle_summary, build_bullet_summary,
                )
                from scripts.signals.grouping import (
                    build_entity_daily_venue_groups,
                    filter_double_circle_candidate_groups,
                    build_trainer_cross_venue_race_groups,
                    filter_bullet_candidate_groups,
                )
                from scripts.signals.double_circle import evaluate_all_double_circle_groups
                from scripts.signals.bullet_signal import evaluate_all_bullet_groups

                # 全馬(フィルタ前)の Entry を作成 (◎●は全馬で判定する必要がある)
                all_entries = []
                for ra in races:
                    for h in ra.horses:
                        all_entries.append(SigEntry(
                            date=scan_date, venue=ra.venue, race_id=ra.race_id,
                            race_number=ra.race_number, field_size=ra.field_size,
                            horse_number=h.horse_number, horse_name=h.horse_name,
                            jockey=h.jockey, trainer=h.trainer,
                            odds=h.odds, odds_rank=h.odds_rank,
                            patterns_detected=",".join(sorted(list(h.matched_patterns))),
                            match_details=" | ".join(h.matched_details),
                            existing_score=0,
                        ))

                # パイプライン実行
                run_special_signal_pipeline(all_entries)

                # 結果をDFにマッピング (race_number + horse_number でキー)
                sig_map = {}
                for e in all_entries:
                    sig_map[(e.race_number, e.horse_number)] = e

                # DataFrame に列追加
                df["special_marks"] = ""
                df["jockey_dc_flag"] = False
                df["jockey_dc_rule"] = ""
                df["trainer_dc_flag"] = False
                df["trainer_dc_rule"] = ""
                df["trainer_bullet_flag"] = False
                df["trainer_bullet_rules"] = ""

                for idx, row in df.iterrows():
                    key = (row["race_number"], row["horse_number"])
                    if key in sig_map:
                        e = sig_map[key]
                        df.at[idx, "special_marks"] = e.special_marks
                        df.at[idx, "jockey_dc_flag"] = e.jockey_double_circle_flag
                        df.at[idx, "jockey_dc_rule"] = e.jockey_double_circle_rule_type or ""
                        df.at[idx, "trainer_dc_flag"] = e.trainer_double_circle_flag
                        df.at[idx, "trainer_dc_rule"] = e.trainer_double_circle_rule_type or ""
                        df.at[idx, "trainer_bullet_flag"] = e.trainer_bullet_flag
                        df.at[idx, "trainer_bullet_rules"] = ",".join(e.trainer_bullet_rule_types)
                        # スコア加算
                        bonus = 0
                        if e.jockey_double_circle_flag: bonus += 3
                        if e.trainer_double_circle_flag: bonus += 3
                        if e.trainer_bullet_flag: bonus += 2
                        df.at[idx, "score"] = row["score"] + bonus

                # ◎●サマリーを保持 (UIで表示用)
                dc_groups = build_entity_daily_venue_groups(all_entries)
                dc_cands = filter_double_circle_candidate_groups(dc_groups)
                dc_results = evaluate_all_double_circle_groups(dc_cands)
                bt_groups = build_trainer_cross_venue_race_groups(all_entries)
                bt_cands = filter_bullet_candidate_groups(bt_groups)
                bt_results = evaluate_all_bullet_groups(bt_cands)

                self._dc_summary = build_double_circle_summary(dc_groups, dc_results)
                self._bt_summary = build_bullet_summary(bt_groups, bt_results)

            except Exception as sig_err:
                print(f"[WARN] ◎●シグナル統合でエラー (既存結果は影響なし): {sig_err}")
                import traceback
                traceback.print_exc()
                self._dc_summary = []
                self._bt_summary = []

            df = df.sort_values(by=["score", "race_number"], ascending=[False, True])
        return df

# ──────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────

def build_urls_from_seed(seed_url: str, max_races: int = 12) -> List[str]:
    # URL example: https://race.netkeiba.com/race/shutuba.html?race_id=202406050511
    # We ensure we use shutuba.html and update the race_id.
    
    # 1. Force shutuba.html
    base_url = seed_url.split('?')[0]
    if 'shutuba.html' not in base_url:
        # Replace result.html or any other page with shutuba.html
        seed_url = seed_url.replace(base_url.split('/')[-1], 'shutuba.html')

    match = re.search(r'(race_id=)(\d{10})(\d{2})', seed_url)
    if not match: return [seed_url]
    
    prefix = match.group(1)
    base_id = match.group(2)
    urls = []
    for i in range(1, max_races + 1):
        r_id = f"{base_id}{i:02d}"
        # Careful replacement of only the ID part
        new_url = re.sub(r'race_id=\d+', f'race_id={r_id}', seed_url)
        urls.append(new_url)
    return urls

def run_scan(
    urls: List[str],
    entity: str = "jockey",
    min_patterns: int = 1,
    output_csv: Optional[str] = "result.csv",
    progress_callback: Optional[Callable] = None
):
    scanner = RacePositionScanner(entity_mode=entity, min_patterns=min_patterns)
    df = scanner.scan(urls, progress_callback=progress_callback)

    if output_csv and not df.empty:
        df.to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"[INFO] Saved results to {output_csv}")

    return df


def run_scan_with_signals(
    urls: List[str],
    entity: str = "jockey",
    min_patterns: int = 1,
    output_csv: Optional[str] = None,
    progress_callback: Optional[Callable] = None
):
    """run_scan + ◎●サマリーを返す拡張版。
    戻り値: (df, dc_summary, bt_summary)
    """
    scanner = RacePositionScanner(entity_mode=entity, min_patterns=min_patterns)
    df = scanner.scan(urls, progress_callback=progress_callback)

    if output_csv and not df.empty:
        df.to_csv(output_csv, index=False, encoding='utf-8-sig')

    dc_summary = getattr(scanner, '_dc_summary', [])
    bt_summary = getattr(scanner, '_bt_summary', [])

    return df, dc_summary, bt_summary

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RacePositionPatternScanner Ver 2.0")
    parser.add_argument("--urls", nargs="+", help="Target entry URLs")
    parser.add_argument("--seed-url", help="Base URL to expand 1R-12R")
    parser.add_argument("--auto-day", type=int, default=12, help="Max races for seed expansion")
    parser.add_argument("--entity", choices=["jockey", "trainer", "both"], default="jockey")
    parser.add_argument("--min-patterns", type=int, default=1)
    parser.add_argument("--output", default="result.csv")

    args = parser.parse_args()
    
    target_urls = []
    if args.seed_url:
        target_urls = build_urls_from_seed(args.seed_url, args.auto_day)
    elif args.urls:
        target_urls = args.urls
    else:
        parser.print_help()
        sys.exit(1)

    df_final = run_scan(target_urls, args.entity, args.min_patterns, args.output)
    if not df_final.empty:
        print("\n=== TOP RESULTS ===")
        print(df_final.head(10).to_string(index=False))
