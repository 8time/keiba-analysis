---
name: project-philosophy-engine
description: 競馬AI思考法の言語化(docs/keiba_ai_philosophy.md)と思考エンジン(core/philosophy.py)をSRAに配線した案件
metadata: 
  node_type: memory
  type: project
  originSessionId: 9ae897bd-d954-4ace-a024-a2d4254e1de5
---

「開発者の思考で選んだ馬を毎レース表示・思考プロセスを設定可能に」という要望を、
**LLMに毎レース考えさせる方式ではなく決定的ルールエンジン**として実装した(2026-07-13完了)。

- 正本 = `docs/keiba_ai_philosophy.md`。**創作ではなく検証済み台帳(verified_*)の編纂**。
  ステップ0〜6(レース選別→除外→危険人気馬→妙味馬→軸の裏取り→買い目→反対役)＋禁止リスト14項目。
- エンジン = `core/philosophy.py`。既存モジュール(consensus_view/value_scanner/danger_gate/
  elim_cross)の結果を受け取り理由文に編成するだけの薄い層。**新しい予測ロジックは作らない**。
  最終結論は統合ビューの合議を正本として再掲=別予想を作らない(表示の矛盾防止)。
- 設定 = `philosophy.json`。3層: ①ステップON/OFF ②厳しさ3択(厳しめ/標準/ゆるめ) ③調整値(PARAM_SPECS
  =見送り理由数/荒れ寄り%/穴のcombo数/複勝信頼度フロア/相手頭数…すべて選択式・スライダー禁止)。
  paramsが強度既定値を上書きする。**検証で出た数値(複勝率テーブル/z値/荒れロジット係数)は動かせない**。
- ⑧自分のルール = 検証外の個人ルールを画面から追加可(人気/オッズ/combo/来にくさ の条件→注意or消し)。
  本命と穴は誤爆防止で保護。[[project_elim_reasons_learning]]/パドック台帳と同じ観測台帳扱いで①〜⑦と分離表示。
- 新ステップの足し方 = STEPSに1行 + `_step_xxx()` + think()の_runに1行(docs §8)。
- 指示書 = `repo/opus_brief_philosophy.md`。

**Why:** 汎用プロンプトでLLMに思考法を生成させると、過去に潰した俗説(展開読み・脚質・
EV>100で買い・PCI等)を再発明する。禁止リストを本文に収録して再発明を構造的にブロックした。

**How to apply:** 思考法に新しい判断軸を足したくなったら、まず [[MEMORY]] の verified_* を確認し、
未検証なら `repo/fable_brief_*.md` 形式でバックテスト指示書を起こす。ドキュメントに直接足さない。
