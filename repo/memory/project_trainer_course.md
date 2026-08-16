---
name: project-trainer-course
description: 厩舎の当コース勝率をRanking Trainer列に表示＋初ブリ検知。検証で当コース高勝率のみ妙味
metadata: 
  node_type: memory
  type: project
  originSessionId: 5e89769b-3184-403b-8fde-01496f4cfa45
---

📊 強適 Ranking Table の Trainer列を「名前だけ」から実用化(2026-06-15)。

**検証(scripts/trainer_backtest.py, train〜2022→test2023-2025, 13.1万騎乗)**:
- 調教師の**全体勝率(≒リーディング)は市場織込み済**(残差ほぼ0)=「友道だからすごい」は効かない。
- **当コース(競馬場×馬場)勝率の高帯のみ妙味**: >20% 勝利残差+0.030(z≈2.6有意)、14-20% +0.011。<10%は負。

**実装**:
- core/jockey_jv.py: `trainer_course_winrate(tc,jyo,surface,min_year)` / `trainer_overall_winrate(tc,min_year)` / `horse_blinker_history(ketto)`。jyo==netkeiba race_id[4:6](JRAは01-10)。surfaceは'芝'/'ダート'。
- app.py Ranking: Trainer列を「栗東・友道 A-17%(383)」形式に。ﾗﾝｸ=全体3年勝率(A≥14/B≥10/C≥7/D)、当ｺｰｽ=今回場×馬場の3年勝率＋🔴≥20%/🟠≥14%妙味マーク。セル文字色は厩舎ランクで色分け(color_trainer)。name→成績は session_state[f"trainer_course_{race_id}"]にキャッシュ。Streamlit表は1セル1色のためランクと数字の別色は不可。
- **初ブリンカー**: core/scraper.py get_race_data が出馬表B印(`<span class="Mark">B</span>`)を `Blinker` 列に取得。app.pyで現走B印＋過去blinker=0→Alert列に「🅑初ブリ」橙表示。検証で過剰人気のため注意表示のみ([[feedback-folk-signals-overbet]])。
- **季節フェード**: 牝×冬/春をAlertに「♀冬/♀春ﾌｪｰﾄﾞ」青表示(検証で有意に過剰人気)。

未push(2026-06-15時点): core/jockey_jv.py, core/scraper.py, app.py, scripts/trainer_backtest.py・blinker_backtest.py・folk_signals_backtest.py。
