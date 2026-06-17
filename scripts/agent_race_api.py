# -*- coding: utf-8 -*-
"""
AUTOMATA エージェント用 レース分析API（FastAPI）

デプロイ済みStreamlitアプリと同じ core.scraper / core.calculator を使い、
レースIDからの分析結果を REST(JSON) で返す。デスクA（収集役）1体がここを叩き、
結果は共有DB(KnowledgeStore)経由で他エージェントへ展開される（多重スクレイプ回避）。

サーバ内にTTLキャッシュを持つため、万一複数アクセスが来ても実スクレイプは1回。

起動:
    cd keiba_analysis
    pip install fastapi uvicorn        # 初回のみ
    python -m uvicorn scripts.agent_race_api:app --host 127.0.0.1 --port 8011

エンドポイント:
    GET /health                → {"ok": true}
    GET /analyze?raceId=<12桁> → agent_race_tool.analyze_race と同じJSON

pre_agi 側は環境変数で接続先を指定:
    $env:KEIBA_API_URL = "http://127.0.0.1:8011"
"""
import os
import sys
import time

# scripts/ の親（keiba_analysis ルート）を import パスに追加
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI, Query  # noqa: E402
from scripts.agent_race_tool import analyze_race  # noqa: E402

app = FastAPI(title="AUTOMATA Keiba Analysis API")

# ── TTLキャッシュ（同一レースの再スクレイプを防ぐ／単一アクセス化） ──
_CACHE = {}
_TTL = int(os.environ.get("KEIBA_API_TTL", "600"))  # 秒


def _cached_analyze(race_id: str):
    now = time.time()
    hit = _CACHE.get(race_id)
    if hit and now - hit[0] < _TTL:
        return {**hit[1], "cached": True}
    data = analyze_race(race_id)
    # エラーはキャッシュしない（次回リトライ可能に）
    if isinstance(data, dict) and not data.get("error"):
        _CACHE[race_id] = (now, data)
    return data


@app.get("/health")
def health():
    return {"ok": True, "cached_races": list(_CACHE.keys()), "ttl": _TTL}


@app.get("/analyze")
def analyze(raceId: str = Query(..., description="12桁のレースID")):
    return _cached_analyze(raceId)
