# フェーズA: ledger.db 監査スキーマ・バックアップ

## 対象

- ファイル: `data/ledger.db`（SQLite）
- テーブル: `bets`, `bet_settlement_log`, `analysis_runs`, `audit_events`, `audit_snapshots`, `purchase_batches`

## スキーマ追加（冪等）

アプリ起動または `Ledger()` / `AuditStore()` 初回接続時に **ALTER IF NOT EXISTS** 相当で列追加されます。

| 変更 | 内容 |
|------|------|
| `bets` | `purchase_batch_id`, `recommendation_id`, `analysis_run_id`, `audit_link`, `bet_purpose` |
| `bet_settlement_log` | `action` |
| `purchase_batches` | 既存。`record_status`: `ok`(legacy=committed), `pending`, `committed`, `failed` |

**再実行安全**: 既存列がある場合は例外を握りつぶしスキップ（Python `ALTER TABLE` try/except）。

**失敗時**: 起動は継続。監査記録のみ失敗し UI に警告（購入確定はトランザクション rollback）。

## migration 手順（本番）

1. **停止**: Streamlit を Ctrl+C で完全停止。
2. **バックアップ**（必須）:
   ```powershell
   Copy-Item data\ledger.db data\ledger.db.bak-YYYYMMDD-HHMMSS
   ```
3. **起動**: `streamlit run app.py` — 初回接続で列・監査テーブルが無ければ作成。
4. **確認**:
   ```powershell
   python -c "from core.money import Ledger; from core.audit_store import AuditStore; lg=Ledger(); st=AuditStore(con=lg.con); print('ok'); lg.close()"
   ```

## 復元

```powershell
# Streamlit 停止後
Copy-Item data\ledger.db.bak-YYYYMMDD-HHMMSS data\ledger.db -Force
```

## やってはいけないこと

- 全 `bets` の一括再精算・ID の推測埋め
- `purchase_batches` の `record_status` を一括 `committed` に書き換え（orphan 調査前）

## orphan batch（batch のみ・bets 無し）

step5 テスト互換の `confirm_app_purchase`（bets 非連携）で残る可能性あり。  
集計は **committed かつ bets 行** を正とし、`load_settled_result(..., '__all__')` は **pending/failed batch の bets を除外**。

## バックアップ推奨頻度

- 購入確定前後、MAGI 回顧保存前
- 精算訂正（`void_settlement` / `correct_settlement`）前

## retro_ledger.json

MAGI 会話台帳（`data/retro_ledger.json`）は DB 外。別途ファイルコピーでバックアップ。
