# -*- coding: utf-8 -*-
"""
④ 収支・自己改善ログ（予測→結果→反省→学習）デモ

実体は core/money.py の Ledger に移管済み。本ファイルは CLI デモ＋後方互換ラッパ。
  from scripts.betting_ledger import Ledger  # = core.money.Ledger
DB: data/ledger.db
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.money import Ledger, LEDGER_DB as DB  # noqa: E402


def _demo():
    import random
    if os.path.exists(DB):
        os.remove(DB)
    lg = Ledger()
    rng = random.Random(1)
    print("=" * 64); print("④ 収支・自己改善ログ デモ（予測→結果→反省）"); print("=" * 64)
    # 合成データ: AIが各馬に予測勝率をつけて単勝を買い、結果を精算
    # わざと「予測を少し過大評価する」クセを入れて、反省が検知できるか見る
    for i in range(300):
        rid = f"R{i:04d}"
        true_p = rng.uniform(0.05, 0.5)
        pred_p = min(0.95, true_p * 1.2)        # 20%過大評価のクセ
        odds = round(1 / true_p * rng.uniform(0.8, 1.0), 1)  # 控除率込みオッズ
        lg.record_prediction(rid, 1, f"馬{i}", pred_p, odds)
        won = 1 if rng.random() < true_p else 0
        lg.settle(rid, 1 if won else 99, int(odds * 100))
    rep = lg.report()
    print(f"\n■ 成績: {rep['bets']}戦 的中{rep['hit_rate']}% 回収率{rep['roi']}% 収支{rep['profit']:+}円")
    print(f"  Brier score(較正の良さ・低いほど良): {rep['brier']}")
    print("\n■ 反省会（予測 vs 実際の較正ズレ → 次回ルール）")
    for r in lg.reflection():
        print("  -", r)
    print("\n→ 「予測を過大評価するクセ」を数値で自己検知。これを予測プロンプト/モデルに反映＝自己改善ループ")
    lg.close()


if __name__ == '__main__':
    _demo()
