---
name: project_elim_reasons_learning
description: 🧠AIフィルタリング削除→🎯強適消去エンジンに消去理由ラーニング(条件タグ3回で自動残し)を新設
metadata:
  node_type: memory
  type: project
  originSessionId: c3fa42fa-de5c-41c4-9911-b6156b6e7b9d
---

🧹消去フィルターページ改修(2026-06-17・ユーザー要望)。

- **🧠AIフィルタリング(自然言語→ルール+出馬データ表)を丸ごと削除**(旧app.py col_left/col_right ブロック218行)。convert_natural_language_to_rule/apply_rule_to_row等の関数定義は未使用で残置(害なし)。
- **🎯強適消去エンジンに『消去理由ラーニング』新設**(core/elim_reasons.py)。回顧用途=終了レースで3着内馬が『🧹消し』に入っていたら残しに変更し、自由文理由(空欄可)＋条件タグを記録。
- **学習方式=条件タグ付き自動残し(ユーザー選択)/昇格回数=3回(ユーザー選択)**。同じタグが3回たまると以後そのタグに合致する消し馬を自動で『✅残し』に昇格(♻️表示)。
- TAG_DEFS(12個・全て出馬表/過去走から自動判定): anauma(人気薄8番↓)/dist_short/dist_long/layoff/spurt(末脚0.8↑)/wt_up(+8)/wt_down(-8)/mare/front/closer/dirt_new/topswap。入力時は該当馬の自動タグを初期選択、ユーザーが増減可。
- 台帳=ルート elim_reasons.json(.gitignore追加・ユーザー個人データ。Cloudでは揮発)。compute_tags/load_ledger/add_entry/make_entry/tag_counts/learned_tags。
- **正直な前提**: backtest検証済みエッジではなく個人実観測の学習ループ(folk-signal領域)。人気薄/牝馬等の広いタグは多くの馬を残すと注意書き。検証済み妙味は[[project_elimination_engine]](穴1頭救出)/[[verified_spurt_index]]/[[project_value_scanner]]側。
- 新moduleのためStreamlit完全再起動が必要。未commit(push待ち)。
