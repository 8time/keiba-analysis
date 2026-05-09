import sys, io
sys.setrecursionlimit(10000) # Increased to handle Torch initialization
import os
import re
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
import concurrent.futures
import main
import numpy as np
import time
import math
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# Core functionality imports
from core import scraper
try:
    importlib.reload(scraper)
except:
    pass
from core import calculator
try:
    importlib.reload(calculator)
except:
    pass
from core import race_analysis_tools
try:
    importlib.reload(race_analysis_tools)
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
from core import jockey_analyzer
try:
    importlib.reload(jockey_analyzer)
except:
    pass
from core import trainer_tactics
try:
    importlib.reload(trainer_tactics)
except:
    pass
from core import jockey_tactics
try:
    importlib.reload(jockey_tactics)
except:
    pass

# ──────────────────────────────────────────────
# 起動時ボーナスキャッシュ初期化
# Settingsタブを開かなくても分析時にボーナスが反映されるよう
# モジュールロード直後に一度だけ実行する
# ──────────────────────────────────────────────
try:
    from core.jockey_analyzer import (
        _DBKEIBA_BONUS_CACHE as _STARTUP_CACHE,
        JOCKEY_TENDENCY_DB   as _STARTUP_JTDB,
        get_tendency_as_bonus_dict as _startup_get_tendency,
        load_bonus_csv             as _startup_load_csv,
    )
    # Step1: 組み込み傾向DBを自動ロード（未ロードのときのみ）
    if not _STARTUP_CACHE:
        for _st_jid, _st_data in _STARTUP_JTDB.items():
            _STARTUP_CACHE[_st_jid] = _startup_get_tendency(_st_jid)

    # Step2: data/bonus_conditions.csv があれば上書きロード（CSV優先）
    _startup_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "data", "bonus_conditions.csv")
    if os.path.exists(_startup_csv):
        _startup_load_csv(_startup_csv)
except Exception:
    pass


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

# === 🔬 スコアリングシグナル: 当日JRAレースをスキャンしてJ◎/T●を取得 ===
@st.cache_data(ttl=600, show_spinner=False)
def _fetch_daily_signals(rid: str, race_date_str: str):
    """当日の全JRAレースをスキャンしてシグナルmap {umaban: {marks,j_dc,t_bullet}} を返す。
    race_date_str: YYYYMMDD 形式の実際のカレンダー日付"""
    try:
        from core.scraper import get_race_list_for_date
        from scripts.race_position_scanner import run_scan_with_signals
        race_list = get_race_list_for_date(race_date_str)
        if not race_list:
            return {}
        # JRA中央のみ (venue 01-10)
        urls = []
        for r in race_list:
            r_id = r['race_id'] if isinstance(r, dict) else str(r)
            vc = r_id[4:6] if len(r_id) == 12 else '99'
            if vc.isdigit() and 1 <= int(vc) <= 10:
                urls.append(f"https://race.netkeiba.com/race/shutuba.html?race_id={r_id}")
        if not urls:
            return {}
        df_sig, _, _ = run_scan_with_signals(urls=urls, entity='both', min_patterns=1, output_csv=None)
        if df_sig is None or df_sig.empty:
            return {}
        # 対象レースの馬のみ抽出（min_patterns=1で検出された馬のみ入る）
        sig_map = {}
        if 'race_id' in df_sig.columns:
            df_target = df_sig[df_sig['race_id'] == rid]
        else:
            df_target = pd.DataFrame()
        for _, row in df_target.iterrows():
            uma = int(row.get('horse_number', 0))
            sig_map[uma] = {
                'marks':    str(row.get('special_marks', '')),
                'j_dc':     bool(row.get('jockey_dc_flag', False)),
                't_bullet': bool(row.get('trainer_bullet_flag', False)),
                'score':    float(row.get('score', 0)),  # スキャナー総合スコア
            }
        return sig_map
    except Exception as _e:
        import logging
        logging.getLogger(__name__).warning(f"[Signal] fetch failed: {_e}")
        return {}

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
            "🧠 MAGIシステム",
            "🎓 MAGI回顧学習",
            "💰 BetSync（資金管理）",
            "🔍 Race Scanner (Batch)",
            "🧹 消去フィルター",
            "📊 History & Review",
            "🧪 新ロジックテスト(FEW+マクリ)",
            "🧪 テスト",
            "🤓 N氏の研究室",
            "🏇 騎手分析Pro",
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
        *   **🦁 (ライオン): 先行馬** (過去の平均位置取りが4番手以内かつ上位3頭まで)
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
        
    if 'persisted_main_race_id' in st.session_state:
        st.session_state['main_race_id_input'] = st.session_state['persisted_main_race_id']
    elif 'main_race_id_input' not in st.session_state:
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
        st.session_state['persisted_main_race_id'] = st.session_state['main_race_id_input']
        
        # Always clear stale advanced data when the ID is touched (prevent cross-race leakage)
        if 'test_adv_data' in st.session_state:
            del st.session_state['test_adv_data']

    # Input Layout
    col1, col2 = st.columns([1, 2])
    with col1:
        race_id_input = st.text_input("Race ID (Netkeiba)", key='main_race_id_input', on_change=_on_main_race_id_change)
        st.session_state['persisted_main_race_id'] = race_id_input
        
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
                st.session_state['persisted_main_race_id'] = str(rid)
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

    # --- 他タブで df が消されていた場合、tab1専用バックアップから自動復元 ---
    if (
        st.session_state.get('df') is None
        and st.session_state.get('tab1_df') is not None
        and st.session_state.get('tab1_analyzed_id') == race_id_input
    ):
        st.session_state['df'] = st.session_state['tab1_df'].copy()

    if analyze_btn or ("race_id" in query_params and race_id_input == default_id) or st.session_state.get('tab1_analyzed_id') == race_id_input:
        # Determine if we need to fetch fresh data from the web
        # Fetch if analyze button is pressed, OR if it's a new race, OR if df is missing
        must_fetch = analyze_btn or st.session_state.get('tab1_analyzed_id') != race_id_input or st.session_state.get('df') is None
        
        if must_fetch:
            with st.spinner("Fetching data from web..."):
                df = scraper.get_race_data(race_id_input)
                # Keep metadata safe from pandas operations that wipe .attrs
                _meta = df.attrs.get('metadata', {}) if hasattr(df, 'attrs') else {}
                
                # --- [NEW] Fetch Bloodline and Condition Bonus ---
                try:
                    # Streamlit Cloud では 127.0.0.1 へのHTTP呼び出しができないため、直接関数を呼ぶ
                    t_type = df['CurrentSurface'].iloc[0] if 'CurrentSurface' in df.columns else None
                    d_val = df['CurrentDistance'].iloc[0] if 'CurrentDistance' in df.columns else None
                    
                    blood_json = main.get_bloodline_data(str(race_id_input), track_override=t_type, dist_override=d_val)
                    if blood_json and "data" in blood_json:
                        blood_data_list = blood_json.get("data", [])
                        if blood_data_list and df is not None and not df.empty:
                            df_blood = pd.DataFrame(blood_data_list)
                            # 馬番をキーにしてマージ (Umaban: main_df, number: blood_df)
                            df['Umaban_int'] = pd.to_numeric(df['Umaban'], errors='coerce')
                            df_blood['number_int'] = pd.to_numeric(df_blood['number'], errors='coerce')
                            # 重複馬番を除去してから左結合（重複があると行が爆発する）
                            df_blood_dedup = df_blood[['number_int', 'sire', 'broodmareSire', 'bonus']].drop_duplicates(subset=['number_int'])

                            df = df.merge(
                                df_blood_dedup,
                                left_on='Umaban_int', right_on='number_int', how='left'
                            ).drop(columns=['number_int', 'Umaban_int'])
                            
                            # Restore metadata after merge
                            if not hasattr(df, 'attrs') or df.attrs is None:
                                df.attrs = {}
                            df.attrs['metadata'] = _meta
                            
                            # APIが返した判定条件（芝_1800等）を記録
                            df.attrs['bloodline_condition'] = blood_json.get("condition", "不明")
                except Exception as ex_blood:
                    logger.warning(f"血統データの取得に失敗しました: {ex_blood}")

                # Ensure metadata is present on df
                if not hasattr(df, 'attrs') or df.attrs is None:
                    df.attrs = {}
                df.attrs['metadata'] = _meta

                # --- Bloodline列から sire/broodmareSire をフォールバック抽出 ---
                # fetch_shutuba_data() が newspaper.html から "父 / 母父" 形式で取得済みの場合に利用
                if df is not None and not df.empty and 'Bloodline' in df.columns:
                    _empty = ('', '-', '不明', 'nan', 'None')
                    if 'sire' not in df.columns: df['sire'] = '-'
                    if 'broodmareSire' not in df.columns: df['broodmareSire'] = '-'
                    for _idx in df.index:
                        _s = str(df.at[_idx, 'sire'] or '').strip()
                        _b = str(df.at[_idx, 'broodmareSire'] or '').strip()
                        if _s in _empty or _b in _empty:
                            _bl = str(df.at[_idx, 'Bloodline'] or '').strip()
                            if '/' in _bl:
                                _parts = [p.strip() for p in _bl.split('/')]
                                if len(_parts) >= 2:
                                    if _s in _empty and _parts[0] not in ('-', ''):
                                        df.at[_idx, 'sire'] = _parts[0]
                                    if _b in _empty and _parts[-1] not in ('-', ''):
                                        df.at[_idx, 'broodmareSire'] = _parts[-1]

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
                    if must_fetch:
                        # 0. Preserve metadata before calculations wipe df.attrs
                        _saved_metadata = df.attrs.get('metadata', {}) if hasattr(df, 'attrs') else {}

                        # 2. Calculate
                        df = calculator.calculate_battle_score(df)
                        df = calculator.calculate_n_index(df)
                        # --- [NEW] Race Analysis Tools Integration ---
                        df = race_analysis_tools.get_pci_summary(df)
                        # Corner Parsing & Density Score (直近走の記号パース)
                        if 'DensityScore' not in df.columns: df['DensityScore'] = 0.0
                        for i, row in df.iterrows():
                            past = row.get('PastRuns', [])
                            if past:
                                last_p = past[0].get('Passing', '-')
                                p_info = race_analysis_tools.parse_corner_passing(last_p)
                                df.at[i, 'DensityScore'] = p_info['density_score']
                        # 残り600m位置推測列を追加（過去最終走）
                        df = race_analysis_tools.add_pos600m_column(df)
                        # 展開適合度スコア / 前崩れ影響度 / 密集ペナルティラベル を計算
                        try:
                            _pace_pre = calculator.analyze_pace_profile(df)
                            _deploy_info = race_analysis_tools.get_deployment_match_rate(
                                df, _pace_pre['positional_map'], _pace_pre['pace_label']
                            )
                            df = race_analysis_tools.calculate_all_deploy_scores(
                                df,
                                positional_map=_pace_pre['positional_map'],
                                position_score_map=_pace_pre['position_score_map'],
                                rpci=_deploy_info['rpci'],
                                front_collapse_risk=_pace_pre['front_collapse_risk'],
                            )
                        except Exception as _de:
                            import logging as _log; _log.getLogger(__name__).warning(f"[DeployScore] {_de}")
                        
                        # Restore metadata to the final df
                        if not hasattr(df, 'attrs') or df.attrs is None:
                            df.attrs = {}
                        df.attrs['metadata'] = _saved_metadata

                        st.session_state['df'] = df
                        # --- tab1専用バックアップ: 他タブに移動しても復元可能にする ---
                        st.session_state['tab1_df'] = df.copy()
                        # Preserve metadata in session state
                        if hasattr(df, 'attrs') and 'metadata' in df.attrs:
                            st.session_state['race_metadata'] = df.attrs['metadata']
                        else:
                            st.session_state['race_metadata'] = {'class': '-', 'weight_rule': '-', 'holding_days': '-', 'weather': '-', 'condition': '-', 'is_handicap': False}
                        
                        # Reset vision apply flag for new race
                        if st.session_state.get('last_race_id') != race_id_input:
                            st.session_state['vision_data_applied'] = True
                            st.session_state['last_race_id'] = race_id_input
                    else:
                        # Restore metadata from df attrs if must_fetch is False
                        if hasattr(df, 'attrs') and 'metadata' in df.attrs:
                            st.session_state['race_metadata'] = df.attrs['metadata']
                        elif st.session_state.get('tab1_df') is not None and hasattr(st.session_state['tab1_df'], 'attrs') and 'metadata' in st.session_state['tab1_df'].attrs:
                            st.session_state['race_metadata'] = st.session_state['tab1_df'].attrs['metadata']

                    # --- オッズ・人気未取得 警告バナー ---
                    _pop_series = pd.to_numeric(df['Popularity'], errors='coerce') if 'Popularity' in df.columns else pd.Series(dtype=float)
                    _odds_series = pd.to_numeric(df['Odds'], errors='coerce') if 'Odds' in df.columns else pd.Series(dtype=float)
                    _pop_missing  = (_pop_series >= 99).any()
                    _odds_missing = ((_odds_series <= 0) | (_odds_series >= 9999.0)).any()
                    _pop_all_missing  = (_pop_series >= 99).all()
                    _odds_all_missing = ((_odds_series <= 0) | (_odds_series >= 9999.0)).all()

                    if _pop_missing or _odds_missing:
                        _is_early = _pop_all_missing and _odds_all_missing
                        if _is_early:
                            # 全馬取得失敗 → オッズ発売前 or レースIDが存在しない
                            st.warning(
                                "⏳ **オッズ・人気が未発表**（または現在のレースIDは存在しないか、オッズ発売前です）\n\n"
                                f"- レースID: `{race_id_input}`\n"
                                "- netkeibaのAPIが `empty free odds schedule` を返しています\n"
                                "- **通常、当日レースのオッズは前日夜〜当日朝に発売となります。**\n"
                                "- 発売後に再試行するか、下の手入力モードで手動入力してください。"
                            )
                        else:
                            # 一部取得失敗
                            _missing_count = (_pop_series >= 99).sum()
                            st.error(f"🚨 **取得エラー（部分失敗）**: {_missing_count}頭のオッズ/人気を取得できませんでした。")

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
                                    _saved_meta_manual = df.attrs.get('metadata', {}) if hasattr(df, 'attrs') else {}
                                    df = calculator.calculate_battle_score(df)
                                    df = calculator.calculate_n_index(df)
                                    df.attrs['metadata'] = _saved_meta_manual
                                    st.session_state['df'] = df
                                    st.session_state['tab1_df'] = df.copy()
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
                    
                    # 血統判定用の条件取得
                    blood_cond = df.attrs.get('bloodline_condition', '-')
                    display_cond = blood_cond.replace('_', ' ') + "m" if blood_cond != '-' else "不明"

                    evidence_list = [
                        {"項目": "コース条件", "値": display_cond, "ステータス": "✅ 血統カタログ連動"},
                        {"項目": "クラス", "値": meta.get('class', '-'), "ステータス": "✅ 実力勝負（最高峰重賞）" if any(g in str(meta.get('class', '')) for g in ['G1', 'G2', 'G3', 'GI', 'GII', 'GIII']) else ("✅ 実力勝負（紛れ少）" if 'オープン' in str(meta.get('class', '')) else ("✅ 正常（実力準拠）" if any(c in str(meta.get('class', '')) for c in ['1勝クラス', '2勝クラス', '3勝クラス']) else ("⚠️ 荒れ警戒（能力未確定）" if any(c in str(meta.get('class', '')) for c in ['新馬', '未勝利']) else "✅ 一般競走"))) if meta.get('class', '-') != '-' else "情報なし"},
                        {"項目": "斤量ルール", "値": meta.get('weight_rule', '-'), "ステータス": "⚠️ ハンデ戦: 波乱リスク高" if meta.get('is_handicap') else "✅ 定量/馬齢"},
                    ]
                    
                    # Holding days logic with regex to support venue prefix
                    hd = meta.get('holding_days', '-')
                    hd_status = "情報なし"
                    if hd != '-':
                        import re as _re
                        hd_digit = _re.search(r'\d+', str(hd))
                        if hd_digit:
                            hd_num = int(hd_digit.group())
                            if hd_num >= 7: hd_status = "🚩 馬場劣化警告（外差し有利化）"
                            else: hd_status = "✅ 良好（内枠フラット路面）"
                    evidence_list.append({"項目": "開催日数", "値": f"{hd}日目" if hd != '-' else "-", "ステータス": hd_status})
                    
                    # Weather / Condition logic
                    w_val = meta.get('weather', '-')
                    c_val = meta.get('condition', '-')
                    wc_status = "情報なし"
                    if c_val != '-':
                        if c_val in ['重', '不良']: wc_status = "⚠️ 道悪: パワー・道悪適性重視"
                        elif c_val == '稍重': wc_status = "⚠️ 稍重: 適性・時計変化に注意"
                        elif c_val == '良': wc_status = "✅ 正常（良馬場・時計準拠）"
                    evidence_list.append({"項目": "天候/馬場", "値": f"{w_val}/{c_val}" if (w_val != '-' or c_val != '-') else "-", "ステータス": wc_status})
                    
                    # Existing items
                    evidence_list.extend([
                        {"項目": "1番人気オッズ", "値": f"{df['Odds'].min():.1f}倍" if not df.empty else "-", "ステータス": "🚩 要注意（混戦・大波乱高）" if (not df.empty and df['Odds'].min() >= 3.5) else "✅ 正常（信頼の1番人気）"},
                        {"項目": "要警戒アノマリー数", "値": f"{chaos_data.get('anomaly_count', 0)}件", "ステータス": "⚠️ 検出" if chaos_data.get('anomaly_count', 0) > 0 else "✅ 低"},
                        {"項目": "先行馬密集度", "値": "高" if "先行馬が密集" in chaos_data['reason'] else "中以下", "ステータス": "⚠️ 展開崩れ・差し追込有利" if "先行馬が密集" in chaos_data['reason'] else "✅ フラット（先行前残り注意）"}
                    ])

                    st.markdown(f"""
                        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 10px; border-left: 10px solid {rank_color}; margin-bottom: 20px;">
                            <div style="display: flex; align-items: baseline; gap: 15px;">
                                <h1 style="margin: 0; font-size: 36px; color: #333;">Race Rating: {chaos_data['rank']} | {df['RaceName'].iloc[0] if not df.empty else ''}</h1>
                                <span style="font-size: 24px; color: {rank_color}; font-weight: bold;">(Score: {chaos_data.get('chaos_score', 0):.1f})</span>
                                <span style="margin-left: auto; font-size: 20px; font-weight: bold; background: #eee; padding: 4px 12px; border-radius: 20px;">📍 {display_cond}</span>
                            </div>
                            <p style="font-size: 18px; color: #555; margin-top: 10px; line-height: 1.6;"><b>判定理由:</b> {chaos_data['reason']}</p>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    # Evidence Table
                    with st.expander("📊 判定根拠エビデンス表", expanded=True):
                        st.table(pd.DataFrame(evidence_list))

                    # --- [NEW v2] PCI & 馬群密度分析（RPCI数値・展開適合率付き）---
                    with st.expander("⚡ PCI（ペースチェンジ指数）& 展開適合分析", expanded=True):
                        try:
                            _pace_for_pci = calculator.analyze_pace_profile(df)
                            _pos_map_pci  = _pace_for_pci.get('positional_map', {})
                            _pace_lbl_pci = _pace_for_pci.get('pace_label', 'ミドル')

                            # RPCI / 展開適合率 算出
                            _deploy = race_analysis_tools.get_deployment_match_rate(df, _pos_map_pci, _pace_lbl_pci)
                            _rpci = _deploy['rpci']
                            _rpci_type = _deploy['rpci_type']
                            _match_pct = _deploy['match_rate_pct']
                            _match_horses = _deploy['match_horses']

                            # 物理的不利補正密集率
                            _sym_density = race_analysis_tools.analyze_field_density_with_symbols(df, _pos_map_pci)
                            _raw_d = _sym_density['raw_density_pct']
                            _cor_d = _sym_density['corrected_density_pct']
                            _dense_pen_n = _sym_density['dense_penalty_horses']
                            _leader_n    = _sym_density['leader_star_horses']

                            # フィールド平均PCI
                            avg_pci_val = float(df['AvgPCI'].mean()) if 'AvgPCI' in df.columns else 50.0

                            # カラーリング
                            _rpci_color = '#E63946' if _rpci <= 49.9 else ('#2A9D8F' if _rpci >= 56.0 else '#F4A261')
                            _match_color = '#2A9D8F' if _match_pct >= 60 else ('#F4A261' if _match_pct >= 40 else '#E63946')

                            # ヘッダーカード（ワンライナー）
                            st.markdown(f"""
                            <div style="background:#0f3460; color:#eee; padding:12px 18px; border-radius:10px;
                                        border-left:8px solid {_rpci_color}; margin-bottom:12px; font-family:monospace;">
                                <span style="font-size:15px;">
                                ⚡ 想定ペース: <b style="color:{_rpci_color}; font-size:18px;">{_pace_lbl_pci}</b>
                                &nbsp;|&nbsp; <b>RPCI {_rpci:.1f}</b> <span style="font-size:12px; color:#aaa;">({_rpci_type})</span>
                                &nbsp;|&nbsp; 展開適合率: <b style="color:{_match_color};">{_match_pct:.0f}%</b>
                                &nbsp;|&nbsp; 先行密集率: <b>{_raw_d:.0f}%</b>
                                <span style="font-size:12px; color:#ffb347;">→ 物理的不利補正後 <b>{_cor_d:.0f}%</b></span>
                                </span>
                            </div>
                            """, unsafe_allow_html=True)

                            # 4列メトリクス
                            _pc1, _pc2, _pc3, _pc4 = st.columns(4)
                            with _pc1:
                                st.metric("フィールド平均PCI", f"{avg_pci_val:.1f}",
                                          help="50.0がイーブン。56以上で後傾（スロー）、49以下で前傾（ハイ）")
                            with _pc2:
                                st.metric("想定RPCI", f"{_rpci:.1f}",
                                          help=f"逃げ想定馬の過去PCI平均。{_rpci_type}のペースが想定される。")
                            with _pc3:
                                st.metric("展開適合率", f"{_match_pct:.0f}%",
                                          help="RPCIと各馬の過去PCI傾向を比較した適合度。高いほど実力通りになりやすい。")
                            with _pc4:
                                st.metric("密集補正密集率", f"{_cor_d:.0f}%",
                                          help=f"記号()ペナルティ込み。単純密集率{_raw_d:.0f}%→補正後{_cor_d:.0f}% "
                                               f"（密集ペナルティ馬{_dense_pen_n}頭、先頭スペース馬{_leader_n}頭）")

                            # 展開適合馬テーブル
                            if _match_horses:
                                st.markdown("**📋 各馬の展開適合度（RPCI基準）**")
                                _mh_df = pd.DataFrame(_match_horses)
                                _mh_df['AvgPCI'] = _mh_df['AvgPCI'].round(1)
                                _match_cfg = {
                                    '馬番': st.column_config.NumberColumn(width='small'),
                                    'AvgPCI': st.column_config.NumberColumn("平均PCI", format="%.1f", width='small'),
                                    'PCIタイプ': st.column_config.TextColumn(width='medium'),
                                    '適合度': st.column_config.TextColumn(width='medium'),
                                }
                                def _highlight_match(s):
                                    return ['color:#2A9D8F; font-weight:bold' if '◎' in str(v) else
                                            'color:#F4A261' if '○' in str(v) else
                                            'color:#aaa' for v in s]
                                st.dataframe(
                                    _mh_df.style.apply(_highlight_match, subset=['適合度']),
                                    column_config=_match_cfg, use_container_width=True, hide_index=True
                                )

                            # 展開逆らい馬アラート（残り600m後方から追い込んだ馬）
                            _anom_list = race_analysis_tools.extract_anom_rushers(df, threshold_sec=0.8)
                            if _anom_list:
                                _anom_tags = ' '.join(
                                    f'<span style="background:#E6394633; color:#E63946; border:1px solid #E63946; '
                                    f'border-radius:12px; padding:2px 10px; font-size:12px; margin-right:4px;">'
                                    f'🚨 {a["馬名"]}（+{a["残り600m秒差"]:.2f}s）</span>'
                                    for a in _anom_list
                                )
                                st.markdown(f"<div style='margin-top:8px;'>⚡ 展開逆らい馬（次走注目）: {_anom_tags}</div>",
                                            unsafe_allow_html=True)
                        except Exception as _pci_ex:
                            st.caption(f"PCI分析: {_pci_ex}")

                    # ── 展開分析パネル (analyze_pace_profile) ──
                    try:
                        _pace = calculator.analyze_pace_profile(df)
                        _pace_colors = {'super_high': '#C1121F', 'high': '#E63946', 'mid': '#F4A261', 'slow': '#2A9D8F'}
                        _pace_color = _pace_colors.get(_pace['pace_estimate'], '#888')
                        _upset_pct = int(_pace['upset_prob'])
                        _upset_color = '#E63946' if _upset_pct >= 60 else ('#F4A261' if _upset_pct >= 40 else '#2A9D8F')

                        with st.expander("🏇 展開分析 & 波乱確率", expanded=True):
                            # ── ワンライナーサマリーカード ──
                            _collapse_stars = '★' * int(_pace['front_collapse_risk'] + 0.5) + '☆' * (5 - int(_pace['front_collapse_risk'] + 0.5))
                            _up_bar_filled = min(5, _upset_pct // 20)
                            _up_bar = '🔴' * _up_bar_filled + '⚪' * (5 - _up_bar_filled)
                            _wfd = _pace.get('weighted_front_density', _pace['front_density'] * 100)
                            _thr = _pace.get('front_threshold', 0.42)
                            # RPCI をここでも簡易計算（キャッシュ済み _deploy があれば使う）
                            try:
                                _rpci_hdr = _deploy['rpci']
                                _rpci_tp_hdr = _deploy['rpci_type']
                                _match_hdr = _deploy['match_rate_pct']
                            except Exception:
                                _rpci_hdr, _rpci_tp_hdr, _match_hdr = 51.0, 'ミドル', 0
                            st.markdown(f"""
                            <div style="background:#1a1a2e; color:#eee; padding:14px 18px; border-radius:10px;
                                        border-left:8px solid {_pace_color}; margin-bottom:14px; font-family:monospace;">
                                <span style="font-size:15px;">
                                🏇 想定ペース: <b style="color:{_pace_color}; font-size:18px;">{_pace['pace_label']}</b>
                                &nbsp;（<b>RPCI {_rpci_hdr:.1f}</b> / {_rpci_tp_hdr}）
                                &nbsp;|&nbsp; 展開適合率: <b style="color:{_match_color if '_match_color' in dir() else '#F4A261'};">{_match_hdr:.0f}%</b>
                                &nbsp;|&nbsp; 前崩れリスク: <b>{_collapse_stars}</b>
                                &nbsp;|&nbsp; 差し有利度: <b>{_pace['closer_advantage']}</b>
                                &nbsp;|&nbsp; 波乱確率: <b style="color:{_upset_color};">{_upset_pct}%</b> {_up_bar}
                                </span>
                            </div>
                            """, unsafe_allow_html=True)

                            # シナリオ帯
                            st.markdown(f"""
                            <div style="background:{_pace_color}22; border-left:6px solid {_pace_color};
                                        padding:10px 14px; border-radius:8px; margin-bottom:14px;">
                                <span style="font-size:14px;">{_pace['scenario']}</span>
                            </div>
                            """, unsafe_allow_html=True)

                            # 波乱要因タグ
                            if _pace.get('upset_factors'):
                                _tags_html = ' '.join(
                                    f'<span style="background:#F4A26133; color:#b85c00; border:1px solid #F4A261; border-radius:12px; padding:2px 10px; font-size:12px; margin-right:4px;">{f}</span>'
                                    for f in _pace['upset_factors']
                                )
                                st.markdown(f"<div style='margin-bottom:10px;'>⚠️ 波乱要因: {_tags_html}</div>", unsafe_allow_html=True)

                            # 指標カード（行1）
                            _pc1, _pc2, _pc3, _pc4 = st.columns(4)
                            with _pc1:
                                st.metric("先行馬頭数", f"{_pace['front_count']}頭",
                                          help=f"position_score < {_thr}（距離{meta.get('distance','?')}mに合わせた閾値）の馬")
                            with _pc2:
                                st.metric("重み付き密集率", f"{_wfd:.0f}%",
                                          help=f"ガチ先行馬ほど大きく寄与。閾値{_thr}。シンプル密集率: {_pace['front_density']*100:.0f}%")
                            with _pc3:
                                st.metric("前崩れリスク", f"{_pace['front_collapse_risk']:.1f} / 5.0",
                                          help="重み付き密集率×ペース強度から算出。3.5以上で差し有利")
                            with _pc4:
                                st.metric("差し馬有利度", _pace['closer_advantage'],
                                          help="前崩れリスクから導出")

                            # 指標カード（行2）
                            _mc1, _mc2, _mc3, _mc4 = st.columns(4)
                            with _mc1:
                                st.metric("波乱確率", f"{_upset_pct}%",
                                          help="多変数モデル: 0.40×能力差 + 0.30×ペース + 0.15×オッズ + 0.10×コース + 0.05×その他")
                            with _mc2:
                                st.metric("マクリ癖馬", f"{_pace['makuri_count']}頭",
                                          help="過去走で中団から4ポジション以上急上昇した馬")
                            with _mc3:
                                st.metric("能力分散(σ)", f"{_pace['ability_variance']:.1f}",
                                          help="BattleScore標準偏差。σ高=能力差大=固め。σ低=均衡=荒れ寄り")
                            with _mc4:
                                st.metric("上位3頭オッズ計", f"{_pace['odds_concentration']:.1f}倍",
                                          help="小さいほど固め。大きいほど分散=荒れ傾向")

                            # ── 波乱確率内訳（根拠の透明化） ──
                            _breakdown = _pace.get('upset_breakdown', {})
                            if _breakdown:
                                st.markdown("**📊 波乱確率 内訳（各因子の寄与%）**")
                                _bd_cols = st.columns(len(_breakdown))
                                for _i, (_factor, _val) in enumerate(_breakdown.items()):
                                    with _bd_cols[_i]:
                                        st.metric(_factor, f"{_val:.1f}%")
                                # プログレスバー風の棒グラフ（合計=upset_prob）
                                _total_bd = sum(_breakdown.values())
                                _bar_parts = []
                                _bd_colors = ['#E63946', '#F4A261', '#2A9D8F', '#457B9D', '#6A4C93']
                                for _i, (_factor, _val) in enumerate(_breakdown.items()):
                                    _w = round(_val / max(_total_bd, 1) * 100, 1)
                                    _c = _bd_colors[_i % len(_bd_colors)]
                                    _bar_parts.append(f'<div style="display:inline-block; width:{_w}%; background:{_c}; height:16px; title="{_factor}"></div>')
                                st.markdown(
                                    f'<div style="width:100%; border-radius:4px; overflow:hidden; margin-top:4px;">{"".join(_bar_parts)}</div>',
                                    unsafe_allow_html=True
                                )
                                st.caption(f"合計寄与={_total_bd:.1f}% → 波乱確率{_upset_pct}%（クランプ後）")

                            # ── 脚質マップ表 ──
                            if _pace['positional_map']:
                                st.markdown(f"**📍 各馬の推定脚質（閾値: score < {_thr} = 本物の先行）**")
                                _style_emoji = {'逃げ': '🔴', '先行': '🟠', '差し': '🔵', '追込': '🟣', '不明': '⚪'}
                                _style_rows = []
                                for _uma, _lbl in sorted(_pace['positional_map'].items()):
                                    _horse_row = df[df['Umaban'] == _uma]
                                    _hname = _horse_row['Name'].iloc[0] if not _horse_row.empty and 'Name' in _horse_row.columns else ''
                                    _ps = _pace['position_score_map'].get(_uma, 0.5)
                                    _true_front = '✅' if _ps < _thr else ''
                                    # 重み寄与（本物先行のみ）
                                    _w_contrib = round((_thr - _ps) * 100, 1) if _ps < _thr else 0.0
                                    _style_rows.append({
                                        '馬番': _uma,
                                        '馬名': _hname,
                                        '脚質': f"{_style_emoji.get(_lbl, '⚪')} {_lbl}",
                                        'スコア': round(_ps, 3),
                                        '先行判定': _true_front,
                                        '密集寄与': _w_contrib,
                                    })
                                _style_df = pd.DataFrame(_style_rows)
                                st.dataframe(_style_df, use_container_width=True, hide_index=True,
                                             column_config={
                                                 '馬番': st.column_config.NumberColumn(width='small'),
                                                 '脚質': st.column_config.TextColumn(width='medium'),
                                                 'スコア': st.column_config.NumberColumn(format='%.3f', width='small',
                                                     help=f"コーナー通過平均/頭数。{_thr}未満=本物の先行"),
                                                 '先行判定': st.column_config.TextColumn(width='small'),
                                                 '密集寄与': st.column_config.NumberColumn(format='%.1f', width='small',
                                                     help="重み付き密集率への寄与ポイント（先行判定馬のみ）"),
                                             })
                    except Exception as _pace_e:
                        st.caption(f"展開分析: {_pace_e}")

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
                            gap_df = res.sort_values('Popularity').reset_index(drop=True).copy()
                            gap_df['Odds_num'] = _pd_conv.to_numeric(gap_df['Odds'], errors='coerce')
                            pop_ser = _pd_conv.to_numeric(gap_df['Popularity'], errors='coerce')

                            # 断層位置を検出: 人気順で隣接する馬のオッズ比
                            _gap_positions = []  # 断層が発生する「何番人気と何番人気の間」
                            # 1〜6番人気の隣接間のみチェック（インデックス0〜4: 1-2位間〜5-6位間）
                            for _gi in range(min(5, len(gap_df) - 1)):
                                _o_cur = gap_df['Odds_num'].iloc[_gi]
                                _o_nxt = gap_df['Odds_num'].iloc[_gi + 1]
                                if _o_cur and _o_cur > 0 and _o_nxt and _o_nxt > 0:
                                    if _o_nxt / _o_cur >= 2.0:
                                        _gap_positions.append(_gi + 1)  # 0-indexedで「i+1番目の人気の前」に断層

                                                        # 各馬のOddsGapパターン判定
                            _num_gaps = len(_gap_positions)
                            _gap_set = set(_gap_positions)

                            def _classify_oddsgap(row_idx):
                                """各馬に対してオッズ断層パターンを分類する"""
                                if _num_gaps == 0:
                                    return "断層なし"

                                _has_gap_before = row_idx in _gap_set

                                # 断層D系（2箇所以上）優先判定
                                if _num_gaps >= 2:
                                    # 断層D1: 1-2間 AND 2-3間 → 1・2番人気が圧倒的に強い
                                    _is_d1 = (1 in _gap_set and 2 in _gap_set)
                                    # 断層D2: 2-3間 AND 3-4間 → 2・3番人気を主軸に
                                    _is_d2 = (2 in _gap_set and 3 in _gap_set)

                                    if _has_gap_before:
                                        if _is_d1 and row_idx in (1, 2):
                                            return "断層D1"
                                        if _is_d2 and row_idx in (2, 3):
                                            return "断層D2"
                                        return "断層D"
                                    return "-"

                                # 断層が1箇所のみ
                                if not _has_gap_before:
                                    return "-"

                                if row_idx == 1:
                                    return "断層A"
                                if row_idx == 2:
                                    return "断層B"
                                if 3 <= row_idx <= 5:
                                    return "断層C"

                                return "-"

                            gap_df['OddsGap'] = [_classify_oddsgap(_i) for _i in range(len(gap_df))]

                            # 断層D判定: 2箇所以上断層がある場合、全行を「断層D」にする（先頭行判定を上書き）
                            if _num_gaps >= 2:
                                gap_df['OddsGap'] = gap_df['OddsGap'].apply(
                                    lambda v: "断層D" if v not in ["-", "断層なし"] else v
                                )
                                # 断層D の場合は断層位置の直後の馬にのみ表示（全馬には付けない）
                                gap_df['OddsGap'] = [
                                    "断層D" if (_i in _gap_positions) else
                                    ("断層なし" if _num_gaps == 0 else "-")
                                    for _i in range(len(gap_df))
                                ]

                            # ここでマージ
                            res = res.merge(gap_df[['Umaban', 'OddsGap']], on='Umaban', how='left')
                            res['OddsGap'] = res['OddsGap'].fillna('-')

                            # OddsGap はラベル文字列のまま（断層A, 断層B, ... 断層なし, -）
                            # バッジパネル側でホバー説明＋クリック画像を実装
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
                                current_jockey = str(row.get('Jockey', '')).strip()
                                prev_jockey = str(last_run.get('PrevJockey', '') or last_run.get('Jockey', '')).strip()
                                # 名前の部分一致も考慮（例: "川田将雅" vs "川田"）
                                def _jockey_same(a, b):
                                    if not a or not b or b in ('-', ''):
                                        return True  # 不明は同一扱い
                                    return a == b or a in b or b in a
                                if current_jockey and prev_jockey and not _jockey_same(current_jockey, prev_jockey):
                                    j_flag = f"乗替({prev_jockey}→{current_jockey})"

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
                        try:
                            from core.odds_tracker import OddsTracker
                            from core.odds_analyzer import OddsAnalyzer
                            _tracker = OddsTracker()
                            _analyzer = OddsAnalyzer()

                            # ── 操作ボタン行 ──
                            _ob1, _ob2 = st.columns([2, 1])
                            with _ob1:
                                st.caption("「📥 記録」を押すたびにスナップショットを保存。複数回記録すると推移グラフが表示されます。")
                            with _ob2:
                                if st.button("📥 現在オッズを記録", key="btn_record_odds_v4"):
                                    with st.spinner("取得中..."):
                                        _cnt = _tracker.track(race_id_input)
                                    if _cnt > 0:
                                        st.success(f"✅ {_cnt}件を記録しました")
                                        st.rerun()
                                    else:
                                        st.error("取得失敗 — ネットワーク/レースID確認")

                            _history_df = _tracker.get_history_df(race_id_input)

                            # ── 最新スナップショット表示 ──
                            st.markdown("#### 📊 最新オッズスナップショット")
                            _latest_odds_df = _tracker.get_latest_odds_df(race_id_input)
                            if not _latest_odds_df.empty:
                                # メインdfの馬名をマージ
                                if 'Umaban' in df.columns and 'Name' in df.columns:
                                    _name_map = df[['Umaban', 'Name']].copy()
                                    _name_map['Umaban'] = pd.to_numeric(_name_map['Umaban'], errors='coerce')
                                    _latest_odds_df['Umaban'] = pd.to_numeric(_latest_odds_df['Umaban'], errors='coerce')
                                    _latest_odds_df = _latest_odds_df.merge(_name_map, on='Umaban', how='left')
                                # 表示カラム整理
                                _disp_cols = [c for c in ['Umaban', 'Name', 'Win Odds', 'Show Odds (Min)', 'Popularity'] if c in _latest_odds_df.columns]
                                st.dataframe(_latest_odds_df[_disp_cols].sort_values('Umaban'), use_container_width=True, hide_index=True)
                            else:
                                st.info("まだ記録がありません。上の「📥 現在オッズを記録」を押してください。")

                            # ── 時系列グラフ ──
                            import altair as alt
                            if not _history_df.empty:
                                st.markdown("#### 📉 単勝オッズ推移")
                                _history_df['timestamp'] = pd.to_datetime(_history_df['timestamp'])
                                _win_hist = _history_df[_history_df['odds_type'] == 'win'].copy()
                                _snap_count = len(_win_hist['timestamp'].unique())
                                if not _win_hist.empty and _snap_count >= 2:
                                    # 馬名ラベル付け
                                    _nm = {}
                                    if 'Umaban' in df.columns and 'Name' in df.columns:
                                        _nm = {int(r['Umaban']): r['Name'] for _, r in df.iterrows() if pd.notna(r.get('Umaban'))}
                                    _win_hist['horse'] = _win_hist['umaban'].apply(lambda u: f"{int(u)}:{_nm.get(int(u), str(u))}")

                                    # 急変馬を検出（最初→最後のオッズ変化率 ±15%以上）
                                    _first = _win_hist.sort_values('timestamp').groupby('umaban')['odds_value'].first()
                                    _last  = _win_hist.sort_values('timestamp').groupby('umaban')['odds_value'].last()
                                    _change = ((_last - _first) / _first.replace(0, float('nan'))).abs()
                                    _alert_uma = set(_change[_change >= 0.15].index.tolist())

                                    # 人気上位8頭 + 急変馬に絞る（全頭は線が多すぎ）
                                    _latest_pop = _win_hist.sort_values('timestamp').groupby('umaban')['odds_value'].last().sort_values()
                                    _top8_uma = set(_latest_pop.head(8).index.tolist())
                                    _show_uma = _top8_uma | _alert_uma

                                    _win_filtered = _win_hist[_win_hist['umaban'].isin(_show_uma)].copy()

                                    # 急変フラグ列（色分け用）
                                    _win_filtered['急変'] = _win_filtered['umaban'].apply(lambda u: '🚨急変' if u in _alert_uma else '通常')

                                    _line_chart = alt.Chart(_win_filtered).mark_line(point=True).encode(
                                        x=alt.X('timestamp:T', title='記録時刻'),
                                        y=alt.Y('odds_value:Q', title='単勝オッズ', scale=alt.Scale(zero=False)),
                                        color=alt.Color('horse:N', title='馬番:馬名'),
                                        strokeDash=alt.StrokeDash('急変:N', legend=alt.Legend(title='種別')),
                                        tooltip=[
                                            alt.Tooltip('horse:N', title='馬'),
                                            alt.Tooltip('odds_value:Q', title='オッズ', format='.1f'),
                                            alt.Tooltip('timestamp:T', title='時刻', format='%H:%M:%S'),
                                            alt.Tooltip('急変:N', title='状態'),
                                        ]
                                    ).interactive()
                                    st.altair_chart(_line_chart, use_container_width=True)

                                    # 急変馬サマリー
                                    if _alert_uma:
                                        _alert_rows = []
                                        for _u in sorted(_alert_uma):
                                            _f = float(_first.get(_u, 0))
                                            _l = float(_last.get(_u, 0))
                                            _d = (_l - _f) / max(_f, 0.01) * 100
                                            _arrow = '📉' if _d < 0 else '📈'
                                            _alert_rows.append({'馬番': int(_u), '馬名': _nm.get(int(_u), ''), '初回': _f, '最新': _l, '変化': f"{_arrow}{_d:+.1f}%"})
                                        st.dataframe(pd.DataFrame(_alert_rows), use_container_width=True, hide_index=True)
                                    else:
                                        st.caption(f"急変馬なし（{_snap_count}スナップショット・変化率±15%未満）")

                                    if len(_show_uma) < len(_win_hist['umaban'].unique()):
                                        st.caption(f"※ 人気上位8頭 + 急変馬のみ表示（全{len(_win_hist['umaban'].unique())}頭中{len(_show_uma)}頭）")
                                else:
                                    st.caption(f"グラフ表示には2回以上の記録が必要です（現在 {_snap_count} スナップショット）")

                            # ── 異常検知 ──
                            st.markdown("#### ⚠️ 異常検知 (インサイダー・単複乖離)")
                            # 記録済みのDB ODDSで分析（単複両方ある）
                            _detect_src = _latest_odds_df if not _latest_odds_df.empty else df
                            _static_alerts = _analyzer.detect_abnormal_odds(_detect_src)
                            # 時系列の急落アラート
                            _ts_alerts = _analyzer.analyze_time_series(_history_df) if not _history_df.empty else []
                            _all_alerts = _static_alerts + _ts_alerts

                            if _all_alerts:
                                for _a in _all_alerts:
                                    _sev = _a.get('severity', 'medium')
                                    _icon = '🚨' if _sev == 'critical' else ('⚠️' if _sev == 'high' else 'ℹ️')
                                    _atype = _a.get('alert_type', '')
                                    if _atype == 'sudden_drop':
                                        st.error(f"{_icon} 馬番{_a['horse_number']}: {_a['reason']}")
                                    elif _sev == 'critical':
                                        st.error(f"{_icon} 馬番{_a['horse_number']}: {_a['reason']}")
                                    else:
                                        st.warning(f"{_icon} 馬番{_a['horse_number']}: {_a['reason']}")
                            else:
                                if _latest_odds_df.empty:
                                    st.caption("記録後に異常検知が実行されます。")
                                else:
                                    st.success("✅ 特筆すべき異常は検出されませんでした。")

                            # 記録件数サマリー
                            if not _history_df.empty:
                                _snap_count = len(_history_df['timestamp'].unique())
                                _first_ts = _history_df['timestamp'].min()
                                _last_ts = _history_df['timestamp'].max()
                                st.caption(f"📁 DB記録: {len(_history_df)}件 / {_snap_count}スナップショット（{_first_ts} 〜 {_last_ts}）")

                        except Exception as _ot_e:
                            st.error(f"時系列オッズモジュールエラー: {_ot_e}")
                            import traceback
                            st.code(traceback.format_exc(), language='text')

                    st.divider()

                    # --- [NEW] 影響率（ウェイト）設定パネル ---
                    _WEIGHTS_FILE = os.path.join(os.path.dirname(__file__), ".score_weights_main.json")
                    _weight_defaults = {
                        "NIndex": 0.0, "UIndex": 0.0, "LaboIndex": 0.0, "SpeedIndex": 0.0, "Popularity": 0.0,
                        "Strength (X)": 0.0, "Jockey": 0.0, "Training": 0.0, "Weight": 0.0, "WeightPenalty": -0.1, "WeightCarried": 0.0,
                        "Suitability": 0.0, "AvgAgari": 0.0, "Umaban": 0.0, "Waku": 0.0, "AvgPosition": 0.0, "Bloodline": 1.0,
                        "Base": 1.0, "Stress": 1.0, "ScoringSignal": 1.0, "TopBattleBonus": 0.0
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
                    
                    # --- Global Style Injection for Sidebar (To match screenshots) ---
                    st.markdown("""
                        <style>
                        [data-testid="stSidebar"] {
                            background-color: #111111;
                            color: white;
                        }
                        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
                            color: #ddd;
                        }
                        [data-testid="stSidebarNav"] span {
                            color: white !important;
                        }
                        </style>
                    """, unsafe_allow_html=True)
                    
                    sw = st.session_state['score_weights_main']
                    for k, v in _weight_defaults.items():
                        if k not in sw: sw[k] = v

                    def _make_sync_slider_sm(key_num, key_sld):
                        def _cb(): st.session_state[key_sld] = st.session_state[key_num]
                        return _cb
                    def _make_sync_num_sm(key_sld, key_num):
                        def _cb(): st.session_state[key_num] = st.session_state[key_sld]
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
                                   ("🧧 枠番%",        "Waku",         "waku"),
                                   ("🦁 平均位置取り%", "AvgPosition",  "pos"),
                                   ("🧬 血統%",       "Bloodline",    "bld"),
                                   ("基礎戦闘力%",     "Base",         "base"),
                                   ("🛡️ ストレス特性%", "Stress",       "strss")]
                    _W_GROUP4   = [("🔬 スコアリング(×倍)", "ScoringSignal", "sig")]

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
                                "NIndex": 0.6, "UIndex": 0.6, "Base": 1.0, "Suitability": 0.8,
                                "SpeedIndex": 0.8, "Popularity": 0.3, "Jockey": 0.4
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

                            max_val = 1.0
                            min_val = -1.0
                            if sw_key == "WeightPenalty": max_val = 0.0
                            if sw_key == "Base": min_val, max_val = 0.0, 10.0
                            if sw_key == "Suitability": max_val = 10.0
                            if sw_key == "SpeedIndex": max_val = 10.0
                            if sw_key == "Bloodline": max_val = 10.0
                            if sw_key == "Stress": max_val = 15.0
                            if sw_key == "Popularity": max_val = 10.0
                            if sw_key == "Stress": max_val = 15.0
                            if sw_key == "AvgAgari": max_val = 10.0
                            if sw_key == "AvgPosition": max_val = 10.0

                            # Initialize if missing with clamping safety
                            safe_val = max(float(min_val), min(float(max_val), float(cur_val)))
                            if sld_key not in st.session_state: st.session_state[sld_key] = safe_val
                            if num_key not in st.session_state: st.session_state[num_key] = safe_val

                            c1, c2 = st.columns([2, 1])
                            with c1:
                                st.slider(display_label, min_val, max_val, step=0.01, key=sld_key, on_change=_make_sync_num_sm(sld_key, num_key))
                            with c2:
                                st.number_input("", min_val, max_val, step=0.01, key=num_key, on_change=_make_sync_slider_sm(num_key, sld_key), label_visibility="collapsed")
                            
                            # Keep sw updated
                            sw[sw_key] = float(st.session_state.get(num_key, cur_val))

                    with st.expander("📊 プロ設定：総合影響率（ウェイト）設定", expanded=False):
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
                        with st.container(border=True):
                            st.markdown("#### 🔬 スコアリングシグナル")
                            st.caption("J◎(騎手◎シグナル)・T◎(厩舎◎シグナル)・T●(厩舎●シグナル)検出時に加算するボーナス。ベース各30ポイントに対し、設定した倍率(1〜10倍)が乗算されます。")
                            _sig_sld = "wsld_sm_g4sig"; _sig_num = "wnum_sm_g4sig"
                            _sig_cur = float(sw.get("ScoringSignal", 1.0))
                            _sig_cur = max(1.0, min(10.0, _sig_cur))
                            if _sig_sld not in st.session_state: st.session_state[_sig_sld] = _sig_cur
                            if _sig_num not in st.session_state: st.session_state[_sig_num] = _sig_cur
                            _sc1, _sc2 = st.columns([2, 1])
                            with _sc1:
                                st.slider("🔬 スコアリング(×倍)", 1.0, 10.0, step=0.5, key=_sig_sld,
                                          on_change=_make_sync_num_sm(_sig_sld, _sig_num))
                            with _sc2:
                                st.number_input("", 1.0, 10.0, step=0.5, key=_sig_num,
                                                on_change=_make_sync_slider_sm(_sig_num, _sig_sld),
                                                label_visibility="collapsed")
                            sw["ScoringSignal"] = float(st.session_state.get(_sig_num, _sig_cur))

                        with st.container(border=True):
                            st.markdown("#### 🏆 総合戦闘力ボーナス")
                            st.caption("BattleScore(基礎戦闘力)上位3頭の予測スコアに、入力した値をそのまま加算します")
                            _tbb_sld = "wsld_sm_tbb"; _tbb_num = "wnum_sm_tbb"
                            _tbb_cur = float(sw.get("TopBattleBonus", 0.0))
                            _tbb_cur = max(0.0, min(300.0, _tbb_cur))
                            if _tbb_sld not in st.session_state: st.session_state[_tbb_sld] = _tbb_cur
                            if _tbb_num not in st.session_state: st.session_state[_tbb_num] = _tbb_cur
                            _tb1, _tb2 = st.columns([2, 1])
                            with _tb1:
                                st.slider("🏆 上位3頭ボーナス", 0.0, 300.0, step=0.5, key=_tbb_sld,
                                          on_change=_make_sync_num_sm(_tbb_sld, _tbb_num))
                            with _tb2:
                                st.number_input("", 0.0, 300.0, step=0.5, key=_tbb_num,
                                                on_change=_make_sync_slider_sm(_tbb_num, _tbb_sld),
                                                label_visibility="collapsed")
                            sw["TopBattleBonus"] = float(st.session_state.get(_tbb_num, _tbb_cur))

                            total_w = sum(v for k, v in sw.items() if k != "TopBattleBonus")
                            if total_w > 0:
                                st.info(f"💡 合計(影響率): **{total_w:.2f}%** ｜ 🏆上位3頭ボーナス: **+{sw.get('TopBattleBonus', 0.0):.1f}**")
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
                                st.session_state['tab1_df'] = df.copy()
                                st.rerun()

                        # ─── 名前付きプリセット管理 ───────────────────────
                        import json as _json_p
                        _PRESETS_FILE = os.path.join(os.path.dirname(__file__), ".score_weights_presets.json")

                        def _load_presets():
                            # session_state キャッシュを優先（サーバーファイルが消えても保持）
                            if 'weight_presets_cache' in st.session_state:
                                return st.session_state['weight_presets_cache']
                            try:
                                if os.path.exists(_PRESETS_FILE):
                                    with open(_PRESETS_FILE, 'r', encoding='utf-8') as _f:
                                        data = _json_p.load(_f)
                                        st.session_state['weight_presets_cache'] = data
                                        return data
                            except: pass
                            return {}

                        def _save_presets(presets: dict):
                            # session_state + ファイル両方に保存
                            st.session_state['weight_presets_cache'] = presets
                            try:
                                with open(_PRESETS_FILE, 'w', encoding='utf-8') as _f:
                                    _json_p.dump(presets, _f, ensure_ascii=False, indent=2)
                            except: pass

                        st.divider()
                        st.markdown("##### 📂 名前付きプリセット管理")
                        st.caption("💡 アプリ更新後もプリセットを保持するには、定期的に「📤 エクスポート」でPCに保存してください。")
                        _presets = _load_presets()

                        # ── ロード＆削除 ──
                        if _presets:
                            _p_col1, _p_col2, _p_col3 = st.columns([3, 1, 1])
                            with _p_col1:
                                _sel_preset = st.selectbox(
                                    "保存済みプリセットを選択",
                                    options=list(_presets.keys()),
                                    key="preset_selector_main",
                                    label_visibility="collapsed",
                                )
                            with _p_col2:
                                if st.button("📂 ロード", key="btn_load_preset_main", use_container_width=True):
                                    _loaded = _presets.get(_sel_preset, {})
                                    if _loaded:
                                        for _wk, _wv in _loaded.items():
                                            _sld_k = f"wsld_sm_{_wk}"
                                            _num_k = f"wnum_sm_{_wk}"
                                            if _sld_k in st.session_state: st.session_state[_sld_k] = float(_wv)
                                            if _num_k in st.session_state: st.session_state[_num_k] = float(_wv)
                                        try:
                                            with open(_WEIGHTS_FILE, 'w', encoding='utf-8') as _wf2:
                                                _json_p.dump(_loaded, _wf2, ensure_ascii=False, indent=2)
                                        except: pass
                                        st.success(f"✅ プリセット「{_sel_preset}」をロードしました。")
                                        st.rerun()
                            with _p_col3:
                                if st.button("🗑 削除", key="btn_del_preset_main", use_container_width=True):
                                    del _presets[_sel_preset]
                                    _save_presets(_presets)
                                    st.success(f"🗑 「{_sel_preset}」を削除しました。")
                                    st.rerun()
                        else:
                            st.caption("保存済みプリセットはまだありません。")

                        # ── 名前付き保存 ──
                        _p_name_col, _p_save_col = st.columns([3, 1])
                        with _p_name_col:
                            _new_preset_name = st.text_input(
                                "新しいプリセット名",
                                placeholder="例: ダート短距離特化、差し馬優先 など",
                                key="new_preset_name_main",
                                label_visibility="collapsed",
                            )
                        with _p_save_col:
                            if st.button("💾 名前で保存", key="btn_save_preset_main", use_container_width=True):
                                if _new_preset_name.strip():
                                    _presets[_new_preset_name.strip()] = dict(sw)
                                    _save_presets(_presets)
                                    st.success(f"✅ 「{_new_preset_name.strip()}」として保存しました！")
                                    st.rerun()
                                else:
                                    st.warning("プリセット名を入力してください。")

                        # ── エクスポート / インポート（デプロイ後もデータを保持するための永続化手段）──
                        _ex_col, _im_col = st.columns(2)
                        with _ex_col:
                            if _presets:
                                _export_bytes = _json_p.dumps(_presets, ensure_ascii=False, indent=2).encode('utf-8')
                                st.download_button(
                                    label="📤 エクスポート（PCに保存）",
                                    data=_export_bytes,
                                    file_name="keiba_weight_presets.json",
                                    mime="application/json",
                                    key="btn_export_presets_main",
                                    use_container_width=True,
                                    help="このJSONファイルをPCに保存しておけば、アプリ更新後も「インポート」で完全復元できます。"
                                )
                        with _im_col:
                            _uploaded = st.file_uploader(
                                "📥 インポート（JSONファイル）",
                                type=["json"],
                                key="preset_uploader_main",
                                label_visibility="collapsed",
                                help="エクスポートしたJSONファイルをアップロードすると、プリセットを復元します。"
                            )
                            if _uploaded is not None:
                                try:
                                    _imported = _json_p.loads(_uploaded.read().decode('utf-8'))
                                    # 既存プリセットとマージ（上書き）
                                    _presets.update(_imported)
                                    _save_presets(_presets)
                                    st.success(f"✅ {len(_imported)} 件のプリセットをインポートしました！")
                                    st.rerun()
                                except Exception as _ie:
                                    st.error(f"インポートに失敗しました: {_ie}")
                        # ────────────────────────────────────────────────────

                    # === 🔬 スコアリングシグナル: 当日JRAレースをスキャンしてJ◎/T●を取得 ===
                    # シグナルスキャン実行（Analyze後。df から RaceDate を取得して正しいカレンダー日付を使う）
                    _signal_map = {}
                    _rid_str = str(race_id_input)
                    if len(_rid_str) == 12:
                        _vc = _rid_str[4:6]
                        if _vc.isdigit() and 1 <= int(_vc) <= 10:  # JRAのみ
                            # セッションキャッシュの初期化
                            if 'daily_signals_cache' not in st.session_state:
                                st.session_state['daily_signals_cache'] = {}
                            
                            # キャッシュに存在する場合はそれを使用
                            if _rid_str in st.session_state['daily_signals_cache']:
                                _signal_map = st.session_state['daily_signals_cache'][_rid_str]
                            else:
                                # df から実際の開催日を取得（例: '2026/04/04' → '20260404'）
                                _race_date_raw = ''
                                if not df.empty and 'RaceDate' in df.columns:
                                    _race_date_raw = str(df['RaceDate'].iloc[0])
                                _race_date_ymd = re.sub(r'[^\d]', '', _race_date_raw)[:8]  # YYYYMMDD
                                if len(_race_date_ymd) == 8:
                                    with st.spinner("🔬 当日シグナルスキャン中...（初回のみ時間がかかります）"):
                                        _signal_map = _fetch_daily_signals(_rid_str, _race_date_ymd)
                                        # 結果をキャッシュに保存
                                        st.session_state['daily_signals_cache'][_rid_str] = _signal_map

                    # dfに Signal 列を追加
                    df['Signal'] = df['Umaban'].apply(
                        lambda u: _signal_map.get(int(u) if pd.notna(u) else 0, {}).get('marks', '')
                    )

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

                    def _safe_float(v, default=0.0):
                        """NaN/None/空文字を安全にfloatに変換"""
                        try:
                            f = float(v)
                            return default if f != f else f  # NaN check: NaN != NaN
                        except (TypeError, ValueError):
                            return default

                    def _safe_int(v, default=0):
                        try:
                            f = float(v)
                            return default if f != f else int(f)
                        except (TypeError, ValueError):
                            return default

                    def _calc_pro_scores(row):
                        bonuses = {}
                        bonus_details = []

                        # 基礎点
                        base_pts = _safe_float(row.get('BattleScore'), 0.0)

                        # 各項目のスコア化と重み付け
                        for m_key, sw_key in [
                            ('NIndex', 'NIndex'), ('UIndex', 'UIndex'), ('LaboIndex', 'LaboIndex'),
                            ('SpeedIndex', 'SpeedIndex'), ('Strength (X)', 'Strength (X)'), ('Popularity', 'Popularity'),
                            ('TrainingScore', 'Training'), ('WeightDiff', 'Weight'),
                            ('WeightCarried', 'WeightCarried'), ('Suitability (Y)', 'Suitability'),
                            ('AvgAgari', 'AvgAgari'), ('Umaban', 'Umaban'), ('Waku', 'Waku'), ('AvgPosition', 'AvgPosition')
                        ]:
                            col_name = m_key if m_key in row else None
                            raw_val = _safe_float(row.get(col_name) if col_name else None, 0.0)
                            
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
                            
                            bonus_val = score * sw.get(sw_key, 0.0)
                            bonuses[sw_key] = bonus_val
                            if bonus_val != 0:
                                label_txt = label_map_short.get(sw_key, sw_key)
                                bonus_details.append(f"{label_txt}:{bonus_val:+.1f}")

                        # 騎手(特例)
                        j_pts = 0
                        past = row.get('PastRuns')
                        if not isinstance(past, list): past = []
                        for r in past[:10]:
                            rnk = r.get('Rank', 99)
                            if rnk == 1: j_pts += 10
                            elif rnk == 2: j_pts += 7
                            elif rnk == 3: j_pts += 5
                            elif rnk in (4, 5): j_pts += 2
                        j_score = min(100.0, float(j_pts)) if past else 50.0
                        j_bonus = j_score * sw.get('Jockey', 0.0)
                        bonuses['Jockey'] = j_bonus
                        if j_bonus != 0:
                            bonus_details.append(f"騎手:+{j_bonus:.1f}")

                        # --- Bloodline Influence ---
                        blood_raw = _safe_float(row.get('bonus'), 0.0)
                        blood_w = sw.get('Bloodline', 0.0)
                        blood_impact = blood_raw * blood_w

                        # --- ダート血統ボーナス ---
                        _DIRT_SIRES = {
                            "S": ["ナダル", "シニスターミニスター", "ヘニーヒューズ", "サウスヴィグラス",
                                  "カネヒキリ", "ゴールドアリュール", "クロフネ", "アドマイヤムーン"],
                            "A": ["ルヴァンスレーヴ", "ドレフォン", "ベストウォーリア", "ホッコータルマエ",
                                  "マジェスティックウォリアー", "スウェプトオーヴァーボード", "タイムパラドックス",
                                  "エスポワールシチー", "スマートファルコン", "キングズベスト"],
                        }
                        _DIRT_BONUS = {"S": 25.0, "A": 15.0}
                        _surface = str(row.get('CurrentSurface', ''))
                        # Bloodline列 + sire/broodmareSire列の両方を参照
                        _blood_text = " ".join([
                            str(row.get('Bloodline', '') or ''),
                            str(row.get('sire', '') or ''),
                            str(row.get('broodmareSire', '') or ''),
                        ])
                        _dirt_bonus = 0.0
                        _dirt_rank = None
                        if "ダ" in _surface and _blood_text.strip() and _blood_text.strip() != "-":
                            for _rank, _sires in _DIRT_SIRES.items():
                                if any(s in _blood_text for s in _sires):
                                    _dirt_rank = _rank
                                    _dirt_bonus = _DIRT_BONUS[_rank] * blood_w
                                    break
                        blood_impact += _dirt_bonus

                        bonuses['Bloodline'] = blood_impact
                        if blood_impact != 0:
                            _blood_detail = f"血統:{blood_impact:+.1f}"
                            if _dirt_rank:
                                _blood_detail += f"(ダート{_dirt_rank})"
                            bonus_details.append(_blood_detail)

                        # --- ScoringSignal Bonus (スキャナースコア×倍率) ---
                        uma_key = int(row.get('Umaban', 0))
                        sig_info = _signal_map.get(uma_key, {})
                        sig_w = sw.get('ScoringSignal', 1.0)
                        sig_raw = float(sig_info.get('score', 0))  # スキャナー総合スコア(Evidences+Overlap+...)
                        sig_bonus = sig_raw * sig_w
                        if sig_bonus > 0:
                            bonuses['ScoringSignal'] = sig_bonus
                            marks = sig_info.get('marks', '')
                            bonus_details.append(f"🔬{marks}(×{sig_w:.1f})=+{sig_bonus:.1f}")

                        total_bonus = sum(bonuses.values())

                        # --- Stress Multiplier (乗算デバフ: リミッター論理) ---
                        multiplier = 1.0
                        reasons = []
                        
                        # 共通データの準備
                        w_text = str(row.get('WeightHistory', ''))
                        match_w = re.search(r'(\d+)\(([-+]?\d+)\)', w_text)
                        curr_w = int(match_w.group(1)) if match_w else 0 # 当日馬体重
                        w_diff_val = int(match_w.group(2)) if match_w else 0 # 増減値
                        
                        umaban = _safe_int(row.get('Umaban'), 0)
                        waku = _safe_int(row.get('Waku'), 1)
                        avg_pos = _safe_float(row.get('AvgPosition'), 9.9)
                        surface = str(row.get('CurrentSurface') or '')
                        dist = _safe_float(row.get('CurrentDistance'), 1600.0)

                        # 条件A：キックバック・ストレス (ダート内枠+後方脚質)
                        if "ダ" in surface and waku <= 3 and avg_pos >= 8.0:
                            multiplier -= 0.08
                            reasons.append("ダート内枠の砂かぶり(精神ストレス)")
                        
                        # 条件D：ダート長距離の内枠 (1800m以上のダート1〜3枠)
                        if "ダ" in surface and dist >= 1800 and waku <= 3:
                            multiplier -= 0.10
                            reasons.append("長距離ダートの内枠(距離ストレス)")

                        # 条件B：待機・出遅れストレス (奇数枠+逃げ脚質)
                        if umaban % 2 != 0 and avg_pos <= 2.5:
                            multiplier -= 0.05
                            reasons.append("奇数枠の逃げ馬(待機ストレス)")

                        # 条件C：過剰消耗ストレス (小柄馬+大幅馬体減)
                        if curr_w > 0 and curr_w < 440 and w_diff_val <= -6:
                            multiplier -= 0.15
                            reasons.append("小柄馬の大幅馬体減(肉体ストレス)")
                        
                        multiplier = max(multiplier, 0.70)
                        
                        # 重み付き減衰量の計算 (指示書: 基礎評価に対する割合カット)
                        stress_w = sw.get('Stress', 1.0)
                        raw_potential = (base_pts * sw.get('Base', 1.0)) + total_bonus
                        weighted_loss = raw_potential * (1.0 - multiplier) * stress_w
                        
                        if weighted_loss > 0:
                            bonus_details.append(f"ストレス:({'+'.join(reasons)})")

                        # --- Horse Weight Change Penalty (Legacy Support) ---
                        w_penalty_w = sw.get('WeightPenalty', 0.0)
                        w_penalty_score = abs(float(w_diff_val)) * w_penalty_w
                        if w_penalty_score != 0:
                            total_bonus += w_penalty_score
                            bonus_details.append(f"馬体:{w_penalty_score:+.1f}")

                        # 最終スコア = (基礎点 + 全ボーナス) - 加重デバフ
                        final_score = raw_potential - weighted_loss
                        
                        return pd.Series({
                            **{f"{k}_Bonus": v for k, v in bonuses.items()},
                            'Projected Score': round(final_score, 1),
                            'Stress': -round(weighted_loss, 1),
                            'sire': row.get('sire', '-'),
                            'broodmareSire': row.get('broodmareSire', '-'),
                            'ボーナス詳細': ", ".join(bonus_details) if bonus_details else "-",
                            '_DirtBloodlineRank': _dirt_rank or '',
                            '_DirtBloodlineBonus': _dirt_bonus,
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
                    
                    # --- 🏆 総合戦闘力ボーナス: BattleScore上位3頭に加算 ---
                    _top_battle_bonus = float(sw.get('TopBattleBonus', 0.0))
                    if _top_battle_bonus > 0 and 'BattleScore' in df.columns and 'Projected Score' in df.columns:
                        _bs_col = pd.to_numeric(df['BattleScore'], errors='coerce').fillna(0)
                        _top3_idx = _bs_col.nlargest(3).index
                        df.loc[_top3_idx, 'Projected Score'] = df.loc[_top3_idx, 'Projected Score'] + _top_battle_bonus
                        # ボーナス詳細にも追記
                        for _tidx in _top3_idx:
                            _existing = str(df.at[_tidx, 'ボーナス詳細']) if 'ボーナス詳細' in df.columns else ''
                            _rank = list(_top3_idx).index(_tidx) + 1
                            _tag = f"🏆Top{_rank}:+{_top_battle_bonus:.1f}"
                            df.at[_tidx, 'ボーナス詳細'] = f"{_existing}, {_tag}" if _existing and _existing != '-' else _tag


                    # チャート用データ
                    st.session_state['current_bonus_df'] = df.copy()
                            
                    st.divider()

                    # --- 強適 Ranking Table ---
                    st.subheader("📊 強適 Ranking Table")
                    display_icon_legend()

                    view_df = df.copy()
                    # Signal列が未設定の場合に備えて補完
                    if 'Signal' not in view_df.columns:
                        view_df['Signal'] = ''

                    # ダート血統ボーナス表示は fmt_blood() に統合済み（後続で処理）

                    # ────────── Numerical Rounding (1 decimal) ──────────
                    # Ensure all numeric metrics are rounded to 1 decimal place before display
                    num_cols_to_round = ['Projected Score', 'BattleScore', 'NIndex', 'Strength (X)', 'Suitability (Y)', 'SpeedIndex', 'LaboIndex', 'UIndex', 'Stress']
                    for col in num_cols_to_round:
                        if col in view_df.columns:
                            view_df[col] = pd.to_numeric(view_df[col], errors='coerce').round(1)
                    # ───────────────────────────────────────────────────

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
                    # Show Lion icon ONLY for Top 5 horses with lowest AvgPosition
                    top_5_lion_umaban = set()
                    if 'AvgPosition' in view_df.columns and 'Umaban' in view_df.columns:
                        try:
                            # 1. 最小の3頭を特定（平均位置取り 4.0以内の馬限定）
                            pos_df = view_df[['Umaban', 'AvgPosition']].copy()
                            pos_df['AvgPosition'] = pd.to_numeric(pos_df['AvgPosition'], errors='coerce')
                            pos_df = pos_df.dropna(subset=['AvgPosition'])
                            pos_df = pos_df[(pos_df['AvgPosition'] > 0) & (pos_df['AvgPosition'] <= 4.0)]
                            
                            top_3_df = pos_df.sort_values(by='AvgPosition', ascending=True).head(3)
                            top_5_lion_umaban = set(top_3_df['Umaban'].astype(int).tolist())
                        except: pass

                    def fmt_pos(row):
                        p = row.get('AvgPosition', 99.9)
                        u = row.get('Umaban')
                        if pd.isna(p) or p >= 99.0 or p <= 0: return "-"
                        
                        # 指定された上位5頭の馬番号(Umaban)に含まれる場合のみ🦁を表示
                        icon = ""
                        try:
                            if u is not None and int(u) in top_5_lion_umaban:
                                icon = " 🦁"
                        except: pass
                        
                        return f"{p:.1f}{icon}"
                    
                    view_df['AvgPosition'] = view_df.apply(fmt_pos, axis=1)

                    # Format Bloodline (Sire / BMS + Impact + ダート血統ボーナス)
                    def fmt_blood(row):
                        def _clean(v):
                            s = str(v) if v is not None else '-'
                            return '-' if s in ('nan', 'NaN', 'None', '不明', '', '-') else s
                        sire = _clean(row.get('sire'))
                        bms = _clean(row.get('broodmareSire'))
                        impact = _safe_float(row.get('Bloodline_Bonus'), 0.0)
                        dirt_rank = str(row.get('_DirtBloodlineRank') or '')
                        dirt_bonus = _safe_float(row.get('_DirtBloodlineBonus'), 0.0)

                        if sire == '-' and bms == '-':
                            base = "-"
                        else:
                            base = f"{sire} / {bms}"
                            if impact > 0:
                                base += f" (+{impact:.1f}pt) 🔥"
                            elif impact < 0:
                                base += f" ({impact:.1f}pt) ❄️"

                        # ダート血統ボーナス表示
                        if dirt_rank and dirt_bonus > 0:
                            icon = '🔥' if dirt_rank == 'S' else '🔶'
                            base += f" {icon}+{dirt_bonus:.0f}pt(ダート{dirt_rank})"

                        return base

                    view_df['Bloodline'] = view_df.apply(fmt_blood, axis=1)
                    # 表示後に内部列を削除
                    view_df = view_df.drop(columns=['_DirtBloodlineRank', '_DirtBloodlineBonus'], errors='ignore')

                    view_df['Rank'] = range(1, len(view_df) + 1)

                    # Mask sentinel values for display (99=未取得人気, 9999.0=未取得オッズ)
                    if 'Popularity' in view_df.columns:
                        def _fmt_pop_emerald(x):
                            if pd.isna(x) or (isinstance(x, (int, float)) and x >= 99): return '-'
                            p_int = int(x)
                            if p_int == 6: return "6 💎"
                            return str(p_int)
                        view_df['Popularity'] = view_df['Popularity'].apply(_fmt_pop_emerald)
                    if 'Waku' in view_df.columns:
                        def _fmt_waku(x):
                            try:
                                w = int(x)
                                if 1 <= w <= 3: return f"内 {w}"
                                elif 6 <= w <= 8: return f"外 {w}"
                                return str(w)
                            except: return str(x)
                        view_df['Waku'] = view_df['Waku'].apply(_fmt_waku)
                    if 'Odds' in view_df.columns:
                        view_df['Odds'] = view_df['Odds'].apply(
                            lambda x: '-' if (pd.isna(x) or (isinstance(x, (int, float)) and (x >= 9999.0 or x < 0))) else f'{float(x):.1f}'
                        )

                    # Merge previous screenshot columns with latest advanced columns
                    # --- v2.02: 展開データ列を追加 ---
                    cols = ['Rank', 'Umaban', 'Waku', 'Popularity', 'Odds', 'Name', 'Jockey', 'Signal',
                            'Projected Score', 'BattleScore', 'AvgPosition',
                            'DeployScoreLabel', 'PCILabel', 'Pos600m', 'FrontCollapseEffect',
                            'DensityPenaltyLabel',
                            'OddsGap', 'Stress', 'SexAge', 'WeightHistory', 'WeightCarried',
                            'Trainer', 'Bloodline', 'JockeyChange',
                            'ボーナス詳細', 'AvgPCI', 'PCIType', 'DensityScore',
                            'NIndex', 'Strength (X)', 'Suitability (Y)',
                            'SpeedIndex', 'AvgAgari', 'Alert', 'RiskFlags']
                    view_df = view_df[[c for c in cols if c in view_df.columns]]

                    # --- Column order persistence (user_prefs.json) ---
                    import json as _json_sra
                    _prefs_path_sra = os.path.join(os.getcwd(), "user_prefs.json")
                    _saved_sra = []
                    try:
                        with open(_prefs_path_sra, 'r', encoding='utf-8') as _f:
                            _saved_sra = _json_sra.load(_f).get('single_race_col_order', [])
                    except: pass
                    
                    if _saved_sra and 'Stress' not in _saved_sra:
                        if 'OddsGap' in _saved_sra:
                            _idx = _saved_sra.index('OddsGap') + 1
                            _saved_sra.insert(_idx, 'Stress')
                        else:
                            _saved_sra.append('Stress')

                    _all_cols = list(view_df.columns)

                    _col_label_map = {
                        "Rank": "順位", "Umaban": "馬番", "Popularity": "人気",
                        "Odds": "単勝オッズ", "OddsGap": "オッズ断層",
                        "SexAge": "性別/年齢", "WeightHistory": "当日馬体重(増減)",
                        "WeightCarried": "斤量", "Trainer": "厩舎",
                        "Bloodline": "血統(父/母父)", "Jockey": "騎手",
                        "JockeyChange": "乗替", "Name": "馬名",
                        "Signal": "🔬シグナル",
                        "Projected Score": "⭐予測スコア", "ボーナス詳細": "ボーナス内訳", "NIndex": "N指数",
                        "Stress": "ストレス", "Waku": "枠",
                        "BattleScore": "🔥総合戦闘力",
                        "Strength (X)": "💪強さ(X)", "Suitability (Y)": "🎯適性(Y)",
                        "AvgPCI": "平均PCI", "PCIType": "脚質タイプ(PCI)",
                        "PCILabel": "펼 PCI適性タイプ",
                        "Pos600m": "残600m位置(秒差)",
                        "DeployScoreLabel": "⭐展開適合度",
                        "FrontCollapseEffect": "前崩れ影音度",
                        "DensityPenaltyLabel": "密集ペナルティ",
                        "DensityScore": "馬群密度スコア",
                        "SpeedIndex": "スピード指数", "AvgAgari": "上がり3F(順位)",
                        "AvgPosition": "平均位置取り", "Alert": "アラート",
                        "RiskFlags": "不安要素",
                    }

                    # Restore saved order if available
                    # 新規列(Signal等)は保存済み順の先頭に自動挿入する
                    _default_cols = _all_cols[:]
                    if _saved_sra:
                        _valid_saved = [c for c in _saved_sra if c in _all_cols]
                        # 保存済みに含まれない新列を先頭付近(Name直後)に追加
                        _new_cols = [c for c in _all_cols if c not in _valid_saved]
                        
                        # Fix: Ensure 'Waku' is forced into the display list if it's a new column
                        if 'Waku' in _new_cols:
                            try:
                                _idx = _valid_saved.index('Umaban') + 1
                                _valid_saved.insert(_idx, 'Waku')
                            except ValueError:
                                _valid_saved.insert(0, 'Waku')
                            _new_cols.remove('Waku')

                        if _new_cols and _valid_saved:
                            _insert_after = 'Signal'  # Signalを必ず含める
                            if _insert_after in _new_cols:
                                try:
                                    _idx = _valid_saved.index('Jockey') + 1
                                except ValueError:
                                    _idx = min(6, len(_valid_saved))
                                _valid_saved.insert(_idx, _insert_after)
                                _new_cols.remove(_insert_after)
                        if _valid_saved:
                            _default_cols = _valid_saved

                    _display_to_col = {_col_label_map.get(c, c): c for c in _all_cols}
                    _col_to_display = {c: _col_label_map.get(c, c) for c in _all_cols}
                    _all_display = [_col_to_display[c] for c in _all_cols]
                    _default_display = [_col_to_display[c] for c in _default_cols]

                    # ── 展開フィルター（v2.02追加） ──────────────────────── #
                    _filter_row = st.columns([1.5, 1.5, 3])
                    _deploy_filter = '全て'
                    with _filter_row[0]:
                        _deploy_filter = st.selectbox(
                            '🚦 展開フィルター',
                            options=['全て', '◎恩恵大のみ', '▲不利除外', '展開適合85+のみ'],
                            key='deploy_filter_sra',
                            help=(
                                "・◎恩恵大のみ: 前崩れやスローなどの展開利がある馬に絞り込み。\n"
                                "・▲不利除外: 逆に展開が不向き（不利）な馬をリストから消去。\n"
                                "・展開適合85+のみ: 総合的な展開適合スコアが極めて高い(85点以上)馬のみを表示します。"
                            )
                        )
                    with _filter_row[1]:
                        _avg_deploy_val = float(df['DeployScore'].mean()) if 'DeployScore' in df.columns else 0.0
                        _deploy_rank_label = ['低', '中', '高', '最高'][min(3, int(_avg_deploy_val // 25))]
                        st.markdown(
                            f"<div style='font-size:0.8em;color:#888;margin-bottom:2px;'>強適上位馬 展開適合度</div>"
                            f"<div style='font-size:1.2em;font-weight:700;white-space:nowrap;'>平均{_avg_deploy_val:.1f}（{_deploy_rank_label}）</div>",
                            unsafe_allow_html=True
                        )
                    # フィルター適用
                    _view_df_filtered = view_df.copy()
                    if _deploy_filter == '◎恩恵大のみ' and 'FrontCollapseEffect' in _view_df_filtered.columns:
                        _view_df_filtered = _view_df_filtered[_view_df_filtered['FrontCollapseEffect'].str.contains('◎', na=False)]
                    elif _deploy_filter == '▲不利除外' and 'FrontCollapseEffect' in _view_df_filtered.columns:
                        _view_df_filtered = _view_df_filtered[~_view_df_filtered['FrontCollapseEffect'].str.contains('▲', na=False)]
                    elif _deploy_filter == '展開適合85+のみ' and 'DeployScore' in df.columns:
                        _umas_85 = set(df[df['DeployScore'] >= 85]['Umaban'].astype(str).tolist())
                        if 'Umaban' in _view_df_filtered.columns:
                            _view_df_filtered = _view_df_filtered[_view_df_filtered['Umaban'].astype(str).isin(_umas_85)]
                    view_df = _view_df_filtered
                    # ─────────────────────────────────────────────────────── #

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
                        "Waku": st.column_config.TextColumn("枠", help="内(1-3), 外(6-8)の区分を表示"),
                        "Umaban": st.column_config.NumberColumn("馬番"),
                        "Popularity": st.column_config.TextColumn("人気"),
                        "Odds": st.column_config.TextColumn("単勝オッズ"),
                        "OddsGap": st.column_config.TextColumn(
                            "オッズ断層",
                            help="ホバーで詳細説明、クリックで解説画像が新タブ表示（テーブル上部のバッジをご利用ください）"
                        ),
                        "SexAge": st.column_config.TextColumn("性別/年齢"),
                        "WeightHistory": st.column_config.TextColumn("当日馬体重(増減)"),
                        "WeightCarried": st.column_config.TextColumn("斤量"),
                        "Trainer": st.column_config.TextColumn("Trainer"),
                        "Bloodline": st.column_config.TextColumn("血統(父/母父)"),
                        "Jockey": st.column_config.TextColumn("騎手"),
                        "JockeyChange": st.column_config.TextColumn("乗替"),
                        "Name": st.column_config.TextColumn("馬名"),
                        "Signal": st.column_config.TextColumn("🔬シグナル", help="J◎: 騎手◎ / T◎: 厩舎◎ / T●: 厩舎●（各30pt × ウェイト倍率）"),
                        "Projected Score": st.column_config.NumberColumn("⭐予測スコア", format="%.1f"),
                        "Stress": st.column_config.NumberColumn("ストレス", format="%.1f", help="外的・内的要因による能力減衰量。内訳ボタン（ボーナス詳細）で理由を確認できます"),
                        "ボーナス詳細": st.column_config.TextColumn("ボーナス内訳"),
                        "NIndex": st.column_config.NumberColumn("N指数", format="%.1f"),
                        "BattleScore": st.column_config.NumberColumn("🔥 総合戦闘力", format="%.1f"),
                        "Strength (X)": st.column_config.NumberColumn("💪 強さ(X)", format="%.1f", help="netkeiba タイム指数ベースの偏差能力 (最高100)"),
                        "Suitability (Y)": st.column_config.NumberColumn("🎯 適性(Y)", format="%.1f"),
                        "AvgPCI": st.column_config.NumberColumn("平均PCI", format="%.1f",
                                    help="50.0が均等。56以上で後傾、490以下で前傾。"),
                        "PCIType": st.column_config.TextColumn("脚質タイプ(PCI)"),
                        "Pos600m": st.column_config.NumberColumn("残600m位置", format="%+.2f秒",
                                    help="遠走過去走の残り600m地点の先頭との秒差。3前傾=負値，追い込み=正値，+1.0s以上は展開逆らい注目馬。"),
                        "DensityScore": st.column_config.NumberColumn("馬群密度スコア", format="%.1f"),
                        "DeployScoreLabel": st.column_config.TextColumn(
                            "⭐展開適合度",
                            help="(位置取り×0.40)+(展開マッチ×0.35)+(密集補正×0.25)。★=80以上"
                        ),
                        "PCILabel": st.column_config.TextColumn(
                            "펼 PCI適性タイプ",
                            help="持続型(52.3)の形式で表示。数値が逃げ馬PCI（RPCI）に近いほど展開適合。"
                        ),
                        "FrontCollapseEffect": st.column_config.TextColumn(
                            "前崩れ影音度",
                            help="◎恣恵大=展開恵身 △不利=展開不向き"
                        ),
                        "DensityPenaltyLabel": st.column_config.TextColumn(
                            "密集ペナルティ",
                            help="+値=密集被り（不利）、-値=先頭/余裕"
                        ),
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
                                    if val >= 85: colors.append("background-color: #d9480f; color: white; font-weight: bold") 
                                    elif val >= 75: colors.append("background-color: #f76707; color: white; font-weight: bold") 
                                    elif val >= 65: colors.append("background-color: #2b8a3e; color: white; font-weight: bold") 
                                    elif val >= 50: colors.append("background-color: #1864ab; color: white; font-weight: bold") 
                                    else: colors.append("background-color: #ebfbee; color: #2b8a3e;") 
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

                        def color_popularity(s):
                            # Special highlight for 6th Favorite (The "Emerald" horse)
                            colors = []
                            for val in s:
                                if "6 💎" in str(val):
                                    colors.append("background-color: #2b8a3e; color: #fab005; font-weight: bold")
                                else:
                                    colors.append("")
                            return colors
                        
                        def color_pci(s):
                            colors = []
                            for v in s:
                                try:
                                    val = float(v)
                                    if val >= 56: colors.append("background-color: #ffe8cc; color: #d9480f; font-weight: bold") 
                                    elif val <= 49.9: colors.append("background-color: #e3f2fd; color: #1565c0; font-weight: bold") 
                                    else: colors.append("")
                                except: colors.append("")
                            return colors

                        styled_df = view_df.style
                        if 'Popularity' in view_df.columns:
                            styled_df = styled_df.apply(color_popularity, axis=0, subset=['Popularity'])
                        
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
                        
                        if 'AvgPCI' in view_df.columns:
                            styled_df = styled_df.apply(color_pci, axis=0, subset=['AvgPCI'])

                        def color_waku(s):
                            """枠色設定: 1=白, 2=黒, 3=赤, 4=青, 5=黄, 6=緑, 7=橙, 8=桃"""
                            bg_map = {
                                1: "#ffffff", 2: "#000000", 3: "#ff0000", 4: "#0000ff",
                                5: "#ffff00", 6: "#008000", 7: "#ffa500", 8: "#ffc0cb"
                            }
                            # 黒・赤・青・緑は背景が濃いので文字を白にする。白・黄・桃・橙は黒文字。
                            text_map = {
                                1: "#000000", 2: "#ffffff", 3: "#ffffff", 4: "#ffffff",
                                5: "#000000", 6: "#ffffff", 7: "#000000", 8: "#000000"
                            }
                            colors = []
                            for v in s:
                                try:
                                    # 「内 1」などの文字列から数字部分を抽出
                                    sv = str(v)
                                    w_match = re.search(r'(\d+)', sv)
                                    if not w_match:
                                        colors.append("")
                                        continue
                                    w = int(w_match.group(1))
                                    bg = bg_map.get(w, "")
                                    tx = text_map.get(w, "")
                                    if bg:
                                        colors.append(f"background-color: {bg}; color: {tx}; font-weight: bold; text-align: center;")
                                    else:
                                        colors.append("")
                                except:
                                    colors.append("")
                            return colors

                        if 'Waku' in view_df.columns:
                            styled_df = styled_df.apply(color_waku, axis=0, subset=['Waku'])
                        
                        def color_pos600m(s):
                            """残り600m位置取り: +1.0s以上は次走注目オレンジ、-1.0以下は先行系青を着色"""
                            colors = []
                            for v in s:
                                try:
                                    val = float(v)
                                    if val >= 1.0:   colors.append("background-color:#fff3bf; color:#d9480f; font-weight:bold")
                                    elif val <= -1.0: colors.append("background-color:#d0ebff; color:#1864ab; font-weight:bold")
                                    else: colors.append("")
                                except: colors.append("")
                            return colors
                        if 'Pos600m' in view_df.columns:
                            styled_df = styled_df.apply(color_pos600m, axis=0, subset=['Pos600m'])

                        def color_deploy_score(s):
                            """展開適合度★: 80以上=ゴールド、60以上=グリーン、それ以下=グレー"""
                            colors = []
                            for v in s:
                                try:
                                    num = float(str(v).replace('★', '').strip())
                                    if num >= 80:   colors.append("background-color:#fff9c4; color:#d9480f; font-weight:bold")
                                    elif num >= 60: colors.append("background-color:#e8f5e9; color:#2b8a3e; font-weight:bold")
                                    else:           colors.append("color:#888")
                                except: colors.append("")
                            return colors
                        if 'DeployScoreLabel' in view_df.columns:
                            styled_df = styled_df.apply(color_deploy_score, axis=0, subset=['DeployScoreLabel'])

                        def color_front_collapse(s):
                            """前崩れ影響度: ◎=グリーン、▲=レッド、○=ライトグリーン、△=グレー"""
                            colors = []
                            for v in s:
                                sv = str(v)
                                if '◎' in sv:   colors.append("background-color:#2b8a3e33; color:#2b8a3e; font-weight:bold")
                                elif '▲' in sv: colors.append("background-color:#E6394633; color:#E63946; font-weight:bold")
                                elif '○' in sv: colors.append("color:#2A9D8F; font-weight:bold")
                                elif '△' in sv: colors.append("color:#aaa")
                                else:           colors.append("")
                            return colors
                        if 'FrontCollapseEffect' in view_df.columns:
                            styled_df = styled_df.apply(color_front_collapse, axis=0, subset=['FrontCollapseEffect'])

                        def color_density_penalty(s):
                            """密集ペナルティ: 密集=赤文字、余裕=青文字"""
                            colors = []
                            for v in s:
                                sv = str(v)
                                if '密集' in sv:  colors.append("color:#E63946; font-weight:bold")
                                elif '余裕' in sv: colors.append("color:#2A9D8F; font-weight:bold")
                                else:              colors.append("")
                            return colors
                        if 'DensityPenaltyLabel' in view_df.columns:
                            styled_df = styled_df.apply(color_density_penalty, axis=0, subset=['DensityPenaltyLabel'])

                        def color_oddsgap(s):
                            """オッズ断層パターン別カラーリング"""
                            _gap_colors = {
                                "断層A":   "color: #f59f00; font-weight: bold;",   # 金 — 1番人気圧倒的
                                "断層B":   "color: #2b8a3e; font-weight: bold;",   # 緑 — 2番人気逆転狙い
                                "断層C":   "color: #1864ab; font-weight: bold;",   # 青 — 直上馬浮上
                                "断層D1":  "color: #7950f2; font-weight: bold;",   # 濃紫 — 1-2間+2-3間、上位2頭軸
                                "断層D2":  "color: #d6336c; font-weight: bold;",   # 赤紫 — 2-3間+3-4間、2・3番人気軸
                                "断層D":   "color: #ae3ec9; font-weight: bold;",   # 紫 — その他の複数断層
                                "断層なし": "color: #868e96; font-style: italic;",  # グレー — 混戦
                            }
                            return [_gap_colors.get(str(v), "") for v in s]
                        if 'OddsGap' in view_df.columns:
                            styled_df = styled_df.apply(color_oddsgap, axis=0, subset=['OddsGap'])

                        def color_jockey_change(s):
                            return ["color: #e03131; font-weight: bold;" if "乗替" in str(v) else "" for v in s]
                        if 'JockeyChange' in view_df.columns:
                            styled_df = styled_df.apply(color_jockey_change, axis=0, subset=['JockeyChange'])
                        
                        # === オッズ断層バッジパネル（ホバー→説明文 / クリック→解説画像）===
                        try:
                            _sb_base = "https://raw.githubusercontent.com/8time/keiba-analysis/main/static"
                            _gap_badge_info = {
                                "断層A":   {"color":"#f59f00","border":"#f59f00","bg":"rgba(245,159,0,0.08)",
                                             "url":f"{_sb_base}/gap_a.png",
                                             "tip":"【断層A】1番人気と2番人気の間に断層&#10;&#10;特徴・戦略: 1番人気が圧倒的。1番人気を軸または1着固定にする。&#10;&#10;期待値・データ: 1番人気の勝率 52.9%、複勝率 80.7%。"},
                                "断層B":   {"color":"#2b8a3e","border":"#2b8a3e","bg":"rgba(43,138,62,0.08)",
                                             "url":f"{_sb_base}/gap_b.png",
                                             "tip":"【断層B】2番人気と3番人気の間に断層&#10;&#10;特徴・戦略: 1・2位の差が小さい(2倍以内)場合、2番人気の逆転を狙う。&#10;&#10;期待値・データ: 1番人気の勝率が通常より約8%低下する。"},
                                "断層C":   {"color":"#1864ab","border":"#1864ab","bg":"rgba(24,100,171,0.08)",
                                             "url":f"{_sb_base}/gap_c.png",
                                             "tip":"【断層C】3〜6番人気の間に断層&#10;&#10;特徴・戦略: その断層のすぐ上にいる直上馬が勝ち負けに浮上しやすい。&#10;&#10;期待値・データ: 4番人気などを軸に組み立てる。"},
                                "断層D1":  {"color":"#7950f2","border":"#7950f2","bg":"rgba(121,80,242,0.08)",
                                             "url":f"{_sb_base}/gap_d1.png",
                                             "tip":"【断層D1】1-2間 ＋ 2-3間に断層&#10;&#10;状態: 例 1番人気2.0倍、2番人気5.0倍(断層2.5倍)、3番人気12倍(断層2.4倍)。&#10;&#10;意味: 上位2頭の能力が3番人気以下と圧倒的な差。&#10;&#10;狙い方: 上位2頭を主軸に。1・2の差が大きければ1番人気不動軸、小さければ2番人気の逆転も視野に。"},
                                "断層D2":  {"color":"#d6336c","border":"#d6336c","bg":"rgba(214,51,108,0.08)",
                                             "url":f"{_sb_base}/gap_d2.png",
                                             "tip":"【断層D2】2-3間 ＋ 3-4間に断層&#10;&#10;状態: 例 2番人気5倍、3番人気10倍、4番人気25倍のような連続断層。&#10;&#10;意味: 4番人気以下の評価が極端に低く、上位3頭の信頼度が相対的に高い。&#10;&#10;狙い方: 2番人気と3番人気を主軸に。あえて1番人気をヒモに回す戦略も。"},
                                "断層D":   {"color":"#ae3ec9","border":"#ae3ec9","bg":"rgba(174,62,201,0.08)",
                                             "url":f"{_sb_base}/gap_d.png",
                                             "tip":"【断層D】複数箇所に断層&#10;&#10;能力の壁が複数存在し明確。断層の上にいる馬(直上馬)が好走しやすく、断層の下の馬は凡走しやすい傾向。&#10;&#10;狙い方: 断層上位の馬に絞り込んで厚く狙う。"},
                                "断層なし": {"color":"#868e96","border":"#868e96","bg":"rgba(134,142,150,0.08)",
                                              "url":f"{_sb_base}/gap_none.png",
                                              "tip":"【断層なし】全てのオッズ差が2倍以下のなだらかなレース。&#10;&#10;特徴: 混戦で予想が困難。見送りが無難。"},
                            }
                            _gap_src = df if 'OddsGap' in df.columns else view_df
                            _detected_gaps = [v for v in _gap_src['OddsGap'].unique()
                                              if str(v) not in ['-', '', 'nan', 'None']]
                            if _detected_gaps:
                                _badge_html_parts = []
                                for _gp in _detected_gaps:
                                    _bi = _gap_badge_info.get(str(_gp))
                                    if not _bi: continue
                                    _badge_html_parts.append(
                                        f'''<a href="{_bi['url']}" target="_blank" class="kba-gap-badge"
                                            style="color:{_bi['color']};border:2px solid {_bi['border']};background:{_bi['bg']};">
                                            {_gp}
                                            <span class="kba-gap-tip">{_bi['tip']}</span>
                                        </a>'''
                                    )
                                _full_badge_html = f"""
<style>
.kba-gap-badge {{
    display:inline-block; padding:5px 15px; border-radius:20px; font-weight:bold;
    font-size:14px; cursor:pointer; position:relative; text-decoration:none;
    margin-right:8px; margin-bottom:6px; transition: box-shadow 0.2s;
}}
.kba-gap-badge:hover {{ box-shadow: 0 2px 12px rgba(0,0,0,0.25); }}
.kba-gap-tip {{
    visibility:hidden; opacity:0; background:#1a1a2e; color:#eee;
    text-align:left; border-radius:10px; padding:12px 16px;
    position:absolute; z-index:9999; bottom:130%; left:0;
    transform:none; width:330px; font-size:13px;
    font-weight:normal; white-space:pre-line; line-height:1.7;
    border:1px solid #444; box-shadow:0 6px 24px rgba(0,0,0,0.5);
    transition:opacity 0.2s; pointer-events:none;
}}
.kba-gap-badge:hover .kba-gap-tip {{ visibility:visible; opacity:1; }}
</style>
<div style="margin:4px 0 10px 0;">
  <span style="font-size:12px;color:#888;margin-right:6px;">🔍 検出断層（ホバー→説明 / クリック→解説画像）</span><br style="margin:3px 0">
  {"".join(_badge_html_parts)}
</div>"""
                                st.markdown(_full_badge_html, unsafe_allow_html=True)
                        except Exception as _badge_ex:
                            pass
                        # ======================================================
                        st.dataframe(styled_df, column_config=column_config, use_container_width=True, hide_index=True)
                        
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

            except Exception as e:
                import traceback
                st.error(f"An error occurred: {e}")
                st.exception(e)
                logger.error(f"Analysis Failed: {traceback.format_exc()}")

# Tab 2 placeholder logic
if nav == "🧹 消去フィルター":
    st.header("🧹 消去フィルター")
    st.caption("自然言語で消去条件を設定し、出馬表から該当する馬をリアルタイムで除外します。")

    import json
    import os
    import re
    from datetime import datetime

    FILTER_PACK_FILE = "saved_filter_packs.json"

    def load_filter_packs():
        if os.path.exists(FILTER_PACK_FILE):
            try:
                with open(FILTER_PACK_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_filter_packs(packs):
        with open(FILTER_PACK_FILE, "w", encoding="utf-8") as f:
            json.dump(packs, f, ensure_ascii=False, indent=2)

    def convert_natural_language_to_rule(user_input: str) -> dict:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            try:
                api_key = st.secrets.get("GEMINI_API_KEY")
            except:
                pass
                
        fallback_rule = {
            "field": "Name",
            "operator": "contains",
            "value": user_input,
            "explanation": f"「{user_input}」を含む馬"
        }
        
        if not api_key:
            return fallback_rule
            
        prompt = f"""あなたは競馬データフィルタリングのルール変換AIです。
ユーザーが指定した自然言語の消去条件を、プログラムで処理可能な構造化JSONルールに変換してください。

馬のデータ構造は以下の通りです：
- `Umaban` (int): 馬番
- `Name` (str): 馬名
- `SexAge` (str): 性別と年齢（例：「牡3」「牝4」「セ5」）
- `Jockey` (str): 騎手名（例：「ルメール」「川田将雅」）
- `Odds` (float): 単勝オッズ
- `Popularity` (int): 単勝人気
- `Weight` (str): 馬体重（例：「474(+6)」「512(-2)」）
- `WeightCarried` (float): 斤量（例: 57.0）
- `Trainer` (str): 調教師名（例：「国枝」「藤原」）

出力フォーマットは必ず以下のJSONオブジェクト1つのみとしてください。Markdownのコードブロック（```json）は使わずに、直接プレーンテキストのJSON文字列として出力してください：
{{
  "field": "フィールド名（'Umaban', 'Name', 'SexAge', 'Jockey', 'Odds', 'Popularity', 'Weight', 'WeightCarried', 'Trainer' のいずれか）",
  "operator": "演算子（'contains', 'not_contains', 'eq', 'ne', 'gt', 'ge', 'lt', 'le', 'is_odd', 'is_even'）",
  "value": "比較する値（文字列、数値。演算子が is_odd/is_even などの場合は null。数値の場合は引用符をつけない数値型にしてください）",
  "explanation": "条件の日本語説明（例: 'オッズが10倍未満'）"
}}

ユーザーの消去条件: 「{user_input}」
"""
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            rule = json.loads(text)
            return rule
        except Exception as e:
            logger.warning(f"AI rule conversion failed, using fallback: {e}")
            import re
            
            # オッズの判定
            m_odds_lt = re.search(r'オッズ\s*(\d+(?:\.\d+)?)\s*倍?\s*(未満|以下|より小さい|より低)', user_input)
            if m_odds_lt:
                val = float(m_odds_lt.group(1))
                return {"field": "Odds", "operator": "lt", "value": val, "explanation": f"オッズが {val}倍 未満"}
                
            m_odds_gt = re.search(r'オッズ\s*(\d+(?:\.\d+)?)\s*倍?\s*(以上|超|より大きい|より高)', user_input)
            if m_odds_gt:
                val = float(m_odds_gt.group(1))
                return {"field": "Odds", "operator": "gt", "value": val, "explanation": f"オッズが {val}倍 以上"}
                
            # 人気の判定
            m_pop_lt = re.search(r'(\d+)\s*人気\s*(以内|以下|より上|未満)', user_input)
            if m_pop_lt:
                val = int(m_pop_lt.group(1))
                return {"field": "Popularity", "operator": "le", "value": val, "explanation": f"{val}人気 以内"}
                
            m_pop_gt = re.search(r'(\d+)\s*人気\s*(以降|以上|より下|超)', user_input)
            if m_pop_gt:
                val = int(m_pop_gt.group(1))
                return {"field": "Popularity", "operator": "ge", "value": val, "explanation": f"{val}人気 以下"}

            # 3歳馬などの年齢
            m_age = re.search(r'(\d+)\s*歳馬?', user_input)
            if m_age:
                val = m_age.group(1)
                return {"field": "SexAge", "operator": "contains", "value": val, "explanation": f"{val}歳馬"}

            # 馬番
            if "奇数" in user_input:
                return {"field": "Umaban", "operator": "is_odd", "value": None, "explanation": "馬番が奇数"}
            if "偶数" in user_input:
                return {"field": "Umaban", "operator": "is_even", "value": None, "explanation": "馬番が偶数"}

            return fallback_rule

    def apply_rule_to_row(row: dict, rule: dict) -> bool:
        field = rule.get("field")
        operator = rule.get("operator")
        val = rule.get("value")
        
        if field not in row:
            return False
            
        row_val = row[field]
        if row_val is None:
            return False
            
        try:
            if operator == "contains":
                return str(val).lower() in str(row_val).lower()
            elif operator == "not_contains":
                return str(val).lower() not in str(row_val).lower()
            elif operator == "eq":
                if isinstance(row_val, (int, float)) and isinstance(val, (int, float)):
                    return float(row_val) == float(val)
                return str(row_val).lower() == str(val).lower()
            elif operator == "ne":
                if isinstance(row_val, (int, float)) and isinstance(val, (int, float)):
                    return float(row_val) != float(val)
                return str(row_val).lower() != str(val).lower()
            elif operator == "gt":
                if field == "Weight" and isinstance(row_val, str):
                    m = re.search(r'^(\d+)', row_val)
                    if m: row_val = float(m.group(1))
                return float(row_val) > float(val)
            elif operator == "ge":
                if field == "Weight" and isinstance(row_val, str):
                    m = re.search(r'^(\d+)', row_val)
                    if m: row_val = float(m.group(1))
                return float(row_val) >= float(val)
            elif operator == "lt":
                if field == "Weight" and isinstance(row_val, str):
                    m = re.search(r'^(\d+)', row_val)
                    if m: row_val = float(m.group(1))
                return float(row_val) < float(val)
            elif operator == "le":
                if field == "Weight" and isinstance(row_val, str):
                    m = re.search(r'^(\d+)', row_val)
                    if m: row_val = float(m.group(1))
                return float(row_val) <= float(val)
            elif operator == "is_odd":
                return int(row_val) % 2 != 0
            elif operator == "is_even":
                return int(row_val) % 2 == 0
        except Exception as e:
            logger.warning(f"Error applying rule {rule} to field {field}: {e}")
            
        return False

    # ── Session Stateの初期化 ──
    if 'kf_rules' not in st.session_state:
        st.session_state['kf_rules'] = []
    if 'kf_race_id' not in st.session_state:
        st.session_state['kf_race_id'] = "202405020611"
    if 'kf_race_data' not in st.session_state:
        st.session_state['kf_race_data'] = None
    if 'kf_selected_rules' not in st.session_state:
        st.session_state['kf_selected_rules'] = {}
        
    packs = load_filter_packs()
    
    # --- 上部: レース検索カード ---
    st.markdown("### 🔍 レースを検索")
    
    col_id, col_btn = st.columns([4, 1])
    with col_id:
        race_id_input = st.text_input(
            "netkeibaのレースIDを入力して出馬表を取得します",
            value=st.session_state['kf_race_id'],
            placeholder="例: 202405020611",
            label_visibility="collapsed"
        )
    with col_btn:
        fetch_clicked = st.button("▶ データ取得", use_container_width=True)
        
    if fetch_clicked or st.session_state['kf_race_data'] is None:
        if race_id_input:
            st.session_state['kf_race_id'] = race_id_input
            with st.spinner("出馬データを取得中..."):
                try:
                    df = scraper.get_race_data(race_id_input)
                    if not df.empty:
                        st.session_state['kf_race_data'] = df
                        st.success(f"レースデータを取得しました！ ({len(df)}頭)")
                    else:
                        st.error("データの取得に失敗しました。レースIDが正しいか、またはネットワーク環境を確認してください。")
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")
                    
    if st.session_state['kf_race_data'] is not None:
        df = st.session_state['kf_race_data']
        metadata = df.attrs.get('metadata', {})
        
        col_left, col_right = st.columns([1, 3])
        
        with col_left:
            st.markdown("### 🧠 AIフィルタリング")
            st.caption("自然言語で条件を追加できます。")
            st.caption("例: 「オッズ10倍未満」「ルメール騎手」「3歳馬」「馬番が奇数」")
            
            col_cond_input, col_cond_add = st.columns([4, 1])
            with col_cond_input:
                new_cond = st.text_input(
                    "条件を入力してEnter",
                    placeholder="ルメール騎手",
                    label_visibility="collapsed",
                    key="kf_new_cond_input"
                )
            with col_cond_add:
                add_cond_clicked = st.button("➕", key="kf_add_cond_btn")
                
            if add_cond_clicked or (new_cond and new_cond != st.session_state.get('last_processed_cond', '')):
                if new_cond:
                    st.session_state['last_processed_cond'] = new_cond
                    with st.spinner("AIが条件を解析中..."):
                        rule = convert_natural_language_to_rule(new_cond)
                        if rule not in st.session_state['kf_rules']:
                            st.session_state['kf_rules'].append(rule)
                            st.rerun()
                            
            st.write("---")
            st.write("**追加された条件:**")
            
            if not st.session_state['kf_rules']:
                st.info("条件は追加されていません。")
            else:
                rules_to_delete = []
                for idx, rule in enumerate(st.session_state['kf_rules']):
                    explanation = rule.get("explanation", "不明な条件")
                    
                    r_col_chk, r_col_del = st.columns([4, 1])
                    with r_col_chk:
                        is_checked = st.checkbox(
                            explanation,
                            value=st.session_state['kf_selected_rules'].get(idx, True),
                            key=f"kf_rule_chk_{idx}"
                        )
                        st.session_state['kf_selected_rules'][idx] = is_checked
                    with r_col_del:
                        if st.button("🗑️", key=f"kf_rule_del_{idx}"):
                            rules_to_delete.append(idx)
                            
                if rules_to_delete:
                    for idx in sorted(rules_to_delete, reverse=True):
                        st.session_state['kf_rules'].pop(idx)
                        if idx in st.session_state['kf_selected_rules']:
                            del st.session_state['kf_selected_rules'][idx]
                    st.rerun()
                    
                st.write("---")
                st.write("**📁 フィルターパックとして保存**")
                pack_name = st.text_input("パック名（例: １次選抜）", placeholder="１次選抜", key="kf_pack_name")
                if st.button("💾 選択した条件をパックとして保存", use_container_width=True):
                    if pack_name:
                        selected_rules = [
                            st.session_state['kf_rules'][idx]
                            for idx, checked in st.session_state['kf_selected_rules'].items()
                            if checked and idx < len(st.session_state['kf_rules'])
                        ]
                        if selected_rules:
                            packs[pack_name] = selected_rules
                            save_filter_packs(packs)
                            st.success(f"パック『{pack_name}』を保存しました！")
                            st.rerun()
                        else:
                            st.warning("保存する条件が選択されていません。")
                    else:
                        st.warning("パック名を入力してください。")
                        
            if packs:
                st.write("---")
                st.write("**📂 保存済みパックを読み込む**")
                selected_pack = st.selectbox("パックを選択", ["選択してください..."] + list(packs.keys()), key="kf_pack_select")
                if selected_pack != "選択してください...":
                    if st.button("⚡ パックを適用する", use_container_width=True):
                        st.session_state['kf_rules'] = list(packs[selected_pack])
                        st.session_state['kf_selected_rules'] = {i: True for i in range(len(packs[selected_pack]))}
                        st.success(f"パック『{selected_pack}』を適用しました！")
                        st.rerun()
                    if st.button("🗑️ パックを削除する", use_container_width=True):
                        del packs[selected_pack]
                        save_filter_packs(packs)
                        st.success(f"パック『{selected_pack}』を削除しました。")
                        st.rerun()
                        
        with col_right:
            race_name = metadata.get('RaceName', metadata.get('RaceTitle', ''))
            if not race_name and 'RaceName' in df.columns and not df.empty:
                race_name = str(df['RaceName'].iloc[0]) if pd.notna(df['RaceName'].iloc[0]) else ''
            if not race_name:
                race_name = 'Unknown Race'
            race_date = df.iloc[0]['RaceDate'] if not df.empty else datetime.now().strftime("%Y/%m/%d")
            venue = df.iloc[0]['Venue'] if not df.empty else 'Unknown'
            dist = df.iloc[0]['CurrentDistance'] if not df.empty else 1600
            surf = df.iloc[0]['CurrentSurface'] if not df.empty else '芝'
            weather = metadata.get('weather', '-')
            condition = metadata.get('condition', '-')
            class_val = metadata.get('class', '-')
            weight_rule = metadata.get('weight_rule', '-')
            
            header_detail = f"{race_date} | {venue} {class_val} {weight_rule} / {surf}{dist}m | 天候:{weather} 馬場:{condition}"
            
            active_rules = [
                st.session_state['kf_rules'][idx]
                for idx, checked in st.session_state['kf_selected_rules'].items()
                if checked and idx < len(st.session_state['kf_rules'])
            ]
            
            eliminated_umaban = []
            display_rows = []
            
            for _, row in df.iterrows():
                row_dict = row.to_dict()
                
                is_eliminated = False
                matched_rule_explanation = ""
                for rule in active_rules:
                    if apply_rule_to_row(row_dict, rule):
                        is_eliminated = True
                        matched_rule_explanation = rule.get("explanation", "")
                        break
                        
                row_data = {
                    'Status': '❌ 消去' if is_eliminated else '✅ 残存',
                    'MatchReason': matched_rule_explanation if is_eliminated else '',
                    'Umaban': int(row['Umaban']) if pd.notna(row['Umaban']) else 0,
                    'Name': row['Name'],
                    'SexAge': row.get('SexAge', '-'),
                    'Jockey': row['Jockey'],
                    'WeightCarried': row.get('WeightCarried', '-'),
                    'Odds': row.get('Odds', 0.0),
                    'Popularity': int(row['Popularity']) if pd.notna(row['Popularity']) else 99,
                    'Weight': row.get('Weight', '-'),
                    'Trainer': row.get('Trainer', '-')
                }
                
                if is_eliminated:
                    eliminated_umaban.append(row_data['Umaban'])
                    
                display_rows.append(row_data)
                
            total_horses = len(df)
            eliminated_count = len(eliminated_umaban)
            
            col_h_left, col_h_right = st.columns([3, 1])
            with col_h_left:
                st.markdown(f"## {race_name}")
                st.markdown(f"*{header_detail}*")
            with col_h_right:
                st.html(f"""
                <div style="background-color: #1e1e1e; border: 2px solid #FF3333; border-radius: 20px; padding: 10px 20px; text-align: center; color: white; font-weight: bold; font-size: 1.1em; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                    消去対象: <span style="color: #FF3333; font-size: 1.3em;">{eliminated_count}</span> / {total_horses} 頭
                </div>
                """)
                
            st.write("---")
            
            hide_eliminated = st.checkbox("❌ 消去対象の馬を非表示にする", value=False)
            
            df_display = pd.DataFrame(display_rows)
            
            if hide_eliminated:
                df_display = df_display[df_display['Status'] == '✅ 残存']
                
            df_display = df_display.rename(columns={
                'Status': '状態',
                'MatchReason': '消去理由',
                'Umaban': '馬番',
                'Name': '馬名',
                'SexAge': '性齢',
                'Jockey': '騎手',
                'WeightCarried': '斤量',
                'Odds': '単勝オッズ',
                'Popularity': '人気',
                'Weight': '馬体重',
                'Trainer': '厩舎'
            })
            
            col_order = ['状態', '馬番', '馬名', '性齢', '騎手', '斤量', '単勝オッズ', '人気', '馬体重', '厩舎', '消去理由']
            df_display = df_display[[c for c in col_order if c in df_display.columns]]
            
            def style_dataframe(df_in):
                styler = df_in.style.format({
                    '単勝オッズ': '{:.1f}'
                })
                
                def apply_row_styles(row):
                    if row['状態'] == '❌ 消去':
                        # グレー背景 + 赤打ち消し線
                        return [
                            'background-color: #2e2e2e; color: #aaaaaa; '
                            'text-decoration: line-through; text-decoration-color: #ff4444; '
                            'text-decoration-thickness: 2px;'
                        ] * len(row)
                    return [''] * len(row)
                    
                styler = styler.apply(apply_row_styles, axis=1)
                return styler
                
            st.write("**📊 出馬データ表**")
            # 全頭スクロールなし表示: 1行あたり約35px + ヘッダー38px
            n_rows = len(df_display)
            table_height = 38 + n_rows * 35
            st.dataframe(
                style_dataframe(df_display),
                use_container_width=True,
                hide_index=True,
                height=table_height
            )

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
# 🧪 テスト タブ (🐎 Stress Analyst - 乗算デバフ検証)
# ──────────────────────────────────────────────
if nav == "🧪 テスト":
    st.header("🐎 Stress Analyst (乗算デバフ検証)")
    st.markdown("""
    **「能力が低いのではなく、リミッターが掛かっている状態」を数値化します。**
    基礎能力（スピード指数＋血統）に対し、当日の環境ストレスを「掛け算（％カット）」で適用し、危険な人気馬をあぶり出します。
    """)

    # 入力エリア
    with st.container(border=True):
        col_in1, col_in2 = st.columns([2, 1])
        with col_in1:
            test_race_id_input = st.text_input("レースIDを入力", placeholder="202406010101", key="stress_test_race_id")
        with col_in2:
            st.write(" ")
            fetch_btn = st.button("ストレス要因を解析", type="primary", use_container_width=True)

    if fetch_btn:
        if not test_race_id_input:
            st.warning("レースIDを入力してください。")
        else:
            # メインタブのデータを流用するか、新規取得するか
            # ここでは検証用に最新の df を使用
            df = st.session_state.get('df')
            if df is None or st.session_state.get('tab1_analyzed_id') != test_race_id_input:
                with st.spinner("データを取得中..."):
                    df = scraper.get_race_data(test_race_id_input)
                    if df is not None:
                        df = calculator.calculate_battle_score(df)
                        # 血統も取得
                        try:
                            api_url = f"http://127.0.0.1:8000/api/bloodline/{test_race_id_input}"
                            resp = requests.get(api_url, timeout=5)
                            if resp.status_code == 200:
                                b_data = pd.DataFrame(resp.json().get('data', []))
                                if not b_data.empty:
                                    df = df.merge(b_data[['number', 'bonus']], left_on=df['Umaban'].astype(int), right_on=b_data['number'].astype(int), how='left')
                        except: pass

            if df is not None and not df.empty:
                results = []
                for _, row in df.iterrows():
                    m = 1.0
                    reasons = []
                    
                    # 共通データの準備
                    w_text = str(row.get('WeightHistory', ''))
                    match_w = re.search(r'(\d+)\(([-+]?\d+)\)', w_text)
                    curr_w = int(match_w.group(1)) if match_w else 0
                    w_diff_val = int(match_w.group(2)) if match_w else 0
                    
                    umaban = int(row.get('Umaban', 0))
                    waku = int(row.get('Waku', 1))
                    avg_pos = float(row.get('AvgPosition', 9.9))
                    surface = str(row.get('CurrentSurface', ''))
                    dist = float(row.get('CurrentDistance', 1600) or 1600)
                    
                    # 条件A：キックバック・ストレス (ダート内枠+後方脚質)
                    if "ダ" in surface and waku <= 3 and avg_pos >= 8.0:
                        m -= 0.08
                        reasons.append("ダート内枠の砂かぶり(精神ストレス)")

                    # 条件D：ダート長距離の内枠 (1800m以上のダート1〜3枠)
                    if "ダ" in surface and dist >= 1800 and waku <= 3:
                        m -= 0.10
                        reasons.append("長距離ダートの内枠(距離ストレス)")

                    # 条件B：待機・出遅れストレス (奇数枠+逃げ脚質)
                    if umaban % 2 != 0 and avg_pos <= 2.5:
                        m -= 0.05
                        reasons.append("奇数枠の逃げ馬(待機ストレス)")

                    # 条件C：過剰消耗ストレス (小柄馬+大幅馬体減)
                    if curr_w > 0 and curr_w < 440 and w_diff_val <= -6:
                        m -= 0.15
                        reasons.append("小柄馬の大幅馬体減(肉体ストレス)")

                    multiplier = max(m, 0.70)
                    
                    # 仮の基礎スコア計算 (BattleScore + Bloodline)
                    base = float(row.get('BattleScore', 0))
                    blood = float(row.get('bonus', 0))
                    pre_score = base + blood
                    final_score = pre_score * multiplier
                    
                    results.append({
                        "枠番": waku,
                        "馬番": umaban,
                        "馬名": row.get('Name', ''),
                        "基礎評価": round(pre_score, 1),
                        "ストレス係数": f"{multiplier:.1f}",
                        "ストレス要因": " / ".join(reasons) if reasons else "良好 ✅",
                        "最終予測": round(final_score, 1),
                        "減衰量": round(final_score - pre_score, 1)
                    })
                
                res_df = pd.DataFrame(results).sort_values("最終予測", ascending=False)
                
                st.subheader(f"🛡️ ストレス解析結果: {test_race_id_input}")
                
                # スタイル適用
                def style_stress(val):
                    f_val = float(val)
                    if f_val < 0.85: return 'background-color: #ffebee; color: #c62828; font-weight: bold;'
                    if f_val < 1.0: return 'background-color: #fff8e1; color: #f57f17;'
                    return 'color: #2e7d32;'

                st.dataframe(
                    res_df.style.map(style_stress, subset=['ストレス係数']),
                    column_config={
                        "基礎評価": st.column_config.NumberColumn(format="%.1f"),
                        "最終予測": st.column_config.NumberColumn(format="%.1f"),
                        "減衰量": st.column_config.NumberColumn(format="%.1f"),
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
                # エピッククイーン・トラップ警報
                trap_horses = res_df[res_df['ストレス係数'].astype(float) <= 0.85]
                if not trap_horses.empty:
                    st.error(f"⚠️ **過剰評価トラップ警告**: 以下の馬はストレスにより能力リミッターが強く掛かっています！\n\n" + 
                             "\n".join([f"- {h['馬名']} (係数: {h['ストレス係数']})" for _, h in trap_horses.iterrows()]))
            else:
                st.error("データの取得に失敗しました。")

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
            "Strength (X)": 0.0, "Jockey": 0.0, "Training": 0.0, "Weight": 0.0, "WeightPenalty": -0.1, "WeightCarried": 0.0,
            "Suitability": 0.0, "AvgAgari": 0.0, "Umaban": 0.0, "Bloodline": 1.0,
            "Base": 1.0
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
            def _cb(): st.session_state[key_sld] = st.session_state[key_num]
            return _cb
        def _make_sync_num(key_sld, key_num):
            def _cb(): st.session_state[key_num] = st.session_state[key_sld]
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
                
                max_val = 1.0
                min_val = -1.0
                if sw_key == "WeightPenalty": max_val = 0.0
                if sw_key == "Base": min_val, max_val = 0.0, 2.0
                if sw_key == "Bloodline": max_val = 10.0
                if sw_key == "AvgAgari": max_val = 10.0
                if sw_key == "AvgPosition": max_val = 10.0
                
                # Initialize if missing with clamping safety
                safe_val = max(float(min_val), min(float(max_val), float(cur_val)))
                if sld_key not in st.session_state: st.session_state[sld_key] = safe_val
                if num_key not in st.session_state: st.session_state[num_key] = safe_val
                
                c1, c2 = st.columns([2, 1])
                with c1:
                    st.slider(
                        display_label, min_value=min_val, max_value=max_val, step=0.01, 
                        key=sld_key,
                        on_change=_make_sync_num(sld_key, num_key)
                    )
                with c2:
                    st.number_input(
                        "", min_value=min_val, max_value=max_val, step=0.01,
                        key=num_key,
                        on_change=_make_sync_slider(num_key, sld_key),
                        label_visibility="collapsed"
                    )
                sw[sw_key] = float(st.session_state.get(num_key, cur_val))

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
                "枠": row.get('Waku', "-"),
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
                name = "🔥『金星』 " + name
            return name
            
        df_test_res['馬名(ラベル付)'] = df_test_res.apply(refine_marks, axis=1)
        
        # --- Re-order and Finalize ---
        # ユーザー要望: 新順位を一番左に、枠順を追加
        cols = ['新順位', '枠', '馬番'] + [c for c in df_test_res.columns if c not in ['新順位', '枠', '馬番', 'Diff']] + ['Diff']
        df_test_res = df_test_res[cols]
        
        # Sort by Predicted Score
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
            is_giant = "🔥『金星』" in str(r.get('馬名(ラベル付)', ''))
            new_rank = r.get('新順位', 99)
            
            if is_giant: 
                bg = 'background-color: #ff4500;' # OrangeRed (Giant Killing)
            elif diff_val >= 3: 
                bg = 'background-color: #006400;' # Bright Green
            elif 'BEST' in style_tag: 
                bg = 'background-color: #004d00;' # Dark Green
            elif 'RISK' in style_tag: 
                bg = 'background-color: #4d0000;' # Dark Red
            elif new_rank <= 5:
                bg = 'background-color: #1e3d59;' # Dark Blue (Top 5 Highlight)
            
            text_col = 'color: white; font-weight: bold;' if bg else ''
            return [bg + text_col for _ in r]

        df_display = df_test_res.drop(columns=['_BonusDetails', '_Style']) if '_BonusDetails' in df_test_res.columns else df_test_res
        # カラム順の最終保証（新順位を左端に）
        if '新順位' in df_display.columns:
            # 優先表示順: 新順位, 枠, 馬番, ...
            _prio = ['新順位', '枠', '馬番']
            cols = [c for c in _prio if c in df_display.columns] + [c for c in df_display.columns if c not in _prio]
            df_display = df_display[cols]
        
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
                # 重要カラム（指数・スコア系・馬情報）は先頭、その他は末尾に
                _important = [c for c in _missing_new if any(tok in c for tok in ["枠", "馬番", "指数", "スコア", "適性", "U指数", "オメガ"])]
                _the_rest = [c for c in _missing_new if c not in _important]
                df_display = df_display[_important + _ordered_valid + _the_rest]
        except: pass

        with st.expander("📋 列の表示順序を設定（選択順が左から右の順になります）", expanded=False):
            _cur_cols_lt = list(df_display.columns)
            # multiselect の初期値がキャッシュに引きずられるため、新設カラムを優先的にマージ
            _default_lt = st.session_state.get('logic_test_col_order_sel', _cur_cols_lt)
            for c in ["枠", "馬番", "調教", "U指数", "スピード指数", "斤量", "予測スコア"]:
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
        | **Signal J◎** | 騎手の当日全出走が同一馬番等で統一 | +30 |
        | **Signal T◎** | 厩舎の当日全出走が同一馬番等で統一 | +30 |
        | **Signal T●** | 厩舎が異なる場・同一Rで好配置一致 | +30 |
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

            # 全場URL（●シグナル対応のため）- JRA中央競馬のみ
            for rr in race_list:
                r_id = rr['race_id']
                v_code = r_id[4:6] if len(r_id) == 12 else '99'
                if not (v_code.isdigit() and 1 <= int(v_code) <= 10):
                    continue  # NAR（地方競馬）を除外
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

                display_cols = [c for c in [
                        "race_number", "horse_number", "horse_name", "special_marks",
                        "jockey", "trainer", "score",
                        "jockey_single_ride",
                        "patterns_detected", "match_details",
                        "odds", "odds_rank", "is_best_period", "warning"
                    ] if c in df_res.columns]

                try:
                    styled_df = df_res[display_cols].style.map(
                        color_score, subset=["score"] if "score" in display_cols else []
                    )
                    if "is_best_period" in display_cols:
                        styled_df = styled_df.map(color_best_period, subset=["is_best_period"])

                    st.dataframe(
                        styled_df,
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
                        use_container_width=True,
                        hide_index=True,
                    )
                except Exception as e_disp:
                    st.warning(f"スタイルエラー: {e_disp}")
                    st.dataframe(df_res[display_cols], use_container_width=True, hide_index=True)

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
                csv_bytes = _df_csv.to_csv(index=False).encode("utf-8-sig")
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
    # Use absolute path relative to this script to ensure persistence regardless of CWD.
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    LOGIC_FILE = os.path.join(BASE_DIR, "saved_logic_notes.json")
    
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

    # --- Persistence Warning (st.secrets = Cloud environment) ---
    is_cloud = "st.secrets" in str(st.secrets) or os.environ.get("STREAMLIT_RUNTIME_HOST") is not None
    if is_cloud:
         st.warning("⚠️ **ご注意**: 現在 Streamlit Cloud 環境で実行されています。ここでの変更はサーバーの再起動（Git Push時など）でリセットされるため、保存後は必ず下の「📥 バックアップをダウンロード」を行ってください。")

    st.subheader("📁 保存済みロジック一覧")
    
    # Manage Export/Import (JSON)
    me1, me2 = st.columns(2)
    with me1:
        if logics:
            logic_json = json.dumps(logics, ensure_ascii=False, indent=2)
            st.download_button(
                "📥 バックアップをダウンロード (JSON)",
                data=logic_json.encode('utf-8'),
                file_name=f"logic_backup_{datetime.now().strftime('%Y%m%d')}.json",
                mime="application/json",
                help="現在のすべてのロジックをファイルとして保存します。Cloud環境でお使いの場合は必須です。"
            )
    with me2:
        uploaded_logic = st.file_uploader("📤 バックアップから復元", type=["json"], key="logic_uploader")
        if uploaded_logic:
            try:
                uploaded_data = json.load(uploaded_logic)
                if st.button("🔄 復元を実行する (既存データにマージ)"):
                    logics.update(uploaded_data)
                    save_logics(logics)
                    st.success("ロジックを復元・マージしました！")
                    time.sleep(1)
                    st.rerun()
            except Exception as e:
                st.error(f"読み込みエラー: {e}")

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
        elif not new_memo.strip() and not new_ag.strip():
             st.error("メモまたは指示が空です。上書きで内容が消える可能性があるため保存を中断しました。")
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
# 🧠 MAGIシステム
# ──────────────────────────────────────────────
# MAGIページ以外では、MAGIのグローバルCSSをリセットして元のUIを復元する
if nav != "🧠 MAGIシステム":
    st.markdown("""
    <style>
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"],
    [data-testid="stMainBlockContainer"], .block-container {
        background-color: #ffffff !important;
        background: #ffffff !important;
        color: #262730 !important;
    }
    section[data-testid="stSidebar"] { background: #121212 !important; }
    p, li, ul, ol, small { color: #262730 !important; font-family: inherit !important; }
    .stMarkdown p, .stMarkdown li { color: #262730 !important; font-family: inherit !important; }
    h1 { color: #262730 !important; font-family: inherit !important;
         text-shadow: none !important; letter-spacing: inherit !important; }
    h2, h3, h4 { color: #262730 !important; font-family: inherit !important; }
    div[data-testid="stMetricValue"] { color: #262730 !important; font-family: inherit !important;
                                       text-shadow: none !important; }
    div[data-testid="stMetricLabel"] > div { color: #262730 !important; font-family: inherit !important;
                                              font-size: inherit !important; letter-spacing: inherit !important; }
    div[data-testid="stAlert"] { background: #f0f2f6 !important; border-radius: 4px !important; }
    div[data-testid="stRadio"] label, div[data-testid="stRadio"] p,
    div[role="radiogroup"] label, div[role="radiogroup"] span { color: #262730 !important; font-family: inherit !important; }
    div[data-testid="stSlider"] label, div[data-testid="stSlider"] p,
    div[data-testid="stNumberInput"] label, div[data-testid="stNumberInput"] p,
    div[data-testid="stSelectbox"] label, div[data-testid="stSelectbox"] p { color: #262730 !important; }
    </style>
    """, unsafe_allow_html=True)

if nav == "🧠 MAGIシステム":
    from core import magi_system
    import importlib; importlib.reload(magi_system)

    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700;900&display=swap');

    /* ─── ベース背景 ─── */
    .stApp { background: #000000 !important; }
    section[data-testid="stSidebar"] { background: #050510 !important; }

    /* ─── MAGIヘッダー ─── */
    .magi-masthead {
        background: linear-gradient(180deg, #000000 0%, #0a0a1a 100%);
        border: 1px solid #00ffff44;
        border-top: 3px solid #00ffff;
        padding: 24px 20px 16px;
        margin-bottom: 4px;
        position: relative;
        overflow: hidden;
        font-family: 'Orbitron', monospace;
    }
    .magi-masthead::before {
        content: '';
        position: absolute; top:0; left:0; right:0; bottom:0;
        background: repeating-linear-gradient(0deg, transparent, transparent 39px, #00ffff08 39px, #00ffff08 40px),
                    repeating-linear-gradient(90deg, transparent, transparent 39px, #00ffff06 39px, #00ffff06 40px);
        pointer-events: none;
    }
    .magi-masthead-title {
        font-family: 'Orbitron', monospace;
        font-size: 22px; font-weight: 900;
        color: #00ffff;
        letter-spacing: 4px;
        text-shadow: 0 0 20px #00ffff, 0 0 40px #00ffff88;
        margin: 0 0 4px 0;
    }
    .magi-masthead-sub {
        font-family: 'Share Tech Mono', monospace;
        font-size: 12px; color: #ff6600;
        letter-spacing: 3px;
        text-shadow: 0 0 8px #ff6600;
        margin: 0;
    }
    .magi-unit-badges {
        display: flex; gap: 12px; margin-top: 12px;
    }
    .magi-badge-mel { background:#1a0000; border:1px solid #ff3333; color:#ff3333; padding:4px 12px; font-family:'Orbitron',monospace; font-size:10px; letter-spacing:2px; }
    .magi-badge-bal { background:#001a00; border:1px solid #00ff44; color:#00ff44; padding:4px 12px; font-family:'Orbitron',monospace; font-size:10px; letter-spacing:2px; }
    .magi-badge-cas { background:#00001a; border:1px solid #3399ff; color:#3399ff; padding:4px 12px; font-family:'Orbitron',monospace; font-size:10px; letter-spacing:2px; }

    /* ─── ユニットカード ─── */
    .melchior-card {
        background: linear-gradient(135deg, #0d0000 0%, #1a0505 100%);
        border: 1px solid #ff333344; border-top: 2px solid #ff3333;
        border-radius: 0; padding: 16px; position: relative; overflow: hidden;
        font-family: 'Share Tech Mono', monospace;
    }
    .balthasar-card {
        background: linear-gradient(135deg, #000d00 0%, #051a05 100%);
        border: 1px solid #00ff4444; border-top: 2px solid #00ff44;
        border-radius: 0; padding: 16px; position: relative; overflow: hidden;
        font-family: 'Share Tech Mono', monospace;
    }
    .casper-card {
        background: linear-gradient(135deg, #00000d 0%, #05051a 100%);
        border: 1px solid #3399ff44; border-top: 2px solid #3399ff;
        border-radius: 0; padding: 16px; position: relative; overflow: hidden;
        font-family: 'Share Tech Mono', monospace;
    }
    .unit-label-mel { color:#ff3333; font-family:'Orbitron',monospace; font-size:13px; font-weight:700; letter-spacing:3px; text-shadow:0 0 10px #ff333388; }
    .unit-label-bal { color:#00ff44; font-family:'Orbitron',monospace; font-size:13px; font-weight:700; letter-spacing:3px; text-shadow:0 0 10px #00ff4488; }
    .unit-label-cas { color:#3399ff; font-family:'Orbitron',monospace; font-size:13px; font-weight:700; letter-spacing:3px; text-shadow:0 0 10px #3399ff88; }
    .unit-subtitle { color:#ff8844; font-size:10px; letter-spacing:2px; font-family:'Share Tech Mono',monospace; }

    /* ─── 合議結果 ─── */
    .magi-consensus {
        background: linear-gradient(135deg, #0a0800 0%, #1a1200 100%);
        border: 2px solid #ffaa00;
        border-radius: 0; padding: 20px; margin-top: 8px;
        font-family: 'Share Tech Mono', monospace;
        position: relative; overflow: hidden;
        box-shadow: 0 0 30px #ffaa0022, inset 0 0 30px #ffaa0008;
    }
    .consensus-title {
        font-family: 'Orbitron', monospace; font-size: 14px; font-weight:700;
        color: #ffaa00; letter-spacing: 4px;
        text-shadow: 0 0 15px #ffaa00;
        margin-bottom: 12px;
    }
    .consensus-ok {
        color: #00ff44; font-family:'Orbitron',monospace;
        font-size:13px; letter-spacing:3px;
        text-shadow: 0 0 12px #00ff44;
    }
    .consensus-ng {
        color: #ff6600; font-family:'Orbitron',monospace;
        font-size:13px; letter-spacing:3px;
        text-shadow: 0 0 12px #ff6600;
    }

    /* ─── 馬券推奨パネル ─── */
    .bet-panel {
        background: #000a00;
        border: 1px solid #00ff44;
        padding: 12px 16px; margin: 6px 0;
        font-family: 'Orbitron', monospace;
    }
    .bet-panel-cas {
        background: #00000a;
        border: 1px solid #3399ff;
        padding: 12px 16px; margin: 6px 0;
        font-family: 'Orbitron', monospace;
    }
    .bet-label { color:#ff8844; font-size:9px; letter-spacing:3px; }
    .bet-combo { color:#ffffff; font-size:22px; font-weight:700; letter-spacing:4px; text-shadow: 0 0 10px #ffffff88; }
    .bet-combo-cas { color:#3399ff; font-size:22px; font-weight:700; letter-spacing:4px; text-shadow: 0 0 10px #3399ff88; }

    /* ─── ランキング行 ─── */
    .vote-row {
        display:flex; align-items:center; gap:12px;
        padding: 8px 12px; margin: 4px 0;
        background: #050510; border-left: 3px solid #ffaa00;
        font-family: 'Share Tech Mono', monospace;
    }
    .vote-rank { color:#ffaa00; font-size:18px; font-weight:700; min-width:32px; }
    .vote-num { color:#ff8844; font-size:11px; min-width:40px; }
    .vote-name { color:#ffffff; font-size:13px; flex:1; }
    .vote-pts { color:#ffaa00; font-size:12px; }
    .vote-supporters { font-size:10px; color:#ff6622; }

    /* ─── ボタン上書き ─── */
    div[data-testid="stButton"] > button[kind="primary"] {
        background: transparent !important;
        border: 2px solid #ff6600 !important;
        color: #ff6600 !important;
        font-family: 'Orbitron', monospace !important;
        font-size: 13px !important; letter-spacing: 3px !important;
        border-radius: 0 !important;
        text-shadow: 0 0 8px #ff6600 !important;
        box-shadow: 0 0 15px #ff660033 !important;
        padding: 12px 24px !important;
    }
    div[data-testid="stButton"] > button[kind="primary"]:hover {
        background: #ff660022 !important;
        box-shadow: 0 0 25px #ff660066 !important;
    }

    /* ─── expander 枠 ─── */
    .streamlit-expanderHeader {
        background: #050510 !important; color: #ff8844 !important;
        font-family: 'Share Tech Mono', monospace !important;
        border: 1px solid #222244 !important; border-radius: 0 !important;
    }
    .streamlit-expanderContent {
        background: #020208 !important;
        border: 1px solid #222244 !important; border-top: none !important;
    }

    /* ─── metric ─── */
    div[data-testid="stMetric"] {
        background: #050510; border: 1px solid #1a1a3a;
        padding: 12px; border-radius: 0;
    }
    div[data-testid="stMetricLabel"] > div { color:#ff8844 !important; font-family:'Share Tech Mono',monospace !important; font-size:10px !important; letter-spacing:2px !important; }
    div[data-testid="stMetricValue"] { color:#00ffff !important; font-family:'Orbitron',monospace !important; text-shadow: 0 0 8px #00ffff88 !important; }

    /* ─── 警告/情報メッセージ ─── */
    div[data-testid="stAlert"] { border-radius:0 !important; border-left-width:3px !important; background:#050510 !important; }

    /* ─── 全体テキスト（p / li / 本文） ─── */
    p, li, ul, ol, small { color:#ff8844 !important; }
    .stMarkdown p, .stMarkdown li { color:#ff8844 !important; }

    /* ─── メインタイトル・サブタイトル ─── */
    h1 { color:#00ffff !important; font-family:'Orbitron',monospace !important;
         text-shadow:0 0 16px #00ffff88 !important; letter-spacing:2px !important; }
    h2, h3, h4 { color:#ff8844 !important; font-family:'Orbitron',monospace !important; }

    /* ─── ラジオボタン ─── */
    div[data-testid="stRadio"] > label { color:#ff8844 !important; font-family:'Share Tech Mono',monospace !important; }
    div[data-testid="stRadio"] label { color:#ff8844 !important; }
    div[data-testid="stRadio"] p { color:#ff8844 !important; }
    div[role="radiogroup"] label { color:#ff8844 !important; }
    div[role="radiogroup"] span { color:#ff8844 !important; }

    /* ─── スライダー・数値入力・selectbox ─── */
    div[data-testid="stSlider"] label, div[data-testid="stSlider"] p { color:#ff8844 !important; }
    div[data-testid="stNumberInput"] label, div[data-testid="stNumberInput"] p { color:#ff8844 !important; }
    div[data-testid="stSelectbox"] label, div[data-testid="stSelectbox"] p { color:#ff8844 !important; }
    div[data-testid="stSelectSlider"] label, div[data-testid="stSelectSlider"] p { color:#ff8844 !important; }

    /* ─── テキスト入力 ─── */
    div[data-testid="stTextInput"] label { color:#ff8844 !important; }

    /* ─── チェックボックス ─── */
    div[data-testid="stCheckbox"] label, div[data-testid="stCheckbox"] p { color:#ff8844 !important; }

    /* ─── caption / help text ─── */
    div[data-testid="stCaptionContainer"] p { color:#ff6622 !important; }
    .stCaption, [data-testid="stCaptionContainer"] { color:#ff6622 !important; }

    /* ─── expander内テキスト ─── */
    details summary p { color:#ff8844 !important; }
    details p, details li, details strong { color:#ff8844 !important; }
    [data-testid="stExpanderDetails"] p { color:#ff8844 !important; }
    [data-testid="stExpanderDetails"] label { color:#ff8844 !important; }

    /* ─── bold / strong ─── */
    strong, b { color:#ffaa44 !important; }

    /* ─── info/warning/success メッセージ本文 ─── */
    div[data-testid="stAlert"] p { color:#ff8844 !important; }

    /* ─── dataframe テキスト ─── */
    div[data-testid="stDataFrame"] { color:#ff8844; }

    /* ─── sidebar ラベル ─── */
    section[data-testid="stSidebar"] label { color:#ff8844 !important; }
    section[data-testid="stSidebar"] p { color:#ff8844 !important; }
    section[data-testid="stSidebar"] span { color:#ff8844 !important; }
    </style>
    """, unsafe_allow_html=True)

    # ─── ヘッダー描画 ───
    st.markdown("""
    <div class='magi-masthead'>
      <div class='magi-masthead-title'>🧠 MAGI SYSTEM — Joint Consensus AI</div>
      <div class='magi-masthead-sub'>合議制予測AI ／ MELCHIOR-1 × BALTHASAR-2 × CASPER-3</div>
      <div class='magi-unit-badges'>
        <div class='magi-badge-mel'>⬡ MELCHIOR-1</div>
        <div class='magi-badge-bal'>⬡ BALTHASAR-2</div>
        <div class='magi-badge-cas'>⬡ CASPER-3</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


    st.info("**使い方:** 先に「🏠 Single Race Analysis」でレースを解析してから、このページでMAGI合議を実行してください。")

    # データ確認
    df_magi = st.session_state.get('df')
    race_metadata = st.session_state.get('race_metadata', {})

    if df_magi is None or df_magi.empty:
        st.warning("⚠️ レースデータが未読み込みです。先に Single Race Analysis でレースを解析してください。")
        st.stop()

    # レース情報表示
    meta_col1, meta_col2, meta_col3 = st.columns(3)
    with meta_col1:
        st.metric("クラス", race_metadata.get('class', '-'))
    with meta_col2:
        st.metric("馬場状態", race_metadata.get('condition', '-'))
    with meta_col3:
        st.metric("出走頭数", len(df_magi))

    # コースプロファイル選択
    race_id_for_magi = st.session_state.get('tab1_analyzed_id', '')
    default_magi_profile = 2
    if len(str(race_id_for_magi)) >= 6:
        vc = str(race_id_for_magi)[4:6]
        if vc in ['04', '05', '07']:
            default_magi_profile = 0
        elif vc in ['01', '02', '03', '06', '10']:
            default_magi_profile = 1

    magi_course = st.radio(
        "コース特性（展開判定に使用）",
        ["✨ 直線が長い・差し有利", "✨ 小回り・先行有利", "✨ 標準"],
        index=default_magi_profile,
        horizontal=True,
    )

    # 波乱度取得
    chaos_data = calculator.evaluate_race_chaos_v3(df_magi)
    chaos_rank = chaos_data.get('rank', 'B')
    chaos_reasons = chaos_data.get('reason', '')

    st.markdown(f"**波乱度: `{chaos_rank}` 判定** — {chaos_reasons[:100] if isinstance(chaos_reasons, str) else ''}")

    # ── モード選択 ──────────────────────────────────────────────
    st.markdown("---")
    magi_mode = st.radio(
        "🧠 MAGIモード選択",
        ["⚡ ルールベースモード（高速）", "🤖 LLMマルチエージェントモード（本物の独立AI）"],
        index=0,
        horizontal=True,
        help="LLMモードは各MAGIが独立したGemini APIコールを行います（計6回のAPIコール）。ルールベースは計算式による高速版です。",
    )
    use_llm_mode = "LLM" in magi_mode

    if use_llm_mode:
        st.info(
            "**LLMマルチエージェントモード:** 3機のMAGIがそれぞれ独立したGemini APIインスタンスで思考します。\n"
            "- 🔴 MELCHIOR: temperature=0.2（論理・分析）\n"
            "- 🟢 BALTHASAR: temperature=0.35（慎重・保守）\n"
            "- 🔵 CASPER: temperature=0.85（直感・創造）\n"
            "ラウンド1（独立分析）→ ラウンド2（相互批判）→ 最終合議 の3段階で計6回のAPIコールを行います。"
        )

    # MAGI合議実行ボタン
    btn_label = "⚡ MAGI合議システム 起動" if not use_llm_mode else "🤖 MAGI LLM合議 起動（Gemini API × 6コール）"
    if st.button(btn_label, type="primary", use_container_width=True):
        st.session_state['magi_result'] = None
        st.session_state['magi_mode'] = 'llm' if use_llm_mode else 'rule'

        if use_llm_mode:
            with st.spinner("🤖 MAGI合議中... R1: MELCHIOR(2.5-flash)→BALTHASAR(3.1-flash-lite)→CASPER(2.5-flash-lite) → R2: 相互批判 ※約30秒"):
                try:
                    llm_result = magi_system.run_magi_llm_deliberation(
                        df_magi.copy(),
                        api_key=GEMINI_API_KEY,
                        meta=race_metadata,
                        course_profile=magi_course,
                        chaos_rank=chaos_rank,
                    )
                    st.session_state['magi_result'] = llm_result
                except Exception as e:
                    st.error(f"LLMモードエラー: {e}")
        else:
            with st.spinner("🧠 三機のMAGIが合議中... (Round 1 → 2 → 3)"):
                result = magi_system.run_magi_deliberation(
                    df_magi.copy(),
                    course_profile=magi_course,
                    chaos_rank=chaos_rank
                )
                st.session_state['magi_result'] = result

    magi_result = st.session_state.get('magi_result')
    magi_mode_used = st.session_state.get('magi_mode', 'rule')

    # ── LLMモード結果表示 ──────────────────────────────────────
    if magi_result and magi_result.get('mode') == 'llm':
        if 'error' in magi_result:
            st.error(f"MAGIシステムエラー: {magi_result['error']}")
        else:
            st.markdown("---")
            st.markdown("## 🤖 LLM MAGI合議結果（独立AIによる合議）")

            # ── ラウンド1: 各MAGIの独立分析 ──
            st.markdown("### ラウンド1: 独立分析（APIコール × 3）")
            col_m, col_b, col_c = st.columns(3)

            def _show_llm_unit(col, unit_key, color, icon, r1_data, r2_data):
                with col:
                    st.markdown(f"<div style='border-left:5px solid {color};padding:10px;background:#fafafa'>", unsafe_allow_html=True)
                    model_used = r1_data.get('_model', '?')
                    st.markdown(f"#### {icon} {unit_key}")
                    st.caption(f"モデル: `{model_used}`")
                    if '_error' in r1_data:
                        st.error(f"エラー: {r1_data['_error']}")
                        if '_raw' in r1_data:
                            with st.expander("rawレスポンス（デバッグ用）"):
                                st.code(r1_data['_raw'][:500], language=None)
                    else:
                        # R1出力
                        with st.expander("ラウンド1 回答", expanded=True):
                            st.code(r1_data.get('_raw', ''), language=None)
                        # R2出力（批判・修正後）
                        if r2_data and '_error' not in r2_data:
                            with st.expander("ラウンド2 批判・修正後", expanded=False):
                                st.code(r2_data.get('_raw', ''), language=None)
                        elif r2_data and '_error' in r2_data:
                            st.warning(f"R2失敗: {r2_data['_error']}")
                    st.markdown("</div>", unsafe_allow_html=True)

            r1 = magi_result['round1']
            r2 = magi_result['round2']
            _show_llm_unit(col_m, "MELCHIOR-1 (科学者)", "#e74c3c", "🔴", r1['melchior'], r2['melchior'])
            _show_llm_unit(col_b, "BALTHASAR-2 (母)", "#2ecc71", "🟢", r1['balthasar'], r2['balthasar'])
            _show_llm_unit(col_c, "CASPER-3 (直感)", "#3498db", "🔵", r1['casper'], r2['casper'])

            # ── 最終合議結果 ──
            st.markdown("---")
            st.markdown("## ⚡ MAGI最終合議（LLMモード）")
            final = magi_result['final_prediction']

            if final.get('consensus_achieved'):
                st.success("✅ **合議成立** — 2機以上のAIが合意した馬が確定されました")
            else:
                st.warning("⚠️ **合議分裂** — 3機の意見が分かれています")

            # 得票テーブル
            vote_data = []
            for rank_i, (ub, data) in enumerate(magi_result['vote_tally'].items()):
                if rank_i >= 8: break
                vote_data.append({
                    '順位': rank_i + 1,
                    '馬番': int(ub),
                    '馬名': data['name'],
                    '得票': data['votes'],
                    '推薦AI': ", ".join(data['supporters']),
                    '合議': "✅" if len(data['supporters']) >= 2 else "－"
                })
            if vote_data:
                st.dataframe(pd.DataFrame(vote_data), use_container_width=True, hide_index=True)

            # 最終推奨馬券
            consensus_h = final.get('consensus_horses', [])
            if consensus_h:
                st.markdown("**🎯 合議成立馬による推奨馬券:**")
                ubs = [str(h['umaban']) for h in consensus_h[:3]]
                if len(ubs) >= 3:
                    st.info(f"3連複BOX: {' - '.join(ubs[:3])}")
                if len(ubs) >= 2:
                    st.info(f"馬連: {ubs[0]} - {ubs[1]}")

                # CASPERのパターン
                cas_final = magi_result['final']['casper']
                if 'pattern_a' in cas_final:
                    pa = " - ".join(map(str, cas_final['pattern_a']))
                    pb = " - ".join(map(str, cas_final.get('pattern_b', [])))
                    st.info(f"🔵 CASPER パターンA: {pa} / パターンB: {pb}")

        # ルールベースモードの結果表示はここで終了
        st.markdown("---")
        st.markdown("*(ルールベース結果を見るには「⚡ ルールベースモード」で再実行してください)*")

    elif magi_result and magi_result.get('mode') != 'llm':
        if 'error' in magi_result:
            st.error(f"MAGIシステムエラー: {magi_result['error']}")
        else:
            r1 = magi_result['round1']
            r2 = magi_result['round2_critiques']
            r3 = magi_result['round3']
            final = magi_result['final_prediction']

            # ─── ラウンド1: 初期提案 ───
            st.markdown("---")
            st.markdown("<div style='font-family:Orbitron,monospace;font-size:15px;font-weight:700;color:#00ff44;letter-spacing:3px;text-shadow:0 0 12px #00ff44,0 0 24px #00ff4466;padding:10px 0 6px;border-bottom:1px solid #00ff4433;margin-bottom:12px;'>▶ ROUND 1 — 各MAGIの独立分析</div>", unsafe_allow_html=True)

            col_m, col_b, col_c = st.columns(3)

            with col_m:
                mel = r1['melchior']
                horse_rows_m = "".join([
                    f"<div style='padding:5px 0;border-bottom:1px solid #ff333322;'>"
                    f"<span style='color:#ff3333;font-family:Orbitron,monospace;font-size:11px;'>[{'🥇🥈🥉'[i] if i<3 else str(i+1)}]</span> "
                    f"<span style='color:#ffffff;'>{h['Umaban']}番 {h['Name']}</span> "
                    f"<span style='color:#ff8844;font-size:11px;'>SCORE:{h['MelchiorScore']:.1f}</span></div>"
                    for i, h in enumerate(mel['top_horses'][:3])
                ])
                st.markdown(f"""
<div class='melchior-card'>
  <div class='unit-label-mel'>🔴 MELCHIOR-1</div>
  <div class='unit-subtitle'>SCIENTIST — {mel['title']}</div>
  <hr style='border-color:#ff333333;margin:8px 0;'/>
  <div style='color:#ff666688;font-size:10px;letter-spacing:2px;margin-bottom:4px;'>PACE ANALYSIS</div>
  <div style='color:#ff9966;font-family:Orbitron,monospace;font-size:12px;'>{mel['pace_type']}</div>
  <div style='color:#ff8844;font-size:11px;margin:4px 0 8px;'>{mel['pace_note'][:60]}...</div>
  <div style='color:#ff666688;font-size:10px;letter-spacing:2px;margin-bottom:4px;'>FRONT RUNNERS: {mel['front_runner_count']} / FAVORED: {mel['favored_style']}</div>
  <div style='color:#ff666688;font-size:10px;letter-spacing:2px;margin:8px 0 4px;'>TOP SELECTION</div>
  {horse_rows_m}
  <div style='margin-top:8px;color:#ff3333;font-size:10px;'>CONFIDENCE: {mel['confidence']}%</div>
</div>""", unsafe_allow_html=True)

            with col_b:
                bal = r1['balthasar']
                horse_rows_b = "".join([
                    f"<div style='padding:5px 0;border-bottom:1px solid #00ff4422;'>"
                    f"<span style='color:#00ff44;font-family:Orbitron,monospace;font-size:11px;'>[{['🥇','🥈','🥉'][i] if i<3 else str(i+1)}]</span> "
                    f"<span style='color:#ffffff;'>{h['Umaban']}番 {h['Name']}</span> "
                    f"<span style='color:#00aa33;font-size:11px;'>EV:{'+' if float(h['EV'])>=0 else ''}{float(h['EV']):.2f}</span></div>"
                    for i, h in enumerate(bal['top_horses'][:3])
                ])
                rec_rows = "".join([
                    f"<div style='padding:4px 0;color:#88ff88;font-size:11px;'>▶ {r['type']} {'-'.join(map(str,r['horses']))} ({r['est_odds']}倍)</div>"
                    for r in bal['recommendations'][:3]
                ])
                st.markdown(f"""
<div class='balthasar-card'>
  <div class='unit-label-bal'>🟢 BALTHASAR-2</div>
  <div class='unit-subtitle'>MOTHER — {bal['title']}</div>
  <hr style='border-color:#00ff4433;margin:8px 0;'/>
  <div style='color:#00ff4488;font-size:10px;letter-spacing:2px;margin-bottom:4px;'>CHAOS RANK: {bal['chaos_rank']} / POSITIVE EV: {bal['positive_ev_count']}頭</div>
  <div style='color:#00ff4488;font-size:10px;letter-spacing:2px;margin:8px 0 4px;'>EV TOP SELECTION</div>
  {horse_rows_b}
  <div style='color:#00ff4488;font-size:10px;letter-spacing:2px;margin:10px 0 4px;'>RECOMMENDED BETS</div>
  {rec_rows}
  <div style='margin-top:8px;color:#00ff44;font-size:10px;'>MIN INVESTMENT: ¥{bal['min_investment']:,}</div>
</div>""", unsafe_allow_html=True)

            with col_c:
                cas = r1['casper']
                def _cas_pat_html(pat, color):
                    rows = "".join([
                        f"<span style='color:{color};font-family:Orbitron,monospace;font-size:18px;font-weight:700;'>{h['Umaban']}</span>"
                        f"<span style='color:#ff8844;font-size:12px;'> {h['Name']} </span>"
                        for h in pat['horses']
                    ])
                    return f"""<div style='padding:8px 0;border-bottom:1px solid {color}22;'>
<div style='color:{color}88;font-size:9px;letter-spacing:3px;'>{pat['label']} — CONF:{pat['confidence']}%</div>
<div style='margin-top:4px;'>{rows}</div></div>"""
                st.markdown(f"""
<div class='casper-card'>
  <div class='unit-label-cas'>🔵 CASPER-3</div>
  <div class='unit-subtitle'>WOMAN — {cas['title']}</div>
  <hr style='border-color:#3399ff33;margin:8px 0;'/>
  {_cas_pat_html(cas['pattern_a'], '#3399ff')}
  {_cas_pat_html(cas['pattern_b'], '#aa44ff')}
</div>""", unsafe_allow_html=True)

            # ─── ラウンド2: 相互批判 ───
            st.markdown("---")
            st.markdown("<div style='font-family:Orbitron,monospace;font-size:15px;font-weight:700;color:#00ff44;letter-spacing:3px;text-shadow:0 0 12px #00ff44,0 0 24px #00ff4466;padding:10px 0 6px;border-bottom:1px solid #00ff4433;margin-bottom:12px;'>▶ ROUND 2 — 相互批判フェーズ</div>", unsafe_allow_html=True)

            with st.expander("🔍 各MAGIへの批判ログ（クリックで展開）", expanded=True):
                c2_m, c2_b, c2_c = st.columns(3)
                with c2_m:
                    st.markdown("**→ MELCHIOR-1 への批判**")
                    for crit in r2['to_melchior']:
                        st.warning(crit)
                    if not r2['to_melchior']:
                        st.success("批判なし。分析は堅固。")
                with c2_b:
                    st.markdown("**→ BALTHASAR-2 への批判**")
                    for crit in r2['to_balthasar']:
                        st.warning(crit)
                    if not r2['to_balthasar']:
                        st.success("批判なし。分析は堅固。")
                with c2_c:
                    st.markdown("**→ CASPER-3 への批判**")
                    for crit in r2['to_casper']:
                        st.warning(crit)
                    if not r2['to_casper']:
                        st.success("批判なし。分析は堅固。")

            # ─── ラウンド3: 自己改善後の最終提案 ───
            st.markdown("---")
            st.markdown("<div style='font-family:Orbitron,monospace;font-size:15px;font-weight:700;color:#00ff44;letter-spacing:3px;text-shadow:0 0 12px #00ff44,0 0 24px #00ff4466;padding:10px 0 6px;border-bottom:1px solid #00ff4433;margin-bottom:12px;'>▶ ROUND 3 — 自己改善・再提案</div>", unsafe_allow_html=True)

            with st.expander("🔄 改善ノート", expanded=False):
                c3_m, c3_b, c3_c = st.columns(3)
                with c3_m:
                    st.markdown("**MELCHIOR-1 の改善メモ**")
                    for note in r3['melchior'].get('refinement_notes', []):
                        st.info(note)
                with c3_b:
                    st.markdown("**BALTHASAR-2 の改善メモ**")
                    for note in r3['balthasar'].get('refinement_notes', []):
                        st.info(note)
                with c3_c:
                    st.markdown("**CASPER-3 の改善メモ**")
                    for note in r3['casper'].get('refinement_notes', []):
                        st.info(note)

            # ─── 最終合議結果 ───
            st.markdown("---")
            st.markdown("<div style='font-family:Orbitron,monospace;font-size:15px;font-weight:700;color:#00ff44;letter-spacing:3px;text-shadow:0 0 12px #00ff44,0 0 24px #00ff4466;padding:10px 0 6px;border-bottom:1px solid #00ff4433;margin-bottom:12px;'>⚡ 最終合議結果 — MAGI VERDICT</div>", unsafe_allow_html=True)

            # ─── 合議結果パネル（サイバーパンク） ───
            consensus_ok = final['consensus_achieved']
            vote_tally = magi_result['vote_tally']
            vote_items = sorted(vote_tally.items(), key=lambda x: x[1]['votes'], reverse=True)

            # 得票HTMLテーブル
            RANK_LABELS = ['01', '02', '03', '04', '05']
            RANK_ICONS  = ['🥇', '🥈', '🥉', '', '']
            vote_html_rows = ""
            for ri, (ub, vd) in enumerate(vote_items[:5]):
                supporters_str = " / ".join(vd['supporters']) if vd['supporters'] else "-"
                is_consensus = len(vd['supporters']) >= 2
                row_border = "border-left:3px solid #ffaa00;" if is_consensus else "border-left:3px solid #333;"
                badge = "<span style='color:#00ff44;font-size:9px;margin-left:8px;'>✔ CONSENSUS</span>" if is_consensus else ""
                vote_html_rows += f"""
<div style='display:flex;align-items:center;gap:10px;padding:8px 12px;margin:3px 0;background:#050510;{row_border};font-family:Share Tech Mono,monospace;'>
  <span style='color:#ffaa00;font-family:Orbitron,monospace;font-size:16px;font-weight:700;min-width:28px;'>{RANK_ICONS[ri] if ri<3 else str(ri+1)}</span>
  <span style='color:#ff8844;font-size:11px;min-width:48px;'>【{str(int(ub)).zfill(2)}番】</span>
  <span style='color:#ffffff;font-size:13px;flex:1;'>{vd['name']}</span>
  <span style='color:#ffaa00;font-size:12px;min-width:50px;'>{vd['votes']:.1f}票</span>
  <span style='color:#ff6622;font-size:10px;'>{supporters_str}</span>
  {badge}
</div>"""

            # ── 動的馬券推奨（generate_bet_recommendations使用）──
            # 先に信頼度を計算しておく
            mel_conf_pre = r1['melchior'].get('confidence', 50)
            cas_a_conf_pre = r1['casper']['pattern_a']['confidence']
            cas_b_conf_pre = r1['casper']['pattern_b']['confidence']
            overall_conf_pre = round((mel_conf_pre + cas_a_conf_pre + cas_b_conf_pre) / 3, 1)

            bet_recs = magi_system.generate_bet_recommendations(
                magi_result=magi_result,
                chaos_rank=chaos_rank,
                overall_conf=overall_conf_pre,
            )

            # リスク別のスタイル定義
            _risk_colors = {'LOW': '#00ff44', 'MID': '#ffaa00', 'HIGH': '#ff3333'}
            _risk_labels = {'LOW': 'LOW RISK', 'MID': 'MID RISK', 'HIGH': 'HIGH RISK'}

            # 馬券カードHTML生成
            bet_cards_html = ""
            for rec in bet_recs:
                risk_c = _risk_colors.get(rec['risk'], '#888888')
                risk_lbl = _risk_labels.get(rec['risk'], rec['risk'])
                note_html = f"<div style='color:#888;font-size:9px;margin-top:3px;'>※{rec.get('note','')}</div>" if rec.get('note') else ""
                bet_cards_html += f"""
<div style='background:#050510;border:1px solid {risk_c}44;border-top:2px solid {risk_c};
            padding:12px 14px;min-width:140px;flex:1;'>
  <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;'>
    <span style='color:{risk_c};font-family:Orbitron,monospace;font-size:11px;font-weight:700;letter-spacing:2px;'>
      {rec['emoji']} {rec['label']}
    </span>
    <span style='color:{risk_c}88;font-size:8px;letter-spacing:1px;'>{risk_lbl}</span>
  </div>
  <div style='color:#ffffff;font-family:Orbitron,monospace;font-size:16px;font-weight:700;
              letter-spacing:3px;text-shadow:0 0 8px {risk_c}66;margin-bottom:6px;'>
    {rec['horses']}
  </div>
  <div style='color:#ff8844;font-size:10px;line-height:1.4;'>{rec['reason']}</div>
  {note_html}
</div>"""

            consensus_label = "<span class='consensus-ok'>⬡ CONSENSUS ACHIEVED — EXECUTE</span>" if consensus_ok else "<span class='consensus-ng'>⚠ CONSENSUS PENDING — REVIEW</span>"

            st.markdown(f"""
<div class='magi-consensus'>
  <div class='consensus-title'>⬡ MAGI FINAL CONSENSUS (RULE MODE)</div>
  {consensus_label}
  <div style='margin:14px 0;'>{vote_html_rows}</div>
  <div style='border-top:1px solid #ffaa0044;padding-top:14px;margin-top:4px;'>
    <div style='color:#ffaa0088;font-size:9px;letter-spacing:3px;margin-bottom:10px;'>
      RECOMMENDED BETTING TICKETS — 波乱度:{chaos_rank} / 信頼度:{overall_conf_pre:.0f}%
    </div>
    <div style='display:flex;gap:10px;flex-wrap:wrap;'>
      {bet_cards_html}
    </div>
  </div>
</div>""", unsafe_allow_html=True)

            # 予測信頼度の総合評価
            mel_conf = r1['melchior'].get('confidence', 50)
            cas_a_conf = r1['casper']['pattern_a']['confidence']
            cas_b_conf = r1['casper']['pattern_b']['confidence']
            overall_conf = round((mel_conf + cas_a_conf + cas_b_conf) / 3, 1)

            st.markdown(f"<div style='font-family:Orbitron,monospace;font-size:15px;font-weight:700;color:#00ff44;letter-spacing:3px;text-shadow:0 0 12px #00ff44,0 0 24px #00ff4466;padding:10px 0 6px;border-bottom:1px solid #00ff4433;margin-bottom:12px;'>📊 総合信頼度: {overall_conf}%</div>", unsafe_allow_html=True)
            if overall_conf >= 75:
                st.success(f"高信頼度 ({overall_conf}%) — 積極的な投資を推奨")
            elif overall_conf >= 55:
                st.info(f"中程度の信頼度 ({overall_conf}%) — 慎重な少額投資を推奨")
            else:
                st.warning(f"低信頼度 ({overall_conf}%) — 見送りまたは最小賭けを推奨")

            st.markdown("</div>", unsafe_allow_html=True)

            # ─── 詳細スコアテーブル ───
            with st.expander("📋 全馬MAGIスコア詳細", expanded=False):
                mel_scores = {row['Umaban']: row['MelchiorScore'] for row in r1['melchior']['all_scores']}
                bal_scores = {row['Umaban']: {'EV': row['EV'], 'Odds': row['Odds']} for row in r1['balthasar']['all_scores']}
                cas_scores = {row['Umaban']: row['PlaceScore'] for row in r1['casper']['all_scores']}

                detail_rows = []
                for _, row in df_magi.iterrows():
                    ub = row['Umaban']
                    detail_rows.append({
                        '馬番': int(ub),
                        '馬名': row.get('Name', '?'),
                        '単勝': float(row.get('Odds', 0)),
                        '人気': int(row.get('Popularity', 99)),
                        'MELCHIOR\n展開スコア': mel_scores.get(ub, 0),
                        'BALTHASAR\nEV': round(float(bal_scores.get(ub, {}).get('EV', 0)), 3),
                        'CASPER\n複勝スコア': cas_scores.get(ub, 0),
                    })

                detail_df = pd.DataFrame(detail_rows).sort_values('MELCHIOR\n展開スコア', ascending=False)
                st.dataframe(detail_df, use_container_width=True, hide_index=True)

    # ─────────────────────────────────────────────────────
    # MAGIトレーニング（合議の下に配置）
    # ─────────────────────────────────────────────────────

    st.markdown("---")
    st.markdown("<div style='font-family:Orbitron,monospace;font-size:15px;font-weight:700;color:#00ff44;letter-spacing:3px;text-shadow:0 0 12px #00ff44,0 0 24px #00ff4466;padding:10px 0 6px;border-bottom:1px solid #00ff4433;margin:16px 0 12px;'>🎓 MAGIトレーニング — 過去データで自動学習</div>", unsafe_allow_html=True)
    st.info(
        "Kaggle過去データ（2010-2025年、約19.8万レース）を使ってMAGIパラメータを自動最適化します。\n"
        "「予測→実績比較→改善」を繰り返し、的中率80%を目指します。"
    )

    from core import magi_trainer
    importlib.reload(magi_trainer)

    # 現在の重みを表示
    with st.expander("⚙️ 現在のMAGIパラメータ", expanded=False):
        current_w = magi_trainer.load_weights()
        w_col1, w_col2 = st.columns(2)
        param_items = list(current_w.items())
        half = len(param_items) // 2
        with w_col1:
            for k, v in param_items[:half]:
                st.metric(k, f"{v:.3f}" if isinstance(v, float) else v)
        with w_col2:
            for k, v in param_items[half:]:
                st.metric(k, f"{v:.3f}" if isinstance(v, float) else v)

    # トレーニング設定
    tr_col1, tr_col2, tr_col3 = st.columns(3)
    with tr_col1:
        train_samples = st.selectbox("バックテストサンプル数", [50, 100, 200, 500], index=1,
            help="多いほど精度が上がるが時間がかかる")
    with tr_col2:
        train_iterations = st.selectbox("最適化イテレーション数", [10, 20, 50, 100], index=1,
            help="多いほど探索が深くなる")
    with tr_col3:
        train_year = st.selectbox("学習対象年", [None, 2024, 2023, 2022, 2021],
            format_func=lambda x: "直近2年" if x is None else f"{x}年",
            help="特定年のデータで学習")

    if "magi_train_log" not in st.session_state:
        st.session_state["magi_train_log"] = []
    if "magi_train_result" not in st.session_state:
        st.session_state["magi_train_result"] = None

    if st.button("🚀 MAGIトレーニング開始", type="primary", use_container_width=True):
        st.session_state["magi_train_log"] = []
        st.session_state["magi_train_result"] = None

        log_placeholder = st.empty()
        progress_bar = st.progress(0)

        logs = []

        def log_cb(msg):
            logs.append(msg)
            log_placeholder.code("\n".join(logs[-30:]), language=None)

        def prog_cb(it, total, score=None):
            progress_bar.progress(int(it / total * 100))

        with st.spinner("📦 Kaggleデータをロード中..."):
            dfs = magi_trainer.load_kaggle_data()

        if dfs is None:
            st.error("❌ Kaggleデータのロードに失敗しました")
        else:
            st.success(f"✅ データロード完了: {len(dfs.get('results', pd.DataFrame()))}件の出走記録")

            with st.spinner("🧠 MAGIトレーニング実行中..."):
                try:
                    train_result = magi_trainer.optimize_weights(
                        dfs=dfs,
                        n_samples=train_samples,
                        n_iterations=train_iterations,
                        year_filter=train_year,
                        progress_callback=prog_cb,
                        log_callback=log_cb,
                    )
                    st.session_state["magi_train_result"] = train_result
                    progress_bar.progress(100)
                except Exception as e:
                    st.error(f"トレーニングエラー: {e}")
                    import traceback
                    st.code(traceback.format_exc())

    # トレーニング結果の表示
    train_result = st.session_state.get("magi_train_result")
    if train_result:
        if "error" in train_result:
            st.error(f"エラー: {train_result['error']}")
        else:
            st.markdown("### 📊 トレーニング結果")

            res_col1, res_col2, res_col3, res_col4 = st.columns(4)
            final_m = train_result.get("final_metrics", {})
            baseline_score = train_result.get("baseline_score", 0)
            best_score = train_result.get("best_score", 0)
            improvement = train_result.get("improvement", 0)

            with res_col1:
                st.metric("最終的中率 (合議top3)", f"{best_score:.1f}%",
                    delta=f"+{improvement:.1f}%" if improvement > 0 else f"{improvement:.1f}%")
            with res_col2:
                st.metric("CASPERパターン的中率", f"{final_m.get('casper_hit_rate', 0):.1f}%")
            with res_col3:
                st.metric("1着予測的中率", f"{final_m.get('winner_hit_rate', 0):.1f}%")
            with res_col4:
                st.metric("サンプル数", f"{final_m.get('total', 0)}レース")

            # 目標達成チェック
            if best_score >= 80:
                st.success(f"🎯 目標達成！ 的中率 {best_score:.1f}% ≥ 80%")
            elif best_score >= 65:
                st.info(f"📈 良好。的中率 {best_score:.1f}% (目標: 80%)")
            else:
                st.warning(f"⚠️ 的中率 {best_score:.1f}%。サンプル数・イテレーション数を増やしてください。")

            # 各MAGI的中率
            st.markdown("**各MAGIユニットの的中率:**")
            magi_acc_col1, magi_acc_col2, magi_acc_col3 = st.columns(3)
            with magi_acc_col1:
                st.metric("🔴 MELCHIOR", f"{final_m.get('mel_hit_rate', 0):.1f}%")
            with magi_acc_col2:
                st.metric("🟢 BALTHASAR", f"{final_m.get('bal_hit_rate', 0):.1f}%")
            with magi_acc_col3:
                st.metric("🔵 CASPER (A+B)", f"{final_m.get('casper_hit_rate', 0):.1f}%")

            # 最適化履歴
            history = train_result.get("history", [])
            if len(history) > 1:
                with st.expander("📈 最適化履歴", expanded=False):
                    hist_df = pd.DataFrame([
                        {"イテレーション": h["iteration"], "的中率": h["score"]}
                        for h in history
                    ])
                    st.line_chart(hist_df.set_index("イテレーション")["的中率"])

                    # 最適化されたパラメータ
                    st.markdown("**最適化後のパラメータ:**")
                    best_w = train_result.get("best_weights", {})
                    default_w = magi_trainer.DEFAULT_WEIGHTS
                    param_rows = []
                    for k, v in best_w.items():
                        default_v = default_w.get(k, v)
                        diff = v - default_v if isinstance(v, (int, float)) else 0
                        param_rows.append({
                            "パラメータ": k,
                            "最適値": round(v, 4) if isinstance(v, float) else v,
                            "デフォルト": default_v,
                            "差分": round(diff, 4) if isinstance(diff, float) else diff,
                        })
                    st.dataframe(pd.DataFrame(param_rows), hide_index=True, use_container_width=True)

            st.success("💾 最適化されたパラメータは `magi_weights.json` に保存済みです。次回のMAGI合議から自動的に適用されます。")


# ══════════════════════════════════════════════════════════════
# 🎓 MAGI 回顧学習タブ
# ══════════════════════════════════════════════════════════════

if nav == "🎓 MAGI回顧学習":
    st.header("🎓 MAGI 回顧学習 - 過去レース振り返りセッション")

    st.markdown("""
    **このタブでできること:**
    - 過去のレースRaceIDを入力し、アプリの全スコア（Ranking Table相当）でMAGI予測を自動生成
    - netkeibaから**実際の結果**を取得
    - **3人格（MELCHIOR・BALTHASAR・CASPER）がLLMで回顧** → 「なぜ外れたか」「次回どうすべきか」を議論
    - 学習結果はMAGIのシステムプロンプトに活かされます
    """)

    retro_cols1 = st.columns([2, 1, 1, 2])
    with retro_cols1[0]:
        retro_race_id = st.text_input(
            "回顧対象 RaceID",
            value="",
            placeholder="例: 202406050811",
            key="retro_race_id_input"
        )
    with retro_cols1[1]:
        retro_date = st.text_input("日付 (保存用)", placeholder="例: 2024/12/22", key="retro_date_input")
    with retro_cols1[2]:
        retro_place = st.text_input("場所 (保存用)", placeholder="例: 中山", key="retro_place_input")
    with retro_cols1[3]:
        retro_name = st.text_input("レース名 (保存用)", placeholder="例: 有馬記念", key="retro_name_input")

    retro_cols2 = st.columns(2)
    with retro_cols2[0]:
        retro_course_opts = ["標準", "小回り(中山・中京・福島)", "直線が長い(東京・京都外回り)", "洋芝(札幌・函館)"]
        retro_course = st.selectbox("コース特性", retro_course_opts, key="retro_course")
    with retro_cols2[1]:
        retro_chaos_opts = ["C (堅い)", "B (標準)", "A (波乱)", "S (大波乱)"]
        retro_chaos = st.select_slider("波乱度（事後評価）", options=retro_chaos_opts, value="B (標準)", key="retro_chaos")

    retro_btn = st.button("🎓 回顧セッション開始", type="primary", use_container_width=False, key="retro_btn")

    # ── Session State for Interactive Learning ──
    if 'retro_session' not in st.session_state:
        st.session_state.retro_session = None

    if retro_btn and retro_race_id:
        st.session_state.retro_session = {
            'race_id': str(retro_race_id).strip(),
            'date': str(retro_date).strip(),
            'place': str(retro_place).strip(),
            'name': str(retro_name).strip()
        }
        st.session_state.retro_chat_history = []
        
        retro_race_id_str = st.session_state.retro_session['race_id']
        st.info(f"📡 レースID: {retro_race_id_str} のデータを取得中...")

        # Step 1: レースカードデータ取得
        with st.spinner("Step 1/4: レースカードデータ取得中..."):
            try:
                df_retro = scraper.get_race_data(retro_race_id_str, use_storage=False)
            except Exception as e:
                df_retro = pd.DataFrame()
                st.warning(f"スクレイパーエラー: {e}")

        if df_retro.empty:
            st.error("❌ レースカードデータを取得できませんでした。RaceIDを確認してください。")
            st.session_state.retro_session = None
            st.stop()
        
        # Step 2: スコア計算
        with st.spinner("Step 2/4: BattleScore・OguraIndex等の計算中..."):
            try:
                df_retro = calculator.calculate_all(df_retro)
            except Exception as e:
                st.warning(f"スコア計算エラー（部分): {e}")

        # Step 3: MAGI合議
        with st.spinner("Step 3/4: MAGI合議（ルールベース）実行中..."):
            try:
                from core.magi_system import run_magi_deliberation
                chaos_char = retro_chaos[0]
                magi_pred = run_magi_deliberation(df_retro, course_profile=retro_course, chaos_rank=chaos_char)
            except Exception as e:
                magi_pred = {}
                st.warning(f"MAGI合議エラー: {e}")

        # Step 4: 実際の結果取得
        with st.spinner("Step 4/4: netkeibaから実際の結果を取得中..."):
            try:
                actual_result = scraper.fetch_comprehensive_result(retro_race_id_str)
            except Exception as e:
                actual_result = {}
                st.warning(f"結果取得エラー: {e}")

        if not actual_result or not actual_result.get('horses'):
            st.error("❌ 実際の結果を取得できませんでした。確定済みレースか確認してください。")
            st.session_state.retro_session = None
            st.stop()

        # Step 5: LLM回顧セッション
        with st.spinner("🔴🟢🔵 3ユニットが回顧中... (約30〜40秒)"):
            try:
                from core.magi_retrospective import run_magi_retrospective
                retro_result = run_magi_retrospective(
                    df=df_retro,
                    magi_prediction=magi_pred,
                    actual_result=actual_result,
                    api_key=GEMINI_API_KEY,
                    meta={'course_profile': retro_course, 'chaos_rank': chaos_char}
                )
            except Exception as e:
                st.error(f"回顧セッションエラー: {e}")
                retro_result = None

        # Store to session and RERUN to display cleanly
        st.session_state.retro_session.update({
            'df_retro': df_retro,
            'magi_pred': magi_pred,
            'actual_result': actual_result,
            'retro_result': retro_result
        })
        st.rerun()

    # ── Render Session Data ──
    if st.session_state.retro_session and 'retro_result' in st.session_state.retro_session:
        rs = st.session_state.retro_session
        df_retro = rs['df_retro']
        magi_pred = rs['magi_pred']
        actual_result = rs['actual_result']
        retro_result = rs['retro_result']

        st.success(f"✅ レースデータ取得完了")
        # 予測結果プレビュー
        if magi_pred and 'final_prediction' in magi_pred:
            pred_horses = magi_pred['final_prediction'].get('horses', [])
            if pred_horses:
                pred_str = ', '.join([f"馬番{h['umaban']}({h.get('name','?')})" for h in pred_horses[:3]])
                st.info(f"🔮 MAGI事前予測TOP3: {pred_str}")

        # 実際の結果プレビュー
        from core.magi_retrospective import format_actual_result
        actual_text = format_actual_result(actual_result)
        with st.expander("📋 実際のレース結果（クリックで開く）", expanded=True):
            st.text(actual_text)

        st.divider()
        st.subheader("🧠 MAGI 回顧セッション（3人格がLLMで分析）")

        if retro_result:
            summary = retro_result.get('summary', {})
            pred_top3 = summary.get('predicted_top3', [])
            actual_top3 = summary.get('actual_top3', [])
            hits = summary.get('hits', [])
            hit_count = summary.get('hit_count', 0)

            hit_color = "🟢" if hit_count >= 2 else ("🟡" if hit_count == 1 else "🔴")
            st.markdown(f"### {hit_color} 予測精度: {summary.get('hit_rate_label', '?')} 的中")
            met1, met2, met3 = st.columns(3)
            met1.metric("MAGI予測TOP3", ", ".join(pred_top3) or "-")
            met2.metric("実際のTOP3", ", ".join(actual_top3) or "-")
            met3.metric("一致した馬番", ", ".join(str(h) for h in hits) or "なし")
            st.divider()

            retro_cols = st.columns(3)
            unit_configs = [
                ('melchior', '🔴 MELCHIOR-1', '科学者・論理'),
                ('balthasar', '🟢 BALTHASAR-2', '母・資金管理'),
                ('casper', '�� CASPER-3', '女・直感'),
            ]
            for col, (key, label, subtitle) in zip(retro_cols, unit_configs):
                with col:
                    r = retro_result.get(key, {})
                    if '_error' in r:
                         st.error(f"{label}: エラー")
                         continue
                    acc = r.get('prediction_accuracy', '不明')
                    acc_icon = "✅" if acc == "的中" else "❌"
                    st.markdown(f"#### {label}")
                    st.caption(subtitle)
                    st.markdown(f"**{acc_icon} {acc}**")

                    lesson = r.get('lesson_learned', '')
                    if lesson:
                        st.info(f"💡 **学習ポイント**: {lesson}")

                    with st.expander(f"{label} 全回顧内容", expanded=False):
                        display_map = {{
                            'key_miss_factor': '🔍 最大の見落とし',
                            'scientific_note': '🔬 科学的補足',
                            'odds_analysis': '📊 オッズ評価',
                            'bet_assessment': '💰 馬券評価',
                            'risk_note': '⚠️ リスク見落とし',
                            'intuition_review': '💭 直感の振り返り',
                            'pattern_a_result': '📌 パターンA結果',
                            'pattern_b_result': '📌 パターンB結果',
                            'hidden_signal': '👁 見落としたサイン',
                            'emotional_note': '💔 感情的振り返り',
                            'revised_confidence': '📈 次回信頼度',
                        }}
                        for field, label_j in display_map.items():
                            val = r.get(field)
                            if val is not None and val != '':
                                st.markdown(f"**{label_j}**: {val}")

            st.divider()
            with st.expander("📊 使用したRanking Table（解析データ）", expanded=False):
                display_cols = [c for c in ['Umaban', 'Name', 'Popularity', 'Odds', 'BattleScore', 'OguraIndex', 'AvgPosition', 'AvgAgari', 'Rank'] if c in df_retro.columns]
                if display_cols:
                    st.dataframe(df_retro[display_cols].reset_index(drop=True), use_container_width=True, hide_index=True)

        # ── 人間とMAGIの対話（Interactive Learning） ──
        st.divider()
        st.subheader("🗣 人間とMAGIの反省討論（Interactive Session）")
        st.markdown("レース結果を見た**あなたの直感やパドックの印象、気づいたサイン**を入力してください。AIと共に次へ繋がるロジックを探求します。")
        
        # 過去のチャットログを表示
        for msg in st.session_state.retro_chat_history:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
                
        user_insight = st.chat_input("なぜこの穴馬を当てられなかったのか？例：パドックで発汗がひどかったから切るべきだった")
        if user_insight:
            st.session_state.retro_chat_history.append({"role": "user", "content": user_insight})
            with st.chat_message("user"):
                st.write(user_insight)
                
            with st.chat_message("assistant"):
                with st.spinner("MAGIマスターAIが考察中..."):
                    from core.magi_retrospective import discuss_interactive_retrospective
                    # API Key is defined globally in app.py as GEMINI_API_KEY
                    response_text = discuss_interactive_retrospective(st.session_state.retro_session, user_insight, st.session_state.retro_chat_history[:-1], GEMINI_API_KEY)
                    st.write(response_text)
                    st.session_state.retro_chat_history.append({"role": "assistant", "content": response_text})
                    
            # 記録処理 (Log to diary)
            import os
            from datetime import datetime
            diary_dir = os.path.join("sandbox", "hyperagents")
            diary_file = os.path.join(diary_dir, "IMPROVEMENTS.md")
            if os.path.exists(diary_file):
                with open(diary_file, "a", encoding="utf-8") as f:
                    # 追加情報のフォーマット生成
                    date_str = rs.get('date', '')
                    place_str = rs.get('place', '')
                    name_str = rs.get('name', '')
                    
                    extra_parts = []
                    if date_str: extra_parts.append(date_str)
                    if place_str: extra_parts.append(place_str)
                    if name_str: extra_parts.append(name_str)
                    extra_text = f" ({' / '.join(extra_parts)})" if extra_parts else ""
                    
                    f.write(f"\n\n## [ HUMAN + AI Interactive Retro ] Race {rs['race_id']}{extra_text} [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
                    f.write(f"**Human**: {user_insight}\n")
                    f.write(f"**MAGI AI**: {response_text[:400]}...\n")


# ──────────────────────────────────────────────
# 🏇 騎手分析Pro（リニューアル版）
# ──────────────────────────────────────────────
if nav == "🏇 騎手分析Pro":
    st.header("🏇 騎手分析Pro")
    st.caption("N指数不使用 — 回収率・連対率ベースのスクリーニングエンジン")

    # --- ユーティリティインポート ---
    from utils.jockey_stats_db import JockeyStatsDB
    from utils.jockey_screening import screen_entry, ScreeningResult
    from utils.jockey_bayesian import bayesian_adjusted_rate
    from utils.jockey_track_condition import fetch_track_conditions, get_condition_for_venue

    _jpro_db = JockeyStatsDB()

    # --- カスタムCSS ---
    st.markdown("""
    <style>
    .jockey-flag-teppan {
        background: linear-gradient(135deg, #DC3545 0%, #C82333 100%);
        color: white; padding: 4px 10px; border-radius: 12px;
        font-weight: bold; font-size: 0.85em; display: inline-block;
        box-shadow: 0 2px 4px rgba(220,53,69,0.3);
    }
    .jockey-flag-myomi {
        background: linear-gradient(135deg, #FFC107 0%, #E0A800 100%);
        color: #333; padding: 4px 10px; border-radius: 12px;
        font-weight: bold; font-size: 0.85em; display: inline-block;
        box-shadow: 0 2px 4px rgba(255,193,7,0.3);
    }
    .jockey-flag-kiken {
        background: linear-gradient(135deg, #0D6EFD 0%, #0B5ED7 100%);
        color: white; padding: 4px 10px; border-radius: 12px;
        font-weight: bold; font-size: 0.85em; display: inline-block;
        box-shadow: 0 2px 4px rgba(13,110,253,0.3);
    }
    .jockey-card {
        background: #1e1e2e; border: 1px solid #333; border-radius: 12px;
        padding: 16px 20px; margin: 8px 0;
        transition: all 0.2s ease;
    }
    .jockey-card:hover {
        border-color: #666; box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }
    .jockey-stat-grid {
        display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: 8px; margin-top: 8px;
    }
    .jockey-stat-item {
        background: #2a2a3a; border-radius: 8px; padding: 8px 12px;
        text-align: center;
    }
    .jockey-stat-val {
        font-size: 1.3em; font-weight: bold; color: #6fcf97;
    }
    .jockey-stat-label {
        font-size: 0.75em; color: #888; margin-top: 2px;
    }
    </style>
    """, unsafe_allow_html=True)

    # --- メインUI: 1ページ完結体験（出馬表ビューを先頭に） ---
    jpro_tab3, jpro_tab1, jpro_tab2, jpro_tab4 = st.tabs([
        "✅ 最強予想ビュー (One-Push)",
        "🔍 詳細データ (コンビ/脚質)",
        "🚦 フラグ手動入力",
        "⚙️ 設定・データ管理",
    ])

    # =============================================
    # タブ1: コンビネーション分析
    # =============================================
    with jpro_tab1:
        st.subheader("マルチ・コンビネーション評価")

        jpro_analysis_type = st.radio(
            "分析タイプ",
            ["騎手×馬（継続騎乗・乗り替わり）", "騎手×厩舎（黄金コンビ）", "騎手×コース×脚質"],
            horizontal=True,
            key="jpro_analysis_type",
        )

        # --- 騎手×馬 ---
        if jpro_analysis_type == "騎手×馬（継続騎乗・乗り替わり）":
            st.markdown("##### 継続騎乗ボーナス & 乗り替わり期待値")

            jockey_name_input = st.text_input("騎手名で検索", key="jpro_jockey_horse",
                                               placeholder="例: ルメール")

            if jockey_name_input:
                try:
                    df_horse = _jpro_db.query_by_jockey(jockey_name_input, target_type="horse")
                    if not df_horse.empty:
                        # ベイズ補正を適用
                        avgs = _jpro_db.get_global_averages()
                        prior_strength = st.session_state.get("jpro_prior_strength", 20)
                        df_horse["補正連対率"] = df_horse.apply(
                            lambda r: bayesian_adjusted_rate(
                                r["top2_rate"], r["ride_count"],
                                avgs["avg_top2_rate"], prior_strength
                            ), axis=1
                        )
                        df_horse = df_horse.sort_values("補正連対率", ascending=False)

                        display_cols = {
                            "jockey_name": "騎手", "target_name": "馬名",
                            "ride_count": "騎乗回数", "win_count": "勝利数",
                            "top2_count": "連対数", "win_rate": "勝率",
                            "top2_rate": "生連対率", "補正連対率": "補正連対率",
                            "return_win": "単回収(%)", "return_place": "複回収(%)",
                            "updated_at": "更新日",
                        }
                        cols_to_show = [c for c in display_cols.keys() if c in df_horse.columns]
                        df_show = df_horse[cols_to_show].rename(columns=display_cols)

                        # 連対率50%以上をハイライト
                        def _highlight_top2(row):
                            if row.get("補正連対率", 0) >= 0.50:
                                return ["background-color: #FFEAEA"] * len(row)
                            elif row.get("補正連対率", 0) >= 0.30:
                                return ["background-color: #FFF8E1"] * len(row)
                            return [""] * len(row)

                        st.dataframe(
                            df_show.style.apply(_highlight_top2, axis=1),
                            use_container_width=True,
                            hide_index=True,
                        )
                        st.caption(f"📊 {len(df_show)}件のデータ（ベイズ補正済み、事前強度={prior_strength}）")
                    else:
                        st.info(f"「{jockey_name_input}」のデータがDBにありません。⚙️設定タブからCSVインポートまたはDB初期化してください。")
                except Exception as e:
                    st.warning(f"DB検索エラー: {e}")
                    st.info("⚙️設定タブからDB初期化を実行してください。")

        # --- 騎手×厩舎 ---
        elif jpro_analysis_type == "騎手×厩舎（黄金コンビ）":
            st.markdown("##### 黄金コンビ抽出")
            st.caption("単勝回収率120%以上 & 最低騎乗回数を満たすコンビを「黄金コンビ 🥇」として強調")

            min_rides_trainer = st.slider("最低騎乗回数", 5, 50, 15, key="jpro_trainer_min_rides")

            try:
                df_trainer = _jpro_db.query_by_target("trainer", min_rides=min_rides_trainer)
                if not df_trainer.empty:
                    avgs = _jpro_db.get_global_averages()
                    prior_strength = st.session_state.get("jpro_prior_strength", 20)
                    df_trainer["補正連対率"] = df_trainer.apply(
                        lambda r: bayesian_adjusted_rate(
                            r["top2_rate"], r["ride_count"],
                            avgs["avg_top2_rate"], prior_strength
                        ), axis=1
                    )
                    df_trainer = df_trainer.sort_values("return_win", ascending=False)

                    # 黄金コンビフラグ
                    df_trainer["黄金"] = df_trainer["return_win"].apply(
                        lambda x: "🥇 黄金コンビ" if x >= 120 else ""
                    )

                    display_cols = {
                        "jockey_name": "騎手", "target_name": "厩舎",
                        "ride_count": "騎乗回数", "win_count": "勝利数",
                        "top2_rate": "連対率", "補正連対率": "補正連対率",
                        "return_win": "単回収(%)", "return_place": "複回収(%)",
                        "黄金": "判定",
                    }
                    cols_to_show = [c for c in display_cols.keys() if c in df_trainer.columns]
                    df_show = df_trainer[cols_to_show].rename(columns=display_cols)

                    # ヒートマップスタイル（連対率カラーリング）
                    def _color_top2_rate(val):
                        try:
                            v = float(val)
                            if v >= 0.50:
                                return "color: #D32F2F; font-weight: bold"
                            elif v >= 0.30:
                                return "color: #F57C00"
                            elif v < 0.10:
                                return "color: #9E9E9E"
                        except (ValueError, TypeError):
                            pass
                        return ""

                    styled = df_show.style
                    if "補正連対率" in df_show.columns:
                        styled = styled.map(_color_top2_rate, subset=["補正連対率"])

                    st.dataframe(styled, use_container_width=True, hide_index=True)
                    st.caption(f"📊 {len(df_show)}件（最低{min_rides_trainer}回騎乗、ベイズ補正済み）")
                else:
                    st.info("該当データがありません。⚙️設定タブからCSVインポートしてください。")
            except Exception as e:
                st.warning(f"DB検索エラー: {e}")
                st.info("⚙️設定タブからDB初期化を実行してください。")

        # --- 騎手×コース×脚質 ---
        elif jpro_analysis_type == "騎手×コース×脚質":
            st.markdown("##### コース適性 & 馬場状態別成績")

            # 馬場状態の自動取得（キャッシュ: session_state）
            if "jpro_track_conditions" not in st.session_state:
                st.session_state["jpro_track_conditions"] = []
            if st.button("🌤️ 本日の馬場を取得", key="jpro_fetch_track"):
                with st.spinner("馬場状態を取得中..."):
                    conditions = fetch_track_conditions()
                    st.session_state["jpro_track_conditions"] = conditions
                    if conditions:
                        for c in conditions:
                            st.caption(f"🏟️ {c.venue} {c.surface}: **{c.condition}** ({c.updated_at})")
                    else:
                        st.info("馬場データを自動取得できませんでした。手動で選択してください。")

            col1, col2, col3 = st.columns(3)
            with col1:
                course_options = [
                    "全体",
                    "東京芝1600", "東京芝2000", "東京芝2400", "東京ダ1600",
                    "中山芝2000", "中山芝2500", "中山ダ1200", "中山ダ1800",
                    "阪神芝1600", "阪神芝1800", "阪神芝2000", "阪神ダ1400",
                    "京都芝1600", "京都芝2000", "京都ダ1400", "京都ダ1800",
                    "中京芝2000", "中京ダ1800",
                    "新潟芝1600", "新潟芝2000",
                    "小倉芝1200", "小倉芝1800",
                    "札幌芝1800", "函館芝1200", "福島芝1800",
                ]
                course_select = st.selectbox("コース", course_options, key="jpro_course")
            with col2:
                style_select = st.selectbox("脚質", ["全体", "逃げ", "先行", "差し", "追込"], key="jpro_style")
            with col3:
                # 馬場自動取得結果をデフォルト値に反映
                track_options = ["全体", "良", "稍重", "重", "不良"]
                auto_idx = 0
                _tc = st.session_state.get("jpro_track_conditions", [])
                if _tc and course_select != "全体":
                    # コースから会場名を抽出（先頭2文字）
                    _venue_hint = course_select[:2] if len(course_select) >= 2 else ""
                    _auto_cond = get_condition_for_venue(_tc, _venue_hint)
                    if _auto_cond and _auto_cond in track_options:
                        auto_idx = track_options.index(_auto_cond)
                track_select = st.selectbox("馬場", track_options, index=auto_idx, key="jpro_track")

            try:
                target_name = None if course_select == "全体" else course_select
                df_course = _jpro_db.query_by_target("course", target_name=target_name)

                if not df_course.empty:
                    # 脚質フィルタ
                    if style_select != "全体":
                        df_course = df_course[df_course["running_style"] == style_select]
                    # 馬場フィルタ
                    if track_select != "全体":
                        df_course = df_course[df_course["track_condition"] == track_select]

                    if not df_course.empty:
                        avgs = _jpro_db.get_global_averages()
                        prior_strength = st.session_state.get("jpro_prior_strength", 20)
                        df_course["補正連対率"] = df_course.apply(
                            lambda r: bayesian_adjusted_rate(
                                r["top2_rate"], r["ride_count"],
                                avgs["avg_top2_rate"], prior_strength
                            ), axis=1
                        )
                        df_course = df_course.sort_values("補正連対率", ascending=False)

                        display_cols = {
                            "jockey_name": "騎手", "target_name": "コース",
                            "ride_count": "騎乗回数", "win_count": "勝利数",
                            "top2_rate": "連対率", "補正連対率": "補正連対率",
                            "return_win": "単回収(%)", "return_place": "複回収(%)",
                            "running_style": "脚質", "track_condition": "馬場",
                        }
                        cols_to_show = [c for c in display_cols.keys() if c in df_course.columns]
                        df_show = df_course[cols_to_show].rename(columns=display_cols)

                        st.dataframe(df_show, use_container_width=True, hide_index=True)
                        st.caption(f"📊 {len(df_show)}件（ベイズ補正済み）")
                    else:
                        st.info("フィルタ条件に合致するデータがありません。")
                else:
                    st.info("該当データがありません。⚙️設定タブからCSVインポートしてください。")
            except Exception as e:
                st.warning(f"DB検索エラー: {e}")
                st.info("⚙️設定タブからDB初期化を実行してください。")


    # =============================================
    # タブ2: スクリーニング
    # =============================================
    with jpro_tab2:
        st.subheader("🚦 フラグ自動判定")

        st.markdown("""
        | フラグ | 条件 | 意味 |
        |:---:|---|---|
        | 🔴 鉄板 | コースまたは厩舎の連対率≧40% & 騎乗30回以上 | 高確率で馬券に絡む軸候補 |
        | 🟡 妙味 | コースまたは厩舎の単回収≧120% & 騎乗15回以上 | 人気薄だが一発あり |
        | 🔵 危険 | 1〜3番人気 & コース連対率＜15% | 過剰人気の飛び候補 |
        """)

        st.markdown("---")

        # === 手動入力フォーム ===
        st.markdown("##### レースデータ入力")

        num_horses = st.number_input("出走頭数", 2, 18, 12, key="jpro_num_horses")

        # 閾値をsession_stateから取得（設定タブで変更可能）
        _iron_th = st.session_state.get("jpro_iron_threshold", 40) / 100.0
        _iron_rides = st.session_state.get("jpro_iron_min_rides", 30)
        _value_th = st.session_state.get("jpro_value_threshold", 120)
        _value_rides = st.session_state.get("jpro_value_min_rides", 15)
        _danger_th = st.session_state.get("jpro_danger_threshold", 15) / 100.0

        _custom_thresholds = {
            "iron_top2_rate": _iron_th,
            "iron_min_rides": _iron_rides,
            "value_return_win": float(_value_th),
            "value_min_rides": _value_rides,
            "danger_top2_rate": _danger_th,
            "danger_min_rides": 10,
            "danger_max_popularity": 3,
        }

        entries = []
        for i in range(int(num_horses)):
            with st.expander(f"馬番{i+1}", expanded=(i < 3)):
                cols = st.columns([2, 2, 1, 1, 1, 1, 1])
                horse = cols[0].text_input("馬名", key=f"jpro_scr_horse_{i}")
                jockey = cols[1].text_input("騎手", key=f"jpro_scr_jockey_{i}")
                pop = cols[2].number_input("人気", 0, 18, 0, key=f"jpro_scr_pop_{i}", help="0=未定")
                c_top2 = cols[3].number_input("コース連対%", 0.0, 100.0, 0.0, key=f"jpro_scr_ctop2_{i}")
                c_rides = cols[4].number_input("コース回数", 0, 999, 0, key=f"jpro_scr_crides_{i}")
                c_ret = cols[5].number_input("コース単回収%", 0.0, 500.0, 0.0, key=f"jpro_scr_cret_{i}")
                t_top2 = cols[6].number_input("厩舎連対%", 0.0, 100.0, 0.0, key=f"jpro_scr_ttop2_{i}")

                # 厩舎の追加入力
                cols2 = st.columns([1, 1])
                t_rides = cols2[0].number_input("厩舎回数", 0, 999, 0, key=f"jpro_scr_trides_{i}")
                t_ret = cols2[1].number_input("厩舎単回収%", 0.0, 500.0, 0.0, key=f"jpro_scr_tret_{i}")

                entries.append({
                    "馬番": i + 1,
                    "馬名": horse,
                    "騎手": jockey,
                    "人気": pop if pop > 0 else None,
                    "c_top2": c_top2 / 100,
                    "c_rides": c_rides,
                    "c_ret": c_ret,
                    "t_top2": t_top2 / 100,
                    "t_rides": t_rides,
                    "t_ret": t_ret,
                })

        if st.button("🚦 スクリーニング実行", key="jpro_run_screen", type="primary"):
            results = []
            for e in entries:
                if not e["馬名"]:
                    continue
                r = screen_entry(
                    jockey_course_top2_rate=e["c_top2"],
                    jockey_course_ride_count=e["c_rides"],
                    jockey_course_return_win=e["c_ret"],
                    jockey_trainer_top2_rate=e["t_top2"],
                    jockey_trainer_ride_count=e["t_rides"],
                    jockey_trainer_return_win=e["t_ret"],
                    popularity=e["人気"],
                    thresholds=_custom_thresholds,
                )
                results.append({
                    "馬番": e["馬番"],
                    "馬名": e["馬名"],
                    "騎手": e["騎手"],
                    "判定": r.label,
                    "理由": r.reason,
                })

            df_result = pd.DataFrame(results)
            st.session_state["jpro_screening_result"] = df_result

            # 色付き表示
            def highlight_flag(row):
                if "🔴" in str(row["判定"]):
                    return ["background-color: #FFEAEA"] * len(row)
                elif "🟡" in str(row["判定"]):
                    return ["background-color: #FFF8E1"] * len(row)
                elif "🔵" in str(row["判定"]):
                    return ["background-color: #E3F2FD"] * len(row)
                return [""] * len(row)

            st.dataframe(
                df_result.style.apply(highlight_flag, axis=1),
                use_container_width=True,
                hide_index=True,
            )

    # =============================================
    # タブ3: 出馬表ビュー (Jockey Ranking Table)
    # =============================================
    with jpro_tab3:
        st.markdown("### 🏇 騎手ランキング — レースID一発分析")
        st.caption("レースIDを1回入力するだけで、全騎手の全指標を取得・スコア化してランキング表示します。")

        # ── レースID入力 ──
        jp3_col1, jp3_col2 = st.columns([3, 1])
        with jp3_col1:
            jp_race_input = st.text_input(
                "レースID または URL",
                placeholder="例: 202505021211 または https://race.netkeiba.com/race/shutuba.html?race_id=...",
                value=st.session_state.get("main_race_id_input", ""),
                key="jp_race_input",
            )
        with jp3_col2:
            st.write("")
            jp_analyze_btn = st.button("🏇 分析開始", type="primary", key="jp_analyze_btn", use_container_width=True)

        jp_race_id = ""
        if jp_race_input:
            _m = re.search(r'(\d{12})', jp_race_input)
            if _m:
                jp_race_id = _m.group(1)

        if 'jp_analysis_result' not in st.session_state:
            st.session_state.jp_analysis_result = None

        # ── 💡 騎手分析Pro：総合スコア影響率（ウェイト）設定 ──
        _WEIGHTS_FILE_JOCKEY = os.path.join(os.path.dirname(__file__), ".score_weights_jockey.json")
        _jockey_weight_defaults = {
            "調子P": 0.0, "単回収%": 0.0, "人気": 0.0, "オッズ": 0.0,
            "PW指数": 0.0, "単勝USM": 0.0, "連対USM": 0.0, "複勝USM": 0.0,
            "フラグボーナス": 50.0
        }
        if 'score_weights_jockey' not in st.session_state:
            if os.path.exists(_WEIGHTS_FILE_JOCKEY):
                try:
                    import json as _json
                    with open(_WEIGHTS_FILE_JOCKEY, 'r', encoding='utf-8') as _wf:
                        _loaded = _json.load(_wf)
                    st.session_state['score_weights_jockey'] = {**_jockey_weight_defaults, **_loaded}
                except Exception:
                    st.session_state['score_weights_jockey'] = _jockey_weight_defaults.copy()
            else:
                st.session_state['score_weights_jockey'] = _jockey_weight_defaults.copy()

        sw_jockey = st.session_state['score_weights_jockey']
        for k, v in _jockey_weight_defaults.items():
            if k not in sw_jockey: sw_jockey[k] = v

        with st.expander("📊 騎手分析Pro：総合スコア影響率（ウェイト）設定", expanded=False):
            st.caption("各指標の生の値に、設定した影響率ウェイト（乗数）を乗算して総合スコアに加算します。フラグボーナス値は「妙味」「危険」フラグ時のポイント加算値です。")
            j_col1, j_col2 = st.columns(2)
            
            _J_WEIGHTS_CONFIG = [
                ("📈 調子Pウェイト", "調子P", "調子ポイント(好不調)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("💰 単回収%ウェイト", "単回収%", "コース単勝回収率(割合換算)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("👥 人気ウェイト", "人気", "人気値(1〜18、1人気ほど高得点化)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("オッズウェイト", "オッズ", "オッズ値(1.0〜150.0)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🥋 PW指数ウェイト", "PW指数", "PW指数(0〜150程度、/10)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🎯 単勝USMウェイト", "単勝USM", "単勝USM(割合換算)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🥈 連対USMウェイト", "連対USM", "連対USM(割合換算)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🥉 複勝USMウェイト", "複勝USM", "複勝USM(割合換算)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🚩 フラグボーナス値", "フラグボーナス", "「妙味」や「危険」フラグがついた際に、総合スコアに加算するポイントボーナス。", 0.0, 100.0, 1.0)
            ]
            
            def _sync_slider_jockey(sld_key, num_key):
                st.session_state[num_key] = st.session_state[sld_key]
            def _sync_num_jockey(num_key, sld_key):
                st.session_state[sld_key] = st.session_state[num_key]
                
            for _i, (label, sw_key, help_text, min_v, max_v, step_v) in enumerate(_J_WEIGHTS_CONFIG):
                sld_key = f"wsld_jockey_{sw_key}"
                num_key = f"wnum_jockey_{sw_key}"
                cur_v = float(sw_jockey.get(sw_key, 50.0 if sw_key == "フラグボーナス" else 0.0))
                
                cur_v = max(min_v, min(max_v, cur_v))
                
                if sld_key not in st.session_state: st.session_state[sld_key] = cur_v
                if num_key not in st.session_state: st.session_state[num_key] = cur_v
                
                target_col = j_col1 if _i % 2 == 0 else j_col2
                with target_col:
                    c_sld, c_num = st.columns([3, 1])
                    with c_sld:
                        st.slider(label, min_v, max_v, step=step_v, key=sld_key, 
                                  help=help_text, on_change=lambda sk=sld_key, nk=num_key: _sync_slider_jockey(sk, nk))
                    with c_num:
                        st.write("")
                        st.number_input("", min_v, max_v, step=step_v, key=num_key, label_visibility="collapsed",
                                        on_change=lambda nk=num_key, sk=sld_key: _sync_num_jockey(nk, sk))
                    
                    sw_jockey[sw_key] = float(st.session_state.get(num_key, cur_v))
            
            st.session_state['score_weights_jockey'] = sw_jockey
            
            jb_col1, jb_col2 = st.columns(2)
            with jb_col1:
                if st.button("💾 影響率を保存（全ランキングに適用）", key="btn_save_weights_jockey"):
                    try:
                        import json as _json
                        with open(_WEIGHTS_FILE_JOCKEY, 'w', encoding='utf-8') as _wf:
                            _json.dump(sw_jockey, _wf, ensure_ascii=False, indent=2)
                        st.success("✅ 騎手分析影響率を保存しました。")
                    except Exception as _e:
                        st.error(f"保存失敗: {_e}")
            with jb_col2:
                st.caption("💡 スライダーを動かすと、リアルタイムに下のランキングが再計算されます。")

        # ── 分析実行 ──
        if jp_analyze_btn and jp_race_id:


            _jp_pb = st.progress(0)
            _jp_st = st.empty()

            def jp_progress(current, total, msg):
                if total > 0:
                    _jp_pb.progress(min(1.0, current / total))
                _jp_st.caption(msg)

            with st.spinner("騎手データを収集中... (しばらくお待ちください)"):
                try:
                    _jp_result = jockey_analyzer.analyze_race(jp_race_id, progress_callback=jp_progress)
                    st.session_state.jp_analysis_result = _jp_result
                except Exception as _e:
                    st.error(f"分析エラー: {_e}")
                    import traceback
                    st.code(traceback.format_exc())

            _jp_pb.empty()
            _jp_st.empty()

        elif jp_analyze_btn and not jp_race_id:
            st.warning("有効なレースID（12桁の数字）を入力してください。")

        # ── 結果表示 ──
        _jp_res = st.session_state.get('jp_analysis_result')
        if _jp_res and _jp_res.get('entries'):


            _jp_venue = _jp_res.get('venue', '')
            _jp_entries = _jp_res.get('entries', [])

            st.success(f"✅ {_jp_venue}  {len(_jp_entries)}頭の分析完了")


            # ── スコアリング（全指標を集計） ──
            def _compute_full_score(entry, venue, weights=None):
                """全取得可能指標を合計してスコア化"""
                vs  = entry.get('venue_stats') or {}
                pr  = entry.get('jockey_profile') or {}
                ys  = pr.get('year_stats') or {}
                flg = entry.get('flags', [])
                score = 0.0
                breakdown = {}

                # 1) コース連対率 (補正済) — 最大配点40
                v_top2 = vs.get('adj_top2_rate', 0)
                s1 = v_top2 * 200
                score += s1
                breakdown['コース連対率'] = round(s1, 1)

                # 2) 本年勝率 — 最大配点30
                y_win = ys.get('win_rate', 0)
                s2 = y_win * 300
                score += s2
                breakdown['本年勝率'] = round(s2, 1)

                # 3) 本年連対率 — 最大配点20
                y_top2 = ys.get('top2_rate', 0)
                s3 = y_top2 * 100
                score += s3
                breakdown['本年連対率'] = round(s3, 1)

                # 4) 単回収率（コース）— 超過分のみ加点
                win_ret = vs.get('adj_win_return', 80)
                s4 = max(0, (win_ret - 80)) * 0.5
                score += s4
                breakdown['単回収率超過'] = round(s4, 1)

                # 5) 騎乗経験（コース）— ログスケール
                rides = vs.get('rides', 0)
                s5 = math.log10(rides + 1) * 8
                score += s5
                breakdown['コース騎乗経験'] = round(s5, 1)

                # 6) 通算騎乗数（信頼度）
                total_rides = ys.get('total', 0)
                s6 = math.log10(total_rides + 1) * 5
                score += s6
                breakdown['通算経験'] = round(s6, 1)

                # 7) コース複勝率（3着以内率）— 純粋な実力指標
                v_top3 = vs.get('top3_rate', 0)
                s7 = v_top3 * 80
                score += s7
                breakdown['コース複勝率'] = round(s7, 1)

                # 8) 本年複勝率
                y_top3 = ys.get('top3_rate', 0)
                s8 = y_top3 * 60
                score += s8
                breakdown['本年複勝率'] = round(s8, 1)

                # 9) PW指数 — 0~999の整数値想定、100点で最大10点加算
                pw_idx = entry.get('pw_index')
                if pw_idx is not None:
                    try:
                        s9 = float(pw_idx) * 0.1
                        score += s9
                        breakdown['PW指数'] = round(s9, 1)
                    except (TypeError, ValueError):
                        pass

                # 10) db-keiba ボーナス/減点（今レースにマッチした条件のみ加算）
                bonuses = entry.get('bonuses') or {}
                s10_add = bonuses.get('matched_bonus_score', 0.0)
                s10_sub = bonuses.get('matched_penalty_score', 0.0)  # 既に負値
                if s10_add != 0:
                    score += s10_add
                    breakdown['加算ボーナス'] = round(s10_add, 1)
                if s10_sub != 0:
                    score += s10_sub
                    breakdown['減点ペナルティ'] = round(s10_sub, 1)

                # 11) PRB (Percentage of Rivals Beaten) — 0.5が平均、高いほど良い
                _madv = entry.get('matched_adv') or {}
                prb_val = _madv.get('prb_overall', 0.5)
                s11 = (prb_val - 0.5) * 80
                if abs(s11) > 0.5:
                    score += s11
                    breakdown['PRB'] = round(s11, 1)

                # 12) Hot/Cold — 直近好調なら加点、不調なら減点
                hc = _madv.get('hot_cold', '—')
                if hc == 'HOT':
                    score += 10
                    breakdown['好調'] = 10
                elif hc == 'COLD':
                    score -= 8
                    breakdown['不調'] = -8

                # 13) 調子P（Jockey Form Score）
                form_score = entry.get('advanced_stats', {}).get('form_score', 0.0)
                if form_score != 0:
                    s13 = max(-15.0, min(15.0, form_score * 0.3))
                    score += s13
                    breakdown['調子P'] = round(s13, 1)

                # ── 🧠 人間変数＆作戦連携加減点（騎手分析Pro特別アップグレード） ──
                adv = entry.get('advanced_stats') or {}
                pos_skill = adv.get('pos_skill', 50.0)
                drive_power = adv.get('drive_power', 0.0)
                clutch_score = adv.get('clutch_score', 50.0)
                gate_adapt = adv.get('gate_adapt', 50.0)

                # 14) 位置取り力（ポジション奪取力）の実力加減点
                s14 = (pos_skill - 50.0) * 0.1
                if abs(s14) > 0.1:
                    score += s14
                    breakdown['位置取り力'] = round(s14, 1)

                # 15) 剛腕追い上げ数（差し馬との連携）
                r_style = _madv.get('riding_style', '—')
                s15 = drive_power * 0.5
                if r_style in ['差し・追込', '中団']:
                    s15 = s15 * 1.5  # 差し馬に乗る際は追い上げ力が1.5倍に生きる
                s15 = min(s15, 10.0) # 最大でも10点の加点に抑える
                if abs(s15) > 0.1:
                    score += s15
                    breakdown['剛腕追い上げ'] = round(s15, 1)

                # 16) プレッシャー耐性（人気との連携）
                try:
                    pop_val = int(entry.get('popularity', 99))
                    if pop_val <= 3:  # 上位人気のときにプレッシャー耐性が生きる
                        s16 = (clutch_score - 50.0) * 0.1
                        if abs(s16) > 0.1:
                            score += s16
                            breakdown['プレ耐性'] = round(s16, 1)
                except:
                    pass

                # 17) 外枠克服力（馬番・枠順との連携）
                try:
                    umaban_val = int(entry.get('umaban', 0))
                    if umaban_val >= 10:  # 外枠のときに外枠克服力が生きる
                        s17 = (gate_adapt - 50.0) * 0.1
                        if abs(s17) > 0.1:
                            score += s17
                            breakdown['外枠克服'] = round(s17, 1)
                except:
                    pass

                # 18) 専門家脚質作戦完全一致ボーナス（厩舎×騎手×馬）
                t_name = entry.get('trainer_name', '')
                j_name = entry.get('jockey_name', '')
                t_tac = trainer_tactics.get_trainer_tactics(t_name) if 'trainer_tactics' in globals() else None
                j_tac = jockey_tactics.get_jockey_tactics(j_name) if 'jockey_tactics' in globals() else None

                if t_tac or j_tac:
                    s18_t = 0.0
                    s18_j = 0.0
                    if r_style in ['逃げ・番手', '先行']:
                        if t_tac:
                            t_front = t_tac.get('逃げ', 0) + t_tac.get('先行', 0)
                            s18_t = (t_front - 35.0) * 0.25  # 35%を基準平均とする
                        if j_tac:
                            j_front = j_tac.get('逃げ', 0) + j_tac.get('先行', 0)
                            s18_j = (j_front - 35.0) * 0.25
                    elif r_style in ['差し・追込', '中団']:
                        if t_tac:
                            t_back = t_tac.get('中団', 0) + t_tac.get('後方', 0) + t_tac.get('マクリ', 0)
                            s18_t = (t_back - 65.0) * 0.25  # 65%を基準平均とする
                        if j_tac:
                            j_back = j_tac.get('中団', 0) + j_tac.get('後方', 0) + j_tac.get('マクリ', 0)
                            s18_j = (j_back - 65.0) * 0.25

                    s18 = s18_t + s18_j
                    if abs(s18) > 0.1:
                        score += s18
                        breakdown['作戦一致'] = round(s18, 1)

                # ── 👑 [NEW] 影響率（ウェイト）の加算 ──
                if weights:
                    # 1) 調子P
                    form_score_val = float(entry.get('advanced_stats', {}).get('form_score', 0.0))
                    score += form_score_val * weights.get('調子P', 0.0)
                    
                    # 2) 単回収% (割合換算)
                    win_ret_val = float(vs.get('adj_win_return', 0))
                    score += (win_ret_val / 100.0) * weights.get('単回収%', 0.0)
                    
                    # 3) 人気 (1人気ほど加点)
                    pop = entry.get('popularity', 99)
                    if pop < 99:
                        score += (19.0 - float(pop)) * weights.get('人気', 0.0)
                        
                    # 4) オッズ (大穴加点、そのまま乗算)
                    odds = float(entry.get('odds', 0.0))
                    score += odds * weights.get('オッズ', 0.0)
                    
                    # 5) PW指数 (/10でベーススケール調整)
                    pw_idx_val = entry.get('pw_index')
                    if pw_idx_val is not None:
                        try:
                            score += (float(pw_idx_val) / 10.0) * weights.get('PW指数', 0.0)
                        except (TypeError, ValueError):
                            pass
                            
                    # 6) 単勝USM, 7) 連対USM, 8) 複勝USM (割合換算)
                    usm_data = entry.get('advanced_stats', {}).get('usm', {})
                    win_usm = usm_data.get('win_usm')
                    top2_usm = usm_data.get('top2_usm')
                    top3_usm = usm_data.get('top3_usm')
                    
                    if isinstance(win_usm, int):
                        score += (win_usm / 100.0) * weights.get('単勝USM', 0.0)
                    if isinstance(top2_usm, int):
                        score += (top2_usm / 100.0) * weights.get('連対USM', 0.0)
                    if isinstance(top3_usm, int):
                        score += (top3_usm / 100.0) * weights.get('複勝USM', 0.0)

                # ── 👑 [NEW] フラグボーナス (妙味・危険) ──
                # 妙味または危険フラグがつくと、総合スコアにユーザー設定のボーナスポイントを加算する
                _flg_list = entry.get('flags', [])
                _bonus_v = weights.get('フラグボーナス', 50.0) if weights else 50.0
                _flag_bonus = 0.0
                for _f in _flg_list:
                    if "妙味" in _f or "危険" in _f:
                        _flag_bonus += _bonus_v
                if _flag_bonus > 0:
                    score += _flag_bonus
                    breakdown['フラグボーナス'] = _flag_bonus

                return round(score, 1), breakdown

            # 各エントリのスコアを計算
            scored = []
            for _e in _jp_entries:
                _sc, _bd = _compute_full_score(_e, _jp_venue, weights=sw_jockey)
                _vs = _e.get('venue_stats') or {}
                _pr = _e.get('jockey_profile') or {}
                _ys = _pr.get('year_stats') or {}
                _flg = _e.get('flags', [])
                _madv = _e.get('matched_adv') or {}
                _adv_full = _e.get('advanced_stats') or {}
                _prb = _madv.get('prb_overall', 0.5)
                _hc = _madv.get('hot_cold', '—')
                _hc_icon = {'HOT': '🔥', 'COLD': '🧊'}.get(_hc, '')
                _rstyle = _madv.get('riding_style', '—')
                _usm = _adv_full.get('usm', {})
                _win_usm = _usm.get('win_usm', '-')
                _top2_usm = _usm.get('top2_usm', '-')
                _top3_usm = _usm.get('top3_usm', '-')

                # フラグ表示のアップデート (妙味/危険があれば+50.0ボーナス内訳を付記)
                _flag_bonus_val = _bd.get('フラグボーナス', 0.0)
                _flag_str = " ".join(_flg) if _flg else "—"
                if _flag_bonus_val > 0:
                    _flag_display = f"{_flag_str} (+{_flag_bonus_val:.1f})"
                else:
                    _flag_display = _flag_str

                # 加減点表示のアップデート (フラグボーナス内訳をわかりやすく付記)
                _bonuses = _e.get('bonuses') or {}
                _b_score = _bonuses.get('matched_bonus_score', 0.0)
                _p_score = _bonuses.get('matched_penalty_score', 0.0)
                
                _kagenten_str = '—'
                if _b_score != 0 or _p_score != 0:
                    _kagenten_str = f"+{_b_score:.1f} / {_p_score:.1f}"
                if _flag_bonus_val > 0:
                    if _kagenten_str == '—':
                        _kagenten_str = f"フラグ加点: +{_flag_bonus_val:.1f}"
                    else:
                        _kagenten_str += f" (フラグ: +{_flag_bonus_val:.1f})"

                scored.append({
                    '_umaban': _e.get('umaban', 0),
                    '_score': _sc,
                    '_breakdown': _bd,
                    '順位': 0,
                    '評価': '',
                    '馬番': _e.get('umaban', ''),
                    '馬名': _e.get('horse_name', ''),
                    '騎手': _e.get('jockey_name', ''),
                    '厩舎': _e.get('trainer_name', ''),
                    '人気': _e.get('popularity', 99) if _e.get('popularity', 99) < 99 else '—',
                    'オッズ': f"{_e.get('odds', 0):.1f}" if _e.get('odds', 0) > 0 else '—',
                    '調子P': f"{_adv_full.get('form_score', 0.0):.1f}",
                    'PRB': f"{_prb:.1f}",
                    '調子': f"{_hc_icon}{_hc}" if _hc != '—' else '—',
                    '脚質傾向': _rstyle,
                    '単勝USM': f"{float(_win_usm):.1f}%" if isinstance(_win_usm, int) else "-",
                    '連対USM': f"{float(_top2_usm):.1f}%" if isinstance(_top2_usm, int) else "-",
                    '複勝USM': f"{float(_top3_usm):.1f}%" if isinstance(_top3_usm, int) else "-",
                    'コース連対%': f"{_vs.get('adj_top2_rate', 0)*100:.1f}",
                    'コース複勝%': f"{_vs.get('top3_rate', 0)*100:.1f}",
                    '単回収%': f"{float(_vs.get('adj_win_return', 0)):.1f}",
                    '騎乗数': _vs.get('rides', 0),
                    '本年勝率': f"{_ys.get('win_rate', 0)*100:.1f}",
                    '本年連対%': f"{_ys.get('top2_rate', 0)*100:.1f}",
                    '本年複勝%': f"{_ys.get('top3_rate', 0)*100:.1f}",
                    'フラグ': _flag_display,
                    'PW指数': f"{float(_e['pw_index']):.1f}" if _e.get('pw_index') is not None else '—',
                    '加減点': _kagenten_str,
                    '総合スコア': _sc,  # Stylerや判定用にfloatのままとし、表示上のHTMLでのみ後から丸める
                    '_bonuses': _bonuses,
                    '_adv': _adv_full,
                    '_matched_adv': _madv,
                })

            scored.sort(key=lambda x: x['_score'], reverse=True)
            _eval_marks = ['◎', '◎', '◎', '○', '▲', '△', '×']
            for _i, _s in enumerate(scored):
                _s['順位'] = _i + 1
                _s['評価'] = _eval_marks[_i] if _i < len(_eval_marks) else '—'

            # ── サマリーメトリクス ──
            _iron_n   = sum(1 for s in scored if "🔴 鉄板" in s['フラグ'])
            _value_n  = sum(1 for s in scored if "🟡 妙味" in s['フラグ'])
            _danger_n = sum(1 for s in scored if "🔵 危険" in s['フラグ'])
            _top1 = scored[0] if scored else {}

            _mc1, _mc2, _mc3, _mc4 = st.columns(4)
            _mc1.metric("🥇 本命", f"{_top1.get('馬番', '?')}番 {_top1.get('騎手', '?')[:4]}", f"スコア {float(_top1.get('総合スコア', 0)):.1f}")
            _mc2.metric("🔴 鉄板フラグ", f"{_iron_n}騎手")
            _mc3.metric("🟡 妙味フラグ", f"{_value_n}騎手")
            _mc4.metric("🔵 危険フラグ", f"{_danger_n}騎手")

            st.divider()

            # ── ランキング表 ──
            st.subheader("📊 騎手ランキング（全指標スコア順）")

            _display_cols = ['順位', '評価', '馬番', '馬名', '騎手', '厩舎',
                             '人気', 'オッズ', '調子P', 'PRB', '調子', '脚質傾向',
                             '単勝USM', '連対USM', '複勝USM',
                             'コース連対%', 'コース複勝%', '単回収%',
                             '騎乗数', '本年勝率', '本年連対%', '本年複勝%', 'PW指数', '加減点', 'フラグ', '総合スコア']
            _df_rank = pd.DataFrame(scored)[_display_cols]

            def _to_numeric(val):
                if val is None:
                    return float('inf')
                s = str(val).strip()
                if s in ('—', '—', '-', 'None', 'nan', ''):
                    return float('inf')
                s = s.replace('%', '')
                try:
                    return float(s)
                except ValueError:
                    return float('inf')

            def _style_top3_per_col(df):
                style_df = pd.DataFrame('', index=df.index, columns=df.columns)
                col_ascending_map = {
                    '人気': True,
                    'オッズ': True,
                    '調子P': False,
                    'PRB': False,
                    '単勝USM': False,
                    '連対USM': False,
                    '複勝USM': False,
                    'コース連対%': False,
                    'コース複勝%': False,
                    '単回収%': False,
                    '騎乗数': False,
                    '本年勝率': False,
                    '本年連対%': False,
                    '本年複勝%': False,
                    'PW指数': False,
                    '総合スコア': False
                }
                for col, asc in col_ascending_map.items():
                    if col in df.columns:
                        nums = df[col].map(_to_numeric)
                        valid_nums = nums[nums != float('inf')]
                        if len(valid_nums) > 0:
                            ranks = valid_nums.rank(method='min', ascending=asc)
                            top3_idx = ranks[ranks <= 3].index
                            for idx in top3_idx:
                                style_df.at[idx, col] = 'border: 2px solid #FF1744; box-shadow: inset 0 0 0 2px #FF1744;'
                return style_df

            def _style_rank_row(row):
                rank = row['順位']
                flag = str(row['フラグ'])
                if rank == 1:
                    return ['background-color: #2a2200; color: #FBC02D; font-weight: bold; border-top: 1px solid #FBC02D; border-bottom: 1px solid #FBC02D;'] * len(row)
                if rank == 2:
                    return ['background-color: #2a1100; color: #F57C00; font-weight: bold; border-top: 1px solid #F57C00; border-bottom: 1px solid #F57C00;'] * len(row)
                if rank == 3:
                    return ['background-color: #001a00; color: #66BB6A; font-weight: bold; border-top: 1px solid #66BB6A; border-bottom: 1px solid #66BB6A;'] * len(row)
                if "🔵 危険" in flag:
                    return ['color: #7B9FFF;'] * len(row)
                return [''] * len(row)

            def _style_eval(val):
                if val == '◎': return 'color:#FF1744; font-weight:bold; font-size:1.3em;'
                if val == '○': return 'color:#FF9100; font-weight:bold;'
                if val == '▲': return 'color:#FFEA00; font-weight:bold;'
                return 'color:#888;'

            def _style_score(val):
                try:
                    v = float(str(val).replace('%', ''))
                    if v >= 120: return 'color:#FF5252; font-weight:bold;'
                    if v >= 90:  return 'color:#FFAB40;'
                    if v < 40:   return 'color:#666;'
                except: pass
                return ''

            # 列名を画面表示用にリネーム（旧 st.dataframe の column_config 設定に準拠）
            _df_rank_display = _df_rank.rename(columns={
                '脚質傾向': '脚質',
                'コース連対%': f'{_jp_venue}連対%',
                'コース複勝%': f'{_jp_venue}複勝%',
            })

            # スタイル適用（インデックス非表示化および小数点第1位フォーマットも Styler 側で実現）
            _styled = (_df_rank_display.style
                .hide(axis='index')
                .format(subset=['総合スコア'], formatter="{:.1f}")
                .apply(_style_rank_row, axis=1)
                .map(_style_eval, subset=['評価'])
                .map(_style_score, subset=['総合スコア'])
                .apply(_style_top3_per_col, axis=None)
            )

            # HTMLテーブル生成
            _styled.set_uuid("jpro_rank")
            _table_html = _styled.to_html(escape=False)

            # プレミアムダークテーマCSSおよびインタラクティブJavaScriptソーター
            _premium_table_html = f"""
            <div class="premium-table-container">
              <style>
                .premium-table-container {{
                    background: #0d0d1a;
                    border: 1px solid #2d1b4e;
                    border-radius: 12px;
                    padding: 16px;
                    margin-bottom: 24px;
                    box-shadow: 0 4px 25px rgba(0,0,0,0.6);
                    overflow-x: auto;
                }}
                .premium-table-container table {{
                    width: 100%;
                    border-collapse: separate;
                    border-spacing: 0;
                    color: #eee;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                    font-size: 0.85rem;
                }}
                .premium-table-container th {{
                    background: #121225;
                    color: #b388ff;
                    font-weight: bold;
                    text-align: center;
                    padding: 12px 10px;
                    border-bottom: 2px solid #2d1b4e;
                    cursor: pointer;
                    user-select: none;
                    white-space: nowrap;
                    position: relative;
                    transition: background 0.2s, color 0.2s;
                }}
                .premium-table-container th:hover {{
                    background: #1e1e3f;
                    color: #ffffff;
                }}
                .premium-table-container th::after {{
                    content: " ↕";
                    font-size: 0.75em;
                    color: #666;
                    margin-left: 4px;
                }}
                .premium-table-container th.sorted-asc::after {{
                    content: " ▲" !important;
                    color: #ffab40 !important;
                }}
                .premium-table-container th.sorted-desc::after {{
                    content: " ▼" !important;
                    color: #ffab40 !important;
                }}
                .premium-table-container td {{
                    padding: 10px 10px;
                    border-bottom: 1px solid #1a1a35;
                    text-align: center;
                    white-space: nowrap;
                    transition: background 0.15s;
                }}
                .premium-table-container tr:hover td {{
                    background: rgba(255, 255, 255, 0.05) !important;
                }}
              </style>
              
              {_table_html}
              
              <script>
                (function() {{
                    const table = document.querySelector('.premium-table-container table');
                    if (!table) return;
                    const headers = table.querySelectorAll('th');
                    const tbody = table.querySelector('tbody');
                    if (!tbody) return;
                    
                    headers.forEach((header, index) => {{
                        let asc = true;
                        header.addEventListener('click', () => {{
                            const rows = Array.from(tbody.querySelectorAll('tr'));
                            
                            rows.sort((rowA, rowB) => {{
                                const cellA = rowA.children[index].innerText.trim();
                                const cellB = rowB.children[index].innerText.trim();
                                
                                const clean = (val) => {{
                                    val = val.replace('%', '').replace('🔥', '').replace('🧊', '').trim();
                                    if (val === '—' || val === '-' || val === '' || val === 'None') {{
                                        return asc ? Infinity : -Infinity;
                                    }}
                                    const num = parseFloat(val);
                                    return isNaN(num) ? val : num;
                                }};
                                
                                const valA = clean(cellA);
                                const valB = clean(cellB);
                                
                                if (typeof valA === 'number' && typeof valB === 'number') {{
                                    return asc ? valA - valB : valB - valA;
                                }}
                                return asc ? String(valA).localeCompare(String(valB)) : String(valB).localeCompare(String(valA));
                            }});
                            
                            rows.forEach(row => tbody.appendChild(row));
                            asc = !asc;
                            
                            headers.forEach(h => h.classList.remove('sorted-asc', 'sorted-desc'));
                            header.classList.add(asc ? 'sorted-desc' : 'sorted-asc');
                        }});
                    }});
                }})();
              </script>
            </div>
            """

            st.html(_premium_table_html)

            # ── 📈 勝ち指数バー（HTML+CSSプレミアムグラデーションバー） ──
            st.divider()
            st.subheader("📈 勝ち指数バー（上位5頭）")
            _top5 = scored[:5]
            
            _gradients = [
                "linear-gradient(90deg, #FFE082, #FFB300)",  # 1位 金ゴールド
                "linear-gradient(90deg, #FFF59D, #FBC02D)",  # 2位 黄ゴールド
                "linear-gradient(90deg, #FFE082, #F57F17)",  # 3位 濃ゴールド
                "linear-gradient(90deg, #E0E0E0, #757575)",  # 4位 銀
                "linear-gradient(90deg, #FFCC80, #CA8A04)",  # 5位 銅
            ]
            
            _max_score = max([s['総合スコア'] for s in _top5]) if _top5 else 100
            
            _bars_html = ""
            for _idx, _s in enumerate(_top5):
                _pct = max(10, min(100, int((_s['総合スコア'] / _max_score) * 85)))
                _grad = _gradients[_idx] if _idx < len(_gradients) else "linear-gradient(90deg, #424242, #212121)"
                _eval = _s.get('評価', '—')
                _eval_color = '#FFD700' if _eval == '◎' else '#C0C0C0' if _eval == '○' else '#CD7F32' if _eval == '▲' else '#aaa'
                
                _bars_html += f"""
                <div style="margin-bottom: 14px;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px; font-size: 0.9em;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <span style="font-weight: bold; color: {_eval_color}; width: 20px; text-align: center; font-size: 1.1em;">{_eval}</span>
                      <span style="color: #fff; font-weight: bold; background: #222; padding: 2px 6px; border-radius: 4px; font-size: 0.85em;">{_s.get('馬番', '')}番</span>
                      <span style="color: #fff; font-weight: 500;">{_s.get('馬名', '')[:10]}</span>
                      <span style="color: #888; font-size: 0.85em;">({_s.get('騎手', '')[:4]})</span>
                    </div>
                    <span style="font-weight: bold; color: #FFF; font-size: 1.1em; font-family: monospace;">{_s['総合スコア']:.1f} pt</span>
                  </div>
                  <div style="background: #111; border: 1px solid #222; border-radius: 6px; height: 18px; width: 100%; overflow: hidden; display: flex; align-items: center; padding: 1px;">
                    <div style="background: {_grad}; width: {_pct}%; height: 100%; border-radius: 5px; 
                                transition: width 0.8s ease-in-out; 
                                box-shadow: 0 0 10px rgba(255,171,64,0.15);"></div>
                  </div>
                </div>
                """
            
            st.html(f"""
            <div style="background: #0d0d1a; border: 1px solid #2d1b4e; border-radius: 12px; padding: 18px; margin-bottom: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
              {_bars_html}
            </div>
            """)

            # ── 上位3頭の詳細カード ──
            st.divider()
            st.subheader("🃏 評価付き7頭 詳細カード")
            for _s in scored[:7]:
                _ent = next((e for e in _jp_entries if e.get('umaban') == _s['_umaban']), None)
                if not _ent: continue
                _vs2  = _ent.get('venue_stats') or {}
                _pr2  = _ent.get('jockey_profile') or {}
                _ys2  = _pr2.get('year_stats') or {}
                _t_name = _s.get('厩舎', '')
                _j_name = _s.get('騎手', '')
                _t_tac = trainer_tactics.get_trainer_tactics(_t_name) if 'trainer_tactics' in globals() else None
                _j_tac = jockey_tactics.get_jockey_tactics(_j_name) if 'jockey_tactics' in globals() else None
                _flg2 = _ent.get('flags', [])
                _rank_color_map = {
                    1: '#FFD700', 2: '#FFD700', 3: '#FFD700',  # ◎ 金
                    4: '#C0C0C0',                               # ○ 銀
                    5: '#CD7F32',                               # ▲ 銅
                    6: '#4A90D9',                               # △ 青
                    7: '#888888',                               # × グレー
                }
                _rank_color = _rank_color_map.get(_s['順位'], '#555555')
                _bd   = _s['_breakdown']
                _bd_html = "".join(
                    f'<span style="background:#1e1e2e;border:1px solid #444;padding:3px 8px;border-radius:8px;font-size:0.8em;margin:2px;display:inline-block;">'
                    f'{k}: <b style="color:#FFAB40;">{v:+.0f}</b></span>'
                    for k, v in _bd.items() if v != 0
                )
                _badge_html2 = "".join(
                    f'<span style="background:{"#8B0000" if "鉄板" in f else "#7B6000" if "妙味" in f else "#0D47A1"};'
                    f'color:white;padding:2px 8px;border-radius:10px;font-size:0.85em;margin-right:4px;">{f}</span>'
                    for f in _flg2
                ) or '<span style="color:#666;">フラグなし</span>'

                _pw2 = _ent.get('pw_index')
                _pw2_str = f"{float(_pw2):.1f}" if _pw2 is not None else '—'
                _pw2_color = '#6fcf97' if _pw2 is not None and _pw2 >= 100 else '#FFAB40' if _pw2 is not None and _pw2 >= 50 else '#fff'
                _bon2 = _s.get('_bonuses') or {}
                _add100 = _bon2.get('add_100', [])
                _add90  = _bon2.get('add_90', [])
                _sub70  = _bon2.get('sub_70', [])
                _sub60  = _bon2.get('sub_60', [])
                _bonus_score   = _bon2.get('bonus_score', 0.0)
                _penalty_score = _bon2.get('penalty_score', 0.0)
                _cadv = _s.get('_adv') or {}
                _cmadv = _s.get('_matched_adv') or {}
                _cprb = _cmadv.get('prb_overall', 0.5)
                _cprb_color = '#6fcf97' if _cprb >= 0.60 else '#FFAB40' if _cprb >= 0.50 else '#ef4444'
                _chc = _cmadv.get('hot_cold', '—')
                _chc_str = {'HOT': '🔥 HOT', 'COLD': '🧊 COLD'}.get(_chc, '— 平常')
                _chc_color = '#FF5252' if _chc == 'HOT' else '#64B5F6' if _chc == 'COLD' else '#888'
                _c_rstyle = _cmadv.get('riding_style', '—')

                _tactics_html = ""
                if _t_tac or _j_tac:
                    _tactics_html = f"""
                    <div style="font-size:0.75em;color:#888;margin:8px 0 2px 0;">🏠 生涯脚質・作戦傾向（専門家集計データ / 2016年〜2026年）</div>
                    <div style="background:#222;border:1px solid #333;border-radius:8px;padding:8px;margin:2px 0 8px 0;">
                      <table style="width:100%;font-size:0.85em;text-align:center;color:#eee;border-collapse:collapse;">
                        <tr style="border-bottom:1px solid #444;"><th style="color:#aaa;padding:4px;">対象</th><th>逃げ</th><th>先行</th><th>中団</th><th>後方</th><th>マクリ</th></tr>
                    """
                    if _t_tac:
                        _tactics_html += f"<tr><td style='color:#b388ff;font-weight:bold;padding:4px;border-bottom:1px solid #333;'>厩舎({_t_name[:4]})</td><td style='border-bottom:1px solid #333;'>{_t_tac.get('逃げ', 0)}%</td><td style='border-bottom:1px solid #333;'>{_t_tac.get('先行', 0)}%</td><td style='border-bottom:1px solid #333;'>{_t_tac.get('中団', 0)}%</td><td style='border-bottom:1px solid #333;'>{_t_tac.get('後方', 0)}%</td><td style='border-bottom:1px solid #333;'>{_t_tac.get('マクリ', 0)}%</td></tr>"
                    if _j_tac:
                        _tactics_html += f"<tr><td style='color:#b388ff;font-weight:bold;padding:4px;'>騎手({_j_name[:4]})</td><td>{_j_tac.get('逃げ', 0)}%</td><td>{_j_tac.get('先行', 0)}%</td><td>{_j_tac.get('中団', 0)}%</td><td>{_j_tac.get('後方', 0)}%</td><td>{_j_tac.get('マクリ', 0)}%</td></tr>"
                    
                    _tactics_html += """
                      </table>
                    </div>
                    """

                # Recent Form bars
                _rf = _cadv.get('recent_form', {})
                _rf_html = ""
                _prev_sample = -1
                for _rfd, _rfl in [('14d', '14日'), ('30d', '30日'), ('90d', '90日')]:
                    _rfv = _rf.get(_rfd)
                    if _rfv:
                        _sample_size = _rfv.get('sample', 0)
                        if _sample_size > 0 and _sample_size == _prev_sample:
                            continue
                        _prev_sample = _sample_size
                        
                        _rfp = _rfv.get('prb', 0.5)
                        _rfn = _sample_size
                        _rft3 = _rfv.get('top3_rate', 0)
                        _rfbar_w = int(min(_rfp * 100, 100))
                        _rfbar_c = '#6fcf97' if _rfp >= 0.60 else '#FFAB40' if _rfp >= 0.50 else '#ef4444'
                        _rf_html += (
                            f'<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">'
                            f'<span style="width:32px;font-size:0.7em;color:#aaa;">{_rfl}</span>'
                            f'<div style="flex:1;background:#222;border-radius:4px;height:14px;overflow:hidden;">'
                            f'<div style="width:{_rfbar_w}%;background:{_rfbar_c};height:100%;border-radius:4px;"></div>'
                            f'</div>'
                            f'<span style="font-size:0.75em;color:{_rfbar_c};width:60px;">{_rfp:.2f} ({_rfn}走)</span>'
                            f'<span style="font-size:0.7em;color:#888;">複{_rft3*100:.0f}%</span>'
                            f'</div>'
                        )

                # 順位に応じたバッジ色
                _badge_bg = "#FBC02D" if _s['順位'] == 1 else "#F57C00" if _s['順位'] == 2 else "#757575"
                _badge_color = "#000" if _s['順位'] == 1 else "#fff"

                st.html(f"""
                <div style="border: 1px solid #333; border-radius: 12px; padding: 16px; margin-bottom: 16px; background: #1c1c1c;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <div style="display: flex; align-items: center;">
                      <!-- 順位バッジ -->
                      <div style="width: 28px; height: 28px; border-radius: 6px; background: {_badge_bg}; color: {_badge_color}; font-weight: bold; font-size: 1.1em; display: flex; align-items: center; justify-content: center; margin-right: 12px;">
                        {_s['順位']}
                      </div>
                      <span style="font-size: 1.3em; font-weight: bold; color: #fff;">
                        {_s['馬番']}番 {_s['馬名']}
                      </span>
                      <span style="color: #aaa; margin-left: 12px; font-size: 0.9em;">
                        🏇 {_s['騎手']} ／ 🏠 {_s['厩舎']}
                      </span>
                    </div>
                    <div style="text-align: right;">
                      <div style="font-size: 1.6em; font-weight: bold; color: #fff;">{_s['総合スコア']:.1f} <span style="font-size: 0.6em; color: #888;">pt</span></div>
                    </div>
                  </div>
                  <div style="margin-bottom: 12px;">{_badge_html2}</div>
                  
                  <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 12px 0;">
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: #fff;">{_vs2.get('adj_top2_rate', 0)*100:.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">{_jp_venue}連対率</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: #fff;">{_vs2.get('top3_rate', 0)*100:.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">{_jp_venue}複勝率</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: {'#6fcf97' if _vs2.get('adj_win_return',0)>=100 else '#fff'};">{_vs2.get('adj_win_return', 0):.0f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">単回収率</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: #fff;">{_vs2.get('rides', 0)}</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">騎乗数</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: {_pw2_color};">{_pw2_str}</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">PW指数</div>
                    </div>
                  </div>
                  
                  <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 8px 0;">
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: {_cprb_color};">{_cprb:.2f}</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">PRB</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.1em; font-weight: bold; color: {_chc_color};">{_chc_str}</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">調子</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1em; font-weight: bold; color: #fff;">{_c_rstyle}</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">脚質傾向</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: #fff;">{_ys2.get('win_rate', 0)*100:.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">本年勝率</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: #fff;">{_ys2.get('top3_rate', 0)*100:.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">本年複勝率</div>
                    </div>
                  </div>
                  
                  <!-- 人間変数 -->
                  <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 8px 0 12px 0;">
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 8px;">
                      <div style="font-size: 1.2em; font-weight: bold; color: #ddd;">{_cadv.get('pos_skill', 50.0):.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 2px;">位置取り奪取力</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 8px;">
                      <div style="font-size: 1.2em; font-weight: bold; color: #ddd;">{_cadv.get('drive_power', 0.0):+.2f}頭/R</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 2px;">剛腕追い上げ数</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 8px;">
                      <div style="font-size: 1.2em; font-weight: bold; color: #ddd;">{_cadv.get('clutch_score', 50.0):.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 2px;">プレッシャー耐性</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 8px;">
                      <div style="font-size: 1.2em; font-weight: bold; color: #ddd;">{_cadv.get('gate_adapt', 50.0):.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 2px;">外枠克服力</div>
                    </div>
                  </div>
                  {_tactics_html}
                  <!-- Recent Form -->
                  <div style="background:#0a0a1a;border-radius:8px;padding:8px 12px;margin:8px 0;">
                    <div style="font-size:0.75em;color:#888;margin-bottom:4px;">📈 Recent Form (PRB推移)</div>
                    {_rf_html if _rf_html else '<span style="color:#666;font-size:0.8em;">データなし</span>'}
                  </div>
                  <div style="font-size:0.8em;color:#888;margin-top:6px;">📐 スコア内訳: {_bd_html}</div>
                </div>
                """)

                # ── ボーナス/減点内訳（Expander） ──
                _m_add100 = _bon2.get('matched_add_100', [])
                _m_add90  = _bon2.get('matched_add_90', [])
                _m_sub70  = _bon2.get('matched_sub_70', [])
                _m_sub60  = _bon2.get('matched_sub_60', [])
                _m_bonus  = _bon2.get('matched_bonus_score', 0.0)
                _m_penalty= _bon2.get('matched_penalty_score', 0.0)
                _has_bonus_data = _add100 or _add90 or _sub70 or _sub60
                _has_match = _m_add100 or _m_add90 or _m_sub70 or _m_sub60

                _bonus_label_parts = []
                if _m_bonus > 0:
                    _bonus_label_parts.append(f"✅ 加算 +{_m_bonus:.0f}pt")
                if _m_penalty < 0:
                    _bonus_label_parts.append(f"⚠️ 減点 {_m_penalty:.0f}pt")
                if not _has_match and _has_bonus_data:
                    _bonus_label_parts.append("今レースは条件不一致")
                _expander_label = (
                    f"📊 ボーナス/減点内訳 （{'・'.join(_bonus_label_parts) if _bonus_label_parts else 'データなし'}）"
                )
                with st.expander(_expander_label, expanded=False):
                    if not _has_bonus_data:
                        st.caption("db-keibaからボーナスデータを取得できませんでした。")
                    else:
                        # レースメタ情報を表示
                        _rm = _ent.get('race_meta') or {}
                        if _rm:
                            _rm_parts = []
                            if _rm.get('surface'): _rm_parts.append(_rm['surface'])
                            if _rm.get('distance'): _rm_parts.append(f"{_rm['distance']}m")
                            if _rm.get('condition'): _rm_parts.append(f"馬場:{_rm['condition']}")
                            if _rm.get('weather'): _rm_parts.append(f"天候:{_rm['weather']}")
                            if _rm.get('race_class'): _rm_parts.append(_rm['race_class'])
                            if _rm.get('waku'): _rm_parts.append(f"{_ent.get('waku',0)}枠")
                            if _ent.get('trainer_name'): _rm_parts.append(f"厩舎:{_ent['trainer_name']}")
                            if _ent.get('owner_name'): _rm_parts.append(f"馬主:{_ent['owner_name']}")
                            st.caption(f"🔍 照合条件: {' / '.join(_rm_parts)}")

                        _bcol1, _bcol2 = st.columns(2)
                        with _bcol1:
                            st.markdown("#### ✅ 加算条件")
                            if _add100:
                                st.markdown("🟢 **回収率100%以上** `+15pt/件`")
                                for _cond in _add100:
                                    _hit = _cond in _m_add100
                                    _prefix = "🎯 **" if _hit else "　"
                                    _suffix = "** ← 今レース発動！" if _hit else ""
                                    st.markdown(f"- {_prefix}{_cond}{_suffix}")
                            if _add90:
                                st.markdown("🟡 **回収率90%以上** `+8pt/件`")
                                for _cond in _add90:
                                    _hit = _cond in _m_add90
                                    _prefix = "🎯 **" if _hit else "　"
                                    _suffix = "** ← 今レース発動！" if _hit else ""
                                    st.markdown(f"- {_prefix}{_cond}{_suffix}")
                            if not _add100 and not _add90:
                                st.caption("加算条件なし")
                        with _bcol2:
                            st.markdown("#### ⚠️ 減点条件")
                            if _sub60:
                                st.markdown("🔴 **回収率60%未満** `-15pt/件`")
                                for _cond in _sub60:
                                    _hit = _cond in _m_sub60
                                    _prefix = "💥 **" if _hit else "　"
                                    _suffix = "** ← 今レース発動！" if _hit else ""
                                    st.markdown(f"- {_prefix}{_cond}{_suffix}")
                            if _sub70:
                                st.markdown("🟠 **回収率70%未満** `-8pt/件`")
                                for _cond in _sub70:
                                    _hit = _cond in _m_sub70
                                    _prefix = "💥 **" if _hit else "　"
                                    _suffix = "** ← 今レース発動！" if _hit else ""
                                    st.markdown(f"- {_prefix}{_cond}{_suffix}")
                            if not _sub60 and not _sub70:
                                st.caption("減点条件なし")

                # ── 条件別PRB内訳（Expander） ──
                _cadv_data = _s.get('_adv') or {}
                if _cadv_data.get('sample_size', 0) > 0:
                    with st.expander(f"📈 条件別PRB・複勝率 （直近{_cadv_data.get('sample_size',0)}走）", expanded=False):
                        def _render_prb_table(title, data_dict, highlight_key=None):
                            if not data_dict:
                                st.caption(f"{title}: データなし")
                                return
                            _rows = []
                            for _dk, _dv in data_dict.items():
                                _rows.append({
                                    '条件': ('→ ' + _dk if _dk == highlight_key else _dk),
                                    'PRB': f"{_dv['prb']:.2f}",
                                    '勝率': f"{_dv.get('win_rate',0)*100:.1f}%",
                                    '複勝率': f"{_dv.get('top3_rate',0)*100:.1f}%",
                                    'サンプル': _dv.get('sample', 0),
                                })
                            st.markdown(f"**{title}**")
                            st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True)

                        _rm2 = _ent.get('race_meta') or {}
                        _dist_hl = None
                        if _rm2.get('distance'):
                            _dist_hl = jockey_analyzer._classify_distance(_rm2['distance'])
                        _cond_hl = _rm2.get('condition', '')
                        _gate_hl = None
                        if _ent.get('umaban', 0) > 0:
                            _gate_hl = jockey_analyzer._classify_gate(_ent['umaban'])

                        _pcol1, _pcol2, _pcol3 = st.columns(3)
                        with _pcol1:
                            _render_prb_table("距離区分別", _cadv_data.get('by_distance', {}), _dist_hl)
                            _render_prb_table("馬場状態別", _cadv_data.get('by_condition', {}), _cond_hl)
                        with _pcol2:
                            _render_prb_table("枠順別", _cadv_data.get('by_gate', {}), _gate_hl)
                            _render_prb_table("レースクラス別", _cadv_data.get('by_class', {}))
                        with _pcol3:
                            _render_prb_table("オッズ帯別", _cadv_data.get('by_odds_band', {}))
                            _render_prb_table("斤量別", _cadv_data.get('by_weight', {}))

            # ── 買い目サジェスト ──
            st.divider()
            st.subheader("🎯 買い目サジェスト")
            _honmei = scored[0] if len(scored) > 0 else None
            _taikou = scored[1] if len(scored) > 1 else None
            _tanaka  = scored[2] if len(scored) > 2 else None
            _myomi_list = [s for s in scored if "🟡 妙味" in s['フラグ'] and s['順位'] > 3][:2]

            _buy_lines = []
            if _honmei and _taikou:
                _buy_lines.append(f"**単勝**: {_honmei['馬番']}番（{_honmei['騎手']}）")
                _buy_lines.append(f"**馬連**: {_honmei['馬番']}番 ー {_taikou['馬番']}番")
            if _honmei and _taikou and _tanaka:
                _buy_lines.append(f"**3連複**: {_honmei['馬番']}番 ー {_taikou['馬番']}番 ー {_tanaka['馬番']}番")
                _buy_lines.append(f"**3連単（軸1頭流し）**: {_honmei['馬番']}番 → {_taikou['馬番']}番, {_tanaka['馬番']}番 ...")
            if _myomi_list:
                _myomi_str = "・".join([f"{s['馬番']}番（{s['騎手']}）" for s in _myomi_list])
                _buy_lines.append(f"**妙味馬（ヒモ候補）**: {_myomi_str}")

            for _line in _buy_lines:
                st.markdown(f"- {_line}")

            # ── CSVダウンロード ──
            st.divider()
            _csv_bytes = _df_rank.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(
                "💾 ランキング結果をCSVダウンロード",
                data=_csv_bytes,
                file_name=f"jockey_ranking_{jp_race_id}.csv",
                mime="text/csv",
                key="jp_csv_download",
            )

        elif _jp_res and _jp_res.get('error'):
            st.warning(_jp_res['error'])
        elif not _jp_res:
            st.info("⬆️ レースIDを入力して「分析開始」ボタンを押してください。")


    # =============================================
    # タブ4: 設定・データ管理
    # =============================================
    with jpro_tab4:
        st.subheader("⚙️ 設定")

        st.markdown("##### フラグ閾値設定")
        col1, col2 = st.columns(2)
        with col1:
            st.number_input("🔴鉄板：連対率閾値（%）", 10, 80, 40, key="jpro_iron_threshold")
            st.number_input("🔴鉄板：最低騎乗回数", 5, 100, 30, key="jpro_iron_min_rides")
        with col2:
            st.number_input("🟡妙味：単回収閾値（%）", 80, 300, 120, key="jpro_value_threshold")
            st.number_input("🟡妙味：最低騎乗回数", 5, 100, 15, key="jpro_value_min_rides")

        st.number_input("🔵危険：連対率上限（%）", 5, 30, 15, key="jpro_danger_threshold")

        st.markdown("---")

        st.markdown("##### ベイズ補正設定")
        st.number_input(
            "事前分布の強さ（擬似サンプル数）", 5, 100, 20,
            key="jpro_prior_strength",
            help="数値が大きいほど、少数サンプルのデータが全体平均に強く引き寄せられる"
        )

        st.markdown("---")

        st.markdown("##### データ管理")

        # DB状態表示
        try:
            if _jpro_db.table_exists():
                rec_count = _jpro_db.get_record_count()
                st.success(f"✅ jockey_statsテーブル: {rec_count}件のレコード")
            else:
                st.warning("⚠️ jockey_statsテーブルが存在しません。下のボタンで初期化してください。")
        except Exception:
            st.warning("⚠️ DB接続エラー。下のボタンで初期化してください。")

        if st.button("🗄️ DBテーブル初期化（jockey_stats）", key="jpro_init_db"):
            try:
                _jpro_db.init_table()
                st.success("✅ jockey_statsテーブルを初期化しました。")
            except Exception as e:
                st.error(f"❌ 初期化エラー: {e}")

        st.markdown("---")

        st.markdown("##### CSVインポート")
        st.caption("""
        **必須カラム**: jockey_id, jockey_name, target_type, target_id, target_name, ride_count, win_count, top2_count, win_rate, top2_rate, return_win
        
        **target_type**: `course` / `trainer` / `horse` のいずれか
        
        **オプション**: top3_count, top3_rate, return_place, running_style, track_condition
        """)

        uploaded = st.file_uploader(
            "騎手成績CSVをアップロード",
            type=["csv"],
            key="jpro_csv_upload",
        )
        if uploaded:
            try:
                df_csv = pd.read_csv(uploaded, encoding="utf-8")
            except UnicodeDecodeError:
                df_csv = pd.read_csv(uploaded, encoding="utf-8-sig")

            st.dataframe(df_csv.head(10), use_container_width=True)
            st.caption(f"プレビュー: {len(df_csv)}件、カラム: {list(df_csv.columns)}")

            if st.button("📥 インポート実行", key="jpro_csv_import", type="primary"):
                try:
                    # テーブルが無ければ先に初期化
                    if not _jpro_db.table_exists():
                        _jpro_db.init_table()

                    count = _jpro_db.import_csv(df_csv)
                    st.success(f"✅ {count}件をインポートしました。")
                except Exception as e:
                    st.error(f"❌ インポートエラー: {e}")
                    import traceback
                    st.code(traceback.format_exc())

        st.markdown("---")

        # =============================================
        # netkeibaデータ自動取得
        # =============================================
        st.markdown("##### 📥 netkeibaデータ自動取得")
        st.caption("騎手IDを入力すると、コース別/厩舎別/馬別の成績をnetkeibaから取得しDBに保存します。")

        _fetch_col1, _fetch_col2 = st.columns([3, 1])
        with _fetch_col1:
            _fetch_jid = st.text_input(
                "騎手ID（netkeiba 5桁）",
                placeholder="例: 05212 (ルメール)",
                key="jpro_fetch_jockey_id",
            )
        with _fetch_col2:
            st.write("")
            _fetch_single_btn = st.button("📥 単独取得", key="jpro_fetch_single", use_container_width=True)

        if _fetch_single_btn and _fetch_jid.strip():
            from utils.jockey_scraper import JockeyScraper
            _scraper = JockeyScraper()
            with st.spinner(f"騎手ID {_fetch_jid.strip()} のデータを取得中..."):
                try:
                    stats = _scraper.fetch_all_stats(_fetch_jid.strip())
                    total_fetched = 0
                    if not _jpro_db.table_exists():
                        _jpro_db.init_table()
                    for target_type, df in stats.items():
                        if not df.empty:
                            records = df.to_dict("records")
                            count = _jpro_db.upsert(records)
                            total_fetched += count
                            st.caption(f"  {target_type}: {count}件")
                    if total_fetched > 0:
                        st.success(f"✅ 合計{total_fetched}件のデータを取得・保存しました。")
                    else:
                        st.warning("データを取得できませんでした。騎手IDを確認してください。")
                except Exception as e:
                    st.error(f"取得エラー: {e}")

        # バッチ取得（リーディング上位）
        with st.expander("🔄 一括取得（リーディング上位）"):
            _batch_top_n = st.slider("上位N名", 5, 30, 10, key="jpro_batch_top_n")
            if st.button(f"🔄 上位{_batch_top_n}名を一括取得", key="jpro_batch_fetch"):
                from utils.jockey_scraper import JockeyScraper, TOP_JOCKEYS
                _scraper = JockeyScraper()
                jockey_ids = list(TOP_JOCKEYS.keys())[:_batch_top_n]
                progress_bar = st.progress(0)
                status_text = st.empty()
                total_batch = 0
                if not _jpro_db.table_exists():
                    _jpro_db.init_table()
                for idx, jid in enumerate(jockey_ids):
                    jname = TOP_JOCKEYS.get(jid, jid)
                    progress_bar.progress((idx + 1) / len(jockey_ids))
                    status_text.caption(f"取得中: {jname} ({jid}) [{idx+1}/{len(jockey_ids)}]")
                    try:
                        stats = _scraper.fetch_all_stats(jid)
                        for ttype, df in stats.items():
                            if not df.empty:
                                total_batch += _jpro_db.upsert(df.to_dict("records"))
                    except Exception:
                        pass
                progress_bar.empty()
                status_text.empty()
                st.success(f"✅ {_batch_top_n}名から合計{total_batch}件を取得・保存しました。")

        st.markdown("---")

        # =============================================
        # LightGBMウェイト算出
        # =============================================
        st.markdown("##### 🤖 機械学習ウェイト算出（LightGBM）")
        st.caption("DB内の騎手成績データから、各相性数値が回収率にどれだけ影響するかを客観的に算出します。")

        _ml_col1, _ml_col2 = st.columns([2, 1])
        with _ml_col1:
            _ml_target = st.selectbox(
                "目的変数",
                ["回収率（return_win）", "着順（finish_position）"],
                key="jpro_ml_target",
            )
        with _ml_col2:
            st.write("")
            _ml_train_btn = st.button("🤖 ウェイト算出", key="jpro_ml_train_btn", use_container_width=True)

        if _ml_train_btn:
            try:
                from utils.jockey_ml import train_weights
                target = "return_win" if "回収率" in _ml_target else "finish_position"
                with st.spinner("学習中（数秒〜数十秒）..."):
                    weights = train_weights(target=target, db_path=_jpro_db.db_path)
                if weights:
                    st.success("✅ ウェイト算出完了！")
                    df_w = pd.DataFrame([
                        {"特徴量": k, "重要度": v} for k, v in weights.items()
                    ])
                    st.bar_chart(df_w.set_index("特徴量"))
            except Exception as e:
                st.error(f"ウェイト算出エラー: {e}")
                import traceback
                st.code(traceback.format_exc())

        # 現在のウェイト表示
        with st.expander("📊 現在のウェイト"):
            try:
                from utils.jockey_ml import get_weights
                current_weights = get_weights(db_path=_jpro_db.db_path)
                for feat, w in current_weights.items():
                    bar_len = int(w * 200)
                    st.markdown(
                        f"**{feat}**: `{w:.4f}` "
                        f"{'█' * bar_len}{'░' * max(0, 20 - bar_len)}"
                    )
            except Exception as e:
                st.info(f"ウェイト未算出: {e}")

        st.markdown("---")

        # =============================================
        # 外部指数インポート（PW指数等）
        # =============================================
        st.markdown("##### 🔢 外部指数インポート（PW指数等）")
        st.caption("PakkaWinのPW指数やタイム指数などのCSVデータをインポートし、出馬表ビューに統合表示します。")

        pw_uploaded = st.file_uploader(
            "PW指数データCSV",
            type=["csv"],
            key="jpro_pw_upload",
            help="必須カラム: horse_id, horse_name, pw_index / オプション: race_id",
        )
        if pw_uploaded:
            try:
                df_pw = pd.read_csv(pw_uploaded, encoding="utf-8")
            except UnicodeDecodeError:
                df_pw = pd.read_csv(pw_uploaded, encoding="utf-8-sig")

            st.dataframe(df_pw.head(10), use_container_width=True)
            st.caption(f"プレビュー: {len(df_pw)}件、カラム: {list(df_pw.columns)}")

            if st.button("📥 PW指数インポート", key="jpro_pw_import", type="primary"):
                try:
                    import sqlite3
                    conn = sqlite3.connect(_jpro_db.db_path)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS external_index (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            race_id TEXT NOT NULL DEFAULT '',
                            horse_id TEXT NOT NULL,
                            horse_name TEXT NOT NULL,
                            index_name TEXT NOT NULL,
                            index_value REAL NOT NULL,
                            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                            UNIQUE(race_id, horse_id, index_name)
                        )
                    """)
                    pw_count = 0
                    for _, row in df_pw.iterrows():
                        conn.execute(
                            """INSERT OR REPLACE INTO external_index
                               (race_id, horse_id, horse_name, index_name, index_value)
                               VALUES (?, ?, ?, 'PW', ?)""",
                            (
                                str(row.get("race_id", "")),
                                str(row.get("horse_id", "")),
                                str(row.get("horse_name", "")),
                                float(row.get("pw_index", 0.0)),
                            ),
                        )
                        pw_count += 1
                    conn.commit()
                    conn.close()
                    st.success(f"✅ PW指数 {pw_count}件をインポートしました。")
                except Exception as e:
                    st.error(f"❌ PW指数インポートエラー: {e}")
                    import traceback
                    st.code(traceback.format_exc())

        st.markdown("---")

        # =============================================
        # レース一括ボーナス条件作成モード
        # =============================================
        st.markdown("##### 🏇 レース一括ボーナス条件作成モード")
        st.caption("レースIDを入力するだけで出走騎手のCSVテンプレートとdb-keibaリンクを一括生成します。")

        _bulk_race_id = st.text_input(
            "netkeibaレースIDを入力",
            placeholder="例: 202504050811",
            key="bonus_bulk_race_id",
        )
        if st.button("🔍 騎手一覧を抽出してテンプレート生成", key="bonus_bulk_btn", type="primary"):
            if not _bulk_race_id.strip():
                st.warning("レースIDを入力してください。")
            else:
                with st.spinner("出走騎手を取得中..."):
                    try:
                        _bulk_entries = jockey_analyzer.extract_jockey_ids_from_race(_bulk_race_id.strip())
                    except Exception as _bulk_e:
                        _bulk_entries = []
                        st.error(f"取得失敗: {_bulk_e}")

                if _bulk_entries:
                    st.success(f"{len(_bulk_entries)}人の騎手を抽出しました。")

                    # db-keibaスラッグ変換（ローマ字）— 既知の主要騎手マッピング
                    _SLUG_MAP = {
                        '川田将雅': 'kawada', '福永祐一': 'fukunaga', '武豊': 'take',
                        'ルメール': 'lemaire', 'デムーロ': 'demuro', '横山典弘': 'yokoyama-n',
                        '横山武史': 'yokoyama-t', '松山弘平': 'matsuyama', '岩田康誠': 'iwata-k',
                        '岩田望来': 'iwata-m', '戸崎圭太': 'tosaki', '浜中俊': 'hamanaka',
                        '池添謙一': 'ikezoe', '和田竜二': 'wada', '藤岡佑介': 'fujioka-y',
                        '藤岡康太': 'fujioka-k', '幸英明': 'miyuki', '丸山元気': 'maruyama',
                        '三浦皇成': 'miura', '田辺裕信': 'tanabe', '内田博幸': 'uchida',
                        '北村友一': 'kitamura-t', '北村宏司': 'kitamura-h', '石橋脩': 'ishibashi',
                        '坂井瑠星': 'sakai', '津村明秀': 'tsumura', '鮫島克駿': 'samejima',
                        '鮫島良太': 'samejima-r', '永野猛蔵': 'nagano', '西村淳也': 'nishimura',
                        '菅原明良': 'sugawara', '団野大成': 'danno', '古川吉洋': 'furukawa',
                        '角田大河': 'tsunoda', '角田大和': 'tsunoda-y', '小沢大仁': 'ozawa',
                        'モレイラ': 'moreira', 'ムーア': 'moore', 'ビュイック': 'buick',
                    }

                    # 表示用DataFrame
                    _bulk_rows = []
                    for _be in _bulk_entries:
                        _jname = _be.get('jockey_name', '')
                        _jid   = _be.get('jockey_id', '')
                        _slug  = _SLUG_MAP.get(_jname, '')
                        _dburl = f"https://db-keiba.com/jockey-{_slug}/" if _slug else '（スラッグ不明）'
                        _bulk_rows.append({
                            '馬番':    _be.get('umaban', ''),
                            '馬名':    _be.get('horse_name', ''),
                            '騎手名':  _jname,
                            '騎手ID':  _jid,
                            'db-keiba傾向URL': _dburl,
                        })
                    _bulk_df = pd.DataFrame(_bulk_rows)

                    # テーブル表示（URLはリンクとして）
                    st.dataframe(
                        _bulk_df,
                        column_config={
                            '馬番':  st.column_config.NumberColumn(width='small'),
                            '馬名':  st.column_config.TextColumn(width='medium'),
                            '騎手名': st.column_config.TextColumn(width='medium'),
                            '騎手ID': st.column_config.TextColumn(width='small'),
                            'db-keiba傾向URL': st.column_config.LinkColumn(
                                "db-keiba傾向ページ",
                                display_text="傾向を見る",
                                width='medium',
                            ),
                        },
                        hide_index=True,
                        use_container_width=True,
                    )

                    # CSVテンプレート自動生成（既知騎手は傾向DBから条件を自動埋め込み）
                    JOCKEY_TENDENCY_DB = jockey_analyzer.JOCKEY_TENDENCY_DB
                    _tmpl_rows = []
                    _known_count = 0
                    _unknown_count = 0
                    for _be in _bulk_entries:
                        _jid = _be.get('jockey_id', '')
                        if not _jid:
                            continue
                        _jname = _be.get('jockey_name', '')
                        _tendency = JOCKEY_TENDENCY_DB.get(_jid)
                        if _tendency:
                            _known_count += 1
                            # 既知騎手: 傾向DBから条件を自動埋め込み
                            for _typ in ['add_100', 'add_90', 'sub_70', 'sub_60']:
                                for _cond in _tendency.get(_typ, []):
                                    _tmpl_rows.append({
                                        'jockey_id': _jid,
                                        'jockey_name': _jname,
                                        'type': _typ,
                                        'condition': _cond,
                                    })
                            # 余白行（追記用）
                            for _typ in ['add_100', 'add_90', 'sub_70', 'sub_60']:
                                _tmpl_rows.append({
                                    'jockey_id': _jid,
                                    'jockey_name': _jname,
                                    'type': _typ,
                                    'condition': '',
                                })
                        else:
                            _unknown_count += 1
                            # 未知騎手: 空欄×2行
                            for _typ in ['add_100', 'add_90', 'sub_70', 'sub_60']:
                                for _ in range(2):
                                    _tmpl_rows.append({
                                        'jockey_id': _jid,
                                        'jockey_name': _jname,
                                        'type': _typ,
                                        'condition': '',
                                    })
                    _tmpl_df = pd.DataFrame(_tmpl_rows)
                    _tmpl_csv = _tmpl_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')

                    if _known_count > 0:
                        st.info(f"✅ {_known_count}人は傾向DBから条件を自動入力済みです。"
                                f"{'（残り' + str(_unknown_count) + '人は手動入力が必要）' if _unknown_count > 0 else ''}")
                    st.download_button(
                        "📥 CSVテンプレートをダウンロード（既知騎手は条件自動入力済み）",
                        data=_tmpl_csv,
                        file_name=f"bonus_{_bulk_race_id.strip()}.csv",
                        mime="text/csv",
                        key="bonus_bulk_dl",
                        type="primary",
                    )
                    st.caption(
                        "既知騎手（約20名）の条件はDB自動入力済みです。"
                        "未知騎手の `condition` 欄はdb-keibaの傾向ページを参照しながら入力してください。"
                        "入力後、下の「ボーナス条件CSVインポート」からアップロードしてください。"
                    )
                elif _bulk_entries is not None:
                    st.warning("出走騎手を取得できませんでした。レースIDを確認してください。")

        st.markdown("---")

        # =============================================
        # 騎手ボーナス条件 統合エディタ
        # （登録・修正・削除・新規追加をひとつの表で管理）
        # =============================================
        import json as _json_tendency

        # グリーン基調のヘッダー
        st.markdown("""
<div style="background:linear-gradient(90deg,#1a6e3c,#27ae60);
            padding:12px 18px;border-radius:8px;margin-bottom:12px;">
  <span style="color:#fff;font-size:1.1rem;font-weight:700;">
    🟢 騎手ボーナス条件エディタ
  </span>
  <span style="color:#d4f5e2;font-size:0.85rem;margin-left:12px;">
    登録・追加・修正・削除をこの表で一括管理
  </span>
</div>
""", unsafe_allow_html=True)

        # 保存先CSVパス
        _BONUS_CSV_PATH = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "bonus_conditions.csv"
        )

        # ---- キャッシュ → DataFrame に展開 ----
        _UE_CACHE = jockey_analyzer._DBKEIBA_BONUS_CACHE
        _ue_rows = []
        for _uejid, _uebd in _UE_CACHE.items():
            _uename = _uebd.get('name', _uejid)
            for _uetyp in ['add_100', 'add_90', 'sub_70', 'sub_60']:
                for _uecond in _uebd.get(_uetyp, []):
                    _ue_rows.append({
                        'jockey_id':   _uejid,
                        'jockey_name': _uename,
                        'type':        _uetyp,
                        'condition':   _uecond,
                    })
        _ue_df = pd.DataFrame(_ue_rows) if _ue_rows else pd.DataFrame(
            columns=['jockey_id','jockey_name','type','condition'])

        # ---- 統計サマリをグリーンカードで表示 ----
        _ue_jcount = _ue_df['jockey_id'].nunique() if len(_ue_df) else 0
        _ue_rcount = len(_ue_df)
        _ua1, _ua2, _ua3, _ua4 = st.columns(4)
        _ua1.markdown(f"""<div style="background:#e8f8ee;border-left:4px solid #27ae60;
            padding:8px 12px;border-radius:6px;text-align:center;">
            <div style="color:#1a6e3c;font-size:1.4rem;font-weight:700;">{_ue_jcount}</div>
            <div style="color:#2e7d52;font-size:0.8rem;">登録騎手数</div></div>""",
            unsafe_allow_html=True)
        _ua2.markdown(f"""<div style="background:#e8f8ee;border-left:4px solid #27ae60;
            padding:8px 12px;border-radius:6px;text-align:center;">
            <div style="color:#1a6e3c;font-size:1.4rem;font-weight:700;">{_ue_rcount}</div>
            <div style="color:#2e7d52;font-size:0.8rem;">条件総数</div></div>""",
            unsafe_allow_html=True)
        _ue_add = len(_ue_df[_ue_df['type'].isin(['add_100','add_90'])]) if len(_ue_df) else 0
        _ua3.markdown(f"""<div style="background:#e8f8ee;border-left:4px solid #2ecc71;
            padding:8px 12px;border-radius:6px;text-align:center;">
            <div style="color:#1a6e3c;font-size:1.4rem;font-weight:700;">+{_ue_add}</div>
            <div style="color:#2e7d52;font-size:0.8rem;">加算条件</div></div>""",
            unsafe_allow_html=True)
        _ue_sub = len(_ue_df[_ue_df['type'].isin(['sub_70','sub_60'])]) if len(_ue_df) else 0
        _ua4.markdown(f"""<div style="background:#fdf0f0;border-left:4px solid #e74c3c;
            padding:8px 12px;border-radius:6px;text-align:center;">
            <div style="color:#922b21;font-size:1.4rem;font-weight:700;">-{_ue_sub}</div>
            <div style="color:#922b21;font-size:0.8rem;">減点条件</div></div>""",
            unsafe_allow_html=True)

        st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)
        st.markdown("""<div style="background:#f0faf4;border:1px solid #a8dbb8;
            border-radius:6px;padding:8px 14px;font-size:0.85rem;color:#1a5e34;">
            💡 <b>使い方</b>：セルをクリックして直接編集 ／ 下の「＋」ボタンで行追加（新騎手登録も可）
            ／ 行選択→ Delete で削除 ／ 編集後は <b>💾 保存</b> ボタンを押してください
        </div>""", unsafe_allow_html=True)
        st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

        # ---- data_editor ----
        _ue_edited = st.data_editor(
            _ue_df,
            column_config={
                'jockey_id': st.column_config.TextColumn(
                    '騎手ID', width='small',
                    help='netkeibaの5桁ID（例: 01167）',
                ),
                'jockey_name': st.column_config.TextColumn(
                    '騎手名', width='small',
                ),
                'type': st.column_config.SelectboxColumn(
                    'タイプ', width='medium',
                    options=['add_100','add_90','sub_70','sub_60'],
                    help='add_100=+15pt / add_90=+8pt / sub_70=-8pt / sub_60=-15pt',
                ),
                'condition': st.column_config.TextColumn(
                    '条件', width='large',
                    help='例: 芝逃げ / 東京芝コース / 前走逃げ馬 など',
                ),
            },
            num_rows='dynamic',
            use_container_width=True,
            hide_index=True,
            key="unified_bonus_editor",
        )

        # ---- ボタン行 ----
        _ubtn1, _ubtn2, _ubtn3 = st.columns([2, 2, 3])
        with _ubtn1:
            _ue_save = st.button(
                "💾 保存して反映",
                type="primary",
                key="unified_bonus_save",
                use_container_width=True,
            )
        with _ubtn2:
            _ue_dl_csv = _ue_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(
                "⬇️ CSVダウンロード",
                data=_ue_dl_csv,
                file_name="bonus_conditions_export.csv",
                mime="text/csv",
                key="unified_bonus_dl",
                use_container_width=True,
            )
        with _ubtn3:
            st.markdown(
                "<span style='color:#888;font-size:0.8rem;line-height:2.4rem;'>"
                "※ 保存するとキャッシュとCSVファイルに即時反映されます</span>",
                unsafe_allow_html=True,
            )

        if _ue_save:
            _ue_new_cache = {}
            for _, _uer in _ue_edited.iterrows():
                _ueid   = str(_uer.get('jockey_id','')).strip().zfill(5)
                _uetyp2 = str(_uer.get('type','')).strip()
                _uecnd  = str(_uer.get('condition','')).strip()
                _uenm   = str(_uer.get('jockey_name','')).strip()
                if not _ueid or not _uetyp2 or not _uecnd or _uecnd in ('nan',''):
                    continue
                if _ueid not in _ue_new_cache:
                    _ue_new_cache[_ueid] = {
                        'name': _uenm,
                        'add_100':[], 'add_90':[], 'sub_70':[], 'sub_60':[],
                    }
                if _uetyp2 in ('add_100','add_90','sub_70','sub_60'):
                    _ue_new_cache[_ueid][_uetyp2].append(_uecnd)

            # キャッシュ更新
            _UE_CACHE.clear()
            _UE_CACHE.update(_ue_new_cache)

            # CSV永続保存
            _ue_save_rows = []
            for _us_id, _us_bd in _ue_new_cache.items():
                for _us_typ in ['add_100','add_90','sub_70','sub_60']:
                    for _us_cnd in _us_bd.get(_us_typ,[]):
                        _ue_save_rows.append({
                            'jockey_id':   _us_id,
                            'jockey_name': _us_bd.get('name', _us_id),
                            'type':        _us_typ,
                            'condition':   _us_cnd,
                        })
            pd.DataFrame(_ue_save_rows).to_csv(
                _BONUS_CSV_PATH, index=False, encoding='utf-8-sig'
            )

            _ue_jc2 = len(_ue_new_cache)
            _ue_rc2 = len(_ue_save_rows)
            st.markdown(f"""<div style="background:#e8f8ee;border-left:4px solid #27ae60;
                border-radius:6px;padding:10px 16px;margin-top:8px;">
                ✅ <b>{_ue_jc2}騎手 / {_ue_rc2}件</b> を保存しました。次回分析から反映されます。
            </div>""", unsafe_allow_html=True)
            st.rerun()

        st.markdown("---")

        # =============================================
        # ボーナス/減点条件CSVインポート
        # =============================================
        st.markdown("##### 🎯 ボーナス/減点条件CSVインポート")

        st.markdown("**📖 使い方**")
        st.markdown("""
1. **db-keiba.com** で騎手ページを開く（例: `https://db-keiba.com/jockey-kawada/`）
2. 「条件別成績・回収率まとめ」を参照し、回収率の高い／低い条件を確認
3. 下の **CSVテンプレート** をダウンロードしてExcelやメモ帳で条件を入力して保存
4. 保存したCSVをアップロード → 「インポート」ボタンを押す
5. 次回の騎手ランキング分析時にスコアへ自動反映。詳細カードの「📊 ボーナス/減点内訳」で発動状況を確認
""")
        st.markdown("**typeの種類（condition 1件あたりの加減点）:**")
        _tc1, _tc2, _tc3, _tc4 = st.columns(4)
        _tc1.success("add_100: 回収率100%以上 +15pt")
        _tc2.warning("add_90 : 回収率90%以上  +8pt")
        _tc3.warning("sub_70 : 回収率70%未満  -8pt")
        _tc4.error("sub_60 : 回収率60%未満  -15pt")
        st.markdown(
            "**騎手ID確認:** netkeibaの騎手URLの5桁数字 "
            "（例: `db.netkeiba.com/jockey/01167/` → `01167`）  \n"
            "**condition例:** 芝 / ダート / 東京 / 阪神 / 中山 / 京都 / 良 / 重 / 稍重 / "
            "マイル / 短距離 / 中距離 / 長距離 / 1600m / G1 / オープン / 新馬 / 厩舎名 / 馬主名 など"
        )

        # CSVテンプレートダウンロード
        _bonus_template = (
            "jockey_id,type,condition\n"
            "01167,add_100,芝\n"
            "01167,add_100,阪神\n"
            "01167,add_90,マイル\n"
            "01167,sub_70,ダート\n"
            "01167,sub_60,新馬\n"
        )
        st.download_button(
            "📄 CSVテンプレートをダウンロード",
            data=_bonus_template.encode('utf-8-sig'),
            file_name="bonus_conditions_template.csv",
            mime="text/csv",
            key="bonus_template_dl",
            help="このテンプレートに騎手IDと条件を入力して保存し、下からアップロードしてください",
        )

        _bonus_csv_uploaded = st.file_uploader(
            "ボーナス条件CSV",
            type=["csv"],
            key="bonus_csv_upload",
            help="必須カラム: jockey_id, type, condition",
        )
        if _bonus_csv_uploaded:
            try:
                try:
                    _df_bonus = pd.read_csv(_bonus_csv_uploaded, dtype=str, encoding='utf-8-sig').fillna('')
                except UnicodeDecodeError:
                    _bonus_csv_uploaded.seek(0)
                    _df_bonus = pd.read_csv(_bonus_csv_uploaded, dtype=str, encoding='cp932').fillna('')
                _df_bonus.columns = [c.strip() for c in _df_bonus.columns]
                st.dataframe(_df_bonus.head(15), use_container_width=True, hide_index=True)
                st.caption(f"プレビュー: {len(_df_bonus)}件 / カラム: {list(_df_bonus.columns)}")

                if st.button("📥 ボーナス条件をインポート", key="bonus_csv_import", type="primary"):
                    # CSVを一時ファイルに保存してload_bonus_csvで読み込む
                    _bonus_csv_path = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), "data", "bonus_conditions.csv"
                    )
                    os.makedirs(os.path.dirname(_bonus_csv_path), exist_ok=True)
                    _bonus_csv_uploaded.seek(0)
                    with open(_bonus_csv_path, 'wb') as _f:
                        _f.write(_bonus_csv_uploaded.read())

                    # キャッシュをリセットしてから再読み込み
                    jockey_analyzer._DBKEIBA_BONUS_CACHE.clear()
                    jockey_analyzer.load_bonus_csv(_bonus_csv_path)

                    _loaded_ids = len(jockey_analyzer._DBKEIBA_BONUS_CACHE)
                    _loaded_rows = sum(
                        len(v['add_100']) + len(v['add_90']) + len(v['sub_70']) + len(v['sub_60'])
                        for v in jockey_analyzer._DBKEIBA_BONUS_CACHE.values()
                    )
                    st.success(f"✅ {_loaded_ids}騎手 / {_loaded_rows}件のボーナス条件をインポートしました。")
                    st.caption("次回の分析実行時から自動的にスコアへ反映されます。")

            except Exception as _be:
                st.error(f"❌ ボーナスCSVエラー: {_be}")


        # 起動時: 傾向DBを自動ロード → 保存済みCSVがあれば上書き
        try:
            _DBKEIBA_BONUS_CACHE = jockey_analyzer._DBKEIBA_BONUS_CACHE
            JOCKEY_TENDENCY_DB = jockey_analyzer.JOCKEY_TENDENCY_DB
            get_tendency_as_bonus_dict = jockey_analyzer.get_tendency_as_bonus_dict
            load_bonus_csv = jockey_analyzer.load_bonus_csv
            # Step1: JOCKEY_TENDENCY_DBから既知騎手を自動ロード
            if not _DBKEIBA_BONUS_CACHE:
                for _jid_t, _tdata in JOCKEY_TENDENCY_DB.items():
                    _DBKEIBA_BONUS_CACHE[_jid_t] = get_tendency_as_bonus_dict(_jid_t)

            # Step2: 保存済みCSVがあれば追加ロード（CSV側が優先）
            _auto_bonus_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "data", "bonus_conditions.csv"
            )
            if os.path.exists(_auto_bonus_path):
                load_bonus_csv(_auto_bonus_path)
        except Exception:
            pass


# ──────────────────────────────────────────────
# --- Footer ---
st.divider()
st.caption("Keiba Analysis v2.5 - Powered by Streamlit & Gemini API")



