---
name: verified-fukusho-combo-leak
description: 複勝combo≥4の+EV(123%)はlook-aheadリークの幻と反証。leak-free版combo6pは全期間-EV(81-85%)。的中率単調性のみ本物。歴史BTでモジュール静的統計は使用禁止
metadata: 
  node_type: memory
  type: project
  originSessionId: 64a070b3-be5e-4051-a8b3-047fbb5b0c0c
---

Fable案件③(2026-07-07)。「買い方研究で初の+EV」(fukusho_combo_backtest.py・複勝combo≥4=
ROI123.5% CI[109.8,138.2])を長期履歴+leak-free再計算で厳密検証した結果、**リークの幻と反証**。

**Why(証拠・scripts/fukusho_wide_ev.py)**:
- リーク経路: 元combo(vh2_combo_cache)の構成モジュールが凍結DB全期間の静的統計=歴史レースの
  未来を含む。最強= corrected_time.get_figure(horse_figテーブル・馬の未来走含むベスト補正T・
  before_key非対応)。jockey_powerもbefore_key無しで呼ばれていた。血統も静的辞書。
- リーク署名(決定的): +EVは「leak-free版と不一致=未来情報でのみ上位」群にROI144%[121,168]で
  集中し、一致群は104%(非有意)。未来情報が最少の2026年は97.7%で消滅。
- 厳密leak-free版combo6p(CSV連続量のレース内top3化・相関0.479)では複勝ROIは全期間-EV:
  ≥4で2016-23=81.3%/2024-26=84.5%・年別11年でCI下限>100%ゼロ。
  ワイド(最良=combo×人気1-4で81-82%)/オッズ帯(最良=単勝10-20倍86%)/単複乖離(72-75%)/
  他エッジ単体(70-75%)も全て-EV。**複勝/ワイドプールもこのシグナル集合では効率的**。
- **的中率の単調性はleak-freeでも本物**(combo6p 0=5%→≥4=14%)=相手絞り用途は正当。
  ただし既公表の3着内率テーブル(combo4=19%等)は楽観側。

**How to apply**:
- 複勝買い目配線は中止。妙味馬リストは網羅ショートリスト位置づけ(+EV主張禁止)を維持。
- vh2_combo_cache.jsonをROIバックテストの根拠に使わない。歴史BTはCSV特徴ストア
  (data/export/horse_races.csv・2016+・48.6万行・全shift(1)厳守・sire_winroi等追加済)を正本に。
- 今後+EV候補には必ずリーク署名テスト(leak-free一致/不一致分解+未来情報量の年勾配)を適用。
  疑う順=①リーク②分散の幻(3連単の轍)③多重検定。
- fukusho_combo_backtest.pyに反証注記追記済。詳細=repo/fable_report_fukusho_wide.md。

関連: [[project-value-horse-hunter]] [[verified-tansho-roi-efficient]] [[verified-arare-signal-check]]
(6シグナルの3着内リフト表も同リークで楽観側の可能性・単調性自体は再確認済み)
