---
name: verified-spurt-pace-quality
description: 上がり3Fはスローペース由来だけ信頼(バテ差し検証)。前走スロー×上がりtop3=次走z+3.8〜8.5(3窓安定)/ハイ由来=z≈0(priced-in)。末脚の質を🐢⚡で表示補助。動画の0.3秒勝ち狙い目は却下
metadata: 
  node_type: memory
  type: project
  originSessionId: 64a070b3-be5e-4051-a8b3-047fbb5b0c0c
---

動画『真の上がり3ハロンの使い方』検証(2026-07・DB mae3f/ato3f)。

**Why(検証・scripts/spurt_pace_backtest.py)**:
- 核心の"バテ差し"は本物: 前走スロー×上がりtop3→次走複勝残差 z+8.5(16-23)/+6.0(24-25)/
  +3.8(26)=3窓安定。前走ハイ×上がりtop3→z+0.6/+0.7/-0.4=織込み済み(前が失速しただけ)。
  =上がり3Fはスロー由来だけ信頼できる。既存spurt_indexはペース無条件だったのでこれが精緻化。
- ペース判定=mae3f-ato3f(前半3F-後半3F)を(馬場×距離帯)内でz化。z>=0.5スロー/<=-0.5ハイ。
  凍結表data/pace_norm.json(train2016-23)。mae3fカバレッジ54%(芝中距離中心)。
- **動画の狙い目(スロー×先行×上がり1-2位×0.3秒勝ち)は却下**: z+0.3=priced-in。
  勝ち/着差フィルタが人気馬を選ぶだけ(スロー×先行×上がり1-2位のみならz+6.4だが着差追加で消滅)。
  「単勝回収率100%超え」は再現せず(全帯単ROI<100%)。
- 利益シグナルでなく軸信頼度/相手の質の道具(spurt_indexと同性質・単ROI 60-80%)。

**How to apply(実装済・表示のみ)**:
- core/pace_spurt.py: classify_pace(surface,kyori,mae3f,ato3f)→slow/high/mid、
  spurt_quality(ketto_num,before_key)→末脚top3走がスロー/ハイどちら由来か集計しtag。
- 強適ランキング末脚指数列: 🔥末脚top3馬に🐢(スロー質=信頼)/⚡(ハイ質=バテ差し注意)付与。
  買い目スコアは不変(表示補助)。列helpに検証注記。
- ペース判定は[[verified-lap33-theory]]のlap33(中盤-上がり)と同概念族。

関連: [[verified-spurt-index]](末脚は人気薄限定の妙味) [[verified-tenkai-priced-in]]
[[verified-prior-margin-debunk]](前走着差は俗説=今回も0.3秒勝ちは却下)
