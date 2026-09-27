# -*- coding: utf-8 -*-
"""📒 プレイブック成績 — 検証済み買い方の実券と、確定後の成績。

買い方は変えない。見るだけ。的中・払戻はレース確定後にだけ付ける。
"""
import streamlit as st
import pandas as pd

from core import playbook_ledger as pl


def _fmt_pct(v):
    return '—' if v is None else f'{v:.1f}%'


def _fmt_yen(v):
    if v is None:
        return '—'
    return f'{int(v):,}円'


def _ticket_preview(row, cap=4):
    tks = row.get('tickets') or []
    if row.get('skip') or not tks:
        return '見送り（0点）'
    kind = row.get('ticket_type') or ''
    sep = '→' if kind == '3連単' else '-'
    labels = [sep.join(str(x) for x in c) for c in tks[:cap]]
    more = len(tks) - cap
    s = ' / '.join(labels)
    if more > 0:
        s += f' …他{more}点'
    return s


def _metric_box(title, races, hit_rate, roi, note, n_settled=0,
                hit_rate_lo=None, hit_rate_hi=None, loss_per_100=None,
                cost_per_hit=None, max_losing_streak=None):
    if n_settled >= 30 and hit_rate is not None and hit_rate_lo is not None and hit_rate_hi is not None:
        hr_txt = (
            f'{hit_rate:.1f}%'
            f'<span style="color:#888;font-size:12px;">'
            f'（確定{n_settled}R・統計的なぶれ幅 {hit_rate_lo:.0f}〜{hit_rate_hi:.0f}%）'
            f'</span>'
        )
    elif hit_rate is not None:
        hr_txt = (
            f'{hit_rate:.1f}%'
            f'<span style="color:#888;font-size:12px;">'
            f'（集計中・確定{n_settled}R・30Rで表示）'
            f'</span>'
        )
    else:
        hr_txt = '—'
    extra_lines = []
    if loss_per_100 is not None:
        extra_lines.append(
            f"<div>100円賭けるごとに平均<b>{loss_per_100:.1f}円</b>減る"
            f"<span style='color:#888;font-size:12px;'>（回収率100%未満の分）</span></div>"
        )
    if cost_per_hit is not None:
        extra_lines.append(
            f"<div>1回当たるまでに平均<b>{int(cost_per_hit):,}円</b></div>"
        )
    if max_losing_streak is not None:
        extra_lines.append(
            f"<div>最長で<b>{max_losing_streak}回</b>連続はずれ</div>"
        )
    extras = ''.join(extra_lines)
    st.markdown(
        f"<div style='border:1px solid #ddd;border-radius:8px;padding:10px 12px;'>"
        f"<div style='font-size:12px;color:#666;'>{title}</div>"
        f"<div style='font-size:15px;margin-top:4px;'>レース数 <b>{races}</b></div>"
        f"<div>的中率 <b>{hr_txt}</b></div>"
        f"<div>回収率 <b>{_fmt_pct(roi)}</b>"
        f"<span style='color:#888;font-size:12px;'>（払戻÷投資。100%で元が取れる）</span></div>"
        f"{extras}"
        f"<div style='font-size:12px;color:#888;margin-top:4px;'>{note}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


_SKIP_LABELS = {
    'zone_ba': '荒れそうなので見送り',
    'ninki_missing': '人気1〜4番が取れなかった',
    'ltr_insufficient': '能力順（検証AI）が足りなかった',
    'no_horses': '出走表が無かった',
}


def render():
    st.title('📒 プレイブック成績')
    st.caption(
        '検証済みのデフォルト買い方だけを記録します。'
        '手動の3連複・3連単エンジンは含みません。'
        '的中と払戻は、レースが確定してから付けます。'
    )

    entries = pl.list_entries()
    summ = pl.summarize(entries)
    d, c, ba, all_ = summ['D'], summ['C'], summ['BA'], summ['ALL']
    purchase_rate = summ.get('purchase_rate')
    if purchase_rate is not None:
        st.caption(
            f'買ったレースの割合 {purchase_rate:.1f}%'
            f'（見送りを含めた全レース比）'
        )

    col1, col2, col3 = st.columns(3)
    with col1:
        _metric_box(
            'D 鉄板（人気1〜4の3連複2点）',
            d['n_races'], d['hit_rate'], d['roi'],
            f"確定{d['n_settled']}R / 投資{_fmt_yen(d['investment'])} / 払戻{_fmt_yen(d['payout'])}",
            n_settled=d['n_settled'],
            hit_rate_lo=d.get('hit_rate_lo'), hit_rate_hi=d.get('hit_rate_hi'),
            loss_per_100=d.get('loss_per_100'), cost_per_hit=d.get('cost_per_hit'),
            max_losing_streak=d.get('max_losing_streak'),
        )
    with col2:
        _metric_box(
            'C 中庸（能力順2-4-7の3連単30点）',
            c['n_races'], c['hit_rate'], c['roi'],
            f"確定{c['n_settled']}R / 投資{_fmt_yen(c['investment'])} / 払戻{_fmt_yen(c['payout'])}",
            n_settled=c['n_settled'],
            hit_rate_lo=c.get('hit_rate_lo'), hit_rate_hi=c.get('hit_rate_hi'),
            loss_per_100=c.get('loss_per_100'), cost_per_hit=c.get('cost_per_hit'),
            max_losing_streak=c.get('max_losing_streak'),
        )
    with col3:
        _metric_box(
            '全体（DとCを合わせたもの）',
            all_['n_races'], all_['hit_rate'], all_['roi'],
            f"確定{all_['n_settled']}R / 投資{_fmt_yen(all_['investment'])} / 払戻{_fmt_yen(all_['payout'])}",
            n_settled=all_['n_settled'],
            hit_rate_lo=all_.get('hit_rate_lo'), hit_rate_hi=all_.get('hit_rate_hi'),
            loss_per_100=all_.get('loss_per_100'), cost_per_hit=all_.get('cost_per_hit'),
            max_losing_streak=all_.get('max_losing_streak'),
        )
    skip_parts = []
    for reason, cnt in sorted((summ.get('skips_by_reason') or {}).items()):
        label = _SKIP_LABELS.get(reason, reason)
        skip_parts.append(f'{label}: {cnt}件')
    if skip_parts:
        st.caption('見送りの内訳 — ' + ' / '.join(skip_parts))
    degraded_n = summ.get('degraded_n') or 0
    if degraded_n > 0:
        st.caption(
            f'穴データが無いまま3連単を組んだレース: {degraded_n}件（今後の見直し対象）'
        )
    st.caption(
        f"B/A 荒れはデフォルト見送りです。"
        f"記録 {ba['n_races']} レース・券数 0。"
        f"回収率の集計には入れません。"
    )

    try:
        from core import playbook_shadow as psh
        sh_cmp = pl.summarize_shadow_vs_production()
        sh_s = sh_cmp.get('shadow') or {}
        pr_s = sh_cmp.get('production_paired') or {}
        n_done = sh_cmp.get('n_shadow_settled') or 0
        n_min = sh_cmp.get('min_races') or 100
        n_tgt = sh_cmp.get('target_races') or 300
        with st.expander('🎯 Cゾーン Shadow（的中率重視 2-4-8）— 本番では使いません', expanded=False):
            st.caption(
                f'本番は ROI重視の **2-3-6** のままです。'
                f'2-4-8 は裏で記録だけしています。'
                f'再評価は **{n_min}〜{n_tgt}レース** 蓄積後'
                f'（現在 確定 {n_done} / 目安 {n_tgt}）。'
            )
            if n_done < n_min:
                st.info(
                    f'Shadow 確定 {n_done} レース — あと {max(0, n_min - n_done)} レースで'
                    f'初回再評価可能です。'
                )
            c1, c2 = st.columns(2)
            with c1:
                _metric_box(
                    '本番 2-3-6（同レース比較）',
                    pr_s.get('n_races') or 0,
                    pr_s.get('hit_rate'),
                    pr_s.get('roi'),
                    f"確定{pr_s.get('n_settled') or 0}R",
                    n_settled=pr_s.get('n_settled') or 0,
                    loss_per_100=pr_s.get('loss_per_100'),
                    cost_per_hit=pr_s.get('cost_per_hit'),
                    max_losing_streak=pr_s.get('max_losing_streak'),
                )
            with c2:
                _metric_box(
                    'Shadow 2-4-8（700円/レース）',
                    sh_s.get('n_races') or 0,
                    sh_s.get('hit_rate'),
                    sh_s.get('roi'),
                    f"確定{sh_s.get('n_settled') or 0}R / 予算{psh.SHADOW_BUDGET_YEN}円",
                    n_settled=sh_s.get('n_settled') or 0,
                    loss_per_100=sh_s.get('loss_per_100'),
                    cost_per_hit=sh_s.get('cost_per_hit'),
                    max_losing_streak=sh_s.get('max_losing_streak'),
                )
            if sh_s.get('hit_rate') is not None and pr_s.get('hit_rate') is not None:
                st.caption(
                    f"差分（Shadow−本番）: 的中率 "
                    f"{sh_s['hit_rate'] - pr_s['hit_rate']:+.1f}ポイント / "
                    f"回収率 {sh_s['roi'] - pr_s['roi']:+.1f}ポイント"
                )
    except Exception:
        pass

    unsettled = [r for r in entries if not r.get('settled') and not r.get('skip')]
    if unsettled:
        if st.button(f'確定結果を取り込む（未確定 {len(unsettled)} レース）',
                     help='ローカル成績DBにあればそれを使い、無ければ結果ページから当選組だけ取ります。買い目は作り直しません。'):
            n_ok = 0
            for r in unsettled:
                out = pl.settle(r['race_id'], fetch_remote=True)
                if out:
                    n_ok += 1
            st.success(f'{n_ok} レースに払戻を付けました。ページを再読み込みしてください。')
            st.rerun()

    if not entries:
        st.info('まだプレイブックの記録がありません。Single Race Analysis でレースを表示すると保存されます。')
        return

    zone_filter = st.selectbox(
        '表示するゾーン',
        ['全部', 'D', 'C', 'B/A'],
        index=0,
    )
    rows = entries
    if zone_filter == 'D':
        rows = [r for r in entries if r.get('zone') == 'D']
    elif zone_filter == 'C':
        rows = [r for r in entries if r.get('zone') == 'C']
    elif zone_filter == 'B/A':
        rows = [r for r in entries if r.get('zone') == 'BA' or r.get('skip')]

    table = []
    for r in rows:
        hit_txt = '—'
        if r.get('skip'):
            hit_txt = '見送り'
        elif r.get('settled'):
            hit_txt = '的中' if r.get('hit') else '外れ'
        table.append({
            '日付': r.get('race_date') or '',
            'レースID': r.get('race_id'),
            'ゾーン': r.get('ui_line') or r.get('zone') or '',
            '券種': r.get('ticket_type') or '見送り',
            '点数': r.get('ticket_count'),
            '実券': _ticket_preview(r),
            '結果': hit_txt,
            '投資': r.get('investment'),
            '払戻': r.get('payout') if r.get('settled') else None,
            '回収率(%)': r.get('roi') if r.get('settled') else None,
        })
    st.subheader('レース一覧')
    st.caption('実券は保存されたプレイブックそのものです。下の行をクリックせず、表で確認できます。')
    st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)

    with st.expander('1レースの全買い目を見る', expanded=False):
        ids = [r.get('race_id') for r in rows]
        if ids:
            pick = st.selectbox('レースID', ids)
            chosen = next((r for r in rows if r.get('race_id') == pick), None)
            if chosen:
                st.write({
                    '日付': chosen.get('race_date'),
                    'ゾーン': chosen.get('zone'),
                    '買い方': chosen.get('strategy'),
                    '券種': chosen.get('ticket_type'),
                    '点数': chosen.get('ticket_count'),
                    '投資': chosen.get('investment'),
                    '的中': chosen.get('hit'),
                    '払戻': chosen.get('payout'),
                    '回収率': chosen.get('roi'),
                    '確定の組': chosen.get('actual_result'),
                })
                tks = chosen.get('tickets') or []
                kind = chosen.get('ticket_type') or ''
                sep = '→' if kind == '3連単' else '-'
                if tks:
                    st.dataframe(
                        pd.DataFrame({'買い目': [sep.join(map(str, c)) for c in tks]}),
                        hide_index=True, use_container_width=True)
                else:
                    st.caption('このレースのデフォルト券はありません（見送り）。')
