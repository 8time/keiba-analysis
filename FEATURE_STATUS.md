# 機能ステータス正準表（QAループの真実の源）

`/goal`・`/loop` でこの表を更新しながら全機能を一つずつ検証する。
ステータス: ✅検証済(BTあり) / 🟢実装済(動作確認済) / 🟡実装済(未確認) / ⬜未着手 / 🐞不具合
テストの実体 = `python tests/smoke.py`（ロジック＋構文スモーク・依存ゼロ）。UX/見た目は人間確認。

| ページ/機能 | 期待動作（ユーザーストーリー） | ステータス | 検証/根拠 | 最終確認 |
|---|---|---|---|---|
| 🏁 今日のダッシュボード(司令塔) | 既定ランディング。今日の買える/軸注意/見送り(Scanner gate)＋Gate別ROI/最大DD/回顧すべき負け(BetSync台帳)を1画面 | 🟢 | score_cache.recent_gates＋money.report/roi_by_gate/max_drawdown/loss_breakdown | 2026-06-24 |
| 🏠 Single Race Analysis | レースID/URL入力→出馬表取得→強適Ranking表示 | 🟡 | — | — |
| ├ 強適Ranking Table | 予測スコア/戦闘力/補正T/LTR/適性を列表示・列順保存 | 🟢 | CorrectedT/LTRヘッダ修正(077cfeb/ab0d15f) | 2026-06-23 |
| ├ 🎯軸馬候補◎〇▲ | 人気別複勝率＋圧勝🔨＋危険人気Vetoで軸提示(危険は降格/⚠) | ✅ | [[verified_ohtani_trap]]＋danger_gate(P0) | 2026-06-23 |
| ├ 🔵補正T | 直近7走×同馬場の最高/100・top3に🔵 | ✅ | [[verified_corrected_time]] | — |
| ├ 🤖検証AI(LTR) | LambdaRankで勝ち馬を上位7に(recall@7) | ✅ | recall@7=0.936 | — |
| ├ 展開MAP/Vマトリクス | テン速力でペース想定・隊列・荒れ寄り判定 | 🟡 | 展開恩恵はpriced-in([[verified_tenkai_priced_in]]) | — |
| ├ 🎯3連複おすすめエンジン | 決着タイプ判定→本線/②パターン＋lean連動の可変点数(本線8/②10/中立8)＋本線トリガミ警告 | 🟢 | trio_lean配線＋可変点数(4d81226) | 2026-06-24 |
| ├ 🎯妙味度/根拠 | 価格帯×穴脚エッジで🎯・根拠ラベル表示 | ✅ | [[verified_tansho_roi_efficient]] | 2026-06-23 |
| ├ 🎯馬連/馬単エンジン | 高配当検知・軸流し＋危険軸Veto(自動軸が危険1番を回避) | 🟢 | pair_gate_backtest#6(Veto前後ROI不変=安全装置・参考ツール) | 2026-06-24 |
| ├ 🎰EV配分/多肢ケリー | EV>1馬に配分・破産確率 | 🟡 | EVは未検証目安 | — |
| 🧹 消去フィルター | 緑枠ワークフロー→消去エンジン→クロス→フォーメーション | 🟢 | ワークフロー常掲(2af5fc1) | 2026-06-23 |
| ├ 強適消去エンジン | 半分消去＋穴1頭救出＋危険人気馬検知 | ✅ | [[project_elimination_engine]] | — |
| ├ 消去クロステーブル | 来にくさフラグ重複→複勝率低下の可視化 | ✅ | 重複数で単調低下 | — |
| ├ 3連複フォーメーション | ✅残し→軸/対抗、🎯穴→押さえ自動配置 | 🟢 | kf_form警告修正(2ca7a8c) | 2026-06-23 |
| ├ netkeibaレースリンク | 入力欄直下に出馬表リンク | 🟢 | (2ca7a8c) | 2026-06-23 |
| 🔍 Race Scanner (Batch) | 日付→全レース取得→『買える順』(✅買える/⏸見送り/△様子見)で並替 | 🟢 | ③Gate化・決着タイプ強化版 | 2026-06-24 |
| 👁️ パドック解析 | パドック/調教の観察タグ台帳(scene切替・記録→精算→タグ別複勝率/単ROI/ベース比)。タグ説明凡例＋画像/動画の任意添付。主観cueの個人検証装置 | 🟢 | core/paddock_ledger.py(lib不要JSON台帳・scene=paddock/training・TAG_HELP・save_media)。定量は検証済([[verified_paddock_weight]])で除外。添付=Gemma 4 12B(動画対応)自動タグ(phase B)の答え合わせ用 | 2026-06-24 |
| 🩸 血統SP | レースID→血統スコア順＋道悪判定／種牡馬しらべ | 🟢 | 道悪判定追加・小数第一位 | 2026-06-23 |
| 💰 BetSync(資金管理) | ガードレール/多肢ケリー/破産確率/台帳・Brier＋Gate判定別ROI(#8) | 🟢 | [[project_betsync_money]]＋roi_by_gate | 2026-06-24 |
| 🐎 Stress Analyst | 馬体/馬場×血統の減衰(リーク無し版) | ✅ | [[verified_stress_debuff]] | — |
| 🧠 MAGI回顧 | 3人格おしゃべり学習／合議ゲート | 🟡 | [[project_magi_oshaberi]][[project_magi_consensus]] | — |
| 💰 BetSync 回顧(⑥) | 負けの自動分類=運用事故(Gate無視/危険軸/危険人気含み)＋設計ミス(盲目②/本線点数過多/トリガミ設計)＋想定内ブレ。買い目メタは3連複エンジンから自動補完 | 🟢 | money.classify_loss/loss_breakdown＋score_cache.write_buy/read_buy | 2026-06-24 |
| 🏇 騎手分析Pro | 当場/当距離/黄金ライン等 | 🟡 | [[project_jockey_jv]] | — |
| 🤓 N氏の研究室 | 馬番ポジションスキャナ等 | 🟡 | — | — |
| 💾 ロジック置き場 | ロジックメモ永続化 | 🟡 | — | — |
| 📦 データ保管庫 | レース履歴管理 | 🟡 | — | — |

## 既知の制約（テストで"仕様"として扱う）
- 血統: JV-VANマスタ2023-07凍結→2024-26馬はnetkeibaバックフィル中([[project_jravan_setup]])。ライブは scraped sire優先で発火。
- 買い方でROIは控除を抜けない（追い上げ/穴厚/エッジ流し全て✗）= 馬選別でなく見送り/点数/券種で守る([[verified_tansho_roi_efficient]])。
