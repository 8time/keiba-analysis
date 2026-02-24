import sys, io
import os
from dotenv import load_dotenv
import google.genai as genai
from google.genai import types as genai_types

# Load environment variables from .env file (for local testing)
load_dotenv()
# try:
#     sys.stdout.reconfigure(encoding='utf-8')
# except:
#     pass

# sys.stdout.reconfigure(encoding='utf-8')
import importlib
import streamlit as st
import pandas as pd
import time
import scraper
import calculator
# Force reload so code changes are always reflected
importlib.reload(calculator)
importlib.reload(scraper)
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

st.set_page_config(page_title="Keiba Analysis - Modified Ogura Index", layout="wide")

# Sidebar: Cache Clear Button
with st.sidebar:
    st.divider()
    if st.button("🔄 キャッシュクリア (Cache Clear)"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.success("Cache cleared! Please re-analyze.")

st.title("🐎 Keiba Analysis - Modified Ogura Index")
st.markdown("""
**Modified Ogura Flat Index (Speed Index Based + Deviation)**
- **SS Rank**: High Outlier (Top Class, Fixed 1st).
- **Outlier**: Low Outlier (Time limit exceeded, Excluded).
- **Flat Mode**: No class multipliers.
""")

def display_icon_legend():
    with st.expander("💡 アイコンの意味（クリックで開く）"):
        st.markdown("""
        **【総合評価・アラート（Alert）】**
        *   **💣 (爆弾): 絶対に3着に絡まない馬** (人気、スピード指数、オッズ、総合戦闘力が全て下位の馬。※単勝人気8位以内は除く)
        *   **💀 (ドクロ): 危険な馬** (スピード指数が下位8頭かつ総合戦闘力が下位9頭に含まれる馬。※単勝人気8位以内は除く)
        *   **🎯◎ (二重丸): 本命候補** (スピード指数 1位)
        *   **○ (丸): 対抗候補** (スピード指数 2位)
        *   **▲ (黒三角): 単穴候補** (スピード指数 3位)
        *   **⏱️ (時計): タイム指数保有** (過去走において優秀なタイム指数が記録されている馬)
        
        **【能力・適性・人気（各カラム）】**
        *   **🚀 (ロケット): 上がり最速（穴馬）** (過去データで上がり3Fが全体1位かつ信頼度高)
        *   **🦁 (ライオン): 先行馬** (過去の平均位置取りが5番手以内かつ信頼度高)
        *   **🔥 (炎): 上位人気馬** (現在の単勝人気が1〜3番人気の馬)
        """)

# Tab Layout
tab1, tab2, tab_betsync, tab3 = st.tabs(["Single Race Analysis", "Race Scanner (Batch)", "💰 BetSync（資金管理）", "📊 History & Review"])




# ──────────────────────────────────────────────
# 💰 BetSync（資金管理）タブ
# ──────────────────────────────────────────────
with tab_betsync:
    st.header("💰 BetSync — 資金管理ダッシュボード")
    st.caption("レースごとの勝敗を記録し、最適な賭け金と残高を自動計算します。")

    # ── 定数 ──
    ROKU_UNITS   = [100, 200, 300, 400, 500, 600]   # 6連法の単価ステップ
    TICKET_COUNT = {"3連複（15点）": 15, "馬連（5点）": 5}

    # ── Session State 初期化 ──
    _ss = st.session_state
    if 'bs_bankroll'  not in _ss: _ss['bs_bankroll']  = 20000
    if 'bs_init_bet'  not in _ss: _ss['bs_init_bet']  = 100
    if 'bs_target'    not in _ss: _ss['bs_target']    = 50
    if 'bs_strategy'  not in _ss: _ss['bs_strategy']  = "[稼働中] 6連サバイバル"
    if 'bs_ticket'    not in _ss: _ss['bs_ticket']    = "3連複（15点）"
    if 'bs_races'     not in _ss: _ss['bs_races']     = []   # start empty = Step 1 显示

    # ─────────────────────────────────────────
    # ① 基本設定パネル
    # ─────────────────────────────────────────
    STRATEGIES = [
        "[稼働中] 6連サバイバル",
        "[稼働中] 3Dリカバリ",
        "[開発中] ココモ加速",
        "[稼働中] ジワ上げ",
        "[開発中] 超追い上げ",
        "[稼働中] ウィナーズ",
    ]
    STRATEGY_INTERNAL = {s: "6連法（サバイバル）" for s in STRATEGIES}
    STRATEGY_INTERNAL["[稼働中] 3Dリカバリ"] = "3Dリカバリ"
    STRATEGY_INTERNAL["[稼働中] ジワ上げ"]   = "ジワ上げ"
    STRATEGY_INTERNAL["[稼働中] ウィナーズ"] = "ウィナーズ"
    STRATEGY_DESC = {
        "[開発中] ココモ加速":  "前2戦の負けを合算し、連敗時の威力を高める爆発型。",
        "[開発中] 超追い上げ":  "負けたら倍額+αを賭ける強気設定。",
    }
    # Migrate old session state strategy names
    if _ss['bs_strategy'] not in STRATEGIES:
        _ss['bs_strategy'] = STRATEGIES[0]

    with st.expander("⚙️ 基本設定（クリックで開閉）", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            _ss['bs_bankroll'] = st.number_input(
                "開始資金 (円)", min_value=1000, step=1000,
                value=_ss['bs_bankroll'], key="bs_bankroll_inp"
            )
        with c2:
            _ss['bs_target'] = st.number_input(
                "目標利回り (%)", min_value=1, max_value=1000, step=10,
                value=_ss['bs_target'], key="bs_target_inp"
            )
        with c3:
            _ss['bs_init_bet'] = st.number_input(
                "初期ベット単価 (円)", min_value=100, step=100,
                value=_ss['bs_init_bet'], key="bs_initbet_inp",
                help="6連法では初回の単価として使用します（固定100円推奨）"
            )

        cs1, cs2 = st.columns(2)
        with cs1:
            _ss['bs_strategy'] = st.selectbox(
                "ベット戦略",
                STRATEGIES,
                index=STRATEGIES.index(_ss['bs_strategy']),
                key="bs_strategy_sel"
            )
        with cs2:
            TICKET_OPTIONS = list(TICKET_COUNT.keys())
            _ss['bs_ticket'] = st.selectbox(
                "馬券種",
                TICKET_OPTIONS,
                index=TICKET_OPTIONS.index(_ss['bs_ticket']) if _ss['bs_ticket'] in TICKET_OPTIONS else 0,
                key="bs_ticket_sel",
                help="全損ラインと1レース投資額の計算に使用します"
            )

        # Strategy description card (for 開発中 strategies)
        _sel = _ss['bs_strategy']
        if _sel in STRATEGY_DESC:
            st.html(f"""<div style="background:#2a2a3a;border:1px solid #666;border-radius:8px;
            padding:10px 16px;color:#bbb;font-size:0.88em;">
  <strong style="color:#FF9800;">&#128679; 開発中</strong>&nbsp;&nbsp;{STRATEGY_DESC[_sel]}<br>
  <span style="font-size:0.82em;color:#888;">※ 開発中の戦略は「6連サバイバル」のロジックで代替動作します。</span>
</div>""")

        # 6連法の場合、全損ラインをリアルタイム表示
        if STRATEGY_INTERNAL.get(_ss['bs_strategy']) == "6連法（サバイバル）":
            tkt = _ss['bs_ticket']
            n   = TICKET_COUNT[tkt]
            total_loss = sum(u * n for u in ROKU_UNITS)
            st.html(f"""
<div style="background:#FFF3CD;border:2px solid #FFCA28;border-radius:8px;
            padding:12px 18px;font-size:0.92em;color:#856404;line-height:1.6;">
  <span style="font-size:1.05em;font-weight:bold;">&#x26A0;&#xFE0F; 6連法 全損ライン</span><br>
  {tkt} の場合、<strong>¥{total_loss:,}</strong> を超えると全損。<br>
  単価ステップ：{' &rarr; '.join(f'&yen;{u}' for u in ROKU_UNITS)}&nbsp;&nbsp;
  (1R投資：&yen;{ROKU_UNITS[0]*n:,}&sim;&yen;{ROKU_UNITS[-1]*n:,})
</div>""")

    # ─────────────────────────────────────────
    # 賭け金計算ロジック
    # ─────────────────────────────────────────
    bankroll  = _ss['bs_bankroll']
    init_bet  = _ss['bs_init_bet']
    strategy  = STRATEGY_INTERNAL.get(_ss['bs_strategy'], "6連法（サバイバル）")
    ticket    = _ss['bs_ticket']
    n_tickets = TICKET_COUNT[ticket]
    races     = _ss['bs_races']

    # --- 6連法：しきい値テーブル（チケット種別） ---
    # 各Stepの直前時点のサイクル累計マイナス額の上限
    # 例：3連複 Step1=0-1500, Step2=1501-4500 ...
    ROKU_THRESHOLDS = {
        "3連複（15点）": [0, 1500, 4500, 9000, 15000, 22500],  # >22500 = 全損
        "馬連（5点）":   [0,  500, 1500, 3000,  5000,  7500],  # >7500  = 全損
    }
    ROKU_TOTAL_LOSS_LINE = {
        "3連複（15点）": 22500,
        "馬連（5点）":    7500,
    }

    def _roku_step_from_deficit(deficit, thresholds):
        """Map cycle deficit → step index (0-5). Returns 6 if total loss."""
        if deficit <= 0:
            return 0  # recovered → Step 1
        for i, t in enumerate(thresholds[1:], 1):
            if deficit <= t:
                return i   # i=1→Step2, i=2→Step3, ...
        return 6  # beyond all thresholds = 全損

    computed      = []
    cum_bet       = 0
    cycle_deficit = 0
    _3d_seq        = [1, 1, 1]   # 3Dリカバリ
    _jiwa_unit     = 100          # ジワ上げ
    _win_seq       = []           # ウィナーズ: recovery sequence (empty = not triggered)
    _win_consec_loss = 0          # ウィナーズ: consecutive loss counter

    # Pre-compute the step for the NEXT (pending) race before the loop
    # so we can display it in the pending card
    decided_races = [r for r in races if r.get('decided', True)]

    for i, r in enumerate(races):
        # Skip undecided (pending) races in financial calculations
        if not r.get('decided', True):
            continue

        prev = computed[-1] if computed else None

        if strategy == "フラット（固定）":
            unit = init_bet
            step = 0
        elif strategy == "マーチンゲール（負け倍増）":
            unit = init_bet if (prev is None or prev['win']) else min(prev['unit'] * 2, init_bet * 16)
            step = 0
        elif strategy == "逆マーチン（勝ち倍増）":
            unit = min(prev['unit'] * 2, init_bet * 16) if (prev and prev['win']) else init_bet
            step = 0
        elif strategy == "3Dリカバリ":
            if not _3d_seq:
                _3d_seq = [1, 1, 1]
            _3d_mult = (_3d_seq[0] + _3d_seq[-1]) if len(_3d_seq) >= 2 else _3d_seq[0]
            unit = max(100, (_3d_mult * 50 // 100) * 100)
            step = len(_3d_seq)
        elif strategy == "ジワ上げ":
            unit = _jiwa_unit
            step = max(0, (unit - 100) // 100)
        elif strategy == "ウィナーズ":
            # Winners: flat 100 until 2-loss trigger, then leftmost*2*100
            if _win_seq:
                _win_mult = _win_seq[0] * 2
                unit = _win_mult * 100
                step = len(_win_seq)
            else:
                unit = 100
                _win_mult = 1
                step = 0
        else:  # 6連法 — step determined by cycle deficit BEFORE this race
            thresholds = ROKU_THRESHOLDS[ticket]
            step = _roku_step_from_deficit(cycle_deficit, thresholds)
            step = min(step, 5)
            unit = ROKU_UNITS[step]

        bet      = unit * n_tickets
        cum_bet += bet
        ret      = r.get('ret', 0) if r['win'] else 0

        # Update cycle deficit
        cycle_deficit = cycle_deficit + bet - ret

        overall_ret = sum((rr.get('ret', 0) if rr['win'] else 0) for rr in decided_races[:len(computed)+1])
        overall_profit = overall_ret - cum_bet
        balance = bankroll + overall_profit

        # Result type: compare ret vs THIS race's bet
        if ret == 0:
            result_type = "MISS"
        elif ret > bet:
            result_type = "PLUS"
        else:
            result_type = "GAMI"

        if cycle_deficit <= 0:
            cycle_deficit = 0

        # 3Dリカバリ: modify sequence after this race
        if strategy == "3Dリカバリ":
            if result_type == "MISS":
                _3d_seq.append(_3d_mult)
            elif result_type == "PLUS":
                _3d_seq = _3d_seq[1:-1] if len(_3d_seq) >= 2 else []
            elif result_type == "GAMI":
                _3d_seq = _3d_seq[1:] if _3d_seq else []
            if not _3d_seq:
                _3d_seq = [1, 1, 1]
        elif strategy == "ジワ上げ":
            if result_type == "MISS":
                _jiwa_unit += 100
            else:
                _jiwa_unit = max(100, _jiwa_unit - 100)
        elif strategy == "ウィナーズ":
            if _win_seq:   # sequence is active
                if result_type == "MISS":
                    _win_seq.append(_win_mult)
                else:  # PLUS or GAMI: remove leftmost
                    _win_seq = _win_seq[1:]
                    if not _win_seq:
                        _win_consec_loss = 0   # full reset
            else:          # sequence not started yet
                if result_type == "MISS":
                    _win_consec_loss += 1
                    if _win_consec_loss >= 2:
                        _win_seq = [1, 1]  # trigger!
                else:
                    _win_consec_loss = 0   # reset counter on any win

        computed.append({
            'race_idx':     races.index(r),
            'win':          r['win'],
            'unit':         unit,
            'step':         step,
            'bet':          bet,
            'cum_bet':      cum_bet,
            'ret':          ret,
            'profit':       overall_profit,
            'balance':      balance,
            'cycle_deficit':cycle_deficit,
            'result_type':  result_type,
        })

    # Next-race step/bet (for pending card)
    if strategy == "3Dリカバリ":
        if not _3d_seq:
            _3d_seq = [1, 1, 1]
        _nd_3d_mult = (_3d_seq[0] + _3d_seq[-1]) if len(_3d_seq) >= 2 else _3d_seq[0]
        _nd_unit = max(100, (_nd_3d_mult * 50 // 100) * 100)
        _nd_step = len(_3d_seq)
        _nd_bet  = _nd_unit * n_tickets
    elif strategy == "6連法（サバイバル）":
        _th = ROKU_THRESHOLDS[ticket]
        _nd_step = min(_roku_step_from_deficit(cycle_deficit, _th), 5)
        _nd_unit = ROKU_UNITS[_nd_step]
        _nd_bet  = _nd_unit * n_tickets
    elif strategy == "ジワ上げ":
        _nd_unit = _jiwa_unit
        _nd_step = max(0, (_jiwa_unit - 100) // 100)
        _nd_bet  = _nd_unit * n_tickets
    elif strategy == "ウィナーズ":
        if _win_seq:
            _nd_win_mult = _win_seq[0] * 2
            _nd_unit = _nd_win_mult * 100
            _nd_step = len(_win_seq)
        else:
            _nd_unit = 100
            _nd_step = 0
        _nd_bet = _nd_unit * n_tickets
    else:
        _nd_step = 0
        _nd_unit = init_bet
        _nd_bet  = _nd_unit * n_tickets



    # ─────────────────────────────────────────
    # ② サマリーメトリクス
    # ─────────────────────────────────────────
    st.divider()
    total_races   = len(computed)
    wins          = sum(1 for c in computed if c['win'])
    total_ret     = sum(c['ret'] for c in computed if c['win'])
    total_cum_bet = computed[-1]['cum_bet'] if computed else 0
    final_balance = computed[-1]['balance'] if computed else bankroll
    final_profit  = computed[-1]['profit']  if computed else 0
    target_profit = bankroll * _ss['bs_target'] / 100

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("現在残高",     f"¥{final_balance:,.0f}", f"{final_profit:+,.0f}")
    m2.metric("勝率",         f"{wins/total_races*100:.0f}%" if total_races else "—",
              f"{wins}勝 / {total_races-wins}敗")
    m3.metric("総投資額",     f"¥{total_cum_bet:,.0f}")
    m4.metric("総払戻金",     f"¥{total_ret:,.0f}")
    m5.metric("目標利益まで", f"¥{max(0, target_profit-final_profit):,.0f}",
              f"目標¥{target_profit:,.0f}")

    progress_pct = min(1.0, max(0.0, final_profit / target_profit)) if target_profit > 0 else 0
    st.progress(progress_pct, text=f"目標達成率: {progress_pct*100:.1f}%")

    # ─────────────────────────────────────────
    # 6連法：ステッパー（サイクル赤字に応じた自動進行）
    # ─────────────────────────────────────────
    if strategy == "6連法（サバイバル）":
        # Determine NEXT step from current cycle_deficit (end of all computed races)
        thresholds  = ROKU_THRESHOLDS[ticket]
        total_loss_line = ROKU_TOTAL_LOSS_LINE[ticket]
        # cycle_deficit was reset to 0 if it went <=0; take from last computed entry if any
        cur_deficit = computed[-1]['cycle_deficit'] if computed else 0
        next_step   = _roku_step_from_deficit(cur_deficit, thresholds)
        is_total_loss = cur_deficit > total_loss_line

        if is_total_loss:
            st.error(f"🚨 **全損到達（累計赤字 ¥{cur_deficit:,.0f}）。** サイクルをリセットして第1回目から再開してください。")
        else:
            next_step  = min(next_step, 5)
            next_unit  = ROKU_UNITS[next_step]
            next_bet   = next_unit * n_tickets
            is_danger  = cur_deficit > thresholds[3] if len(thresholds) > 3 else False  # Step4以上

            # Visual stepper pills
            step_pills = ""
            for j in range(6):
                is_active  = (j == next_step)
                is_d       = (is_danger and is_active)
                pill_bg    = "#FF6B00" if is_d else ("#FFD700" if is_active else "transparent")
                pill_color = "#000"    if is_active else "#DDD"   # DDD = readable on dark bg
                pill_border= "#FF6B00" if is_d else ("#FFD700" if is_active else "#666")
                pill_size  = "1.05em" if is_active else "0.85em"
                pill_label = f"Step {j+1}<br><span style='font-size:0.78em;'>&#165;{ROKU_UNITS[j]*n_tickets:,}</span>"
                connector  = "" if j == 0 else "<span style='color:#888;padding:0 4px;'>&mdash;</span>"
                step_pills += f"""
{connector}<span style='display:inline-block;text-align:center;padding:6px 12px;
  background:{pill_bg};color:{pill_color};border:2px solid {pill_border};
  border-radius:20px;font-size:{pill_size};font-weight:{'bold' if is_active else 'normal'};
  line-height:1.4;vertical-align:middle;'>{pill_label}</span>"""

            deficit_pct = cur_deficit / total_loss_line if total_loss_line > 0 else 0
            danger_note = f"<span style='color:#FF6B6B;font-size:0.9em;'>⚠️ サイクル赤字：¥{cur_deficit:,.0f} / 全損ライン：¥{total_loss_line:,}</span>" if cur_deficit > 0 else "<span style='color:#6FE09A;'>✅ サイクルプラス — Step 1リセット</span>"
            border_color = "#FF6B00" if is_danger else "#FFD700"
            bg_color     = "#1f0800" if is_danger else "#1a1400"
            st.html(f"""
<div style="border:2px solid {border_color};border-radius:10px;padding:14px 18px;margin:12px 0;background:{bg_color};">
  <div style="font-size:0.82em;color:#888;margin-bottom:10px;letter-spacing:.05em;">📊 6連法 ステッパー（サイクル赤字に応じた自動進行）</div>
  <div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-bottom:12px;">{step_pills}</div>
  <div style="font-size:1.05em;">
    ▶ 次回のベット：
    <strong style="color:{border_color};font-size:1.25em;">¥{next_bet:,.0f}</strong>
    <span style="color:#aaa;font-size:0.85em;">（単価 ¥{next_unit} × {n_tickets}点）</span>
    &nbsp;&nbsp;{danger_note}
  </div>
</div>""")

    # ─────────────────────────────────────────
    # 3Dリカバリ：数列ディスプレイ
    # ─────────────────────────────────────────
    elif strategy == "3Dリカバリ":
        seq_display = ', '.join(str(x) for x in _3d_seq)
        _3d_next_mult = (_3d_seq[0] + _3d_seq[-1]) if len(_3d_seq) >= 2 else (_3d_seq[0] if _3d_seq else 1)
        _3d_raw  = _3d_next_mult * 50
        _3d_next_unit = max(100, (_3d_raw // 100) * 100)
        _3d_truncated = (_3d_raw % 100) > 0   # 50円端数があるか
        _3d_next_bet  = _3d_next_unit * n_tickets
        seq_len = len(_3d_seq)
        # Color: green if short (recovering), orange/red if long (deep)
        if seq_len <= 3:
            _3d_border = "#4CAF50"
            _3d_bg     = "#0a1f0a"
            _3d_status = "<span style='color:#6FE09A;'>&#10003; 数列が短い = リカバリー順調</span>"
        elif seq_len <= 5:
            _3d_border = "#FFD700"
            _3d_bg     = "#1a1400"
            _3d_status = "<span style='color:#FFD700;'>⚠️ 数列が伸びています</span>"
        else:
            _3d_border = "#FF6B00"
            _3d_bg     = "#1f0800"
            _3d_status = "<span style='color:#FF6B6B;'>🚨 数列が長い = 深追い中</span>"

        # Build sequence pills
        seq_pills = ""
        for si, sv in enumerate(_3d_seq):
            is_edge = (si == 0 or si == len(_3d_seq) - 1)
            p_bg   = "#FFD700" if is_edge else "transparent"
            p_col  = "#000" if is_edge else "#DDD"
            p_bdr  = "#FFD700" if is_edge else "#666"
            p_fw   = "bold" if is_edge else "normal"
            seq_pills += f"<span style='display:inline-block;padding:4px 10px;background:{p_bg};color:{p_col};border:2px solid {p_bdr};border-radius:16px;font-size:0.95em;font-weight:{p_fw};margin:2px 3px;'>{sv}</span>"

        st.html(f"""
<div style="border:2px solid {_3d_border};border-radius:10px;padding:14px 18px;margin:12px 0;background:{_3d_bg};">
  <div style="font-size:0.82em;color:#888;margin-bottom:10px;letter-spacing:.05em;">
    &#127922; 3Dリカバリ 数列モニター（モンテカルロ方式）
  </div>
  <div style="margin-bottom:10px;">{seq_pills}</div>
  <div style="font-size:0.88em;color:#aaa;margin-bottom:8px;">
    数列: [{seq_display}]&nbsp;&nbsp;(要素数: {seq_len})
    &nbsp;&nbsp;{_3d_status}
  </div>
  <div style="font-size:1.05em;">
    &#9654; 次回のベット：
    <strong style="color:{_3d_border};font-size:1.25em;">&#165;{_3d_next_bet:,.0f}</strong>
    <span style="color:#aaa;font-size:0.85em;">（単価 &#165;{_3d_next_unit:,} = [{_3d_seq[0]}+{_3d_seq[-1] if len(_3d_seq)>=2 else 0}] &times; 50{' <span style="color:#FF9800;font-size:0.85em;">(50円端数切捨)</span>' if _3d_truncated else ''} &times; {n_tickets}点）</span>
  </div>
</div>""")

    # -----------------------------------------
    # jiwa-age display
    # -----------------------------------------
    elif strategy == "jiwa-age-placeholder":
        pass  # placeholder to avoid syntax issues

    if strategy == "ジワ上げ":
        _jw_level = (_jiwa_unit - 100) // 100  # 0 = base
        if _jiwa_unit <= 200:
            _jw_border = "#4CAF50"; _jw_bg = "#0a1f0a"
            _jw_status = "<span style='color:#6FE09A;'>&#10003; 低単価ゾーン（守備的）</span>"
        elif _jiwa_unit <= 400:
            _jw_border = "#FFD700"; _jw_bg = "#1a1400"
            _jw_status = "<span style='color:#FFD700;'>&#9888;&#65039; 中単価ゾーン</span>"
        else:
            _jw_border = "#FF6B00"; _jw_bg = "#1f0800"
            _jw_status = "<span style='color:#FF6B6B;'>&#128680; 高単価ゾーン（注意）</span>"

        # Build step pills for 100-600
        _jw_pills = ""
        for jp in range(6):
            jp_unit = (jp + 1) * 100
            jp_active = (jp_unit == _jiwa_unit)
            jp_bg  = "#FFD700" if jp_active else "transparent"
            jp_col = "#000" if jp_active else "#DDD"
            jp_bdr = "#FFD700" if jp_active else "#666"
            jp_fw  = "bold" if jp_active else "normal"
            jp_sz  = "1.05em" if jp_active else "0.85em"
            connector = "" if jp == 0 else "<span style='color:#888;padding:0 4px;'>&mdash;</span>"
            _jw_pills += f"""{connector}<span style='display:inline-block;text-align:center;padding:6px 12px;
  background:{jp_bg};color:{jp_col};border:2px solid {jp_bdr};
  border-radius:20px;font-size:{jp_sz};font-weight:{jp_fw};
  line-height:1.4;vertical-align:middle;'>&#165;{jp_unit}<br><span style='font-size:0.78em;'>&#165;{jp_unit*n_tickets:,}</span></span>"""

        # Direction arrow
        if computed:
            last_rt = computed[-1]['result_type']
            if last_rt == "MISS":
                _jw_arrow = "<span style='color:#FF6B6B;font-size:1.1em;'>&#9650; +100</span>"
            else:
                _jw_arrow = "<span style='color:#6FE09A;font-size:1.1em;'>&#9660; -100</span>"
        else:
            _jw_arrow = "<span style='color:#aaa;'>&#8212; \u521d\u671f\u72b6\u614b</span>"

        st.html(f"""
<div style="border:2px solid {_jw_border};border-radius:10px;padding:14px 18px;margin:12px 0;background:{_jw_bg};">
  <div style="font-size:0.82em;color:#888;margin-bottom:10px;letter-spacing:.05em;">
    &#128737; \u30b8\u30ef\u4e0a\u3052 \u5358\u4fa1\u30e2\u30cb\u30bf\u30fc\uff08\u30c0\u30e9\u30f3\u30d9\u30fc\u30eb\u65b9\u5f0f\uff09
    &nbsp;&nbsp;<span style="font-size:0.9em;">\u8ca0\u3051\u2192+100 / \u52dd\u3061\u30fb\u30ac\u30df\u2192-100 (\u6700\u4f4e100)</span>
  </div>
  <div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-bottom:12px;">{_jw_pills}</div>
  <div style="font-size:0.88em;color:#aaa;margin-bottom:8px;">
    \u73fe\u5728\u5358\u4fa1: <strong style="color:#FFF;">&#165;{_jiwa_unit:,}</strong>
    &nbsp;&nbsp;{_jw_arrow}&nbsp;&nbsp;{_jw_status}
  </div>
  <div style="font-size:1.05em;">
    &#9654; \u6b21\u56de\u306e\u30d9\u30c3\u30c8\uff1a
    <strong style="color:{_jw_border};font-size:1.25em;">&#165;{_jiwa_unit*n_tickets:,.0f}</strong>
    <span style="color:#aaa;font-size:0.85em;">\uff08\u5358\u4fa1 &#165;{_jiwa_unit:,} &times; {n_tickets}\u70b9\uff09</span>
  </div>
</div>""")


    # -----------------------------------------
    # winners display
    # -----------------------------------------
    elif strategy == "ウィナーズ":
        if _win_seq:
            seq_display = ', '.join(str(x) for x in _win_seq)
            _wn_next_mult = _win_seq[0] * 2
            _wn_next_unit = _wn_next_mult * 100
            _wn_next_bet  = _wn_next_unit * n_tickets
            seq_len = len(_win_seq)
            
            _wn_border = "#FFD700"
            _wn_bg     = "#1a1400"
            _wn_status = "<span style='color:#FFD700;'>&#9888;&#65039; リカバリー実行中</span>"

            # Build sequence pills
            seq_pills = ""
            for si, sv in enumerate(_win_seq):
                is_edge = (si == 0) # left edge
                p_bg   = "#FFD700" if is_edge else "transparent"
                p_col  = "#000" if is_edge else "#DDD"
                p_bdr  = "#FFD700" if is_edge else "#666"
                p_fw   = "bold" if is_edge else "normal"
                seq_pills += f"<span style='display:inline-block;padding:4px 10px;background:{p_bg};color:{p_col};border:2px solid {p_bdr};border-radius:16px;font-size:0.95em;font-weight:{p_fw};margin:2px 3px;'>{sv}</span>"

            st.html(f"""
<div style="border:2px solid {_wn_border};border-radius:10px;padding:14px 18px;margin:12px 0;background:{_wn_bg};">
  <div style="font-size:0.82em;color:#888;margin-bottom:10px;letter-spacing:.05em;">
    &#127919; ウィナーズ 数列モニター（2連敗で始動）
    &nbsp;&nbsp;<span style="font-size:0.9em;">負け&rarr;右端追加 / 勝ち・ガミ&rarr;左端削除</span>
  </div>
  <div style="margin-bottom:10px;">{seq_pills}</div>
  <div style="font-size:0.88em;color:#aaa;margin-bottom:8px;">
    数列: [{seq_display}]&nbsp;&nbsp;(要素数: {seq_len})
    &nbsp;&nbsp;{_wn_status}
  </div>
  <div style="font-size:1.05em;">
    &#9654; 次回のベット：
    <strong style="color:{_wn_border};font-size:1.25em;">&#165;{_wn_next_bet:,.0f}</strong>
    <span style="color:#aaa;font-size:0.85em;">&#xff08;単価 &#165;{_wn_next_unit:,} = [{_win_seq[0]}] &times; 2 &times; 100 &times; {n_tickets}点&#xff09;</span>
  </div>
</div>""")
        else:
            _wn_border = "#4CAF50"
            _wn_bg     = "#0a1f0a"
            _wn_status = "<span style='color:#6FE09A;'>&#10003; 待機中&#xff08;2連敗で始動&#xff09;</span>"
            if _win_consec_loss == 1:
                _wn_status = "<span style='color:#FFD700;'>&#9888;&#65039; 1敗中&#xff08;次負けると始動&#xff09;</span>"
                _wn_border = "#FFD700"
                _wn_bg     = "#1a1400"

            st.html(f"""
<div style="border:2px solid {_wn_border};border-radius:10px;padding:14px 18px;margin:12px 0;background:{_wn_bg};">
  <div style="font-size:0.82em;color:#888;margin-bottom:10px;letter-spacing:.05em;">
    &#127919; ウィナーズ 数列モニター&#xff08;2連敗で始動&#xff09;
  </div>
  <div style="font-size:0.88em;color:#aaa;margin-bottom:8px;">
    数列: [ 未始動 ]&nbsp;&nbsp;{_wn_status}
  </div>
  <div style="font-size:1.05em;">
    &#9654; 次回のベット：
    <strong style="color:{_wn_border};font-size:1.25em;">&#165;{init_bet * n_tickets:,.0f}</strong>
    <span style="color:#aaa;font-size:0.85em;">&#xff08;単価 &#165;{init_bet:,} &times; {n_tickets}点&#xff09;</span>
  </div>
</div>""")

    # レース履歴テーブル（カード型）
    # ─────────────────────────────────────────
    st.divider()
    st.subheader("📋 レース履歴")

    if not races:
        st.html("""
<div style="border:2px dashed #555;border-radius:10px;padding:20px;
            text-align:center;color:#888;font-size:0.95em;">
  まだレースが記録されていません。<br>
  下の「＋ 次のレースを追加」ボタンで R1 を開始してください。
</div>""")
    else:
        comp_idx = 0
        for ri, r in enumerate(races):
            is_pending = not r.get('decided', True)
            rnum = ri + 1

            if is_pending:
                # ── 未確定行：賭け金指示カード ──
                st_tag = f"Step {_nd_step+1}" if strategy == "6連法（サバイバル）" else ""
                step_label = f" — {st_tag}" if st_tag else ""
                ul = f"単価¥{_nd_unit:,}×{n_tickets}点" if strategy == "6連法（サバイバル）" else f"¥{_nd_bet:,}"
                st.html(f"""
<div style="border:2px solid #FFD700;border-radius:10px;padding:12px 16px;
            margin-bottom:4px;background:#1a1400;">
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
    <span style="font-weight:bold;font-size:1em;color:#FFF;min-width:34px;">R{rnum}</span>
    <span style="color:#aaa;font-size:0.82em;">&#9651; 未入力</span>
    <span style="color:#FFD700;font-size:0.97em;font-weight:bold;">
      &#9654; 今回の賭け金{step_label}：
      <strong style="font-size:1.22em;">&#165;{_nd_bet:,.0f}</strong>
      <span style="font-size:0.82em;color:#aaa;">({ul})</span>
    </span>
  </div>
  <div style="font-size:0.82em;color:#aaa;margin-top:6px;">
    &#8595; レース終了後、下の「勝 / 負」を選択して結果を入力してください。
  </div>
</div>""")
                inp_c1, inp_c2, inp_c3 = st.columns([1.5, 3, 0.7])
                with inp_c1:
                    radio_val = st.radio(
                        "",
                        options=["❌ 負", "✅ 勝"],
                        index=None,
                        horizontal=True,
                        key=f"bs_radio_{ri}",
                        label_visibility="collapsed"
                    )
                    if radio_val is not None:
                        _ss['bs_races'][ri]['win'] = (radio_val == "✅ 勝")
                        _ss['bs_races'][ri]['decided'] = True
                        if not _ss['bs_races'][ri]['win']:
                            _ss['bs_races'][ri]['ret'] = 0
                        st.rerun()
                with inp_c2:
                    st.caption("← 勝敗を選択すると結果が表示されます")
                with inp_c3:
                    if ri > 0:
                        if st.button("🗑️ 削除", key=f"bs_del_{ri}"):
                            _ss['bs_races'].pop(ri)
                            st.rerun()
            else:
                # ── 確定済み行：結果カード ──
                c = computed[comp_idx]
                comp_idx += 1
                bg          = "#1a3a1f" if c['win'] else "#2a1515"
                border      = "#4CAF50" if c['win'] else "#F44336"
                result_icon = "✅ 勝"   if c['win'] else "❌ 負"

                if strategy == "6連法（サバイバル）":
                    rt = c['result_type']
                    if rt == "PLUS":
                        badge = "<span style='background:#1a4a2a;color:#6FE09A;border:1px solid #6FE09A;border-radius:4px;padding:2px 6px;font-size:0.8em;font-weight:bold;'>✅プラス</span>"
                    elif rt == "GAMI":
                        badge = "<span style='background:#3a2a00;color:#FFB347;border:1px solid #FFB347;border-radius:4px;padding:2px 6px;font-size:0.8em;font-weight:bold;'>⚠️ガミ</span>"
                    else:
                        badge = "<span style='background:#3a0000;color:#FF7070;border:1px solid #FF7070;border-radius:4px;padding:2px 6px;font-size:0.8em;font-weight:bold;'>❌ハズレ</span>"
                else:
                    badge = ""

                ul = f"単価¥{c['unit']:,}×{n_tickets}点" if strategy == "6連法（サバイバル）" else f"¥{c['bet']:,}"
                step_tag = f"<span style='color:#aaa;font-size:0.78em;background:#333;padding:1px 5px;border-radius:10px;'>Step {c['step']+1}</span>" if strategy == "6連法（サバイバル）" else ""

                st.html(f"""
<div style="background:{bg};border-left:5px solid {border};border-radius:8px;
            padding:9px 14px;margin-bottom:2px;display:flex;align-items:center;
            gap:12px;flex-wrap:wrap;">
  <span style="font-weight:bold;font-size:1em;color:#FFF;min-width:34px;">R{rnum}</span>
  {step_tag}
  <span style="color:{border};font-weight:bold;">{result_icon}</span>
  {badge}
  <span style="color:#ccc;font-size:0.86em;">ベット <strong style="color:#FFF;">¥{c['bet']:,.0f}</strong>
    <span style="font-size:0.78em;color:#aaa;">({ul})</span></span>
  <span style="color:#ccc;font-size:0.86em;">累計投資 <strong style="color:#FFF;">¥{c['cum_bet']:,.0f}</strong></span>
  <span style="color:#ccc;font-size:0.86em;">払戻 <strong style="color:#FFF;">¥{c['ret']:,.0f}</strong></span>
  <span style="color:#ccc;font-size:0.86em;">利益
    <strong style="color:{'#6FE09A' if c['profit']>=0 else '#FF7070'};">¥{c['profit']:+,.0f}</strong></span>
  <span style="color:#ccc;font-size:0.86em;">残高 <strong style="color:#FFD700;">¥{c['balance']:,.0f}</strong></span>
</div>""")
                ec1, ec2 = st.columns([1, 4])
                with ec1:
                    rv = st.radio(
                        "",
                        options=["❌ 負", "✅ 勝"],
                        index=1 if races[ri]['win'] else 0,
                        horizontal=True,
                        key=f"bs_radio_{ri}",
                        label_visibility="collapsed"
                    )
                    nw = (rv == "✅ 勝")
                    if nw != races[ri]['win']:
                        _ss['bs_races'][ri]['win'] = nw
                        if not nw:
                            _ss['bs_races'][ri]['ret'] = 0
                        st.rerun()
                with ec2:
                    if races[ri]['win']:
                        nr = st.number_input(
                            "💴 払い戻し金入力",
                            min_value=0, step=100,
                            value=int(races[ri].get('ret', 0)),
                            key=f"bs_ret_{ri}",
                            placeholder="払戻金額を入力",
                            help="実際に受け取った払い戻し金額を入力してください"
                        )
                        if nr != races[ri].get('ret', 0):
                            _ss['bs_races'][ri]['ret'] = nr
                            st.rerun()
                        if nr > c['bet']:
                            st.success("✅ プラス（このレースで利益）", icon=None)
                        elif nr > 0:
                            st.warning("⚠️ ガミ（一部回収・赤字継続）", icon=None)
                    else:
                        st.caption("❌ ハズレ — 払い戻しなし")
                if ri > 0 and ri == len(races) - 1:
                    if st.button("🗑️ 削除", key=f"bs_del_{ri}"):
                        _ss['bs_races'].pop(ri)
                        st.rerun()

    # ─────────────────────────────────────────
    # 追加 / リセット ボタン
    # ─────────────────────────────────────────
    st.divider()
    badd, breset = st.columns([2, 1])
    # Guard: prevent adding new race before deciding the current one
    _last_pending = bool(races) and not races[-1].get('decided', True)
    _add_label = "➕ 次のレースを追加"
    if not _last_pending and races:
        _add_label += f" （次は Step {_nd_step+1} / ¥{_nd_bet:,.0f}）"

    with badd:
        if st.button(_add_label, type="primary", key="bs_add",
                     disabled=_last_pending,
                     help="現在のレースの勝敗を確定してから次のレースを追加してください" if _last_pending else None):
            _ss['bs_races'].append({'win': False, 'ret': 0, 'decided': False})
            st.rerun()
    if _last_pending:
        st.caption("⚠️ 上のレースの勝敗（✅・❌）を選択してから次のレースを追加できます。")
    with breset:
        if st.button("🔄 リセット（最初からやり直す）", key="bs_reset"):
            _ss['bs_races'] = []
            _ss['bs_strategy'] = "[稼働中] 6連サバイバル"   # ステッパーを確実に表示
            st.rerun()












# --- Tab 1: Single Race Analysis (Main View) ---
with tab1:

    # Handle Query Params for Race ID
    query_params = st.query_params
    default_id = "202608020211"
    
    if "race_id" in query_params:
        default_id = query_params["race_id"]
        
    if 'main_race_id_input' not in st.session_state:
        st.session_state['main_race_id_input'] = default_id

    def _on_main_race_id_change():
        import re
        val = st.session_state['main_race_id_input']
        match = re.search(r'race_id=(\d{12})', val)
        if not match:
            match = re.search(r'(\d{12})', val)
        if match:
            extracted = match.group(1)
            if extracted != val:
                st.session_state['main_race_id_input'] = extracted
                st.session_state['main_race_id_extracted'] = True

    # Input
    col1, col2 = st.columns([1, 2])
    with col1:
        race_id_input = st.text_input("Race ID (Netkeiba)", key='main_race_id_input', on_change=_on_main_race_id_change)
        
        if st.session_state.get('main_race_id_extracted', False):
            st.success("✨ URLからレースIDを自動抽出しました！", icon="✅")
            st.session_state['main_race_id_extracted'] = False

        st.caption("Example: 202608020211 または Netkeiba の URL をそのまま貼り付けてもOK")
        
        race_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id_input}"
        st.markdown(f"🔗 **[Netkeiba レースページを開く]({race_url})**")
        
        analyze_btn = st.button("Analyze Race", type="primary")
        if analyze_btn:
            st.session_state['tab1_analyzed_id'] = race_id_input
        
    if analyze_btn or ("race_id" in query_params and race_id_input == default_id) or st.session_state.get('tab1_analyzed_id') == race_id_input:
        with st.spinner("Fetching data and calculating indices..."):
            try:
                # 1. Fetch Data
                df = scraper.get_race_data(race_id_input)
                
                if df.empty:
                    st.error("No data found for this Race ID.")
                else:
                    # 2. Calculate
                    df = calculator.calculate_battle_score(df)
                    df = calculator.calculate_n_index(df) # NEW
                    
                    # --- RESURRECTED: Race Rating Header ---
                    score, rating, reasons = calculator.calculate_confidence(df) if hasattr(calculator, 'calculate_confidence') else (0, 'C', [])
                    
                    # Icon
                    rating_icon = "💣" # C
                    if rating == "S": rating_icon = "🔥🔥"
                    elif rating == "A": rating_icon = "🔥"
                    elif rating == "B": rating_icon = "⚖️"
                    
                    try:
                         st.markdown(f"## Race Rating: {rating_icon} {rating} (Score: {score})")
                         st.progress(min(score, 100) / 100.0)
                         if reasons:
                             st.caption(f"Reason: {', '.join(reasons)}")
                    except: pass
                    # ---------------------------------------
                    
                    # 3. Display
                    
                    # Top Table
                    st.subheader("📊 Ranking & Direct Match")
                    display_icon_legend()
                     
                    # 1. Icons & Formatting
                    # Popularity Icon (🔥 for 1-3 Pop)
                    if 'Popularity' in df.columns:
                        def fmt_pop_name(row):
                            name = row['Name']
                            try:
                                pop = int(row['Popularity'])
                                if pop <= 3:
                                    return f"{name} (🔥)"
                            except:
                                pass
                            return name
                        df['Name'] = df.apply(fmt_pop_name, axis=1)

                    # Jockey
                    if 'Jockey' in df.columns:
                        df = calculator.apply_jockey_icons(df)

                        
                    # Speed Index Rank (Shortened)
                    if 'SpeedIndex' in df.columns:
                        df['SpRank'] = df['SpeedIndex'].rank(ascending=False, method='min')
                    
                    view_df = df.copy()

                    # --- Sorting by Battle Score ---
                    if 'BattleScore' in view_df.columns:
                        view_df = view_df.sort_values(by='BattleScore', ascending=False).reset_index(drop=True)
                    
                    # --- Alert Column Logic ---
                    # Logic is centralized in calculator.py to ensure consistency.
                    # Add ⏱️ icon if TimeIndexAvg5 > 0
                    if 'TimeIndexAvg5' in view_df.columns:
                        def add_time_icon(row):
                            alert = row.get('Alert', '')
                            # Ensure alert is a string
                            if not isinstance(alert, str): alert = ''
                            if row.get('TimeIndexAvg5', 0) > 0:
                                if '⏱️' not in alert:
                                    return alert + ' ⏱️'
                            return alert
                        view_df['Alert'] = view_df.apply(add_time_icon, axis=1)
                             
                    # Rank Re-assignment for Display (Relative to BattleScore)
                    view_df['Rank'] = range(1, len(view_df) + 1)

                    # --- Sorting by Horse Number (Umaban) for Display ---
                    if 'Umaban' in view_df.columns:
                        view_df = view_df.sort_values(by='Umaban').reset_index(drop=True)


                    # カラム順序の確定と整理
                    cols = ['Rank', 'Umaban', 'Name', 'Popularity', 'Odds', 'Jockey', 'BattleScore', 'OguraIndex', 'AvgAgari', 'AvgPosition', 'Alert']
                    view_df = view_df[[c for c in cols if c in view_df.columns]]
                    
                    # Format Agari (34.5 (1))
                    def fmt_agari(row):
                        a = row.get('AvgAgari', 99.9)
                        r = row.get('AgariRank', 99)
                        trusted = row.get('AgariTrust', False)
                        
                        if a >= 99.0: return "-"
                        try:
                            r_int = int(r)
                            # Only show Rocket if Rank 1 AND Trusted
                            icon = " 🚀" if (r_int == 1 and trusted) else ""
                            # Maybe mark imputed data with (?) or color?
                            # User just said "Don't show Rocket if imputed".
                            return f"{a:.1f} ({r_int}位){icon}"
                        except:
                            return f"{a:.1f}"

                    view_df['AvgAgari'] = df.apply(fmt_agari, axis=1)

                    # Format Position (2.5 🦁)
                    def fmt_pos(row):
                        p = row.get('AvgPosition', 99.9)
                        trusted = row.get('PosTrust', False)
                        
                        if p >= 99.0: return "-"
                        # If AvgPos <= 5 AND Trusted, add Lion
                        icon = " 🦁" if (p <= 5.0 and trusted) else ""
                        return f"{p:.1f}{icon}"
                        
                    view_df['AvgPosition'] = df.apply(fmt_pos, axis=1)

                    column_config = {
                        "BattleScore": st.column_config.NumberColumn("🔥 総合戦闘力", format="%.1f"),
                        "OguraIndex": st.column_config.NumberColumn("スピード指数 (旧)", format="%.1f"),
                        "AvgAgari": st.column_config.TextColumn("上がり3F (順位)"),
                        "AvgPosition": st.column_config.TextColumn("平均位置取り"),
                        "Umaban": st.column_config.NumberColumn("馬番"),
                        "Jockey": st.column_config.TextColumn("騎手"),
                        "Odds": st.column_config.NumberColumn("単勝オッズ", format="%.1f"),
                        "Popularity": st.column_config.NumberColumn("人気", format="%d"),
                    }

                    # Create styled_df with refined colors
                    try:
                        styled_df = view_df.style.format({
                            "BattleScore": "{:.1f}",
                            "OguraIndex": "{:.1f}",
                        })
                        
                        # Apply Color to BattleScore
                        def color_battle(s):
                            colors = []
                            for val in s:
                                try:
                                    v = float(val)
                                    if v >= 65: 
                                        colors.append("background-color: #cc0000; color: white") # Dark Red
                                    elif v >= 50: 
                                        colors.append("background-color: #ccffcc; color: black") # Green
                                    else: 
                                        colors.append("background-color: #0000cc; color: white") # Dark Blue
                                except:
                                    colors.append("")
                            return colors

                        def color_rank(s):
                            colors = []
                            for val in s:
                                try:
                                    v = int(val)
                                    if 1 <= v <= 5:
                                        colors.append("background-color: yellow; color: black") # Yellow
                                    else:
                                        colors.append("")
                                except:
                                    colors.append("")
                            return colors


                        def color_alert(s):
                            colors = []
                            for val in s:
                                if "💣" in str(val): colors.append("background-color: #444444; color: white; font-weight: bold")
                                elif "🎯" in str(val): colors.append("font-weight: bold; color: yellow")
                                elif "🚀" in str(val): colors.append("font-weight: bold; color: red")
                                elif "💀" in str(val): colors.append("font-weight: bold; color: gray")
                                else: colors.append("")
                            return colors
                            
                        def row_style(row):
                            if '💣' in str(row.get('Alert', '')) or '💀' in str(row.get('Alert', '')):
                                return ['background-color: #2F4F4F; color: #CCCCCC'] * len(row)
                            return [''] * len(row)


                        styled_df = styled_df.apply(color_battle, axis=0, subset=['BattleScore'])
                        if 'Rank' in view_df.columns:
                            styled_df = styled_df.apply(color_rank, axis=0, subset=['Rank'])
                        if 'Alert' in view_df.columns:
                            styled_df = styled_df.apply(color_alert, axis=0, subset=['Alert'])
                            styled_df = styled_df.apply(row_style, axis=1)
                        
                        st.dataframe(
                            styled_df,
                            column_config=column_config,
                            use_container_width=True,
                            hide_index=True
                        )
                    except Exception as e:
                        st.warning(f"Display Error (Showing raw data): {e}")
                        st.dataframe(view_df)

                    # --- Betting Strategy (Resurrected) ---
                    st.divider()
                    st.subheader("🎯 Betting Strategy")
                    
                    # 1. Strategy Advice
                    strat_text = ""
                    if rating in ["S", "A"]:
                        strat_text = "🔥 **Banker Race (鉄板)**: The Axis horse is very strong. Focus on 3-Ren-Tan (Trifecta) or Uma-Tan."
                        st.success(strat_text)
                    elif rating == "B":
                        strat_text = "⚖️ **Balanced Race**: Good for Wide or 3-Ren-Puku (Trio) flow from top horses to Rocket candidates."
                        st.info(strat_text)
                    else:
                        strat_text = "💣 **Chaos Race**: High variance. Recommended Box betting or targeting Rocket horses for high payout."
                        st.warning(strat_text)
                        
                    # 2. Betting Proposal (Columns)
                    c_bet1, c_bet2 = st.columns(2)
                    
                    # Get Advice Data using correct function name
                    advice = calculator.get_betting_recommendation(df) if hasattr(calculator, 'get_betting_recommendation') else None
                    
                    with c_bet1:
                        st.markdown("#### 📦 Recommended Box / Flow")
                        if advice and isinstance(advice, dict):
                             st.write(f"**Type**: {advice.get('Type', '-')}")
                             st.write(f"**Horses**: {advice.get('Horses', '-')}")
                             st.caption(f"Reason: {advice.get('Reason', '-')}")
                        else:
                             st.write("No specific advice generated.")
                             
                    with c_bet2:
                        st.markdown("#### ⚠️ Danger & Rocket")
                        rockets = df[df['Alert'].astype(str).str.contains("🚀")]
                        dangers = df[df['Alert'].astype(str).str.contains("💀")]
                        
                        if not rockets.empty:
                            r_names = ", ".join(rockets['Name'].tolist())
                            st.write(f"🚀 **Rocket**: {r_names}")
                        else:
                            st.write("🚀 Rocket: None")
                            
                        if not dangers.empty:
                            d_names = ", ".join(dangers['Name'].tolist())
                            st.write(f"💀 **Danger**: {d_names}")
                        else:
                            st.write("💀 Danger: None")
                    # --------------------------------------
                    
                    # --- 指数該当・人気順10選 ---
                    st.divider()
                    st.subheader("🎯 指数該当・人気順10選")
                    st.caption("BattleScore上位5頭を含む買い目を人気順から抽出")
                    with st.spinner("オッズ取得・計算中..."):
                        try:
                            odds_list = scraper.fetch_sanrenpuku_odds(race_id_input)
                            recs = calculator.get_sanrenpuku_recommendations(df, odds_list)
                            
                            if recs:
                                rec_df = pd.DataFrame([
                                    {
                                        "人気順位": f"{r['Rank']}人気",
                                        "買い目": r['Combination'],
                                        "馬名組み合わせ": r['HorseNames'],
                                        "オッズ": f"{r['Odds']}倍",
                                    } for r in recs
                                ])
                                st.table(rec_df)
                            else:
                                st.info("オッズが取得できなかったか、該当する買い目が見つかりませんでした。（発売前の場合は発売開始後に再度お試しください）")
                        except Exception as e:
                            st.error(f"3連複推奨データの取得中にエラーが発生しました: {e}")

                    # --- ３連複スペシャル（2頭軸流し自動生成） ---
                    st.divider()
                    st.subheader("🌟 ３連複スペシャル（2頭軸流し自動生成）")
                    st.caption("軸馬を「2頭だけ」選ぶと、残りの馬からシステム推奨のヒモ（相手）を自動選出します。")
                    
                    # Create choices in the format [Umaban] Name
                    horse_choices = []
                    for _, row in df.iterrows():
                        u_val = int(row['Umaban']) if pd.notnull(row['Umaban']) else 0
                        horse_choices.append(f"[{u_val:02d}] {row['Name']}")
                    
                    # Store selected axis horses
                    axis_selections = st.multiselect(
                        "軸馬を「2頭だけ」選んでください:",
                        options=horse_choices,
                        max_selections=2
                    )
                    
                    if len(axis_selections) == 2:
                        # Extract selected horse names
                        axis_names = [sel.split("] ")[1] for sel in axis_selections]
                        
                        # Filter out axis horses
                        pool_df = df[~df['Name'].isin(axis_names)].copy()
                        
                        # Filter out horses with 💣 or 💀 in Alert
                        pool_df = pool_df[~pool_df['Alert'].astype(str).str.contains("💣|💀", regex=True)]
                        
                        # Sort remaining horses by Rank (ascending)
                        if 'Rank' in pool_df.columns:
                            # Parse rank as numeric just in case
                            pool_df['Rank_Num'] = pd.to_numeric(pool_df['Rank'], errors='coerce').fillna(999)
                            pool_df = pool_df.sort_values('Rank_Num', ascending=True)
                        else:
                            pool_df = pool_df.sort_values('BattleScore', ascending=False)
                            
                        # Select top 10 opponents
                        recommended_opponents = pool_df.head(10)
                        
                        if not recommended_opponents.empty:
                            opp_list_strs = []
                            for _, r in recommended_opponents.iterrows():
                                u_val = int(r['Umaban']) if pd.notnull(r['Umaban']) else 0
                                opp_list_strs.append(f"[{u_val:02d}] {r['Name']}")
                            
                            st.markdown("#### 【あなたの軸馬】")
                            st.write(f"**{axis_selections[0]}** と **{axis_selections[1]}**")
                            
                            st.markdown("#### 【システム推奨の相手】")
                            for opp in opp_list_strs:
                                st.write(f"- {opp}")
                            
                            st.markdown("#### 【買い目点数】")
                            st.success(f"3連複 2頭軸流し 計 **{len(opp_list_strs)}** 点")
                            
                        else:
                            st.warning("推奨できる相手馬が見つかりませんでした（全頭が除外条件に該当）。")
                    elif len(axis_selections) > 0:
                        st.info("※軸馬を「あと1頭」選んでください。")

                    # --- Direct Match Pyramid ---
                    # Define one_year_ago for filtering
                    one_year_ago = datetime.now() - timedelta(days=365)
                    
                    # Define current_surf for filtering
                    try:
                        if 'Type' in df.columns:
                            current_surf = df['Type'].iloc[0]
                        elif 'Track' in df.columns:
                            current_surf = df['Track'].iloc[0]
                        else:
                            current_surf = '芝'
                    except:
                        current_surf = '芝'
                    
                    matches = calculator.get_direct_matches(df)
                    if matches:
                        st.subheader("🥊 Direct Match Pyramid")
                        st.caption("Color: 🔴>=70, 🟢50-69, 🔵<50 (Speed Index)")
                        
                        # Verify loss counts for thick border
                        loss_counts = {}
                        for w, l, _ in matches:
                            loss_counts[l] = loss_counts.get(l, 0) + 1
                            
                        dot = 'digraph {'
                        dot += 'rankdir=TB;'
                        dot += 'nodesep=1.0;' 
                        # RESIZED: width=2.0, fontsize=16
                        dot += 'node [shape=circle, fixedsize=true, width=2.0, style="filled", fontname="Meiryo", fontsize=16];'
                        dot += 'edge [penwidth=2.5];' 
                        
                        df['SpeedRank'] = df['SpeedIndex'].rank(ascending=False)
                        
                        unique_edges = set()
                        has_edges = False
                        
                        # Pre-calculate colors map to ensure consistency
                        node_colors = {}
                        for _, row in df.iterrows():
                            name = row['Name']
                            speed = row['SpeedIndex']
                            alert = str(row['Alert'])
                            
                            n_color = "#ccffcc" # Default Green
                            if "💀" in alert:
                                n_color = "#ccccff" # Blue
                            elif speed >= 70:
                                n_color = "#ff9999" # Red
                            elif speed >= 50:
                                n_color = "#ccffcc" # Green
                            else:
                                n_color = "#ccccff" # Blue
                            
                            node_colors[name] = n_color

                        for w, l, details in matches:
                            # ... (Filters same) ...
                            match_date = None
                            try:
                                d_str = details.get('Date', '')
                                match_date = datetime.strptime(d_str, "%Y.%m.%d")
                            except:
                                pass
                            if match_date and match_date < one_year_ago: continue
                            
                            m_surf = details.get('Surface', '')
                            is_same_surf = (current_surf in m_surf) if current_surf else True
                            if not is_same_surf: continue
                                
                            has_edges = True
                            
                            w_color = node_colors.get(w, "#ffffff")
                            l_color = node_colors.get(l, "#ffffff")
                            
                            # ID Helpers
                            w_row = df[df['Name'] == w]
                            l_row = df[df['Name'] == l]
                            w_umaban = w_row['Umaban'].iloc[0] if not w_row.empty else "??"
                            l_umaban = l_row['Umaban'].iloc[0] if not l_row.empty else "??"
                            
                            # Border Width Logic (Ironclad Delete)
                            w_width = 5.0 if (w_color == "#ccccff" and loss_counts.get(w, 0) >= 3) else 1.0
                            l_width = 5.0 if (l_color == "#ccccff" and loss_counts.get(l, 0) >= 3) else 1.0
                            
                            # Labels
                            w_label = f'<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0"><TR><TD><B><FONT POINT-SIZE="28">{w_umaban}</FONT></B></TD></TR><TR><TD><FONT POINT-SIZE="16">{w}</FONT></TD></TR></TABLE>>'
                            l_label = f'<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0"><TR><TD><B><FONT POINT-SIZE="28">{l_umaban}</FONT></B></TD></TR><TR><TD><FONT POINT-SIZE="16">{l}</FONT></TD></TR></TABLE>>'
                            
                            dot += f'"{w}" [label={w_label}, fillcolor="{w_color}", penwidth={w_width}];'
                            dot += f'"{l}" [label={l_label}, fillcolor="{l_color}", penwidth={l_width}];'
                            
                            race_name = details.get('RaceName', '')
                            short_race = race_name.split('(')[0].strip()[:6]
                            edge_key = (w, l)
                            if edge_key not in unique_edges:
                                 dot += f'"{w}" -> "{l}" [label="{short_race}" fontsize=10, color="#444444"];'
                                 unique_edges.add(edge_key)
                        
                        dot += '}'
                        if has_edges:
                             st.graphviz_chart(dot, use_container_width=True)
                        else:
                             st.caption("No matching direct comparisons.")
                             
                    # --- Exclude Recommended List ---
                    st.divider()
                    st.subheader("💀 Exclude Recommended List (Speed Index Bottom)")
                    excludes = df[df['Alert'].astype(str).str.contains("💀")]
                    if not excludes.empty:
                        for _, row in excludes.iterrows():
                            reason = row.get('Reason', '')
                            st.markdown(f"**{row['Umaban']} - {row['Name']}** (SI: {row['SpeedIndex']:.1f}) - {reason}")
                    else:
                        st.info("No explicit exclude recommendations.")

                    # --- 🎯 Strategy Advisor ---
                    st.divider()
                    st.subheader("🎯 戦略アドバイザー")
                    
                    strategy_df = df.copy()
                    
                    # 1. グラフを描画する直前に、データフレームを OguraIndex と SpeedIndex の合計値（総合戦闘力）の降順（高い順）にソート
                    strategy_df['TotalScore_For_Chart'] = pd.to_numeric(strategy_df['OguraIndex'], errors='coerce').fillna(0) + pd.to_numeric(strategy_df['SpeedIndex'], errors='coerce').fillna(0)
                    strategy_df = strategy_df.sort_values(by='TotalScore_For_Chart', ascending=False).reset_index(drop=True)
                    
                    sorted_scores = strategy_df['TotalScore_For_Chart'].tolist()
                    
                    # 2. 戦略アドバイザーの判定ロジック厳格化
                    if len(sorted_scores) >= 5: # Need at least 5 for deep compare
                        diff_threshold = 30
                        
                        score_1 = sorted_scores[0]
                        score_2 = sorted_scores[1]
                        score_3 = sorted_scores[2]
                        score_4 = sorted_scores[3]
                        score_5 = sorted_scores[4]
                        
                        gap_1_2 = score_1 - score_2
                        gap_2_3 = score_2 - score_3
                        gap_1_5 = score_1 - score_5
                        gap_1_3 = score_1 - score_3
                        gap_3_4 = score_3 - score_4
                        
                        if gap_1_2 >= diff_threshold:
                            st.info("👑 **1強レース**：1位の能力が突出しています。1位を絶対的な軸に固定し、相手は手広く探るのが推奨です。")
                        elif gap_1_2 < diff_threshold and gap_2_3 >= diff_threshold:
                            st.success("⚔️ **2強マッチレース**：上位2頭が抜けています。この2頭を軸にした『3連複2頭軸流し』が最も威力を発揮するレースです！")
                        elif gap_1_5 < 20.0:
                            st.error("🌪️ **大混戦（カオス）**：全馬の能力差が小さく難解です。『見送り（ケン）』推奨、またはオッズ妙味のみで超大穴を狙うレースです。")
                        elif gap_1_3 < 20.0 and gap_3_4 >= 20.0:
                            st.warning("🛡️ **上位拮抗レース**：上位陣の実力が伯仲しています。軸を絞りすぎず、上位馬のボックス買いなどで対応するのが安全です。")
                        else:
                            st.warning("🌋 **波乱含み（中穴警戒）**：中位馬にもチャンスがあります。消し馬ロジック（💀💣）を駆使してヒモ荒れを狙いましょう。")
                    else:
                        st.info("📊 **少頭数レース**：データが少ないため、各馬の状態や展開を重視してください。")

                    # --- RESURRECTED: Composite Chart (Dual-Axis with Altair) ---
                    st.subheader("📈 Index Analysis Chart")
                    import altair as alt
                    
                    cols_to_keep = ['Name', 'OguraIndex', 'SpeedIndex', 'TotalScore_For_Chart']
                    if 'Odds' in strategy_df.columns:
                        cols_to_keep.append('Odds')
                        
                    chart_df = strategy_df[cols_to_keep].copy()
                    
                    if 'Odds' in chart_df.columns:
                        chart_df['Odds'] = pd.to_numeric(chart_df['Odds'], errors='coerce').fillna(0)
                        
                    # Melt dataframe for stacked bar chart
                    id_vars = ['Name', 'TotalScore_For_Chart']
                    if 'Odds' in chart_df.columns:
                        id_vars.append('Odds')
                        
                    melted_df = chart_df.melt(id_vars=id_vars, 
                                              value_vars=['OguraIndex', 'SpeedIndex'], 
                                              var_name='IndexType', value_name='Score')
                    
                    # Define X-axis sort order based on dataframe index
                    sort_order = chart_df['Name'].tolist()
                    
                    # Create base stacked bar chart
                    bars = alt.Chart(melted_df).mark_bar().encode(
                        x=alt.X('Name:N', sort=sort_order, title='Horse Name'),
                        y=alt.Y('Score:Q', title='Index Score (Total)'),
                        color=alt.Color('IndexType:N', legend=alt.Legend(title="Index Type", orient='top-left')),
                        tooltip=['Name', 'TotalScore_For_Chart']
                    )
                    
                    # Add line chart for Odds if available
                    if 'Odds' in chart_df.columns:
                        line = alt.Chart(chart_df).mark_line(color='#ff2a2a', strokeWidth=3).encode(
                            x=alt.X('Name:N', sort=sort_order),
                            y=alt.Y('Odds:Q', axis=alt.Axis(orient='right', title='Win Odds (Red Line)', titleColor='#ff2a2a', labelColor='#ff2a2a'))
                        )
                        
                        points = alt.Chart(chart_df).mark_circle(color='#FFD700', size=90, stroke='#ff2a2a', strokeWidth=2).encode(
                            x=alt.X('Name:N', sort=sort_order),
                            y=alt.Y('Odds:Q'),
                            tooltip=['Name', 'Odds', 'TotalScore_For_Chart']
                        )
                        
                        # Layer them and resolve Y axis to be independent
                        composite_chart = alt.layer(bars, line, points).resolve_scale(y='independent').properties(height=450)
                    else:
                        composite_chart = bars.properties(height=450)
                    
                    st.altair_chart(composite_chart, use_container_width=True)
                    # --------------------------
                    
                    # --- 💡 Race Pattern Strategy Advisor ---
                    st.divider()
                    st.subheader("💡 レースパターン別 おすすめ戦略")
                    
                    # --- Constants for pattern detection ---
                    GAP_VERY_LARGE = 50    # Pattern 1: 超固い
                    GAP_LARGE = 30          # Pattern 2: やや固い
                    GAP_FLAT = 15           # Pattern 5: 大荒れ (gap between 1st and last)
                    GAP_MIDDLE_SMALL = 20   # Pattern 4: 荒れ (gap between top and mid)
                    
                    # --- Pattern Detection Logic ---
                    def detect_race_pattern(scores):
                        if len(scores) < 2:
                            return 3  # Default: 通常
                        s = scores
                        gap_1_2 = s[0] - s[1]
                        gap_1_3 = s[0] - s[2] if len(s) >= 3 else gap_1_2
                        gap_top_mid = (s[2] - s[6]) if len(s) >= 7 else 0
                        gap_1_last = s[0] - s[-1]
                        
                        if gap_1_2 >= GAP_VERY_LARGE:
                            return 1
                        elif gap_1_3 >= GAP_LARGE and gap_1_2 < GAP_VERY_LARGE:
                            return 2
                        elif gap_1_last < GAP_FLAT:
                            return 5
                        elif len(scores) >= 7 and gap_top_mid < GAP_MIDDLE_SMALL:
                            return 4
                        else:
                            return 3
                    
                    race_pattern = detect_race_pattern(sorted_scores)
                    
                    # --- Advice text per pattern ---
                    if race_pattern == 1:
                        advice_color = "#FF4500"
                        advice_border = "#FF4500"
                        advice_bg = "#2D0000"
                        advice_title = "🔻 【超固い（鉄板）レース】"
                        advice_text = """
<strong>⚠️ このレースは買わずに「見（ケン）」を強く推奨します。</strong><br><br>
1位馬の指数が2位以下を圧倒しており、単勝・馬連ともに低配当が確実な構造です。
むやみに買い続けると、払い戻しが投資額を下回る「プラス収支の罠」にはまります。<br><br>
<strong>【推奨アクション】</strong><br>
✅ 基本姿勢：完全ケン（見送り）<br>
✅ どうしても買いたい場合：1強馬を軸に「3連単1-2着固定」で点数を絞り、配当倍率が最低でも10倍以上になる組み合わせのみ購入<br>
✅ 次の「荒れレース」に向けて資金をキープし、体力を温存することが最優先戦略です。
"""
                    elif race_pattern == 2:
                        advice_color = "#00C8FF"
                        advice_border = "#00C8FF"
                        advice_bg = "#001A2D"
                        advice_title = "🔵 【やや固い（順当）レース】"
                        advice_text = """
<strong>✅ 上位2頭が安定しており、「手堅く回収」を狙えるレースです。</strong><br><br>
指数上位2頭と3位以下の差が明確なため、軸が絞りやすい構造です。
無理に穴を狙わず、堅実な買い目でしっかり的中率を維持しましょう。<br><br>
<strong>【推奨買い目】</strong><br>
🏇 <strong>馬連：1-2位軸の流し</strong>（相手は3〜5位まで）→ 点数3〜4点に絞る<br>
🏇 <strong>3連複：1・2位を軸に1頭ずつ固定</strong>、3頭目を3〜6位から3点流し → 合計5〜6点<br>
🏇 <strong>目標配当：馬連10〜20倍、3連複30〜80倍</strong><br><br>
💡 このレースで確実に回収し、次のレースに向けた資金基盤を整えましょう。
"""
                    elif race_pattern == 3:
                        advice_color = "#FFD700"
                        advice_border = "#FFD700"
                        advice_bg = "#1A1400"
                        advice_title = "🔥 【通常（波乱含み）レース】"
                        advice_text = """
<strong>🎯 最もバランスの良い「勝負レース」です。積極的に仕掛けましょう！</strong><br><br>
上位馬が階段状にスコアが落ちており、1〜5位に実力差はあるものの混戦要素があります。
軸馬を1頭固定しつつ、相手を広げることで「中穴の旨みを取る」戦略が最適です。<br><br>
<strong>【推奨買い目】</strong><br>
🏇 <strong>馬連：1位軸から2〜6位への流し</strong> → 5点<br>
🏇 <strong>3連複：1位を軸1頭固定、2〜7位から6頭選んで流し</strong> → 15点前後<br>
🏇 <strong>3連単：1位→2・3位固定→4〜7位まで流し</strong>で点数を絞った高配当狙い<br>
🏇 <strong>目標配当：馬連15〜40倍、3連複50〜200倍</strong><br><br>
💡 消し馬ロジック（💀💣マーク）を最大活用し、買い目数を削減してください。点数を絞るほど回収率が上がります。
"""
                    elif race_pattern == 4:
                        advice_color = "#FF8C00"
                        advice_border = "#FF8C00"
                        advice_bg = "#1A0A00"
                        advice_title = "🔥 【荒れ（中穴チャンス）レース】"
                        advice_text = """
<strong>💥 一撃まくりの大チャンス！中堅馬に大きなチャンスがあるレースです。</strong><br><br>
上位3頭と6〜9位の指数差が小さく、「どの馬が来てもおかしくない」展開が予想されます。
このタイプのレースで人気馬だけを買うのは最も非効率。相手を広げ、中穴を積極的に狙うべきです。<br><br>
<strong>【推奨買い目】</strong><br>
🏇 <strong>3連複ボックス：1〜2位＋4〜8位の中から合計5頭ボックス</strong> → 10点<br>
🏇 <strong>馬連：1・2位から5〜8位への2頭流し</strong> → 8〜10点<br>
🏇 <strong>3連単：2・3位→1位→4〜7位の「マクリ」フォーメーション</strong><br>
🏇 <strong>目標配当：馬連40〜100倍、3連複100〜500倍</strong><br><br>
💡 人気薄でも💡マークや指数上位に食い込んでいる馬は要注目。スコアと人気のギャップが最大の武器です。
"""
                    else:  # pattern 5
                        advice_color = "#FF4500"
                        advice_border = "#FF4500"
                        advice_bg = "#2D0000"
                        advice_title = "🔻 【大荒れ（爆穴）レース】"
                        advice_text = """
<strong>⚠️ 予測不能のロト・レース！分析ツールの限界を超えた「宝くじ戦場」です。</strong><br><br>
全馬の指数がほぼ横並びで、どの馬が来てもグラフでは説明できない状況です。
このレースで大きく張るのは危険。当たれば万馬券確実ですが、的中率は極めて低い。<br><br>
<strong>【推奨買い目】</strong><br>
🏇 <strong>3連複ボックス：気になる馬を6〜7頭選んでボックス</strong>（購入点数は多くなるが仕方なし）<br>
🏇 <strong>馬単・3連単はNG</strong>（順番まで当てるのは運ゲー）<br>
🏇 <strong>1頭だけ「消し（💀マーク）」の馬を除いた残り全馬流し</strong>という逆転発想も有効<br>
🏇 <strong>目標配当：3連複500倍〜万馬券</strong><br><br>
💡 このレースは「楽しむ・夢を買う」レースと割り切り、投資額を抑えて少点数で挑みましょう。
当たればボーナス、外れても次のレースで取り返す気持ちで臨むのが正解です。
"""
                    
                    st.html(f"""
<div style="
    background-color: {advice_bg};
    border: 2px solid {advice_border};
    border-radius: 12px;
    padding: 24px 28px;
    margin-top: 12px;
    box-shadow: 0 0 22px {advice_color}55;
">
    <div style="font-size: 1.3em; font-weight: bold; color: {advice_color}; margin-bottom: 14px; border-bottom: 1px solid {advice_border}55; padding-bottom: 10px;">
        {advice_title}
    </div>
    <div style="font-size: 1.0em; color: #EEEEEE; line-height: 2.0;">
        {advice_text}
    </div>
</div>
""")
                    # --- End Race Pattern Strategy Advisor ---

                    # --- 🤖 AI Assistant ---

                    st.divider()
                    st.subheader("🤖 AI最終予想アシスタント（検索連携）")
                    if st.button("🤖 AIに最終予想を依頼する（Web検索連携）"):
                        
                        # dynamically reload dotenv to pick up any changes
                        from dotenv import load_dotenv
                        load_dotenv(override=True)
                        
                        # Fetch API key securely from environment variables or st.secrets
                        genai_api_key = os.getenv("GEMINI_API_KEY")
                        if not genai_api_key:
                            try:
                                genai_api_key = st.secrets.get("GEMINI_API_KEY")
                            except FileNotFoundError:
                                pass
                                
                        if not genai_api_key:
                            st.error("APIキーが設定されていません。.envファイルまたはst.secretsに『GEMINI_API_KEY』を設定してください。")
                        else:
                            try:
                                with st.spinner("AIが競走馬データとWeb検索結果を統合して予想しています... (約10〜20秒)"):
                                    # Use new google-genai SDK
                                    client = genai.Client(api_key=genai_api_key)
                                    
                                    df_str = df.to_markdown(index=False)
                                    
                                    # Build race pattern context
                                    pattern_names = {
                                        1: "超固い（鉄板）",
                                        2: "やや固い（順当）",
                                        3: "通常（波乱含み）",
                                        4: "荒れ（中穴チャンス）",
                                        5: "大荒れ（爆穴）",
                                    }
                                    pattern_label_ai = pattern_names.get(race_pattern, "不明")
                                    
                                    # Build top horses string (up to 12 to include "11位" context)
                                    top_horses_str = "\n".join(
                                        f"  {i+1}位: {strategy_df['Name'].iloc[i]}（TotalScore: {sorted_scores[i]:.1f}）"
                                        for i in range(min(12, len(sorted_scores)))
                                    )
                                    
                                    # Build hn() helper: returns "[馬番] 馬名"
                                    h_names = strategy_df['Name'].tolist()
                                    h_umaban = (
                                        strategy_df['Umaban'].tolist()
                                        if 'Umaban' in strategy_df.columns
                                        else list(range(1, len(h_names) + 1))
                                    )
                                    def hn(i, icon=""):
                                        if i >= len(h_names):
                                            return f"{icon}[{i+1}] {i+1}位馬".strip()
                                        no = int(h_umaban[i]) if str(h_umaban[i]).isdigit() or isinstance(h_umaban[i], (int, float)) else i+1
                                        return f"{icon}[{no}] {h_names[i]}"
                                    
                                    # Pattern-specific buy instruction for AI to follow
                                    if race_pattern == 1:
                                        sanren_rule = """
〇 AIおすすめの買い目（3連複 15点）
---
🚫 買い目なし（見推奨）

💡 アドバイス
「本命決着が濃厚です。配当妙味が薄いため、ここは『見（ケン）』を推奨します。無駄な被弾を避けましょう。」
"""
                                        umaren_rule = """
〇 AIおすすめの買い目（馬連 5点）
---
🚫 買い目なし（見推奨）

💡 アドバイス
「馬連の配当的な旨味が全くありません。このレースはパス（見）して、次のチャンスを待ちましょう。」
"""
                                    elif race_pattern in [2, 3, 4]:
                                        anaba_idx = 10 if len(h_names) > 10 else len(h_names) - 1
                                        sanren_rule = f"""
〇 AIおすすめの買い目（3連複 15点）
---
【1】上位＋大穴ボックス（10点）
{hn(0, "🔥")}
{hn(1, "🔥")}
{hn(2)}
{hn(3)}
{hn(anaba_idx)} ★大穴

【2】1位・2位の2頭軸流し（5点）
■ 軸馬
{hn(0, "🎯")}
{hn(1, "🎯")}
■ 相手（ヒモ）
{hn(4)}
{hn(5)}
{hn(6)}
{hn(7)}
{hn(8) if len(h_names) > 8 else hn(min(7, len(h_names)-1))}

💡 アドバイス
「『1位が飛ぶ縦目リスク』と『圏外馬（11位等）の突っ込み』を両方カバーした究極の15点です。堅実な決着から、2-3-11などの特大万馬券まで逃さず狙い撃ちします。」
"""
                                        sanren_rule = sanren_rule.strip()
                                        umaren_rule = f"""
〇 AIおすすめの買い目（馬連 5点）
---
■ 軸馬
{hn(0, "🔥")}
■ 相手
{hn(1)}
{hn(2)}
{hn(3)}
{hn(4)}
{hn(1)} ← 2位-3位のクロス（{hn(2)}）も押さえ

💡 アドバイス
「馬連5点のコツコツ投資モードです。スコア上位馬から流し、高い勝率でコンスタントな的中を狙います。」
"""
                                        umaren_rule = umaren_rule.strip()
                                    else:  # pattern 5 大荒れ
                                        sanren_rule = f"""
〇 AIおすすめの買い目（3連複 15点）
---
【1】上位5頭ボックス（10点）
{hn(0, "🔥")}
{hn(1, "🔥")}
{hn(2)}
{hn(3)}
{hn(4)}

【2】1位・2位軸 穴流し（5点）
■ 軸馬
{hn(0, "🎯")}
{hn(1, "🎯")}
■ 相手（ヒモ）
{hn(5)}
{hn(6)}
{hn(7)}
{hn(8)}
{hn(9) if len(h_names) > 9 else hn(min(8, len(h_names)-1))}

💡 アドバイス
「波乱の予兆あり！オッズが跳ねる大チャンスです。手広く網を張り、一撃の高配当を狙い撃ちしましょう。」
"""
                                        sanren_rule = sanren_rule.strip()
                                        umaren_rule = f"""
〇 AIおすすめの買い目（馬連 5点）
---
■ 軸馬（スコア上位2頭）
{hn(0, "🔥")}
■ 相手（混戦フォーメーション）
{hn(2)}
{hn(4)}
{hn(3)}
{hn(5) if len(h_names) > 5 else hn(4)}
{hn(4)}

💡 アドバイス
「大混戦のため軸が絞りにくいレースです。手広く狙うか、自信がなければ少額で宝くじ感覚で楽しみましょう。」
"""
                                        umaren_rule = umaren_rule.strip()

                                    
                                    prompt = f"""
あなたは優秀な競馬AIアシスタントです。以下の独自データ・パターン判定・検索結果を統合して最終予想を出力してください。

【出走馬データ（独自算出数値）】
{df_str}

【スコアランキング（降順・上位12頭）】
{top_horses_str}

【グラフパターン自動判定結果】
このレースは「{pattern_label_ai}」パターンと判定されました。

【指示事項】
1. Web検索機能を使い、以下の最新情報を取得してください。
   ・本日の対象競馬場の天気・馬場状態（良・稍重など）・トラックバイアス
   ・競馬ブログや予想サイト（一般予想家・専門サイト）のこのレースに関する見解
2. Web情報と独自データ（スコアランキング・パターン判定）を比較・吟味してください。
3. 両者を総合的に判断し、軸馬・本命馬の根拠を詳しく解説してください。
4. 以下の構成で出力してください（買い目セクションは別途提示するため不要）：

---
## 📋 総合分析・推論プロセス
（Web情報と独自データの比較、推奨軸馬の根拠）

## 🎯 最終的な推奨馬
（勝ち馬・軸馬の名前と理由）
---
"""

                                    response = client.models.generate_content(
                                        model='gemini-2.5-flash',
                                        contents=prompt,
                                        config=genai_types.GenerateContentConfig(
                                            tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())]
                                        )
                                    )
                                    
                                    st.success("予想が完了しました！")
                                    st.markdown(response.text)
                                    
                                    # --- Render buy sections directly with st.html (not via AI) ---
                                    st.divider()
                                    
                                    # Helper: safe horse number
                                    def _no(i):
                                        try:
                                            return int(float(h_umaban[i])) if i < len(h_umaban) else i + 1
                                        except (ValueError, TypeError):
                                            return i + 1
                                    
                                    def axis_row(i):
                                        if i >= len(h_names): return ""
                                        return f'<div style="display:flex;align-items:center;gap:10px;padding:8px 10px;margin:4px 0;background:#263a50;border-radius:8px;border-left:4px solid #FFD700;"><span style="font-size:1.1em;">👑</span><span style="background:#FFD700;color:#111;font-weight:bold;font-size:1em;padding:4px 11px;border-radius:6px;min-width:34px;text-align:center;">{_no(i)}</span><span style="color:#FFFFFF;font-weight:bold;font-size:1em;">{h_names[i]}</span></div>'
                                    
                                    def target_row(i, extra=""):
                                        if i >= len(h_names): return ""
                                        ex = f'<span style="color:#FFD700;font-size:0.82em;margin-left:6px;">{extra}</span>' if extra else ""
                                        return f'<div style="display:flex;align-items:center;gap:10px;padding:6px 10px;margin:2px 0 2px 20px;border-bottom:1px solid #2a2a3a;"><span style="background:#1e3a5f;color:#fff;font-weight:bold;font-size:0.95em;padding:3px 9px;border-radius:6px;min-width:34px;text-align:center;">{_no(i)}</span><span style="color:#CCCCCC;font-size:0.95em;">{h_names[i]}</span>{ex}</div>'
                                    
                                    def lbl(text, color="#90CAF9"):
                                        return f'<div style="color:{color};font-size:0.88em;font-weight:bold;margin:10px 0 4px;letter-spacing:0.5px;">{text}</div>'
                                    
                                    def advice_box(text, color="#FFD700"):
                                        return f'<div style="background:#1a1200;border-left:4px solid {color};border-radius:6px;padding:12px 16px;margin-top:16px;color:#EEEEEE;font-size:0.93em;line-height:1.9;">💡 {text}</div>'
                                    
                                    anaba_idx = 10 if len(h_names) > 10 else len(h_names) - 1
                                    
                                    # ======== 〇 3連複 15点 ========
                                    st.markdown("### 〇 AIおすすめの買い目（3連複 15点）")
                                    
                                    if race_pattern == 1:
                                        st.html('<div style="color:#FF6B6B;font-size:1.1em;font-weight:bold;padding:12px;">🚫 買い目なし（見推奨）</div>')
                                        st.html(advice_box("本命決着が濃厚です。配当妙味が薄いため、ここは『見（ケン）』を推奨します。無駄な被弾を避けましょう。", "#FF4500"))
                                    else:
                                        col_a, col_b = st.columns(2)
                                        with col_a:
                                            a = f'<div style="font-size:1.05em;font-weight:bold;color:#60A5FA;border-left:4px solid #60A5FA;padding-left:10px;margin-bottom:10px;">【A】上位1軸流し（10点）</div>'
                                            a += lbl("▶ 軸馬（1頭固定）", "#FFD700")
                                            a += axis_row(0)
                                            a += lbl("▶ 相手（2〜6位から2頭選択 C5,2=10点）", "#90CAF9")
                                            for j in [1, 2, 3, 4, 5]:
                                                a += target_row(j)
                                            st.html(f'<div style="background:#0d1e35;border:1.5px solid #60A5FA55;border-radius:12px;padding:18px 16px;">{a}</div>')
                                        with col_b:
                                            b = f'<div style="font-size:1.05em;font-weight:bold;color:#FBBF24;border-left:4px solid #FBBF24;padding-left:10px;margin-bottom:10px;">【B】縦目・大穴カバー（5点）</div>'
                                            b += lbl("▶ 軸馬（2頭固定）", "#FFD700")
                                            b += axis_row(1)
                                            b += axis_row(2)
                                            b += lbl("▶ 相手（4〜7位 + 11位の大穴）", "#FCD34D")
                                            for j in [3, 4, 5, 6]:
                                                b += target_row(j)
                                            b += target_row(anaba_idx, "★大穴")
                                            st.html(f'<div style="background:#1e1500;border:1.5px solid #FBBF2455;border-radius:12px;padding:18px 16px;">{b}</div>')
                                        
                                        _h2 = h_names[2] if len(h_names) > 2 else "3位馬"
                                        _h5 = h_names[5] if len(h_names) > 5 else "6位馬"
                                        _hx = h_names[anaba_idx] if anaba_idx < len(h_names) else f"{anaba_idx+1}位馬"
                                        st.html(advice_box(
                                            f"【A】は1位が勝った場合の本線（1位軸×2〜6位が2頭完成で的中）。"
                                            f"【B】は1位が飛んでも{_h2}（3位）を軸に縦目をカバーし、{_hx}（大穴）まで押さえます。"
                                            f"{_h5}（6位）まで相手に入れることで中堅馬突っ込みにも対応した究極の15点です。"
                                        ))
                                    
                                    st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                                    
                                    # ======== 〇 馬連 5点 ========
                                    st.markdown("### 〇 AIおすすめの買い目（馬連 5点）")
                                    
                                    if race_pattern == 1:
                                        st.html('<div style="color:#FF6B6B;font-size:1.1em;font-weight:bold;padding:12px;">🚫 買い目なし（見推奨）</div>')
                                        st.html(advice_box("馬連の配当的な旨味が全くありません。このレースはパス（見）して、次のチャンスを待ちましょう。", "#FF4500"))
                                    elif race_pattern in [2, 3, 4]:
                                        u = lbl("■ 軸馬", "#FFD700") + axis_row(0)
                                        u += lbl("■ 相手（2〜5位 + 2-3位クロス）", "#90CAF9")
                                        for j in [1, 2, 3, 4]:
                                            u += target_row(j)
                                        u += target_row(2, "← 2-3位クロス")
                                        st.html(f'<div style="background:#0d1b2a;border:1.5px solid #00C8FF44;border-radius:12px;padding:18px 16px;max-width:480px;">{u}</div>')
                                        st.html(advice_box("馬連5点のコツコツ投資モードです。スコア上位馬から流し、高い勝率でコンスタントな的中を狙います。", "#00C8FF"))
                                    else:
                                        u = lbl("■ 軸馬（スコア上位2頭）", "#FFD700") + axis_row(0)
                                        u += lbl("■ 相手（混戦フォーメーション）", "#90CAF9")
                                        for j in [2, 4, 3, 5, 6]:
                                            u += target_row(j)
                                        st.html(f'<div style="background:#0d1b2a;border:1.5px solid #FF8C0044;border-radius:12px;padding:18px 16px;max-width:480px;">{u}</div>')
                                        st.html(advice_box("大混戦のため軸が絞りにくいレースです。手広く狙うか、自信がなければ少額で宝くじ感覚で楽しみましょう。", "#FF8C00"))
                            except Exception as e:
                                st.error(f"AI処理中にエラーが発生しました: {e}")
                    # -----------------------




            except Exception as e:
                st.error(f"An error occurred: {e}")

with tab2:
    st.header("🔍 Race Scanner（バッチ分析・パターン絞り込み）")

    # ---- Mode selector ----
    scan_mode = st.radio(
        "入力方法を選択",
        ["📅 日付指定で自動取得", "✏️ IDを直接入力"],
        horizontal=True,
        key="scan_mode"
    )

    import re as _re2
    from datetime import date as _date

    # Shared name map (race_id -> race_name) populated by auto-fetch
    if 'scanner_name_map' not in st.session_state:
        st.session_state['scanner_name_map'] = {}

    PATTERN_OPTIONS = {
        "超固い（鉄板）":      1,
        "やや固い（順当）":    2,
        "通常（波乱含み）":    3,
        "荒れ（中穴チャンス）": 4,
        "大荒れ（爆穴）":      5,
    }

    col_input, col_filter = st.columns([3, 2])
    with col_filter:
        st.markdown("**レース評価フィルター**")
        selected_patterns = st.multiselect(
            "表示するパターン（未選択＝全表示）",
            options=list(PATTERN_OPTIONS.keys()),
            default=[],
            key="scanner_pattern_filter"
        )
        filter_ids = set(PATTERN_OPTIONS[k] for k in selected_patterns)

    with col_input:
        if scan_mode == "📅 日付指定で自動取得":
            picked_date = st.date_input(
                "対象日を選択",
                value=_date.today(),
                key="scanner_date"
            )
            auto_btn = st.button("この日の全レースを取得", key="scanner_auto_btn")
            if auto_btn:
                date_str = picked_date.strftime("%Y%m%d")
                with st.spinner(f"{date_str} のレース一覧を取得中..."):
                    race_list = scraper.get_race_list_for_date(date_str)
                if race_list:
                    st.session_state['scanner_auto_ids'] = [r['race_id'] for r in race_list]
                    st.session_state['scanner_name_map'] = {r['race_id']: r['race_name'] for r in race_list}
                    st.success(f"{len(race_list)} 件のレースを取得しました。")
                else:
                    st.warning("この日のレースが見つかりませんでした。")
                    st.session_state['scanner_auto_ids'] = []

            auto_ids = st.session_state.get('scanner_auto_ids', [])
            if auto_ids:
                st.caption(f"取得済み: {len(auto_ids)} 件 ― すぐ下の「スキャン開始」を押してください")
            scan_input = "\n".join(auto_ids)
        else:
            if 'scanner_input' not in st.session_state:
                st.session_state['scanner_input'] = ""
                
            def _on_scanner_input_change():
                import re
                val = st.session_state['scanner_input']
                if not val: return
                lines = val.replace(',', '\n').split('\n')
                extracted_lines = []
                changed = False
                for line in lines:
                    line = line.strip()
                    if not line: continue
                    match = re.search(r'race_id=(\d{12})', line)
                    if not match: match = re.search(r'(\d{12})', line)
                    if match:
                        extracted = match.group(1)
                        extracted_lines.append(extracted)
                        if extracted != line: changed = True
                    else:
                        extracted_lines.append(line)
                
                if changed:
                    st.session_state['scanner_input'] = '\n'.join(extracted_lines)
                    st.session_state['scanner_extracted'] = True

            scan_input = st.text_area(
                "レースID / URL（1行1件、カンマ区切りも可）",
                height=160,
                placeholder="202608020211\n202608020212\nhttps://race.netkeiba.com/race/shutuba.html?race_id=202608020213",
                key="scanner_input",
                on_change=_on_scanner_input_change
            )
            
            if st.session_state.get('scanner_extracted', False):
                st.success("✨ URLからレースIDを自動抽出しました！", icon="✅")
                st.session_state['scanner_extracted'] = False

    scan_btn = st.button("🔍 スキャン開始", type="primary", key="scanner_btn")


    if scan_btn and scan_input:
        import re as _re2

        # Parse IDs (URL/raw)
        raw_lines = scan_input.replace(",", "\n").split("\n")
        race_ids = []
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            m = _re2.search(r'race_id=(\d{12})', line)
            if m:
                race_ids.append(m.group(1))
            else:
                m2 = _re2.search(r'(\d{12})', line)
                if m2:
                    race_ids.append(m2.group(1))

        race_ids = list(dict.fromkeys(race_ids))  # dedupe

        if not race_ids:
            st.warning("有効なレースIDが見つかりませんでした。12桁の数字またはURLを入力してください。")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()

            # Pattern detection helper (same logic as Single Race tab)
            def _detect_pattern(scores):
                GAP_VERY_LARGE, GAP_LARGE, GAP_FLAT, GAP_MIDDLE_SMALL = 50, 30, 15, 20
                s = scores
                if len(s) < 2: return 3
                g12 = s[0] - s[1]
                g13 = s[0] - s[2] if len(s) >= 3 else g12
                g_last = s[0] - s[-1]
                g_mid = (s[2] - s[6]) if len(s) >= 7 else 0
                if g12 >= GAP_VERY_LARGE: return 1
                elif g13 >= GAP_LARGE and g12 < GAP_VERY_LARGE: return 2
                elif g_last < GAP_FLAT: return 5
                elif len(s) >= 7 and g_mid < GAP_MIDDLE_SMALL: return 4
                else: return 3

            PATTERN_LABELS = {
                1: ("超固い（鉄板）",     "#FF4500", "#2D0000"),
                2: ("やや固い（順当）",   "#00C8FF", "#001A2D"),
                3: ("通常（波乱含み）",   "#FFD700", "#1A1400"),
                4: ("荒れ（中穴チャンス）","#FF8C00","#1A0A00"),
                5: ("大荒れ（爆穴）",     "#FF4500", "#2D0000"),
            }

            results = []   # list of dicts

            for i, rid in enumerate(race_ids):
                status_text.text(f"スキャン中... {rid}  ({i+1}/{len(race_ids)})")
                try:
                    df_r = scraper.get_race_data(rid)
                    if df_r is None or df_r.empty:
                        raise ValueError("データなし")
                    df_r = calculator.calculate_ogura_index(df_r)

                    # Compute scores
                    tmp = df_r.copy()
                    tmp['_score'] = (
                        pd.to_numeric(tmp.get('OguraIndex', 0), errors='coerce').fillna(0) +
                        pd.to_numeric(tmp.get('SpeedIndex', 0), errors='coerce').fillna(0)
                    )
                    tmp = tmp.sort_values('_score', ascending=False).reset_index(drop=True)
                    scores_sorted = tmp['_score'].tolist()
                    pattern = _detect_pattern(scores_sorted)

                    # 1st: pre-fetched name map (from date auto-fetch)
                    race_title = st.session_state.get('scanner_name_map', {}).get(rid, "")
                    # 2nd: from df columns
                    if not race_title or race_title == rid:
                        for col in ['RaceName', 'RaceTitle', 'Title']:
                            if col in df_r.columns:
                                v = str(df_r.iloc[0][col]).strip()
                                SKIP_VALS = {"unknown race", rid, "", "nan"}
                                if v and v.lower() not in SKIP_VALS:
                                    race_title = v
                                    break
                    if not race_title or race_title.lower() == "unknown race":
                        race_title = f"Race {rid[-4:]}"   # last 4 digits as fallback label

                    top3 = tmp['Name'].head(3).tolist()

                    results.append({
                        "id": rid,
                        "title": str(race_title),
                        "pattern": pattern,
                        "top3": top3,
                        "df": tmp,
                        "error": None,
                    })
                except Exception as e:
                    results.append({
                        "id": rid,
                        "title": rid,
                        "pattern": None,
                        "top3": [],
                        "df": None,
                        "error": str(e),
                    })

                progress_bar.progress((i + 1) / len(race_ids))

            status_text.text(f"✅ スキャン完了！ {len(race_ids)}件処理しました。")

            # Apply filter
            if filter_ids:
                display = [r for r in results if r['pattern'] in filter_ids]
            else:
                display = results

            errors = [r for r in results if r['error']]
            if errors:
                with st.expander(f"⚠️ スキップされたレース {len(errors)}件", expanded=False):
                    for r in errors:
                        st.markdown(f"- `{r['id']}` : {r['error']}")

            st.markdown(f"### 📋 結果 {len(display)} 件 {'（フィルター適用中）' if filter_ids else ''}")

            if not display:
                st.info("条件に合致するレースが見つかりませんでした。フィルターを変更してみてください。")
            else:
                for r in display:
                    p = r['pattern']
                    label, color, bg = PATTERN_LABELS.get(p, ("不明", "#888", "#111"))
                    badge = f'<span style="background:{bg};color:{color};border:1px solid {color};border-radius:6px;padding:3px 10px;font-size:0.85em;font-weight:bold;">{label}</span>'
                    race_name = r["title"] if r["title"] != r["id"] else "(レース名不明)"
                    header_html = (
                        f'<span style="font-size:1.15em;font-weight:bold;color:inherit;">{race_name}</span>'
                        f'&nbsp;&nbsp;{badge}&nbsp;&nbsp;'
                        f'<span style="color:#888;font-size:0.82em;">{r["id"]}</span>'
                    )
                    st.html(f'<div style="margin-top:18px;padding:10px 0 4px;border-top:1px solid #333;">{header_html}</div>')


                    with st.expander("▶ 詳細を見る", expanded=False):
                        if r['df'] is not None:
                            tmp_df = r['df']
                            # Show top 10 horses
                            cols_show = [c for c in ['Umaban', 'Name', 'Jockey', 'OguraIndex', 'SpeedIndex', '_score'] if c in tmp_df.columns]
                            display_df = tmp_df[cols_show].head(10).copy()
                            rename_map = {'Umaban': '馬番', 'Name': '馬名', 'Jockey': '騎手', 'OguraIndex': 'OguraIdx', 'SpeedIndex': 'SpeedIdx', '_score': 'TotalScore'}
                            display_df.columns = [rename_map.get(c, c) for c in display_df.columns]
                            st.dataframe(display_df, use_container_width=True, hide_index=True)

                            # Link to Single Race
                            st.markdown(f"🔗 [このレースをシングルタブで詳細分析する](/?race_id={r['id']})")
                        else:
                            st.error(f"データ取得エラー: {r['error']}")




# --- Tab 3: History & Review ---
# --- Tab 3: History & Review ---
with tab3:
    st.header("📊 Learning Fortress: History & Review")
    
    # 1. AI Guide (Updated for Learning Mode)
    with st.expander("💡 AIによる改善サイクルのやり方 (Learning Mode)", expanded=True):
        st.markdown("""
        **最強の予想ロジックを作るための「後出し学習」機能です。**
        
        1. **過去レース登録**: 下のフォームに、終わったレースのIDを入れて「確定させて保存」を押します。
        2. **自動採点**: 予測指数(Index)と、実際の着順(Result)が自動で保存されます。
        3. **AI分析依頼**: 保存された `race_history.csv` をGeminiに渡し、**「指数が高いのに負けた馬の共通点は？」** と聞いてください。
        4. **ロジック修正**: 「○○条件で弱い」と分かったら、 `calculator.py` の計算式を調整しましょう。
        """)

    import history_manager

    # --- Registration Area ---
    st.subheader("🏁 Register Past Races (Learning)")
    reg_input = st.text_area("Past Race IDs (Finished Races)", height=100, placeholder="202608020211\n202608020212")
    
    col_reg1, col_reg2 = st.columns([1, 3])
    with col_reg1:
        if st.button("📥 結果を確定させて保存", type="primary"):
            if reg_input:
                rids = reg_input.replace(",", "\n").split("\n")
                rids = [r.strip() for r in rids if r.strip()]
                
                with st.spinner("Fetching results and calculating indices..."):
                    logs = history_manager.register_past_races(rids)
                    
                for log in logs:
                    if "✅" in log:
                        st.success(log)
                    else:
                        st.error(log)
            else:
                st.warning("Please enter Race IDs.")
                
    with col_reg2:
        if st.button("🔄 Update Existing Records (Re-fetch Results)"):
            status = history_manager.update_history_with_results()
            st.info(status)

    st.divider()

    # --- Display Section: View Full Analysis + Results ---
    st.subheader("🔍 レース解析＆結果表示 (Display)")
    st.caption("Race IDを入力すると、解析結果とレース結果を同時に表示します。")
    
    if 'history_display_race_id' not in st.session_state:
        st.session_state['history_display_race_id'] = ""

    def _on_history_display_change():
        import re
        val = st.session_state['history_display_race_id']
        if not val: return
        match = re.search(r'race_id=(\d{12})', val)
        if not match: match = re.search(r'(\d{12})', val)
        if match:
            extracted = match.group(1)
            if extracted != val:
                st.session_state['history_display_race_id'] = extracted
                st.session_state['history_extracted'] = True

    display_race_id = st.text_input("Race ID を入力 (Display)", placeholder="202605010811", key="history_display_race_id", on_change=_on_history_display_change)
    
    if st.session_state.get('history_extracted', False):
        st.success("✨ URLからレースIDを自動抽出しました！", icon="✅")
        st.session_state['history_extracted'] = False

    display_btn = st.button("📊 解析＆結果を表示", type="primary", key="history_display_btn")
    
    if display_btn and display_race_id:
        with st.spinner("データ取得・解析中..."):
            try:
                # 1. Fetch Race Data
                disp_df = scraper.get_race_data(display_race_id)
                
                if disp_df.empty:
                    st.error("指定されたRace IDのデータが見つかりません。")
                else:
                    # 2. Calculate Indices
                    disp_df = calculator.calculate_battle_score(disp_df)
                    disp_df = calculator.calculate_n_index(disp_df)
                    
                    # 3. Fetch Actual Results (if finished race)
                    race_results = scraper.fetch_race_result(display_race_id)
                    
                    if race_results:
                        # Map actual results to DataFrame
                        disp_df['ActualRank'] = disp_df['Name'].map(
                            lambda n: race_results.get(n, {}).get('Rank', None)
                        )
                        disp_df['ResultAgari'] = disp_df['Name'].map(
                            lambda n: race_results.get(n, {}).get('Agari', None)
                        )
                        # Fill in Odds from result if live API returned 0
                        result_odds = disp_df['Name'].map(
                            lambda n: race_results.get(n, {}).get('ResultOdds', 0.0)
                        )
                        if 'Odds' in disp_df.columns:
                            disp_df['Odds'] = disp_df.apply(
                                lambda row: result_odds[row.name] if row['Odds'] == 0.0 and result_odds[row.name] > 0 else row['Odds'],
                                axis=1
                            )
                        else:
                            disp_df['Odds'] = result_odds
                        st.success(f"✅ レース結果取得済み ({len(race_results)}頭)")
                    else:
                        disp_df['ActualRank'] = None
                        disp_df['ResultAgari'] = None
                        st.info("ℹ️ レース結果はまだ取得できません（未確定）")
                    
                    # 4. Display - Race Info Header
                    race_title = disp_df['RaceName'].iloc[0] if 'RaceName' in disp_df.columns else f"Race {display_race_id}"
                    race_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={display_race_id}"
                    st.markdown(f"### 🐎 {race_title}")
                    st.markdown(f"🔗 **[Netkeiba レースページ]({race_url})**")
                    
                    # 5. Display - Analysis Table
                    display_icon_legend()
                    disp_view = disp_df.copy()
                    
                    # Sort by BattleScore
                    if 'BattleScore' in disp_view.columns:
                        disp_view = disp_view.sort_values(by='BattleScore', ascending=False).reset_index(drop=True)
                    
                    # Rank
                    disp_view['Rank'] = range(1, len(disp_view) + 1)
                    
                    # Sort by Umaban for display
                    if 'Umaban' in disp_view.columns:
                        disp_view = disp_view.sort_values(by='Umaban').reset_index(drop=True)
                    
                    # Select columns for display
                    disp_cols = ['Rank', 'Umaban', 'Name', 'Popularity', 'Odds', 'Jockey', 'BattleScore', 
                                 'OguraIndex', 'AvgAgari', 'AvgPosition', 'Alert']
                    
                    # Add result columns if available
                    if race_results:
                        disp_cols = ['Rank', 'ActualRank', 'Umaban', 'Name', 'Popularity', 'Odds', 'Jockey', 
                                     'BattleScore', 'OguraIndex', 'AvgAgari', 'AvgPosition', 
                                     'ResultAgari', 'Alert']
                    
                    disp_view = disp_view[[c for c in disp_cols if c in disp_view.columns]]
                    
                    # Format Agari
                    def fmt_agari_disp(row):
                        a = row.get('AvgAgari', 99.9)
                        if a >= 99.0: return "-"
                        return f"{a:.1f}"
                    
                    if 'AvgAgari' in disp_view.columns:
                        disp_view['AvgAgari'] = disp_df.apply(fmt_agari_disp, axis=1)
                    
                    # Format Position
                    def fmt_pos_disp(row):
                        p = row.get('AvgPosition', 99.9)
                        if p >= 99.0: return "-"
                        return f"{p:.1f}"
                    
                    if 'AvgPosition' in disp_view.columns:
                        disp_view['AvgPosition'] = disp_df.apply(fmt_pos_disp, axis=1)
                    
                    # Column Config
                    disp_col_config = {
                        "Rank": st.column_config.NumberColumn("予測順位"),
                        "ActualRank": st.column_config.NumberColumn("🏁 着順"),
                        "BattleScore": st.column_config.NumberColumn("🔥 総合戦闘力", format="%.1f"),
                        "OguraIndex": st.column_config.NumberColumn("スピード指数", format="%.1f"),
                        "AvgAgari": st.column_config.TextColumn("上がり3F"),
                        "AvgPosition": st.column_config.TextColumn("平均位置"),
                        "ResultAgari": st.column_config.NumberColumn("🏁 結果上がり", format="%.1f"),
                        "Umaban": st.column_config.NumberColumn("馬番"),
                        "Jockey": st.column_config.TextColumn("騎手"),
                        "Odds": st.column_config.NumberColumn("単勝オッズ", format="%.1f"),
                        "Popularity": st.column_config.NumberColumn("人気", format="%d"),
                    }
                    
                    # Styling
                    try:
                        styled = disp_view.style
                        
                        # Color BattleScore
                        def color_bs(s):
                            colors = []
                            for val in s:
                                try:
                                    v = float(val)
                                    if v >= 65: colors.append("background-color: #cc0000; color: white")
                                    elif v >= 50: colors.append("background-color: #ccffcc; color: black")
                                    else: colors.append("background-color: #0000cc; color: white")
                                except: colors.append("")
                            return colors
                        
                        def color_alert(s):
                            colors = []
                            for val in s:
                                if "💣" in val: colors.append("background-color: #444444; color: white; font-weight: bold")
                                elif "🎯" in val: colors.append("font-weight: bold; color: yellow")
                                elif "🚀" in val: colors.append("font-weight: bold; color: red")
                                elif "💀" in val: colors.append("font-weight: bold; color: gray")
                                else: colors.append("")
                            return colors
                        
                        # Highlight entire row for 💣 and 💀
                        def row_style(row):
                            if '💣' in str(row.get('Alert', '')) or '💀' in str(row.get('Alert', '')):
                                return ['background-color: #2F4F4F; color: #CCCCCC'] * len(row)
                            return [''] * len(row)

                        # Color ActualRank
                        def color_actual_rank(s):
                            colors = []
                            for val in s:
                                try:
                                    v = int(val)
                                    if v == 1: colors.append("background-color: #FFD700; color: black; font-weight: bold")
                                    elif v <= 3: colors.append("background-color: #FFA500; color: black")
                                    elif v <= 5: colors.append("background-color: #90EE90; color: black")
                                    else: colors.append("")
                                except: colors.append("")
                            return colors
                        
                        def color_rank_disp(s):
                            colors = []
                            for val in s:
                                try:
                                    v = int(val)
                                    if 1 <= v <= 5:
                                        colors.append("background-color: yellow; color: black")
                                    else:
                                        colors.append("")
                                except:
                                    colors.append("")
                            return colors
                        
                        if 'BattleScore' in disp_view.columns:
                            styled = styled.apply(color_bs, axis=0, subset=['BattleScore'])
                        if 'ActualRank' in disp_view.columns and race_results:
                            styled = styled.apply(color_actual_rank, axis=0, subset=['ActualRank'])
                        if 'Rank' in disp_view.columns:
                            styled = styled.apply(color_rank_disp, axis=0, subset=['Rank'])
                            
                        # Apply Never Placed styles
                        if 'Alert' in disp_view.columns:
                            styled = styled.apply(color_alert, axis=0, subset=['Alert'])
                            styled = styled.apply(row_style, axis=1)
                        
                        st.dataframe(styled, column_config=disp_col_config, use_container_width=True, hide_index=True)
                    except Exception as e:
                        st.warning(f"表示エラー (raw data表示): {e}")
                        st.dataframe(disp_view, use_container_width=True)
                    
                    # 6. Display - Result Summary (if available)
                    if race_results:
                        st.divider()
                        st.subheader("🏁 予測 vs 実績 サマリー")
                        
                        # Compare prediction rank vs actual rank
                        compare_df = disp_df[['Umaban', 'Name', 'BattleScore', 'ActualRank']].copy()
                        compare_df = compare_df.sort_values(by='BattleScore', ascending=False).reset_index(drop=True)
                        compare_df['PredictRank'] = range(1, len(compare_df) + 1)
                        compare_df = compare_df.dropna(subset=['ActualRank'])
                        compare_df['ActualRank'] = compare_df['ActualRank'].astype(int)
                        
                        # Hit check: Did our Top 3 predictions actually place?
                        top3_pred = compare_df.head(3)
                        hits = top3_pred[top3_pred['ActualRank'] <= 3]
                        
                        col_s1, col_s2, col_s3 = st.columns(3)
                        col_s1.metric("予測Top3 → 3着内的中", f"{len(hits)}/3")
                        
                        # Winner check
                        winner = compare_df[compare_df['ActualRank'] == 1]
                        if not winner.empty:
                            w_name = winner.iloc[0]['Name']
                            w_pred = winner.iloc[0]['PredictRank']
                            col_s2.metric("1着馬", f"{w_name}", f"予測順位: {w_pred}位")
                        
                        # Display comparison table
                        compare_cols = ['PredictRank', 'ActualRank', 'Umaban', 'Name', 'BattleScore']
                        st.dataframe(
                            compare_df[compare_cols],
                            column_config={
                                "PredictRank": "予測順位",
                                "ActualRank": "🏁 着順",
                                "BattleScore": st.column_config.NumberColumn("戦闘力", format="%.1f"),
                            },
                            use_container_width=True,
                            hide_index=True
                        )
                    
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
                import traceback
                st.code(traceback.format_exc())

    st.divider()

    col1, col2 = st.columns([1, 1])
    with col2:
        if st.button("🗑️ Clear History"):
            import os
            if os.path.exists("race_history.csv"):
                os.remove("race_history.csv")
                st.warning("History deleted.")
            
    df_history = history_manager.load_history()
    
    if not df_history.empty:
        # Display Improvements
        st.subheader("📜 Race History")
        
        # 1. Date Filter (Month)
        if 'Date' in df_history.columns:
            # Extract YYYY-MM
            # Handle potential parse errors or mixed formats
            try:
                df_history['YearMonth'] = pd.to_datetime(df_history['Date'], errors='coerce').dt.strftime('%Y-%m')
            except:
                df_history['YearMonth'] = "Unknown"
                
            months = sorted(df_history['YearMonth'].dropna().unique(), reverse=True)
            if not months: months = ["All"]
            
            selected_month = st.selectbox("📆 Select Month", ["All"] + list(months))
            
            if selected_month != "All":
                df_display = df_history[df_history['YearMonth'] == selected_month].copy()
            else:
                df_display = df_history.copy()
        else:
            df_display = df_history.copy()
            
        # 2. Sorting (Date Desc, RaceNum Asc)
        if 'RaceNum' in df_display.columns:
            # Ensure RaceNum is int
            df_display['RaceNum'] = pd.to_numeric(df_display['RaceNum'], errors='coerce').fillna(0)
            df_display = df_display.sort_values(by=['Date', 'RaceNum'], ascending=[False, True])
        else:
            df_display = df_display.sort_values(by='Date', ascending=False)
        
        # Drop temp col
        if 'YearMonth' in df_display.columns:
            df_display = df_display.drop(columns=['YearMonth'])

        # Show Table
        st.dataframe(df_display, use_container_width=True)

        # Metrics Calculation
        # Clean data for stats
        if 'ActualRank' in df_history.columns:
            df_calc = df_history.dropna(subset=['ActualRank'])
        else:
            df_calc = pd.DataFrame()
        
        if not df_calc.empty and 'OguraIndex' in df_calc.columns:
            df_calc['ActualRank'] = pd.to_numeric(df_calc['ActualRank'], errors='coerce')
            
            # 1. SS Rank Win/Place Rate
            if 'Status' in df_calc.columns:
                ss_horses = df_calc[df_calc['Status'] == 'SS']
                ss_total = len(ss_horses)
                if ss_total > 0:
                    ss_wins = len(ss_horses[ss_horses['ActualRank'] == 1])
                    ss_places = len(ss_horses[ss_horses['ActualRank'] <= 3])
                    
                    col_m1, col_m2 = st.columns(2)
                    col_m1.metric("SS Rank Win Rate", f"{ss_wins/ss_total:.1%}", f"{ss_wins}/{ss_total}")
                    col_m2.metric("SS Rank Place Rate", f"{ss_places/ss_total:.1%}", f"{ss_places}/{ss_total}")
                else:
                    st.info("No SS Rank data with results yet.")
                
            # 2. Ogura Top 3 Place Rate
            if 'RaceID' in df_calc.columns:
                place_hits = 0
                top3_total = 0
                
                for rid, group in df_calc.groupby('RaceID'):
                     top3 = group.sort_values(by='OguraIndex', ascending=False).head(3)
                     hits = len(top3[top3['ActualRank'] <= 3])
                     place_hits += hits
                     top3_total += len(top3)
                     
                if top3_total > 0:
                     st.metric("Index Top 3 Place Rate", f"{place_hits/top3_total:.1%}")
                     
                # 3. "Missed" List (Failures)
                cols_show = ['Date', 'RaceTitle', 'Name', 'OguraIndex', 'ActualRank', 'Status']
                cols_show = [c for c in cols_show if c in df_calc.columns]
                st.subheader("💀 Missed Candidates (Analysis Needed)")
                
                missed_list = []
                for rid, group in df_calc.groupby('RaceID'):
                    top3 = group.sort_values(by='OguraIndex', ascending=False).head(3)
                    failures = top3[top3['ActualRank'] > 3]
                    if not failures.empty:
                        missed_list.append(failures)
                    
                if missed_list:
                    df_missed = pd.concat(missed_list)
                    if cols_show:
                        st.dataframe(df_missed[cols_show].sort_values(by='Date', ascending=False), use_container_width=True)
                else:
                    st.success("No significant misses yet! (or no data)")
                
        else:
            st.warning("History exists but lacks Result data. Click 'Fetch Actual Results'.")
            
        with st.expander("Full History Data"):
            st.dataframe(df_history)
            
    else:
        st.info("No history yet. Analyze races to build your database!")

