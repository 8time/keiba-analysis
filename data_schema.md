# Data Schema Reference

このファイルは、プロジェクト内の重いデータファイルの構造を記録した軽量なリファレンスです。
AIエージェント（Antigravity）は、実際のデータファイルを読み込む代わりにこのファイルを参照します。

## 1. `race_history.csv` (ルートディレクトリ)
分析結果の概要が保存されるCSVファイルです。

### ヘッダー (Columns)
`RaceID,Date,Year,Month,Day,RaceTitle,Venue,RaceNum,Distance,Condition,Name,Umaban,Popularity,Odds,Weight,OguraIndex,BattleScore,Status,SiteIndex,ScoreBaseOgura,ScoreTimeIndex,ScoreMakuri,ScoreTraining,ScoreWeight,ScoreBloodline,ActualRank,ResultOdds,Agari,Alert,AlertText,Predicted_Diff,Actual_Diff`

### サンプルデータ (1行)
```csv
https://race.netkeiba.com/odds/index.html?type=b7&race_id=202608020211&housiki=c99,2026/02/28,2026,2,28,,Unknown,99,,,エイシンフェンサー,13,5.0,5.0,,166.8,116.8,No Data,,116.8,0.0,0.0,0.0,0.0,0.0,11,5.0,33.7,🎯◎,,,
```

---

## 2. `data/history/*.json`
「新ロジックテスト」の詳細な分析結果が保存されるJSONファイルです。

### 基本構造 (Schema)
```json
{
  "RaceID": "202608020211",
  "SavedAt": "2026-03-07 17:40:21",
  "Results": [
    {
      "馬番": 12,
      "馬名(ラベル付)": "💪 🧬 エーティーマクフィ",
      "人気": 1,
      "馬体重": "482(+2)",
      "調教": "B",
      "U指数": 99.9,
      "オメガ指数": 91.0,
      "血統": "SS",
      "元の順位": 5,
      "元のスコア": 130.6,
      "DIY2": 53.6,
      "DIY指数": 50.3,
      "Test_Score": 89.5,
      "加点内訳(備考)": "究極仕上(+5.0), 調教B(+70.0), 血統(SS), マクリ(+5.0)",
      "新順位": 1,
      "Diff": "↑+4"
    }
  ]
}
```
