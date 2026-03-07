import sys, io
import os
import logging

# Configure logging to handle Streamlit and sub-module output safely
logging.basicConfig(level=logging.INFO)
# Silence noisy internal logs
logging.getLogger("scrapling").setLevel(logging.ERROR)
logging.getLogger("browserforge").setLevel(logging.ERROR)
logging.getLogger("curl_cffi").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

import streamlit as st
from dotenv import load_dotenv
import google.genai as genai
from google.genai import types as genai_types

# Load environment variables from .env file (for local testing)
load_dotenv()

# API Key Management (Priority: st.secrets > .env)
# On Streamlit Cloud, set this in: Settings -> Secrets
# For local dev, use .env file: GEMINI_API_KEY="your_key"
try:
    GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
except Exception:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    st.error("API Key not found. Please set GEMINI_API_KEY in .env or Streamlit Secrets.")
    st.stop()
import importlib
import pandas as pd
import time
import math
import scraper
import calculator
# Force reload so code changes are always reflected
importlib.reload(calculator)
importlib.reload(scraper)
import theory_rmhs
importlib.reload(theory_rmhs)
from scraper import fetch_comprehensive_result
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

st.set_page_config(page_title="Keiba Analysis - Modified Ogura Index", layout="wide")

# Custom UI Styling (U-NEXT style dark sidebar)
st.markdown("""
<style>
    /* Darken sidebar background */
    [data-testid="stSidebar"] {
        background-color: #121212 !important;
    }
    /* Force white text for all elements in sidebar */
    [data-testid="stSidebar"] * {
        color: white !important;
    }
    /* Specifically target radio button labels which can be stubborn */
    [data-testid="stSidebar"] .stRadio label p {
        color: white !important;
    }
    /* Force black text for buttons in sidebar (Cache Clear button) */
    [data-testid="stSidebar"] button p {
        color: black !important;
    }
    
    /* Force main tab Race ID text input to have a white background and black text */
    div[data-testid="stTextInput"] input {
        background-color: #FFFFFF !important;
        color: #000000 !important;
    }
</style>
""", unsafe_allow_html=True)

# Sidebar: Cache Clear & Navigation
is_local = (os.name == 'nt') # Simple check for Windows local environment
is_cloud = not is_local

with st.sidebar:
    st.divider()
    if st.button("🗑️ キャッシュクリア (Cache Clear)"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.success("Cache cleared! Please re-analyze.")

    # ── Cloud Sync / Help Section ──
    st.divider()
    if is_local:
        st.markdown("### ☁️ Cloud Sync")
        st.caption("ローカルで取得したデータ（U指数等）をクラウドサーバーへ送信します。")
        if st.button("🚀 GitHubへ同期（公開）", help="push.bat を実行してデータをアップロードします。"):
            with st.spinner("Pushing to GitHub..."):
                try:
                    import subprocess
                    result = subprocess.run(["push.bat"], capture_output=True, text=True, shell=True)
                    if result.returncode == 0:
                        st.success("✅ 同期が完了しました！クラウド版でデータが利用可能です。")
                    else:
                        st.error(f"❌ 同期エラー: {result.stderr}")
                except Exception as e:
                    st.error(f"❌ 実行エラー: {e}")
    else:
        with st.expander("❓ U指数・オメガ指数を使いたい場合"):
            st.markdown("""
            クラウド版ではログインが必要なデータ（U指数など）を直接取得できません。
            
            **手順:**
            1. **ローカル版**で解析し「履歴に保存」
            2. ローカル版の「GitHubへ同期」ボタンを押す
            3. クラウド版を更新すると、データが自動反映されます。
            """)

    st.divider()
    st.markdown("### 🧭 メニュー (Menu)")
    nav = st.radio(
        "機能を選択してください",
        [
            "🏠 Single Race Analysis",
            "🔍 Race Scanner (Batch)",
            "💰 BetSync（資金管理）",
            "📊 History & Review",
            "📦 データ保管庫",
            "🧪 新ロジックテスト(FEW+マクリ)",
            "📚 RMHS分析",
            "🏇 過去走R理論スキャン",
            "💾 ロジック置き場",
            "🔬 実験その３(馬番パターン)",
        ],
        label_visibility="collapsed"
    )

st.title("🐎 Keiba Analysis - Modified Ogura Index")
st.markdown("""
**Modified Ogura Flat Index (Speed Index Based + Deviation)**
- **SS Rank**: High Outlier (Top Class, Fixed 1st).
- **Outlier**: Low Outlier (Time limit exceeded, Excluded).
- **Flat Mode**: No class multipliers.
""")

def display_icon_legend():
    with st.expander("📋 アイコンの意味（クリックで開く）"):
        st.markdown("""
        **【総合評価・アラート（Alert）】**
        *   **💣 (爆弾): 絶対に3着に絡まない馬** (人気、スピード指数、オッズ、総合戦闘力が全て下位の馬。※単勝人気8位以内は除く)
        *   **💀 (ドクロ): 危険な馬** (スピード指数が下位8頭かつ総合戦闘力が下位9頭に含まれる馬。※単勝人気8位以内は除く)
        *   **◎ (二重丸): 本命候補** (スピード指数 1位)
        *   **○ (丸): 対抗候補** (スピード指数 2位)
        *   **▲ (黒三角): 単穴候補** (スピード指数 3位)
        *   **⏱️ (時計): タイム指数保有** (過去走において優秀なタイム指数が記録されている馬)
        
        **【能力・適性・人気（各カラム）】**
        *   **🚀 (ロケット): 上がり最速（穴馬）** (過去データで上がり3Fが全体1位かつ信頼度高)
        *   **🦁 (ライオン): 先行馬** (過去の平均位置取りが5番手以内かつ信頼度高)
        *   **🔥 (炎): 上位人気馬** (現在の単勝人気が1～3番人気の馬)
        """)

# Tab Layout






# ──────────────────────────────────────────────
# 💰 BetSync（資金管理）タブ
# ──────────────────────────────────────────────
if nav == "💰 BetSync（資金管理）":
    st.header("💰 BetSync 📊 資金管理ダッシュボード")
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
    if 'bs_races'     not in _ss: _ss['bs_races']     = []   # start empty = Step 1 表示

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
        else:  # 6連法 ? step determined by cycle deficit BEFORE this race
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
    m2.metric("勝率",         f"{wins/total_races*100:.0f}%" if total_races else "-",
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
            st.error(f"✨ **全損到達（累計赤字 ¥{cur_deficit:,.0f}）。** サイクルをリセットして第1回目から再開してください。")
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
            danger_note = f"<span style='color:#FF6B6B;font-size:0.9em;'>✨ サイクル赤字：¥{cur_deficit:,.0f}?/?全損ライン：¥{total_loss_line:,}</span>" if cur_deficit > 0 else "<span style='color:#6FE09A;'>? サイクルプラス ? Step 1リセット</span>"
            border_color = "#FF6B00" if is_danger else "#FFD700"
            bg_color     = "#1f0800" if is_danger else "#1a1400"
            st.html(f"""
<div style="border:2px solid {border_color};border-radius:10px;padding:14px 18px;margin:12px 0;background:{bg_color};">
  <div style="font-size:0.82em;color:#888;margin-bottom:10px;letter-spacing:.05em;">✨ 6連法 ステッパー（サイクル赤字に応じた自動進行）</div>
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
            _3d_status = "<span style='color:#FFD700;'>✨ 数列が伸びています</span>"
        else:
            _3d_border = "#FF6B00"
            _3d_bg     = "#1f0800"
            _3d_status = "<span style='color:#FF6B6B;'>✨ 数列が長い = 深追い中</span>"

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
    st.subheader("🏁 レース履歴")

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
                step_label = f" ? {st_tag}" if st_tag else ""
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
                        badge = "<span style='background:#1a4a2a;color:#6FE09A;border:1px solid #6FE09A;border-radius:4px;padding:2px 6px;font-size:0.8em;font-weight:bold;'>📈プラス</span>"
                    elif rt == "GAMI":
                        badge = "<span style='background:#3a2a00;color:#FFB347;border:1px solid #FFB347;border-radius:4px;padding:2px 6px;font-size:0.8em;font-weight:bold;'>⚠️ガミ</span>"
                    else:
                        badge = "<span style='background:#3a0000;color:#FF7070;border:1px solid #FF7070;border-radius:4px;padding:2px 6px;font-size:0.8em;font-weight:bold;'>📉ハズレ</span>"
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
                            "✨ 払い戻し金入力",
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
                            st.success("✅ プラス（このレースで利益）", icon="✅")
                        elif nr > 0:
                            st.warning("✨ ガミ（一部回収・赤字継続）", icon=None)
                    else:
                        st.caption("❌ ハズレ → 払い戻しなし")
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
        st.caption("✨ 上のレースの勝敗（✅・❌）を選択してから次のレースを追加できます。")
    with breset:
        if st.button("✨ リセット（最初からやり直す）", key="bs_reset"):
            _ss['bs_races'] = []
            _ss['bs_strategy'] = "[稼働中] 6連サバイバル"   # ステッパーを確実に表示
            st.rerun()












# --- Tab 1: Single Race Analysis (Main View) ---
if nav == "🏠 Single Race Analysis":

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
        
        # Always clear stale advanced data when the ID is touched (prevent cross-race leakage)
        if 'test_adv_data' in st.session_state:
            del st.session_state['test_adv_data']

    # Input Layout
    col1, col2 = st.columns([1, 2])
    with col1:
        race_id_input = st.text_input("Race ID (Netkeiba)", key='main_race_id_input', on_change=_on_main_race_id_change)
        
        if st.session_state.get('main_race_id_extracted', False):
            st.success("🔗 URLからレースIDを自動抽出しました！", icon="🔗")
            st.session_state['main_race_id_extracted'] = False

        st.caption("Example: 202608020211 または Netkeiba の URL をそのまま貼り付けてもOK")
        
        race_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id_input}"
        st.markdown(f"✨ **[Netkeiba レースページを開く]({race_url})**")

    # Determine default profile based on Netkeiba JRA venue code (digits 4-5 of Race ID)
    default_profile_index = 2 # 2=Standard
    if len(race_id_input) >= 6:
        venue_c = race_id_input[4:6]
        # 04=Niigata, 05=Tokyo, 07=Chukyo -> Straight/Long
        if venue_c in ['04', '05', '07']:
            default_profile_index = 0
        # 01=Sapporo, 02=Hakodate, 03=Fukushima, 06=Nakayama, 10=Kokura -> Tight
        elif venue_c in ['01', '02', '03', '06', '10']:
            default_profile_index = 1
            
    with col2:
        st.markdown("**✨ コース特性プロファイル （開催場所から自動判定）**")
        course_profile_main = st.radio(
            "コース特性",
            options=["✨ 直線が長い・差し有利 (東京/外回り 等)", "✨ 小回り・先行有利 (中山/小倉/札幌 等)", "✨ 標準 (バランス)"],
            index=default_profile_index,
            horizontal=True,
            label_visibility="collapsed",
            help="レースIDの競馬場コードから自動で適性計算を切り替えています。"
        )

    analyze_btn = st.button("🚀 Analyze Race & Generate Map", type="primary")

    # --- Recent Races History List (Shortcut) ---
    import history_manager
    importlib.reload(history_manager)  # always pick up the latest version (avoids cached stale module)
    df_h_main = history_manager.load_history()
    if not df_h_main.empty:
        with st.expander("📁 最近解析したレース履歴から読み込む", expanded=False):
            # State for main tab history actions
            if 'main_race_action_confirm' not in st.session_state:
                st.session_state.main_race_action_confirm = None

            def execute_main_race_action():
                conf = st.session_state.main_race_action_confirm
                if not conf: return
                rid = conf["rid"]
                # Load: Set input and trigger analysis flag
                st.session_state.main_race_id_input = str(rid)
                st.session_state.tab1_analyzed_id = str(rid)
                st.session_state.main_race_action_confirm = None
                st.rerun()

            main_h_confirm = st.session_state.main_race_action_confirm
            if main_h_confirm:
                rid = main_h_confirm["rid"]
                st.warning(f"Race ID: {rid} を解析用に読み込みますか？")
                c_my, c_mn = st.columns(2)
                with c_my: st.button("✅ 実行", on_click=execute_main_race_action, use_container_width=True, key="main_race_conf_yes")
                with c_mn: st.button("❌ キャンセル", on_click=lambda: st.session_state.update({"main_race_action_confirm": None}), use_container_width=True, key="main_race_conf_no")

            # Prepare list (Last 5 races)
            df_h_unique = df_h_main.drop_duplicates(subset=['RaceID']).copy()
            # Sort by Date (assume YYYY/MM/DD)
            df_h_unique = df_h_unique.sort_values(by=['Date', 'RaceNum'], ascending=[False, False]).head(5)
            main_race_list = df_h_unique[['RaceID', 'Date', 'RaceTitle', 'Venue']].to_dict('records')

            # CSS
            css_rules_m = ["<style>"]
            for i, r in enumerate(main_race_list):
                bg = "#ffffff" if i % 2 == 0 else "#f5f5f5"
                css_rules_m.append(f"""
                    div[data-testid="stVerticalBlock"]:has(.main-race-row-{i}) div[data-testid="stHorizontalBlock"] {{
                        background-color: {bg} !important;
                        padding: 6px 10px;
                        border-radius: 4px;
                        align-items: center;
                    }}
                    div[data-testid="stVerticalBlock"]:has(.main-race-row-{i}) * {{
                        color: #333333 !important;
                    }}
                """)
            css_rules_m.append("</style>")
            st.markdown("\n".join(css_rules_m), unsafe_allow_html=True)

            for i, r in enumerate(main_race_list):
                rid = r['RaceID']
                title = r.get('RaceTitle') or f"Race {rid}"
                date = r.get('Date') or "---"
                venue = r.get('Venue') or ""
                
                mc1, mc2, mc3 = st.columns([6, 3, 1])
                with mc1:
                    st.markdown(f"<span class='main-race-row-{i}'>🏇 **{title}** <small style='color:#666'>({rid})</small></span>", unsafe_allow_html=True)
                with mc2:
                    st.caption(f"{date} {venue}")
                with mc3:
                    if st.button("📂", key=f"btn_main_hload_{rid}", help="読み込む", disabled=(main_h_confirm is not None)):
                        st.session_state.main_race_action_confirm = {"action": "load", "rid": rid}
                        st.rerun()

    if analyze_btn:
        st.session_state['tab1_analyzed_id'] = race_id_input
        
    if analyze_btn or ("race_id" in query_params and race_id_input == default_id) or st.session_state.get('tab1_analyzed_id') == race_id_input:
        with st.spinner("Fetching data and calculating indices..."):
            df = st.session_state.get('df')
            try:
                # 1. Fetch Data
                df = scraper.get_race_data(race_id_input)
                
                if df is None or df.empty:
                    is_nar_check = False
                    try:
                        if int(str(race_id_input)[4:6]) > 10: is_nar_check = True
                    except: pass
                    
                    if is_nar_check:
                        chk_url = f"https://nar.netkeiba.com/race/shutuba.html?race_id={race_id_input}"
                        st.error(f"No data found for Race ID: {race_id_input}. (⚠️ 地方競馬(NAR)のデータ取得は現在制限されているか、出馬表が未発表の可能性があります。)")
                        st.markdown(f"🔍 **確認用URL (地方):** [{chk_url}]({chk_url})")
                    else:
                        chk_url = f"https://race.netkeiba.com/race/shutuba_past.html?race_id={race_id_input}"
                        st.error(f"No data found for Race ID: {race_id_input}. (データが取得できませんでした。レースIDが正しいか、または出馬表が既に公開されているかご確認ください。)")
                        st.markdown(f"🔍 **確認用URL (JRA):** [{chk_url}]({chk_url})")
                else:
                    # 2. Calculate
                    df = calculator.calculate_battle_score(df)
                    df = calculator.calculate_n_index(df)
                    st.session_state['df'] = df
                    
                    # ★ New: Strength × Suitability calculation
                    import altair as alt
                    import numpy as _np_main
                    df = calculator.calculate_strength_suitability(df, course_profile_main)
                    
                    # --- Race Rating + Strategy (Merged) ---
                    score, rating, reasons = calculator.calculate_confidence(df) if hasattr(calculator, 'calculate_confidence') else (0, 'C', [])
                    
                    rating_icon = "➖"
                    if "S" in rating: rating_icon = "🌟"
                    elif "A" in rating: rating_icon = "➖"
                    elif "B" in rating: rating_icon = "➖"
                    st.divider()
                    st.subheader("🏁 レース情報（展開予測・波乱警戒）")
                    
                    # --- Data Processing (No Rendering Here) ---
                    fav_vuln_msg = ""
                    dark_horse_msgs = []
                    
                    try:
                        if 'Popularity' in df.columns and 'Suitability (Y)' in df.columns:
                            top_favs = df[pd.to_numeric(df['Popularity'], errors='coerce') <= 3]
                            if not top_favs.empty:
                                avg_suit = top_favs['Suitability (Y)'].mean()
                                if avg_suit < 50:
                                    fav_vuln_msg = "🚨 **【波乱警戒】** 上位人気馬のコース適性（Y軸）が全体的に低く、**ヒモ荒れや波乱の可能性が非常に高い**レースです。人気馬を過信せず、適性の高い中穴馬からのアプローチを推奨します。"
                                elif avg_suit < 65:
                                    fav_vuln_msg = "⚠️ **【中穴注意】** 上位人気馬のコース適性は平凡です。付け入る隙があり、展開次第で中穴馬が台頭する余地があります。"
                                else:
                                    fav_vuln_msg = "✨ **【軸馬信頼】** 上位人気馬のコース適性が高く安定しています。順当な決着になる確率が高いレースです。"

                            dark_horses = df[(pd.to_numeric(df['Popularity'], errors='coerce') >= 6) & (pd.to_numeric(df['Suitability (Y)'], errors='coerce') >= 65)]
                            if not dark_horses.empty:
                                for _, dh in dark_horses.iterrows():
                                    dh_name = dh['Name']
                                    dh_uma = dh['Umaban']
                                    dh_pop = int(dh['Popularity']) if pd.notnull(dh['Popularity']) else "?"
                                    dh_suit = int(dh['Suitability (Y)'])
                                    dark_horse_msgs.append(f"🐴 **{dh_uma}番 {dh_name}** ({dh_pop}人気 / 適性 {dh_suit}): 人気薄ながらコース適性抜群！激走の可能性大。")
                    except Exception as e_enh:
                        fav_vuln_msg = f"Analysis error: {e_enh}"

                    strategy_df = df.copy()
                    score_col = 'Projected Score' if 'Projected Score' in strategy_df.columns else 'BattleScore'
                    strategy_df = strategy_df.sort_values(by=score_col, ascending=False).reset_index(drop=True)
                    strategy_df['TotalScore_For_Chart'] = pd.to_numeric(strategy_df[score_col], errors='coerce').fillna(0)
                    sorted_scores = strategy_df['TotalScore_For_Chart'].tolist()
                    
                    gap_msg = ""
                    gap_type = "info"
                    if len(sorted_scores) >= 5:
                        diff_threshold = 15
                        score_1, score_2, score_3, score_4, score_5 = sorted_scores[:5]
                        gap_1_2, gap_2_3 = score_1 - score_2, score_2 - score_3
                        gap_1_5, gap_1_3, gap_3_4 = score_1 - score_5, score_1 - score_3, score_3 - score_4
                        
                        if gap_1_2 >= diff_threshold:
                            gap_msg, gap_type = "✨ **1強レース**：1位の予測スコアが突出。散布図の右上にいる馬を絶対軸に、相手は手広く3連複で。", "info"
                        elif gap_1_2 < diff_threshold and gap_2_3 >= diff_threshold:
                            gap_msg, gap_type = "✨ **2強マッチレース**：上位2頭が抜けています。この2頭を軸に『3連複2頭軸流し』が最も威力を発揮します！", "success"
                        elif gap_1_5 < 8.0:
                            gap_msg, gap_type = "🚨 **大混戦（カオス）**：全馬の予測スコアが接近。ケン推奨か、散布図の左上（高適性・低人気）の馬狙いで大穴一点。", "error"
                        elif gap_1_3 < 8.0 and gap_3_4 >= 8.0:
                            gap_msg, gap_type = "⚠️ **上位拮抗レース**：上位陣が伯仲。散布図で対角線より上の馬を中心にボックス買いが安全です。", "warning"
                        else:
                            gap_msg, gap_type = "✨ **波乱含み（中穴警戒）**：散布図で適性が高い中位馬にチャンスあり。💀を消してヒモ荒れを狙いましょう。", "warning"
                    else:
                        gap_msg, gap_type = "✨ **少頭数レース**：データが少ないため、各馬の状態や展開を重視してください。", "info"

                    GAP_VERY_LARGE, GAP_LARGE, GAP_FLAT, GAP_MIDDLE_SMALL = 50, 30, 15, 20
                    def detect_race_pattern(scores):
                        if len(scores) < 2: return 3
                        s = scores
                        gap_1_2 = s[0] - s[1]
                        gap_1_3 = s[0] - s[2] if len(s) >= 3 else gap_1_2
                        gap_top_mid = (s[2] - s[6]) if len(s) >= 7 else 0
                        gap_1_last = s[0] - s[-1]
                        if gap_1_2 >= GAP_VERY_LARGE: return 1
                        elif gap_1_3 >= GAP_LARGE and gap_1_2 < GAP_VERY_LARGE: return 2
                        elif gap_1_last < GAP_FLAT: return 5
                        elif len(scores) >= 7 and gap_top_mid < GAP_MIDDLE_SMALL: return 4
                        return 3
                    
                    race_pattern = detect_race_pattern(sorted_scores)
                    
                    if race_pattern == 1:
                        advice_color, advice_border, advice_bg = "#FF4500", "#FF4500", "#FF450015"
                        advice_title = "予測難易度: D ➖ ✨ 超固い"
                        advice_text = "<strong>✨ このレースは買わずに「見（ケン）」を強く推奨します。</strong><br><br>1位馬の指数が2位以下を圧倒しており、単勝・馬連ともに低配当が確実な構造です。むやみに買い続けると、払い戻しが投資額を下回る「プラス収支の罠」にはまります。<br><br><strong>【推奨アクション】</strong><br>▶ 基本姿勢：完全ケン（見送り）<br>▶ どうしても買いたい場合：1強馬を軸に「3連単1-2着固定」で点数を絞り、配当倍率が最低でも10倍以上になる組み合わせのみ購入<br>▶ 次の「荒れレース」に向けて資金をキープし、体力を温存することが最優先戦略です。"
                    elif race_pattern == 2:
                        advice_color, advice_border, advice_bg = "#00C8FF", "#00C8FF", "#00C8FF15"
                        advice_title = "予測難易度: C ➖ 🔥 固い"
                        advice_text = "<strong>▶ 上位2頭が安定しており、「手堅く回収」を狙えるレースです。</strong><br><br>指数上位2頭と3位以下の差が明確なため、軸が絞りやすい構造です。無理に穴を狙わず、堅実な買い目でしっかり的中率を維持しましょう。<br><br><strong>【推奨買い目】</strong><br>✨ <strong>馬連：1-2位軸の流し</strong>（相手は3～5位まで）→ 点数3～4点に絞る<br>✨ <strong>3連複：1・2位を軸に1頭ずつ固定</strong>、3頭目を3～6位から3点流し → 合計5～6点<br>✨ <strong>目標配当：馬連10～20倍、3連複30～80倍</strong><br><br>✨ このレースで確実に回収し、次のレースに向けた資金基盤を整えましょう。"
                    elif race_pattern == 3:
                        advice_color, advice_border, advice_bg = "#FFD700", "#FFD700", "#FFD70015"
                        advice_title = "予測難易度: B ➖ 🔥 通常"
                        advice_text = "<strong>✨ 最もバランスの良い「勝負レース」です。積極的に仕掛けましょう！</strong><br><br>上位馬が階段状にスコアが落ちており、1～5位に実力差はあるものの混戦要素があります。軸馬を1頭固定しつつ、相手を広げることで「中穴の旨みを取る」戦略が最適です。<br><br><strong>【推奨買い目】</strong><br>✨ <strong>馬連：1位軸から2～6位への流し</strong> → 5点<br>✨ <strong>3連複：1位を軸1頭固定、2～7位から6頭選んで流し</strong> → 15点前後<br>✨ <strong>3連単：1位→2・3位固定→4～7位まで流し</strong>で点数を絞った高配当狙い<br>✨ <strong>目標配当：馬連15～40倍、3連複50～200倍</strong><br><br>✨ 消し馬ロジック（💀マーク）を最大活用し、買い目数を削減してください。点数を絞るほど回収率が上がります。"
                    elif race_pattern == 4:
                        advice_color, advice_border, advice_bg = "#7FFF00", "#7FFF00", "#7FFF0015"
                        advice_title = "予測難易度: A ➖ ⚠️ 荒れ"
                        advice_text = "<strong>⚠️ 上位陣が伯仲しており、軸選びが非常に難しいレースです。</strong><br><br>1位から中位までのスコア差が小さく、展開一つで着順が大きく入れ替わる可能性が高いです。「荒れる」可能性を秘めており、手広く買うか、あるいは見送るかの判断が求められます。<br><br><strong>【推奨買い目】</strong><br>✨ <strong>馬連/ワイド：上位5頭のボックス買い</strong>（10点）で確実に的中を拾う<br>✨ <strong>3連複：上位5～6頭のボックス買い</strong>（10～20点）<br>✨ <strong>フォーメーション：</strong>どうしても勝負したい場合は、好調教馬や騎手評価の高い馬を1列目に置く<br><br>✨ 資金に余裕がない場合は、「見（ケン）」も立派な戦略です。"
                    elif race_pattern == 5:
                        advice_color, advice_border, advice_bg = "#FF1493", "#FF1493", "#FF149315"
                        advice_title = "予測難易度: S ➖ ✨ 大荒れ"
                        advice_text = "<strong>🚨 超危険！大波乱の予感が漂う「爆穴狙い推奨」レースです。</strong><br><br>1位から最下位までのスコア差が極めて小さく、人気馬に明確な死角があります。全馬に勝つチャンスがあるため、最も回収率を爆増させやすいレースです。<br><br><strong>【推奨買い目】</strong><br>✨ <strong>3連複全頭流し：</strong>どうしても勝負したい場合は、好適性の穴馬から全通りを買う「全流し」で事故待ち<br>✨ <strong>単勝・複勝コロガシ：</strong>10番人気以下の馬から単複を買う<br><br>✨ 安全に行くなら100%「見」ですが、ギャンブルとして楽しむなら最高の舞台です。"
                    else:
                        advice_color, advice_border, advice_bg = "#9400D3", "#9400D3", "#9400D315"
                        advice_title = "予測難易度: Unknown ➖ 🚨 大混戦（カオス）"
                        advice_text = "<strong>🚨 全馬の実력이拮抗しており、何が来てもおかしくない「超難解レース」です。</strong><br><br>予測スコアが完全にフラットになっており、データからは軸馬を絞りきれません。高配当が狙える一方、的中率は極めて低くなります。<br><br><strong>【推奨アクション】</strong><br>▶ 基本姿勢：完全ケン（見送り）<br>▶ <strong>一攫千金狙い（遊び）</strong>：散布図の「左上（高適性・低人気）」にいる【波乱の使者】から単勝やワイドを少額で買う<br>▶ <strong>全頭買い</strong>：資金に余裕があれば、荒れることを前提に入線を祈る<br><br>✨ 「わからないレースは買わない」が投資競馬の鉄則です。無理な勝負は避けましょう。"
                    # --- UI Rendering ---
                    col_r1, col_r2 = st.columns([1.3, 1])
                    with col_r1:
                        # Render Pattern Advisor Component (First)
                        # Remove forced colors to let Streamlit handle dark/light mode dynamically while keeping the background colorful
                        st.markdown(f"""
                        <div style="background-color: {advice_bg}; border: 2px solid {advice_border}; border-radius: 12px; padding: 24px 28px; margin-bottom: 24px; box-shadow: 0 0 22px {advice_color}55;">
                            <div style="font-size: 1.4em; font-weight: bold; color: {advice_color}; margin-bottom: 14px; border-bottom: 1px solid {advice_border}55; padding-bottom: 10px;">
                                {advice_title}
                            </div>
                            <div style="font-size: 1.0em; line-height: 2.0;">
                                {advice_text}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        # Render Gap Strategy
                        getattr(st, gap_type)(gap_msg)
                        
                        # Render Upset/Vulnerability
                        if fav_vuln_msg:
                            st.info(fav_vuln_msg)
                        if dark_horse_msgs:
                            formatted_dark_horses = "  \n\n".join(dark_horse_msgs)
                            st.warning(f"🎯 **【注目の適性ダークホース】**  \n\n{formatted_dark_horses}")

                        # --- NEW: CHAOS INDEX (荒れ度判定) ---
                        score_col = 'Test_Score' if 'Test_Score' in df.columns else ('Projected Score' if 'Projected Score' in df.columns else 'BattleScore')
                        if score_col in df.columns and 'Popularity' in df.columns:
                            valid_df = df.dropna(subset=[score_col, 'Popularity'])
                            
                            top5_scores = valid_df.sort_values(by=score_col, ascending=False).head(5)[score_col]
                            std_dev = top5_scores.std() if len(top5_scores) > 1 else 0
                            
                            pop_avg = valid_df[valid_df['Popularity'] <= 3][score_col].mean()
                            dark_horses = valid_df[valid_df['Popularity'] >= 7]
                            dark_max = dark_horses[score_col].max() if not dark_horses.empty else 0
                            
                            if pd.isna(pop_avg): pop_avg = 0
                            if pd.isna(dark_max): dark_max = 0
                            
                            chaos_status = "🟢 順当"
                            chaos_desc = "人気と実力が概ね一致しています。"
                            if dark_max > pop_avg and std_dev < 3.0:
                                chaos_status = "🔴 大荒れ注意"
                                chaos_desc = "人気馬の指数が低く、実力が拮抗しています。穴馬券を狙う大チャンス！"
                            elif dark_max > pop_avg or std_dev < 4.5:
                                chaos_status = "🟡 波乱含み"
                                chaos_desc = "指数上位に穴馬が混じっています。ヒモ荒れに警戒してください。"
                                
                            st.metric("📊 荒れ度 (Chaos Index)", chaos_status, help=f"上位5頭のスコア偏差: {std_dev:.1f} / 人気上位平均: {pop_avg:.1f} vs 穴馬最高: {dark_max:.1f}")
                            st.caption(chaos_desc)
                        else:
                            st.metric("📊 荒れ度 (Chaos Index)", "判定不能")
                            
                        # --- NEW: Predicted Difficulty Display ---
                        pred_diff = calculator.calculate_predicted_difficulty(df) if df is not None and not df.empty else "B"
                        diff_labels = {"S": "大荒れ (S)", "A": "荒れ (A)", "B": "通常 (B)", "C": "堅い (C)"}
                        st.metric("予測レース難易度", diff_labels.get(pred_diff, "判定不能"))
                            
                    with col_r2:
                        st.progress(min(score, 100) / 100.0)
                        if reasons:
                            st.caption(f"Reason: {', '.join(reasons)}")
                    
                    st.divider()
                    # --- 強適 Ranking Table ---
                    st.subheader("📊 強適 Ranking Table")
                    display_icon_legend()

                    view_df = df.copy()

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
                        
                        view_df['Name'] = view_df.apply(fmt_pop_name, axis=1)
                        if 'Jockey' in view_df.columns:
                            view_df = calculator.apply_jockey_icons(view_df)

                    # Speed Index Rank (Shortened)
                    if 'SpeedIndex' in df.columns:
                        df['SpRank'] = df['SpeedIndex'].rank(ascending=False, method='min')

                    # Sort by Projected Score (new)
                    if 'Projected Score' in view_df.columns:
                        view_df = view_df.sort_values(by='Projected Score', ascending=False).reset_index(drop=True)
                    elif 'BattleScore' in view_df.columns:
                        view_df = view_df.sort_values(by='BattleScore', ascending=False).reset_index(drop=True)

                    # Add time icon
                    if 'TimeIndexAvg5' in view_df.columns:
                        def add_time_icon(row):
                            alert = str(row.get('Alert', ''))
                            if row.get('TimeIndexAvg5', 0) > 0 and '⏱️' not in alert:
                                return alert + ' ⏱️'
                            return alert
                        view_df['Alert'] = view_df.apply(add_time_icon, axis=1)

                    # Format Agari (34.5 (1))
                    def fmt_agari(row):
                        a = row.get('AvgAgari', 99.9)
                        r = row.get('AgariRank', 99)
                        trusted = row.get('AgariTrust', False)
                    
                        if a >= 99.0: return "-"
                        try:
                            r_int = int(r)
                            icon = " 🚀" if (r_int == 1 and trusted) else ""
                            return f"{a:.1f} ({r_int}位){icon}"
                        except:
                            return f"{a:.1f}"

                    view_df['AvgAgari'] = df.apply(fmt_agari, axis=1)

                    # Format Position (2.5 🦁)
                    def fmt_pos(row):
                        p = row.get('AvgPosition', 99.9)
                        trusted = row.get('PosTrust', False)
                    
                        if p >= 99.0: return "-"
                        icon = " 🦁" if (p <= 5.0 and trusted) else ""
                        return f"{p:.1f}{icon}"
                    
                    view_df['AvgPosition'] = df.apply(fmt_pos, axis=1)

                    view_df['Rank'] = range(1, len(view_df) + 1)

                    # New column set with Projected Score highlighted
                    cols = ['Rank', 'Umaban', 'Name', 'Popularity', 'Odds', 'Jockey',
                            'Projected Score', 'Strength (X)', 'Suitability (Y)', 'BattleScore', 'Alert', 'AvgAgari', 'AvgPosition']
                    view_df = view_df[[c for c in cols if c in view_df.columns]]

                    column_config = {
                        "Projected Score": st.column_config.NumberColumn("⭐ 予測スコア", format="%.1f"),
                        "Strength (X)": st.column_config.NumberColumn("💪 強さ(X)", format="%.0f"),
                        "Suitability (Y)": st.column_config.NumberColumn("🎯 適性(Y)", format="%.0f"),
                        "BattleScore": st.column_config.NumberColumn("🔥 戦闘力", format="%.1f"),
                        "Umaban": st.column_config.NumberColumn("馬番"),
                        "Jockey": st.column_config.TextColumn("騎手"),
                        "Odds": st.column_config.NumberColumn("単勝オッズ", format="%.1f"),
                        "Popularity": st.column_config.NumberColumn("人気", format="%d"),
                        "AvgAgari": st.column_config.TextColumn("上がり3F (順位)"),
                        "AvgPosition": st.column_config.TextColumn("平均位置取り"),
                    }

                    try:
                        def color_projected(s):
                            colors = []
                            vals = pd.to_numeric(s, errors='coerce')
                            vmax, vmin = vals.max(), vals.min()
                            spread = vmax - vmin if vmax != vmin else 1
                            for v in vals:
                                if pd.isna(v): colors.append("")
                                elif v >= vmax - spread * 0.1:
                                    colors.append("background-color: #cc0000; color: white")
                                elif v >= vmin + spread * 0.5:
                                    colors.append("background-color: #ccffcc; color: black")
                                else:
                                    colors.append("background-color: #0000cc; color: white")
                            return colors

                        def color_rank(s):
                            return ["background-color: yellow; color: black" if 1 <= (int(v) if str(v).isdigit() else 99) <= 5 else "" for v in s]

                        def color_alert(s):
                            colors = []
                            for val in s:
                                if "💣" in str(val): colors.append("background-color: #444444; color: white; font-weight: bold")
                                elif "💀" in str(val): colors.append("font-weight: bold; color: yellow")
                                elif "◎" in str(val): colors.append("font-weight: bold; color: red")
                                elif "⏱️" in str(val): colors.append("font-weight: bold; color: gray")
                                else: colors.append("")
                            return colors

                        styled_df = view_df.style
                        if 'Projected Score' in view_df.columns:
                            styled_df = styled_df.apply(color_projected, axis=0, subset=['Projected Score'])
                        if 'Rank' in view_df.columns:
                            styled_df = styled_df.apply(color_rank, axis=0, subset=['Rank'])
                        if 'Alert' in view_df.columns:
                            styled_df = styled_df.apply(color_alert, axis=0, subset=['Alert'])
                        st.dataframe(styled_df, column_config=column_config, use_container_width=True, hide_index=True)
                    except Exception as e:
                        st.warning(f"Display Error: {e}")
                        st.dataframe(view_df)

                    # --- RESURRECTED: Composite Chart (Dual-Axis with Altair) ---
                    st.subheader("✨ Index Analysis Chart")
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
                    
                    # --- 強適マップ 散布図 (Main Feature) ---
                    st.subheader("📊 強適シート (Strength × Suitability)")
                    st.caption("右上ゾーン（強い×合う）の馬が注目馬。対角線より上の馬が買い目の中心候補。")
                    
                    try:
                        import pandas as pd_sc
                        df_sc = df.copy()
                        
                        # Add Bomb Horse Highlight
                        if 'Popularity' in df_sc.columns and 'Strength (X)' in df_sc.columns and 'Suitability (Y)' in df_sc.columns:
                            def add_bomb_icon(r):
                                name_str = str(r['Name'])
                                if r.get('Popularity', 99) >= 7 and r.get('Strength (X)', 0) > 50 and r.get('Suitability (Y)', 0) > 50:
                                    return f"🔥{name_str}"
                                return name_str
                            df_sc['Name'] = df_sc.apply(add_bomb_icon, axis=1)
                    
                        # Rank diff label
                        df_sc['Old Rank'] = df_sc['BattleScore'].rank(ascending=False, method='min').astype(int)
                        df_sc['New Rank'] = df_sc['Projected Score'].rank(ascending=False, method='min').astype(int)
                        df_sc['Rank Diff'] = df_sc['Old Rank'] - df_sc['New Rank']
                        df_sc['Trend'] = df_sc['Rank Diff'].apply(lambda x: '↑' if x > 0 else ('↓' if x < 0 else 'ー'))
                    
                        # Jitter
                        _rng_m = _np_main.random.default_rng(seed=42)
                        df_sc['_sx'] = (df_sc['Strength (X)'] + _rng_m.uniform(-2.5, 2.5, len(df_sc))).clip(1, 99)
                        df_sc['_sy'] = (df_sc['Suitability (Y)'] + _rng_m.uniform(-2.5, 2.5, len(df_sc))).clip(1, 99)
                    
                        domain_m = ['↑', '↓', 'ー']
                        range_m  = ['#e05252', '#5281e0', '#aaaaaa']
                    
                        base_m = alt.Chart(df_sc).encode(
                            x=alt.X('_sx:Q', scale=alt.Scale(domain=[-5, 105]), title='強い →'),
                            y=alt.Y('_sy:Q', scale=alt.Scale(domain=[-5, 105]), title='合う ↑')
                        )
                        pts_m = base_m.mark_circle(size=3500, opacity=0.75).encode(
                            color=alt.Color('Trend:N', scale=alt.Scale(domain=domain_m, range=range_m), legend=alt.Legend(title="Rank Shift")),
                            tooltip=['Umaban', 'Name', 'Strength (X)', 'Suitability (Y)', 'Projected Score', 'BattleScore']
                        )
                        num_m  = base_m.mark_text(align='center', baseline='middle', dy=-5, color='white', fontWeight='bold', fontSize=14).encode(text='Umaban:N')
                        name_m = base_m.mark_text(align='center', baseline='top', dy=30, color='#222', fontWeight='bold', fontSize=11).encode(text='Name:N')
                    
                        # Diagonal line (buy zone)
                        diag_m_df = pd.DataFrame({'x': [0, 100], 'y': [75, 25]})
                        diag_m = alt.Chart(diag_m_df).mark_line(strokeDash=[8, 6], color='#888888', strokeWidth=2, opacity=0.7).encode(x='x:Q', y='y:Q')
                        zone_m_df = pd.DataFrame({'x': [8], 'y': [95], 'label': ['◎ 強い×合う（推奨ゾーン）']})
                        zone_m = alt.Chart(zone_m_df).mark_text(align='left', color='#cc2222', fontSize=12, fontWeight='bold').encode(x='x:Q', y='y:Q', text='label:N')
                    
                        st.altair_chart((diag_m + zone_m + pts_m + num_m + name_m).properties(height=550).interactive(), use_container_width=True)
                    except Exception as e_sc:
                        st.warning(f"強適マップの描画中にエラー: {e_sc}")
                    
                    st.divider()
                    
                    # 3. Display
                    
                    # --- Direct Match Pyramid ---
                    # Define one_year_ago for filtering
                    one_year_ago = datetime.now() - timedelta(days=365)
                    
                    # Define current_surf for filtering
                    try:
                        if df is not None and not df.empty:
                            if 'Type' in df.columns:
                                current_surf = df['Type'].iloc[0]
                            elif 'Track' in df.columns:
                                current_surf = df['Track'].iloc[0]
                            else:
                                current_surf = '芝'
                        else:
                            current_surf = '芝'
                    except:
                        current_surf = '芝'
                    
                    matches = calculator.get_direct_matches(df) if df is not None and not df.empty else []
                    if matches:
                        st.subheader("🥊 Direct Match Pyramid")
                        st.caption("Color: 🔴>=70, 🟢 50-69, 🔵 <50 (Speed Index) | 過去1年・同コースタイプの対戰のみ表示")
                    
                        # Verify loss counts for thick border
                        loss_counts = {}
                        for w, l, _ in matches:
                            loss_counts[l] = loss_counts.get(l, 0) + 1
                        
                        dot = 'digraph {'
                        dot += 'rankdir=TB;'
                        dot += 'size="14,10"; ratio=compress;'  # Fixed canvas size prevents layout variation
                        dot += 'nodesep=0.8; ranksep=1.2;'
                        dot += 'node [shape=circle, fixedsize=true, width=1.8, style="filled", fontname="Meiryo", fontsize=14];'
                        dot += 'edge [penwidth=2.0];'
                    
                        df['SpeedRank'] = df['SpeedIndex'].rank(ascending=False)
                    
                        unique_edges = set()
                        has_edges = False
                    
                        # Calculate excluded horses (Bottom 30% by Projected Score or BattleScore)
                        import math
                        num_horses = len(df)
                        exclude_count = math.ceil(num_horses * 0.3)
                        sort_col = 'Projected Score' if 'Projected Score' in df.columns else 'BattleScore'
                        if sort_col in df.columns:
                            sorted_df = df.sort_values(by=sort_col, ascending=False)
                            excludes_df = sorted_df.tail(exclude_count)
                            excluded_names = excludes_df['Name'].tolist()
                        else:
                            excluded_names = []
                            
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
                        
                            # Labels with large Skull icon next to Umaban if in Exclude List
                            w_umaban_disp = f'{w_umaban} <FONT POINT-SIZE="48">💀</FONT>' if w in excluded_names else w_umaban
                            l_umaban_disp = f'{l_umaban} <FONT POINT-SIZE="48">💀</FONT>' if l in excluded_names else l_umaban
                            
                            w_label = f'<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0"><TR><TD><B><FONT POINT-SIZE="28">{w_umaban_disp}</FONT></B></TD></TR><TR><TD><FONT POINT-SIZE="16">{w}</FONT></TD></TR></TABLE>>'
                            l_label = f'<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0"><TR><TD><B><FONT POINT-SIZE="28">{l_umaban_disp}</FONT></B></TD></TR><TR><TD><FONT POINT-SIZE="16">{l}</FONT></TD></TR></TABLE>>'
                        
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
                         
                    # --- Exclude Recommended List & Dark Horse ---
                    st.divider()
                    col_el_left, col_el_right = st.columns([1, 1])

                    with col_el_left:
                        st.subheader("💀 消し推奨馬（予測スコア下位30%）")
                        
                        import math
                        num_horses = len(df)
                        exclude_count = math.ceil(num_horses * 0.3)
                        
                        # Use Projected Score or BattleScore for the ranking
                        sort_col = 'Projected Score' if 'Projected Score' in df.columns else 'BattleScore'
                        
                        # Sort descending, so the worst horses are at the tail
                        if sort_col in df.columns:
                            sorted_df = df.sort_values(by=sort_col, ascending=False)
                            excludes = sorted_df.tail(exclude_count)
                        else:
                            # Fallback if neither score column exists
                            excludes = pd.DataFrame()

                        if not excludes.empty:
                            # Show the horses that are being mathematically excluded
                            for _, row in excludes.iterrows():
                                score_val = row.get(sort_col, 0.0)
                                st.markdown(f"**{row['Umaban']} - {row['Name']}** (予測スコア: {float(score_val):.1f})")
                        else:
                            st.info("消し推奨に該当する馬はいませんでした。")
                            
                    with col_el_right:
                        st.subheader("🎯 推奨穴馬 (Top Dark Horse)")
                        try:
                            if 'Popularity' in df.columns and 'Suitability (Y)' in df.columns:
                                dark_horses = df[(pd.to_numeric(df['Popularity'], errors='coerce') >= 6) & (pd.to_numeric(df['Suitability (Y)'], errors='coerce') >= 60)]
                                if not dark_horses.empty:
                                    # Sort by Suitability highest first
                                    dark_horses = dark_horses.sort_values(by='Suitability (Y)', ascending=False)
                                    best_dh = dark_horses.iloc[0]
                                    
                                    dh_name = best_dh['Name']
                                    dh_uma = best_dh['Umaban']
                                    dh_pop = int(best_dh['Popularity']) if pd.notnull(best_dh['Popularity']) else "?"
                                    dh_suit = int(best_dh['Suitability (Y)'])
                                    dh_score = best_dh.get('Projected Score', best_dh.get('BattleScore', 0.0))
                                    
                                    st.warning(f"""
                                    **🐴 {dh_uma}番 {dh_name}**
                                    * **人気**: {dh_pop}番人気
                                    * **コース適性**: {dh_suit} (抜群)
                                    * **予測スコア**: {float(dh_score):.1f}
                                    
                                    予測や戦闘力では一歩譲るかもしれませんが、**特化した強み（コース適性）**を持っており、展開次第で一発激走の可能性がある不気味な1頭です。ヒモに加えておくことをお勧めします。
                                    """)
                                else:
                                    st.info("現在、条件に合致する強力な穴馬は見当たりません。")
                            else:
                                st.info("オッズまたは適性データが不足しています。")
                        except Exception as e_dh:
                            st.error(f"穴馬計算エラー: {e_dh}")

                    # --- 🎯 買い目用 10選 コンテナ (Visual Reordering) ---
                    # We create the container here so it renders ABOVE the Axis Selection,
                    # but we populate it below after Axis Selection is determined.
                    recommends_container = st.container()

                    # --- 共通の軸馬選択 (Shared Axis Selection) ---
                    st.divider()
                    st.subheader("🔩 買い目用 軸馬設定")
                    st.caption("ここで選んだ軸馬は、下部の「荒れ予想専用特殊狙い」および「3連複スペシャル」のベースとなります。")

                    # Build horse choices ordered by Projected Score (desc)
                    sort_col = 'Projected Score' if 'Projected Score' in df.columns else 'BattleScore'
                    df_axis_sorted = df.sort_values(sort_col, ascending=False).reset_index(drop=True)
                    horse_choices = []
                    for _, row in df_axis_sorted.iterrows():
                        u_val = int(row['Umaban']) if pd.notnull(row['Umaban']) else 0
                        horse_choices.append(f"[{u_val:02d}] {row['Name']}")

                    # Pre-fill top-2 Projected Score horses as default axis
                    default_axis = horse_choices[:2] if len(horse_choices) >= 2 else []

                    axis_selections = st.multiselect(
                        "🔩 軸馬を「2頭」選んでください（予測スコア順にソート済み）:",
                        options=horse_choices,
                        default=default_axis,
                        max_selections=2
                    )

                    # Extract raw umaban lists
                    selected_axis_umaban = None
                    if len(axis_selections) == 2:
                        valid_names = [sel.split("] ")[1] for sel in axis_selections]
                        selected_axis_umaban = df[df['Name'].isin(valid_names)]['Umaban'].tolist()

                    # --- 🎯 指数該当・人気順10選 / A・S専用買い目 ---
                    # Populate the container created above
                    with recommends_container:
                        st.divider()
                        
                        if race_pattern in [4, 5]:
                            st.html("""
                            <div style="background-color: #3d0000; border: 3px solid #ff4500; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 0 30px #ff450077;">
                                <h3 style="color: #ffd700; text-align: center; margin-bottom: 5px; font-weight: 900; letter-spacing: 2px;">🚨 【荒れ予想専用】あなた独自の軸2頭 ＋ 中穴 特殊狙い 🚨</h3>
                                <p style="color: #ffcccc; text-align: center; margin-top: 0; font-size: 1.1em; font-weight: bold;">このレースは難易度がA/S判定のため、自動的に高配当特化の「選択した軸2頭 ＋ その他の全馬」の組み合わせに切り替わりました。</p>
                            </div>
                            """)
                        else:
                            st.subheader("🎯 指数上位＋推奨穴馬の最適買い目")
                            st.caption("予測スコア上位5頭に「推奨穴馬（🔥）」を加え、期待値上位の買い目を抽出します。トリガミを防ぐ資金管理も自動計算します。")
                            
                        with st.spinner("オッズ取得・計算中..."):
                            try:
                                # Use Projected Score to define top-5 axis horses
                                if 'Projected Score' in df.columns:
                                    df_for_recs = df.copy()
                                    df_for_recs['BattleScore'] = df_for_recs['Projected Score']
                                else:
                                    df_for_recs = df
                                odds_list = scraper.fetch_sanrenpuku_odds(race_id_input)

                                if not odds_list:
                                    st.error("データ取得失敗: 3連複のオッズ・人気データが取得できませんでした。")
                                    recs = []
                                else:
                                    # Define top-5 horses based on Projected Score
                                    sort_col = 'Projected Score' if 'Projected Score' in df.columns else 'BattleScore'
                                    top5_df = df.sort_values(by=sort_col, ascending=False).head(5)
                                    top5_scores = [float(row[sort_col]) for idx, row in top5_df.iterrows()]
                                    
                                    # Identify any Dark Horses or Fitness Horses not in Top 5
                                    icon_regex = r'🔥|🎯|○|▲|🚀'
                                    fitness_horse_df = df[(df['Alert'].str.contains(icon_regex, na=False, regex=True)) & (~df['Name'].isin(top5_df['Name']))]
                                    
                                    # Combine Top 5 + Fitness Horses to form candidate pool
                                    candidate_df = pd.concat([top5_df, fitness_horse_df]).drop_duplicates(subset=['Umaban'])
                                    
                                    candidate_horses = []
                                    import re
                                    for idx, row in candidate_df.iterrows():
                                        alert_str = str(row['Alert'])
                                        candidate_horses.append({
                                            'Umaban': int(row['Umaban']),
                                            'Name': row['Name'],
                                            'Score': float(row[sort_col]),
                                            'HasFitness': bool(re.search(r'🔥|🎯|○|▲', alert_str)),
                                            'HasRocket': '🚀' in alert_str
                                        })

                                    # Strategic Formation Recommendation Panel
                                    scores = top5_scores
                                    if len(scores) >= 4:
                                        first_score = scores[0]
                                        second_score = scores[1]
                                        fourth_score = scores[3]
                                        
                                        st.markdown("#### 💡 システム推奨フォーメーション")
                                        if first_score >= second_score * 1.2:
                                            st.success(f"**【1頭軸フォーメーション推奨】** トップの {top5_df.iloc[0]['Name']} が抜けています。(1-4-4)などの組み立てが有効です。")
                                        elif (first_score - fourth_score) <= (first_score * 0.05):
                                            st.warning("**【混戦用フォーメーション推奨】** 上位陣の実力差がほぼありません。(2-2-6)などの手広いフォーメーションが有効です。")
                                        else:
                                            st.info("**【標準ボックス推奨】** 順当なスコア分布です。上位5頭のボックス買い（10点）を軸に検討してください。")
                                            
                                    st.divider()
                                    st.markdown("#### 💸 合成オッズ・資金配分シミュレーター")
                                    bankroll = st.number_input("この買い目にかける総予算（円）", min_value=100, value=10000, step=100, format="%d")
                                    
                                    from itertools import combinations
                                    box_combos = list(combinations(candidate_horses, 3))
                                    
                                    raw_recs = []
                                    
                                    for combo in box_combos:
                                        # combo is a tuple of 3 horse dicts
                                        sorted_combo = sorted(combo, key=lambda x: x['Umaban'])
                                        combo_str = f"{sorted_combo[0]['Umaban']}-{sorted_combo[1]['Umaban']}-{sorted_combo[2]['Umaban']}"
                                        combo_names = f"{sorted_combo[0]['Name']}・{sorted_combo[1]['Name']}・{sorted_combo[2]['Name']}"
                                        score_sum = sum(h['Score'] for h in combo)
                                        has_fitness = any(h['HasFitness'] for h in combo)
                                        has_rocket = any(h['HasRocket'] for h in combo)
                                        
                                        # Find odds from the fetched list
                                        matched_odds = 0.0
                                        for odds_item in odds_list:
                                            if odds_item['Combination'] == combo_str:
                                                matched_odds = odds_item['Odds']
                                                break
                                                
                                        # Skip if no odds found or odds is zero (e.g. ---)
                                        if matched_odds <= 0.0:
                                            continue
                                            
                                        expected_value = score_sum * matched_odds
                                        if has_fitness:
                                            score_sum *= 1.2 # Fitness Bonus (+20%)
                                            expected_value *= 1.2
                                        if has_rocket:
                                            score_sum *= 1.15 # Rocket Bonus (+15%)
                                            expected_value *= 1.15
                                        
                                        raw_recs.append({
                                            'Combination': combo_str,
                                            'HorseNames': combo_names,
                                            'ScoreSum': score_sum,
                                            'Odds': matched_odds,
                                            'ExpectedValue': expected_value,
                                            'HasFitness': has_fitness,
                                            'HasRocket': has_rocket
                                        })
                                        
                                    # 1. 🎯 的中重視枠 (Hit-focused): Top 3 by ScoreSum (Regardless of odds)
                                    raw_recs.sort(key=lambda x: x['ScoreSum'], reverse=True)
                                    hit_focused = raw_recs[:3]
                                    for r in hit_focused: r['Slot'] = "🎯 的中優先"
                                    
                                    # 2. 💸 期待値重視枠 (EV-focused): Top 7 by ExpectedValue from the remainder
                                    remaining = raw_recs[3:]
                                    remaining.sort(key=lambda x: x['ExpectedValue'], reverse=True)
                                    ev_focused = remaining[:7]
                                    for r in ev_focused: r['Slot'] = "💸 期待値優先"
                                    
                                    # Combine to total 10 combinations
                                    recs = hit_focused + ev_focused
                                    
                                    # Calculate Bankroll Distribution on the extracted 10 combinations
                                    inverse_odds_sum = sum((1.0 / r['Odds']) for r in recs)
                                    synthetic_odds = 0.0
                                    
                                    if inverse_odds_sum > 0:
                                        synthetic_odds = 1.0 / inverse_odds_sum
                                        
                                        if synthetic_odds < 3.0:
                                            st.error(f"⚠️ **トリガミ注意**: 現在のオッズプールでの合成オッズは **{synthetic_odds:.2f}倍** です。リターンが低すぎるため見送りも検討してください。")
                                        else:
                                            st.success(f"📊 現在のオッズプールでの合成オッズ: **{synthetic_odds:.2f}倍**")
                                            
                                        for r in recs:
                                            target_payout = bankroll * synthetic_odds
                                            exact_bet = target_payout / r['Odds']
                                            r['RecommendedBet'] = max(100, int(round(exact_bet / 100.0) * 100))
                                    else:
                                        for r in recs: r['RecommendedBet'] = 0

                                if recs:
                                    def highlight_dark_horse(row):
                                        return ['background-color: #3b0a0a; color: #ffebcc' if '含有' in str(row['適性フラグ']) else '' for _ in row]
                                        
                                    for r in recs:
                                        if r['HasFitness'] and r['HasRocket']:
                                            r['HorseNames'] = f"🔥🚀 {r['HorseNames']}"
                                            r['FlagText'] = "🔥🚀 含有 (+35%)"
                                        elif r['HasFitness']:
                                            r['HorseNames'] = f"✅ {r['HorseNames']}"
                                            r['FlagText'] = "🔥 含有 (1.2倍)"
                                        elif r['HasRocket']:
                                            r['HorseNames'] = f"🚀 {r['HorseNames']}"
                                            r['FlagText'] = "🚀 上がり最速 (1.15倍)"
                                        else:
                                            r['FlagText'] = ""
                                            
                                    rec_df = pd.DataFrame([
                                        {
                                            "選出枠": r['Slot'],
                                            "適性フラグ": r['FlagText'],
                                            "期待値": f"{r['ExpectedValue']:.1f}",
                                            "買い目": r['Combination'],
                                            "馬名組み合わせ": r['HorseNames'],
                                            "オッズ": f"{r['Odds']:.1f}倍",
                                            "推奨購入額(円)": f"¥{r['RecommendedBet']:,}",
                                        } for r in recs
                                    ])
                                    st.dataframe(rec_df.style.apply(highlight_dark_horse, axis=1), use_container_width=True)
                                else:
                                    is_nar = False
                                    if 'race_id_input' in locals() and len(race_id_input) >= 6:
                                        try:
                                            # Netkeiba venue codes > 10 are NAR (e.g., 42, 45, 65)
                                            if int(str(race_id_input)[4:6]) > 10:
                                                is_nar = True
                                        except: pass
                                        
                                    if is_nar:
                                        st.warning("⚠️ **地方競馬（NAR）のオッズ自動取得は現在サポートされていません。** 買い目と資金配分の計算はJRAレースでのみご利用いただけます。")
                                    else:
                                        st.info("オッズが取得できなかったか、該当する買い目が見つかりませんでした。（発売前の場合は発売開始後に再度お試しください）")

                            except Exception as e:
                                st.error(f"3連複推奨データの取得中にエラーが発生しました: {e}")

                    # --- ✨ ３連複スペシャル（2頭軸流し自動生成） ---
                    st.divider()
                    st.subheader("✨ ３連複スペシャル（2頭軸流し自動生成）")
                    st.caption("上で設定した軸馬2頭に対して、残りから強適スコア順にヒモを自動選出します。")
                    
                    if axis_selections and len(axis_selections) == 2:
                        # Extract selected horse names
                        axis_names = [sel.split("] ")[1] for sel in axis_selections]
                    
                        # Filter out axis horses + danger horses
                        pool_df = df[~df['Name'].isin(axis_names)].copy()
                        pool_df = pool_df[~pool_df['Alert'].astype(str).str.contains(r"💣|💀", regex=True)]
                    
                        # Sort remaining horses by Projected Score (new) descending
                        pool_df = pool_df.sort_values(sort_col, ascending=False)
                        
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
                        st.info("※上で軸馬を「あと1頭」選んでください。")

                    

                    
                    
                    # --- Removed redundant and broken logic block ---




            except Exception as e:
                import traceback
                st.error(f"An error occurred: {e}")
                st.exception(e)
                logger.error(f"Analysis Failed: {traceback.format_exc()}")

# Tab 2 placeholder logic
if nav == "🔍 Race Scanner (Batch)":
    st.header("✨ Race Scanner（バッチ分析・パターン絞り込み）")

    # ---- Mode selector ----
    scan_mode = st.radio(
        "入力方法を選択",
        ["✨ 日付指定で自動取得", "✨ IDを直接入力"],
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
        selected_options = st.multiselect(
            "予測難易度フィルター（未選択＝全表示）",
            options=['D（超固い）', 'C（固い）', 'B（通常）', 'A（荒れ）', 'S（大荒れ）'],
            default=[],
            key="scanner_pattern_filter"
        )

    with col_input:
        if scan_mode == "✨ 日付指定で自動取得":
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
                st.success("🔗 URLからレースIDを自動抽出しました！", icon="🔗")
                st.session_state['scanner_extracted'] = False

    scan_btn = st.button("✨ スキャン開始", type="primary", key="scanner_btn")


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
                1: ("超固い",     "#FF4500", "#2D0000"),
                2: ("固い",       "#00C8FF", "#001A2D"),
                3: ("通常",       "#FFD700", "#1A1400"),
                4: ("荒れ",       "#7FFF00", "#0B1F00"),
                5: ("大荒れ",     "#FF4500", "#2D0000"),
            }

            results = []   # list of dicts

            for i, rid in enumerate(race_ids):
                status_text.text(f"スキャン中... {rid}  ({i+1}/{len(race_ids)})")
                try:
                    df_r = scraper.get_race_data(rid)
                    if df_r is None or df_r.empty:
                        raise ValueError("データなし")
                    # 単独分析と全く同じアルゴリズムに統合
                    prof_idx = 2
                    if len(rid) >= 6:
                        vc = rid[4:6]
                        if vc in ['04', '05', '07']: prof_idx = 0
                        elif vc in ['01', '02', '03', '06', '10']: prof_idx = 1
                    prof_text = ["✨ 直線が長い・差し有利 (東京/外回り 等)", "✨ 小回り・先行有利 (中山/小倉/札幌 等)", "✨ 標準 (バランス)"][prof_idx]

                    df_r = calculator.calculate_battle_score(df_r)
                    df_r = calculator.calculate_n_index(df_r)
                    df_r = calculator.calculate_strength_suitability(df_r, prof_text)

                    # Compute scores the exact same way as tab1
                    tmp = df_r.copy()
                    score_col = 'Projected Score' if 'Projected Score' in tmp.columns else 'BattleScore'
                    tmp['_score'] = pd.to_numeric(tmp[score_col], errors='coerce').fillna(0)
                    tmp = tmp.sort_values('_score', ascending=False).reset_index(drop=True)
                    scores_sorted = tmp['_score'].tolist()
                    pattern = _detect_pattern(scores_sorted)

                    difficulty_map = {1: 'D', 2: 'C', 3: 'B', 4: 'A', 5: 'S'}
                    diff_val = difficulty_map.get(pattern, 'Unknown')
                    tmp['Difficulty'] = diff_val

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
                        "difficulty": diff_val,
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
            display = []
            for r in results:
                if r['error']: continue
                df_scan = r.get('df')
                if df_scan is not None and not df_scan.empty:
                    if selected_options:
                        filter_diffs = [opt[0] for opt in selected_options]
                        df_filtered = df_scan[df_scan['Difficulty'].isin(filter_diffs)]
                        if df_filtered.empty:
                            continue
                        r['df'] = df_filtered
                    display.append(r)

            errors = [r for r in results if r['error']]
            if errors:
                with st.expander(f"✨ スキップされたレース {len(errors)}件", expanded=False):
                    for r in errors:
                        st.markdown(f"- `{r['id']}` : {r['error']}")

            st.markdown(f"### 💡 結果 {len(display)} 件 {'（フィルター適用中）' if selected_options else ''}")

            if not display:
                st.info("条件に合致するレースが見つかりませんでした。フィルターを変更してみてください。")
            else:
                for r in display:
                    p = r['pattern']
                    label, color, bg = PATTERN_LABELS.get(p, ("不明", "#888", "#111"))
                    badge = f'<span style="background:{bg};color:{color};border:1px solid {color};border-radius:6px;padding:3px 10px;font-size:0.85em;font-weight:bold;">{label}</span>'
                    race_name = r["title"] if r["title"] != r["id"] else "(レース名不明)"
                    diff_str = r.get("difficulty", "?")
                    header_html = (
                        f'<span style="font-size:1.15em;font-weight:bold;color:inherit;">{race_name}</span>'
                        f'&nbsp;&nbsp;{badge}&nbsp;[難易度: {diff_str}]&nbsp;'
                        f'<span style="color:#888;font-size:0.82em;">{r["id"]}</span>'
                    )
                    st.html(f'<div style="margin-top:18px;padding:10px 0 4px;border-top:1px solid #333;">{header_html}</div>')


                    with st.expander("🔍 詳細を見る", expanded=False):
                        if r['df'] is not None:
                            tmp_df = r['df']
                            # Show top 10 horses
                            cols_show = [c for c in ['Umaban', 'Name', 'Jockey', 'Difficulty', 'OguraIndex', 'SpeedIndex', '_score'] if c in tmp_df.columns]
                            display_df = tmp_df[cols_show].head(10).copy()
                            rename_map = {'Umaban': '馬番', 'Name': '馬名', 'Jockey': '騎手', 'Difficulty': '難易度', 'OguraIndex': 'OguraIdx', 'SpeedIndex': 'SpeedIdx', '_score': 'TotalScore'}
                            display_df.columns = [rename_map.get(c, c) for c in display_df.columns]
                            st.dataframe(display_df, use_container_width=True, hide_index=True)

                            # Link to Single Race
                            st.markdown(f"✨ [このレースをシングルタブで詳細分析する](/?race_id={r['id']})")
                        else:
                            st.error(f"データ取得エラー: {r['error']}")




# --- Tab 3: History & Review ---
# --- Tab 3: History & Review ---
if nav == "📊 History & Review":
    st.header("✨ Learning Fortress: History & Review")
    
    # 1. AI Guide (Updated for Learning Mode)
    with st.expander("✨ AIによる改善サイクルのやり方 (Learning Mode)", expanded=True):
        st.markdown("""
        **最強の予想ロジックを作るための「後出し学習」機能です。**
        
        1. **過去レース登録**: 下のフォームに、終わったレースのIDを入れて「確定させて保存」を押します。
        2. **自動採点**: 予測指数(Index)と、実際の着順(Result)が自動で保存されます。
        3. **AI分析依頼**: 保存された `race_history.csv` をGeminiに渡し、**「指数が高いのに負けた馬の共通点は？」** と聞いてください。
        4. **ロジック修正**: 「○○条件で弱い」と分かったら、 `calculator.py` の計算式を調整しましょう。
        """)

    import history_manager

    # --- Registration Area ---
    st.subheader("✨ Register Past Races (Learning)")
    reg_input = st.text_area("Past Race IDs (Finished Races)", height=100, placeholder="202608020211\n202608020212")
    
    col_reg1, col_reg2 = st.columns([1, 3])
    with col_reg1:
        if st.button("✨ 結果を確定させて保存", type="primary"):
            if reg_input:
                import re
                rids_raw = reg_input.replace(",", "\n").split("\n")
                rids = []
                for r_raw in rids_raw:
                    match = re.search(r'(\d{12})', r_raw)
                    if match:
                        rids.append(match.group(1))
                
                if not rids:
                    st.warning("有効な12桁のレースIDが含まれていません")
                else:
                    with st.spinner(f"Fetching results for {len(rids)} races..."):
                        logs = history_manager.register_past_races(rids)
                        
                    for log in logs:
                        if "?" in log:
                            st.success(log)
                        else:
                            st.error(log)
            else:
                st.warning("Please enter Race IDs.")
                
    with col_reg2:
        if st.button("✨ Update Existing Records (Re-fetch Results)"):
            status = history_manager.update_history_with_results()
            st.info(status)

    st.divider()

    # --- Display Section: View Full Analysis + Results ---
    st.subheader("🏁 レース解析＆結果表示 (Display)")
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
        st.success("🔗 URLからレースIDを自動抽出しました！", icon="🔗")
        st.session_state['history_extracted'] = False

    display_btn = st.button("✨ 解析＆結果を表示", type="primary", key="history_display_btn")
    auto_triggered = st.session_state.get('history_auto_run', False)
    
    if (display_btn or auto_triggered) and display_race_id:
        if auto_triggered:
            st.session_state.history_auto_run = False
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
                        st.info("🏁 レース結果はまだ取得できません（未確定）")
                    
                    # 4. Display - Race Info Header
                    race_title = disp_df['RaceName'].iloc[0] if 'RaceName' in disp_df.columns else f"Race {display_race_id}"
                    race_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={display_race_id}"
                    st.markdown(f"### 💡 {race_title}")
                    st.markdown(f"✨ **[Netkeiba レースページ]({race_url})**")
                    
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
                        "ActualRank": st.column_config.NumberColumn("✨ 着順"),
                        "BattleScore": st.column_config.NumberColumn("🔥 総合戦闘力", format="%.1f"),
                        "OguraIndex": st.column_config.NumberColumn("スピード指数", format="%.1f"),
                        "AvgAgari": st.column_config.TextColumn("上がり3F"),
                        "AvgPosition": st.column_config.TextColumn("平均位置"),
                        "ResultAgari": st.column_config.NumberColumn("✨ 結果上がり", format="%.1f"),
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
                                elif "💀" in val: colors.append("font-weight: bold; color: yellow")
                                elif "◎" in val: colors.append("font-weight: bold; color: red")
                                elif "⏱️" in val: colors.append("font-weight: bold; color: gray")
                                else: colors.append("")
                            return colors
                        
                        # Highlight entire row for ✨ and ??
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

                    # --- NEW: Predicted vs Actual Difficulty Display in Review ---
                    if race_results:
                        st.divider()
                        st.subheader("📊 難易度ダブルスコア検証")
                        c_diff1, c_diff2, c_diff3 = st.columns(3)
                        
                        pred_d = calculator.calculate_predicted_difficulty(df)
                        act_d = race_results.get('Actual_Diff', 'C')
                        
                        diff_labels = {"S": "大荒れ (S)", "A": "荒れ (A)", "B": "通常 (B)", "C": "堅い (C)"}
                        c_diff1.metric("予測難易度", diff_labels.get(pred_d, "?"))
                        c_diff2.metric("実際の難易度", diff_labels.get(act_d, "?"))
                        
                        match = (pred_d == act_d)
                        c_diff3.metric("判定一致", "一致" if match else "不一致", delta="OK" if match else "NG", delta_color="normal" if match else "inverse")
                    
                    # 6. Display - Result Summary (if available)
                    if race_results:
                        st.divider()
                        st.subheader("✨ 予測 vs 実績 サマリー")
                        
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
                                "ActualRank": "✨ 着順",
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
        # --- NEW: Correlation Analysis Section ---
        st.divider()
        st.subheader("📊 Correlation Analysis (High-Res Analysis)")
        st.caption("予測スコア内訳と実際の着順との相関関係を分析します。数値が高いほど（着順との相関なので負の相関が強いほど）的中への寄与度が高いことを示します。")
        
        if 'ActualRank' in df_history.columns:
            df_analysis = df_history.dropna(subset=['ActualRank']).copy()
            df_analysis['ActualRank'] = pd.to_numeric(df_analysis['ActualRank'], errors='coerce')
            
            score_cols = ['ScoreBaseOgura', 'ScoreTimeIndex', 'ScoreMakuri', 'ScoreTraining', 'ScoreWeight', 'ScoreBloodline', 'BattleScore']
            # Filter for columns that actually exist in the CSV
            score_cols = [c for c in score_cols if c in df_analysis.columns]
            
            if len(df_analysis) > 5 and score_cols:
                correlations = {}
                for col in score_cols:
                    # We want to see how each score correlates with ActualRank.
                    # Since rank 1 is "best", a LOWER rank usually correlates with HIGHER score.
                    # Thus, a negative correlation (e.g. -0.6) is "good" for the score logic.
                    # We'll display the absolute correlation or flip it for readability.
                    corr = df_analysis[col].corr(df_analysis['ActualRank'])
                    correlations[col] = corr
                
                # Display Metrics
                cols = st.columns(len(score_cols))
                for i, col in enumerate(score_cols):
                    corr_val = correlations.get(col, 0)
                    
                    if pd.isna(corr_val):
                         cols[i].metric(
                            label=col.replace("Score", ""),
                            value="---",
                            delta="データ不足"
                        )
                         continue
                         
                    strength = "なし"
                    if abs(corr_val) > 0.7: strength = "非常に強い"
                    elif abs(corr_val) > 0.4: strength = "強い"
                    elif abs(corr_val) > 0.2: strength = "相関あり"
                    
                    # Flip sign for user display: "Higher score -> better rank" = Positive Correlation in user mind
                    display_corr = -corr_val 
                    
                    cols[i].metric(
                        label=col.replace("Score", ""),
                        value=f"{display_corr:.2f}" if not pd.isna(display_corr) else "---",
                        delta=strength if not pd.isna(display_corr) else "データ不足",
                        delta_color="normal" if (not pd.isna(display_corr) and display_corr > 0) else "inverse"
                    )
                
                # --- NEW: Accuracy Stats for Difficulty ---
                if 'Predicted_Diff' in df_analysis.columns and 'Actual_Diff' in df_analysis.columns:
                    st.divider()
                    st.subheader("🎯 難易度予測 正答率分析")
                    valid_diff = df_analysis.dropna(subset=['Predicted_Diff', 'Actual_Diff'])
                    if not valid_diff.empty:
                        # Dedupe by RaceID for difficulty check
                        race_diffs = valid_diff.drop_duplicates(subset=['RaceID'])
                        total_races = len(race_diffs)
                        matched_races = len(race_diffs[race_diffs['Predicted_Diff'] == race_diffs['Actual_Diff']])
                        accuracy = matched_races / total_races if total_races > 0 else 0
                        
                        ma1, ma2 = st.columns(2)
                        ma1.metric("検証レース数", f"{total_races} レース")
                        ma2.metric("難易度的中率", f"{accuracy:.1%}", delta=f"{matched_races}/{total_races}")
                    else:
                        st.info("難易度の検証データがありません。")

                st.markdown("""
                > [!NOTE]
                > **相関係数の見方**: 1.0に近いほど「その指標が高い馬が上位に来ている」ことを示します。
                > 0に近い場合はノイズになっている可能性があります。
                """)
            else:
                st.info("相関分析には、着順データ（ActualRank）を含む5件以上のレコードが必要です。")
        
        # Display Improvements
        # 1. Date Filter (Restored)
        if 'Date' in df_history.columns:
            try:
                df_history['YearMonth'] = pd.to_datetime(df_history['Date'], errors='coerce').dt.strftime('%Y-%m')
            except:
                df_history['YearMonth'] = "Unknown"
            months = sorted(df_history['YearMonth'].dropna().unique(), reverse=True)
            if not months: months = ["All"]
            selected_month = st.selectbox("✨ Select Month Filter", ["All"] + list(months), key="history_month_filter")
            if selected_month != "All":
                df_display = df_history[df_history['YearMonth'] == selected_month].copy()
            else:
                df_display = df_history.copy()
        else:
            df_display = df_history.copy()

        # 2. Sorting
        if 'RaceNum' in df_display.columns:
            df_display['RaceNum'] = pd.to_numeric(df_display['RaceNum'], errors='coerce').fillna(0)
            df_display = df_display.sort_values(by=['Date', 'RaceNum'], ascending=[False, True])
        else:
            df_display = df_display.sort_values(by='Date', ascending=False)

        st.subheader("📁 Register/Load History List")
        
        # --- State Management for History Actions ---
        if 'race_action_confirm' not in st.session_state:
            st.session_state.race_action_confirm = None

        def execute_race_action():
            conf = st.session_state.race_action_confirm
            if not conf: return
            rid = conf["rid"]
            act = conf["action"]
            
            if act == "load":
                # Load: Set input and trigger analysis flag
                st.session_state.history_display_race_id = rid
                st.session_state.history_auto_run = True
                st.success(f"Race ID {rid} をセットしました。")
            elif act == "delete":
                # Delete: Remove from CSV
                df_h = history_manager.load_history()
                if not df_h.empty:
                    df_h = df_h[df_h['RaceID'].astype(str) != str(rid)]
                    df_h.to_csv("race_history.csv", index=False, encoding='utf-8')
                    st.success(f"Race ID {rid} の記録を削除しました。")
            
            st.session_state.race_action_confirm = None

        def cancel_race_action():
            st.session_state.race_action_confirm = None

        history_confirm = st.session_state.race_action_confirm
        if history_confirm:
            rid = history_confirm["rid"]
            act = history_confirm["action"]
            if act == "load":
                st.warning(f"Race ID: {rid} を表示用に読み込みますか？")
            else:
                st.error(f"Race ID: {rid} の履歴データを完全に削除しますか？")
            
            cy, cn = st.columns(2)
            with cy: st.button("✅ 実行", on_click=execute_race_action, use_container_width=True, key="race_conf_yes")
            with cn: st.button("❌ キャンセル", on_click=cancel_race_action, use_container_width=True, key="race_conf_no")
            st.write("")

        # Prepare unique race list
        df_display_unique = df_display.drop_duplicates(subset=['RaceID']).copy()
        race_list = df_display_unique[['RaceID', 'Date', 'RaceTitle', 'Venue']].to_dict('records')

        if not race_list:
            st.info("条件に一致する履歴はありません。")
        else:
            # Header
            rh1, rh2, rh3, rh4 = st.columns([5, 3, 1, 1])
            with rh1: st.caption("レース名 / ID")
            with rh2: st.caption("開催日 / 場所")
            st.divider()

            # Dynamic CSS for Race List Marker
            css_rules_h = ["<style>"]
            for i, r in enumerate(race_list):
                bg = "#ffffff" if i % 2 == 0 else "#f5f5f5"
                css_rules_h.append(f"""
                    div[data-testid="stHorizontalBlock"]:has(.race-row-{i}) {{
                        background-color: {bg} !important;
                        padding: 8px 12px;
                        border-radius: 4px;
                        align-items: center;
                    }}
                    div[data-testid="stHorizontalBlock"]:has(.race-row-{i}) * {{
                        color: #333333 !important;
                    }}
                    div[data-testid="stHorizontalBlock"]:has(.race-row-{i}) button {{
                        margin: 0;
                        padding: 4px 8px;
                    }}
                """)
            css_rules_h.append("</style>")
            st.markdown("\n".join(css_rules_h), unsafe_allow_html=True)

            for i, r in enumerate(race_list):
                rid = r['RaceID']
                title = r.get('RaceTitle') or f"Race {rid}"
                date = r.get('Date') or "---"
                venue = r.get('Venue') or ""
                
                c1, c2, c3, c4 = st.columns([5, 3, 1, 1])
                with c1:
                    st.markdown(f"<span class='race-row-{i}'>🏇 **{title}** <br> <small style='color:#666'>{rid}</small></span>", unsafe_allow_html=True)
                with c2:
                    st.markdown(f"📅 {date} <br> 📍 {venue}", unsafe_allow_html=True)
                with c3:
                    if st.button("📂", key=f"btn_hload_{rid}", help="読み込む", disabled=(history_confirm is not None)):
                        st.session_state.race_action_confirm = {"action": "load", "rid": rid}
                        st.rerun()
                with c4:
                    if st.button("🗑️", key=f"btn_hdel_{rid}", help="削除", disabled=(history_confirm is not None)):
                        st.session_state.race_action_confirm = {"action": "delete", "rid": rid}
                        st.rerun()

        st.divider()

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
                st.subheader("✨ Missed Candidates (Analysis Needed)")
                
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

# ──────────────────────────────────────────────
# 🧪 新ロジックテスト(FEW+マクリ) タブ
# ──────────────────────────────────────────────
if nav == "🧪 新ロジックテスト(FEW+マクリ)":
    st.header("🧪 新ロジックテスト (FEW+マクリ)")
    st.markdown("既存の予測スコアをベースに、「枠順バイアス」「馬体重仕上がり」「マクリ地力指数」を統合した検証用スコアリングです。")
    
    # --- Sync Race ID with Main Tab ---
    if 'main_race_id_input' not in st.session_state:
        st.session_state['main_race_id_input'] = ""
        
    def _on_test_race_id_change():
        import re
        val = st.session_state['test_race_id_input']
        match = re.search(r'race_id=(\d{12})', val)
        if not match: match = re.search(r'(\d{12})', val)
        if match:
            extracted = match.group(1)
            if extracted != val:
                st.session_state['test_race_id_input'] = extracted
        
        # Sync back to main tab
        st.session_state['main_race_id_input'] = st.session_state['test_race_id_input']
        st.session_state['tab1_analyzed_id'] = st.session_state['test_race_id_input']
        
        # Clear specific tab4 data to force re-fetch
        if 'test_adv_data' in st.session_state:
            del st.session_state['test_adv_data']

    # Read from main tab's state by default
    current_input_id = st.session_state.get('tab1_analyzed_id', st.session_state.get('main_race_id_input', ''))
    
    col_t1, col_t2 = st.columns([1, 2])
    with col_t1:
        test_race_id = st.text_input("Race ID (同期済み)", value=current_input_id, key="test_race_id_input", on_change=_on_test_race_id_change)
    with col_t2:
        test_analyze_btn = st.button("🚀 データを読み込む (Analyze)", type="primary")

    if test_analyze_btn and test_race_id:
        st.session_state['main_race_id_input'] = test_race_id
        st.session_state['tab1_analyzed_id'] = test_race_id
        with st.spinner("Fetching base data..."):
            try:
                new_df = scraper.get_race_data(test_race_id)
                if new_df is not None and not new_df.empty:
                    new_df = calculator.calculate_battle_score(new_df)
                    new_df = calculator.calculate_n_index(new_df)
                    st.session_state['df'] = new_df
                else:
                    st.error("データが取得できませんでした。")
            except Exception as e:
                st.error(f"Error: {e}")

    df = st.session_state.get('df')
    
    # Consistency check: Ensure the loaded data matches the current input ID
    is_consistent = False
    if df is not None and not df.empty:
        loaded_id = str(df['RaceID'].iloc[0]) if 'RaceID' in df.columns else ""
        if loaded_id == test_race_id:
            is_consistent = True
            
    if is_consistent:
        df_test = df.copy()
        score_col = 'Projected Score' if 'Projected Score' in df_test.columns else 'BattleScore'
        df_test = df_test.sort_values(by=score_col, ascending=False).reset_index(drop=True)

        # 0. Session Status
        import os
        from datetime import datetime
        session_path = "auth_session.json"
        
        with st.expander("🔑 認証・セッション管理 (Umanity)", expanded=not os.path.exists(session_path)):
            if os.path.exists(session_path):
                mtime = os.path.getmtime(session_path)
                dt_mtime = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                st.success(f"✅ セッション保存済み (更新日時: {dt_mtime})")
            else:
                st.warning("⚠️ セッション情報が見つかりません。ウマニティの数値（U指数）を取得するにはログインが必要です。")
            
            if st.button("🔑 ウマニティにログインしてセッションを保存", key="btn_create_session"):
                # Use powershell in a new window to handle encoding and interaction
                cmd = f'start powershell -NoExit -Command "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; py create_session.py"'
                os.system(cmd)
                st.info("別ウィンドウでログイン用ブラウザが起動しました。ログイン完了後、そのウィンドウでEnterキーを押してください。")
        
        # 1. Influence Weights Initialization (Updated defaults for Robustness)
        if 'score_weights' not in st.session_state:
            st.session_state['score_weights'] = {
                "Base": 0.0,
                "Popularity": 0.0,
                "DIY1": 0.0, 
                "DIY2": 0.0, 
                "UIndex": 0.0, 
                "Jockey": 0.0, 
                "Training": 0.0,
                "Weight": 0.0, 
                "LaboIndex": 0.0, # Omega Index
                "Bloodline": 0.0
            }
        
        sw = st.session_state['score_weights']
        # Safety check for new keys
        for k in ["Weight", "LaboIndex", "Bloodline", "Training"]:
            if k not in sw: sw[k] = 0.0
        
        # UI Styling to align with table headers
        st.markdown("""
            <style>
            .weight-header {
                font-size: 0.75rem;
                color: #aaa;
                margin-top: -5px;
                text-align: center;
                line-height: 1.0;
            }
            .stNumberInput {
                margin-bottom: -15px !important;
            }
            </style>
        """, unsafe_allow_html=True)

        st.write("### 📊 影響率（ウェイト）設定")
        # Column distribution matching the result table:
        # 馬番(1), 馬名(2), 特徴(1), 人気(1), 馬体重(1.5), 調教(1.2), U指(1.2), オメガ(1), 血統(1), 元順(1), 元スコ(1.2), DIY2(1.2), DIY1(1.2), Test(1.5), 備考(3)
        # We need to map 10 inputs across these.
        cols = st.columns([1, 2, 1, 1.5, 1.2, 1.2, 1, 1, 1, 1.2, 1.2, 1.2, 1.5, 3]) 
        
        with cols[0]: st.empty() # 馬番
        with cols[1]: 
            sw["Jockey"] = st.number_input("% (騎手)", value=sw["Jockey"], min_value=0.0, max_value=100.0, step=1.0, key="w_jockey", label_visibility="collapsed")
            st.markdown('<div class="weight-header">騎手 %</div>', unsafe_allow_html=True)
        with cols[2]: 
            sw["Popularity"] = st.number_input("% (人気)", value=sw["Popularity"], min_value=0.0, max_value=100.0, step=1.0, key="w_pop", label_visibility="collapsed")
            st.markdown('<div class="weight-header">人気 %</div>', unsafe_allow_html=True)
        with cols[3]: 
            sw["Weight"] = st.number_input("% (馬体)", value=sw["Weight"], min_value=0.0, max_value=100.0, step=1.0, key="w_weight", label_visibility="collapsed")
            st.markdown('<div class="weight-header">馬体 %</div>', unsafe_allow_html=True)
        with cols[4]: 
            sw["Training"] = st.number_input("% (調教)", value=sw["Training"], min_value=0.0, max_value=100.0, step=1.0, key="w_train", label_visibility="collapsed")
            st.markdown('<div class="weight-header">調教 %</div>', unsafe_allow_html=True)
        with cols[5]: 
            sw["UIndex"] = st.number_input("% (U指)", value=sw["UIndex"], min_value=0.0, max_value=100.0, step=1.0, key="w_uindex", label_visibility="collapsed")
            st.markdown('<div class="weight-header">U指 %</div>', unsafe_allow_html=True)
        with cols[6]: 
            sw["LaboIndex"] = st.number_input("% (オメガ)", value=sw["LaboIndex"], min_value=0.0, max_value=100.0, step=1.0, key="w_labo", label_visibility="collapsed")
            st.markdown('<div class="weight-header">オメガ %</div>', unsafe_allow_html=True)
        with cols[7]: 
            sw["Bloodline"] = st.number_input("% (血統)", value=sw["Bloodline"], min_value=0.0, max_value=100.0, step=1.0, key="w_blood", label_visibility="collapsed")
            st.markdown('<div class="weight-header">血統 %</div>', unsafe_allow_html=True)
        with cols[8]: st.empty() # 元順
        with cols[9]: 
            sw["Base"] = st.number_input("% (基本)", value=sw.get("Base", 0.0), min_value=0.0, max_value=100.0, step=1.0, key="w_base", label_visibility="collapsed")
            st.markdown('<div class="weight-header">基本 %</div>', unsafe_allow_html=True)
        with cols[10]:
            sw["DIY2"] = st.number_input("% (末脚)", value=sw["DIY2"], min_value=0.0, max_value=100.0, step=1.0, key="w_diy2", label_visibility="collapsed")
            st.markdown('<div class="weight-header">末脚 %</div>', unsafe_allow_html=True)
        with cols[11]:
            sw["DIY1"] = st.number_input("% (DIY1)", value=sw["DIY1"], min_value=0.0, max_value=100.0, step=1.0, key="w_diy1", label_visibility="collapsed")
            st.markdown('<div class="weight-header">DIY1 %</div>', unsafe_allow_html=True)
        
        # Add a summary row for total
        total_w = sum(sw.values())
        if abs(total_w - 100.0) > 0.01 and total_w > 0:
            st.info(f"💡 合計が {total_w:.1f}% です（100%基準で自動正規化して計算中）")
        elif total_w == 0:
            st.warning("⚠️ 全てのウェイトが 0% です。各項目の生値の合計が表示されます。")
        
        # Update session state
        st.session_state['score_weights'] = sw
        
        # Normalization helper
        norm_w = {k: v / (total_w if total_w > 0 else 1.0) for k, v in sw.items()}
        
        # (Radio buttons removed for automation)
        
        # 2. Base Ranking (to calculate Diff later)
        df_test['BaseRank'] = df_test[score_col].rank(ascending=False, method='min')
        
        # 3. Playwright Action Button (Full Automation)
        if st.button("🚀 Playwrightで全てのデータ取得・計算を一括実行", key="btn_pw_test", type="primary"):
            race_id = st.session_state.get('tab1_analyzed_id', st.session_state.get('main_race_id_input', ''))
            with st.status("📊 統合データ処理中...", expanded=True) as status:
                st.write("1. Playwrightブラウザ起動... [馬体重/調教/血統/U指数/オメガ] をスキャンしています")
                top10_umaban = df_test.head(10)['Umaban'].tolist()
                adv_data = scraper.fetch_advanced_data_playwright(race_id, top_horse_ids=top10_umaban)
                st.session_state['test_adv_data'] = adv_data
                
                st.write("2. 独自指数 (DIY1/DIY2) を計算中...")
                # Calculate on the ORIGINAL dataframe to ensure persistence
                df_main = st.session_state.get('df')
                if df_main is not None:
                    df_main = calculator.calculate_diy_index(df_main)
                    df_main = calculator.calculate_diy2_index(df_main)
                    st.session_state['df'] = df_main
                
                status.update(label="✅ 全データの取得と計算が完了しました！", state="complete", expanded=False)
                st.rerun()

        # 4. Calculation and Table Display
        adv_data = st.session_state.get('test_adv_data', {})
        
        # Ensure indices exist in columns and recalculate if missing but data exists
        if 'DIY_Index' not in df_test.columns or df_test['DIY_Index'].sum() == 0:
             if adv_data: # If we have advanced data, assume we should have indices
                 df_test = calculator.calculate_diy_index(df_test)
                 st.session_state['df'] = df_test
        
        if 'DIY2_Index' not in df_test.columns or df_test['DIY2_Index'].sum() == 0:
             if adv_data:
                 df_test = calculator.calculate_diy2_index(df_test)
                 st.session_state['df'] = df_test

        if 'DIY_Index' not in df_test.columns: df_test['DIY_Index'] = 0.0
        if 'DIY2_Index' not in df_test.columns: df_test['DIY2_Index'] = 0.0
            
        # 5. Jockey Bonus Data & Logic
        JOCKEY_BONUS_MAP = {
            # Tier 1 (+5.0): Win Rate > 15%
            "ルメール": 5.0, "川田": 5.0, "モレイラ": 5.0, "レーン": 5.0, "デムーロ": 5.0, "戸崎": 5.0, "坂井": 5.0, "松山": 5.0,
            # Tier 2 (+3.0): Win Rate 10-15%
            "横山武": 3.0, "岩田望": 3.0, "キング": 3.0, "藤岡佑": 3.0, "横山和": 3.0, "横山典": 3.0, "武豊": 3.0, "北村友": 3.0, "西村": 3.0,
            # Tier 3 (+1.0): Win Rate 5-10%
            "荻野極": 1.0, "浜中": 1.0, "丹内": 1.0, "団野": 1.0, "三浦": 1.0, "佐々木": 1.0, "池添": 1.0, "高杉": 1.0, "菅原明": 1.0, "岩田康": 1.0, "鮫島克": 1.0, "田辺": 1.0, "小林美": 1.0, "津村": 1.0, "吉村": 1.0
        }

        def get_jockey_bonus(j_name):
            for key, val in JOCKEY_BONUS_MAP.items():
                if key in j_name:
                    return val
            return 0.0

        test_scores = []
        total_horses = len(df_test)
        import re
        
        for idx, row in df_test.iterrows():
            base_score = float(row.get(score_col, 0.0))
            score_diff = 0.0
            remarks = []
            horse_name = str(row.get('Name', ''))
            umaban = int(row.get('Umaban', 0))
            
            # Fetch data from advanced playwright scrape
            pw_data = adv_data.get(umaban, {})
            weight_str = pw_data.get('WeightStr', str(row.get('Weight', '')))
            training_eval = pw_data.get('TrainingEval', '')
            training_score = pw_data.get('TrainingScore', 0.0)
            blood_flag = pw_data.get('BloodlineFlag', '')
            
            # A. 枠順バイアス (Frame bias)
            if total_horses > 0 and umaban > 0:
                inner_threshold = total_horses * 0.3
                outer_threshold = total_horses * 0.7
                if umaban <= inner_threshold:
                    score_diff += 3.0
                    remarks.append("内枠(+3.0)")
                elif umaban > outer_threshold:
                    score_diff -= 2.0
                    remarks.append("大外枠(-2.0)")
            
            # B. 馬体重仕上がり (Weight Condition)
            match = re.search(r'\(([-+]\d+)\)', weight_str)
            if match:
                weight_diff = abs(int(match.group(1)))
                if weight_diff <= 2:
                    score_diff += 5.0
                    remarks.append("究極仕上(+5.0)")
                elif weight_diff >= 10:
                    score_diff -= 3.0
                    remarks.append("馬体増減(-3.0)")
                    
            # B-2. 調教評価 (Training)
            # B-2. 調教評価 (Training - Weighted Core Item, no longer additive here)
            # We keep the remarks but move the score impact to weightedCore
            if training_score > 0:
                remarks.append(f"調教{training_eval}(+{training_score})")
            elif training_score < 0:
                remarks.append(f"調教{training_eval}({training_score})")
                
            # B-3. 血統フラグ (Bloodline)
            if blood_flag:
                remarks.append(f"血統({blood_flag})")
                horse_name = f"🧬 {horse_name}"
            
            # C. マクリ地力指数 (Makuri & Positional Delta)
            makuri_bonus = 0.0
            past_runs = row.get('PastRuns', [])
            if isinstance(past_runs, list) and len(past_runs) > 0:
                past1 = past_runs[0]
                past_pos = str(past1.get('Passing', ''))
                past_res = str(past1.get('Rank', ''))
                past_agari_rank = str(past1.get('AgariRank', '99'))
                
                parsed_positions = [int(t) for t in re.split(r'[,\-()]+', past_pos) if t.strip().isdigit()]
                if parsed_positions and past_res.isdigit():
                    max_pos = max(parsed_positions)
                    final_rank = int(past_res)
                    delta = max_pos - final_rank
                    
                    if delta >= 7:
                        makuri_bonus += 5.0
                        remarks.append("マクリ(+5.0)")
                        if past_agari_rank.isdigit() and int(past_agari_rank) <= 3:
                            makuri_bonus += 2.0
                            remarks.append("上がり特典(+2.0)")
                        horse_name = f"💪 {horse_name}"
            
            score_diff += makuri_bonus
            
            # C-2. 騎手ボーナス (Jockey - Weighted Core Item, no longer additive here)
            j_name = str(row.get('Jockey', ''))
            j_bonus = get_jockey_bonus(j_name)
            if j_bonus > 0:
                remarks.append(f"騎手({j_name}:{j_bonus:+})")
            
            # D. 追加指数 (Extra Indices - Automated Weighted Sum WITH DYNAMIC WEIGHTS)
            diy1_val = float(row.get('DIY_Index', 0.0))
            diy2_val = float(row.get('DIY2_Index', 0.0))
            u_val = pw_data.get('UIndex', 0.0)
            l_val = pw_data.get('LaboIndex', 0.0)
            b_flag = pw_data.get('BloodlineFlag', '')
            
            # 1. Popularity Score
            pop_score = 100.0 - (int(row.get('Popularity', 20)) - 1) * 5.0
            pop_score = max(0, pop_score)
            
            # 2. Weight Condition Score
            w_score = 50.0 # Standard
            if "究極仕上" in str(remarks): w_score = 100.0
            elif "馬体増減" in str(remarks): w_score = 25.0
            
            # 3. Bloodline Score
            blood_score = 100.0 if b_flag else 0.0
            
            # Dynamic Weight Redistribution (Robust Scoring)
            # Identify active factors (non-zero raw value) for THIS horse
            factor_map = {
                "Base": base_score, "DIY1": diy1_val, "DIY2": diy2_val, 
                "UIndex": u_val, "Jockey": j_bonus, "Popularity": pop_score,
                "Training": training_score, "Weight": w_score, 
                "LaboIndex": l_val, "Bloodline": blood_score
            }
            
            non_zero_factors = {k: v for k, v in factor_map.items() if v != 0.0}
            total_active_weight = sum([sw.get(k, 0.0) for k in non_zero_factors.keys()])
            
            if total_active_weight > 0:
                # Redistribute weight proportionally
                weighted_score = 0.0
                for k, val in non_zero_factors.items():
                    # adjusted_w = original_w / sum(active_ws)
                    adj_w = sw.get(k, 0.0) / total_active_weight
                    weighted_score += val * adj_w
            else:
                # Fallback if no active weights or all values are zero
                weighted_score = sum(factor_map.values()) / len(factor_map) if any(factor_map.values()) else 0.0
            
            if diy1_val > 0 and sw.get("DIY1", 0) > 0: remarks.append(f"DIY1({diy1_val})")
            if diy2_val > 0 and sw.get("DIY2", 0) > 0: remarks.append(f"末脚({diy2_val})")
            if u_val > 0 and sw.get("UIndex", 0) > 0: remarks.append(f"U指({u_val})")
            if pop_score > 0 and sw.get("Popularity", 0) > 0: remarks.append(f"人({int(row.get('Popularity'))})")
            if training_score != 0 and sw.get("Training", 0) > 0: remarks.append(f"調({training_score})")
            if j_bonus > 0 and sw.get("Jockey", 0) > 0: remarks.append(f"騎({j_bonus})")
            if l_val > 0 and sw.get("LaboIndex", 0) > 0: remarks.append(f"オメガ({l_val})")
            if blood_score > 0 and sw.get("Bloodline", 0) > 0: remarks.append("血(有)")
            
            # Final Test Score = Weighted Core + Raw Diff (Only remaining minor additive bonuses)
            final_test_score = weighted_score + score_diff
            
            test_scores.append({
                "馬番": umaban,
                "馬名(ラベル付)": horse_name,
                "人気": int(row.get('Popularity')) if pd.notnull(row.get('Popularity')) else "-",
                "馬体重": weight_str,
                "調教": training_eval if training_eval else "-",
                "U指数": round(float(pw_data.get('UIndex')), 1) if pw_data.get('UIndex') and str(pw_data.get('UIndex')).replace('.','',1).strip().replace('-','',1).replace('e','',1).replace('E','',1).replace('+','',1).split('.')[0].isdigit() else pw_data.get('UIndex', "-"),
                "オメガ指数": round(float(pw_data.get('LaboIndex')), 1) if pw_data.get('LaboIndex') and str(pw_data.get('LaboIndex')).replace('.','',1).strip().replace('-','',1).replace('e','',1).replace('E','',1).replace('+','',1).split('.')[0].isdigit() else pw_data.get('LaboIndex', "-"),
                "血統": blood_flag if blood_flag else "-",
                "元の順位": int(row.get('BaseRank', 99)),
                "元のスコア": round(base_score, 1),
                "DIY2": round(float(row.get('DIY2_Index', 0.0)), 1),
                "DIY指数": round(float(row.get('DIY_Index', 0.0)), 1),
                "Test_Score": round(final_test_score, 1),
                "加点内訳(備考)": ", ".join(remarks) if remarks else "-"
            })
            
        df_test_res = pd.DataFrame(test_scores)
        # Calculate New Rank and Diff
        df_test_res['新順位'] = df_test_res['Test_Score'].rank(ascending=False, method='min').astype(int)
        df_test_res['Diff'] = df_test_res['元の順位'] - df_test_res['新順位']
        
        # Re-sort by New Score
        df_test_res = df_test_res.sort_values(by="Test_Score", ascending=False).reset_index(drop=True)
        
        def highlight_flags(r):
            bg = ''
            if '究極仕上' in r['加点内訳(備考)']: bg = 'background-color: #004d00;' # Darker Green
            elif '馬体増減' in r['加点内訳(備考)']: bg = 'background-color: #4d0000;' # Darker Red
            elif '調教A' in r['加点内訳(備考)']: bg = 'background-color: #4d3d00;' # Darker Gold
            
            text_col = 'color: #ffffff;' if bg else ''
            return [bg + text_col for _ in r]

        # Format Diff column with arrows
        def format_diff(val):
            if val > 0: return f"↑+{val}"
            elif val < 0: return f"↓{val}"
            return "-"

        df_test_res['Diff'] = df_test_res['Diff'].apply(format_diff)
        
        st.dataframe(
            df_test_res.style.apply(highlight_flags, axis=1), 
            use_container_width=True,
            column_config={
                "元の順位": st.column_config.NumberColumn("元の順位", help="ベーススコアでの順位"),
                "元のスコア": st.column_config.NumberColumn("元のスコア", format="%.1f"),
                "DIY2": st.column_config.NumberColumn("DIY2(末脚)", format="%.1f"),
                "DIY指数": st.column_config.NumberColumn("DIY指数", format="%.1f"),
                "Test_Score": st.column_config.NumberColumn("Test_Score (現在の合算)", format="%.1f"),
                "U指数": st.column_config.NumberColumn("U指数", format="%.1f"),
                "オメガ指数": st.column_config.NumberColumn("オメガ指数", format="%.1f"),
                "Diff": st.column_config.TextColumn("順位変動(Diff)", help="元の順位からのアップダウン"),
                "新順位": st.column_config.NumberColumn("現在の順位"),
            }
        )
        
        st.divider()
        if st.button("💾 解析結果を保存 (Save Results)", type="primary"):
            try:
                import json
                save_dir = os.path.join(os.getcwd(), "data", "history")
                os.makedirs(save_dir, exist_ok=True)
                
                # Fetch current race ID
                current_id = st.session_state.get('tab1_analyzed_id', st.session_state.get('main_race_id_input', 'unknown_race'))
                file_path = os.path.join(save_dir, f"{current_id}.json")
                
                # Convert DataFrame to dictionary
                res_dict = df_test_res.to_dict(orient='records')
                save_data = {
                    "RaceID": current_id,
                    "SavedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Results": res_dict
                }
                
                # Save as JSON with UTF-8 encoding
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(save_data, f, ensure_ascii=False, indent=2)
                    
                st.success(f"✅ 解析結果を保存しました！\n📂 保存先: `{file_path}`")
            except Exception as e:
                import traceback
                st.error(f"保存エラー: {e}")
                logger.error(f"Save Error: {traceback.format_exc()}")
            
    else:
        st.warning(f"⚠️ データが現在のレースID（{current_input_id}）と一致しないか、未解析です。")
        st.info("「Single Race Analysis」タブに戻り、**🚀 Analyze Race** ボタンを押して最新のデータを取得してください。")

# ──────────────────────────────────────────────
# 📚 【新理論】RMHS分析 タブ
# ──────────────────────────────────────────────
if nav == "📚 RMHS分析":
    st.header("📚 【新理論】R/M/H/S 分析")
    st.markdown("レース結果データから、R（リバウンド）、M（マクリ）、H（ハイペース耐性）、S（スロー末脚）の4理論に該当する馬を抽出します。")
    
    col1, col2, col3 = st.columns([2, 5, 2])
    with col1:
        target_id_input = st.text_input("分析対象 RaceID (12桁)", value=st.session_state.get('main_race_id_input', ''), key="rmhs_id_input")
    with col2:
        theory_filter = st.radio(
            "理論フィルタ", 
            ["すべて", "R理論 (Rebound)", "M理論 (Move)", "H理論 (High-pace Hang)", "S理論 (Slow-pace Surge)"], 
            horizontal=True
        )
    with col3:
        st.write("") # Spacer
        analyze_btn = st.button("🔍 RMHS分析を実行", use_container_width=True, key="rmhs_analyze_btn")
        
    if analyze_btn and target_id_input:
        with st.spinner("詳細結果データを取得中..."):
            comp = fetch_comprehensive_result(target_id_input)
            
        if not comp or not comp.get('horses'):
            st.error("レース結果が取得できませんでした。未開催かRaceIDが間違っている可能性があります。")
        else:
            # Prepare RMHS Input
            race_info = comp['race_info']
            # Pace Classification
            p_first = race_info.get('first_half', 0.0)
            p_second = race_info.get('second_half', 0.0)
            pace_class, pace_diff = theory_rmhs.RMHSAnalyzer.calculate_pace(p_first, p_second)
            race_info['pace_class'] = pace_class
            race_info['pace_diff'] = pace_diff
            
            # Leaders and Closers for H/S logic
            field_size = race_info.get('field_size', 0)
            front_finish = []
            for u, h in comp['horses'].items():
                p_list = theory_rmhs.RMHSAnalyzer.parse_passing(h['Passing'] or "")
                last_p = p_list[-1] if p_list else 99
                if last_p <= 4:
                    front_finish.append(h['Rank'])
            
            race_info['front_finish'] = front_finish
            
            # Agari Rank
            all_agari = sorted([h['Agari'] for h in comp['horses'].values() if h['Agari'] > 0])
            def get_agari_rank(val):
                if val <= 0: return 99
                try: return all_agari.index(val) + 1
                except: return 99
            
            # Analyze each horse
            theory_results = []
            for u, h in comp['horses'].items():
                p_list = theory_rmhs.RMHSAnalyzer.parse_passing(h['Passing'] or "")
                h_input = {
                    'umaban': u,
                    'finish_position': h['Rank'],
                    'time': h['Time'],
                    'pos_1c': p_list[0] if len(p_list) > 0 else None,
                    'pos_2c': p_list[1] if len(p_list) > 1 else None,
                    'pos_3c': p_list[2] if len(p_list) > 2 else None,
                    'pos_4c': p_list[-1] if p_list else None,
                    'last3f_rank': get_agari_rank(h['Agari'])
                }
                res = theory_rmhs.RMHSAnalyzer.analyze_horse(h_input, race_info)
                
                # Format for display
                theory_str = []
                if res['R']['flag'] is True: theory_str.append(f"🔴R({res['R']['score']})")
                if res['M']['flag'] is True: theory_str.append(f"🔵M({res['M']['score']})")
                if res['H']['flag'] is True: theory_str.append(f"🟢H({res['H']['score']})")
                if res['S']['flag'] is True: theory_str.append(f"🟡S({res['S']['score']})")
                
                theory_results.append({
                    '馬番': u,
                    '馬名': h.get('Name', 'Unknown'),
                    '着順': h['Rank'],
                    '通過順位': h['Passing'],
                    '上がり3F': h['Agari'],
                    '単勝オッズ': h.get('ResultOdds', 0.0),
                    '人気': h.get('Popularity', 99),
                    'RMHS判定': " ".join(theory_str) if theory_str else "-"
                })
                
            df_rmhs = pd.DataFrame(theory_results).sort_values('着順')
            
            # Apply Filter
            if theory_filter == "R理論 (Rebound)":
                df_rmhs = df_rmhs[df_rmhs['RMHS判定'].str.contains('R', na=False)]
            elif theory_filter == "M理論 (Move)":
                df_rmhs = df_rmhs[df_rmhs['RMHS判定'].str.contains('M', na=False)]
            elif theory_filter == "H理論 (High-pace Hang)":
                df_rmhs = df_rmhs[df_rmhs['RMHS判定'].str.contains('H', na=False)]
            elif theory_filter == "S理論 (Slow-pace Surge)":
                df_rmhs = df_rmhs[df_rmhs['RMHS判定'].str.contains('S', na=False)]
            
            st.subheader(f"📊 RMHS分析結果 (Pace: {pace_class} {pace_diff:+.1f}s) - {theory_filter}")
            
            def highlight_theory(s):
                return ['background-color: rgba(255, 243, 205, 0.3)' if val != "-" else '' for val in s]

            st.dataframe(df_rmhs.style.apply(highlight_theory, subset=['RMHS判定']), use_container_width=True)
            
            with st.expander("📖 理論の解説"):
                st.markdown("""
                - **R理論 (Rebound)**: 道中で不利や置かれ気味で順位を落とすが、直線で猛然と巻き返した馬。次走注目。
                - **M理論 (Move)**: 向正面～3角で一気に進出。脚を使い切って最後甘くなったが、見せ場十分の馬。
                - **H理論 (High-pace Hang)**: ハイペースの中、前線で踏ん張り先行勢の中で最先着。展開不向きの中での好走。
                - **S理論 (Slow-pace Surge)**: スローペースで展開が向かない後方から、上がり最速級で追い込み。差し届かずの負けに価値あり。
                """)


# ──────────────────────────────────────────────
# ──────────────────────────────────────────────
# 🏇 過去走R理論スキャン タブ
# ──────────────────────────────────────────────
if nav == "🏇 過去走R理論スキャン":
    st.header("🏇 指定場 過去走R理論スキャン")
    st.markdown("指定した日付の**全競馬場（全レース）**または特定の競馬場を対象に、全出走馬の**過去5走**を自動スキャンし、R理論（Rebound）に合致する「次走注目馬」を抽出します。")
    st.warning("⚠️ **注意**: アクセス制限(BAN)対策として1レースごとに2秒の待機時間を設けています。全場スキャン（約36レース）には約2分、1場のスキャン（12レース）には約40秒かかります。")
    
    col_d1, col_d2 = st.columns([3, 1])
    with col_d1:
        default_date = datetime.now().strftime("%Y%m%d")
        scan_date_input = st.text_input("スキャン対象日付 (YYYYMMDD形式)", value=default_date, key="r_scan_date_input")
    with col_d2:
        st.write("") # Spacer
        fetch_venues_btn = st.button("📅 開催場一覧を取得", use_container_width=True)
        
    if fetch_venues_btn and scan_date_input:
        st.session_state.r_scan_race_list = scraper.get_race_list_for_date(scan_date_input)
        
    if 'r_scan_race_list' in st.session_state and st.session_state.r_scan_race_list:
        race_list = st.session_state.r_scan_race_list
        if not race_list:
            st.error("指定された日付のレース情報が見つかりませんでした。")
        else:
            # Group by venue code (characters 4-6 of race_id)
            venues = {}
            for r in race_list:
                # e.g., 202406050811 -> '06'
                v_code = r['race_id'][4:6] if len(r['race_id']) == 12 else "Unknown"
                if v_code not in venues:
                    venues[v_code] = []
                venues[v_code].append(r)
            
            VENUE_NAMES = {
                "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
                "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
                "36": "大井", "42": "船橋", "43": "川崎", "44": "浦和", "65": "園田", 
                "62": "名古屋", "54": "門別", "50": "帯広", "45": "盛岡", "46": "水沢"
            }
            
            v_options = list(venues.keys())
            def format_venue(code):
                name = VENUE_NAMES.get(code, f"コード {code}")
                count = len(venues.get(code, []))
                return f"{name} ({count}レース)"
            
            st.markdown("---")
            col_v1, col_v2, col_v3 = st.columns([2, 1, 1])
            with col_v1:
                selected_v_code = st.selectbox("特定の競馬場を選択（個別スキャン用）", v_options, format_func=format_venue)
            with col_v2:
                st.write("")
                run_all_scan_btn = st.button("🌍 全開催場をスキャン", use_container_width=True, type="primary")
            with col_v3:
                st.write("")
                run_single_scan_btn = st.button("🚀 選択した場のみスキャン", use_container_width=True)
            
            # Helper to run scan logic
            def perform_scan(target_races, label):
                total_races = len(target_races)
                st.success(f"✅ {label} の {total_races} レースをスキャン開始します...")
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                extracted_horses = []
                
                for i, race_info in enumerate(target_races):
                    r_id = race_info['race_id']
                    r_name = race_info['race_name']
                    r_num = race_info['race_num']
                    
                    v_code = r_id[4:6] if len(r_id) == 12 else "Unknown"
                    v_name = VENUE_NAMES.get(v_code, v_code)
                    
                    status_text.text(f"⏳ スキャン中... ({i+1}/{total_races}): {v_name} {r_num} {r_name}")
                    
                    df_race = scraper.get_race_data(r_id)
                    if not df_race.empty:
                        for index, row in df_race.iterrows():
                            past_runs = row.get('PastRuns', [])
                            for p_idx, run in enumerate(past_runs[:5]):
                                if theory_rmhs.RMHSAnalyzer.analyze_past_run_for_r(run):
                                    extracted_horses.append({
                                        '競馬場・R': f"{v_name} {r_num}",
                                        '馬番': row['Umaban'],
                                        '馬名': row['Name'],
                                        '予想オッズ': row.get('Odds', 0.0),
                                        '合致した過去走': run.get('Date', 'Unknown'),
                                        '過去走成績': f"{run.get('Rank')}着 (通過:{run.get('Passing')} 上がり:{run.get('Agari')} 差:{run.get('Margin')})"
                                    })
                                    break
                    
                    progress_bar.progress((i + 1) / total_races)
                    if i < total_races - 1:
                        time.sleep(2.0)
                
                status_text.text(f"✅ スキャン完了！ {label} のチェックが終わりました。")
                progress_bar.empty()
                return extracted_horses

            results = []
            if run_all_scan_btn:
                all_races = [r for venue_races in venues.values() for r in venue_races]
                results = perform_scan(all_races, "全開催場")
            elif run_single_scan_btn and selected_v_code:
                results = perform_scan(venues[selected_v_code], VENUE_NAMES.get(selected_v_code, selected_v_code))
            
            if results:
                st.subheader(f"🎯 R理論（Rebound） 次走注目馬 ({len(results)}頭)")
                df_extracted = pd.DataFrame(results)
                st.dataframe(df_extracted, use_container_width=True)
            elif run_all_scan_btn or run_single_scan_btn:
                st.info("該当する馬は見つかりませんでした。")

# ──────────────────────────────────────────────
# 💾 ロジック置き場
# ──────────────────────────────────────────────
if nav == "💾 ロジック置き場":
    st.header("💾 ロジック置き場")
    st.caption("AI(antigravity)への指示や各種設定メモを一か所に保存・参照するためのスペースです。")
    
    import json
    LOGIC_FILE = "saved_logic_notes.json"
    
    def load_logics():
        if os.path.exists(LOGIC_FILE):
            try:
                with open(LOGIC_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_logics(data):
        with open(LOGIC_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    logics = load_logics()
    
    # 日付が新しい順にソート（最新のものから表示）
    sorted_keys = sorted(logics.keys(), key=lambda k: logics[k].get("date", ""), reverse=True)
    
    # Session state for inputs
    if 'logic_name_input' not in st.session_state:
        st.session_state.logic_name_input = ""
    if 'logic_memo_input' not in st.session_state:
        st.session_state.logic_memo_input = ""
    if 'logic_ag_input' not in st.session_state:
        st.session_state.logic_ag_input = ""
    
    # State for confirmation flow
    if 'action_confirm' not in st.session_state:
        st.session_state.action_confirm = None
        
    def execute_action():
        act = st.session_state.action_confirm
        if act:
            k = act["key"]
            if act["action"] == "load":
                entry = logics.get(k, {})
                st.session_state.logic_name_input = k
                st.session_state.logic_memo_input = entry.get("memo", "")
                st.session_state.logic_ag_input = entry.get("ag_prompt", "")
            elif act["action"] == "delete":
                if k in logics:
                    del logics[k]
                    save_logics(logics)
        st.session_state.action_confirm = None
        
    def cancel_action():
        st.session_state.action_confirm = None

    st.subheader("📁 保存済みロジック一覧")
    
    confirm_state = st.session_state.action_confirm
    if confirm_state:
        k = confirm_state["key"]
        act = confirm_state["action"]
        if act == "load":
            st.warning(f"「{k}」を読み込みますか？ 現在の入力内容は上書きされます。")
        else:
            st.error(f"「{k}」を削除しますか？ この操作は元に戻せません。")
            
        c_yes, c_no = st.columns(2)
        with c_yes:
            st.button("✅ はい", on_click=execute_action, key="confirm_action_yes", use_container_width=True)
        with c_no:
            st.button("❌ キャンセル", on_click=cancel_action, key="confirm_action_no", use_container_width=True)
        st.write("")

    if not logics:
        st.info("保存されたロジックはありません。")
    else:
        # Header for the list
        hc1, hc2, hc3, hc4 = st.columns([5, 3, 1, 1])
        with hc1: st.caption("名前")
        with hc2: st.caption("最終更新日時")
        st.divider()
        
        # 動的にCSSを生成して交互の背景色を確実に設定する
        css_rules = ["<style>"]
        for i, k in enumerate(sorted_keys):
            bg = "#ffffff" if i % 2 == 0 else "#f5f5f5"
            css_rules.append(f"""
                div[data-testid="stHorizontalBlock"]:has(.logic-row-{i}) {{
                    background-color: {bg} !important;
                    padding: 8px 12px;
                    border-radius: 4px;
                    align-items: center;
                }}
                /* 背景が明るいので文字色を暗く固定 */
                div[data-testid="stHorizontalBlock"]:has(.logic-row-{i}) p,
                div[data-testid="stHorizontalBlock"]:has(.logic-row-{i}) span,
                div[data-testid="stHorizontalBlock"]:has(.logic-row-{i}) div {{
                    color: #333333 !important;
                }}
                /* ボタンの余白を詰める */
                div[data-testid="stHorizontalBlock"]:has(.logic-row-{i}) button {{
                    margin: 0;
                    padding: 4px 8px;
                }}
            """)
        css_rules.append("</style>")
        st.markdown("\n".join(css_rules), unsafe_allow_html=True)
        
        for i, k in enumerate(sorted_keys):
            c1, c2, c3, c4 = st.columns([5, 3, 1, 1])
            with c1:
                st.markdown(f"<span class='logic-row-{i}'>📄 **{k}**</span>", unsafe_allow_html=True)
            with c2:
                st.caption(logics[k].get("date", ""))
            with c3:
                if st.button("📂", key=f"btn_load_{k}", help="読み込む", disabled=(confirm_state is not None)):
                    st.session_state.action_confirm = {"action": "load", "key": k}
                    st.rerun()
            with c4:
                if st.button("🗑️", key=f"btn_del_{k}", help="削除する", disabled=(confirm_state is not None)):
                    st.session_state.action_confirm = {"action": "delete", "key": k}
                    st.rerun()

    st.divider()
    
    st.subheader("✍️ エディタ")
    
    # "Clear" button to act like the previous "新規作成"
    if st.button("✨ 新規作成 (クリア)", use_container_width=False):
        st.session_state.logic_name_input = ""
        st.session_state.logic_memo_input = ""
        st.session_state.logic_ag_input = ""
        st.rerun()

    new_name = st.text_input("💻 ロジック名", key="logic_name_input")
    
    nc1, nc2 = st.columns(2)
    with nc1:
        new_memo = st.text_area("📝 メモ", height=250, key="logic_memo_input", placeholder="このロジックの概要や使用条件などを記録します...")
    with nc2:
        new_ag = st.text_area("🤖 antigravityへの指示", height=250, key="logic_ag_input", placeholder="プロンプトや設定項目など、エージェントへ引き継ぐ指示を記録...")
        
    date_display = ""
    if new_name and new_name in logics:
        date_display = logics[new_name].get("date", "")
        
    if date_display:
        st.caption(f"最終更新日時: {date_display}")
        
    if st.button("💾 保存する", type="primary"):
        if not new_name.strip():
            st.error("ロジック名を入力してください。")
        else:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logics[new_name.strip()] = {
                "memo": new_memo,
                "ag_prompt": new_ag,
                "date": now_str
            }
            save_logics(logics)
            st.success(f"「{new_name}」を保存しました！({now_str})")
            time.sleep(1)
            st.rerun()



# ──────────────────────────────────────────────
# 🔬 実験その3: 馬番パターンスキャナー Pro v2.0
# ──────────────────────────────────────────────
if nav == "🔬 実験その３(馬番パターン)":
    st.header("🔬 実験その３: 馬番ポジション・パターンスキャナー Pro v2.0")
    st.markdown("""
    同日同場のレース間で、騎手・厩舎の **馬番配置** に特定のパターンを検出し、**穴馬候補をスコアリング**するツールです。

    #### 検出パターン (v2.0)
    | パターン | 条件 |
    |---|---|
    | **P1: 裏同士** | 異なる頭数のレース間で裏番号が一致 |
    | **P2: 裏表逆** | 一方の馬番 = 他方の裏番号 |
    | **P3: 一の位一致** | 馬番の一の位が同じ |
    | **P4: 表循環** | 大頭数側の馬番を小頭数で循環させると一致 |
    | **P4: 裏循環** | 大頭数側の裏番を小頭数で循環させた値が小頭数側の裏番と一致 |

    #### スコアリング (v2.0)
    | ボーナス | 条件 | 加点 |
    |---|---|---|
    | Base | パターン1種類ごと | +1 |
    | Overlap | 3種類以上同時検出 | +3 |
    | Strategic Entry | 当日のEntity出走がちょうど2回 | +3 |
    | Longshot | 7人気以上 or オッズ20倍以上 | +1 |
    | Best Period | 開催日数3〜8日目 | +1 |
    """)

    st.divider()

    col_l, col_r = st.columns([1, 2])
    with col_l:
        seed_url = st.text_input(
            "🔗 ベースURL (当日の任意のレースURL)",
            placeholder="https://race.netkeiba.com/race/shutuba.html?race_id=202608020201",
            key="rpps_seed_url"
        )
        max_races = st.slider("📋 スキャンするレース数 (1R〜NR)", min_value=1, max_value=12, value=12, key="rpps_max_races")
        entity = st.radio("👤 比較対象", options=["jockey", "trainer", "both"], index=0,
                          format_func=lambda x: {"jockey": "🏇 騎手", "trainer": "🏋 厩舎", "both": "🔀 両方"}.get(x, x),
                          key="rpps_entity", horizontal=True)
        min_patterns = st.number_input("🎯 最低パターン数", min_value=1, max_value=5, value=1, step=1, key="rpps_min_pat")

    with col_r:
        st.info("""
        **使い方**:
        1. 当日の任意のレースURL（netkeiba 出馬表）を貼り付けてください。
        2. スキャン範囲（1R〜12Rなど）と比較対象（騎手 or 厩舎）を設定。
        3. 「🔍 スキャン開始」ボタンを押してください。

        **スコア目安**:
        - 🔴 7以上: 超注目穴馬
        - 🟠 5〜6: 要警戒穴馬
        - 🟡 3〜4: 気になる馬
        - ⚪ 1〜2: 参考程度
        """)

    st.divider()

    if 'rpps_result_df' not in st.session_state:
        st.session_state.rpps_result_df = None

    scan_btn = st.button("🔍 スキャン開始", type="primary", disabled=not seed_url, key="rpps_scan_btn")

    if scan_btn and seed_url:
        import race_position_scanner as rpps
        # Reload module to pick up any changes
        import importlib
        importlib.reload(rpps)
        
        urls = rpps.build_urls_from_seed(seed_url, max_races)
        st.info(f"🔍 {len(urls)} 件のレースをスキャンします...")
        progress_bar = st.progress(0)
        status_text = st.empty()

        def update_progress(idx, total, msg):
            if total > 0:
                progress_bar.progress((idx + 1) / total)
            status_text.caption(msg)

        with st.spinner("スクレイピング・パターン検出中... (しばらくお待ちください)"):
            try:
                df_result = rpps.run_scan(
                    urls=urls,
                    entity=entity,
                    min_patterns=int(min_patterns),
                    output_csv=None,
                    progress_callback=update_progress,
                )
                st.session_state.rpps_result_df = df_result
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
                import traceback
                st.code(traceback.format_exc())

        progress_bar.empty()
        status_text.empty()

    # --- Result Display ---
    df_res = st.session_state.rpps_result_df
    if df_res is not None:
        if df_res.empty:
            st.warning("パターンが検出された馬はいませんでした。スキャン範囲や比較対象を変えてお試しください。")
        else:
            st.success(f"✅ {len(df_res)} 頭の候補を検出しました！")
            
            # Highlight warning rows
            if "warning" in df_res.columns and df_res["warning"].any():
                st.warning("⚠️ 取消/除外馬が含まれるレースがあります。警告列を確認してください。")

            st.subheader("📊 スコアランキング (スコア降順)")

            def color_score(val):
                if val >= 7: return "background-color: #8B0000; color: white; font-weight: bold"
                if val >= 5: return "background-color: #cc0000; color: white; font-weight: bold"
                if val >= 3: return "background-color: #ff9900; color: black"
                if val >= 2: return "background-color: #ffff66; color: black"
                return ""

            def color_best_period(val):
                return "background-color: #ccffcc; color: black" if val else ""

            try:
                style_cols = {"score": color_score}
                if "is_best_period" in df_res.columns:
                    style_cols["is_best_period"] = color_best_period
                styled_res = df_res.style.applymap(lambda v: color_score(v), subset=["score"])
                if "is_best_period" in df_res.columns:
                    styled_res = styled_res.applymap(color_best_period, subset=["is_best_period"])

                # Display only readable columns
                display_cols = [c for c in [
                    "race_id", "race_number", "horse_number", "horse_name",
                    "jockey", "trainer", "patterns", "score",
                    "odds", "rank", "is_best_period", "warning"
                ] if c in df_res.columns]

                st.dataframe(
                    df_res[display_cols].style.applymap(
                        color_score, subset=["score"] if "score" in display_cols else []
                    ),
                    column_config={
                        "race_id": st.column_config.TextColumn("Race ID"),
                        "race_number": st.column_config.NumberColumn("R", format="%dR"),
                        "horse_number": st.column_config.NumberColumn("馬番"),
                        "horse_name": st.column_config.TextColumn("馬名"),
                        "jockey": st.column_config.TextColumn("騎手"),
                        "trainer": st.column_config.TextColumn("厩舎"),
                        "patterns": st.column_config.TextColumn("検出パターン"),
                        "score": st.column_config.NumberColumn("🔥 スコア"),
                        "odds": st.column_config.NumberColumn("単勝オッズ", format="%.1f"),
                        "rank": st.column_config.NumberColumn("人気", format="%d位"),
                        "is_best_period": st.column_config.CheckboxColumn("✨ Best Period"),
                        "warning": st.column_config.TextColumn("⚠️ 警告"),
                    },
                    use_container_width=True,
                    hide_index=True,
                )
            except Exception as e_disp:
                st.warning(f"スタイルエラー: {e_disp}")
                st.dataframe(df_res, use_container_width=True)

            # CSV download
            csv_bytes = df_res.to_csv(index=False, encoding='utf-8-sig').encode("utf-8-sig")
            st.download_button(
                label="💾 CSVダウンロード",
                data=csv_bytes,
                file_name="pattern_scan_result.csv",
                mime="text/csv",
                key="rpps_csv_download"
            )

            st.divider()
            st.subheader("📈 パターン別 検出数")
            all_patterns = []
            for pats in df_res.get("patterns", pd.Series()):
                if pats:
                    all_patterns.extend(str(pats).split(","))
            if all_patterns:
                pat_series = pd.Series(all_patterns).value_counts()
                st.bar_chart(pat_series)

# ──────────────────────────────────────────────
# 📦 データ保管庫 (Storage Hub) タブ
# ──────────────────────────────────────────────
if nav == "📦 データ保管庫":
    import history_manager
    from calendar import monthcalendar, month_name
    from datetime import date

    st.header("📦 データ保管庫 (Storage Hub)")
    st.caption("ローカルで取得したデータ（U指数・オメガ指数含む）をクラウドに同期し、いつでも活用できます。")

    st.markdown("""
    > [!NOTE]
    > **使い方**: ローカルPCで解析を実行し、生成された `race_history.csv` をここからアップロードするか、
    > `push.bat` で GitHub にコミットしてください。データはクラウドサーバーに永続保存されます。
    """)

    # ─────────────────────────────────────────
    # ① カレンダー表示（データ取得済みの日を強調）
    # ─────────────────────────────────────────
    st.subheader("📅 データ取得済みカレンダー")

    dates_with_data = history_manager.get_dates_with_data()

    # 月選択
    today = date.today()
    col_y, col_m = st.columns(2)
    with col_y:
        sel_year = st.selectbox("年", list(range(2024, today.year + 2)), index=today.year - 2024, key="hub_year")
    with col_m:
        sel_month = st.selectbox("月", list(range(1, 13)), index=today.month - 1, key="hub_month",
                                  format_func=lambda m: f"{m}月")

    # カレンダー描画
    weeks = monthcalendar(sel_year, sel_month)
    day_headers = ["月", "火", "水", "木", "金", "土", "日"]
    cal_html = """
    <style>
    .hub-cal { width: 100%; border-collapse: collapse; font-size: 1em; }
    .hub-cal th { background: #1e1e2e; color: #aaa; text-align: center; padding: 6px; }
    .hub-cal td { text-align: center; padding: 8px; border: 1px solid #333; border-radius: 4px; min-width: 36px; }
    .hub-cal td.no-day { background: transparent; border: none; }
    .hub-cal td.has-data { background: #1a472a; color: #6fcf97; font-weight: bold; cursor: pointer; }
    .hub-cal td.today { outline: 2px solid #f59e0b; }
    .hub-cal td.no-data { color: #666; }
    .hub-cal .badge { font-size: 0.65em; background: #2d6a4f; color: #b7e4c7; border-radius: 8px; padding: 1px 5px; display: block; }
    </style>
    <table class="hub-cal"><tr>
    """ + "".join(f"<th>{h}</th>" for h in day_headers) + "</tr>"

    for week in weeks:
        cal_html += "<tr>"
        for d in week:
            if d == 0:
                cal_html += '<td class="no-day"></td>'
            else:
                date_key = f"{sel_year}-{sel_month:02d}-{d:02d}"
                is_today = (d == today.day and sel_month == today.month and sel_year == today.year)
                today_cls = " today" if is_today else ""
                if date_key in dates_with_data:
                    race_count = dates_with_data[date_key]
                    cal_html += f'<td class="has-data{today_cls}">{d}<span class="badge">{race_count}R</span></td>'
                else:
                    cal_html += f'<td class="no-data{today_cls}">{d}</td>'
        cal_html += "</tr>"
    cal_html += "</table>"
    st.html(cal_html)

    # ─────────────────────────────────────────
    # ② 日付別データ確認
    # ─────────────────────────────────────────
    st.divider()
    st.subheader("🔎 日付別データ確認")

    if dates_with_data:
        sorted_dates = sorted(dates_with_data.keys(), reverse=True)
        selected_date = st.selectbox(
            "データ取得済みの日付を選択",
            sorted_dates,
            format_func=lambda d: f"📅 {d}（{dates_with_data[d]}レース分）",
            key="hub_date_sel"
        )
        df_date = history_manager.get_data_for_date(selected_date)
        if not df_date.empty:
            st.success(f"✅ {selected_date} のデータ: {len(df_date['RaceID'].unique())} レース / {len(df_date)} 頭")

            # サマリーテーブル（レース別）
            race_summary = df_date.groupby('RaceID').agg(
                RaceName=('RaceName', 'first') if 'RaceName' in df_date.columns else ('RaceID', 'first'),
                頭数=('RaceID', 'count'),
                U指数=('UIndex', lambda x: '✅' if x.notna().any() else '-') if 'UIndex' in df_date.columns else ('RaceID', lambda x: '-'),
                オメガ指数=('LaboIndex', lambda x: '✅' if x.notna().any() else '-') if 'LaboIndex' in df_date.columns else ('RaceID', lambda x: '-'),
            ).reset_index()
            st.dataframe(race_summary, use_container_width=True)

            with st.expander("📋 生データを表示（全カラム）"):
                st.dataframe(df_date, use_container_width=True)
        else:
            st.warning("データが見つかりませんでした。")
    else:
        st.info("まだ保管庫にデータがありません。下のアップローダーからCSVを登録してください。")

    # ─────────────────────────────────────────
    # ③ ローカルCSVアップロード（クラウド同期）
    # ─────────────────────────────────────────
    st.divider()
    st.subheader("⬆️ ローカルCSV同期（クラウドへアップロード）")

    st.markdown("""
    **手順：**
    1. ローカルPCの `keiba_analysis` フォルダ内にある `race_history.csv` をドラッグ＆ドロップ
    2. または、ローカルで解析後に保存された任意のCSVをアップロード
    3. 「同期する」ボタンを押して保管庫に追加
    """)

    uploaded_file = st.file_uploader(
        "race_history.csv または解析済みCSVをアップロード",
        type=["csv"],
        key="hub_csv_uploader",
        help="ローカルで取得したU指数・オメガ指数データを含むCSVをアップロードしてください。"
    )

    if uploaded_file is not None:
        try:
            uploaded_df = pd.read_csv(uploaded_file, encoding='utf-8')
        except Exception:
            try:
                uploaded_file.seek(0)
                uploaded_df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
            except Exception as e:
                st.error(f"CSVの読み込みに失敗しました: {e}")
                uploaded_df = pd.DataFrame()

        if not uploaded_df.empty:
            st.success(f"✅ ファイル読み込み成功: {len(uploaded_df)} 行 / {uploaded_df.shape[1]} カラム")
            with st.expander("📋 プレビュー（最初の10行）"):
                st.dataframe(uploaded_df.head(10), use_container_width=True)

            if st.button("⬆️ 保管庫に同期する", type="primary", key="hub_sync_btn"):
                result = history_manager.merge_uploaded_csv(uploaded_df)
                if result["status"] == "ok":
                    st.success(result["message"])
                    st.info(f"📊 保管庫合計: {result['total_stored']} 件のレコード")
                    st.rerun()
                else:
                    st.error(result["message"])

    # ─────────────────────────────────────────
    # ④ 保管庫統計
    # ─────────────────────────────────────────
    st.divider()
    st.subheader("📊 保管庫サマリー")

    all_hist = history_manager.load_history()
    if not all_hist.empty:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("📅 記録日数", len(dates_with_data))
        with col2:
            unique_races = all_hist['RaceID'].nunique() if 'RaceID' in all_hist.columns else 0
            st.metric("🏇 記録レース数", unique_races)
        with col3:
            st.metric("🐴 記録頭数", len(all_hist))
        with col4:
            has_u = all_hist['UIndex'].notna().sum() if 'UIndex' in all_hist.columns else 0
            st.metric("✨ U指数あり", f"{has_u} 件")

        # GitHub経由での保存案内
        st.markdown("""
        ---
        > 💡 **データを永続保存するには**: ローカルで `push.bat` を実行し、
        > `race_history.csv` を GitHub に コミットしてください。
        > Streamlit Cloud は自動的に最新データをデプロイします。
        """)
    else:
        st.info("保管庫は現在空です。")

# ──────────────────────────────────────────────
# --- Footer ---
st.divider()
st.caption("Keiba Analysis v2.5 - Powered by Streamlit & Gemini API")
