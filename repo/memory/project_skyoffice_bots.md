---
name: skyoffice-bot-integration
description: SkyOffice仮想オフィスにkeiba_analysis連携AIエージェントボットを実装済み
metadata: 
  node_type: memory
  type: project
  originSessionId: d0fe5bcd-c998-4a66-95ac-e868d1730add
---

SkyOffice (C:\Users\kimnhaty\Documents\newoffice3) に競馬AIエージェントを住まわせる機能を実装。

- `server/bots/bot-runner.ts` — 3体のAIボット（血統師ケイ、データ屋マリ、逆張りのタク）
- Colyseus ヘッドレスクライアントとしてオフィスに接続、歩行・チャット・看板設置を自律実行
- keiba_analysisの実データ（レース履歴JSON、騎手傾向DB、スコアウェイト、オッズ履歴DB）を読み込んでエージェントの会話に反映
- `npm run bots`（スクリプト動作）/ `npm run bots:ollama`（Ollama LLM動作）で起動
- クライアントは `cd client && npm run build` でビルド済み、http://localhost:2567 で確認可能

**Why:** AUTOMATAプロジェクト（AI人工生態系）のコンセプトを、既存の仮想オフィスプロジェクトに統合する実験。
**How to apply:** ボット数の増減はBOT_CONFIGSを編集、データソースはKEIBA_ROOT環境変数で変更可能。
