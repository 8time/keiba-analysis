# -*- coding: utf-8 -*-
"""
会場の時間別天気(降水量)取得 — core/weather.py

締切直前に馬場が良→重/不良へ変わるとverified_heavy_track_biasのバイアスが発動する。
そこで会場の緯度経度から時間別降水量を取得し「雨が来ているか/馬場悪化の予兆」を可視化する。

データ源: Open-Meteo (APIキー不要・無料)。通信は既存の requests のみ(新ライブラリ追加なし)。
当日/直近・未来はforecast、過去日はarchiveエンドポイントを使う。失敗しても落ちない。
"""
import datetime as _dt

# JRA10場: jyo(競馬場コード) -> (lat, lon, 名称)。座標は各競馬場の所在地。
VENUE_LL = {
    '01': (43.062, 141.351, '札幌'),
    '02': (41.778, 140.729, '函館'),
    '03': (37.752, 140.470, '福島'),
    '04': (37.918, 139.049, '新潟'),
    '05': (35.659, 139.483, '東京(府中)'),
    '06': (35.725, 139.999, '中山'),
    '07': (35.063, 136.954, '中京'),
    '08': (34.909, 135.713, '京都(淀)'),
    '09': (34.784, 135.362, '阪神'),
    '10': (33.860, 130.882, '小倉'),
}


def venue_of_race(race_id):
    """race_id(12桁 netkeiba) -> (lat,lon,名称) or None。jyo=5-6桁目。"""
    try:
        return VENUE_LL.get(str(race_id)[4:6])
    except Exception:
        return None


def fetch_hourly_precip(race_id, date_yyyymmdd, timeout=8):
    """会場の指定日の時間別降水量(mm)と天気コードを取得。
    戻り: {'venue','date','hours':[(時刻'HH:MM', precip_mm, code), ...], 'total'} or {'_error'}."""
    ll = venue_of_race(race_id)
    if not ll:
        return {'_error': '会場座標が不明です(中央10場のみ対応)'}
    lat, lon, name = ll
    d = str(date_yyyymmdd)
    if len(d) != 8 or not d.isdigit():
        return {'_error': '日付形式が不正(YYYYMMDD)'}
    iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    # 過去日(今日より前)はarchive、当日/未来はforecast
    try:
        today = _dt.date.today()
        target = _dt.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
        host = 'archive-api.open-meteo.com/v1/archive' if target < today else 'api.open-meteo.com/v1/forecast'
    except Exception:
        host = 'api.open-meteo.com/v1/forecast'
    url = (f"https://{host}?latitude={lat}&longitude={lon}"
           f"&hourly=precipitation,weather_code&timezone=Asia%2FTokyo"
           f"&start_date={iso}&end_date={iso}")
    try:
        import requests
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        j = r.json()
        h = j.get('hourly', {}) or {}
        times = h.get('time', []) or []
        precip = h.get('precipitation', []) or []
        codes = h.get('weather_code', []) or [None] * len(times)
        hours = []
        for i, t in enumerate(times):
            hh = t.split('T')[-1] if 'T' in t else t
            p = precip[i] if i < len(precip) else None
            c = codes[i] if i < len(codes) else None
            hours.append((hh, p, c))
        total = round(sum(p for _, p, _ in hours if isinstance(p, (int, float))), 1)
        return {'venue': name, 'date': iso, 'hours': hours, 'total': total}
    except Exception as e:
        return {'_error': str(e)}


def summarize(result, from_hour=8, to_hour=18):
    """開催時間帯(既定8-18時)の降水を要約。戻り: {'rained','total_mm','peak_hour','trend'}。"""
    if not result or '_error' in result:
        return None
    sel = []
    for hh, p, _ in result.get('hours', []):
        try:
            h = int(str(hh).split(':')[0])
        except Exception:
            continue
        if from_hour <= h <= to_hour and isinstance(p, (int, float)):
            sel.append((h, p))
    if not sel:
        return None
    total = round(sum(p for _, p in sel), 1)
    peak = max(sel, key=lambda x: x[1])
    # 後半(午後)ほど増えていれば馬場悪化トレンド
    mid = len(sel) // 2
    early = sum(p for _, p in sel[:mid])
    late = sum(p for _, p in sel[mid:])
    trend = '悪化(午後に雨増)' if late > early + 0.5 else ('回復(午後に雨減)' if early > late + 0.5 else '横ばい')
    return {'rained': total > 0.1, 'total_mm': total,
            'peak_hour': f"{peak[0]:02d}時({peak[1]:.1f}mm)" if peak[1] > 0 else 'なし',
            'trend': trend}
