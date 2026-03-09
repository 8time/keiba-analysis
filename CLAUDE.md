# Project Context
- Python 3.13 / Streamlit / Windows環境
- 文字コード：常にUTF-8（BOMなし）
- スクレイピング：Scrapling + Playwright
- OCR：EasyOCR（置き換え禁止）
- データソース：netkeiba.com

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
