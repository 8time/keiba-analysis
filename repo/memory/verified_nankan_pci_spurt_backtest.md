---
name: verified_nankan_pci_spurt_backtest
description: NAR(大井)でのAvgPCI/末脚指数/脚質分類バックテスト。6人気以下×末脚top3で複勝率+4.1pp(z2.35)を検証済み
metadata: 
  node_type: memory
  type: project
  originSessionId: b85681ee-81a0-4031-a84d-ca3e3c82da92
---

scripts/nankan_pci_legtype_backtest.py。core/nankan_scraper.pyのPastRunsブリッジで
NARでも計算可能になったAvgPCI・末脚指数(compute_spurt_index)・脚質分類(通過順比率)が、
JRAの検証済みエッジ([[verified_spurt_index]])と同じ方向に効くかを大井の実データで確認。

**標本(2026-07拡大版、ブルートフォース探索で5開催分を発見):**
大井5開催(kaiji01〜05・各5日、2026-04-13〜07-01)・263レース・3197頭。
各馬の過去走は「レース当日より前の日付」だけに絞り込み(リーク防止)。

**結果(6番人気以下・二標本比率検定):**
- 末脚指数レース内top3群: 39/316 = 12.3%
- 非top3群: 126/1535 = 8.2%
- 差分+4.1pp・z=2.35(有意水準z>2を突破・**検証済み**に格上げ)

JRA版(verified_spurt_index: 9.4%→13.4%)と同じ方向・近い絶対値の効果量。
初回パイロット(1開催21レース/253頭・n=24でz≈1.0=未確定)から標本を5開催
(263レース/3197頭)に拡大したことで統計的有意性を確認できた。

**AvgPCI/脚質分類のパイプライン健全性:** AvgPCI算出成功3133/3197頭(欠損少)。
脚質分布(差し899/追込1243/逃げ259/先行698)も偏りなく、パイプライン全体が正常に機能。

**標本拡大の手法(scripts/debug/nankan_id_bruteforce*.py):**
nankankeiba.comのrace_id(16桁=日付8+venue2+kaiji(開催回)2+day(日目)2+race2)を、
`/result/{id}.do`のHTTP 200/404を手がかりに(date, kaiji, day)を総当たりで特定。
1つの開催日が見つかれば、day±1日=カレンダー日±1日の関係を使って同一開催の
全日程を安価に特定できる(逆算不要)。[[project_nankan_scraper]]の自動IDマッピング調査
(近日分のみ discoverable)を補完する、過去開催の発見手法。
core/nankan_scraper.pyの`_fetch()`に最小リクエスト間隔0.4秒のスロットリングを実装済み
(IPブロック対策・恒久対応)。

**Why:** [[pilot_nankan_pci_spurt_backtest]](旧・未確定版)の後継。JRA-VANにNARデータが
無いため大量の過去データ収集手段が無かったが、ブルートフォースでnankankeiba.comの
開催構造を解明したことで検証可能な標本規模に到達した。

**How to apply:** 末脚指数レース内top3×6人気以下の穴救出ロジックをNARの消去エンジン/
穴馬ハンターにも展開する根拠が得られた(JRA同様の効果量・有意水準達成)。
標本をさらに拡大する場合は同じブルートフォース手法(kaiji/day総当たり)を他venue
(川崎/船橋/浦和=nankan内部コード21/19/18相当、要確認)にも展開できる。
