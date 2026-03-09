import sys
import os
import time
import argparse
import logging
from datetime import datetime

# Add root directory to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from core.odds_tracker import OddsTracker
from core.scraper import get_race_ids_for_date

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("odds_tracker.log", encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

def run_tracker(race_ids, interval_minutes=5, duration_hours=5):
    tracker = OddsTracker()
    start_time = time.time()
    end_time = start_time + (duration_hours * 3600)
    
    logger.info(f"Starting odds tracker for {len(race_ids)} races.")
    logger.info(f"Interval: {interval_minutes} min, Duration: {duration_hours} hours.")
    
    while time.time() < end_time:
        loop_start = time.time()
        
        for rid in race_ids:
            try:
                count = tracker.track(rid)
                logger.info(f"Race {rid}: Logged {count} entries.")
                # Small sleep between races to avoid throttling
                time.sleep(1)
            except Exception as e:
                logger.error(f"Error tracking race {rid}: {e}")
        
        elapsed = time.time() - loop_start
        wait_time = max(0, (interval_minutes * 60) - elapsed)
        
        if wait_time > 0:
            logger.info(f"Waiting {wait_time/60:.1f} minutes for next cycle...")
            time.sleep(wait_time)
        else:
            logger.warning("Cycle took longer than interval. Starting next cycle immediately.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Odds Time-Series Tracker")
    parser.add_argument("--ids", type=str, help="Comma-separated Race IDs")
    parser.add_argument("--interval", type=int, default=5, help="Interval in minutes (default: 5)")
    parser.add_argument("--duration", type=int, default=12, help="Duration in hours (default: 12)")
    parser.add_argument("--auto-today", action="store_true", help="Automatically fetch today's race IDs")
    
    args = parser.parse_args()
    
    target_ids = []
    if args.ids:
        target_ids = [s.strip() for s in args.ids.split(",")]
    elif args.auto_today:
        logger.info("Fetching today's race IDs...")
        target_ids = get_race_ids_for_date()
        if not target_ids:
            logger.warning("No races found for today.")
            sys.exit(0)
    else:
        logger.error("Please provide --ids or use --auto-today.")
        sys.exit(1)
        
    try:
        run_tracker(target_ids, args.interval, args.duration)
    except KeyboardInterrupt:
        logger.info("Tracker stopped by user.")
