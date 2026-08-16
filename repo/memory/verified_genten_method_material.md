---
name: verified_genten_method_material
description: "「減点方式」資料(The Sculptor's Funnel)の消し条件を台帳照合→9割が既実装or検証済み否定。未検証4項目もLTRで不採用"
metadata: 
  node_type: memory
  type: project
  originSessionId: 423e3727-3223-4cca-9421-07a73ee06686
  modified: 2026-07-21T23:42:41.843Z
---

NotebookLM資料「当てるための足し算から、負けないための引き算へ / The Sculptor's Funnel ―― 減点方式競馬投資戦略」(2026-07-22にユーザーから提示)の全消去項目を検証台帳と突き合わせた結果。**目新しい情報はほぼ無い**。

**資料の枠組み自体が既にこのアプリの設計**: 「複数のマイナスが重なる馬から消す」=🧹消去クロス(重複数→絶対複勝率31.5→10.3%・[[project_elimination_engine]])、「穴馬には減点でなく加点を使う」=消去は人気馬用/穴は[[project_value_horse_hunter]]、「5頭前後まで絞る」=半分カット+🛟ボーダー3([[verified_keepone_border]])、「削りすぎたら見送る」=[[project_magi_consensus]]の見送り判定、「-4点ペナルティ」=app.pyの±1.5ファクター。**思想の追認であって新情報ではない**。

**資料の目玉が"検証済み否定"だったもの(再実装しない)**:
- 前走0.5〜0.6秒差負け → [[verified_prior_margin_debunk]](織込み済み・残差≈0。動画の0.6秒αも同じ)
- 距離適性(過去に同距離で大敗) → [[verified_distance_affinity_pricedin]](holdout z-0.06)
- 中3週以下の詰まったローテ → [[verified_axis_ng_claims]]で否定
- 斤量3kg以上増 → [[verified_rotation_weight_demerit]](±3kgは対称で弱く不採用)
- 500kg以上の大型馬 → [[verified_paddock_weight]]/[[verified_dirt_draw_bias]](priced-in)
- 極端な脚質(逃げ/追込)・小回り内枠の差し → [[verified_legtype_axis]](事前の習性脚質は軸をほぼ動かさない)
- 雨で内伸び馬場なのに外枠 → [[verified_emp_bias_danger]](順張り妙味ゼロ・逆張りもholdout崩落)

**既に実装済みだったもの**: 前走5着以下/高齢7歳+/半年休み明け/主戦騎手からの乗り替わり/前走逃げ/ハンデ戦の荒れ寄り/末脚(決め手)不足/厩舎の当コース成績/場×人気の1番人気危険度([[verified_blood_course]]=資料の1番人気ヒートマップと同族)。

**未検証だった4項目→LTRのauto_feature_searchに投入(2026-07-22)→全不採用**(フル版 train600,702/test7,052レース・ベースtest win@7=0.9366):

| 候補 | Δtest win@7 | Δval |
|---|---|---|
| cand_prev_futan(前走57.5kg以上の過酷さ) | -0.07pp | +0.12pp |
| cand_minarai_lost(前走減量騎手→今回通常=実質斤量増) | -0.16pp | -0.07pp |
| cand_futan_diff(今回−前走の斤量差) | -0.24pp | +0.07pp |
| cand_runs_since_rest(休み明けからの使い詰め戦数) | -0.26pp | +0.10pp |

**4本中3本が val では改善しているのに test では全滅** ＝ 典型的な過学習シグネチャを両窓ゲートが捕まえた形。片窓だけ見て採用していたら3本とも入れていた。scripts/auto_feature_search.py --candset cond7。

**⚠ 資料の数値の読み方(重要)**: 「小倉記念で複勝率3.7%」「【0-0-0-14】で全滅」等の具体例は**単一レース×多重条件の事後選択**で、母数が10〜20頭しかない。当プロジェクトが繰り返し踏んできた罠([[verified_prior_margin_debunk]]の多重検定過学習、[[verified_cushion_theory]]の名指し12頭が崩落)と同型。**資料の"データ例"は根拠として採用しない**。

**How to apply**: この資料が再提示されたら「思想は既に実装済み・個別条件は検証済みで大半が否定」と即答する。俗説隔離([[feedback_folk_signals_overbet]]と同じ扱い)。新規に拾う価値があったのは4項目だけで、それも検証で落ちた。
