# 機能ステータス正準表（QAループの真実の源）

`/goal`・`/loop` でこの表を更新しながら全機能を一つずつ検証する。
ステータス: ✅検証済(BTあり) / 🟢実装済(動作確認済) / 🟡実装済(未確認) / ⬜未着手 / 🐞不具合
テストの実体 = `python tests/smoke.py`（ロジック＋構文スモーク・依存ゼロ）。UX/見た目は人間確認。

| ページ/機能 | 期待動作（ユーザーストーリー） | ステータス | 検証/根拠 | 最終確認 |
|---|---|---|---|---|
| 🏁 今日のダッシュボード(司令塔) | 既定ランディング。今日の買える/軸注意/見送り(Scanner gate)＋Gate別ROI/最大DD/回顧すべき負け(BetSync台帳)を1画面 | 🟢 | score_cache.recent_gates＋money.report/roi_by_gate/max_drawdown/loss_breakdown | 2026-06-24 |
| 🏠 Single Race Analysis | レースID/URL入力→出馬表取得→強適Ranking表示 | 🟡 | — | — |
| ├ NAR(地方競馬)PastRunsブリッジ | nankankeiba.com過去走→PastRuns形式変換でPCI/展開マップ/脚質分類をNARでも有効化 | ✅ | [[project_nankan_scraper]]+[[verified_nankan_pci_spurt_backtest]](大井5開催263R/3197頭・z2.35) | 2026-07-02 |
| ├ NAR会場プロファイル(大井/川崎/船橋/浦和) | 場コード修正(42/43/44/45=浦和/船橋/大井/川崎)＋距離別枠順バイアス/砂質/雨天バイアス/リーディング | 🟢 | [[project_nankan_scraper]] | 2026-07-02 |
| ├ NAR軸/シグナル較正 | ①軸=NAR実測POP_FUKU_NAR(1番人気78.7%>JRA70.1%)で過小評価修正 ②🔬シグナル列を南関でも機能(scrape_raceはrace_id取得でNAR自動判定) ③LTR(JRA学習)はNAR分布外で抑制 | 🟢 | axis_marks_nar/_fetch_daily_signals(NAR分岐)/LTR NARゲート。診断=NAR1番人気複勝率78.7%実測 | 2026-07-02 |
| ├ 🛡️BattleScore乖離セーフティネット NAR比例化 | 中央固定top3/top7→NAR出走頭数比例(seed≈3/16・line≈40%)、中央側は完全不変 | ✅ | [[project_nar_recall_proportional]] | 2026-07-02 |
| ├ 強適Ranking Table | 予測スコア/戦闘力/補正T/LTR/適性を列表示・列順保存 | 🟢 | CorrectedT/LTRヘッダ修正(077cfeb/ab0d15f) | 2026-06-23 |
| ├ 🎯軸馬候補◎〇▲ | 人気別複勝率＋圧勝🔨＋危険人気Vetoで軸提示(危険は降格/⚠) | ✅ | [[verified_ohtani_trap]]＋danger_gate(P0) | 2026-06-23 |
| ├ 🔵補正T | 直近7走×同馬場の最高/100・top3に🔵 | ✅ | [[verified_corrected_time]] | — |
| ├ 🤖検証AI(LTR) | LambdaRankで勝ち馬を上位7に(recall@7) | ✅ | recall@7=0.936 | — |
| ├ 展開MAP/Vマトリクス | テン速力でペース想定・隊列・荒れ寄り判定 | 🟡 | 展開恩恵はpriced-in([[verified_tenkai_priced_in]]) | — |
| ├ 騎手・厩舎脚質傾向を隊列に反映(表示用) | jockey_tactics/trainer_tactics(逃げ先行率)→道中ポジションprior小重み。corner履歴無い馬(NAR/新馬)で効くフォールバック | 🟢 | pace_map.tactics_forward(w0.15)。**表示精度のみ・エッジ主張なし**(ペース圧力の荒れ予測は⑧と重複と検証済) | 2026-07-02 |
| ├ 🎯3連複おすすめエンジン | 決着タイプ判定→本線/②パターン＋lean連動の可変点数(本線8/②10/中立8)＋本線トリガミ警告 | 🟢 | trio_lean配線＋可変点数(4d81226) | 2026-06-24 |
| ├ ●大穴/⚠荒れ寄り(オッズ本命不在) | 決着タイプ判定にコンピ大穴の単勝オッズ等価フラグ(fav1/上位拮抗/live30)を表示。穴相手戦略の適用先を選ぶレース選択器 | ✅ | [[verified_arare_entropy]](2025 z10.9・大穴z5.5/2026 z8.0・ハンデ/16頭と独立)。value_scanner.no_favorite_flag / scripts/arare_entropy_backtest.py | 2026-07-02 |
| ├ 🎯妙味度/根拠 | 価格帯×穴脚エッジで🎯・根拠ラベル表示 | ✅ | [[verified_tansho_roi_efficient]] | 2026-06-23 |
| ├ 🎯馬連/馬単エンジン | 高配当検知・軸流し＋危険軸Veto(自動軸が危険1番を回避) | 🟢 | pair_gate_backtest#6(Veto前後ROI不変=安全装置・参考ツール) | 2026-06-24 |
| ├ 🎰EV配分/多肢ケリー | EV>1馬に配分・破産確率 | 🟡 | EVは未検証目安。精算30件未満+1/4ケリー超で警告表示追加(2026-07-02) | — |
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
| ├ 🧪 検証候補→ロジック置き場登録 | 回顧タグ(3回以上・非俗説)を【検証候補NNNNN】でロジック置き場に番号付き永続化。**自動実装せず**人間レビュー→Claude→holdout検証の入口 | 🟢 | カード7+要望・core/verify_queue.py(番号/重複防止smoke)+hypothesis_schema(俗説隔離)+magi_chat.hypothesis_export | 2026-07-02 |
| 🏛️ 集合知(エージェント掲示板) | LLMペルソナがDB実データで討論→自信度重み合議 | 🟡 | pages/collective.py | — |
| ├ 🧠 Brier加重合議 | 過去成績(◎的中)で当たらないペルソナの票を減衰(λ加重)。台帳n<50は均等縮退で安全稼働 | 🟢 | カード8・agent_forum.agent_weights/weighted_consensus(λ0=均等・空台帳=均等をsmoke担保)+scripts/forum_weight_backtest.py | 2026-07-02 |
| ├ 🔗 エージェント相関診断 | 人格の予想相関で冗長/独立を可視化(アンサンブルは低相関でのみ効く)。結果不要=予想だけで測定。高相関=多様性なし警告 | 🟢 | agent_forum.agent_pick_correlation(◎3/○2/▲1スコアのPearson・smoke)。[[project_magi_consensus]]偽アンサンブルの罠を数値化 | 2026-07-02 |
| ├ 👥 人格・情報を選ぶ | 人数自動でなく特定人格を選択(各人格=情報の切り口=血統/展開/騎手/オッズ…)。切り口の重複=相関警告で脱相関を誘導 | 🟢 | agent_forum.agent_roster/agents_by_ids(smoke)。相関診断とセットで多様な集合知を組む | 2026-07-02 |
| 💰 BetSync 回顧(⑥) | 負けの自動分類=運用事故(Gate無視/危険軸/危険人気含み)＋設計ミス(盲目②/本線点数過多/トリガミ設計)＋想定内ブレ。買い目メタは3連複エンジンから自動補完 | 🟢 | money.classify_loss/loss_breakdown＋score_cache.write_buy/read_buy | 2026-06-24 |
| 🏇 騎手分析Pro | 当場/当距離/黄金ライン等 | 🟡 | [[project_jockey_jv]] | — |
| ├ resolve_horse同名馬誤マッチ修正 | 引退済み同名馬への誤マッチをbefore_key未指定時のみ最終出走年ガードで排除+trainer_code='00000'(調教師不明プレースホルダ・101万行共有)をNoneに丸め、無関係な調教師同士の同一集計表示バグを修正 | ✅ | [[project_jockey_jv]] | 2026-07-02 |
| 🤓 N氏の研究室 | 馬番ポジションスキャナ等 | 🟡 | — | — |
| 💾 ロジック置き場 | ロジックメモ永続化 | 🟡 | — | — |
| 📦 データ保管庫 | レース履歴管理 | 🟡 | — | — |

## 既知の制約（テストで"仕様"として扱う）
- 血統: JV-VANマスタ2023-07凍結→2024-26馬はnetkeibaバックフィル中([[project_jravan_setup]])。ライブは scraped sire優先で発火。
- 買い方でROIは控除を抜けない（追い上げ/穴厚/エッジ流し全て✗）= 馬選別でなく見送り/点数/券種で守る([[verified_tansho_roi_efficient]])。

## 検証済み却下（再提案・再実装しない・恒久決着）
- **PCIは完全終了**（2026-07-02・scripts/pci_course_shape_backtest.py）: 単体PCI乖離=priced-in([[verified_pci_pricedin]])、巻き返し穴=誤り([[verified_comeback_overbet]])に続き、動画の「PCI傾向×コース形状(O字/U字)」交互作用も holdout2025で C=+0.30pp/z=+0.20（train z0.65・2026 z1.65）とゲートz2.0未達。PCI由来のエッジは軸・相手・消去いずれも無し。
- **当日バイアス逆張り(危険人気)のrealtime強化**は却下（2026-07-02・カード2・scripts/intraday_bias_backtest.py）: pooled z-3.8は楽観的でholdout2025 z-1.77/2026崩落。既存danger_popular_innerは弱fadeとして残すが強化しない([[verified_emp_bias_danger]])。
- **ボーダー3のフラグ消去による代替**は却下（2026-07-02・カード3・scripts/elim_frontier_backtest.py）: フラグは人気に織込み済みでW>0はこぼし悪化。ボーダーは代替不能・撤去しない([[verified_keepone_border]])。
- **馬主・馬主×厩舎・地方中央使い分けは織込み済み**（2026-07-02・カード4・scripts/owner_roi_backtest.py+venue_switch_backtest.py）: 馬主=高-低コントラストz-0.52/+0.92、前走NAR(地方帰り)=holdout z-1.91(むしろ過剰人気・ROI42-59%)。全てpriced-in。厩舎全体勝率と同型([[verified_owner_pricedin]])。
