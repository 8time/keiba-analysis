# Project Context
- Python 3.13 / Streamlit / Windows環境
- 文字コード：常にUTF-8（BOMなし）
- スクレイピング：Scrapling + Playwright
- OCR：EasyOCR（置き換え禁止）
- データソース：netkeiba.com

# ファイル構造
```
keiba_analysis/
├── app.py                    # Streamlitメインアプリ（エントリポイント）約270KB
├── create_session.py         # Playwright認証セッション生成スクリプト
├── data_schema.md            # データ構造の仕様書
├── requirements.txt          # 依存ライブラリ
│
├── core/                     # メインロジック
│   ├── scraper.py            # netkeiba HTMLスクレイピング（fetch_robust_html等）
│   ├── calculator.py         # オッズ計算・指数計算
│   ├── odds_tracker.py       # オッズ変動トラッキング（OddsTrackerクラス）
│   ├── odds_analyzer.py      # オッズ分析（OddsAnalyzerクラス）
│   ├── odds_logger.py        # オッズログ保存
│   ├── history_manager.py    # レース履歴管理（race_history.csv の読み書き）
│   ├── simulator_engine.py   # シミュレーション計算
│   ├── theory_rmhs.py        # RMHS理論実装
│   ├── vision_analyzer.py    # Gemini Vision APIでのOCR（VisionOddsAnalyzer）
│   ├── local_vision_analyzer.py # EasyOCRでのローカルOCR（LocalVisionOddsAnalyzer）
│   └── kaggle_client.py      # Kaggle Notebook連携（KaggleChatClient）
│
├── utils/
│   ├── fetch_helper.py       # シンプルHTTPフェッチユーティリティ
│   └── adv_fetch_helper.py   # Scrapling DynamicFetcher（fetch_robust_html実装）
│
├── scripts/
│   ├── odds_tracker.py       # オッズトラッカー実行スクリプト
│   ├── race_position_scanner.py # レース着順スキャン
│   ├── track_odds_runner.py  # オッズ追跡ランナー
│   ├── scrapling_jra.py      # JRAスクレイピングテスト
│   ├── test_odds_analyzer.py # オッズ分析テスト
│   ├── verify_refactoring.py # リファクタリング検証
│   └── debug/                # デバッグ・一時テストスクリプト
│
├── data/
│   ├── odds_history.db       # SQLiteオッズ履歴DB
│   ├── kaggle_interactions.json
│   └── history/              # レース履歴JSONファイル
│
└── （ルートの動的生成ファイル）
    ├── race_history.csv      # レース解析結果（app.pyが生成・参照）
    ├── betsync_data.json     # ベットシンク設定永続化
    ├── saved_logic_notes.json # ロジックメモ永続化
    ├── auth_session.json     # Playwright認証セッション（gitignore推奨）
    └── labo_session.json     # Playwright Labo認証セッション（gitignore推奨）
```

# 禁止事項
- スクレイピング処理をOCRに置き換えない
- 既存の関数シグネチャを変更しない
- requirements.txtにない新ライブラリを追加しない

# よくある問題と解決策
- 文字化け：response.encoding='utf-8'を明示。または content.decode('euc-jp') などの適切なデコード。
- HTML取得失敗：DynamicFetcherのタイムアウトを30秒に延長
- Streamlit再描画ループ：st.session_stateで状態管理

# 過去の失敗事例
- requestsでnetkeiba取得→ボット検知でブロックされる（fetch_robust_htmlを使用すること）
- response.encodingを指定しない→文字化けで◆になる
- 人気列をX座標固定で取得→ブレてNoneになる（オッズの右隣の整数を取得するロジックを使用）
- shutuba_past.htmlの解析ミス→JRAの過去走表はクラス構造が特殊（UmabanがWakuクラス内にある等）

# 実験その３：馬番ポジション・パターンスキャナー 新機能 (Pro v2.0+)
- **全開催場スキャン (All-Venue Scan)**: 複数競馬場のURLをまとめてスキャンする。これにより、場を跨いだ厩舎の「●シグナル」が自動判定可能。
- **当日1回乗り騎手 (J1R)**: 同一開催日・同一場で1レースのみ騎乗する騎手を検出し、`J1R` マークを付与する。
- **◎●シグナル統合スコアリング**: 配置パターンに加え、騎手(J◎)・厩舎(T◎/T●)の特殊マークをスコアに加算する。
- **UnicodeEncodeError (cp932) 対策**: 実行環境に関わらず `sys.stdout` 等を UTF-8 に固定する処理を各スクリプトに実装済み。
