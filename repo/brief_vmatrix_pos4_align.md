# Composer案件 Vエリア縦軸を pos4 に揃える（整合性修正のみ）

> このファイルをそのまま Composer 2.5 に渡してよい。コールドスタート前提。
> **新しい予測・新しいエッジ・赤枠ルールの変更は禁止。** やることは「同じレースの隊列情報へVの縦を統一する」だけ。

モデル指定: Composer 2.5（ユーザー指定）。別モデルに切り替えない。

---

## 0. 最初に読む

- `CLAUDE.md` … 関数シグネチャを壊さない（optional 追加は可）。新ライブラリ禁止。UTF-8。
- `repo/AGENT_BRIEF.md` … 展開恩恵の買い加点は却下済み。再配線しない。
- 実装箇所: `core/pace_map.py` の `build_v_matrix`（現行 ~L1156）、呼び出しは `app.py` ~L4961。

変更後は `python tests/smoke.py --quick` と、下に書く単体テストが通ること。

---

## 1. 背景（なぜ直すか）

同じSRA実行で、すでに次が計算されている。

```text
_pm_ctx = build_pace_context(...)   # pos4: {umaban: 0〜1}  0=先頭
_pm_finish = predict_finish(...)    # 直線到達 0〜1（着順寄り合成）
```

展開マップは `pos4`（新聞の隊列図は `finish`）。
Vエリアの縦だけ `profiles['ten']`（過去走の最初のコーナー平均）を使っている。

同じ馬に「現在位置」が2つある。これは研究ではなく**整合性バグ**。

目標:

```text
縦座標  = pos4（欠損時だけ ten → 脚質score）
≫印     = pos4 より finish が前（座標には入れない）
横・赤枠 = 触らない
買い目   = 触らない
```

---

## 2. やってよいこと / 禁止

### やってよい

- `build_v_matrix` に **optional キーワード引数** `pos4=None`, `finish=None` を末尾追加。既存位置引数は動かさない。
- 縦の基準を `ten` → `pos4`。
- `pos4` が無い／その馬が欠けているときだけ、現行どおり `ten` → `h['score']`。
- `≫` を「差し切り margin≥1.5秒」から「finish が pos4 より前」に付け替える。
- 縦に足していた `sashikiri` の y 加算をやめる（直線補正は ≫ に移す。二重補正しない）。
- `sashikiri=` 引数は残してよい（呼ばれても y に使わない）。削除すると呼び出し側が壊れるので残す。
- 軸ラベル・caption を「4角想定（展開マップと同じ）」に直す。略語には短い日本語を添える。
- 位置解決を短い純関数に切り出してテストする。

### 禁止（実装したら差し戻し）

- `predict_finish` を y / x / 該当判定に入れる。
- `ten_speed` を縦に使う。
- 横の式 `lane = 0.65 * gate + 0.35 * pos` の係数を変える。枠の正規化を変える。
- 赤枠 `_V_COL` / `_V_ROW`、馬場ラジオ、ペースラジオを変える。
- V該当を Rank / VH / 合議 / 買い目 / スコアに接続する。加点しない。
- 9マスの連続スコア化。コース形状・含水・クッションを赤枠に足す。
- `requirements.txt` 追加。既存関数の必須引数化。
- FEATURE_STATUS / 新聞の本番買い目 / playbook を触る必要はない。触るな。

---

## 3. 位置の定義（実装契約）

スケールは既存どおり **0 = 前（先頭）、1 = 後（最後方）**。`pos4` も `ten` も `finish` も同じ向き。

```text
y = (1.0 - pos) * 3.0     # 0..3（後→前）  ※現行と同じ変換
y_adj = y                 # sashikiri を足さない
x = (0.65 * gate + 0.35 * pos) * 3.0
```

`pos` の優先順位（馬ごと）:

1. `pos4.get(umaban)`。キーは int。`pos4` が `{3: 0.1}` でも `'3': 0.1` でも読めるように `int` に揃えてから取る。
2. `profiles[name]['ten']` が not None
3. `h['score']`

`pos` は縦と横の混ぜ（0.35）で**同じ値**を使う。係数は変えない。横だけ ten に残すな。

`finish` 差（≫ のみ）:

```text
delta = pos4_used - finish     # 正 = 直線でより前へ
push = (finish is not None) and (pos4 が実際に使われた) and (delta >= 0.15)
```

- 定数名: `V_FINISH_PUSH_MIN = 0.15`（`core/pace_map.py` 上部、`build_v_matrix` の近く）。
- `pos4` 欠損で ten フォールバックした馬には、finish があっても ≫ を付けない（基準が違うから）。
- `finish` が無い／呼び出しで渡されないときは ≫ なし。旧 sashikiri の ≫ も出さない。

ホバー文言の例:

- 基準: `4角想定(展開マップと同じ)`
- フォールバック時: `過去走の位置取り(4角データなし)`
- ≫: `直線で前へ（4角より前に出る想定）`  ※「予測スコア」とは書かない

Y軸タイトルを `4角想定位置（展開マップと同じ）` に変更。
`到達ポジション（4角＋差し切り補正）` は残すな。

---

## 4. 呼び出し（app.py）

現行（~L4961）:

```python
_vm_fig, _vm_list = _pmap.build_v_matrix(
    _pm_horses, profiles=_pm_profiles,
    pace=_vm_pace, baba=_vm_baba,
    sashikiri=_sk_rows,
)
```

変更後:

```python
_vm_fig, _vm_list = _pmap.build_v_matrix(
    _pm_horses, profiles=_pm_profiles,
    pace=_vm_pace, baba=_vm_baba,
    sashikiri=_sk_rows,
    pos4=(_pm_ctx or {}).get('pos4'),
    finish=_pm_finish if '_pm_finish' in dir() else None,
)
```

`_pm_finish` はこのブロックより上（~L4686）で既に作っている。無い経路では `finish=None`。

キャプション（~L5052 付近）を事実に合わせる:

- 縦 = 展開マップと同じ4角想定（`pos4`）。無い馬だけ過去走の位置取り。
- 黄の ≫ = 4角より直線で前に出る想定（着順予想そのものではない）。
- 「差し切り限界の余裕+1.5秒で縦を前方補正」は**削除**（もうやらない）。
- 「Vは地図であって買いではない」の既存注意（~L4975）は残す。

ラジオ（馬場・ペース）は触るな。

---

## 5. 純関数（テスト用）

`core/pace_map.py` に次を追加して `build_v_matrix` から使う。plotly に依存させるな。

```python
def resolve_v_pos(umaban, name, score, profiles=None, pos4=None):
    """Vの縦・横混ぜに使う pos（0=前, 1=後）。
    戻り: (pos: float, source: 'pos4'|'ten'|'score')
    """

def finish_push_delta(pos, finish, source):
    """≫用。source!='pos4' or finish is None なら None。
    それ以外は pos - finish。
    """
```

`build_v_matrix` はこれらを呼ぶだけにする。ロジックを二重に書くな。

---

## 6. テスト

`tests/test_vmatrix_pos4.py` を新規作成（unittest）。ライブ通信・DB不要。

1. `pos4={1: 0.1, 2: 0.9}` のとき、馬1の pos は 0.1 で source=`pos4`。馬2は 0.9。
2. `pos4=None` で profile ten=0.2 なら source=`ten`、pos=0.2。
3. ten も無しなら `score`。
4. `finish=0.0`, `pos=0.4`, source=`pos4` → delta=0.4 ≥ 0.15 → push 対象。
5. 同じ finish でも source=`ten` → push しない。
6. `build_v_matrix` に pos4 を渡したとき、該当リストが ten だけのときと**変わり得る**（固定した2頭で、ten は中団・pos4 は前方、baba=フラット, pace=スロー なら pos4 側だけ赤枠に入る、のような小さな合成データ）。
7. y に sashikiri margin を足していない（sashikiri に大きな margin を渡しても y == y_raw）。

`tests/smoke.py` に3行程度の契約テストを足してよい（import と resolve_v_pos の優先順位）。巨大なテストは不要。

plotly が無い環境でも純関数テストは通ること。

---

## 7. holdout 確認スクリプト（本番ロジックに接続しない）

`scripts/vmatrix_pos4_align_check.py` を新規。**app / 買い目は変更しない。**

目的: 「悪化していないことの確認」。採用判定で本番ルールを変えるな。

入力: `data/jravan.db`（既存の `scripts/vmatrix_pos_backtest.py` と同じ DB）。

範囲: holdout `day >= 20240101`（race_key 先頭8桁 or year+monthday）。頭数8以上。JRA（場コード 01-10）。件数は最大でも数千Rで打ち切ってよい（フルスキャンが重いなら 2025 のみでも可。スクリプト先頭にコメントで範囲を書く）。

各レース:

- `build_pace_context` 相当の `pos4` を既存関数で取る（自前の隊列式を発明するな）。
- 現行相当の縦: `ten`（`fetch_jv_profiles` の ten、before_key=そのレース）。
- 改修相当の縦: `pos4`。
- 赤枠は **baba=フラット, pace=ミドル で固定**（馬場・ペース研究を混ぜない。縦の差だけ見る）。

出力（print と `repo/analysis/vmatrix_pos4_align/` に csv/json どちらでも可）:

| 指標 | 意味 |
|---|---|
| ① 帯一致率 | 縦を3帯（前/中/後 = pos&lt;1/3, &lt;2/3, else）にしたとき、展開マップ pos4 帯と V 縦帯が一致する割合。改修後はほぼ 1.0 になるはず（定義どおり） |
| ② V該当の重なり | 同じ赤枠での ten案 vs pos4案 の該当馬 Jaccard |
| ③ 該当頭数 | 1レースあたり平均該当数 ten案 / pos4案 |
| ④ 複勝率・単ROI | 該当馬の複勝率と単勝ROI（円は jravan の単勝オッズ）。「改修の方が良いから採用」と書くな。ten案より大きく悪化していなければ「整合性修正として許容」と書く |

④が単勝ROIで ten案より **5pt以上悪い**ときだけ、結果をユーザーに報告して本番反映を保留。それ以外は表示修正として進めてよい。

このスクリプトは今回の必須成果物。動かして数字を出すこと。DBロック時は `vmatrix_pos_backtest.py` と同様にリトライ。

---

## 8. 完了条件

- [ ] `resolve_v_pos` / `finish_push_delta` があり、テストが通る
- [ ] `build_v_matrix(..., pos4=, finish=)` が動き、sashikiri は y に効かない
- [ ] `app.py` が `_pm_ctx['pos4']` と `_pm_finish` を渡す
- [ ] 軸ラベルと caption が「4角想定」「≫は直線で前」になっている
- [ ] 買い目・合議・スコア・赤枠ルールを触っていない（git diff で確認）
- [ ] `python tests/smoke.py --quick` が通る
- [ ] holdout スクリプトを1回実行し、①〜④をユーザー向けに平易な日本語で報告する

コミットはユーザーが頼むまでするな。

---

## 9. ユーザーへの報告テンプレ（実装後）

```text
Vの縦を展開マップと同じ4角想定(pos4)に揃えました。
黄の矢印は「4角より直線で前に出る想定」です。着順予想ではありません。
赤枠の決め方と買い目は変えていません。

holdout: 該当の重なり Jaccard=… / 複勝 ten案…% vs pos4案…% / 単ROI … vs …
→ 悪化が大きい場合のみ保留、と指示書どおり判定。
```

「精度が上がった」「買いやすくなった」とは書くな。地図を揃えた、と書け。
