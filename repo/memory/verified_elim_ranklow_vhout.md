---
name: verified-elim-ranklow-vhout
description: 消去クロス新条件「実力Rank下位56%×穴ハンター圏外」は既存の不人気より効率が良い
metadata: 
  node_type: memory
  type: project
  originSessionId: 8193f2c8-eae5-432d-9103-99a37077d415
  modified: 2026-08-07T03:28:34.141Z
---

ユーザー提案「ランク下位の馬で全体56%かつ穴馬ハンターの🎯精鋭/🕸️広域網にも
含まれない馬」を**実装前に検証**してから配線した。
scripts/elim_ranklow_vhout_backtest.py

## 検証結果（vh学習期間外の2025-2026・67,885頭）
| 条件 | 該当率 | 3着内率 | 3着内馬の取りこぼし |
|---|---|---|---|
| **Rank下位56% かつ vh圏外** | **29.1%** | **3.1%** | **4.3%** |
| 【既存】人気下位34%(poplow) | 31.4% | 3.9% | 5.7% |
| Rank下位56% のみ | 50.2% | 10.9% | 25.9% |
| vh圏外 のみ | 36.4% | 3.4% | 5.9% |

**既存のpoplowより少なく消して取りこぼしも少ない**（29.1%/4.3% vs 31.4%/5.7%）。
Rank単独では3着内率10.9%で消せない。**交差させて初めて効く**のは
botcross/multiweakと同じ構造。全期間(48万頭)でも同じ傾向。

## 実装
`core/elim_cross.py` に `rklow_vh`（ラベル「実力下位×圏外」）を追加。
- **UNVERIFIED に登録**＝BAND(推定複勝率)の較正には入れない。
  実力Rank(LTR)も穴ハンター(vh2)も**市場情報を内包**するので独立弱点ではない。
  人気そのものを重複に足すと重複が人気を追うだけになる（poplow/jlowと同じ理由）。
- **CAUTION_KEYS に登録**＝「過信しない列」として明るい赤背景×黄文字で表示。

## 実装上の注意
- Rankは**消去エンジンの score 降順**（`_edf`が既にソート済みなので index+1）。
- vh tierは `newspaper.load_consensus()` の `aim.vh_tier` から直接引く。
  session_state経由にすると**SRAを開いていない時に取れない**（消去フィルターは
  独立ページなので、SRA前提の実装にしてはいけない）。
- 「下位56%」は `len - max(1, int(len*0.56))` 番目以降。

[[project_elimination_engine]] [[project_value_horse_hunter]]
