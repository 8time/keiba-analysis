---
name: verified-makuri-priced-in
description: マクリ指数(3→4角の位置押し上げ)は独立エッジ無し=priced-in。末脚(上がり速度)と違い展開/位置なので市場織込み済み。列追加せず・再提案しない
metadata: 
  node_type: memory
  type: project
  originSessionId: ddc31c7d-ff26-4821-8a37-bdbceb363b6b
---

ユーザー「末脚指数はあるのにマクリ指数はないの?」→検証(scripts/makuri_backtest.py)。

**マクリ指数の定義**: push = (corner3/頭数 − corner4/頭数) の直近5走平均(リーク無し・過去走のみ)。
正=3→4角で前へ押し上げ(マクリ傾向)。c3&c4カバレッジ83%。

**検証結果(train2021-24/holdout2025・人気補正残差z):**
- レース内マクリ指数top3 × 人気帯: fav(1-3)+0.27pp/mid(4-5)+0.89pp/**long(6+)+0.37pp(z+1.6)/holdout+0.59pp(z+1.3)**=全帯z<2。
- **決定的**: long(6+)でtop3(+0.37/+0.59)が『非top3(=コーナー履歴ありの他の長shot)』(+0.51/+0.68)を**上回らない**=マクリ強でも他の長shotに勝てない。
- 小回り限定説(函館/福島/中山/小倉)も検証: 小回り×6+×マクリtop3=+1.17pp(z+3.1)/holdout+1.25pp(z+1.7)だが、同スライスの非top3も+0.90/+0.80あり増分は+0.3pp・holdout z+1.7で非有意。大回りは-0.08〜+0.24でゼロ。

**結論=非採用(priced-in)。列追加せず・再提案しない。**
末脚指数([[verified_spurt_index]]: 6番人気以下×末脚top3で複勝13.2%vs9.4%=明確エッジ)との違い=
末脚は"上がり3F=実速度"で残差が残る。マクリは"位置押し上げ=展開/脚質"で、展開恩恵/脚質は
市場に織込み済み([[verified_tenkai_priced_in]][[verified_legtype_axis]])と同型。テン速力却下
([[project_elimination_engine]]の残り列検証)と同じ教訓=位置系は消去も軸も予測もエッジ無し。
