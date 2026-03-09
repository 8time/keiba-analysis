import sys
import os
import time
import argparse
import logging
from datetime import datetime

# Ensure we can import from the root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.odds_logger import OddsFetcher, OddsLogger

# Force UTF-8 for Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

def run_tracker(race_ids, interval=300, once=False):
    """
    Main loop for tracking odds.
    """
    fetcher = OddsFetcher()
    logger_obj = OddsLogger()
    
    logging.info(f"Starting Odds Tracker for races: {race_ids}")
    logging.info(f"Interval: {interval} seconds")
    
    while True:
        start_time = time.time()
        
        for race_id in race_ids:
            try:
                logging.info(f"Fetching odds for race {race_id}...")
                data = fetcher.fetch_win_show_popularity(race_id)
                if data:
                    logger_obj.log_odds(race_id, data)
                else:
                    logging.warning(f"No data returned for race {race_id}")
            except Exception as e:
                logging.error(f"Error tracking race {race_id}: {e}")
            
            # Simple crawl-delay to be polite
            time.sleep(2)
            
        if once:
            logging.info("Run-once mode completed.")
            break
            
        elapsed = time.time() - start_time
        wait_for = max(0, interval - elapsed)
        
        if wait_for > 0:
            logging.info(f"Waiting {wait_for:.1f} seconds for next cycle...")
            time.sleep(wait_for)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real-time Odds Tracker for Netkeiba")
    parser.add_argument("--race_ids", nargs="+", required=True, help="List of 12-digit race IDs")
    parser.add_argument("--interval", type=int, default=300, help="Tracking interval in seconds (default: 300)")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    
    args = parser.parse_args()
    
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    try:
        run_tracker(args.race_ids, args.interval, args.once)
    except KeyboardInterrupt:
        logging.info("Tracker stopped by user.")
    except Exception as e:
        logging.critical(f"Critical error in tracker: {e}")
        sys.exit(1)
