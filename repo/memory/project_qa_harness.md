---
name: project_qa_harness
description: /goal・/loopでのQA土台。FEATURE_STATUS.md(正準表)＋tests/smoke.py(依存ゼロ・構文/import/関数/DB)
metadata: 
  node_type: memory
  type: project
  originSessionId: c3fa42fa-de5c-41c4-9911-b6156b6e7b9d
---

`/goal`・`/loop`で全機能を一つずつQAするための土台を新設(2026-06-23・commit a3eac09)。ユーザー要望「アプリ全機能をユーザーストーリー化→正準スプレッドシート→ループでテスト/記録/修正/再テスト」に対応。Streamlitはクリック自動化が困難なので「ロジック層＝core関数テスト＋構文/importスモーク」を実体にした。

**FEATURE_STATUS.md(リポジトリ直下)**: 機能ステータス正準表＝真実の源。列=ページ/機能・期待動作(ユーザーストーリー)・ステータス(✅検証済/🟢動作確認/🟡未確認/⬜未着手/🐞不具合)・検証根拠・最終確認。ループがこれを更新しながら進める。主要ページ(🏠SRA/🧹消去/🔍Scanner/🩸血統SP/💰BetSync/🐎Stress/🧠MAGI/🏇騎手/🤓N研/💾ロジック置場/📦保管庫)を種まき済み。

**tests/smoke.py(pytest不要・stdlibのみ・終了コード=失敗数)**: `python tests/smoke.py`(--quickでDB省略)。Phase1=py_compileで app.py/core/pages/scripts/utils 全.pyの構文検査。Phase2=中核15モジュールのimport。Phase3=検証済み関数の振る舞い(track_bias.heavy_fav_blood_mod/dirt_moisture_bloodtype・value_scanner.trio_lean・bet_filter.annotate_bgets🎯厳格化・trio_engine.build_formation)。Phase4=jravan.db/blood_dict.db主要テーブル行数。/loopはexit0/非0で次手判断可。

**初回成果=即バグ検出**: スモークが core/magi_retrospective.py:391,393,413,428 の`\"\"\"`(エスケープ三重引用符)構文エラーを検出→`"""`に修正。この崩れでモジュールがimport不能だった(MAGI回顧の対話機能discuss_interactive_retrospective)。172/172合格に。

**設計原則(重要)**: 新規ファイルのみ＝既存アプリコード不変で完全可逆(git revert/restore)。テストはread-only・ネット不要。ガードレール=①完了基準(全ストーリーpass)で無限ループを止める ②ループが未検証ロジックをでっち上げて修正しないよう検証台帳([[verified_tansho_roi_efficient]]等)を尊重 ③UX/見た目の最終判断は人間(スクショ)。今後の機能追加時はsmoke.pyのPhase3に検証済み関数チェックを足していく。関連:[[project_app_pipeline]]
