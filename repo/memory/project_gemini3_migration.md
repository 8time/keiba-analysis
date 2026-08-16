---
name: project_gemini3_migration
description: Gemini 3.x移行。temperature廃止/thinking_budget→thinking_level。AIコメント欄で実機検証済み、残り6ファイルは未着手
metadata: 
  node_type: memory
  type: project
  originSessionId: 423e3727-3223-4cca-9421-07a73ee06686
  modified: 2026-07-22T16:04:29.856Z
---

Gemini 3.6 Flash / 3.5 Flash-Lite のGA（ユーザー提供情報・2026-07-22時点）に伴うAPI移行。**(C)方針＝影響の小さい1ファイルで検証してから残りへ**で進行中。

**Gemini 3.x のAPI変更（今後の全モデルに適用）**
- `temperature` / `top_p` / `top_k` → **非推奨**。現在は無視され、**将来世代では400エラー**
- `thinking_budget` → **`thinking_level`**（文字列 `MINIMAL`/`LOW`/`MEDIUM`/`HIGH`）。**完全OFFは存在しない**
- モデルターンの事前入力（prefill）→ **400エラー**
- `candidate_count` → 3.xで廃止
- 新モデル: `gemini-3.6-flash`（$1.50/$7.50・既定thinking=medium）/ `gemini-3.5-flash-lite`（$0.30/$2.50・既定minimal・**ペルソナ一貫性と表形式データ処理が向上**）

**実機で確認済み（2026-07-23）**: `google-genai 1.68.0` は既に `thinking_level` 対応済みで**SDK更新は不要**。`ThinkingLevel` enum = UNSPECIFIED/LOW/MEDIUM/HIGH/MINIMAL。`thinking_level='LOW'` + `response_mime_type='application/json'` で **JSONは思考テキスト混入なくクリーンに出る**（移行前の最大リスクだった「3.xは思考を切れないのでJSONが壊れるのでは」は杞憂だった）。ただし**思考トークンが `max_output_tokens` を消費する**ため枠は多めに要る（700では途中で切れた→1500に）。

**⚠ thinking_budget と thinking_level は排他。「置換」すると壊れる（実測）**

| モデル | `thinking_budget=0` | `thinking_level='MINIMAL'` |
|---|---|---|
| gemini-2.5-flash / 2.5-flash-lite | **OK** | **400** |
| gemini-3.1-flash-lite-preview | OK | OK |
| gemini-3.5-flash-lite / 3.6-flash | **400** | **OK** |

MAGIは2.5系と3.1系を**混在＋相互フォールバック**するため、一括置換だと2.5系が即死する。よって **`core/gemini_compat.py`（新規）** を作り、モデル名から世代を判定して振り分ける方式にした。`apply_thinking(cfg, types, model_name, level=)` を**モデルごとに呼ぶ**のが使い方（cfgをループ外で1回作る実装は要改造。`magi_chat._gen`はそのために組み替えた）。判定は `gemini-<major>.<minor>` を正規表現で読み、**3.5以上=level / 未満=budget / 未知の新モデル=level**（Googleの移行方向に倒す）。

**適用済み（2026-07-23・実機で回帰テスト通過）**
- `core/gemini_compat.py`（新規）
- `core/magi_chat.py` / `core/magi_retrospective.py` / `core/magi_system.py` … `thinking_budget=0`直書き→ヘルパー呼び出し
- `core/newspaper_commentary.py` … 自前の二重実装をヘルパーへ寄せた（[[project_newspaper_ai_commentary]]）

回帰確認: magi_chat._gen=OK / magi_system(2.5-flash-lite)=OK / magi_system(3.5-flash-lite)=OK。2.5-flash-lite/2.5-flash/3.1-preview いずれも `budget=0` が自動選択され通る。**モデル名とtemperatureは意図的に据え置き**（方針①＝エラー箇所だけ先に潰す）。

⚠ 実測中、レート制限（2.5-flashは低RPM）でフォールバックが発動し「変更で壊れた」と誤読しかけた。**API連打の直後にテストしないこと**。

**移行①②③ 完了（2026-07-23・実機回帰済み）**

| # | 内容 | 結果 |
|---|---|---|
| ① | `gemini-3.1-flash-lite-preview` 撤廃 | kaggle_client / vision_analyzer / MAGI(BALTHASAR) → `gemini-3.5-flash-lite`。**画像入力も実機確認OK**(preview版より出力がクリーン=前置き無しで即JSON) |
| ② | MAGIを3.x世代へ | **MELCHIORのみ** `gemini-2.5-flash`→`gemini-3.6-flash`。CASPERは**意図的に2.5-flash-liteに残す** |
| ③ | temperature | **一律削除しない**。`sampling_kwargs()`で効く世代(2.5系)にだけ渡す |

**⚠ ②で全機移行しなかった理由（重要）**: 3.xのGAモデルは `3.6-flash` と `3.5-flash-lite` の**2つしかなく**、3機に別モデルを割り当てられない(同一モデル2機は「異なるAIが人格を形成」の設計意図に反する)。加えて**3.xではtemperatureが無視される**ため、CASPERの `temp=0.85`(直感・創造性)が死ぬ。よって現構成は **MELCHIOR=3.6-flash / BALTHASAR=3.5-flash-lite / CASPER=2.5-flash-lite** の**意図的な世代混在**。gemini_compatが引数差を吸収するので安全。

**⚠ ③で一律削除しなかった理由**: temperatureは2.5系では**今も有効**。一律削除するとCASPERの人格が痩せる。`gemini_compat.sampling_kwargs(model, temperature=)` が世代を見て出し分けるので、将来2.5が廃止されて全機3.xになれば自動的に渡されなくなる(400も踏まない)。

**旧・未着手リスト（すべて対応済み）** — いずれも `temperature` と `thinking_budget=0` を使用:
| ファイル | モデル | 備考 |
|---|---|---|
| `core/magi_chat.py` | 2.5-flash-lite | temp 0.6/0.7/0.2 |
| `core/magi_retrospective.py` | 2.5-flash-lite | temp 0.25/0.3/0.75 |
| `core/magi_system.py` | 2.5-flash / 3.1-flash-lite-preview / 2.5-flash-lite | temp 0.4 |
| `core/kaggle_client.py` | 3.1-flash-lite-preview | temp 0.1/0.2 |
| `core/vision_analyzer.py` | 3.1-flash-lite-preview | temp 0.1 |
| `app.py:9549, 13177` | 2.5-flash | temp 0.2 |

**⚠ 実測で判明した本当の地雷は `thinking_budget=0`（2026-07-23）**

| パラメータ | 3.5-flash-lite / 3.6-flash での挙動 |
|---|---|
| `temperature` / `top_p` | **OK**（発表どおり無視されるだけ。エラーにならない） |
| **`thinking_budget=0`** | **400 INVALID_ARGUMENT で即死** |
| `thinking_level='LOW'` | OK |

未着手6ファイルは**全て `thinking_budget=0` を使っている**ので、3.5/3.6に向けた瞬間に落ちる。移行の必須作業はtemperature削除ではなく**`thinking_budget`→`thinking_level`の置換**。

**MAGIの人格差についての仮説は棄却（実測済み）**。当初「3.x系でtemperatureが無視され人格差が消えているのでは」と疑ったが**外れ**だった：
- `gemini-3.1-flash-lite-preview` / `gemini-2.5-flash-lite` とも temp=0.0で5/5同一・temp=2.0で5/5全部違う → **temperatureは現行モデルで完全に効いている**。（最初「1〜100の整数」で試したら両温度とも'42'で誤判定しかけた＝**事前分布の強いプロンプトで温度テストをしてはいけない**。ひらがな造語のような分布がフラットな課題で測ること）
- さらに**同一モデル・temperature無しでも3人格は明確に別物**を返す（MELCHIOR=`pace_type`/`top3`の分析、BALTHASAR=`value_horses`の保守、CASPER=`pattern_a`/`pattern_b`の挑発。**返すJSONスキーマ自体が違う**）。つまり人格差の本体は `persona`(system_instruction) にあり、temperatureは補助。
- → **3.xへ移行してtemperatureを失っても人格差は保たれる**。[[project_magi_consensus]]の「役割を分ける」設計が効いている証拠でもある。

**対象外（触らない）**: `sandbox/hyperagents/stepping_stones/node_0.py` は `core/magi_system.py` と**バイト単位で完全同一のコピー**（62,948文字・100%一致・両方2026-03-29で停止）。`scripts/hyper_agent_sandbox_dgmh.py` も実験用。ユーザー承認済み。

**移行スキル（`npx skills add google-gemini/gemini-skills`）は使わない**判断（ユーザー承認済み）。`--global` でPC全体を変更＋Node.js依存＋変更内容は3種類だけで手作業可能なため。
