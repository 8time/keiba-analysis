# -*- coding: utf-8 -*-
"""集合知Brier加重の CV 検証 ―― カード8(⑩)。

leave-one-out: 各精算済みレースを1件抜き、残りでエージェント重みを学習→
そのレースの合議を『重み付き』と『均等』で作り、◎/合議top3の的中Brierを比較。
採用ゲート(カード8): 加重合議Brier < 均等合議Brier（台帳CV）。

前提: 台帳(agent_retrospective.json)の精算済みが n>=50 必要。
現状ほぼ空なので、貯まるまでは『データ不足』を報告する(=P3のBetSync台帳と同じ
「使うと貯まる」設計)。エージェント発言生成やgrounding強化は本カードの非目標。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from core import agent_forum as af  # noqa: E402

MIN_N = 50


def consensus_top3(sorted_votes, k=3):
    return [um for um, _ in sorted_votes[:k]]


def brier_of(records, weighted, lam=1.0):
    """各レースで合議top3が実top3を当てたか(0/1)→Brier=平均(1-hit)。"""
    settled = [r for r in records if r.get('result')]
    tot, hits = 0, 0
    for i, rec in enumerate(settled):
        posts = rec.get('_posts')  # 保存があれば使用
        top3_actual = set(rec.get('result', {}).get('top3', []))
        if not top3_actual:
            continue
        if weighted:
            others = settled[:i] + settled[i + 1:]  # LOO(自分を除く)
            w = af.agent_weights(others, lam=lam)
        else:
            w = {}
        # 合議は保存済みpostsが無ければ agent_picks から近似再構成
        if posts:
            sv = af.weighted_consensus(posts, w)
            pred = consensus_top3(sv)
        else:
            # agent_picks(honmei/taikou/anaume)を擬似postに変換
            fake = []
            for ag_id, pk in (rec.get('agent_picks') or {}).items():
                parts = []
                for mark, key in (('◎', 'honmei'), ('○', 'taikou'), ('▲', 'anaume')):
                    if pk.get(key):
                        parts.append(f"{mark}{pk[key]}番")
                if parts:
                    fake.append({'agent_id': ag_id, 'content': ' '.join(parts)
                                 + f" 自信度{pk.get('confidence', 50)}%"})
            sv = af.weighted_consensus(fake, w)
            pred = consensus_top3(sv)
        tot += 1
        hits += 1 if (set(pred) & top3_actual) else 0
    return (1.0 - hits / tot) if tot else None, tot


def main():
    records = af.load_retrospective(100)
    settled = [r for r in records if r.get('result')]
    print(f"台帳: 全{len(records)}件 / 精算済み{len(settled)}件 (必要 n>={MIN_N})")
    tr = af.agent_track_record(records)
    if tr:
        print("\nエージェント別成績(参考):")
        for ag, d in sorted(tr.items(), key=lambda x: -x[1]['hit_rate']):
            print(f"  {ag:<12} n={d['n']:>3} 的中率{d['hit_rate']*100:>5.1f}% Brier{d['brier']:.3f}")

    if len(settled) < MIN_N:
        print(f"\n判定: ⏸ データ不足({len(settled)}<{MIN_N})。集合知掲示板で予測→精算を"
              f"重ねて台帳を貯めてから再実行。均等重み(=単純平均)で安全に稼働中。")
        return

    bw, nw = brier_of(records, weighted=True)
    bu, nu = brier_of(records, weighted=False)
    print(f"\n加重合議 Brier = {bw:.4f} (n={nw})")
    print(f"均等合議 Brier = {bu:.4f} (n={nu})")
    if bw is not None and bu is not None and bw < bu:
        print(f"判定: ✅ 採用 (加重{bw:.4f} < 均等{bu:.4f}) → 重み付き列を主表示に")
    else:
        print(f"判定: ❌ 却下 (加重が均等を下回らない) → 均等のまま(λ=0で安全縮退)")


if __name__ == '__main__':
    main()
