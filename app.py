import sys, io
sys.setrecursionlimit(10000) # Increased to handle Torch initialization
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
load_dotenv(override=True)

# API Key Management (Priority: .env > st.secrets)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    try:
        GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        pass

if not GEMINI_API_KEY:
    st.error("API Key not found. Please set GEMINI_API_KEY in .env or Streamlit Secrets.")
    st.stop()

# Debug info (Masked) - REMOVED for security
# st.sidebar.caption(...) 

import importlib
import pandas as pd
import numpy as np
import time
import math
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# Core functionality imports
from core import scraper
from core import calculator
try:
    importlib.reload(calculator)
except:
    pass
from core import theory_rmhs
from core import odds_tracker
from core import odds_analyzer
from core.scraper import fetch_comprehensive_result
from core.odds_tracker import OddsTracker
from core.odds_analyzer import OddsAnalyzer
from core.kaggle_client import KaggleChatClient
from core import lab_fetcher


st.set_page_config(page_title="Keiba Analysis - Modified Ogura Index", layout="wide")

# --- Shared Constants & Helpers ---

from core.scraper import VENUE_NAMES

def get_netkeiba_domain(race_id):
    """Detects the appropriate netkeiba domain based on race_id."""
    try:
        pid = int(str(race_id)[4:6])
        if pid > 10:
            return "nar.netkeiba.com"
    except:
        pass
    return "race.netkeiba.com"

def render_session_status(key_prefix=""):
    """Renders session status and login buttons for Umanity and KeibaLab."""
    import os
    from datetime import datetime
    
    col1, col2 = st.columns(2)
    
    # Define absolute paths for session files
    base_dir = os.path.dirname(os.path.abspath(__file__))
    session_umanity = os.path.join(base_dir, "auth_session.json")
    session_labo = os.path.join(base_dir, "labo_session.json")
    
    # --- Umanity ---
    with col1:
        st.markdown("**🔑 認証 (Umanity / U指数)**")
        if os.path.exists(session_umanity):
            mtime = os.path.getmtime(session_umanity)
            dt_mtime = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            st.success(f"✅ 保存済み ({dt_mtime})")
        else:
            st.warning("⚠️ 未ログイン (U指数取得不可)")
        
        if st.button("🔑 Umanity ログイン", key=f"{key_prefix}btn_umanity"):
            import subprocess, sys as _sys
            if _sys.platform == 'win32':
                cmd = f'powershell -Command "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; py create_session.py umanity"'
                subprocess.Popen(['powershell', '-Command', cmd], creationflags=subprocess.CREATE_NEW_CONSOLE)
                st.info("別窓でブラウザが起動しました。完了後に窓を閉じてください。")
            else:
                st.warning("⚠️ このボタンはWindows環境専用です。Streamlit Cloud環境では `create_session.py umanity` をローカルで実行し、生成された `auth_session.json` をアップロードしてください。")

    # --- KeibaLab ---
    with col2:
        st.markdown("**🔑 認証 (競馬ラボ / オメガ指数)**")
        if os.path.exists(session_labo):
            mtime = os.path.getmtime(session_labo)
            dt_mtime = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            st.success(f"✅ 保存済み ({dt_mtime})")
        else:
            st.warning("⚠️ 未ログイン (オメガ指数取得不可)")
        
        if st.button("🔑 競馬ラボ ログイン", key=f"{key_prefix}btn_labo"):
            import subprocess, sys as _sys
            if _sys.platform == 'win32':
                cmd = f'powershell -Command "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; py create_session.py keibalab"'
                subprocess.Popen(['powershell', '-Command', cmd], creationflags=subprocess.CREATE_NEW_CONSOLE)
                st.info("別窓でブラウザが起動しました。完了後に窓を閉じてください。")
            else:
                st.warning("⚠️ このボタンはWindows環境専用です。Streamlit Cloud環境では `create_session.py keibalab` をローカルで実行し、生成された `labo_session.json` をアップロードしてください。")

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
            "💰 BetSync（資金管理）",
            "🔍 Race Scanner (Batch)",
            "📊 History & Review",
            "🧪 新ロジックテスト(FEW+マクリ)",
            "🤓 N氏の研究室",
            "💾 ロジック置き場",
            "📦 データ保管庫",
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
        *   **⚠️ (警告): データ不足** (N指数と戦闘力が0の馬。デビュー戦やデータ取得失敗の可能性があります)
        
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

    import json
    import os
    import uuid
    import traceback
    from datetime import datetime

    BETSYNC_FILE = "betsync_data.json"

    def save_betsync_data(data):
        with open(BETSYNC_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_betsync_data():
        if os.path.exists(BETSYNC_FILE):
            try:
                with open(BETSYNC_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return None
        return None

    try:

        # ── 定数 ──
        ROKU_UNITS   = [100, 200, 300, 400, 500, 600]   # 6連法の単価ステップ
        TICKET_COUNT = {"3連複（15点）": 15, "馬連（5点）": 5}

        # ── Session State 初期化 ──
        _ss = st.session_state
        
        # Load persistence if session is empty
        if 'bs_races' not in _ss:
            persisted = load_betsync_data()
            if persisted:
                _ss['bs_bankroll'] = persisted.get('bankroll', 20000)
                _ss['bs_init_bet'] = persisted.get('init_bet', 100)
                _ss['bs_target']   = persisted.get('target', 50)
                _ss['bs_strategy'] = persisted.get('strategy', "[稼働中] 6連サバイバル")
                _ss['bs_ticket']   = persisted.get('ticket', "3連複（15点）")
                _ss['bs_races']    = persisted.get('races', [])
                # Ensure all legacy races have a UUID
                for r in _ss['bs_races']:
                    if 'id' not in r: r['id'] = str(uuid.uuid4())
            else:
                _ss['bs_bankroll'] = 20000
                _ss['bs_init_bet'] = 100
                _ss['bs_target']   = 50
                _ss['bs_strategy'] = "[稼働中] 6連サバイバル"
                _ss['bs_ticket']   = "3連複（15点）"
                _ss['bs_races']    = []

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
                if _win_seq:
                    _win_mult = _win_seq[0] * 2
                    unit = _win_mult * 100
                    step = len(_win_seq)
                else:
                    unit = 100
                    _win_mult = 1
                    step = 0
            else:  # 6連法
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

            # Result type
            if ret == 0: result_type = "MISS"
            elif ret > bet: result_type = "PLUS"
            else: result_type = "GAMI"

            if cycle_deficit <= 0: cycle_deficit = 0

            # modify sequence after this race
            if strategy == "3Dリカバリ":
                if result_type == "MISS":
                    _3d_seq.append(_3d_mult)
                elif result_type == "PLUS":
                    _3d_seq = _3d_seq[1:-1] if len(_3d_seq) >= 2 else []
                elif result_type == "GAMI":
                    _3d_seq = _3d_seq[1:] if _3d_seq else []
                if not _3d_seq: _3d_seq = [1, 1, 1]
            elif strategy == "ジワ上げ":
                if result_type == "MISS": _jiwa_unit += 100
                else: _jiwa_unit = max(100, _jiwa_unit - 100)
            elif strategy == "ウィナーズ":
                if _win_seq:
                    if result_type == "MISS": _win_seq.append(_win_mult)
                    else:
                        _win_seq = _win_seq[1:]
                        if not _win_seq: _win_consec_loss = 0
                else:
                    if result_type == "MISS":
                        _win_consec_loss += 1
                        if _win_consec_loss >= 2: _win_seq = [1, 1]
                    else: _win_consec_loss = 0

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

        # Next-race step/bet
        if strategy == "3Dリカバリ":
            if not _3d_seq: _3d_seq = [1, 1, 1]
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
        m2.metric("勝率",         f"{wins/total_races*100:.0f}%" if total_races else "-", f"{wins}勝 / {total_races-wins}敗")
        m3.metric("総投資額",     f"¥{total_cum_bet:,.0f}")
        m4.metric("総払戻金",     f"¥{total_ret:,.0f}")
        m5.metric("目標利益まで", f"¥{max(0, target_profit-final_profit):,.0f}", f"目標¥{target_profit:,.0f}")

        progress_pct = min(1.0, max(0.0, final_profit / target_profit)) if target_profit > 0 else 0
        st.progress(progress_pct, text=f"目標達成率: {progress_pct*100:.1f}%")

        # ─────────────────────────────────────────
        # 6連法：ステッパー
        # ─────────────────────────────────────────
        if strategy == "6連法（サバイバル）":
            thresholds  = ROKU_THRESHOLDS[ticket]
            total_loss_line = ROKU_TOTAL_LOSS_LINE[ticket]
            cur_deficit = computed[-1]['cycle_deficit'] if computed else 0
            next_step   = _roku_step_from_deficit(cur_deficit, thresholds)
            is_total_loss = cur_deficit > total_loss_line

            if is_total_loss:
                st.error(f"✨ **全損到達（累計赤字 ¥{cur_deficit:,.0f}）。** サイクルをリセットしてください。")
            else:
                next_step  = min(next_step, 5)
                next_unit  = ROKU_UNITS[next_step]
                next_bet   = next_unit * n_tickets
                is_danger  = cur_deficit > thresholds[3] if len(thresholds) > 3 else False

                step_pills = ""
                for j in range(6):
                    is_active  = (j == next_step)
                    is_d       = (is_danger and is_active)
                    pill_bg    = "#FF6B00" if is_d else ("#FFD700" if is_active else "transparent")
                    pill_color = "#000"    if is_active else "#DDD"
                    pill_border= "#FF6B00" if is_d else ("#FFD700" if is_active else "#666")
                    pill_size  = "1.05em" if is_active else "0.85em"
                    pill_label = f"Step {j+1}<br><span style='font-size:0.78em;'>&#165;{ROKU_UNITS[j]*n_tickets:,}</span>"
                    connector  = "" if j == 0 else "<span style='color:#888;padding:0 4px;'>&mdash;</span>"
                    step_pills += f"{connector}<span style='display:inline-block;text-align:center;padding:6px 12px;background:{pill_bg};color:{pill_color};border:2px solid {pill_border};border-radius:20px;font-size:{pill_size};font-weight:{'bold' if is_active else 'normal'};line-height:1.4;vertical-align:middle;'>{pill_label}</span>"

                deficit_pct = cur_deficit / total_loss_line if total_loss_line > 0 else 0
                danger_note = f"<span style='color:#FF6B6B;font-size:0.9em;'>✨ サイクル赤字：¥{cur_deficit:,.0f} / 全損：¥{total_loss_line:,}</span>" if cur_deficit > 0 else "<span style='color:#6FE09A;'>✅ サイクルプラス</span>"
                border_color = "#FF6B00" if is_danger else "#FFD700"
                bg_color     = "#1f0800" if is_danger else "#1a1400"
                st.html(f"""<div style="border:2px solid {border_color};border-radius:10px;padding:14px 18px;margin:12px 0;background:{bg_color};">
      <div style="font-size:0.82em;color:#888;margin-bottom:10px;letter-spacing:.05em;">✨ 6連法 ステッパー</div>
      <div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-bottom:12px;">{step_pills}</div>
      <div style="font-size:1.05em;">▶ 次回のベット：<strong style="color:{border_color};font-size:1.25em;">¥{next_bet:,.0f}</strong><span style="color:#aaa;font-size:0.85em;">（単価 ¥{next_unit} × {n_tickets}点）</span>&nbsp;&nbsp;{danger_note}</div>
    </div>""")

        # ─────────────────────────────────────────
        # ③ 戦略別ディスプレイ (追加)
        # ─────────────────────────────────────────
        elif strategy == "3Dリカバリ":
            seq_display = ', '.join(str(x) for x in _3d_seq)
            _3d_next_mult = (_3d_seq[0] + _3d_seq[-1]) if len(_3d_seq) >= 2 else (_3d_seq[0] if _3d_seq else 1)
            _3d_raw  = _3d_next_mult * 50
            _3d_next_unit = max(100, (_3d_raw // 100) * 100)
            _3d_truncated = (_3d_raw % 100) > 0
            _3d_next_bet  = _3d_next_unit * n_tickets
            seq_len = len(_3d_seq)
            if seq_len <= 3:
                _3d_border = "#4CAF50"; _3d_bg = "#0a1f0a"
                _3d_status = "<span style='color:#6FE09A;'>✓ 数列が短い = リカバリー順調</span>"
            elif seq_len <= 5:
                _3d_border = "#FFD700"; _3d_bg = "#1a1400"
                _3d_status = "<span style='color:#FFD700;'>✨ 数列が伸びています</span>"
            else:
                _3d_border = "#FF6B00"; _3d_bg = "#1f0800"
                _3d_status = "<span style='color:#FF6B6B;'>✨ 数列が長い = 深追い中</span>"

            seq_pills = ""
            for si, sv in enumerate(_3d_seq):
                is_edge = (si == 0 or si == len(_3d_seq) - 1)
                p_bg   = "#FFD700" if is_edge else "transparent"
                p_col  = "#000" if is_edge else "#DDD"
                p_bdr  = "#FFD700" if is_edge else "#666"
                p_fw   = "bold" if is_edge else "normal"
                seq_pills += f"<span style='display:inline-block;padding:4px 10px;background:{p_bg};color:{p_col};border:2px solid {p_bdr};border-radius:16px;font-size:0.95em;font-weight:{p_fw};margin:2px 3px;'>{sv}</span>"

            st.html(f"""<div style="border:2px solid {_3d_border};border-radius:10px;padding:14px 18px;margin:12px 0;background:{_3d_bg};">
      <div style="font-size:0.82em;color:#888;margin-bottom:10px;">🎲 3Dリカバリ 数列モニター</div>
      <div style="margin-bottom:10px;">{seq_pills}</div>
      <div style="font-size:0.88em;color:#aaa;margin-bottom:8px;">数列: [{seq_display}]&nbsp;&nbsp;{_3d_status}</div>
      <div style="font-size:1.05em;">▶ 次回のベット：<strong style="color:{_3d_border};font-size:1.25em;">¥{_3d_next_bet:,.0f}</strong><span style="color:#aaa;font-size:0.85em;">（単価 ¥{_3d_next_unit:,} × {n_tickets}点）</span></div>
    </div>""")

        elif strategy == "ジワ上げ":
            if _jiwa_unit <= 200:
                _jw_border = "#4CAF50"; _jw_bg = "#0a1f0a"
                _jw_status = "<span style='color:#6FE09A;'>✓ 低単価ゾーン</span>"
            elif _jiwa_unit <= 400:
                _jw_border = "#FFD700"; _jw_bg = "#1a1400"
                _jw_status = "<span style='color:#FFD700;'>⚠️ 中単価ゾーン</span>"
            else:
                _jw_border = "#FF6B00"; _jw_bg = "#1f0800"
                _jw_status = "<span style='color:#FF6B6B;'>🚨 高単価ゾーン</span>"

            _jw_pills = ""
            for jp in range(6):
                jp_unit = (jp + 1) * 100
                jp_active = (jp_unit == _jiwa_unit)
                jp_bg  = "#FFD700" if jp_active else "transparent"
                jp_col = "#000" if jp_active else "#DDD"
                jp_bdr = "#FFD700" if jp_active else "#666"
                jp_fw  = "bold" if jp_active else "normal"
                connector = "" if jp == 0 else "<span style='color:#888;padding:0 4px;'>—</span>"
                _jw_pills += f"{connector}<span style='display:inline-block;padding:6px 12px;background:{jp_bg};color:{jp_col};border:2px solid {jp_bdr};border-radius:20px;font-size:0.85em;'>¥{jp_unit}<br>¥{jp_unit*n_tickets:,}</span>"

            st.html(f"""<div style="border:2px solid {_jw_border};border-radius:10px;padding:14px 18px;margin:12px 0;background:{_jw_bg};">
      <div style="font-size:0.82em;color:#888;margin-bottom:10px;">🛡️ ジワ上げ 単価モニター</div>
      <div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-bottom:12px;">{_jw_pills}</div>
      <div style="font-size:1.05em;">▶ 次回のベット：<strong style="color:{_jw_border};font-size:1.25em;">¥{_jiwa_unit*n_tickets:,.0f}</strong><span style="color:#aaa;font-size:0.85em;">（単価 ¥{_jiwa_unit:,} × {n_tickets}点）</span></div>
    </div>""")

        elif strategy == "ウィナーズ":
            if _win_seq:
                _wn_next_bet = (_win_seq[0] * 2 * 100) * n_tickets
                _wn_status = "<span style='color:#FFD700;'>⚠️ リカバリー実行中</span>"
                st.html(f"""<div style="border:2px solid #FFD700;border-radius:10px;padding:14px 18px;margin:12px 0;background:#1a1400;">
          <div style="font-size:0.82em;color:#888;margin-bottom:10px;">🎯 ウィナーズ モニター</div>
          <div style="font-size:0.88em;color:#aaa;margin-bottom:8px;">数列: [{', '.join(str(x) for x in _win_seq)}]&nbsp;&nbsp;{_wn_status}</div>
          <div style="font-size:1.05em;">▶ 次回のベット：<strong style="color:#FFD700;font-size:1.25em;">¥{_wn_next_bet:,.0f}</strong></div>
        </div>""")
            else:
                _wn_status = "<span style='color:#6FE09A;'>✓ 待機中</span>" if _win_consec_loss < 1 else "<span style='color:#FFD700;'>⚠️ 1敗中</span>"
                st.html(f"""<div style="border:2px solid #666;border-radius:10px;padding:14px 18px;margin:12px 0;background:#111;">
          <div style="font-size:0.88em;color:#aaa;">🎯 ウィナーズ: {_wn_status}</div>
          <div style="font-size:1.05em;">▶ 次回のベット：<strong>¥{init_bet*n_tickets:,.0f}</strong></div>
        </div>""")

        # ─────────────────────────────────────────
        # ④ レース履歴テーブル
        # ─────────────────────────────────────────
        st.divider()
        st.subheader("🏁 レース履歴")

        if not races:
            st.info("まだレースが記録されていません。下のボタンから追加してください。")
        else:
            comp_idx = 0
            for ri, r in enumerate(races):
                r_id = r.get('id', str(ri))
                is_pending = not r.get('decided', True)
                rnum = ri + 1

                if is_pending:
                    st.html(f"""<div style="border:2px solid #FFD700;border-radius:10px;padding:12px 16px;margin-bottom:8px;background:#1a1400;">
          <span style="font-weight:bold;color:#FFF;">R{rnum}</span> <span style="color:#aaa;">△ 未入力</span>
          <span style="color:#FFD700;margin-left:12px;">▶ 次回指示：<strong>¥{_nd_bet:,.0f}</strong></span>
        </div>""")
                    inp_c1, inp_c2, inp_c3 = st.columns([1.5, 3, 0.7])
                    with inp_c1:
                        rv = st.radio("勝敗", options=["❌ 負", "✅ 勝"], index=None, horizontal=True, key=f"bs_radio_{r_id}", label_visibility="collapsed")
                        if rv is not None:
                            _ss['bs_races'][ri]['win'] = (rv == "✅ 勝")
                            _ss['bs_races'][ri]['decided'] = True
                            if not _ss['bs_races'][ri]['win']: _ss['bs_races'][ri]['ret'] = 0
                            save_betsync_data({'bankroll': _ss['bs_bankroll'], 'init_bet': _ss['bs_init_bet'], 'target': _ss['bs_target'], 'strategy': _ss['bs_strategy'], 'ticket': _ss['bs_ticket'], 'races': _ss['bs_races']})
                            st.rerun()
                    with inp_c2: st.caption("← 勝敗を選択してください")
                    with inp_c3:
                        if st.button("🗑️", key=f"bs_del_{r_id}"):
                            _ss['bs_races'].pop(ri)
                            save_betsync_data({'bankroll': _ss['bs_bankroll'], 'init_bet': _ss['bs_init_bet'], 'target': _ss['bs_target'], 'strategy': _ss['bs_strategy'], 'ticket': _ss['bs_ticket'], 'races': _ss['bs_races']})
                            st.rerun()
                else:
                    c = computed[comp_idx]
                    comp_idx += 1
                    bg     = "#1a3a1f" if c['win'] else "#2a1515"
                    border = "#4CAF50" if c['win'] else "#F44336"
                    st.html(f"""<div style="background:{bg};border-left:5px solid {border};border-radius:8px;padding:8px 14px;margin-bottom:4px;display:flex;gap:12px;font-size:0.9em;color:#ccc;">
          <span style="font-weight:bold;color:#FFF;min-width:30px;">R{rnum}</span>
          <span>ベット ¥{c['bet']:,.0f}</span>
          <span>払戻 ¥{c['ret']:,.0f}</span>
          <span style="color:{'#6FE09A' if c['profit']>=0 else '#FF7070'};">収支 ¥{c['profit']:+,.0f}</span>
          <span style="color:#FFD700;">残高 ¥{c['balance']:,.0f}</span>
        </div>""")
                    ec1, ec2, ec3 = st.columns([1, 2, 0.5])
                    with ec1:
                        rv = st.radio("勝敗", options=["❌ 負", "✅ 勝"], index=1 if r['win'] else 0, horizontal=True, key=f"bs_radio_{r_id}", label_visibility="collapsed")
                        nw = (rv == "✅ 勝")
                        if nw != r['win']:
                            _ss['bs_races'][ri]['win'] = nw
                            if not nw: _ss['bs_races'][ri]['ret'] = 0
                            save_betsync_data({'bankroll': _ss['bs_bankroll'], 'init_bet': _ss['bs_init_bet'], 'target': _ss['bs_target'], 'strategy': _ss['bs_strategy'], 'ticket': _ss['bs_ticket'], 'races': _ss['bs_races']})
                            st.rerun()
                    with ec2:
                        if r['win']:
                            nr = st.number_input("払戻金", min_value=0, step=100, value=int(r.get('ret', 0)), key=f"bs_ret_{r_id}", label_visibility="collapsed")
                            if nr != r.get('ret', 0):
                                _ss['bs_races'][ri]['ret'] = nr
                                save_betsync_data({'bankroll': _ss['bs_bankroll'], 'init_bet': _ss['bs_init_bet'], 'target': _ss['bs_target'], 'strategy': _ss['bs_strategy'], 'ticket': _ss['bs_ticket'], 'races': _ss['bs_races']})
                                st.rerun()
                    with ec3:
                        if st.button("🗑️", key=f"bs_del_{r_id}"):
                            _ss['bs_races'].pop(ri)
                            save_betsync_data({'bankroll': _ss['bs_bankroll'], 'init_bet': _ss['bs_init_bet'], 'target': _ss['bs_target'], 'strategy': _ss['bs_strategy'], 'ticket': _ss['bs_ticket'], 'races': _ss['bs_races']})
                            st.rerun()

        # ─────────────────────────────────────────
        # ⑤ 操作パネル
        # ─────────────────────────────────────────
        b1, b2 = st.columns([2, 1])
        with b1:
            _pending = any(not r.get('decided', True) for r in races)
            if st.button("➕ 次のレースを追加", type="primary", disabled=_pending, key="bs_add"):
                _ss['bs_races'].append({'id': str(uuid.uuid4()), 'win': False, 'ret': 0, 'decided': False})
                save_betsync_data({'bankroll': _ss['bs_bankroll'], 'init_bet': _ss['bs_init_bet'], 'target': _ss['bs_target'], 'strategy': _ss['bs_strategy'], 'ticket': _ss['bs_ticket'], 'races': _ss['bs_races']})
                st.rerun()
        with b2:
            if st.button("✨ 全リセット", type="secondary", key="bs_reset"):
                _ss['bs_races'] = []
                if os.path.exists(BETSYNC_FILE): os.remove(BETSYNC_FILE)
                st.rerun()

        # ─────────────────────────────────────────
        # ─────────────────────────────────────────
        # ─────────────────────────────────────────
        # ⑥ Kaggleデータ分析チャット
        # ─────────────────────────────────────────
        st.divider()
        
        # Singleton client（session_state 経由で再利用）
        if "kaggle_chat_client" not in st.session_state:
            st.session_state.kaggle_chat_client = KaggleChatClient(api_key=GEMINI_API_KEY)
        kaggle_chat = st.session_state.kaggle_chat_client

        st.subheader("📊 Kaggleデータ分析チャット (2010-2025)")
        st.caption("Geminiを使用して過去15年分のデータを抽出・分析します。質問を入力してください。")

        # 1. 保存済み一覧 (💾 ロジック置き場風スタイル)
        with st.expander("📌 保存済み分析一覧", expanded=False):
            saved_items = kaggle_chat.get_saved_interactions()
            if not saved_items:
                st.write("保存された分析はありません")
            else:
                # ソート (最新順)
                sorted_saved = sorted(saved_items, key=lambda x: x.get('timestamp', ''), reverse=True)
                
                # Header
                shc1, shc2, shc3, shc4 = st.columns([5, 3, 1, 1])
                with shc1: st.caption("クエリ")
                with shc2: st.caption("保存日時")
                st.divider()
                
                # CSS for alternating rows (mimicking 💾 ロジック置き場)
                chat_css = ["<style>"]
                for i, item in enumerate(sorted_saved):
                    bg = "#ffffff" if i % 2 == 0 else "#f5f5f5"
                    chat_css.append(f"""
                        div[data-testid="stHorizontalBlock"]:has(.chat-row-{i}) {{
                            background-color: {bg} !important;
                            padding: 4px 8px;
                            border-radius: 4px;
                            align-items: center;
                        }}
                        div[data-testid="stHorizontalBlock"]:has(.chat-row-{i}) * {{
                            color: #333333 !important;
                        }}
                    """)
                chat_css.append("</style>")
                st.markdown("\n".join(chat_css), unsafe_allow_html=True)

                for i, item in enumerate(sorted_saved):
                    c1, c2, c3, c4 = st.columns([5, 3, 1, 1])
                    with c1:
                        query_disp = item['query'][:30] + "..." if len(item['query']) > 30 else item['query']
                        st.markdown(f"<span class='chat-row-{i}'>💬 **{query_disp}**</span>", unsafe_allow_html=True)
                    with c2:
                        st.caption(item.get('timestamp', '')[:16].replace('T', ' '))
                    with c3:
                        if st.button("📂", key=f"chat_load_{item['id']}", help="読み込む"):
                            restored_df = None
                            if item.get('response_df_json'):
                                try: restored_df = pd.read_json(item['response_df_json'], orient='split')
                                except: pass
                            st.session_state.kaggle_chat_history = [
                                {"role": "user", "content": item['query']},
                                {"role": "assistant", "content": item['response_text'], "df": restored_df}
                            ]
                            st.rerun()
                    with c4:
                        if st.button("🗑️", key=f"chat_del_{item['id']}", help="削除する"):
                            if kaggle_chat.delete_interaction(item['id']):
                                st.rerun()

        # 2. チャット履歴の初期化
        if "kaggle_chat_history" not in st.session_state:
            st.session_state.kaggle_chat_history = []

        # 3. チャットログの表示
        chat_container = st.container()
        with chat_container:
            for i, msg in enumerate(st.session_state.kaggle_chat_history):
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
                    if "df" in msg and msg["df"] is not None:
                        # race_id があればリンク化する
                        df_display = msg["df"].copy()
                        col_config = {}
                        if "race_id" in df_display.columns:
                            col_config["race_id"] = st.column_config.LinkColumn(
                                "Race Link",
                                help="netkeibaのレース詳細を開く",
                                display_text="Open netkeiba"
                            )
                            # race_id カラムの値をURLに変換 (様々な型に対応)
                            def to_netkeiba_url(val):
                                if pd.isnull(val): return val
                                try:
                                    # 科学表記や小数点を排除して文字列化
                                    s = str(int(float(val)))
                                    return f"https://db.netkeiba.com/race/{s}/"
                                except:
                                    return val
                            df_display["race_id"] = df_display["race_id"].apply(to_netkeiba_url)

                        st.dataframe(df_display, width='stretch', column_config=col_config)
                    
                    # 的中保存ボタン
                    if msg["role"] == "assistant":
                        if st.button("⭐ お気に入り保存", key=f"save_btn_{i}"):
                            query_msg = st.session_state.kaggle_chat_history[i-1]["content"]
                            if kaggle_chat.save_interaction(query_msg, msg["content"], msg.get("df")):
                                st.success("保存しました")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("保存に失敗しました。data/kaggle_interactions.json の権限等を確認してください。")

        # 4. チャット入力
        if k_prompt := st.chat_input("例: 2018年の三連複人気ランキングを教えて"):
            st.session_state.kaggle_chat_history.append({"role": "user", "content": k_prompt})
            with chat_container:
                with st.chat_message("user"):
                    st.write(k_prompt)
                
                with st.chat_message("assistant"):
                    _spinner_msg = "📦 Kaggle データを初回ダウンロード中（約1〜2分）..." if not kaggle_chat.is_loaded() else "🔍 データを分析中..."
                    with st.spinner(_spinner_msg):
                        ans_text, ans_df = kaggle_chat.ask(k_prompt)
                        st.write(ans_text)
                        if ans_df is not None:
                            st.dataframe(ans_df, width='stretch')
                        st.session_state.kaggle_chat_history.append({
                            "role": "assistant", 
                            "content": ans_text, 
                            "df": ans_df
                        })
                        st.rerun() # ボタンを表示するために再描画


        # Final persistence save at the end of valid execution
        save_betsync_data({
            'bankroll': _ss['bs_bankroll'],
            'init_bet': _ss['bs_init_bet'],
            'target':   _ss['bs_target'],
            'strategy': _ss['bs_strategy'],
            'ticket':   _ss['bs_ticket'],
            'races':    _ss['bs_races']
        })

    except Exception as e:
        st.error(f"⚠️ BetSync エラーが発生しました: {e}")
        st.code(traceback.format_exc())












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
        
        # Domain handle
        _is_nar_in = False
        try:
            if int(str(race_id_input)[4:6]) > 10: _is_nar_in = True
        except: pass
        _dom = "nar.netkeiba.com" if _is_nar_in else "race.netkeiba.com"
        race_url = f"https://{_dom}/race/shutuba.html?race_id={race_id_input}"
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
    from core import history_manager
    from core import history_manager
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
                with c_my: st.button("✅ 実行", on_click=execute_main_race_action, width='stretch', key="main_race_conf_yes")
                with c_mn: st.button("❌ キャンセル", on_click=lambda: st.session_state.update({"main_race_action_confirm": None}), width='stretch', key="main_race_conf_no")

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
        # Determine if we need to fetch fresh data from the web
        # Fetch if analyze button is pressed, OR if it's a new race, OR if df is missing
        must_fetch = analyze_btn or st.session_state.get('tab1_analyzed_id') != race_id_input or st.session_state.get('df') is None
        
        if must_fetch:
            with st.spinner("Fetching data from web..."):
                df = scraper.get_race_data(race_id_input)
                
                # --- [NEW] Fetch detailed shutuba data (Barei, Futan, Weight, etc.) ---
                try:
                    shutuba_extra = scraper.fetch_shutuba_data(race_id_input)
                    if shutuba_extra and df is not None and not df.empty:
                        for umaban, info in shutuba_extra.items():
                            # Find matching horse in df by Umaban
                            umaban_str = str(umaban).lstrip('0') # Handle possible leading zeros
                            mask = df['Umaban'].astype(str).str.lstrip('0') == umaban_str
                            if mask.any():
                                for col, val in info.items():
                                    # Update if current value is placeholder or empty
                                    if col not in df.columns:
                                        df[col] = "-"
                                    
                                    curr_val = str(df.loc[mask, col].iloc[0])
                                    if curr_val in ["-", "", "None", "発走前のため未公開"]:
                                        if val not in ["-", ""]:
                                            df.loc[mask, col] = val
                except Exception as ex_shutuba:
                    st.warning(f"出馬表データの詳細取得に一部失敗しました: {ex_shutuba}")

                # --- [NEW] Fetch Weight from KeibaLab ---
                try:
                    # 競馬ラボ用IDの組み立て (YYYYMMDD + VenueCode + RaceNum)
                    # netkeibaのIDとは形式が異なるため、スクレイパーが抽出した日付を使用
                    meta = df.attrs.get('metadata', {})
                    r_date = meta.get('date_val', datetime.now().strftime("%Y%m%d"))
                    r_venue = str(race_id_input)[4:6]
                    r_num = str(race_id_input)[-2:]
                    lab_race_id = f"{r_date}{r_venue}{r_num}"
                    
                    logger.info(f"[LabFetcher] Converted Netkeiba ID {race_id_input} to KeibaLab ID {lab_race_id}")
                    lab_weights = lab_fetcher.fetch_horse_weights(lab_race_id)
                    if lab_weights and df is not None and not df.empty:
                        if '馬体重' not in df.columns:
                            df['馬体重'] = "-"
                        for umaban, weight_text in lab_weights.items():
                            # 馬番をAPIのキー形式（2桁ゼロ埋め文字列）に強制変換して照合
                            mask = df['Umaban'].astype(str).str.zfill(2) == umaban
                            if mask.any():
                                df.loc[mask, '馬体重'] = weight_text
                                # 指示に基づいたログ形式での成功証明
                                row = df[mask].iloc[0]
                                print(f"[SUCCESS] Umaban {umaban}: Odds={row.get('Odds', 0.0)}, Popularity={row.get('Popularity', 99)}, Weight={weight_text}")
                        logger.info(f"Integrated {len(lab_weights)} weights from KeibaLab as '馬体重' column")
                except Exception as ex_lab:
                    st.warning(f"競馬ラボからの馬体重取得に失敗しました: {ex_lab}")

                st.session_state['tab1_analyzed_id'] = race_id_input
        else:
            df = st.session_state.get('df')

        with st.spinner("Fetching data and calculating indices..."):
            try:
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
                    # Preserve metadata in session state
                    if hasattr(df, 'attrs') and 'metadata' in df.attrs:
                        st.session_state['race_metadata'] = df.attrs['metadata']
                    else:
                        st.session_state['race_metadata'] = {'class': '-', 'weight_rule': '-', 'holding_days': '-', 'weather': '-', 'condition': '-', 'is_handicap': False}
                    
                    # Reset vision apply flag for new race
                    if st.session_state.get('last_race_id') != race_id_input:
                        st.session_state['vision_data_applied'] = True
                        st.session_state['last_race_id'] = race_id_input

                    # --- オッズ・人気未取得 警告バナー (指示忠実: 手入力機能追加) ---
                    _pop_missing = 'Popularity' in df.columns and (pd.to_numeric(df['Popularity'], errors='coerce') >= 99).any()
                    _odds_missing = 'Odds' in df.columns and ((pd.to_numeric(df['Odds'], errors='coerce') <= 0) | (pd.to_numeric(df['Odds'], errors='coerce') >= 9999.0)).any()
                    
                    if _pop_missing or _odds_missing:
                        st.error("🚨 取得エラー：再試行中（またはデータ未発表）")
                        col_ret1, col_ret2 = st.columns([1, 1])
                        with col_ret1:
                            if st.button("🔄 直ちに再試行 (Force Retry)", key="btn_force_retry_odds"):
                                st.session_state['df'] = None # Clear cache
                                st.rerun()
                        with col_ret2:
                            manual_mode = st.toggle("🛠️ 手入力モードを有効化", key="toggle_manual_input")
                        
                        if manual_mode:
                            with st.expander("📝 人気・単勝オッズを手入力する", expanded=True):
                                st.info("下のテーブルで人気・単勝オッズを編集し、「再計算して反映」ボタンを押送してください。")
                                # 編集用データフレーム作成
                                edit_cols = ['Umaban', 'Name', 'Popularity', 'Odds']
                                edit_df = df[edit_cols].copy()
                                edit_df['Popularity'] = pd.to_numeric(edit_df['Popularity'], errors='coerce').fillna(99).astype(int)
                                edit_df['Odds'] = pd.to_numeric(edit_df['Odds'], errors='coerce').fillna(9999.0).astype(float)
                                
                                edited_data = st.data_editor(
                                    edit_df,
                                    key=f"editor_manual_{race_id_input}",
                                    column_config={
                                        "Umaban": st.column_config.NumberColumn("馬番", disabled=True),
                                        "Name": st.column_config.TextColumn("馬名", disabled=True),
                                        "Popularity": st.column_config.NumberColumn("人気", min_value=1, max_value=99),
                                        "Odds": st.column_config.NumberColumn("単勝オッズ", min_value=1.0, max_value=999.0, format="%.1f"),
                                    },
                                    hide_index=True,
                                    use_container_width=True
                                )
                                
                                if st.button("🎯 入力値を反映して再計算", type="primary", use_container_width=True):
                                    for _, row in edited_data.iterrows():
                                        idx = df[df['Umaban'] == row['Umaban']].index
                                        if not idx.empty:
                                            df.at[idx[0], 'Popularity'] = row['Popularity']
                                            df.at[idx[0], 'Odds'] = row['Odds']
                                    
                                    # 関連する計算を再実行
                                    df = calculator.calculate_battle_score(df)
                                    df = calculator.calculate_n_index(df)
                                    st.session_state['df'] = df
                                    st.success("✅ データを反映し、全ての指数を再計算しました。")
                                    st.rerun()

                    # --- [NEW] RACE SUMMARY BLOCK (TOP PRIORITY) ---
                    st.markdown("""
                        <style>
                        .summary-box {
                            background-color: #f8f9fa;
                            padding: 20px;
                            border-radius: 10px;
                            border-left: 5px solid #ff4b4b;
                            margin-bottom: 20px;
                        }
                        .summary-title { font-size: 24px; font-weight: bold; margin-bottom: 5px; }
                        .summary-rank { font-size: 32px; color: #ff4b4b; font-weight: bold; }
                        </style>
                    """, unsafe_allow_html=True)
                    
                    st.markdown("## 🏆 Race Analysis Summary")
                    
                    # --- [NEW] START OF CONDITIONAL DISPLAY ---
                    # --- [PREPARE EVIDENCE DATA] ---
                    meta = st.session_state.get('race_metadata', {})
                    chaos_data = calculator.evaluate_race_chaos_v3(df)
                    rank_color = {"S": "#E63946", "A": "#F4A261", "B": "#2A9D8F", "C": "#457B9D"}.get(chaos_data['rank'], "#333")
                    
                    evidence_list = [
                        {"項目": "クラス", "値": meta.get('class', '-'), "ステータス": "-"},
                        {"項目": "斤量ルール", "値": meta.get('weight_rule', '-'), "ステータス": "⚠️ ハンデ戦: 波乱リスク高" if meta.get('is_handicap') else "✅ 定量/馬齢"},
                    ]
                    
                    # Holding days logic
                    hd = meta.get('holding_days', '-')
                    hd_status = "-"
                    try:
                        if str(hd).isdigit() and int(hd) >= 7: hd_status = "🚩 馬場劣化警告"
                        elif str(hd).isdigit(): hd_status = "✅ 良好"
                    except: pass
                    evidence_list.append({"項目": "開催日数", "値": f"{hd}日目", "ステータス": hd_status})
                    
                    evidence_list.append({"項目": "天候/馬場", "値": f"{meta.get('weather', '-')}/{meta.get('condition', '-')}", "ステータス": "-"})
                    
                    # Existing items
                    evidence_list.extend([
                        {"項目": "1番人気オッズ", "値": f"{df['Odds'].min():.1f}倍" if not df.empty else "-", "ステータス": "🚩 要注意" if (not df.empty and df['Odds'].min() >= 3.5) else "✅ 正常"},
                        {"項目": "要警戒アノマリー数", "値": f"{chaos_data.get('anomaly_count', 0)}件", "ステータス": "⚠️ 検出" if chaos_data.get('anomaly_count', 0) > 0 else "✅ 低"},
                        {"項目": "先行馬密集度", "値": "高" if "先行馬が密集" in chaos_data['reason'] else "中以下", "ステータス": "-"}
                    ])

                    st.markdown(f"""
                        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 10px; border-left: 10px solid {rank_color}; margin-bottom: 20px;">
                            <h1 style="margin: 0; font-size: 36px; color: #333;">Race Rating: 💣 {chaos_data['rank']} (Score: {chaos_data.get('chaos_score', 0):.1f})</h1>
                            <p style="font-size: 18px; color: #555; margin-top: 5px;">判定理由: {chaos_data['reason']}</p>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    # Evidence Table
                    with st.expander("📊 判定根拠エビデンス表", expanded=True):
                        st.table(pd.DataFrame(evidence_list))

                    st.divider()
                    
                    # --- [PRE-CALCULATE SCORES & DERIVED COLUMNS] ---
                    # Move this up so Sniper Logic can use Projected Score
                    import numpy as _np_main
                    course_profile_main = meta.get('course_profile', '')
                    df = calculator.calculate_strength_suitability(df, course_profile_main)
                    
                    def calc_derived_cols(target_df):
                        res = target_df.copy()
                        # 重複マージ防止: 過去の OddsGap カラム(x/yサフィックス等含む)を全削除
                        # また、以前に生成した可能性のある中間/派生カラムを一旦クリアする
                        to_clean = [c for c in res.columns if c.startswith('OddsGap') or c in ['RiskFlags', 'PrevCorners', 'WeightHistory', 'PrevAgari', 'JockeyChange', 'Odds_num']]
                        if to_clean:
                            res = res.drop(columns=to_clean)

                        if 'Popularity' in res.columns and 'Odds' in res.columns:
                            import pandas as _pd_conv
                            gap_df = res.sort_values('Popularity').copy()
                            gap_df['Odds_num'] = _pd_conv.to_numeric(gap_df['Odds'], errors='coerce')
                            gap_df['PrevOdds'] = gap_df['Odds_num'].shift(1)
                            gap_df['OddsGap'] = gap_df.apply(lambda r: "⚠断層" if (r['PrevOdds'] or 0) > 0 and (r['Odds_num'] or 0)/(r['PrevOdds'] or 1) >= 1.5 else "-", axis=1)
                            # ここでマージ
                            res = res.merge(gap_df[['Umaban', 'OddsGap']], on='Umaban', how='left')
                        else:
                            res['OddsGap'] = "-"

                        # Extra data for v2 Dashboard
                        risks, corners, weight_raw, prev_agari, jockey_flag = [], [], [], [], []
                        current_surf = str(res['CurrentSurface'].iloc[0]) if 'CurrentSurface' in res.columns and not res.empty else "芝"

                        for _, row in res.iterrows():
                            p_runs = row.get('PastRuns', [])
                            r_list, c_val, a_val, j_flag = [], "-", "-", "-"

                            # 当日馬体重(増減): scraper の Weight カラムを使用
                            today_w = str(row.get('Weight', ''))
                            if today_w and today_w not in ('', '-', '発走前のため未公開'):
                                w_val = today_w  # e.g. "456(+4)" or "456(-2)"
                            else:
                                w_val = "未公開"

                            if p_runs:
                                last_run = p_runs[0]
                                c_val = last_run.get('Passing', "-")
                                a_val = f"{last_run.get('Agari', 0.0):.1f}" if last_run.get('Agari', 0.0) > 0 else "-"

                                # Jockey change check
                                current_jockey = str(row.get('Jockey', ''))
                                prev_jockey = str(last_run.get('PrevJockey', ''))
                                if current_jockey and prev_jockey and current_jockey != prev_jockey and prev_jockey != "-":
                                    j_flag = "乗替"

                                if 'ダ' in current_surf and not any('ダ' in str(pr.get('Surface', '')) for pr in p_runs): r_list.append("初ダ")
                                try:
                                    last_date = datetime.strptime(last_run.get('Date', '2000.01.01'), "%Y.%m.%d")
                                    if (datetime.now() - last_date).days > 180: r_list.append("休明")
                                except: pass
                            risks.append(", ".join(r_list) if r_list else "-")
                            corners.append(c_val)
                            weight_raw.append(w_val)
                            prev_agari.append(a_val)
                            jockey_flag.append(j_flag)

                        res['RiskFlags'], res['PrevCorners'], res['WeightHistory'], res['PrevAgari'], res['JockeyChange'] = risks, corners, weight_raw, prev_agari, jockey_flag
                        return res
                    
                    df = calc_derived_cols(df)

                    st.divider()

                    # --- RESTORED ODDS MONITORING SECTIONS ---
                    with st.expander("📈 時系列オッズ・詳細分析 (高度な監視機能)", expanded=False):
                        from core.odds_tracker import OddsTracker
                        from core.odds_analyzer import OddsAnalyzer
                        tracker = OddsTracker()
                        analyzer = OddsAnalyzer()
                        
                        st.markdown("#### 📉 Time-Series Change")
                        st.caption("Record Current Odds で最新の状態を保存し、推移を確認できます。")
                        if st.button("🔴 Record Current Odds", help="現在値を記録します", key="btn_record_odds_v3"):
                            count = tracker.track(race_id_input)
                            if count > 0: st.success(f"Logged {count} records!")
                        
                        history_df = tracker.get_history_df(race_id_input)
                        if not history_df.empty:
                            history_df['timestamp'] = pd.to_datetime(history_df['timestamp'])
                            line_chart = alt.Chart(history_df[history_df['odds_type']=='win']).mark_line(point=True).encode(
                                x='timestamp:T', y='odds_value:Q', color='umaban:N'
                            ).interactive()
                            st.altair_chart(line_chart, width='stretch')
                        
                        st.markdown("#### ⚠️ Anomalies Detected")
                        alerts = analyzer.detect_abnormal_odds(df)
                        if alerts:
                            for a in alerts: st.warning(f"馬番 {a['horse_number']}: {a['reason']}")
                        else: st.success("特筆すべき異常は見つかりませんでした。")

                    st.divider()

                    # --- [NEW] 影響率（ウェイト）設定パネル ---
                    _WEIGHTS_FILE = os.path.join(os.path.dirname(__file__), ".score_weights_main.json")
                    _weight_defaults = {
                        "NIndex": 0.0, "UIndex": 0.0, "LaboIndex": 0.0, "SpeedIndex": 0.0, "Popularity": 0.0,
                        "Jockey": 0.0, "Training": 0.0, "Weight": 0.0, "WeightPenalty": -10.0, "WeightCarried": 0.0,
                        "Suitability": 0.0, "AvgAgari": 0.0, "Umaban": 0.0, "AvgPosition": 0.0,
                        "Base": 100.0
                    }
                    if 'score_weights_main' not in st.session_state:
                        if os.path.exists(_WEIGHTS_FILE):
                            try:
                                import json as _json
                                with open(_WEIGHTS_FILE, 'r', encoding='utf-8') as _wf:
                                    _loaded = _json.load(_wf)
                                st.session_state['score_weights_main'] = {**_weight_defaults, **_loaded}
                            except Exception:
                                st.session_state['score_weights_main'] = _weight_defaults.copy()
                        else:
                            st.session_state['score_weights_main'] = _weight_defaults.copy()
                    
                    sw = st.session_state['score_weights_main']
                    for k, v in _weight_defaults.items():
                        if k not in sw: sw[k] = v

                    def _make_sync_slider_sm(key_num, key_sld):
                        def _cb(): st.session_state[key_sld] = st.session_state[key_num] * 100.0
                        return _cb
                    def _make_sync_num_sm(key_sld, key_num):
                        def _cb(): st.session_state[key_num] = st.session_state[key_sld] / 100.0
                        return _cb

                    _W_GROUP1   = [("📈 N指数%",      "NIndex",      "nidx"),
                                   ("📊 U指数%",      "UIndex",      "uidx"),
                                   ("⚡ ｵﾒｶﾞ指数%",   "LaboIndex",   "labo"),
                                   ("💪 強さ(X)%",  "Strength (X)", "strx"),
                                   ("🏎️ ｽﾋﾟｰﾄﾞ指数%", "SpeedIndex",   "spd"),
                                   ("🔥 人気%",       "Popularity",  "pop")]
                    _W_GROUP2   = [("🏇 騎手(10走)%", "Jockey",      "jky"),
                                   ("⏱️ 調教%",       "Training",    "trn"),
                                   ("⚖️ 馬体重%",     "Weight",      "wgt"),
                                   ("⚖️ 馬体増減ペナルティ", "WeightPenalty", "wgtp"),
                                   ("🏋️ 斤量%",       "WeightCarried","wgtc")]
                    _W_GROUP3   = [("🎯 ｺｰｽ適性(Y)%", "Suitability",   "suit"),
                                   ("🚀 上がり3F%",   "AvgAgari",     "agi"),
                                   ("🏁 枠順(馬番)%",  "Umaban",       "uma"),
                                   ("🦁 平均位置取り%", "AvgPosition",  "pos"),
                                   ("基礎戦闘力%",     "Base",         "base")]

                    # --- Preset Management ---
                    PRESETS_FILE = "influence_presets.json"
                    
                    def load_influence_presets():
                        if os.path.exists(PRESETS_FILE):
                            try:
                                with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                                    return json.load(f)
                            except:
                                pass
                        default_presets = {
                            "Standard": {
                                "NIndex": 60, "UIndex": 60, "Base": 100, "Suitability": 80,
                                "SpeedIndex": 80, "Popularity": 30, "Jockey": 40
                            }
                        }
                        try:
                            with open(PRESETS_FILE, "w", encoding="utf-8") as f:
                                import json as _json2
                                _json2.dump(default_presets, f, indent=2, ensure_ascii=False)
                        except: pass
                        return default_presets
                        
                    def _render_weight_group_sm(items, sw, prefix):
                        for label, sw_key, suffix in items:
                            sld_key = f"wsld_{prefix}{suffix}"
                            num_key = f"wnum_{prefix}{suffix}"
                            cur_val = float(sw.get(sw_key, 0.0))
                            
                            display_label = label
                            if cur_val < 0:
                                color_tag = "blue" if sw_key == "WeightPenalty" else "red"
                                display_label += f" :{color_tag}[[逆相関/減点]]"

                            max_val = 0.0 if sw_key == "WeightPenalty" else 100.0
                            min_val = -100.0

                            # Initialize if missing
                            if sld_key not in st.session_state: st.session_state[sld_key] = float(cur_val)
                            
                            val_num = max(min_val/100.0, min(max_val/100.0, cur_val / 100.0))
                            if num_key not in st.session_state: st.session_state[num_key] = float(val_num)

                            c1, c2 = st.columns([2, 1])
                            with c1:
                                st.slider(display_label, min_val, max_val, step=1.0, key=sld_key, on_change=_make_sync_num_sm(sld_key, num_key))
                            with c2:
                                st.number_input("", min_val/100.0, max_val/100.0, step=0.01, key=num_key, on_change=_make_sync_slider_sm(num_key, sld_key), label_visibility="collapsed")
                            
                            # Keep sw updated
                            sw[sw_key] = float(st.session_state.get(num_key, cur_val/100.0)) * 100.0

                    with st.expander("📊 プロ設定：総合影響率（ウェイト）設定", expanded=True):
                        with st.container(border=True):
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.markdown("#### 📈 能力・指数")
                                _render_weight_group_sm(_W_GROUP1, sw, "sm_g1")
                            with col2:
                                st.markdown("#### 👤 人間・状態")
                                _render_weight_group_sm(_W_GROUP2, sw, "sm_g2")
                            with col3:
                                st.markdown("#### 🎯 適性・展開")
                                _render_weight_group_sm(_W_GROUP3, sw, "sm_g3")

                            total_w = sum(sw.values())
                            if total_w > 0:
                                st.info(f"💡 合計: **{total_w:.2f}%**")
                            else:
                                st.success(f"✅ 全て 0%（戦闘力のみのプレーン状態です）")
                                
                        st.caption("📝 **[予測スコア計算式]** ＝ BattleScore(基礎戦闘力) × 基本% ＋ Σ(各ボーナス素点[0-100] × 各影響率%)")

                        st.session_state['score_weights_main'] = sw
                        _sc1, _sc2 = st.columns([1, 1])
                        with _sc1:
                            if st.button("💾 影響率を保存（全レースに適用）", key="btn_save_weights_main_sp"):
                                import json as _json
                                try:
                                    with open(_WEIGHTS_FILE, 'w', encoding='utf-8') as _wf:
                                        _json.dump(sw, _wf, ensure_ascii=False, indent=2)
                                    st.success("✅ 保存しました。次回以降自動適用されます。")
                                except Exception as _e:
                                    st.error(f"保存に失敗しました: {_e}")
                        with _sc2:
                            if st.button("🔄 この影響率で再計算して反映", type="primary", key="btn_recalc_weights_main_sp"):
                                # Recalculate everything up to Projected Score
                                df = calculator.calculate_battle_score(df)
                                df = calculator.calculate_n_index(df)
                                df = calculator.calculate_strength_suitability(df, course_profile_main)
                                st.session_state['df'] = df
                                st.rerun()

                    # === プロフェッショナル・スコアリングロジック ===
                    # 1. 事前に全指標の最小値/最大値を計算（正規化用）
                    _norm_stats = {}
                    _metric_keys = {
                        'NIndex': True, 'UIndex': True, 'LaboIndex': True, 'SpeedIndex': True, 
                        'Strength (X)': True,
                        'Popularity': False, # 小さいほど良い
                        'TrainingScore': True,
                        'WeightDiff': True,
                        'WeightCarried': False, # 小さいほど良い（一般的に）
                        'Suitability (Y)': True,
                        'AvgAgari': False, # 小さいほど良い
                        'Umaban': True,
                        'AvgPosition': False # 小さいほど良い
                    }
                    
                    # 特殊抽出
                    df['WeightDiff'] = df['WeightHistory'].str.extract(r'\(([+-]?\d+)\)').iloc[:,0].astype(float).fillna(0)
                    # カッコ内の増減値（+20 や -12）のみを抽出。ない場合は 0。

                    for m_key, higher_is_better in _metric_keys.items():
                        col = m_key if m_key in df.columns else None
                        if col:
                            v_series = pd.to_numeric(df[col], errors='coerce').dropna()
                            if not v_series.empty:
                                _norm_stats[m_key] = {'min': v_series.min(), 'max': v_series.max(), 'higher': higher_is_better}

                    def _calc_pro_scores(row):
                        bonuses = {}
                        bonus_details = []
                        
                        # 基礎点
                        base_pts = float(row.get('BattleScore', 0) or 0)
                        
                        # 各項目のスコア化と重み付け
                        for m_key, sw_key in [
                            ('NIndex', 'NIndex'), ('UIndex', 'UIndex'), ('LaboIndex', 'LaboIndex'), 
                            ('SpeedIndex', 'SpeedIndex'), ('Strength (X)', 'Strength (X)'), ('Popularity', 'Popularity'),
                            ('TrainingScore', 'Training'), ('WeightDiff', 'Weight'),
                            ('WeightCarried', 'WeightCarried'), ('Suitability (Y)', 'Suitability'),
                            ('AvgAgari', 'AvgAgari'), ('Umaban', 'Umaban'), ('AvgPosition', 'AvgPosition')
                        ]:
                            col_name = m_key if m_key in row else None
                            raw_val = float(row.get(col_name, 0) or 0) if col_name else 0
                            
                            score = 50.0 # デフォルト
                            if m_key in _norm_stats:
                                s = _norm_stats[m_key]
                                if s['max'] > s['min']:
                                    if s['higher']:
                                        score = 100.0 * (raw_val - s['min']) / (s['max'] - s['min'])
                                    else:
                                        score = 100.0 * (s['max'] - raw_val) / (s['max'] - s['min'])
                                else:
                                    score = 100.0 if raw_val > 0 else 0.0
                            
                            bonus_val = score * (sw.get(sw_key, 0.0) / 100.0)
                            bonuses[sw_key] = bonus_val
                            if bonus_val != 0:
                                label_txt = label_map_short.get(sw_key, sw_key)
                                bonus_details.append(f"{label_txt}:{bonus_val:+.1f}")

                        # 騎手(特例)
                        j_pts = 0
                        past = row.get('PastRuns', [])
                        for r in past[:10]:
                            rnk = r.get('Rank', 99)
                            if rnk == 1: j_pts += 10
                            elif rnk == 2: j_pts += 7
                            elif rnk == 3: j_pts += 5
                            elif rnk in (4, 5): j_pts += 2
                        j_score = min(100.0, float(j_pts)) if past else 50.0
                        j_bonus = j_score * (sw.get('Jockey', 0.0) / 100.0)
                        bonuses['Jockey'] = j_bonus
                        if j_bonus != 0:
                            bonus_details.append(f"騎手:+{j_bonus:.1f}")

                        total_bonus = sum(bonuses.values())
                        
                        # --- Horse Weight Change Penalty ---
                        w_diff = abs(float(row.get('WeightDiff', 0) or 0))
                        w_penalty_w = sw.get('WeightPenalty', 0.0) / 100.0 # e.g. -0.10
                        w_penalty_score = w_diff * w_penalty_w
                        if w_penalty_score != 0:
                            total_bonus += w_penalty_score
                            bonus_details.append(f"馬体:{w_penalty_score:+.1f}")
                        final_score = (base_pts * (sw.get('Base', 100.0) / 100.0)) + total_bonus
                        
                        return pd.Series({
                            **{f"{k}_Bonus": v for k, v in bonuses.items()},
                            'Projected Score': round(final_score, 1),
                            'ボーナス詳細': ", ".join(bonus_details) if bonus_details else "-"
                        })

                    label_map_short = {
                        'NIndex': 'N指', 'UIndex': 'U指', 'LaboIndex': 'オメガ', 'SpeedIndex': 'スピ',
                        'Popularity': '人気', 'Training': '調教', 'Weight': '馬体', 'WeightCarried': '斤量',
                        'Suitability': '適性', 'AvgAgari': '末脚', 'Umaban': '枠', 'AvgPosition': '位置'
                    }
                    
                    # 適用
                    res_df = df.apply(_calc_pro_scores, axis=1)
                    for c in res_df.columns:
                        df[c] = res_df[c]
                    
                    # チャート用データ
                    st.session_state['current_bonus_df'] = df.copy()
                            
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

                    # Format Agari (34.5 (1位) 🚀)
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

                    view_df['AvgAgari'] = view_df.apply(fmt_agari, axis=1)

                    # Format Position (2.5 🦁)
                    def fmt_pos(row):
                        p = row.get('AvgPosition', 99.9)
                        trusted = row.get('PosTrust', False)
                    
                        if p >= 99.0: return "-"
                        icon = " 🦁" if p <= 5.0 else ""
                        return f"{p:.1f}{icon}"
                    
                    view_df['AvgPosition'] = view_df.apply(fmt_pos, axis=1)

                    view_df['Rank'] = range(1, len(view_df) + 1)

                    # Mask sentinel values for display (99=未取得人気, 9999.0=未取得オッズ)
                    if 'Popularity' in view_df.columns:
                        view_df['Popularity'] = view_df['Popularity'].apply(
                            lambda x: '-' if (pd.isna(x) or (isinstance(x, (int, float)) and x >= 99)) else str(int(x))
                        )
                    if 'Odds' in view_df.columns:
                        view_df['Odds'] = view_df['Odds'].apply(
                            lambda x: '-' if (pd.isna(x) or (isinstance(x, (int, float)) and x >= 9999.0)) else f'{x:.1f}'
                        )

                    # Merge previous screenshot columns with latest advanced columns
                    cols = ['Rank', 'Umaban', 'Popularity', 'Odds', 'OddsGap', 'SexAge', 'WeightHistory', 'WeightCarried', 'Trainer', 'Bloodline', 'Jockey', 'JockeyChange', 'Name', 
                            'Projected Score', 'ボーナス詳細', 'NIndex', 'BattleScore', 'Strength (X)', 'Suitability (Y)', 
                            'SpeedIndex', 'AvgAgari', 'AvgPosition', 'Alert', 'RiskFlags']
                    view_df = view_df[[c for c in cols if c in view_df.columns]]

                    # --- Column order persistence (user_prefs.json) ---
                    import json as _json_sra
                    _prefs_path_sra = os.path.join(os.getcwd(), "user_prefs.json")
                    _saved_sra = []
                    try:
                        with open(_prefs_path_sra, 'r', encoding='utf-8') as _f:
                            _saved_sra = _json_sra.load(_f).get('single_race_col_order', [])
                    except: pass

                    _all_cols = list(view_df.columns)

                    _col_label_map = {
                        "Rank": "順位", "Umaban": "馬番", "Popularity": "人気",
                        "Odds": "単勝オッズ", "OddsGap": "オッズ断層",
                        "SexAge": "性別/年齢", "WeightHistory": "当日馬体重(増減)",
                        "WeightCarried": "斤量", "Trainer": "厩舎",
                        "Bloodline": "血統(父/母父)", "Jockey": "騎手",
                        "JockeyChange": "乗替", "Name": "馬名",
                        "Projected Score": "⭐予測スコア", "ボーナス詳細": "ボーナス内訳", "NIndex": "N指数",
                        "BattleScore": "🔥総合戦闘力",
                        "Strength (X)": "💪強さ(X)", "Suitability (Y)": "🎯適性(Y)",
                        "SpeedIndex": "スピード指数", "AvgAgari": "上がり3F(順位)",
                        "AvgPosition": "平均位置取り", "Alert": "アラート",
                        "RiskFlags": "不安要素",
                    }

                    # Restore saved order if available
                    _default_cols = _all_cols[:]
                    if _saved_sra:
                        _valid_saved = [c for c in _saved_sra if c in _all_cols]
                        if _valid_saved:
                            _default_cols = _valid_saved

                    _display_to_col = {_col_label_map.get(c, c): c for c in _all_cols}
                    _col_to_display = {c: _col_label_map.get(c, c) for c in _all_cols}
                    _all_display = [_col_to_display[c] for c in _all_cols]
                    _default_display = [_col_to_display[c] for c in _default_cols]

                    _tl_col1, _tl_col2 = st.columns([1, 4])
                    with _tl_col1:
                        with st.popover("⚙ 列順設定"):
                            st.caption("選択順が左→右の表示順になります")
                            _disp_sel = st.multiselect(
                                "表示する列を選択",
                                options=_all_display,
                                default=_default_display,
                                key="sra_col_order_sel",
                            )
                    with _tl_col2:
                        csv = view_df.to_csv(index=False).encode('utf-8-sig')
                        st.download_button(
                            label="📥 CSV出力",
                            data=csv,
                            file_name=f"ranking_table_{race_id_input}.csv",
                            mime="text/csv",
                            key="btn_download_ranking_csv"
                        )

                    _col_sel = [_display_to_col[d] for d in _disp_sel if d in _display_to_col]
                    if _col_sel:
                        view_df = view_df[[c for c in _col_sel if c in view_df.columns]]
                    # Save column order
                    try:
                        try:
                            with open(_prefs_path_sra, 'r', encoding='utf-8') as _f:
                                _p = _json_sra.load(_f)
                        except: _p = {}
                        _p['single_race_col_order'] = _col_sel if _col_sel else _all_cols
                        with open(_prefs_path_sra, 'w', encoding='utf-8') as _f:
                            _json_sra.dump(_p, _f, ensure_ascii=False, indent=2)
                    except: pass

                    column_config = {
                        "Rank": st.column_config.NumberColumn("Rank"),
                        "Umaban": st.column_config.NumberColumn("馬番"),
                        "Popularity": st.column_config.TextColumn("人気"),
                        "Odds": st.column_config.TextColumn("単勝オッズ"),
                        "OddsGap": st.column_config.TextColumn("オッズ断層"),
                        "SexAge": st.column_config.TextColumn("性別/年齢"),
                        "WeightHistory": st.column_config.TextColumn("当日馬体重(増減)"),
                        "WeightCarried": st.column_config.TextColumn("斤量"),
                        "Trainer": st.column_config.TextColumn("Trainer"),
                        "Bloodline": st.column_config.TextColumn("血統(父/母父)"),
                        "Jockey": st.column_config.TextColumn("騎手"),
                        "JockeyChange": st.column_config.TextColumn("乗替"),
                        "Name": st.column_config.TextColumn("馬名"),
                        "Projected Score": st.column_config.NumberColumn("⭐予測スコア", format="%.1f"),
                        "ボーナス詳細": st.column_config.TextColumn("ボーナス内訳"),
                        "NIndex": st.column_config.NumberColumn("N指数", format="%.1f"),
                        "BattleScore": st.column_config.NumberColumn("🔥 総合戦闘力", format="%.1f"),
                        "Strength (X)": st.column_config.NumberColumn("💪 強さ(X)", format="%.0f", help="netkeiba タイム指数ベースの偏差能力 (最高100)"),
                        "Suitability (Y)": st.column_config.NumberColumn("🎯 適性(Y)", format="%.0f"),
                        "SpeedIndex": st.column_config.NumberColumn("スピード指数 (旧)", format="%.1f"),
                        "AvgAgari": st.column_config.TextColumn("上がり3F (順位)"),
                        "AvgPosition": st.column_config.TextColumn("平均位置取り"),
                        "Alert": st.column_config.TextColumn("Alert"),
                        "RiskFlags": st.column_config.TextColumn("不安要素"),
                    }

                    try:
                        def color_battlescore(s):
                            # 絶対値に基づいた色分けに変更 (ユーザー要望: 戦闘力別に色を変える)
                            colors = []
                            for v in s:
                                try:
                                    val = float(v)
                                    if val >= 80: colors.append("background-color: #d9480f; color: white; font-weight: bold") # 高能力(赤)
                                    elif val >= 65: colors.append("background-color: #ebfbee; color: #2b8a3e; font-weight: bold") # 標準(緑)
                                    else: colors.append("background-color: #1864ab; color: white; font-weight: bold") # 低め(青)
                                except: colors.append("")
                            return colors

                        def color_rank(s):
                            # Yellow for top 5, Dark for others
                            colors = []
                            for v in s:
                                try:
                                    r = int(v)
                                    if 1 <= r <= 5: colors.append("background-color: #fab005; color: black; font-weight: bold")
                                    else: colors.append("background-color: #2b2f32; color: #adb5bd; font-weight: bold")
                                except: colors.append("")
                            return colors

                        def color_advanced_metrics(s):
                            # Subtle blue for specialized indices
                            return ["background-color: #f1f3f5; color: #495057;" for _ in s]

                        def color_projected_score(s):
                            # Light pink for Predicted Score
                            return ["background-color: #fff0f6; color: #c01e5a; font-weight: bold;" for _ in s]

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
                        if 'BattleScore' in view_df.columns:
                            styled_df = styled_df.apply(color_battlescore, axis=0, subset=['BattleScore'])
                        if 'Rank' in view_df.columns:
                            styled_df = styled_df.apply(color_rank, axis=0, subset=['Rank'])
                        
                        if 'Projected Score' in view_df.columns:
                            styled_df = styled_df.apply(color_projected_score, axis=0, subset=['Projected Score'])

                        advanced_cols = [c for c in ['NIndex', 'Strength (X)', 'Suitability (Y)', 'SpeedIndex'] if c in view_df.columns]
                        if advanced_cols:
                            styled_df = styled_df.apply(color_advanced_metrics, axis=0, subset=advanced_cols)
                        
                        if 'Alert' in view_df.columns:
                            styled_df = styled_df.apply(color_alert, axis=0, subset=['Alert'])

                        def color_oddsgap(s):
                            return ["color: red; font-weight: bold;" if "断層" in str(v) else "" for v in s]
                        if 'OddsGap' in view_df.columns:
                            styled_df = styled_df.apply(color_oddsgap, axis=0, subset=['OddsGap'])
                        
                        st.dataframe(styled_df, column_config=column_config, width='stretch', hide_index=True)
                        
                        # --- [NEW] ボーナス内訳の可視化 (Top 5) ---
                        if 'current_bonus_df' in st.session_state:
                            b_df = st.session_state['current_bonus_df'].sort_values('Projected Score', ascending=False).head(5)
                            bonus_cols = [f"{k}_Bonus" for k in label_map_short.keys()] + ['Jockey_Bonus']
                            # 有効な（0でない）ボーナスカラムのみ抽出
                            active_cols = [c for c in bonus_cols if c in b_df.columns and b_df[c].sum() != 0]
                            
                            if active_cols:
                                with st.expander("📈 上位5頭のボーナス加算内訳チャート", expanded=False):
                                    st.markdown("戦闘力(Base)以外に加算された各種ボーナス要素の比重を可視化しています。")
                                    chart_df = b_df.melt(id_vars=['Name'], value_vars=active_cols,
                                                         var_name='BonusType', value_name='Points')
                                    # 日本語ラベルに変換
                                    inv_map = {f"{k}_Bonus": v for k, v in label_map_short.items()}
                                    inv_map['Jockey_Bonus'] = '騎手(直近)'
                                    chart_df['Indicator'] = chart_df['BonusType'].map(inv_map)
                                    
                                    import altair as alt
                                    chart = alt.Chart(chart_df).mark_bar().encode(
                                        x=alt.X('Points:Q', title="加算ポイント"),
                                        y=alt.Y('Name:N', sort='-x', title="馬名"),
                                        color=alt.Color('Indicator:N', legend=alt.Legend(title="指標")),
                                        tooltip=['Name', 'Indicator', 'Points']
                                    ).properties(height=300)
                                    st.altair_chart(chart, use_container_width=True)
                                    
                    except Exception as e:
                        st.warning(f"Display Error: {e}")
                        st.dataframe(view_df, hide_index=True)

                    # --- RESURRECTED: Composite Chart (Dual-Axis with Altair) ---
                    st.subheader("✨ Index Analysis Chart")
                    import altair as alt
                    
                    # TotalScore_For_Chart がなければ BattleScore で代替
                    chart_src = df.copy()
                    if 'TotalScore_For_Chart' not in chart_src.columns:
                        score_col_fallback = 'BattleScore' if 'BattleScore' in chart_src.columns else 'OguraIndex'
                        chart_src['TotalScore_For_Chart'] = chart_src.get(score_col_fallback, 0)
                    
                    # OguraIndex / SpeedIndex がなければ 0 で補完
                    for _c in ['OguraIndex', 'SpeedIndex']:
                        if _c not in chart_src.columns:
                            chart_src[_c] = 0.0
                    
                    cols_to_keep = ['Name', 'OguraIndex', 'SpeedIndex', 'TotalScore_For_Chart']
                    if 'Odds' in chart_src.columns:
                        cols_to_keep.append('Odds')
                    
                    chart_df = chart_src[[c for c in cols_to_keep if c in chart_src.columns]].copy()
                    
                    if 'Odds' in chart_df.columns:
                        chart_df['Odds'] = pd.to_numeric(chart_df['Odds'], errors='coerce').fillna(0)
                    
                    # Melt dataframe for stacked bar chart
                    id_vars = ['Name', 'TotalScore_For_Chart']
                    if 'Odds' in chart_df.columns:
                        id_vars.append('Odds')
                    
                    melted_df = chart_df.melt(id_vars=[v for v in id_vars if v in chart_df.columns],
                                              value_vars=[v for v in ['OguraIndex', 'SpeedIndex'] if v in chart_df.columns],
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
                    
                    st.altair_chart(composite_chart, width='stretch')
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
                        score_col_sc = 'Projected Score' if 'Projected Score' in df_sc.columns else 'BattleScore'
                        df_sc['Old Rank'] = df_sc['BattleScore'].rank(ascending=False, method='min').astype(int)
                        # Avoid KeyError if Projected Score is missing
                        df_sc['New Rank'] = df_sc[score_col_sc].rank(ascending=False, method='min').astype(int)
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
                        pts_m = base_m.mark_circle(size=3500, opacity=0.9).encode(
                            color=alt.Color('BattleScore:Q', 
                                          scale=alt.Scale(scheme='viridis', domain=[50, 100]), 
                                          legend=alt.Legend(title="戦闘力")),
                            tooltip=['Umaban', 'Name', 'Strength (X)', 'Suitability (Y)', 'Projected Score', 'BattleScore', 'Trend']
                        )
                        num_m  = base_m.mark_text(align='center', baseline='middle', dy=-5, color='white', fontWeight='bold', fontSize=14).encode(text='Umaban:N')
                        name_m = base_m.mark_text(align='center', baseline='top', dy=30, color='#222', fontWeight='bold', fontSize=11).encode(text='Name:N')
                    
                        # Diagonal line (buy zone)
                        diag_m_df = pd.DataFrame({'x': [0, 100], 'y': [75, 25]})
                        diag_m = alt.Chart(diag_m_df).mark_line(strokeDash=[8, 6], color='#888888', strokeWidth=2, opacity=0.7).encode(x='x:Q', y='y:Q')
                        zone_m_df = pd.DataFrame({'x': [8], 'y': [95], 'label': ['◎ 強い×合う（推奨ゾーン）']})
                        zone_m = alt.Chart(zone_m_df).mark_text(align='left', color='#cc2222', fontSize=12, fontWeight='bold').encode(x='x:Q', y='y:Q', text='label:N')
                    
                        st.altair_chart((diag_m + zone_m + pts_m + num_m + name_m).properties(height=550).interactive(), width='stretch')
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
                        # 🥊 Direct Match Network (Premium Structural Layout)
                        st.markdown("""
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                            <h3 style="margin:0; font-size:1.4rem;">Direct Match Network</h3>
                            <span style="background-color:#e1f5fe; color:#03a9f4; padding:4px 12px; border-radius:15px; font-size:0.75rem; font-weight:bold; letter-spacing:0.5px;">LIVE DATA</span>
                        </div>
                        """, unsafe_allow_html=True)

                        # Legends
                        st.markdown(f"""
                        <div style="display:flex; justify-content:center; gap:20px; font-size:0.85rem; color:#666; margin-bottom:15px;">
                            <span><span style="color:#ff6b6b;">●</span> Top 5 (Highly Rec)</span>
                            <span><span style="color:#2b8a3e;">●</span> Others</span>
                            <span><span style="color:#339af0;">●</span> Bottom 5 (Caution)</span>
                        </div>
                        """, unsafe_allow_html=True)

                        # Pre-calculate top/bottom names for coloring (Fix for NameError)
                        sort_col = 'BattleScore' if 'BattleScore' in df.columns else df.columns[0]
                        temp_sorted = df.sort_values(by=sort_col, ascending=False)
                        top_5_names = temp_sorted.head(5)['Name'].tolist()
                        bot_5_names = temp_sorted.tail(5)['Name'].tolist()

                        # Construct DOT string (LR Layout - User's favorite)
                        dot = 'digraph {'
                        dot += 'rankdir=LR;'
                        dot += 'nodesep=1.2;'
                        dot += 'ranksep=1.6;'
                        dot += 'bgcolor="transparent";'
                        dot += 'node [fontname="Meiryo", fontsize=12, shape=circle, style="filled", fixedsize=true, width=1.2, margin=0, penwidth=2.5];'
                        dot += 'edge [fontname="Meiryo", fontsize=10, color="#555555", arrowsize=0.8, penwidth=1.5];'
                        
                        relevant_horse_names = set()
                        for w, l, _ in matches:
                            relevant_horse_names.add(w)
                            relevant_horse_names.add(l)

                        for _, row in df.iterrows():
                            name = row['Name']
                            if name not in relevant_horse_names: continue
                            n_color, border_color, font_color = "#c3fae8", "#51cf66", "#2b8a3e" # Default Green
                            if name in top_5_names:
                                n_color, border_color, font_color = "#fff5f5", "#ff6b6b", "#c92a2a" # Red
                            elif name in bot_5_names:
                                n_color, border_color, font_color = "#e7f5ff", "#339af0", "#1971c2" # Blue

                            umaban = row['Umaban']
                            label = f'<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0"><TR><TD><B><FONT POINT-SIZE="14" COLOR="{font_color}">{name}</FONT></B></TD></TR><TR><TD><FONT POINT-SIZE="8" COLOR="#666666">UM:{umaban}</FONT></TD></TR></TABLE>>'
                            dot += f'"{name}" [label={label}, fillcolor="{n_color}", color="{border_color}"];'

                        unique_edges = set()
                        for w, l, details in matches:
                            if current_surf and (current_surf not in details.get('Surface', '')): continue
                            edge_key = (w, l)
                            if edge_key not in unique_edges:
                                dot += f'"{w}" -> "{l}" [label="WON", fontcolor="#555555", style="dashed", color="#555555"];'
                                unique_edges.add(edge_key)
                        dot += '}'

                        import base64
                        from streamlit.components.v1 import html
                        # Use escaped backslashes for JS safety
                        b64_dot = base64.b64encode(dot.encode('utf-8')).decode('utf-8')

                        html_code = f"""
                        <style>
                            #graph-container {{
                                width: 100%; height: 750px; background-color: #ffffff;
                                border: 1px solid #eeeeee; border-radius: 12px;
                                position: relative; overflow: hidden;
                                box-shadow: 0 4px 15px rgba(0,0,0,0.05);
                                cursor: grab;
                            }}
                            #svg-content svg {{ width: 100%; height: 100%; }}
                            .zoom-controls {{
                                position: absolute; top: 25px; right: 25px;
                                display: flex; flex-direction: column; gap: 12px; z-index: 1000;
                            }}
                            .zoom-btn {{
                                width: 50px; height: 50px; background: rgba(255, 255, 255, 0.98);
                                border: 1px solid #ddd; border-radius: 12px;
                                display: flex; align-items: center; justify-content: center;
                                font-size: 28px; font-weight: bold; cursor: pointer;
                                box-shadow: 0 6px 16px rgba(0,0,0,0.12);
                                user-select: none; transition: all 0.2s; color: #333;
                            }}
                            .zoom-btn:hover {{ background: #f8f8f8; box-shadow: 0 8px 24px rgba(0,0,0,0.2); transform: translateY(-2px); }}
                            .zoom-btn:active {{ transform: scale(0.92); }}
                            .reset-btn {{ font-size: 11px; }}
                            #instructions {{
                                position: absolute; bottom: 15px; left: 20px; font-size: 13px; color: #666;
                                pointer-events: none; background: rgba(255,255,255,0.9);
                                padding: 8px 16px; border-radius: 8px; border: 1px solid #ddd;
                            }}
                        </style>
                        <div id="graph-container">
                            <div class="zoom-controls">
                                <div class="zoom-btn" id="btn-zoom-in">＋</div>
                                <div class="zoom-btn" id="btn-zoom-out">－</div>
                                <div class="zoom-btn reset-btn" id="btn-reset">RESET</div>
                            </div>
                            <div id="svg-content" style="width:100%; height:100%; text-align:center; display:flex; align-items:center; justify-content:center;">
                                <div style="color:#888;">📊 グラフを構築中... (リロードで解決する場合があります)</div>
                            </div>
                            <div id="instructions">💡 マウスホイールでズーム | ドラッグで移動 | 空白ダブルクリックでリセット</div>
                        </div>

                        <script src="https://unpkg.com/@hpcc-js/wasm@1.14.1/dist/index.min.js"></script>
                        <script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>
                        <script>
                            async function init() {{
                                try {{
                                    const dot = decodeURIComponent(escape(window.atob("{b64_dot}")));
                                    const hpccWasm = window["@hpcc-js/wasm"];
                                    
                                    // Render DOT to SVG using WASM
                                    const svgString = await hpccWasm.graphviz.layout(dot, "svg", "dot");
                                    
                                    const container = document.getElementById("svg-content");
                                    container.innerHTML = svgString;
                                    
                                    const svgElement = container.querySelector("svg");
                                    svgElement.setAttribute("width", "100%");
                                    svgElement.setAttribute("height", "100%");

                                    // Add Pan & Zoom (User's favorite interaction)
                                    const panZoom = svgPanZoom(svgElement, {{
                                        zoomEnabled: true,
                                        controlIconsEnabled: false,
                                        fit: true,
                                        center: true,
                                        minZoom: 0.1,
                                        maxZoom: 20
                                    }});

                                    document.getElementById('btn-zoom-in').onclick = () => panZoom.zoomIn();
                                    document.getElementById('btn-zoom-out').onclick = () => panZoom.zoomOut();
                                    document.getElementById('btn-reset').onclick = () => {{ panZoom.resetZoom(); panZoom.center(); }};
                                    
                                    const outer = document.getElementById("graph-container");
                                    outer.ondblclick = () => {{ panZoom.resetZoom(); panZoom.center(); }};
                                    outer.onmousedown = () => outer.style.cursor = "grabbing";
                                    outer.onmouseup = () => outer.style.cursor = "grab";

                                }} catch (e) {{
                                    console.error("Layout Error:", e);
                                    document.getElementById("svg-content").innerHTML = '<div style="color:#e03131;">グラフ描画エラーが発生しました。</div>';
                                }}
                            }}

                            // Wait for libs
                            if (window["@hpcc-js/wasm"]) {{ init(); }}
                            else {{ window.addEventListener("load", init); }}
                        </script>
                        """
                        html(html_code, height=770)

                        # Recent Match History Cards
                        st.markdown("<h4 style='margin-top:20px; margin-bottom:15px; color:#333;'>Recent Match History</h4>", unsafe_allow_html=True)
                        
                        # Process matches for history display (Top 5 unique recent)
                        history_matches = []
                        seen_matches = set()
                        for w, l, details in sorted(matches, key=lambda x: x[2].get('Date', ''), reverse=True):
                            key = f"{w}_{l}_{details.get('Date','')}"
                            if key not in seen_matches:
                                history_matches.append((w, l, details))
                                seen_matches.add(key)
                            if len(history_matches) >= 5: break

                        for winner, loser, d in history_matches:
                            date_str = d.get('Date', 'Unknown Date')
                            r_name = d.get('RaceName', 'Unknown Race')
                            venue = d.get('Venue', '')
                            
                            # Find the horse being "analyzed" - prioritizing winner as "WIN" card if target
                            # In this view, we'll just show the cards as "Winner vs Loser"
                            st.markdown(f"""
                            <div style="background-color:white; border-radius:12px; padding:15px; margin-bottom:10px; border:1px solid #eee; display:flex; align-items:center; justify-content:space-between; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
                                <div style="display:flex; align-items:center;">
                                    <div style="background-color:#ebfbee; color:#2b8a3e; width:45px; height:45px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:bold; margin-right:15px; font-size:0.8rem;">WIN</div>
                                    <div>
                                        <div style="font-weight:bold; color:#333; font-size:1rem;">{winner} <span style="color:#888; font-weight:normal; font-size:0.8rem;">vs {loser}</span></div>
                                        <div style="color:#666; font-size:0.75rem;">{venue} {r_name}</div>
                                    </div>
                                </div>
                                <div style="text-align:right;">
                                    <div style="font-weight:bold; color:#333; font-size:0.8rem;">Head-to-Head</div>
                                    <div style="color:#999; font-size:0.7rem;">{date_str}</div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                         
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

                        if bot_5_names:
                            # Show the horses that are being mathematically excluded
                            for name in bot_5_names:
                                r = df[df['Name'] == name]
                                if not r.empty:
                                    row = r.iloc[0]
                                    score_val = row.get(sort_col, 0.0)
                                    st.markdown(f"**{row['Umaban']} - {name}** (予測スコア: {float(score_val):.1f})")
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

                    # --- Save Area (History) ---
                    st.divider()
                    st.subheader("💾 分析結果の保存")
                    col_save1, col_save2 = st.columns([2, 1])
                    with col_save1:
                        memo_val = st.text_input("📝 レースメモ・備忘録 (History & Reviewタブに保存されます)", key="memo_val_main", placeholder="例: 差し有利な馬場、次走期待の穴馬など")
                    
                    with col_save2:
                        st.write("") # Adjust alignment
                        st.write("") 
                        if st.button("✨ この分析内容を履歴に保存", type="primary", width='stretch'):
                            if 'df' in st.session_state:
                                df_to_save = st.session_state['df']
                                # Get race name from session state or placeholder
                                rname = st.session_state.get('race_name_main', race_id_input)
                                
                                success = history_manager.save_race_data(
                                    race_id=race_id_input,
                                    race_name=rname,
                                    df=df_to_save,
                                    memo=memo_val
                                )
                                if success:
                                    st.success(f"✅ レースID {race_id_input} の分析結果を保存しました！")
                                else:
                                    st.error("保存に失敗しました。")
                            else:
                                st.warning("分析データがありません。先に分析を実行してください。")

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
                        
                        # race_pattern の代わりに波乱度 (chaos_rank) を使用
                        _chaos_rank = calculator.evaluate_race_chaos_v2(df).get('rank', 'B')
                        if _chaos_rank in ['A', 'S']:
                            st.html("""
                            <div style="background-color: #3d0000; border: 3px solid #ff4500; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 0 30px #ff450077;">
                                <h3 style="color: #ffff00; text-align: center; margin-bottom: 5px; font-weight: 900; letter-spacing: 2px;">🚨 【荒れ予想専用】あなた独自の軸2頭 ＋ 中穴 特殊狙い 🚨</h3>
                                <p style="color: #ffffff; text-align: center; margin-top: 0; font-size: 1.1em; font-weight: bold;">このレースは難易度がA/S判定のため、自動的に高配当特化の「選択した軸2頭 ＋ その他の全馬」の組み合わせに切り替わりました。</p>
                            </div>
                            """)
                        else:
                            st.subheader("🎯 指数上位＋推奨穴馬の最適買い目")
                            st.caption("予測スコア上位5頭に「推奨穴馬（🔥）」を加え、期待値上位の買い目を抽出します。トリガミを防ぐ資金管理も自動計算します。")
                            
                        _rec_cache_key = f"sanrenpuku_odds_{race_id_input}"

                        @st.cache_data(ttl=120, show_spinner=False)
                        def _fetch_sanrenpuku_cached(_race_id: str):
                            return scraper.fetch_sanrenpuku_odds(_race_id)

                        if st.button("🎯 推奨買い目を取得・更新", key="btn_fetch_san_recs"):
                            _fetch_sanrenpuku_cached.clear()  # 古いキャッシュをクリア
                            with st.spinner("3連複オッズ取得中..."):
                                _fetched = _fetch_sanrenpuku_cached(race_id_input)
                                st.caption(f"取得件数: {len(_fetched) if _fetched else 0}")
                                st.session_state[_rec_cache_key] = _fetched
                                if _fetched:
                                    st.session_state["sanrenpuku_odds_df"] = pd.DataFrame([
                                        {
                                            "人気": item["Rank"],
                                            "馬番組": item["Combination"],
                                            "オッズ": item["Odds"],
                                            "horse1": item["Horses"][0],
                                            "horse2": item["Horses"][1],
                                            "horse3": item["Horses"][2],
                                        }
                                        for item in _fetched[:100]
                                    ])
                                    st.rerun()
                                else:
                                    st.session_state["sanrenpuku_odds_df"] = pd.DataFrame()
                                    st.caption("⚠️ オッズ未取得。発売前または取得エラーの可能性があります。")

                        odds_list = st.session_state.get(_rec_cache_key, None)
                        if odds_list is None:
                            st.info("ボタンを押すと推奨買い目を表示します（発売開始後にご利用ください）")
                        else:
                            try:
                                # Top-20 人気順オッズ表示
                                if odds_list:
                                    st.markdown("##### 📊 3連複 人気順オッズ（上位20件）")
                                    top20_df = pd.DataFrame([
                                        {"人気": item["Rank"], "馬番組": item["Combination"], "オッズ": item["Odds"]}
                                        for item in odds_list[:20]
                                    ])
                                    st.dataframe(top20_df, width='stretch', hide_index=True)
                                    st.divider()

                                # Use Projected Score to define top-5 axis horses
                                if 'Projected Score' in df.columns:
                                    df_for_recs = df.copy()
                                    df_for_recs['BattleScore'] = df_for_recs['Projected Score']
                                else:
                                    df_for_recs = df

                                if not odds_list:
                                    st.info("📡 3連複オッズ未取得。発売開始後（レース約30〜60分前）に「推奨買い目を取得・更新」ボタンを押してください。")
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
                                    st.dataframe(rec_df.style.apply(highlight_dark_horse, axis=1), width='stretch')
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


                    # =========================================================
                    # 買い目点数より下のセクション
                    # =========================================================
                    st.divider()
                    # Recommended Bets Section
                    st.markdown("### 🎫 推奨買い目")
                    rec_col1, rec_col2 = st.columns([2, 1])
                    with rec_col1:
                        top_horses = df.head(3)
                        if chaos_data['rank'] in ['S', 'A']:
                            st.success(f"【穴狙い】高指数・人気薄の軸から広く流す構成を推奨。 軸馬: **{top_horses.iloc[0]['Name']}**")
                        else:
                            st.info(f"【堅実】上位人気・高指数の有力馬による順当な決着を予想。 軸馬: **{top_horses.iloc[0]['Name']}**")
                    with rec_col2:
                        st.button("📋 買い目を生成", help="詳細な資金配分を含む買い目を生成します", key="btn_gen_bets_gpt")

                    # --- 精選10点予想: 2強軸＋期待値上位フィルタ ---
                    _chaos_r = chaos_data['rank']

                    _san_threshold = st.slider(
                        "足切り閾値（軸1位スコアの何割未満を除外）",
                        min_value=0.4, max_value=0.8, value=0.6, step=0.05,
                        key="sanrenpuku_threshold_sra",
                        help="値を上げると相手が絞られ、下げると相手が広がります"
                    )
                    _san_result = calculator.generate_sanrenpuku_10(
                        df, _chaos_r, min_score_ratio=_san_threshold
                    )

                    if _san_result.get("warning") and not _san_result["bets"]:
                        st.error(_san_result["warning"])
                    else:
                        _j1 = _san_result.get("jiku_1")
                        _j2 = _san_result.get("jiku_2")
                        if _j1 is not None and _j2 is not None:
                            _sc = _san_result.get("score_col", "BattleScore")
                            _jc1, _jc2 = st.columns(2)
                            with _jc1:
                                st.metric(
                                    label=f"軸① {_j1['Name']}（{int(_j1['Umaban'])}番）",
                                    value=f"スコア {_j1[_sc]:.1f}",
                                    delta=f"{_j1.get('Popularity', '-')}番人気 / {_j1.get('Odds', '-')}倍",
                                )
                            with _jc2:
                                st.metric(
                                    label=f"軸② {_j2['Name']}（{int(_j2['Umaban'])}番）",
                                    value=f"スコア {_j2[_sc]:.1f}",
                                    delta=f"{_j2.get('Popularity', '-')}番人気 / {_j2.get('Odds', '-')}倍",
                                )
                            st.caption(f"戦略：{_san_result.get('strategy', '')}")

                        if _san_result.get("warning"):
                            st.warning(_san_result["warning"])

                        if _san_result["bets"]:
                            _num_to_name = dict(zip(df['Umaban'], df['Name']))
                            _bet_rows = []
                            for _i, (_a, _b, _c) in enumerate(_san_result["bets"]):
                                _bet_rows.append({
                                    "#": _i + 1,
                                    "買い目（馬番）": f"{_a}-{_b}-{_c}",
                                    "馬名": " - ".join(_num_to_name.get(_n, str(_n)) for _n in [_a, _b, _c]),
                                })
                            st.markdown(f"#### 🎫 3連複買い目（{_san_result['bet_count']}点）")
                            st.dataframe(pd.DataFrame(_bet_rows), width='stretch', hide_index=True)
                        else:
                            st.info("買い目を生成できませんでした。足切り閾値を下げてみてください。")

                    st.divider()

                    # --- 3連複：人気順オッズ × スコアTop5フィルタ ---
                    st.subheader("🎯 3連複 中穴10点（オッズ×スコアフィルタ）")
                    st.caption("市場の人気順オッズにスコアTop5フィルタを重ね、5,000〜30,000円帯の中穴を10点に絞ります。")
                    _sof_odds_df = st.session_state.get("sanrenpuku_odds_df", pd.DataFrame())
                    if _sof_odds_df.empty or 'horse1' not in _sof_odds_df.columns:
                        st.info("📡 オッズ取得後に自動表示されます。発売開始後に「推奨買い目を取得・更新」ボタンを押してください。")
                    else:
                        with st.expander("⚙️ 買い目フィルタ設定", expanded=False):
                            _sof_c1, _sof_c2, _sof_c3 = st.columns(3)
                            with _sof_c1:
                                _sof_min_p = st.number_input("最低価格帯（円）", min_value=1000, max_value=50000, value=5000, step=1000, key="sof_min_price_sra")
                            with _sof_c2:
                                _sof_max_p = st.number_input("最高価格帯（円）", min_value=5000, max_value=500000, value=30000, step=5000, key="sof_max_price_sra")
                            with _sof_c3:
                                _sof_msh = st.selectbox("スコアTop5が何頭以上含まれる買い目を採用", options=[1, 2, 3], index=0, key="sof_min_score_sra", help="1=広め、2=絞り")

                        _sof_sc = 'Projected Score' if 'Projected Score' in df.columns else 'BattleScore'
                        _sof_top5 = df.sort_values(_sof_sc, ascending=False).head(5)
                        st.markdown("##### 🏆 スコアTop5（このいずれかが買い目に含まれる）")
                        _sof_top5_disp = _sof_top5[['Umaban', 'Name', 'Popularity', 'Odds', _sof_sc]].copy()
                        _sof_top5_disp.columns = ['馬番', '馬名', '人気', '単勝オッズ', 'スコア']
                        st.dataframe(_sof_top5_disp, width='stretch', hide_index=True)

                        _sof_result = calculator.generate_sanrenpuku_from_odds(
                            odds_df=_sof_odds_df,
                            ranking_df=df,
                            score_col=_sof_sc,
                            horse_num_col='Umaban',
                            odds_col='オッズ',
                            horse1_col='horse1',
                            horse2_col='horse2',
                            horse3_col='horse3',
                            pool_size=5,
                            min_odds=_sof_min_p / 100,
                            max_odds=_sof_max_p / 100,
                            top_n=10,
                            min_score_horses=_sof_msh,
                        )
                        if _sof_result.get("warning"):
                            st.warning(_sof_result["warning"])
                        if _sof_result["bets"]:
                            _sof_num2name = dict(zip(df['Umaban'], df['Name']))
                            _sof_top_h = _sof_result["top_horses"]
                            _sof_rows = []
                            for _si, _sbet in enumerate(_sof_result["bets"]):
                                _sa, _sb, _sc_ = _sbet["combo"]
                                _sof_rows.append({
                                    "#": _si + 1,
                                    "買い目（馬番）": f"{_sa}-{_sb}-{_sc_}",
                                    "馬名": " - ".join(_sof_num2name.get(_n, str(_n)) for _n in [_sa, _sb, _sc_]),
                                    "想定オッズ": f"{_sbet['odds']:.1f}倍",
                                    "Top5含む": f"{_sbet['top5_count']}頭 " + " ".join(f"★{_sof_num2name.get(_n, str(_n))}" for _n in [_sa, _sb, _sc_] if _n in _sof_top_h),
                                })
                            st.markdown(
                                f"#### 🎫 3連複買い目（{_sof_result['bet_count']}点）"
                                f"  価格帯：{_sof_result['price_range']}"
                                f"  候補数：{_sof_result['filtered_count']}件中上位10点"
                            )
                            st.dataframe(pd.DataFrame(_sof_rows), width='stretch', hide_index=True)
                        else:
                            st.error("条件に合う買い目が見つかりませんでした。価格帯の設定を変えてみてください。")

                    st.divider()

                    # --- [NEW] AI UNIFIED SNIPER ANALYSIS ---
                    st.subheader("🤖 中穴スナイパー分析 (詳細配分)")
                    
                    # 波乱度ランクを取得 (1201行付近で定義された chaos_data から)
                    c_rank = chaos_data['rank']
                    pop_ranges = {'S': '15〜45', 'A': '12〜35', 'B': '10〜30', 'C': '10〜30'}
                    current_pop_range = pop_ranges.get(c_rank, '10〜30')
                    
                    if c_rank in ['B', 'C']:
                        st.caption(f"3頭の人気合計が{current_pop_range}の組み合わせに絞り、波乱度に応じた中穴ゾーンをピンポイントで抽出します。")
                    else:
                        st.caption(f"波乱度{c_rank}に基づき、人気合計が{current_pop_range}の広範な組み合わせから期待値を最大化します。")
                    
                    bet_budget = st.number_input("買い目生成用 予算 (円)", min_value=1000, value=10000, step=1000, key="ai_bet_budget_unified")
                    
                    # ロジック呼び出し
                    # 波乱度ランクを取得 (1201行付近で定義された chaos_data から)
                    c_rank = chaos_data['rank']
                    unified_pool = calculator.generate_unified_sniper_pool(df, c_rank)
                    
                    if 'error' in unified_pool:
                        st.error(f"分析プール生成エラー: {unified_pool['error']}")
                    else:
                        # 予算配分を実行
                        allocated_res = calculator.allocate_unified_budget(unified_pool, bet_budget)
                        
                        rank_color = {"S": "#E63946", "A": "#F4A261", "B": "#2A9D8F", "C": "#457B9D"}.get(c_rank, "#333")
                        
                        # ステータス表示
                        f1, f2, f3 = st.columns([1, 1, 1])
                        with f1:
                            st.markdown(f"""
                                <div style="background-color: {rank_color}; color: white; padding: 10px; border-radius: 5px; text-align: center;">
                                    <div style="font-size: 12px;">波乱度判定</div>
                                    <div style="font-size: 28px; font-weight: bold;">{c_rank}</div>
                                </div>
                            """, unsafe_allow_html=True)
                        with f2:
                            min_o, max_o = unified_pool['odds_range']
                            st.metric("適用オッズレンジ", f"{min_o:.1f}〜{max_o:.1f}倍")
                        with f3:
                            st.metric("母集団頭数", f"{unified_pool['base_count']}頭")

                        st.write(f"### 🎯 推奨買い目一覧 ({allocated_res.get('main_count', 0)}点 + ボーナス)")
                        
                        if allocated_res.get('tickets'):
                            # パターン別に分離
                            tickets_a = [t for t in allocated_res['tickets'] if t.get('type') == 'A']
                            tickets_b = [t for t in allocated_res['tickets'] if t.get('type') == 'B']
                            bonus_t = [t for t in allocated_res['tickets'] if t.get('is_bonus')]
                            
                            # 2カラム表示 (スクリーンショットのデザインを再現)
                            col_pa, col_pb = st.columns(2)
                            
                            with col_pa:
                                st.markdown("#### 🟦 パターンA (上位5頭から2頭)")
                                if tickets_a:
                                    rows_a = []
                                    for t in tickets_a:
                                        rows_a.append({
                                            "組合せ": ", ".join(map(str, t['horses'])),
                                            "想定オッズ": f"{t['est_odds']:.1f}倍",
                                            "スコア計": round(t['total_score'], 1)
                                        })
                                    st.table(pd.DataFrame(rows_a))
                                else:
                                    st.caption("該当なし")
                                    
                            with col_pb:
                                st.markdown("#### 🟧 パターンB (上位5頭から1頭)")
                                if tickets_b:
                                    rows_b = []
                                    for t in tickets_b:
                                        rows_b.append({
                                            "組合せ": ", ".join(map(str, t['horses'])),
                                            "想定オッズ": f"{t['est_odds']}倍",
                                            "スコア計": round(t['total_score'], 1)
                                        })
                                    st.table(pd.DataFrame(rows_b))
                                else:
                                    st.caption("該当なし")

                            # ボーナスと詳細
                            if bonus_t:
                                st.info(f"🎁 **ボーナス枠**: {', '.join(map(str, bonus_t[0]['horses']))} ({bonus_t[0]['est_odds']:.1f}倍) / スコア計: {round(bonus_t[0]['total_score'], 1)}")

                            # 予算配分の詳細は表の下に
                            st.success(f"合計購入金額: **{allocated_res.get('actual_total', 0):,}円** / 予算: {bet_budget:,}円 (単価: {allocated_res.get('unit_price', 0):,}円)")
                            
                            with st.expander("📝 買い目詳細 (金額・馬名付)", expanded=False):
                                full_rows = []
                                for t in allocated_res['tickets']:
                                    full_rows.append({
                                        "種別": "ボーナス" if t.get('is_bonus') else f"パターン{t['type']}",
                                        "組合せ": ", ".join(map(str, t['horses'])),
                                        "馬名": " - ".join(t['names']),
                                        "購入金額": f"{t['amount']}円",
                                        "想定払戻": f"{t['est_payout']:,}円"
                                    })
                                st.dataframe(pd.DataFrame(full_rows), width='stretch')
                        else:
                            st.warning("条件に合う買い目が見つかりませんでした。")

                        # 除外ログ
                        with st.expander("🕵️ 除外ログ (フィルタリング詳細)", expanded=False):
                            st.caption("以下の組み合わせは、オッズまたは人気の条件により除外されました。")
                            for log in unified_pool['exclusion_log']:
                                st.write(f"- {log}")

                    st.divider()

                    

                    
                    
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

    with st.expander("🔑 認証・セッション管理 (Advanced Data)"):
        render_session_status(key_prefix="scanner_")

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
                    import traceback
                    err_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
                    logger.error(f"Scanner error for {rid}: {err_msg}")
                    results.append({
                        "id": rid,
                        "title": rid,
                        "pattern": None,
                        "top3": [],
                        "df": None,
                        "error": str(e),
                        "traceback": err_msg
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
                        if 'traceback' in r:
                            st.code(r['traceback'], language="python")

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
                            st.dataframe(display_df, width='stretch', hide_index=True)

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

    from core import history_manager

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
                    st.info(f"計 {len(rids)} 件のレースデータを順次取得して保存します...")
                    
                    # Add memo input for bulk registration if needed? 
                    # For now, let's just add it to the single save call if any
                    
                    for rid in rids:
                        with st.status(f"📥 Race {rid} 処理中...", expanded=False) as s:
                            # Use existing logic but pass empty memo for now unless we add a generic one
                            # Better yet, let's add a memo field for this area too if the user wants
                            pass 
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
                    _is_nar_disp = False
                    try:
                        if int(str(display_race_id)[4:6]) > 10: _is_nar_disp = True
                    except: pass
                    _dom_disp = "nar.netkeiba.com" if _is_nar_disp else "race.netkeiba.com"
                    race_url = f"https://{_dom_disp}/race/shutuba.html?race_id={display_race_id}"
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
                                 'OguraIndex', 'AvgAgari', 'AvgPosition', 'Memo', 'Alert']
                    
                    # Add result columns if available
                    if race_results:
                        disp_cols = ['Rank', 'ActualRank', 'Umaban', 'Name', 'Popularity', 'Odds', 'Jockey', 
                                     'BattleScore', 'OguraIndex', 'AvgAgari', 'AvgPosition', 
                                     'ResultAgari', 'Memo', 'Alert']
                    
                    disp_view = disp_view[[c for c in disp_cols if c in disp_view.columns]]

                    # Mask sentinel values for display (99=未取得人気, 9999.0=未取得オッズ)
                    if 'Popularity' in disp_view.columns:
                        disp_view['Popularity'] = disp_view['Popularity'].apply(
                            lambda x: '-' if (pd.isna(x) or (isinstance(x, (int, float)) and x >= 99)) else str(int(x))
                        )
                    if 'Odds' in disp_view.columns:
                        disp_view['Odds'] = disp_view['Odds'].apply(
                            lambda x: '-' if (pd.isna(x) or (isinstance(x, (int, float)) and x >= 9999.0)) else f'{x:.1f}'
                        )

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
                        "Odds": st.column_config.TextColumn("単勝オッズ"),
                        "Popularity": st.column_config.TextColumn("人気"),
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
                        
                        st.dataframe(styled, column_config=disp_col_config, width='stretch', hide_index=True)
                        
                        # --- NEW: プロ推奨買い目 (オッズ断層フォーメーション) ---
                        st.subheader("🎯 プロ推奨買い目 (オッズ断層フォーメーション)")
                        with st.expander("🛠️ 買い目選定・資金配分設定", expanded=True):
                            # BetSync から現在の予算を取得（デフォルト1,000円）
                            default_budget = 1000
                            if 'bs_bankroll' in st.session_state:
                                # BetSyncタブの計算結果（_nd_bet）を想定するが、ここでは簡易的に入力可能にする
                                pass
                            
                            target_budget = st.number_input("今回レースの総予算 (円)", value=1000, step=100)
                            
                            pro_result = calculator.calculate_pro_formation_betting(disp_df, target_budget)
                            
                            if 'error' in pro_result:
                                st.warning(pro_result['error'])
                            else:
                                st.markdown(f"**【フォーメーション構成】**")
                                f_c1, f_c2, f_c3 = st.columns(3)
                                f_c1.markdown(f"**1列目 (軸)**: {' , '.join([str(x) for x in pro_result['col1']])}")
                                f_c2.markdown(f"**2列目 (相手)**: {' , '.join([str(x) for x in pro_result['col2']])}")
                                f_c3.markdown(f"**3列目 (ヒモ)**: {' , '.join([str(x) for x in pro_result['col3']])}")

                                st.info(f"📈 検出されたオッズ断層: {pro_result['gaps_count']}箇所 (Group A: {len(pro_result['group_a'])}頭 / Group B: {len(pro_result['group_b'])}頭)")

                                # 買い目テーブルの表示
                                tickets_df = pd.DataFrame(pro_result['tickets'])
                                if not tickets_df.empty:
                                    def format_horses(h_list):
                                        return " - ".join([str(x) for x in sorted(h_list)])
                                    
                                    tickets_df['買い目'] = tickets_df['horses'].apply(format_horses)
                                    tickets_df['購入額'] = tickets_df['amount'].apply(lambda x: f"¥{x:,}")
                                    tickets_df['想定払戻'] = tickets_df['est_payout'].apply(lambda x: f"¥{x:,}")
                                    tickets_df['推計オッズ'] = tickets_df['est_odds'].apply(lambda x: f"{x:.1f}倍")
                                    tickets_df['状態'] = tickets_df['is_torigami'].apply(lambda x: "⚠トリガミ注意" if x else "✅ 利益圏内")
                                    
                                    st.dataframe(
                                        tickets_df[['買い目', '購入額', '推計オッズ', '想定払戻', '状態']],
                                        column_config={
                                            "買い目": st.column_config.TextColumn("3連複 買い目"),
                                            "購入額": st.column_config.TextColumn("投資金額"),
                                            "推計オッズ": st.column_config.TextColumn("推計オッズ"),
                                            "想定払戻": st.column_config.TextColumn("想定払戻金"),
                                            "状態": st.column_config.TextColumn("判定"),
                                        },
                                        width='stretch',
                                        hide_index=True
                                    )
                                    st.success(f"💰 合計投資予定額: ¥{pro_result['actual_total_bet']:,} (予算 ¥{target_budget:,})")
                                else:
                                    st.warning("予算内で購入可能な買い目がありませんでした。単価を上げるか予算を増やしてください。")

                    except Exception as e:
                        st.warning(f"表示エラー (raw data表示): {e}")
                        st.dataframe(disp_view, width='stretch')

                    # --- NEW: Predicted vs Actual Difficulty Display in Review ---
                    if race_results:
                        st.divider()
                        st.subheader("📊 難易度ダブルスコア検証")
                        c_diff1, c_diff2, c_diff3 = st.columns(3)
                        
                        pred_d = calculator.calculate_predicted_difficulty(disp_df)
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
                            width='stretch',
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
            with cy: st.button("✅ 実行", on_click=execute_race_action, width='stretch', key="race_conf_yes")
            with cn: st.button("❌ キャンセル", on_click=cancel_race_action, width='stretch', key="race_conf_no")
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
                        st.dataframe(df_missed[cols_show].sort_values(by='Date', ascending=False), width='stretch')
                else:
                    st.success("No significant misses yet! (or no data)")
                
        else:
            st.warning("History exists but lacks Result data. Click 'Fetch Actual Results'.")
            
        with st.expander("Full History Data"):
            st.dataframe(df_history)
            
    else:
        st.info("No history yet. Analyze races to build your database!")

# ──────────────────────────────────────────────
# 🧪 🧪 新ロジックテスト(FEW+マクリ) タブ
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
        # Clear base data to force reload for consistency
        st.session_state['df'] = None

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
                    # 適性/スピード指数の初期計算も追加して連携を深める
                    if 'meta' in locals() or 'meta' in globals():
                        _c_profile = meta.get('course_profile', '')
                        new_df = calculator.calculate_strength_suitability(new_df, _c_profile)
                    new_df = calculator.calculate_speed_index(new_df)
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

        # --- オッズ・人気未取得 警告バナー ---
        _pop_missing_t = 'Popularity' in df_test.columns and (pd.to_numeric(df_test['Popularity'], errors='coerce') >= 99).any()
        _odds_missing_t = 'Odds' in df_test.columns and (pd.to_numeric(df_test['Odds'], errors='coerce') >= 9999.0).any()
        if _pop_missing_t or _odds_missing_t:
            st.warning("⚠️ オッズ・人気データ未取得（発売前または取得エラー）")
            with st.expander("🛠️ 人気・オッズを手入力する", expanded=False):
                st.info("下のテーブルで人気・単勝オッズを編集し、「再計算して反映」ボタンを押してください。")
                # df_test を編集用に使用
                edit_df_t = df_test[['Umaban', 'Name', 'Popularity', 'Odds']].copy()
                edit_df_t['Popularity'] = pd.to_numeric(edit_df_t['Popularity'], errors='coerce').fillna(99).astype(int)
                edit_df_t['Odds'] = pd.to_numeric(edit_df_t['Odds'], errors='coerce').fillna(9999.0).astype(float)
                
                edited_t = st.data_editor(
                    edit_df_t,
                    key=f"editor_manual_test_{test_race_id}",
                    column_config={
                        "Umaban": st.column_config.NumberColumn("馬番", disabled=True),
                        "Name": st.column_config.TextColumn("馬名", disabled=True),
                        "Popularity": st.column_config.NumberColumn("人気", min_value=1, max_value=99),
                        "Odds": st.column_config.NumberColumn("単勝オッズ", min_value=1.0, max_value=999.0, format="%.1f"),
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
                if st.button("🎯 入力値を反映して再計算", key="btn_apply_manual_test", type="primary", use_container_width=True):
                    # オリジナルの session_state['df'] を更新
                    df_orig = st.session_state.get('df')
                    if df_orig is not None:
                        for _, row in edited_t.iterrows():
                            idx_o = df_orig[df_orig['Umaban'] == row['Umaban']].index
                            if not idx_o.empty:
                                df_orig.at[idx_o[0], 'Popularity'] = row['Popularity']
                                df_orig.at[idx_o[0], 'Odds'] = row['Odds']
                        
                        # 関連する計算を再実行
                        df_orig = calculator.calculate_battle_score(df_orig)
                        df_orig = calculator.calculate_n_index(df_orig)
                        st.session_state['df'] = df_orig
                        st.success("✅ データを反映し、全ての指数を再計算しました。")
                        st.rerun()

        # 0. Session Status
        with st.expander("🔑 認証・セッション管理 (Advanced Data - Login Status)"):
            render_session_status(key_prefix="test_")
        
        _W_FILE_T = os.path.join(os.path.dirname(__file__), ".score_weights_test.json")
        _weight_defaults = {
            "NIndex": 0.0, "UIndex": 0.0, "LaboIndex": 0.0, "SpeedIndex": 0.0, "Popularity": 0.0,
            "Jockey": 0.0, "Training": 0.0, "Weight": 0.0, "WeightPenalty": -10.0, "WeightCarried": 0.0,
            "Suitability": 0.0, "AvgAgari": 0.0, "Umaban": 0.0, "Bloodline": 0.0,
            "Base": 100.0
        }
        if 'score_weights_test' not in st.session_state:
            if os.path.exists(_W_FILE_T):
                try:
                    import json as _json
                    with open(_W_FILE_T, 'r', encoding='utf-8') as _wf:
                        st.session_state['score_weights_test'] = _json.load(_wf)
                except Exception:
                    st.session_state['score_weights_test'] = _weight_defaults.copy()
            else:
                st.session_state['score_weights_test'] = _weight_defaults.copy()
        sw = st.session_state['score_weights_test']
        for k, v in _weight_defaults.items():
            if k not in sw: sw[k] = v

        # --- リアルタイム同期用コールバック ---
        def _make_sync_slider(key_num, key_sld):
            def _cb(): st.session_state[key_sld] = st.session_state[key_num] * 100.0
            return _cb
        def _make_sync_num(key_sld, key_num):
            def _cb(): st.session_state[key_num] = st.session_state[key_sld] / 100.0
            return _cb

        # --- 各ウェイトのキー定義 (label, sw_key, ui_key_suffix) ---
        _W_GROUP1   = [("📊 N指数%",      "NIndex",      "nidx"),
                       ("📊 U指数%",      "UIndex",      "uidx"),
                       ("⚡ ｵﾒｶﾞ指数%",   "LaboIndex",   "labo"),
                       ("💪 強さ(X)%",  "Strength (X)", "strx"),
                       ("🏎️ ｽﾋﾟｰﾄﾞ指数%", "SpeedIndex",   "spd"),
                       ("🔥 人気%",       "Popularity",  "pop")]
        _W_GROUP2   = [("🏇 騎手(10走)%", "Jockey",      "jky"),
                       ("⏱️ 調教%",       "Training",    "trn"),
                       ("⚖️ 馬体重%",     "Weight",      "wgt"),
                       ("⚖️ 馬体増減ペナルティ", "WeightPenalty", "wgtp"),
                       ("🏋️ 斤量%",       "WeightCarried","wgtc")]
        _W_GROUP3   = [("🎯 ｺｰｽ適性(Y)%", "Suitability",   "suit"),
                       ("🚀 上がり3F%",   "AvgAgari",     "agi"),
                       ("🏁 枠順(馬番)%",  "Umaban",       "uma"),
                       ("🧬 血統%",       "Bloodline",    "bld"),
                       ("基礎戦闘力%",     "Base",         "base")]

        def _render_weight_group(items, sw, prefix):
            """1グループ分のスライダー+数値入力ボックスを描画"""
            for label, sw_key, suffix in items:
                sld_key = f"wsld_{prefix}{suffix}"
                num_key = f"wnum_{prefix}{suffix}"
                cur_val = float(sw.get(sw_key, 0.0))
                
                # UIラベルの装飾（負の値の場合は「逆相関」を表示）
                display_label = label
                if cur_val < 0:
                    color_tag = "blue" if sw_key == "WeightPenalty" else "red"
                    display_label += f" :{color_tag}[[逆相関/減点]]"
                
                max_val = 0.0 if sw_key == "WeightPenalty" else 100.0
                min_val = -100.0
                
                # Initialize if missing
                if sld_key not in st.session_state: st.session_state[sld_key] = float(cur_val)
                
                val_num = max(min_val/100.0, min(max_val/100.0, cur_val / 100.0))
                if num_key not in st.session_state: st.session_state[num_key] = float(val_num)
                
                c1, c2 = st.columns([2, 1])
                with c1:
                    st.slider(
                        display_label, min_value=min_val, max_value=max_val, step=1.0, 
                        key=sld_key,
                        on_change=_make_sync_num(sld_key, num_key)
                    )
                with c2:
                    st.number_input(
                        "", min_value=min_val/100.0, max_value=max_val/100.0, step=0.01,
                        key=num_key,
                        on_change=_make_sync_slider(num_key, sld_key),
                        label_visibility="collapsed"
                    )
                sw[sw_key] = float(st.session_state.get(num_key, cur_val/100.0)) * 100.0

        st.markdown("### 📊 影響率（ウェイト）設定")
        with st.container(border=True):
            col_l, col_c, col_r = st.columns(3)
            with col_l:
                st.markdown("#### 【能力・指数】")
                _render_weight_group(_W_GROUP1, sw, "t1")
            with col_c:
                st.markdown("#### 【人間・状態】")
                _render_weight_group(_W_GROUP2, sw, "t2")
            with col_r:
                st.markdown("#### 【適性・血統】")
                _render_weight_group(_W_GROUP3, sw, "t3")

            # 合計インジケーター
            total_w = sum(sw.values())
            if abs(total_w - 100.0) > 0.01 and total_w > 0:
                st.info(f"💡 合計: **{total_w:.2f}%**（100% 基準で自動正規化して計算されます）")
            elif total_w == 0:
                st.warning("⚠️ 全ウェイトが 0% です。各指数の生値合計が表示されます。")
            else:
                st.success(f"✅ 合計: **{total_w:.2f}%**")

        st.session_state['score_weights'] = sw
        norm_w = {k: v / (total_w if total_w > 0 else 1.0) for k, v in sw.items()}

        # --- 影響率 操作パネル ---
        st.session_state['score_weights_test'] = sw
        c_b1, c_b2, _ = st.columns([1.2, 1.2, 2.6])
        with c_b1:
            if st.button("🔄 この影響率で再計算して反映", key="btn_recalc_test", type="primary", use_container_width=True):
                st.rerun()
        with c_b2:
            if st.button("💾 この影響率を保存", key="btn_save_weights_test", use_container_width=True):
                import json as _j2
                with open(_W_FILE_T, 'w', encoding='utf-8') as _f2:
                    _j2.dump(sw, _f2, ensure_ascii=False, indent=2)
                st.success("✅ このタブ専用の設定（.score_weights_test.json）として保存完了！")

        # 2. Base Ranking (to calculate Diff later)
        df_test['BaseRank'] = df_test[score_col].rank(ascending=False, method='min')

        # 3. Playwright Action Button (Full Automation)  ← コンテナ直下、幅広
        if st.button("🚀 Playwrightで全てのデータ取得・計算を一括実行",
                     key="btn_pw_test", type="primary", use_container_width=True):
            race_id = st.session_state.get('tab1_analyzed_id', st.session_state.get('main_race_id_input', ''))
            with st.status("📊 統合データ処理中...", expanded=True) as status:
                st.write("1. Playwrightブラウザ起動... [馬体重/調教/血統/U指数/オメガ] をスキャンしています")
                top10_umaban = df_test.head(10)['Umaban'].tolist()
                adv_data = scraper.fetch_advanced_data_playwright(race_id, top_horse_ids=top10_umaban)
                st.session_state['test_adv_data'] = adv_data
                st.write("2. 独自指数 (DIY1/DIY2) を計算中...")
                df_main = st.session_state.get('df')
                if df_main is not None:
                    # --- TimeIndex Merge and Strength Recalculation ---
                    for u, d in adv_data.items():
                        ti = d.get('TimeIndex', 0.0)
                        if ti > 0:
                            df_main.loc[df_main['Umaban'] == u, 'TimeIndex'] = ti
                    
                    df_main = calculator.calculate_diy_index(df_main)
                    df_main = calculator.calculate_diy2_index(df_main)
                    # Recalculate Strength basis (X) with new Netkeiba Time Index
                    meta_prof = st.session_state.get('race_metadata', {}).get('course_profile', '')
                    df_main = calculator.calculate_strength_suitability(df_main, meta_prof)
                    st.session_state['df'] = df_main
                status.update(label="✅ 全データの取得と計算が完了しました！", state="complete", expanded=False)
            st.rerun()

        # 4. Calculation and Table Display
        adv_data = st.session_state.get('test_adv_data', {})
        
        # Ensure indices exist — always recalculate from PastRuns (no adv_data gate)
        if 'DIY_Index' not in df_test.columns or (df_test['DIY_Index'] == 0).all():
            df_test = calculator.calculate_diy_index(df_test)
            st.session_state['df'] = df_test

        if 'DIY2_Index' not in df_test.columns or (df_test['DIY2_Index'] == 50).all() or (df_test['DIY2_Index'] == 0).all():
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
            
            # Update Popularity/Odds from Playwright if available (v2.1 fix)
            pop_val = pw_data.get('Popularity', 99)
            if pop_val != 99:
                row['Popularity'] = pop_val
            
            odds_val = pw_data.get('Odds', 0.0)
            if odds_val > 0.0:
                row['Odds'] = odds_val
            
            # --- Strength (X) Sync ---
            s_val = float(row.get('Strength (X)', 0))
            # If TimeIndex was merged but recalculation not yet done, we can trust the current row['Strength (X)'] 
            # as it was recalculated in btn_pw_test or Analyze button.
            
            # --- Netkeiba Time Index Merge ---
            t_idx = pw_data.get('TimeIndex', 0.0)
            if t_idx > 0:
                row['TimeIndex'] = t_idx

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
            
            # C-2. 騎手ボーナス
            j_name = str(row.get('Jockey', ''))
            j_bonus = get_jockey_bonus(j_name)
            if j_bonus > 0:
                remarks.append(f"騎手({j_name}:{j_bonus:+})")

            # C-3. 逆転ロジック・特殊検知
            y_val_raw = float(row.get('Suitability (Y)', 0))
            s_idx_raw = float(row.get('SpeedIndex', row.get('DIY_Index', 0)))
            
            # 適性不足ペナルティ (-30点)
            if y_val_raw <= 30:
                score_diff -= 30.0
                remarks.append("適性不足(-30)")

            # 激走候補 (Hidden Gem) 判定
            # 条件: 戦闘力がトップ層(上位3位以内)ではないが、指数と適性が共に80点以上
            base_rank_val = row.get('BaseRank', 99)
            if base_rank_val > 3 and s_idx_raw >= 80 and y_val_raw >= 80:
                horse_name = f"💎 {horse_name}"
                remarks.append("激走候補(HiddenGem)")

            # D. Scoring Logic (Unified Professional Spec)
            u_val = pw_data.get('UIndex', 0.0)
            l_val = pw_data.get('LaboIndex', 0.0)
            
            # Weight/Blood scores for normalization
            w_score = 50.0  # Default
            match_w = re.search(r'\(([-+]\d+)\)', weight_str)
            if match_w:
                diff_w = abs(int(match_w.group(1)))
                if diff_w <= 2: w_score = 100.0
                elif diff_w >= 10: w_score = 25.0
            
            blood_score = 100.0 if blood_flag else 0.0
            
            # Normalize factors 0-100
            norm_stats = {}
            # Capability / Index
            norm_stats['NIndex'] = min(max(float(row.get('NIndex', 0)) / 1.0, 0), 100)
            norm_stats['UIndex'] = min(max(u_val / 1.0, 0), 100)
            norm_stats['LaboIndex'] = min(max(l_val / 1.0, 0), 100)
            # スピード指数があれば優先、なければ 0
            s_idx_val = float(row.get('SpeedIndex', row.get('DIY_Index', 0)))
            norm_stats['SpeedIndex'] = min(max(s_idx_val, 0), 100)

            # Popularity (1st=100, 18th=0)
            try:
                pop_int = int(row.get('Popularity', 18))
                if pop_int == 99: pop_int = 18
                norm_stats['Popularity'] = max(0, 100 - (pop_int - 1) * 6)
            except: norm_stats['Popularity'] = 0
            
            # Human / Condition
            norm_stats['Jockey'] = min(max(j_bonus * 20, 0), 100) # +5=100
            norm_stats['Training'] = min(max(training_score * 10, 0), 100) # +10=100
            norm_stats['Weight'] = w_score # 100/50/25
            norm_stats['WeightCarried'] = 50.0 # Placeholder
            
            # Suitability / Others
            # 適性(Y)があれば優先
            y_val = float(row.get('Suitability (Y)', 0))
            norm_stats['Suitability'] = min(max(y_val, 0), 100)
            # AvgAgari (Rank based if possible, or DIY2)
            agari_val = float(row.get('DIY2_Index', 50))
            if isinstance(past_runs, list) and len(past_runs) > 0:
                try:
                    ar = int(past_runs[0].get('AgariRank', 10))
                    agari_val = max(0, 100 - (ar - 1) * 10)
                except: pass
            norm_stats['AvgAgari'] = agari_val
            norm_stats['Umaban'] = 50.0 + (3.0 if umaban <= 4 else (-2.0 if umaban >= 13 else 0)) * 10
            norm_stats['Bloodline'] = blood_score
            
            # Weighted Bonus Calculation
            total_bonus = 0.0
            horse_bonus_details = []
            # For Styling
            _style_note = []
            if "究極仕上" in str(remarks): _style_note.append("BEST")
            if "馬体増減" in str(remarks): _style_note.append("RISK")
            
            label_map_short_test = {
                'NIndex': 'N指', 'UIndex': 'U指', 'LaboIndex': 'オメガ', 'SpeedIndex': 'スピ',
                'Popularity': '人気', 'Jockey': '騎手', 'Training': '調教', 'Weight': '馬体',
                'Suitability': '適性', 'AvgAgari': '末脚', 'Umaban': '枠', 'Bloodline': '血統'
            }
            
            for k, s_val in norm_stats.items():
                w_percent = sw.get(k, 0.0) / 100.0
                b_pts = s_val * w_percent
                total_bonus += b_pts
                if b_pts != 0:
                    short_n = label_map_short_test.get(k, k)
                    horse_bonus_details.append(f"{short_n}:{b_pts:+.1f}")

            # Base Score impact
            base_w = sw.get('Base', 100.0) / 100.0
            final_test_score = (base_score * base_w) + total_bonus + score_diff # score_diff is frame/weight extra
            
            # D. Scoring Logic (Unified Professional Spec)
            # ユーザー要望: 戦闘力を100%とした上での上乗せボーナス方式
            base_w = 1.0 # 固定 (100%)
            final_test_score = (base_score * base_w) + total_bonus + score_diff
            
            test_scores.append({
                "馬番": umaban,
                "馬名(ラベル付)": horse_name,
                "騎手": j_name,
                "人気": int(row.get('Popularity')) if pd.notnull(row.get('Popularity')) and row.get('Popularity') != 99 else "-",
                "馬体": weight_str if weight_str and str(weight_str).strip() != "" else "-",
                "U指数": pw_data.get('UIndex', row.get('UIndex', "-")),
                "オメガ": pw_data.get('LaboIndex', "-"),
                "適性": round(float(row.get('Suitability (Y)', 0.0)), 1),
                "上り3F（順位）": row.get('AgariRank', past_runs[0].get('AgariRank', "-")) if isinstance(past_runs, list) and len(past_runs) > 0 else row.get('AgariRank', "-"),
                "元の順位": int(row.get('BaseRank', 99)),
                "元のスコア": round(base_score, 1),
                "予測スコア": round(final_test_score, 1),
                "調教": pw_data.get('TrainingScore', "-"),
                "斤量": row.get('WeightCarried', "-"),
                "スピード指数": round(s_idx_raw, 1),
                "強さ(X)": round(float(row.get('Strength (X)', 0.0)), 1),
                "DIY指数": round(float(row.get('DIY_Index', 0.0)), 1),
                "DIY2": round(float(row.get('DIY2_Index', 0.0)), 1),
                "タイム指数": pw_data.get('TimeIndex', "-"),
                "_BonusDetails": ", ".join(horse_bonus_details) if horse_bonus_details else "-",
                "_Style": "|".join(_style_note) if _style_note else ""
            })
            
        df_test_res = pd.DataFrame(test_scores)
        # Calculate New Rank and Diff
        df_test_res['新順位'] = df_test_res['予測スコア'].rank(ascending=False, method='min').astype(int)
        df_test_res['Diff'] = df_test_res['元の順位'] - df_test_res['新順位']
        
        # 順位変動ラベルと大金星(Giant Killing)の実装
        def refine_marks(r):
            name = str(r.get('馬名(ラベル付)', ''))
            d = int(r.get('Diff', 0))
            if d > 0: name += f" ↑({d}↑)"
            elif d < 0: name += f" ↓({abs(d)}↓)"
            
            # 大金星 candidate: 戦闘力(元の順位)1位ではない馬が予測1位
            if r['新順位'] == 1 and r['元の順位'] > 1:
                name = "🔥『大金星候補』 " + name
            return name
            
        df_test_res['馬名(ラベル付)'] = df_test_res.apply(refine_marks, axis=1)
        
        # Re-sort by Predicted Score
        df_test_res = df_test_res.sort_values(by="予測スコア", ascending=False).reset_index(drop=True)
        df_test_res.index = range(1, len(df_test_res) + 1)

        # UI: Table with column config
        st.markdown("### 📋 検証結果ランキング")
        
        # Display Bonus Chart (Top 5)
        with st.expander("📈 上位5頭のボーナス加算内訳（加点ウェイト反映）", expanded=True):
            b_df = df_test_res.head(5).copy()
            # Parse _BonusDetails into separate columns for chart
            all_b_types = set()
            for idx, row in b_df.iterrows():
                details = row['_BonusDetails'].split(', ')
                for d in details:
                    if ':' in d:
                        b_type, b_val = d.split(':')
                        b_df.at[idx, f"Chart_{b_type}"] = float(b_val)
                        all_b_types.add(b_type)
            
            active_chart_cols = [f"Chart_{t}" for t in all_b_types]
            if active_chart_cols:
                h_name_col = "馬名(ラベル付)"
                chart_data = b_df.melt(id_vars=[h_name_col], value_vars=active_chart_cols,
                                       var_name='BonusType', value_name='Points')
                chart_data['BonusType'] = chart_data['BonusType'].str.replace('Chart_', '')
                
                import altair as alt
                c = alt.Chart(chart_data).mark_bar().encode(
                    x=alt.X('Points:Q', title="加算ポイント"),
                    y=alt.Y(f'{h_name_col}:N', sort='-x', title="馬名"),
                    color=alt.Color('BonusType:N', legend=alt.Legend(title="指標")),
                    tooltip=[h_name_col, 'BonusType', 'Points']
                ).properties(height=250)
                st.altair_chart(c, use_container_width=True)

        # Style and Display Table
        def highlight_test_rows(r):
            bg = ''
            style_tag = str(r.get('_Style', ''))
            diff_val = r.get('Diff', 0)
            is_giant = "🔥『大金星候補』" in str(r.get('馬名(ラベル付)', ''))
            
            if is_giant: bg = 'background-color: #ff4500;' # OrangeRed (Giant Killing)
            elif diff_val >= 3: bg = 'background-color: #006400;' # Bright Green
            elif 'BEST' in style_tag: bg = 'background-color: #004d00;' # Dark Green
            elif 'RISK' in style_tag: bg = 'background-color: #4d0000;' # Dark Red
            
            text_col = 'color: white; font-weight: bold;' if bg else ''
            return [bg + text_col for _ in r]

        df_display = df_test_res.drop(columns=['_BonusDetails', '_Style']) if '_BonusDetails' in df_test_res.columns else df_test_res
        
        # 行全体のハイライト（仕上がり・逆転候補）
        styled_test_df = df_display.style.apply(highlight_test_rows, axis=1)
        
        # 予測スコア列のみピンクにハイライト
        def highlight_score_col(s):
            return ["background-color: #fff0f6; color: #c01e5a; font-weight: bold;" for _ in s]
        
        if '予測スコア' in df_display.columns:
            styled_test_df = styled_test_df.apply(highlight_score_col, axis=0, subset=['予測スコア'])

        # --- Column order persistence (user_prefs.json) ---
        _prefs_path_lt = os.path.join(os.getcwd(), "user_prefs.json")
        try:
            import json as _json_lt
            with open(_prefs_path_lt, 'r', encoding='utf-8') as _f:
                _prefs_lt = _json_lt.load(_f)
            _saved_lt = list(_prefs_lt.get('logic_test_col_order', []))
            
            _all_lt = list(df_display.columns)
            # 既に保存された順序があればそれを使いつつ、新しく増えた列（調教やU指数など）を末尾ではなく目立つように補完
            if _saved_lt:
                _ordered_valid = [c for c in _saved_lt if c in _all_lt]
                _missing_new = [c for c in _all_lt if c not in _ordered_valid]
                # 重要カラム（指数・スコア系）は先頭、その他は末尾に
                _important = [c for c in _missing_new if any(tok in c for tok in ["指数", "スコア", "適性", "U指数", "オメガ"])]
                _the_rest = [c for c in _missing_new if c not in _important]
                df_display = df_display[_important + _ordered_valid + _the_rest]
        except: pass

        with st.expander("📋 列の表示順序を設定（選択順が左から右の順になります）", expanded=False):
            _cur_cols_lt = list(df_display.columns)
            # multiselect の初期値がキャッシュに引きずられるため、新設カラムを優先的にマージ
            _default_lt = st.session_state.get('logic_test_col_order_sel', _cur_cols_lt)
            for c in ["調教", "U指数", "スピード指数", "斤量", "予測スコア"]:
                if c in _cur_cols_lt and c not in _default_lt:
                    _default_lt = [c] + _default_lt
            
            _sel_cols_lt = st.multiselect(
                "表示する列・順序", options=_cur_cols_lt, default=_default_lt,
                key="logic_test_col_order_sel"
            )
            if st.button("💾 この列順を保存", key="btn_save_logic_col_order"):
                try:
                    import json as _json_lt2
                    try:
                        with open(_prefs_path_lt, 'r', encoding='utf-8') as _f:
                            _prefs_lt2 = _json_lt2.load(_f)
                    except: _prefs_lt2 = {}
                    _prefs_lt2['logic_test_col_order'] = _sel_cols_lt
                    with open(_prefs_path_lt, 'w', encoding='utf-8') as _f:
                        _json_lt2.dump(_prefs_lt2, _f, ensure_ascii=False, indent=2)
                    st.success("✅ 列順を保存しました")
                except Exception as _e:
                    st.error(f"保存失敗: {_e}")
        
        if _sel_cols_lt:
            df_display = df_display[[c for c in _sel_cols_lt if c in df_display.columns]]
            styled_test_df = df_display.style.apply(highlight_test_rows, axis=1)

        st.dataframe(
            styled_test_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "元のスコア": st.column_config.NumberColumn(format="%.1f"),
                "予測スコア": st.column_config.NumberColumn(format="%.1f"),
                "調教": st.column_config.NumberColumn(format="%.1f"),
                "斤量": st.column_config.NumberColumn(format="%.1f"),
                "スピード指数": st.column_config.NumberColumn(format="%.1f"),
                "U指数": st.column_config.NumberColumn(format="%.1f"),
                "DIY指数": st.column_config.NumberColumn(format="%.1f"),
                "DIY2": st.column_config.NumberColumn(format="%.1f"),
                "適性": st.column_config.NumberColumn(format="%.1f"),
                "オメガ": st.column_config.NumberColumn(format="%.1f"),
                "上り3F（順位）": st.column_config.NumberColumn(format="%d"),
                "元の順位": st.column_config.NumberColumn(format="%d"),
                "新順位": st.column_config.NumberColumn(format="%d"),
                "Diff": st.column_config.NumberColumn(format="%+d"),
            }
        )

        # --- 比較用：旧ロジック（FEW+マクリ以前）テーブル ---
        st.divider()
        st.subheader("🔙 【比較用】旧ロジック算出結果（FEW+マクリ）")
        with st.expander("表示する（今回の拡張指示前の状態）", expanded=True):
            if not df_test.empty:
                old_scores = []
                for _, row in df_test.iterrows():
                    b_score = float(row.get('BattleScore', 0.0))
                    o_n = float(row.get('NIndex', 0)) * (sw.get('NIndex', 0.0)/100.0)
                    o_u = float(row.get('UIndex', 0)) * (sw.get('UIndex', 0.0)/100.0)
                    o_d = float(row.get('DIY_Index', 0)) * (sw.get('SpeedIndex', 0.0)/100.0)
                    
                    total_o = b_score + o_n + o_u + o_d
                    old_scores.append({
                        "馬番": row.get('Umaban'),
                        "馬名": row.get('Name'),
                        "「旧」予測スコア": round(total_o, 1),
                        "元の順位": int(row.get('BaseRank', 99))
                    })
                df_old = pd.DataFrame(old_scores)
                df_old['旧順位'] = df_old['「旧」予測スコア'].rank(ascending=False, method='min').astype(int)
                st.dataframe(df_old.sort_values("旧順位"), use_container_width=True, hide_index=True)
            else:
                st.warning("データが読み込まれていないため、比較結果を表示できません。")

        # --- 3連複スペシャル (2強軸ロジック) は独立したコンテナとして後に続く ---
        st.divider()
        _test_chaos_r = calculator.evaluate_race_chaos_v3(df_test).get('rank', 'B') if hasattr(calculator, 'evaluate_race_chaos_v3') else calculator.evaluate_race_chaos_v2(df_test).get('rank', 'B')
        if _test_chaos_r in ['S', 'A']:
            st.subheader("🔥 3連複スペシャル（波乱狙い）")
            st.caption("2強軸＋高オッズ相手 で高配当を狙います")
        else:
            st.subheader("💚 3連複スペシャル（堅実）")
            st.caption("2強軸＋高スコア相手 で的中率重視の構成です")

        _test_threshold = st.slider(
            "足切り閾値（軸1位スコアの何割未満を除外）",
            min_value=0.4, max_value=0.8, value=0.6, step=0.05,
            key="sanrenpuku_threshold_test",
            help="値を上げると相手が絞られ、下げると相手が広がります"
        )
        _test_san = calculator.generate_sanrenpuku_10(
            df_test, _test_chaos_r, min_score_ratio=_test_threshold
        )

        if _test_san.get("warning") and not _test_san["bets"]:
            st.error(_test_san["warning"])
        else:
            _tj1 = _test_san.get("jiku_1")
            _tj2 = _test_san.get("jiku_2")
            if _tj1 is not None and _tj2 is not None:
                _tsc = _test_san.get("score_col", "BattleScore")
                _tc1, _tc2 = st.columns(2)
                with _tc1:
                    st.metric(
                        label=f"軸① {_tj1['Name']}（{int(_tj1['Umaban'])}番）",
                        value=f"スコア {_tj1[_tsc]:.1f}",
                        delta=f"{_tj1.get('Popularity', '-')}番人気 / {_tj1.get('Odds', '-')}倍",
                    )
                with _tc2:
                    st.metric(
                        label=f"軸② {_tj2['Name']}（{int(_tj2['Umaban'])}番）",
                        value=f"スコア {_tj2[_tsc]:.1f}",
                        delta=f"{_tj2.get('Popularity', '-')}番人気 / {_tj2.get('Odds', '-')}倍",
                    )
                st.caption(f"戦略：{_test_san.get('strategy', '')}")

            if _test_san.get("warning"):
                st.warning(_test_san["warning"])

            if _test_san["bets"]:
                _tnum_to_name = dict(zip(df_test['Umaban'], df_test['Name']))
                _tbet_rows = []
                for _ti, (_ta, _tb, _tc_) in enumerate(_test_san["bets"]):
                    _tbet_rows.append({
                        "#": _ti + 1,
                        "買い目（馬番）": f"{_ta}-{_tb}-{_tc_}",
                        "馬名": " - ".join(_tnum_to_name.get(_n, str(_n)) for _n in [_ta, _tb, _tc_]),
                    })
                st.markdown(f"#### 🎫 3連複買い目（{_test_san['bet_count']}点）")
                st.dataframe(pd.DataFrame(_tbet_rows), width='stretch', hide_index=True)
            else:
                st.info("買い目を生成できませんでした。足切り閾値を下げてみてください。")

        # --- 3連複：人気順オッズ × スコアTop5フィルタ ---
        st.divider()
        st.subheader("🎯 3連複 中穴10点（オッズ×スコアフィルタ）")
        st.caption("市場の人気順オッズにスコアTop5フィルタを重ね、5,000〜30,000円帯の中穴を10点に絞ります。")
        _tsof_odds_df = st.session_state.get("sanrenpuku_odds_df", pd.DataFrame())
        if _tsof_odds_df.empty or 'horse1' not in _tsof_odds_df.columns:
            st.info("📡 オッズ取得後に自動表示されます。発売開始後に「推奨買い目を取得・更新」ボタンを押してください。")
        else:
            with st.expander("⚙️ 買い目フィルタ設定", expanded=False):
                _tsof_c1, _tsof_c2, _tsof_c3 = st.columns(3)
                with _tsof_c1:
                    _tsof_min_p = st.number_input("最低価格帯（円）", min_value=1000, max_value=50000, value=5000, step=1000, key="tsof_min_price")
                with _tsof_c2:
                    _tsof_max_p = st.number_input("最高価格帯（円）", min_value=5000, max_value=500000, value=30000, step=5000, key="tsof_max_price")
                with _tsof_c3:
                    _tsof_msh = st.selectbox("スコアTop5が何頭以上含まれる買い目を採用", options=[1, 2, 3], index=0, key="tsof_min_score", help="1=広め、2=絞り")

            _tsof_sc = 'Projected Score' if 'Projected Score' in df_test.columns else 'BattleScore'
            _tsof_top5 = df_test.sort_values(_tsof_sc, ascending=False).head(5)
            st.markdown("##### 🏆 スコアTop5（このいずれかが買い目に含まれる）")
            _tsof_top5_disp = _tsof_top5[['Umaban', 'Name', 'Popularity', 'Odds', _tsof_sc]].copy()
            _tsof_top5_disp.columns = ['馬番', '馬名', '人気', '単勝オッズ', 'スコア']
            st.dataframe(_tsof_top5_disp, width='stretch', hide_index=True)

            _tsof_result = calculator.generate_sanrenpuku_from_odds(
                odds_df=_tsof_odds_df,
                ranking_df=df_test,
                score_col=_tsof_sc,
                horse_num_col='Umaban',
                odds_col='オッズ',
                horse1_col='horse1',
                horse2_col='horse2',
                horse3_col='horse3',
                pool_size=5,
                min_odds=_tsof_min_p / 100,
                max_odds=_tsof_max_p / 100,
                top_n=10,
                min_score_horses=_tsof_msh,
            )
            if _tsof_result.get("warning"):
                st.warning(_tsof_result["warning"])
            if _tsof_result["bets"]:
                _tsof_n2n = dict(zip(df_test['Umaban'], df_test['Name']))
                _tsof_th = _tsof_result["top_horses"]
                _tsof_rows = []
                for _tsi, _tsbet in enumerate(_tsof_result["bets"]):
                    _tsa, _tsb, _tsc_ = _tsbet["combo"]
                    _tsof_rows.append({
                        "#": _tsi + 1,
                        "買い目（馬番）": f"{_tsa}-{_tsb}-{_tsc_}",
                        "馬名": " - ".join(_tsof_n2n.get(_n, str(_n)) for _n in [_tsa, _tsb, _tsc_]),
                        "想定オッズ": f"{_tsbet['odds']:.1f}倍",
                        "Top5含む": f"{_tsbet['top5_count']}頭 " + " ".join(f"★{_tsof_n2n.get(_n, str(_n))}" for _n in [_tsa, _tsb, _tsc_] if _n in _tsof_th),
                    })
                st.markdown(
                    f"#### 🎫 3連複買い目（{_tsof_result['bet_count']}点）"
                    f"  価格帯：{_tsof_result['price_range']}"
                    f"  候補数：{_tsof_result['filtered_count']}件中上位10点"
                )
                st.dataframe(pd.DataFrame(_tsof_rows), width='stretch', hide_index=True)
            else:
                st.error("条件に合う買い目が見つかりませんでした。価格帯の設定を変えてみてください。")

        st.divider()
        memo_val_test = st.text_input("📝 メモ (Memo)", key="memo_val_test", placeholder="この解析に関するメモを入力...")

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("💾 解析結果をJSON保存 (Save JSON)", type="secondary", width='stretch'):
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
                        "Memo": memo_val_test,
                        "Results": res_dict
                    }
                    
                    # Save as JSON with UTF-8 encoding
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(save_data, f, ensure_ascii=False, indent=2)
                        
                    st.success(f"✅ 解析結果をJSON保存しました！\n📂 保存先: `{file_path}`")
                except Exception as e:
                    import traceback
                    st.error(f"保存エラー: {e}")
                    logger.error(f"Save Error: {traceback.format_exc()}")
        
        with col_btn2:
            if st.button("📊 履歴(CSV)に登録", type="primary", width='stretch'):
                 try:
                     # For CSV history, we might need more columns than df_test_res has.
                     # But history_manager.save_race_data handles missing columns.
                     current_id = st.session_state.get('tab1_analyzed_id', st.session_state.get('main_race_id_input', 'unknown_race'))
                     # We use the original df_test which has all raw columns before scoring
                     res = history_manager.save_race_data(df_test, current_id, memo=memo_val_test)
                     if res == "Duplicate":
                         st.warning("⚠️ このレースIDは既に履歴に存在します。")
                     else:
                         st.success("✅ 履歴(CSV)に登録しました！「History & Review」タブで確認できます。")
                 except Exception as e:
                     st.error(f"CSV登録エラー: {e}")
            
    else:
        st.warning(f"⚠️ データが現在のレースID（{current_input_id}）と一致しないか、未解析です。")
        st.info("「Single Race Analysis」タブに戻り、**🚀 Analyze Race** ボタンを押して最新のデータを取得してください。")

# ──────────────────────────────────────────────
# 🤓 🤓 N氏の研究室 — 統合ページ（4タブ）
# ──────────────────────────────────────────────
if nav == "🤓 N氏の研究室":
    st.header("🤓 N氏の研究室")
    nlab_tab1, nlab_tab2, nlab_tab3, nlab_tab4 = st.tabs([
        "📚 RMHS分析",
        "🏇 過去走R理論スキャン",
        "🔬 実験その３(馬番パターン)",
        "🎯 馬番配置AI",
    ])

    with nlab_tab1:
        st.header("📚 【新理論】R/M/H/S 分析")
        st.markdown("レース結果データから、R（リバウンド）、M（マクリ）、H（ハイペース耐性）、S（スロー末脚）の4理論に該当する馬を抽出します。")
    
        col1, col2, col3 = st.columns([2, 5, 2])
        with col1:
            target_id_input = st.text_input("分析対象 RaceID (12桁)", value=st.session_state.get('main_race_id_input', ''), key="rmhs_id_input")
        with col2:
            theory_filter = st.radio(
                "理論フィルタ",
                ["すべて", "R理論 (Rebound)", "M理論 (Move)", "H理論 (High-pace Hang)", "S理論 (Slow-pace Surge)"],
                horizontal=True,
                key="rmhs_theory_filter"
            )
        with col3:
            st.write("") # Spacer
            analyze_btn = st.button("🔍 RMHS分析を実行", width='stretch', key="rmhs_analyze_btn")
        
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

                st.dataframe(df_rmhs.style.apply(highlight_theory, subset=['RMHS判定']), width='stretch')
            
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

    with nlab_tab2:
        st.header("🏇 指定場 過去走R理論スキャン")
        st.markdown("指定した日付の**全競馬場（全レース）**または特定の競馬場を対象に、全出走馬の**過去5走**を自動スキャンし、R理論（Rebound）に合致する「次走注目馬」を抽出します。")
        st.warning("⚠️ **注意**: アクセス制限(BAN)対策として1レースごとに2秒の待機時間を設けています。全場スキャン（約36レース）には約2分、1場のスキャン（12レース）には約40秒かかります。")
    
        col_d1, col_d2 = st.columns([3, 1])
        with col_d1:
            default_date = datetime.now().strftime("%Y%m%d")
            scan_date_input = st.text_input("スキャン対象日付 (YYYYMMDD形式)", value=default_date, key="r_scan_date_input")
        with col_d2:
            st.write("") # Spacer
            fetch_venues_btn = st.button("📅 開催場一覧を取得", width='stretch', key="r_scan_fetch_venues_btn")
        
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
                    if not (v_code.isdigit() and 1 <= int(v_code) <= 10): continue  # Phase 2: JRA Only Restrict
                    if v_code not in venues:
                        venues[v_code] = []
                    venues[v_code].append(r)
            
                # VENUE_NAMES is now imported globally from core.scraper
            
                v_options = sorted(list(venues.keys()), key=lambda x: int(x))
                def format_venue(code):
                    name = VENUE_NAMES.get(code, f"コード {code}")
                    count = len(venues.get(code, []))
                    return f"{name} ({count}レース)"
            
                st.markdown("---")
                col_v1, col_v2, col_v3 = st.columns([2, 1, 1])
                with col_v1:
                    selected_v_code = st.selectbox("特定の競馬場を選択（個別スキャン用）", v_options, format_func=format_venue, key="r_scan_selected_venue")
                with col_v2:
                    st.write("")
                    run_all_scan_btn = st.button("🌍 全開催場をスキャン", width='stretch', type="primary", key="r_scan_run_all_btn")
                with col_v3:
                    st.write("")
                    run_single_scan_btn = st.button("🚀 選択した場のみスキャン", width='stretch', key="r_scan_run_single_btn")
            
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
                    st.dataframe(df_extracted, width='stretch')
                elif run_all_scan_btn or run_single_scan_btn:
                    st.info("該当する馬は見つかりませんでした。")

    # ──────────────────────────────────────────────
    # 💾 💾 ロジック置き場
    # ──────────────────────────────────────────────

    with nlab_tab3:
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
        #### スコアリング (v2.0 統合判定版)
        | ボーナス | 条件 | 加点 |
        |---|---|---|
        | **Evidences** | 検出された配置証拠1件につき | +1 |
        | **Overlap** | 証拠が2種類(P1~P4)以上のタイプに及ぶ | +2 |
        | **Multi-Entry** | 同一レースに同一厩舎が2頭以上出走 | +2 |
        | **Signal J◎** | 騎手の当日全出走が同一馬番等で統一 | +3 |
        | **Signal T◎** | 厩舎の当日全出走が同一馬番等で統一 | +3 |
        | **Signal T●** | 厩舎が異なる場・同一Rで好配置一致 | +2 |
        | **Longshot** | 7人気以下 または 単勝20倍以上 | +1 |
        | **J1R (Single Ride)** | 当該場での騎乗が当日1回のみ | (表示のみ) |
        """)

        st.divider()

        col_d1, col_d2 = st.columns([3, 1])
        with col_d1:
            default_date = datetime.now().strftime("%Y%m%d")
            rpps_date = st.text_input("スキャン対象日付 (YYYYMMDD)", value=default_date, key="rpps_date_input")
        with col_d2:
            st.write("") 
            fetch_venues_btn = st.button("📅 開催場を取得", key="rpps_fetch_venues", width='stretch')

        if fetch_venues_btn and rpps_date:
            res = scraper.get_race_list_for_date(rpps_date)
            if not res:
                st.error(f"⚠️ {rpps_date} の開催場を取得できませんでした。データセンターIP制限によりブロックされているか、該当日の開催が空の可能性があります。少し時間を置いて再試行してください。")
            else:
                st.success(f"✅ {len(res)} レース分の開催情報を取得しました。")
            st.session_state.rpps_venue_list = res

        selected_race_urls = []
        selected_race_urls = []
        all_race_urls = []  # 全場まとめURL（●シグナルに必要）

        if 'rpps_venue_list' in st.session_state and st.session_state.rpps_venue_list:
            race_list = st.session_state.rpps_venue_list
            # 場別にグループ
            venues = {}
            for r in race_list:
                v_code = r['race_id'][4:6] if len(r['race_id']) == 12 else 'Unknown'
                if not (v_code.isdigit() and 1 <= int(v_code) <= 10): continue  # Phase 2: JRA Only Restrict
                if v_code not in venues: venues[v_code] = []
                venues[v_code].append(r)

            # JRA priority sorting
            v_options = sorted(list(venues.keys()), key=lambda x: int(x))
            def format_v(c):
                return f"{VENUE_NAMES.get(c, c)} ({len(venues[c])}R)"

            # 全場URL（●シグナル対応のため）
            for rr in race_list:
                r_id = rr['race_id']
                domain = get_netkeiba_domain(r_id)
                all_race_urls.append(f"https://{domain}/race/shutuba.html?race_id={r_id}")

            # 競馬場選択 + スキャンモード
            col_sv1, col_sv2 = st.columns([3, 1])
            with col_sv1:
                selected_v = st.selectbox(
                    "スキャンする競馬場を選択…（単場内パターンのみ）",
                    v_options, format_func=format_v, key='rpps_selected_venue'
                )
            with col_sv2:
                st.write("")
                scan_mode = st.radio(
                    "スキャン範囲",
                    options=['single', 'all'],
                    format_func=lambda x: {
                        "single": "🏠 選択場のみ",
                        "all":    "🌍 全開催場 (●一括判定)"
                    }.get(x, x),
                    key='rpps_scan_mode',
                    help='●シグナルは各場またぎなので、「全開催場」で実行することで正確に判定できます。'
                )

            if selected_v:
                for r in venues[selected_v]:
                    r_id = r['race_id']
                    domain = get_netkeiba_domain(r_id)
                    selected_race_urls.append(f"https://{domain}/race/shutuba.html?race_id={r_id}")

        st.divider()

        col_l, col_r = st.columns([1, 2])
        with col_l:
            entity = st.radio("👤 比較対象", options=["jockey", "trainer", "both"], index=0,
                              format_func=lambda x: {"jockey": "🏇 騎手", "trainer": "🏋 厩舎", "both": "🔀 両方"}.get(x, x),
                              key='rpps_entity', horizontal=True)
            min_patterns = st.number_input("🎯 最低パターン数", min_value=1, max_value=5, value=1, step=1, key="rpps_min_pat")

        # 設計変更：●シグナルと1日1鞍限定判定の正確性を期すため、常に全場のデータを取得・統合してから判定する
        # スキャン自体は常に全場で行い、表示のみを切り替える
        active_scan_urls = all_race_urls
        scan_mode_val = st.session_state.get('rpps_scan_mode', 'single')
        if scan_mode_val == 'all':
            scan_mode_label = f"全開催場 ({len(all_race_urls)}レース)"
        else:
            scan_mode_label = f"選択場 ({len(selected_race_urls)}レース) ※背景で全場統合判定を実行"

        with col_r:
            st.info(f'''
            **現在の設定**: **{scan_mode_label}** をスキャン対象としています。

            ⚠️ **●シグナルは「全開催場」モードまたは複数場URLを渡した場合のみ機能**します。

            **スコア目安**:
            - 🔴 7以上: 超注目穴馬
            - 🟠 5〜6: 要警戒穴馬
            - 🟡 3〜4: 気になる馬
            - ⚪ 1〜2: 参考程度
            ''')

        st.divider()

        if 'rpps_result_df' not in st.session_state:
            st.session_state.rpps_result_df = None

        scan_btn = st.button("🔍 スキャン開始", type="primary", disabled=not active_scan_urls, key="rpps_scan_btn")

        if scan_btn and active_scan_urls:
            import scripts.race_position_scanner as rpps
            from scripts.race_position_scanner import run_scan_with_signals

            urls = active_scan_urls
            st.info(f"🔍 {len(urls)} 件のレースをスキャンします... 「全開催場」モードは●シグナルが全場対応で機能します。")
            progress_bar = st.progress(0)
            status_text = st.empty()

            def update_progress(idx, total, msg):
                if total > 0:
                    progress_bar.progress((idx + 1) / total)
                status_text.caption(msg)

            with st.spinner("スクレイピング・パターン検出中... (しばらくお待ちください)"):
                try:
                    df_result, dc_summary, bt_summary = run_scan_with_signals(
                        urls=urls,
                        entity=entity,
                        min_patterns=int(min_patterns),
                        output_csv=None,
                        progress_callback=update_progress,
                    )
                    st.session_state.rpps_result_df = df_result
                    st.session_state.rpps_dc_summary = dc_summary
                    st.session_state.rpps_bt_summary = bt_summary
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")
                    import traceback
                    st.code(traceback.format_exc())

            progress_bar.empty()
            status_text.empty()

        # --- Result Display ---
        df_res = st.session_state.rpps_result_df
        if df_res is not None:
            # 設計変更に伴うフィルタリング：単場モードの場合は選択された場のみを表示
            if st.session_state.get('rpps_scan_mode', 'all') == 'single' and 'venue' in df_res.columns:
                target_v = st.session_state.get('rpps_selected_venue')
                if target_v:
                    df_res = df_res[df_res['venue'] == target_v]

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
                    # Display only readable columns
                    display_cols = [c for c in [
                        "race_number", "horse_number", "horse_name", "special_marks",
                        "jockey", "trainer", "score",
                        "jockey_single_ride",
                        "patterns_detected", "match_details",
                        "odds", "odds_rank", "is_best_period", "warning"
                    ] if c in df_res.columns]

                    st.dataframe(
                        df_res[display_cols].style.applymap(
                            color_score, subset=["score"] if "score" in display_cols else []
                        ),
                        column_config={
                            "race_number": st.column_config.NumberColumn("R", format="%dR"),
                            "horse_number": st.column_config.NumberColumn("馬番"),
                            "horse_name": st.column_config.TextColumn("馬名"),
                            "jockey": st.column_config.TextColumn("騎手"),
                            "trainer": st.column_config.TextColumn("厩舎"),
                            "score": st.column_config.NumberColumn("🔥 スコア"),
                            "special_marks": st.column_config.TextColumn("◎●J1R シグナル"),
                            "jockey_single_ride": st.column_config.CheckboxColumn("🎯 1回乗り騎手", help="この競馬場で当日1レースのみ騎乗する騎手"),
                            "patterns_detected": st.column_config.TextColumn("検出パターン"),
                            "match_details": st.column_config.TextColumn("マッチ詳細", width="large"),
                            "odds": st.column_config.NumberColumn("単勝オッズ", format="%.1f"),
                            "odds_rank": st.column_config.NumberColumn("人気", format="%d位"),
                            "is_best_period": st.column_config.CheckboxColumn("✨ Best Period"),
                            "warning": st.column_config.TextColumn("⚠️ 警告"),
                        },
                        width='stretch',
                        hide_index=True,
                    )
                except Exception as e_disp:
                    st.warning(f"スタイルエラー: {e_disp}")
                    st.dataframe(df_res, width='stretch')

                # CSV download (special_marks を horse_name の右隣に列順を整えて出力)
                # CSV download (special_marks を horse_name の右隣に列順を整えて出力)
                _csv_col_order = [
                    "race_number", "horse_number", "horse_name", "special_marks",
                    "jockey", "trainer", "score",
                    "jockey_single_ride",
                    "patterns_detected", "match_details",
                    "odds", "odds_rank", "is_best_period", "warning"
                ]
                # df_res に存在する列だけ先頭に並べ、残りを末尾に追加
                _front = [c for c in _csv_col_order if c in df_res.columns]
                _rest  = [c for c in df_res.columns if c not in _front]
                _df_csv = df_res[_front + _rest]
                csv_bytes = _df_csv.to_csv(index=False, encoding='utf-8-sig').encode("utf-8-sig")
                st.download_button(
                    label="💾 CSVダウンロード",
                    data=csv_bytes,
                    file_name="pattern_scan_result.csv",
                    mime="text/csv",
                    key="rpps_csv_download"
                )

                st.divider()

                # --- ◎●シグナル サマリー ---
                dc_sum = st.session_state.get("rpps_dc_summary", [])
                bt_sum = st.session_state.get("rpps_bt_summary", [])

                if dc_sum or bt_sum:
                    st.subheader("◎● シグナル サマリー")

                if dc_sum:
                    st.markdown("**◎ (当日全出走 統一パターン)**")
                    df_dc = pd.DataFrame(dc_sum)
                    st.dataframe(df_dc, column_config={
                        "date": st.column_config.TextColumn("日付"),
                        "venue": st.column_config.TextColumn("場"),
                        "entity_type": st.column_config.TextColumn("対象"),
                        "entity_name": st.column_config.TextColumn("名前"),
                        "rule_type": st.column_config.TextColumn("統一タイプ"),
                        "entry_count": st.column_config.NumberColumn("出走数"),
                        "race_numbers": st.column_config.TextColumn("R番号"),
                        "horse_numbers": st.column_config.TextColumn("馬番"),
                    }, hide_index=True, width='stretch')

                if bt_sum:
                    st.markdown("**● (場跨ぎ 同一R番号 一致)**")
                    df_bt = pd.DataFrame(bt_sum)
                    st.dataframe(df_bt, column_config={
                        "date": st.column_config.TextColumn("日付"),
                        "trainer": st.column_config.TextColumn("厩舎"),
                        "race_number": st.column_config.NumberColumn("R番号"),
                        "venues": st.column_config.TextColumn("競馬場"),
                        "rule_types": st.column_config.TextColumn("一致パターン"),
                        "matched_pairs_count": st.column_config.NumberColumn("ペア数"),
                    }, hide_index=True, width='stretch')

                st.divider()
                st.subheader("📈 パターン別 検出数")
                all_patterns = []
                pat_col = "patterns_detected" if "patterns_detected" in df_res.columns else "patterns"
                for pats in df_res.get(pat_col, pd.Series()):
                    if pats:
                        all_patterns.extend(str(pats).split(","))
                if all_patterns:
                    pat_series = pd.Series(all_patterns).value_counts()
                    st.bar_chart(pat_series)

                # --- [NEW] Pattern Explanation AI Chat ---
                st.divider()
                st.subheader("🤖 パターン解説チャット")
                st.caption("検出されたパターンがなぜその配置といえるのか、AIがロジカルに解説します。")
            
                # 永続化用のセッションステート
                if 'rpps_chat_answer' not in st.session_state:
                    st.session_state.rpps_chat_answer = ""
            
                # 入力フォームでUIを安定させる
                with st.form(key="rpps_explanation_form", clear_on_submit=False):
                    pattern_query = st.text_input("質問を入力してください（例：15頭立て13番と16頭立て13番が片方循環で一致するのはなぜ？）", value="", placeholder="例）13番がなぜ片方循環（表）で一致しているのか？")
                    submit_button = st.form_submit_button("💬 質問する")
                
                if submit_button:
                    if not pattern_query:
                        st.warning("質問を入力してください。")
                    else:
                        with st.spinner("AIが解析中..."):
                            try:
                                from core.kaggle_client import KaggleChatClient
                                chat_client = KaggleChatClient(api_key=st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY"))
                            
                                if not chat_client.client:
                                    st.error("APIキーが設定されていないため、AIチャットを使用できません。")
                                else:
                                    system_prompt = """あなたは競馬の「馬番配置パターン」分析のエキスパートです。
以下の定義と数式に基づいて、ユーザーの質問に対して具体的に計算過程を示して解説してください。

【用語・解析ロジック詳細】
1. 裏番号 (ura_number): (出走頭数 - 馬番) + 1
2. P1: 裏同士: 異なる頭数のレース間で裏番号が一致。
3. P2: 裏表逆: 一方の馬番 = 他方の裏番号。
4. P3: 1の位一致: 馬番は違うが1の位が同じ。
5. P4: 片方循環: 
    - 大きい頭数のレース(N)の馬番(X)を、小さい頭数のレース(M)の頭数で割った余りで投影。
    - 計算式: projected = ((X - 1) % M) + 1
    - この projected が小さい頭数のレースの馬番（表）または裏番号（裏）と一致する場合。

【回答時の注意】
- 必ず質問にある数字を使って計算式を書いてください。
- 「片方循環(表)」であれば、大きい頭数から算出した projected が、小さい頭数側の馬番と等しいことを説明してください。
- 丁寧な日本語で回答してください。
"""
                                    j_answer = chat_client.generate_content(
                                        contents=[system_prompt, f"ユーザーの質問: {pattern_query}"],
                                        temperature=0.2
                                    )
                                    st.session_state.rpps_chat_answer = j_answer
                            except Exception as e:
                                st.error(f"AI解析中にエラーが発生しました: {e}")

                # 答えがある場合は表示
                if st.session_state.rpps_chat_answer:
                    st.markdown("### 📝 AIの解説")
                    st.markdown(st.session_state.rpps_chat_answer)
                    st.success("解説が完了しました。")
                    if st.button("🗑️ 解説を消去"):
                        st.session_state.rpps_chat_answer = ""
                        st.rerun()

    # ──────────────────────────────────────────────
    # 📦 📦 データ保管庫 (Storage Hub) タブ
    # ──────────────────────────────────────────────

    with nlab_tab4:
        st.subheader("🎯 馬番配置AI — 3層構造 意思決定エンジン")
        st.caption("設計思想：「どの馬が来るか」ではなく「市場の歪みを拾う」AI")

        bango_tab1, bango_tab2, bango_tab3, bango_tab4 = st.tabs([
            "🏟️ Layer1 レース選別",
            "🐴 Layer2 馬抽出（配置スコア）",
            "🎫 Layer3 馬券最適化",
            "📖 スコア設定",
        ])

        # ------ Layer1：レース選別 ------
        with bango_tab1:
            st.markdown("#### レース選別 — このレースを買う価値があるか？")
            st.info("堅すぎるレース・ノイズが多いレースを除外し、配置理論が効く局面のみを選別します。")

            col1, col2, col3 = st.columns(3)
            with col1:
                bango_head_count = st.number_input("頭数", min_value=2, max_value=18, value=16,
                                                    key="bango_head_count")
                bango_race_class = st.selectbox("クラス",
                    ["未勝利", "1勝クラス", "2勝クラス", "3勝クラス", "オープン", "重賞"],
                    key="bango_race_class")
            with col2:
                bango_pop_conc = st.slider("1位人気の単勝支持率 %", 10, 80, 30, key="bango_pop_conc")
                bango_track_bias = st.selectbox("脚質偏り",
                    ["バランス型", "先行有利", "差し有利", "逃げ有利"], key="bango_track_bias")
            with col3:
                bango_venue = st.selectbox("競馬場",
                    ["東京", "中山", "阪神", "京都", "中京", "小倉", "函館", "札幌", "福島", "新潟"],
                    key="bango_venue")
                bango_track_cond = st.selectbox("馬場状態", ["良", "稍重", "重", "不良"],
                                                 key="bango_track_cond")

            if st.button("🔍 レース価値を判定", type="primary", key="bango_layer1_btn"):
                score = 50
                if bango_head_count >= 14: score += 15
                elif bango_head_count <= 8: score -= 15
                if bango_pop_conc >= 50: score -= 20
                elif bango_pop_conc <= 25: score += 10
                if bango_track_cond in ["重", "不良"]: score += 10
                if bango_track_bias in ["先行有利", "逃げ有利"]: score -= 5

                race_value = min(100, max(0, score))
                collapse_score = min(100, max(0,
                    (15 if bango_head_count >= 14 else 0) +
                    (20 if bango_track_bias == "先行有利" and bango_head_count >= 14 else 0) +
                    (10 if bango_track_cond in ["重", "不良"] else 0)
                ))
                avoid = race_value < 40

                col_a, col_b, col_c = st.columns(3)
                color = "🟢" if race_value >= 60 else ("🟡" if race_value >= 40 else "🔴")
                col_a.metric("レース期待値スコア", f"{color} {race_value} / 100")
                col_b.metric("崩壊スコア（波乱度）", f"{collapse_score} / 100")
                col_c.metric("判定", "✅ 勝負レース" if not avoid else "⛔ 見送り推奨")
                if avoid:
                    st.warning("このレースは見送りを推奨します。")
                elif race_value >= 70:
                    st.success("高期待値レースです。Layer2 へ進んでください。")
                else:
                    st.info("配置スコアが高い馬がいれば検討可。")

        # ------ Layer2：馬抽出 ------
        with bango_tab2:
            st.markdown("#### 馬抽出 — 市場が過小評価している馬を見つける")

            num_horses = st.number_input("出走頭数", 2, 18, 8, key="bango_num_horses")

            cols_hdr = st.columns([1, 2, 2, 2, 2, 2])
            for h_lbl, c in zip(["馬番", "馬名", "人気", "単勝オッズ", "◎", "●"], cols_hdr):
                c.markdown(f"**{h_lbl}**")

            horse_data = []
            for i in range(int(num_horses)):
                cols = st.columns([1, 2, 2, 2, 2, 2])
                bn = cols[0].number_input("馬番", 1, 18, i+1, key=f"bango_bn_{i}",
                                           label_visibility="collapsed")
                nm = cols[1].text_input("馬名", f"馬{i+1}", key=f"bango_nm_{i}",
                                         label_visibility="collapsed")
                nk = cols[2].number_input("人気", 1, 18, i+1, key=f"bango_nk_{i}",
                                           label_visibility="collapsed")
                od = cols[3].number_input("単勝オッズ", 1.0, 999.9, float(5+i*3), 0.1,
                                           key=f"bango_od_{i}", label_visibility="collapsed")
                mr = cols[4].checkbox("◎", key=f"bango_mr_{i}")
                tm = cols[5].checkbox("●", key=f"bango_tm_{i}")
                horse_data.append({"馬番": bn, "馬名": nm, "人気": nk,
                                   "単勝オッズ": od, "◎": mr, "●": tm})

            st.markdown("---")
            st.markdown("#### 配置パターン入力")
            pc1, pc2 = st.columns(2)
            with pc1:
                ura_doshi = st.text_input("裏同士（馬番カンマ区切り）", key="bango_ura_doshi",
                                           placeholder="例: 3,5")
                ura_hyou  = st.text_input("裏表逆（馬番カンマ区切り）", key="bango_ura_hyou",
                                           placeholder="例: 1,16")
            with pc2:
                ichinohi  = st.text_input("一の位被り（馬番カンマ区切り）", key="bango_ichi",
                                           placeholder="例: 3,13")
                henhou    = st.text_input("片方循環（馬番カンマ区切り）", key="bango_hen",
                                           placeholder="例: 7,15")

            if st.button("🐴 配置スコアを算出", type="primary", key="bango_layer2_btn"):
                import math as _bmath
                def _bango_parse(s):
                    try: return set(int(x.strip()) for x in s.split(",") if x.strip())
                    except: return set()

                ura_set  = _bango_parse(ura_doshi)
                hyou_set = _bango_parse(ura_hyou)
                ichi_set = _bango_parse(ichinohi)
                hen_set  = _bango_parse(henhou)

                results = []
                for h in horse_data:
                    bn = h["馬番"]; sc = 0; patterns = []
                    if bn in ura_set:  sc += 3; patterns.append("裏同士(3pt)")
                    if bn in hyou_set: sc += 3; patterns.append("裏表逆(3pt)")
                    if bn in ichi_set: sc += 1; patterns.append("一の位被り(1pt)")
                    if bn in hen_set:  sc += 4; patterns.append("片方循環(4pt)")
                    if h["◎"]:         sc += 6; patterns.append("◎マーク(+6pt)")
                    if h["●"]:         sc += 4; patterns.append("●マーク(+4pt)")
                    if h["人気"] >= 7: sc += 1; patterns.append("人気薄(+1pt)")
                    value = round(sc * _bmath.log(max(1.1, h["単勝オッズ"])), 2)
                    results.append({
                        "馬番": bn, "馬名": h["馬名"], "人気": h["人気"],
                        "単勝オッズ": h["単勝オッズ"], "配置スコア": sc,
                        "期待値スコア": value,
                        "該当パターン": " / ".join(patterns) if patterns else "—",
                    })

                df_bango = pd.DataFrame(results).sort_values("期待値スコア", ascending=False)
                st.dataframe(df_bango, width='stretch')
                st.session_state["bango_results"] = df_bango.to_dict("records")

                top = df_bango[df_bango["配置スコア"] > 0]
                if not top.empty:
                    st.success(
                        f"注目馬：{top.iloc[0]['馬名']}（{top.iloc[0]['馬番']}番）"
                        f"— 期待値スコア {top.iloc[0]['期待値スコア']}"
                    )

        # ------ Layer3：馬券最適化 ------
        with bango_tab3:
            st.markdown("#### 馬券最適化 — 単・複・ワイド・見送りを自動判定")
            if "bango_results" not in st.session_state:
                st.warning("先に Layer2 で配置スコアを算出してください。")
            else:
                df3 = pd.DataFrame(st.session_state["bango_results"])
                df3 = df3.sort_values("期待値スコア", ascending=False)
                st.dataframe(
                    df3[["馬番", "馬名", "人気", "単勝オッズ", "配置スコア", "期待値スコア"]],
                    width='stretch'
                )
                st.markdown("---")
                st.markdown("#### 推奨券種")
                for _, row in df3[df3["配置スコア"] > 0].iterrows():
                    od = row["単勝オッズ"]; sc = row["配置スコア"]
                    if sc >= 8 and od >= 10:
                        adv = "🎯 **単勝** 推奨（高スコア×高オッズ）"
                    elif sc >= 5 and od >= 5:
                        adv = "📗 **複勝＋ワイド** 推奨（安定回収）"
                    elif sc >= 3:
                        adv = "📘 **ワイド相手** として採用"
                    else:
                        adv = "⚪ 様子見"
                    st.write(
                        f"**{int(row['馬番'])}番 {row['馬名']}**"
                        f"（人気{int(row['人気'])} / {od}倍）→ {adv}"
                    )
                st.markdown("---")
                bankroll = st.number_input("本日の軍資金（円）", 100, 100000, 3000, 100,
                                            key="bango_bankroll")
                kelly = st.slider("ケリー基準（使用割合 %）", 5, 30, 10, key="bango_kelly")
                bet = int(bankroll * kelly / 100 / 100) * 100
                st.info(f"1点あたりの目安：**{bet:,}円**（{kelly}%基準）")

        # ------ スコア設定 ------
        with bango_tab4:
            st.markdown("""
            | パターン | ベーススコア | 加算条件 | 加点 |
            |---|---|---|---|
            | 裏同士 / 裏表逆 | 3pt | 騎手・厩舎の両方で一致 | +4pt |
            | 片方循環 | 4pt | 3種類以上のパターン重複 | +5pt |
            | 一の位被り | 1pt | 7番人気以下の人気薄 | +1pt |
            | ◎マーク | +6pt | 全出走が同一配置タイプ | 最優先 |
            | ●マーク | +4pt | 異競馬場・同レース番号・同配置 | 高評価 |
            """)
            st.markdown("""
            #### 設計3原則
            1. **市場の歪みを拾う** — オッズが過小評価している馬を狙う
            2. **配置スコアはレース選別と結合して初めて意味を持つ**
            3. **買い方（券種・点数・配分）で成績は大きく変わる** — Layer3を必ず通す
            """)


# ──────────────────────────────────────────────
# 💾 💾 ロジック置き場
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
            st.button("✅ はい", on_click=execute_action, key="confirm_action_yes", width='stretch')
        with c_no:
            st.button("❌ キャンセル", on_click=cancel_action, key="confirm_action_no", width='stretch')
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
    if st.button("✨ 新規作成 (クリア)", width='content'):
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


# ──────────────────────────────────────────────
# 📦 📦 データ保管庫 (Storage Hub) タブ
# ──────────────────────────────────────────────
if nav == "📦 データ保管庫":
    from core import history_manager
    from calendar import monthcalendar, month_name
    from datetime import date

    st.header("📦 📦 データ保管庫 (Storage Hub)")
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
            st.dataframe(race_summary, width='stretch')

            with st.expander("📋 生データを表示（全カラム）"):
                st.dataframe(df_date, width='stretch')
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
                st.dataframe(uploaded_df.head(10), width='stretch')

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
