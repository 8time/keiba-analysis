# Vエリア P1：既存検証済み注記の表示統一

> 実装完了（2026-09-07）。表示・UI配線のみ。Vロジック非変更。

## 実装サマリ

- `core/vmatrix_annotations.py` — 既存4注記の馬番別集約（判定は各モジュール委譲）
- `app.py` — Vチャート直下に統一注記ブロック。末脚の大型HTMLアラートは撤去（新聞保存は維持）

## ガード（変更なし）

`build_v_matrix`, `resolve_v_pos`, pos4, 赤枠, ctx.pace, 買い目, Rank, VH, playbook

## 4注記

| 表示 | 既存ソース |
|------|-----------|
| 🔥末脚 | agari≤0.33 & pop≥6（app.py 既存条件） |
| ⚠危険 | `track_bias.danger_popular_inner` |
| ◆枠 | `track_bias.dirt_draw_signal` |
| ◇場 | `blood_course.venue_fav_note` |

V外の馬も注記があれば表示。Plotly座標は未変更。
