---
name: verified_arare_wide_umaren
description: 荒れ帯(BA)の馬連/ワイド保険券 holdout 検証
metadata:
  node_type: memory
  type: project
---

# verified_arare_wide_umaren

## 背景

netkeiba ウマい馬券360件（全4R大荒れ・的中ショーケース）で的中者の主武器は

馬連16/ワイド14/3連複10/単勝10/3連単8 だった。事後選択サンプルのため

エッジの証明にはならず、本検証で事前ルールとして実配当 holdout にかけた。



## 設計

- 対象: JRA中央 8頭以上 / zone BA(主)・C(副次)

- 分割: train ≤20241231（参考）/ holdout ≥20250101（判定）

- 候補: ワイド/馬連 × 軸(Rank1・VH穴1位・人気1) + VH穴3頭ボックス

- 基準: 3連複 人気3-5-8（研究時代のBA最良形）/ 馬連 人気1×2-7（市場対照）

- 判定: A=holdout ROI≥90% かつ対基準CI下限>-3pp かつ年別一貫



## BA holdout 基準: 3連複3-5-8 ROI 84.2% 的中 40.8%



- **wide_rank1_rank26** → C: holdout 591R 的中27.2% ROI76.5% 対基準CI[-28.0,+12.8] 連敗21 — holdout ROI -7.8pp（3連複3-5-8未満）→ 見送り維持

- **wide_vh1_pop15** → B: holdout 590R 的中19.5% ROI85.0% 対基準CI[-18.8,+20.8] 連敗33 — baseline以上だが条件一部未達（ROI 85.0%・差CI (-18.76352485058539, 20.813912924298517)）

- **wide_vhbox3** → B: holdout 507R 的中5.9% ROI94.7% 対基準CI[-28.8,+56.4] 連敗68 — baseline以上だが条件一部未達（ROI 94.7%・差CI (-28.794568950556744, 56.4378321578354)）

- **umaren_rank1_rank26** → C: holdout 591R 的中11.7% ROI73.6% 対基準CI[-39.0,+21.2] 連敗46 — holdout ROI -10.7pp（3連複3-5-8未満）→ 見送り維持

- **umaren_vh1_pop15** → C: holdout 590R 的中8.6% ROI82.4% 対基準CI[-31.5,+30.2] 連敗89 — holdout ROI -1.8pp（3連複3-5-8未満）→ 見送り維持

- **wide_pop1_pop26** → C: holdout 591R 的中43.5% ROI74.4% 対基準CI[-23.8,+3.2] 連敗7 — holdout ROI -9.8pp（3連複3-5-8未満）→ 見送り維持

- **umaren_pop1_pop27** → C: holdout 591R 的中29.1% ROI75.6% 対基準CI[-23.3,+7.6] 連敗18 — holdout ROI -8.7pp（3連複3-5-8未満）→ 見送り維持



## C holdout 基準: 3連複3-5-8 ROI 76.6%（参考）



- wide_rank1_rank26 → B: 的中38.2% ROI82.9%

- wide_vh1_pop15 → B: 的中21.1% ROI83.2%

- wide_vhbox3 → C: 的中4.6% ROI68.1%

- umaren_rank1_rank26 → C: 的中19.6% ROI75.0%

- umaren_vh1_pop15 → B: 的中11.4% ROI89.2%

- wide_pop1_pop26 → B: 的中56.0% ROI79.5%

- umaren_pop1_pop27 → B: 的中39.5% ROI79.5%



## 解釈（結論）

1. **荒れ(BA)=見送りを維持**。全候補 ROI<100%。最高の wide_vhbox3 (94.7%) も
   CI[58-138]・連敗68・2025:105%/2026:75% で年間ブレが激しく実運用不可。
2. BAで「どうしても買うなら」の least-bad は依然 **3連複 人気3-5-8**
   （ROI 84.2%・的中40.8%・連敗9）。wide_vh1_pop15 (85.0%) とROIは互角だが
   的中率 40.8% vs 19.5%、連敗 9 vs 33 で体験が違いすぎる。
3. 360件の「的中者の主武器は馬連/ワイド」は**事後選択の幻影**。
   荒れたレースでは誰かの馬連/ワイドが必ず光るが、事前ルール化すると
   見送りにも既存形にも統計的に勝てない。
4. Cゾーン umaren_vh1_pop15 (89.2%) は一見良いが、真のincumbentは
   Rule B（holdout 87.7%・verified_bettype_selector_phase2）で、差は+1.5ppの
   ノイズ範囲。的中11.4%・連敗38で券種追加の複雑さに見合わない。
5. 軸の質では VH穴軸 > Rank軸・人気軸 が train/holdout で一貫
   （wide_vh1 89.7/85.0% vs wide_rank1 74.3/76.5% vs wide_pop1 75.8/74.4%）。
   VH穴馬の解像度が高い既存知見と整合。

## 再現

```

python scripts/arare_wide_umaren_verify.py

```
