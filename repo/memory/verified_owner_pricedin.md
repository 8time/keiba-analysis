---
name: verified_owner_pricedin
description: 馬主・馬主×厩舎・地方中央使い分け(前走NAR)すべてholdout織込み済み。厩舎全体勝率と同型。owner_cache.json(4000頭)は資産
metadata: 
  node_type: memory
  type: project
  originSessionId: 2e1ab573-9c8a-4994-96f3-d38f0566d06f
---

## カード4パイロット: 馬主特徴は織込み済み(2026-07-02)

netkeiba horse_id == jravan ketto_num(確認済)を利用し、db.netkeiba.com/horse/から
馬主ID+生産者IDを馬ごとに1回スクレイプ(JRA2023-25出走上位4000頭・抽出成功率100%・
scripts/owner_pilot_collect.py→scripts/debug/owner_cache.json)。馬主の"過去"成績を
【自馬除外=純粋な馬主シグナル・リーク無し】で逐次計算し検証(scripts/owner_roi_backtest.py)。

### holdout2025 高-低tierコントラスト(=馬主質の純シグナル)
| 仮説 | 高-低pp | z | 判定 |
|---|---|---|---|
| ①馬主単体(=馬主ごとの回収率) | -0.41 | -0.52 | ❌織込み済み |
| ①馬主×6人気以下 | -0.08 | -0.10 | ❌織込み済み |
| ③馬主×厩舎ペア | +1.07 | +0.92 | ❌織込み済み(非有意) |

- 単勝ROIも高tier88.7%/低84.0%=全帯100%割れ=市場効率的([[verified_tansho_roi_efficient]])
- [[project_trainer_course]]の「厩舎全体勝率は織込み済み」と完全同型。馬主も同じ。

### 重大な手法教訓(再利用)
単tierのz(全体で高-3.67/低-5.10)は「キャッシュした活動馬が一様に人気ベースを下回る
選抜バイアス」で**エッジではない**。馬主質は必ず【高-低コントラスト】で見る(PCI交互作用と同手法)。
一様シフトを打ち消して初めて priced-in が判る。

### ②地方・中央の使い分けも織込み済み(2026-07-02・scripts/venue_switch_backtest.py)
jravan.dbはNAR結果(jyo30-55・100万走・ketto_num付)も含む→追加スクレイプ無しで地方↔中央
タイムラインが引ける(前走の場=発走前確定でリーク無し)。「前走NAR(地方帰り)」フラグの複勝残差:
| 仮説 | pooled z | holdout2025 z | 単ROI |
|---|---|---|---|
| H1前走NAR全体 | -2.31 | -1.91 | 42-59% |
| H2立て直し戻り(中央経験) | -1.71 | -1.74 | 41-58% |
| H4地方帰り×6人気以下 | -1.18 | -1.08 | 35-55% |
- 地方帰り馬は残差マイナス=**むしろ過剰人気**(買い妙味ゼロ・ROI悲惨)。弱fadeの気配はあるがholdout z-1.91でゲート-2.0未達=配線せず。対照(前走JRA)は残差≈0でベース健全。
- →②も却下。馬主関連(①③④owner+②venue)は全てpriced-in。

### 資産
- 生産者(breeder_id)もowner_cacheに同梱→生産牧場仮説は同スクリプト構造で即テスト可(未実施)。
- owner_cache.json(4000頭の馬主/生産者ID)は将来資産(生産牧場やLTR特徴の種)。

**Why:** ④馬主はカード4の本命だったが、厩舎と同じく市場に織り込まれていた。JV-Link不要・
netkeibaスクレイプ+jravan直結(ID一致)で1時間パイロット→即決着できた。

**How to apply:** 馬主/馬主×厩舎はLTR特徴に入れない・軸/相手/消去に使わない。次は②か打ち切り。
