# -*- coding: utf-8 -*-
"""新馬戦モード Phase 1（表示専用の情報集約レイヤー）。

設計書: repo/maiden_mode_design.md
背景: 新馬戦は全馬がデビュー戦で過去走データがなく、強適スコア・展開MAP・
Vエリア等の過去走依存ロジックが機能しない。かわりに「人（騎手・厩舎）」の
検証済み情報と基礎傾向を並列表示する。

原則（設計書 §1）:
  - スコア合成・順位付け・◎○▲印は付けない（材料の並列表示のみ）
  - 買い目/Rank/VH/合議/playbook には接続しない
  - 載せるのは検証済み資産のみ（J5騎手評価・全レース版黄金ライン・厩舎成績）
  - 禁止: 早生まれ(priced-in) / 兄弟デビュー(priced-in) / 新馬限定コンビ(標本不足) /
          遅デビュー(2023再検証で破棄) / 調教タイム(織込み) を妙味材料として出すこと
"""
from __future__ import annotations

# 新馬戦の基礎傾向（scripts/maiden_birth_month_backtest.py で確定した事実。
# 値を変えるときは検証スクリプト側の再計算が先。設計書 §3.2）
MAIDEN_FACTS = [
    '1番人気は全体より強い: 勝率35.0%（全体28.9%）・3着内率68.1%（全体61.1%）',
    '裏を返すと、1番人気の約3割は飛ぶ。人気馬1点依存は避ける',
    '過去走がないため、展開MAP・Vエリア・強適スコアは出ません',
]

# 注意喚起（検証で棄却された材料を「使える」と誤認させないための固定文）
MAIDEN_CAUTIONS = [
    '調教タイムは「動いた=買い」ではありません（速い時計はオッズに織込み済み・検証済）',
    '早生まれ・兄弟の新馬成績は人気に織込み済み（検証済・妙味なし）',
    'この表は材料の並列表示です。馬の順位付け・合成スコアは新馬戦では出しません',
]


def is_maiden_race(meta):
    """出馬表メタ情報から新馬戦を判定（既存の条件タグと同じ基準）。"""
    return '新馬' in str((meta or {}).get('class', ''))


def _resolve_trainer_code(row, jv):
    """調教師コードの解決。優先: 出馬表のTrainerID(netkeiba=JRAコード)。
    予備: 馬名から resolve_horse（過去走がある馬のみ。デビュー前は通常None）。"""
    tc = str(row.get('TrainerID', '') or '').strip()
    if tc:
        return tc
    try:
        _, tc2 = jv.resolve_horse(str(row.get('Name', '')))
        return tc2
    except Exception:
        return None


def collect_maiden_rows(df, race_id=None, meta=None, expected=None, min_year=None):
    """新馬戦モードの表示行を集める（表示専用。スコア・順位は作らない）。

    戻り値: list[dict] — 馬番順。各キーは日本語の表示ラベル。
      馬番 / 馬名 / 騎手 / 騎手の評価 / 騎手の内訳 / 厩舎 /
      厩舎の勝率(3年) / 当コース勝率 / 黄金ライン
    データが取れない項目は '—'（理由は caption で説明する）。
    """
    from core import jockey_jv as jv

    venue = None
    jyo = None
    if race_id:
        try:
            jyo = str(race_id)[4:6]
            venue = jv._venue_name(jyo)
        except Exception:
            venue = None
            jyo = None
    dist = (meta or {}).get('distance')
    surface = ''
    try:
        if 'CurrentSurface' in df.columns and not df.empty:
            surface = str(df['CurrentSurface'].iloc[0])
    except Exception:
        surface = ''

    rows = []
    for _, r in df.iterrows():
        try:
            uma = int(r['Umaban'])
        except Exception:
            continue
        jockey = str(r.get('Jockey', '') or '')
        name = str(r.get('Name', '') or '')
        trainer = str(r.get('Trainer', '') or '') or '—'
        tc = _resolve_trainer_code(r, jv)

        # 騎手の評価（J5と同じ検証済み係数。trainer_codeを渡すと黄金ラインも内訳に入る）
        j_eval = '—'
        j_note = '—'
        gold_mark = '—'
        try:
            fac = jv.jockey_factor(jockey, venue=venue, distance=dist,
                                   trainer_code=tc, expected=expected)
            if fac.get('note') == 'データ少':
                j_eval = 'データ少'
            else:
                j_eval = jv.coef_band(fac['mult'])
            j_note = fac.get('note') or '—'
            gold_mark = jv.golden_line_mark(fac.get('gold')) or '—'
        except Exception:
            pass

        # 厩舎の成績（全体3年＋当コース。当コースは縮小推定済み勝率を使う）
        t_all = '—'
        t_course = '—'
        if tc:
            try:
                ov = jv.trainer_overall_winrate(tc, min_year=min_year)
                if ov and ov.get('runs'):
                    t_all = f"{ov['win_rate'] * 100:.0f}%（{ov['runs']}走）"
            except Exception:
                pass
            try:
                if jyo and surface:
                    cw = jv.trainer_course_winrate(tc, jyo, surface, min_year=min_year)
                    if cw and cw.get('runs'):
                        t_course = (f"{cw['win_rate_shrunk'] * 100:.0f}%"
                                    f"（{cw['runs']}走・少ない時は平均寄せ済み）")
            except Exception:
                pass

        rows.append({
            '馬番': uma,
            '馬名': name,
            '騎手': jockey or '—',
            '騎手の評価': j_eval,
            '騎手の内訳': j_note,
            '厩舎': trainer,
            '厩舎の勝率(3年)': t_all,
            '当コース勝率': t_course,
            '黄金ライン': gold_mark,
        })
    rows.sort(key=lambda x: x['馬番'])
    return rows
