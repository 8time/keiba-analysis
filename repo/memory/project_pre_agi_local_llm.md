---
name: pre-agi-local-llm
description: pre_agiはOllamaローカルLLMで動くAUTOMATA仮想オフィス（newoffice3 Gemini版から移植・独立）
metadata: 
  node_type: memory
  type: project
  originSessionId: 167390d6-2f22-4f41-bcc2-f3e605727fd4
---

`C:\Users\kimnhaty\.gemini\antigravity\scratch\pre_agi` — newoffice3のガワを移植し、Ollama（ローカルLLM）で動くAUTOMATA AIエージェント環境。無料・無制限で全エージェントが毎ティック自律思考する。

- **newoffice3（Gemini版）は凍結** — 触らない。pre_agiは独立した新プロジェクト。
- LLMバックエンド: `server/bots/ollama-client.ts`（`LLMClient`インターフェース実装、既定モデル`qwen2.5:1.5b`、`http://localhost:11434`）。GeminiClientも同インターフェースで残存（代替可）。
- ブレイン `server/bots/agent-brain.ts` は `LLMClient` 汎用（`this.llm`）。
- デスク役割A収集/B分析/C討論（制約付きペルソナ: 保守=リスク指摘 / 直感=大穴）。課題なし時は自由行動のハイブリッド。
- 調査ツール: `keiba_analysis/scripts/agent_race_tool.py`（race_id→出馬表/指数/ペースをJSON。`@@@AGENT_JSON@@@`マーカー付き出力）を `research-tools.ts` がサブプロセス実行。
- 起動: `npm start`（サーバー）+ `npm run bots [-- url N]`（N体）。要Ollama起動＋`ollama pull qwen2.5:1.5b`。手順は `SETUP_OLLAMA.md`。
- Ollama未起動時は `quotaExhausted=true` でフォールバック脳（テンプレ）に自動切替。

**Why:** Gemini APIのレート制限/クォータでは「全エージェントが毎ステップLLM思考」というAUTOMATA本来の動作ができなかったため、記事と同じローカルLLM構成へ移行。
**How to apply:** モデル変更は`OLLAMA_MODEL`環境変数。体数は`npm run bots -- ws://localhost:2567 30`。関連: [[skyoffice-bot-integration]]
