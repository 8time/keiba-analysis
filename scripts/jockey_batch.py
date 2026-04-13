# -*- coding: utf-8 -*-
"""
騎手成績データのバッチ更新スクリプト。
週次（木〜金曜）に手動で実行する想定。

Usage:
    python scripts/jockey_batch.py --jockeys 05212,01088,01170
    python scripts/jockey_batch.py --top 30
    python scripts/jockey_batch.py --top 10 --retrain
"""

import sys
import os
import argparse
import logging

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# UTF-8強制
os.environ["PYTHONIOENCODING"] = "utf-8"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="騎手成績データのバッチ更新スクリプト"
    )
    parser.add_argument(
        "--jockeys", type=str, default=None,
        help="カンマ区切りの騎手ID (例: 05212,01088,01170)"
    )
    parser.add_argument(
        "--top", type=int, default=30,
        help="リーディング上位N名を対象にする (デフォルト: 30)"
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help="DBパス (デフォルト: data/keiba.db)"
    )
    parser.add_argument(
        "--retrain", action="store_true",
        help="LightGBMウェイトの再学習を行う"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="実際にDBに書き込まず、取得結果を表示のみ"
    )
    args = parser.parse_args()

    from utils.jockey_scraper import JockeyScraper, TOP_JOCKEYS
    from utils.jockey_stats_db import JockeyStatsDB

    db_path = args.db or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "keiba.db"
    )
    scraper = JockeyScraper()
    db = JockeyStatsDB(db_path)

    # テーブルが無ければ初期化
    if not db.table_exists():
        logger.info("jockey_statsテーブルを初期化中...")
        db.init_table()

    # 対象騎手リスト
    if args.jockeys:
        jockey_ids = [jid.strip() for jid in args.jockeys.split(",")]
    else:
        jockey_ids = list(TOP_JOCKEYS.keys())[:args.top]

    logger.info(f"対象騎手: {len(jockey_ids)}名")
    logger.info("=" * 60)

    total_records = 0
    errors = []

    for i, jid in enumerate(jockey_ids):
        name = TOP_JOCKEYS.get(jid, jid)
        logger.info(f"[{i+1}/{len(jockey_ids)}] 取得中: {name} ({jid})")

        try:
            stats = scraper.fetch_all_stats(jid)

            for target_type, df in stats.items():
                if df.empty:
                    logger.warning(f"  {target_type}: 取得失敗（空DataFrame）")
                    continue

                if args.dry_run:
                    logger.info(f"  {target_type}: {len(df)}件 [DRY RUN - 保存スキップ]")
                    print(df.to_string(index=False))
                else:
                    records = df.to_dict("records")
                    count = db.upsert(records)
                    total_records += count
                    logger.info(f"  {target_type}: {count}件保存")

        except Exception as e:
            logger.error(f"  エラー: {e}")
            errors.append({"jockey_id": jid, "name": name, "error": str(e)})
            continue

    logger.info("=" * 60)
    logger.info(f"データ取得完了: 合計{total_records}件保存")

    if errors:
        logger.warning(f"エラー: {len(errors)}件")
        for err in errors:
            logger.warning(f"  {err['name']} ({err['jockey_id']}): {err['error']}")

    # LightGBMウェイト再学習
    if args.retrain:
        logger.info("")
        logger.info("=" * 60)
        logger.info("LightGBMウェイト再学習中...")
        try:
            from utils.jockey_ml import train_weights
            weights = train_weights(target="return_win", db_path=db_path)
            logger.info("ウェイト算出完了:")
            for feat, w in weights.items():
                logger.info(f"  {feat}: {w:.4f}")
        except Exception as e:
            logger.error(f"ウェイト再学習エラー: {e}")

    logger.info("")
    logger.info("バッチ処理完了")


if __name__ == "__main__":
    main()
