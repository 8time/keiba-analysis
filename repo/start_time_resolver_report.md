# START TIME RESOLVER

## REAL_START_TIME_CONFIRMED

2026-09-22 の一覧から、79レースの発走時刻を取得した。欠測は0件。判断スナップショット、影の推奨、結果精算は作っていない。実購入は0件。

## 時刻が0件だった理由

`race_list_sub.html` には `<span class="RaceList_Itemtime">09:45</span>` がある。地方競馬の同じ一覧は `<div class="RaceData">` の中の `14:40` である。`get_race_list_for_date` は race_id だけを読んで、これらの時刻を捨てていた。ページ自体に時刻が無かったわけではない。

## 202606040701 は6月4日のレースではない

中山の払戻リンクは `kaisai_id=2026060407` かつ `kaisai_date=20260922` だった。race_id の並びは「年・場・回・日・レース番号」で、先頭8桁はカレンダー日付ではない。1R の表示時刻は 09:45。先頭8桁を日付として拒否したのは誤判定なので、そのルールは使わない。代わりに、ページ内の `kaisai_date` が要求日と違う一覧は STALE_RACE_LIST として捨てる。

## 取得元

優先は race_list_sub の Itemtime、無ければ RaceData の時刻。それでも無ければ出馬表の「15:40発走」。レース番号からの推測はしない。タイムゾーンは Asia/Tokyo。同じ race_id がページに二度出ても、最初の時刻だけを使う。

診断コマンドは `python scripts/forward_collector.py --diagnose-live`。次回の開催日に `--live` を起動すると、この時刻で 60 / 30 / 15 / 5 分前の枠を見る。15分前に一番近いスナップショットが主判断になる。今日のレースはすでにその窓を過ぎているので、今回は判断を作っていない。
