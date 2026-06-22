# -*- coding: utf-8 -*-
"""cand_trainer_jyo_t3(厩舎の当コース複勝率)の seed 頑健性チェック — scripts/seed_robustness_check.py

第3イテレーションで防護柵を通った候補が『単一seedの偶然でないか』を確認する。
データ準備は1回だけ(auto_feature_search.prepare を再利用)、複数seedで
ベース vs ベース+候補 を訓練し Δtest/Δval recall@7 の分布を見る。
全seedで一貫して正なら配線へGO、ばらつくなら見送り。
"""
import os
import sys
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.auto_feature_search as afs
import scripts.build_ltr_model as bm

FEAT = 'cand_trainer_jyo_t3'
SEEDS = [42, 1, 7, 123, 2024]


def main():
    train_df, val_df, test_df, cands = afs.prepare(quick=False, candset='cond')
    base = list(bm.FEATURES)
    assert FEAT in cands, f'{FEAT} not in candidates: {cands}'

    rows = []
    for sd in SEEDS:
        afs.PARAMS['seed'] = sd
        afs.PARAMS['bagging_seed'] = sd
        afs.PARAMS['feature_fraction_seed'] = sd
        bm_m = afs.train_eval(train_df, val_df, test_df, base)
        cm = afs.train_eval(train_df, val_df, test_df, base + [FEAT])
        d_test = cm['test_win7'] - bm_m['test_win7']
        d_val = cm['val_win7'] - bm_m['val_win7']
        rows.append((sd, bm_m['test_win7'], cm['test_win7'], d_test, d_val))
        print(f"seed={sd:5d}  base_test={bm_m['test_win7']:.4f}  +feat_test={cm['test_win7']:.4f}  "
              f"Δtest={d_test*100:+.2f}pp  Δval={d_val*100:+.2f}pp", file=sys.stderr)

    dts = np.array([r[3] for r in rows])
    dvs = np.array([r[4] for r in rows])
    print('\n' + '=' * 56, file=sys.stderr)
    print(f'{FEAT}  ({len(SEEDS)} seeds)', file=sys.stderr)
    print(f'  Δtest: mean {dts.mean()*100:+.2f}pp  std {dts.std()*100:.2f}pp  '
          f'正の回数 {int((dts>0).sum())}/{len(dts)}', file=sys.stderr)
    print(f'  Δval : mean {dvs.mean()*100:+.2f}pp  std {dvs.std()*100:.2f}pp  '
          f'正の回数 {int((dvs>0).sum())}/{len(dvs)}', file=sys.stderr)
    go = (dts > 0).all() and dts.mean() > 0.0010 and dvs.mean() >= 0
    print(f"\n判定: {'✅ 配線へGO(全seedで正・平均がプラス)' if go else '⚠ ばらつく/弱い→配線見送り推奨'}",
          file=sys.stderr)


if __name__ == '__main__':
    main()
