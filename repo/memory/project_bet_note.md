---
name: project-bet-note
description: 📝買い目ノート — 手書きの買い目を自由記述で書くと検証済みルールだけで診断(LLM不使用)
metadata: 
  node_type: memory
  type: project
  originSessionId: 8193f2c8-eae5-432d-9103-99a37077d415
  modified: 2026-08-02T21:18:46.094Z
---

「その日買う馬券をまっさらなノートに書き出して診断してほしい・API不使用で」という要望で新設。
既存の💱オッズ歪みスキャナーとは別物（あちらはオッズ起点、こちらは自分の買い目起点）。

**core/bet_note.py**（Streamlit非依存・テスト可能）
- `parse_note(text)` … 自由記述を解釈。`1R 馬連 3-7 500円` / `東京5R 単勝 8 1000円` /
  `9R ワイド 5-9,12 200円`(流し) / `11R 3連複 1,4,7,9 BOX 100円`。
  全角・『馬れん』『ウマレン』・`=`区切り・`#`コメント行に対応。点数は自動計算。
- `diagnose(bets, bankroll, race_ctx)` … 検証済み台帳に照らして指摘を返す。

**診断ルール(すべて実測根拠つき・LLM不使用)**
- 資金: 1日で資金の20%超 / 1レースで5%超(bankroll_cap)
- 券種: 単勝が入っていれば警告([[verified_tansho_roi_efficient]]) / 3連単の難度
- レース選択: 見送り推奨レースへの投入(race_skip_reasons)
- 馬の質: 危険人気馬([[verified_danger_fav_audit]]・「切らず相手へ」と案内)/
  消去対象(elim_verdict)/100倍超の構造的不利帯
- 頭数: [[project_narrow_n]]の推奨より広すぎ/狭すぎ
- トリガミ: 最も人気の組合せが当たっても投入額を下回らないか(単勝オッズからの概算)

**app.py** メニューに「📝 買い目ノート」を追加(💰BetSyncの次)。
解析済みスナップショット(view/cv/elimv)があれば自動で突き合わせ、無くても
資金配分と券種の診断だけは動く(段階的に賢くなる設計)。
