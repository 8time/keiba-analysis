---
name: logic-backlog
description: アプリ左メニュー「ロジック置き場」(saved_logic_notes.json・17件)のブラッシュアップ案バックログ
metadata: 
  node_type: memory
  type: project
  originSessionId: 167390d6-2f22-4f41-bcc2-f3e605727fd4
---

keiba_analysisアプリ左メニュー「💾ロジック置き場」= `saved_logic_notes.json`（17件のメモ。各 {memo, ag_prompt, date}）。再構築時に参照するブラッシュアップ案の倉庫。読了済み。

**既存①〜④と直結:** note4シミュレート=①backtest / note12血統(JBIS,PyPedal,ニックス,系統,条件別加減算)=③blood_dict / note16買い方(フォーメーション・合成オッズ)・note17MAGI改造(軸/買い方/切る馬を相談)=②kelly・券種 / note10「来ないパターン学習でAI消し判断」=④self-improve＋消し馬。

**パイプライン組込候補:** note1=波乱度(固い/通常/波乱/大荒れ)を**オッズ分散エントロピー・MAGI不一致度・期待値ズレ**で定量化（現状当たらない問題の解・低コスト）。note2得意距離、note14連続3着なし騎手ランク=特徴量。note3「ROBOTIP(ウマニティ)を実験場に黄金ウェイト発見→影響率へ輸入」。note5=やること残り(枠順×影響率連動・ダート内枠ストレス・下位精度UP=ミドル/穴・時系列オッズ・3連複人気オッズ・騎手補正・資金管理残3・穴馬用テーブル・3連単マギ)。

**新規技術(未導入・要検討):**
- **TimesFM**(Google時系列基盤・CPU可200M・`pip install timesfm`): オッズ変動予測(既存`data/odds_history.db`活用)/馬トレンド補正(BattleScore)/ペース予測。Phase1=オッズ予測が即効。
- **FLAIR**(github TakatoHonda/FLAIR・共変量高速・走破時計を確率分布予測→分布の重なりで波乱度): TimesFMより競馬向きの可能性。
- **MiroFish**(github 666ghj/MiroFish・群知能sim): MAGIを3→多数体に拡張、予測の収束度で波乱度。Win11はWSL2推奨・要ローカルLLM。
- note15 SPAIA/WARP AI=期待値追求・Dixon-Coles思想。note7 Kaggle血統(2010-2025)既導入＋他データ検討。

**正直な所感:** 競馬データは開催不定期・馬ごとデータ数バラバラでTimesFM/FLAIRはそのまま扱いにくい→直近5-10走を固定長シーケンス化が前提。順序は**まずLTR(rank:ndcg)で土台→TimesFM/FLAIRはトレンド補正の特徴量として後段**が安全。波乱度のエントロピー定量化(note1)は最優先の低コスト改善。関連: [[app-rebuild-pipeline]] [[kyoteki-score-rebuild-goal]]
