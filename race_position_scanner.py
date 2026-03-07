"""
RacePositionPatternScanner Pro v2.0
=====================================
netkeibaの出馬表から、騎手・厩舎の配置パターン（裏番、循環、同期等）を抽出し、
構造的な繋がりから穴馬を特定するシステム。

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

# Enforce UTF-8 stdout
try:
    if sys.stdout is not None and hasattr(sys.stdout, 'closed') and not sys.stdout.closed:
        sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass

# Patch print to safely ignore closed pipes
_builtin_print = print
def safe_print(*args, **kwargs):
    try:
        _builtin_print(*args, **kwargs)
    except (ValueError, OSError, AttributeError):
        pass
print = safe_print

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}
SLEEP_SEC = 1.2
BEST_PERIOD_RANGE = range(3, 9)   # holding day 03~08 is "best period"


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
    ura_number: int = 0   # filled after Race.compute_ura()


@dataclass
class Race:
    race_id: str        # 12-digit netkeiba ID
    venue: str          # 競馬場名 (if available)
    holding_day: int    # digits 9-10 of race_id (開催日数)
    field_size: int     # 登録頭数
    horses: List[Horse] = field(default_factory=list)
    has_scratched: bool = False  # 取消/除外馬フラグ

    def compute_ura(self):
        for h in self.horses:
            h.ura_number = (self.field_size - h.horse_number) + 1

    @property
    def race_number(self) -> int:
        try:
            return int(self.race_id[-2:])
        except Exception:
            return 0


# ──────────────────────────────────────────────
# Scraping Helpers
# ──────────────────────────────────────────────

def _fetch_html(url: str) -> Optional[BeautifulSoup]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"[WARN] Fetch failed {url}: {e}")
        return None


def _parse_float(val: str) -> float:
    try:
        return float(val.replace(",", "").strip())
    except Exception:
        return 0.0


def _parse_int(val: str) -> int:
    try:
        return int(re.sub(r"[^0-9]", "", val))
    except Exception:
        return 0


def _extract_race_id(url: str) -> str:
    m = re.search(r"race_id=(\d{12})", url)
    return m.group(1) if m else url


def _holding_day_from_id(race_id: str) -> int:
    """Digits 9-10 (0-indexed 8-9) of race_id = 開催日数."""
    try:
        return int(race_id[8:10])
    except Exception:
        return 0


def scrape_race(url: str) -> Optional[Race]:
    """Scrape shutuba (entry list) page and return Race object."""
    soup = _fetch_html(url)
    if soup is None:
        return None

    race_id = _extract_race_id(url)
    holding_day = _holding_day_from_id(race_id)

    # Venue
    venue = ""
    venue_tag = (
        soup.select_one(".RaceData02 span:first-child")
        or soup.select_one("dl.racedata dd")
    )
    if venue_tag:
        venue = venue_tag.get_text(strip=True)

    # Shutuba table rows
    table = soup.select_one("#shutuba_table") or soup.select_one("table.Shutuba_Table")
    if table is None:
        print(f"[WARN] No shutuba table at {url}")
        return None

    rows = table.select("tr.HorseList") or table.select("tbody tr")
    horses: List[Horse] = []
    has_scratched = False

    for row in rows:
        # ── Horse Number ──
        uma_cell = (
            row.select_one("td.Umaban")
            or row.select_one("td.waku")
            or row.select_one("td:first-child")
        )
        if uma_cell is None:
            continue
        horse_number = _parse_int(uma_cell.get_text(strip=True))
        if horse_number == 0:
            continue

        # ── Scratch check ──
        row_text = row.get_text()
        is_scratched = ("取消" in row_text) or ("除外" in row_text)
        if is_scratched:
            has_scratched = True
            # Still include the horse but track the flag

        # ── Horse Name ──
        name_cell = (
            row.select_one("td.HorseName a")
            or row.select_one("span.HorseName")
            or row.select_one("td.horse_name a")
        )
        horse_name = name_cell.get_text(strip=True) if name_cell else "不明"

        # ── Jockey ──
        jockey_cell = (
            row.select_one("td.Jockey a")
            or row.select_one("td.jockey_name_td a")
        )
        jockey = jockey_cell.get_text(strip=True) if jockey_cell else ""

        # ── Trainer ──
        trainer_cell = (
            row.select_one("td.Trainer a")
            or row.select_one("td.trainer_name_td a")
        )
        trainer = trainer_cell.get_text(strip=True) if trainer_cell else ""

        # ── Odds / Rank ──
        odds_val, odds_rank = 0.0, 0
        try:
            odds_cells = row.select("td.Odds span") or row.select("td.odds span")
            if odds_cells:
                odds_val = _parse_float(odds_cells[0].get_text(strip=True))
            rank_cell = row.select_one("td.Popular span") or row.select_one("td.tan_rank")
            if rank_cell:
                odds_rank = _parse_int(rank_cell.get_text(strip=True))
        except Exception:
            pass

        horses.append(Horse(
            horse_number=horse_number,
            horse_name=horse_name,
            jockey=jockey,
            trainer=trainer,
            odds=odds_val,
            odds_rank=odds_rank,
        ))

    if not horses:
        print(f"[WARN] No horses parsed at {url}")
        return None

    # field_size = 登録頭数 (include scratched horses in count)
    field_size = len(horses)
    race = Race(
        race_id=race_id,
        venue=venue,
        holding_day=holding_day,
        field_size=field_size,
        horses=horses,
        has_scratched=has_scratched,
    )
    race.compute_ura()
    return race


def build_urls_from_seed(seed_url: str, max_races: int = 12) -> List[str]:
    """Auto-generate race URLs for R1..max_races from any URL of the same day/venue."""
    m = re.search(r"race_id=(\d{12})", seed_url)
    if not m:
        return [seed_url]
    prefix = m.group(1)[:10]   # drop last 2 digits (race number)
    return [
        f"https://race.netkeiba.com/race/shutuba.html?race_id={prefix}{r:02d}"
        for r in range(1, max_races + 1)
    ]


# ──────────────────────────────────────────────
# Pattern Detection
# ──────────────────────────────────────────────

def _detect_patterns(ha: Horse, ra: Race, hb: Horse, rb: Race) -> List[str]:
    """Return list of matched pattern labels for the pair (ha,ra) vs (hb,rb)."""
    matched = []
    same_field = (ra.field_size == rb.field_size)

    # ── P1: 裏同士 ──
    if not same_field and ha.ura_number == hb.ura_number:
        matched.append("P1:裏同士")

    # ── P2: 裏表逆 ──
    if ha.ura_number == hb.horse_number or ha.horse_number == hb.ura_number:
        matched.append("P2:裏表逆")

    # ── P3: 一の位一致 ──
    if ha.horse_number % 10 == hb.horse_number % 10:
        matched.append("P3:一の位一致")

    # ── P4: 片方循環（表循環 + 裏循環） ──
    if not same_field:
        if ra.field_size < rb.field_size:
            s_horse, s_ura, s_fs = ha.horse_number, ha.ura_number, ra.field_size
            t_horse, t_ura          = hb.horse_number, hb.ura_number
        else:
            s_horse, s_ura, s_fs = hb.horse_number, hb.ura_number, rb.field_size
            t_horse, t_ura          = ha.horse_number, ha.ura_number

        # 表循環
        if ((t_horse - 1) % s_fs) + 1 == s_horse:
            matched.append("P4:表循環")
        # 裏循環
        if ((t_ura - 1) % s_fs) + 1 == s_ura:
            matched.append("P4:裏循環")

    return matched


# ──────────────────────────────────────────────
# RaceScanner (Main Orchestrator)
# ──────────────────────────────────────────────

class RaceScanner:
    def __init__(self, entity: str = "jockey"):
        self.entity = entity    # "jockey" | "trainer" | "both"

    # ── Build entity occurrence count per day (for Strategic Entry Bonus) ──
    def _build_entity_count(self, races: List[Race]) -> dict:
        """
        Returns {entity_value: count_of_races_that_entity_appears_in}
        Used to detect exactly-2-appearances.
        """
        counter: dict = defaultdict(set)
        for race in races:
            for h in race.horses:
                if self.entity in ("jockey", "both") and h.jockey:
                    counter[("jockey", h.jockey)].add(race.race_id)
                if self.entity in ("trainer", "both") and h.trainer:
                    counter[("trainer", h.trainer)].add(race.race_id)
        # convert set to count
        return {k: len(v) for k, v in counter.items()}

    # ── Pattern detection across all race pairs ──
    def _get_candidates(self, races: List[Race]) -> dict:
        """
        Returns dict: (race_id, horse_number) -> {race, horse, patterns (set)}
        """
        result: dict = {}

        for i, ra in enumerate(races):
            for j, rb in enumerate(races):
                if i >= j:
                    continue
                for ha in ra.horses:
                    for hb in rb.horses:
                        # Entity match
                        ej = (self.entity in ("jockey", "both")) and ha.jockey and ha.jockey == hb.jockey
                        et = (self.entity in ("trainer", "both")) and ha.trainer and ha.trainer == hb.trainer
                        if not (ej or et):
                            continue

                        patterns = _detect_patterns(ha, ra, hb, rb)
                        if not patterns:
                            continue

                        for key, race_obj, horse_obj in [
                            ((ra.race_id, ha.horse_number), ra, ha),
                            ((rb.race_id, hb.horse_number), rb, hb),
                        ]:
                            if key not in result:
                                result[key] = {"race": race_obj, "horse": horse_obj, "patterns": set()}
                            result[key]["patterns"].update(patterns)

        return result

    # ── Scoring ──
    def _score(self, candidates: dict, entity_count: dict, races: List[Race]) -> List[dict]:
        # Trainer multi-entry lookup (Bonus from v1 kept as trainer_bonus)
        trainer_per_race: dict = {}
        for race in races:
            counter: dict = defaultdict(int)
            for h in race.horses:
                if h.trainer:
                    counter[h.trainer] += 1
            trainer_per_race[race.race_id] = counter

        scored = []
        for (race_id, _horse_num), c in candidates.items():
            race: Race = c["race"]
            horse: Horse = c["horse"]
            patterns: set = c["patterns"]

            score = 0

            # Base: +1 per pattern type
            score += len(patterns)

            # Overlap Bonus: 3+ patterns → +3
            if len(patterns) >= 3:
                score += 3

            # Strategic Entry Bonus: entity appears exactly 2 times on the day, ≥1 pattern
            if len(patterns) >= 1:
                key_j = ("jockey", horse.jockey)
                key_t = ("trainer", horse.trainer)
                if (
                    (self.entity in ("jockey", "both") and entity_count.get(key_j, 0) == 2)
                    or (self.entity in ("trainer", "both") and entity_count.get(key_t, 0) == 2)
                ):
                    score += 3

            # Longshot Bonus
            if horse.odds_rank >= 7 or horse.odds >= 20.0:
                score += 1

            # Holding Day Bonus: day 03~08
            is_best_period = race.holding_day in BEST_PERIOD_RANGE
            if is_best_period:
                score += 1

            # Warning text
            warnings = []
            if race.has_scratched:
                warnings.append("取消/除外馬あり")

            scored.append({
                "race_id": race.race_id,
                "race_number": race.race_number,
                "horse_number": horse.horse_number,
                "horse_name": horse.horse_name,
                "jockey": horse.jockey,
                "trainer": horse.trainer,
                "patterns": ",".join(sorted(patterns)),
                "score": score,
                "odds": horse.odds,
                "rank": horse.odds_rank,
                "is_best_period": is_best_period,
                "warning": "; ".join(warnings),
            })

        return scored

    # ── Main run ──
    def scan(
        self,
        urls: List[str],
        output_csv: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> pd.DataFrame:
        races: List[Race] = []

        for idx, url in enumerate(urls):
            msg = f"[{idx+1}/{len(urls)}] {url}"
            print(msg)
            if progress_callback:
                progress_callback(idx, len(urls), msg)
            race = scrape_race(url)
            if race is not None:
                races.append(race)
            time.sleep(SLEEP_SEC)

        if not races:
            print("[INFO] No race data fetched.")
            return pd.DataFrame()

        entity_count = self._build_entity_count(races)
        candidates = self._get_candidates(races)

        if not candidates:
            print("[INFO] No pattern candidates found.")
            return pd.DataFrame()

        scored = self._score(candidates, entity_count, races)

        df = pd.DataFrame(scored).sort_values(
            by=["score", "race_id"], ascending=[False, True]
        ).reset_index(drop=True)

        if output_csv:
            df.to_csv(output_csv, index=False, encoding='utf-8-sig')
            print(f"[INFO] Saved → {output_csv}")

        return df


# ──────────────────────────────────────────────
# Convenience wrapper (used by Streamlit tab)
# ──────────────────────────────────────────────

def run_scan(
    urls: List[str],
    entity: str = "jockey",
    min_patterns: int = 1,
    output_csv: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
) -> pd.DataFrame:
    scanner = RaceScanner(entity=entity)
    df = scanner.scan(urls, output_csv=output_csv, progress_callback=progress_callback)
    if not df.empty and min_patterns > 1:
        # Count distinct pattern types per row
        df = df[df["patterns"].apply(lambda p: len(p.split(",")) >= min_patterns)]
        df = df.reset_index(drop=True)
    return df


def build_urls_from_seed(seed_url: str, max_races: int = 12) -> List[str]:
    m = re.search(r"race_id=(\d{12})", seed_url)
    if not m:
        return [seed_url]
    prefix = m.group(1)[:10]
    return [
        f"https://race.netkeiba.com/race/shutuba.html?race_id={prefix}{r:02d}"
        for r in range(1, max_races + 1)
    ]


# ──────────────────────────────────────────────
# CLI Entry Point
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RacePositionPatternScanner Pro v2.0")
    parser.add_argument("--urls", nargs="*", help="出馬表URL(複数指定可)")
    parser.add_argument("--seed-url", help="ベースURLから1-12R自動生成")
    parser.add_argument("--auto-day", type=int, default=12, help="最大レース数 (default:12)")
    parser.add_argument("--entity", choices=["jockey", "trainer", "both"], default="jockey")
    parser.add_argument("--min-patterns", type=int, default=1, help="最低パターン数フィルタ")
    parser.add_argument("--output", default="result.csv", help="出力CSVファイル名")
    args = parser.parse_args()

    if not args.urls and not args.seed_url:
        parser.print_help()
        sys.exit(1)

    urls = list(args.urls or [])
    if args.seed_url:
        urls = build_urls_from_seed(args.seed_url, args.auto_day)

    df = run_scan(urls, entity=args.entity, min_patterns=args.min_patterns, output_csv=args.output)

    if not df.empty:
        print("\n===== TOP 20 =====")
        print(df.head(20).to_string(index=False))
    else:
        print("[INFO] No results.")


if __name__ == "__main__":
    main()
