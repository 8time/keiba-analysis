---
name: verified_ledger_write
description: 購入確定・見送りから data/ledger.db への自動記録（BetSync配線）
metadata:
  node_type: memory
  type: project
---

## 正本
- DB: `data/ledger.db`
- ロジック: `core/money.py` の `Ledger` クラス
- UI配線: `app.py` 💰 BetSync（ケリー基準）＋ 見送りタブ

## スキーマ（2026-08-30 確認）

### bets
`bet_id, ts, race_id, umaban, bamei, pred_prob, odds, stake, bet_type, settled, won, payout, gate_status, gate_lean, gate_severity, n_points, synth_odds, has_danger, has_value_ana, mood, deviation`

### skips
`skip_id, ts, race_id, reason, vscore, zone, mood, settled, would_hit, would_payout, note`

## どこから何を書くか

| 操作 | UI | 書き込み先 | 呼び出し |
|---|---|---|---|
| **購入確定** | 💰 BetSync → ケリー買い目リスト下の「✅ 購入確定（台帳に記録）」 | `bets`（stake>0 の行ごとに1行） | `Ledger.record_kelly_bets()` |
| **購入確定（進行系）** | 同ページ「➕ 次のレースを追加」（ケリー時） | 同上（サイレント。失敗しても UI は止めない） | 同上 |
| **見送り** | 同ページ「⏸ 見送り（台帳に記録）」 | `skips`（1レース1行） | `Ledger.record_skip()` |
| **見送り（手動）** | 🧘 自分の癖 → 🚫 見送り記録 | `skips` | `Ledger.record_skip()` |

### bets 1行の中身（ケリー購入）
- `race_id` … `bs_ev_feed` / `_kelly_bridge.json` の race_id（🏠 SRA 解析後に供給）
- `umaban` … 買い目文字列の先頭馬番（`7-4-12` → 7）。複式は `bamei` に全文
- `bamei` … 買い目ラベル（例 `7-4-12`）。精算時の combo 照合に使う
- `pred_prob` … ticket_line の的中率 `p`
- `odds`, `stake`, `bet_type`（券種）
- `gate_status/lean/severity` … `score_cache.read_gate(race_id)` から自動補完
- `n_points/synth_odds/has_danger/has_value_ana` … `score_cache.read_buy(race_id)` から自動補完

### skips 1行の中身（見送り）
- `race_id` … 同上
- `reason` … Gate=skip なら「🔴見送り推奨（Gate skip）」、停止中なら「今日は停止」、それ以外「見送り（BetSync）」
- `vscore`, `zone` … SRA の `_race_value_{race_id}` があれば `formation_stats.zone_of` で付与

## 落とし穴

1. **race_id が空だとボタンが disabled** … 🏠 SRA で Analyze してから BetSync を開く（`bs_ev_feed` / kelly bridge が必要）。
2. **購入確定は stake>0 の行だけ** … 見送り判定で stake=0 の行は bets に入らない（意図どおり）。
3. **二重記録** … 「購入確定」と「次のレースを追加」の両方を押すと同じ買い目が2回入る。通常はどちらか一方でよい。
4. **Streamlit キャッシュ** … 配線を直したのに UI が古い場合は Ctrl+C で完全停止 → `streamlit run app.py` 再起動。
5. **scripts/betting_ledger.py を Streamlit から import しない** … stdout 差し替えで壊れる。必ず `from core import money`。
6. **精算は別操作** … 購入記録だけでは ROI は出ない。📒 収支台帳 → 🔄 自動精算、または `Ledger.auto_settle_race()`。
7. **全頭 Brier 記録との混同** … SRA の「📒 台帳に即記録（全頭）」は較正用に全馬を100円で入れる別導線。実購入記録とは用途が違う。

## 検証手順

```powershell
# 1) スキーマ確認
python scripts/debug/_ledger_check.py

# 2) プログラムで1件ずつ書いて件数+1を確認
python scripts/verify_ledger_write.py

# 3) smoke
python tests/smoke.py
```

### UI 手動テスト
1. 🏠 SRA でレース解析 → 💰 BetSync（ケリー基準）
2. 買い目リストに1行以上入力 →「✅ 購入確定」→ `python scripts/debug/_ledger_check.py` で bets ≥ 1
3. 別レースで「⏸ 見送り」→ skips ≥ 1
4. 🏁 今日のダッシュボード → 実運用サマリに未精算件数が表示される
