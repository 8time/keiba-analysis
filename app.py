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


# ── 公開(push)版 / ローカル(フル)版 の出し分け ─────────────────────
# git で文字を消すのではなく実行時に判定して切替（壊れにくい）。
# 判定: 環境変数 KEIBA_PUBLIC があれば優先、無ければ jravan.db(1.2GB・gitignore)の
#       有無で判定 → 無料サーバーにはDBが無い＝自動的に「公開(限定)版」になる。
def _detect_public():
    _ev = os.environ.get('KEIBA_PUBLIC')
    if _ev is not None:
        return _ev not in ('0', '', 'false', 'False')
    _db = os.path.join(os.path.dirname(__file__), 'data', 'jravan.db')
    if not os.path.exists(_db):
        return True
    # ファイルはあるが results テーブルが無い＝sqlite3.connect が誤って生成した空DB。
    # 本物の jravan.db は必ず results を持つ。空DBは公開版扱いにし、自己修復として削除する
    # （読めた上で results 不在を確認した時だけ削除。ロック等で読めない場合は消さない）。
    try:
        import sqlite3 as _s
        _c = _s.connect(f"file:{_db}?mode=ro", uri=True)
        _has = _c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='results'").fetchone()
        _c.close()
        if _has:
            return False
        try:
            os.remove(_db)
        except Exception:
            pass
        return True
    except Exception:
        return False


IS_PUBLIC = _detect_public()

_PUB_REPL = [('JRA-VAN版', '限定版'), ('JRA-VAN実データ', '内部データ'),
             ('JRA-VANで', '内部データで'), ('JRA-VAN/JRA', 'JRA'),
             ('JRA-VAN', ''), ('JV-VAN', ''), ('JV-Data', '公式データ'),
             ('jravan.db', '内部DB')]


def _pub(s):
    """公開(限定)版では JRA-VAN 等の表記を中立語へ置換。ローカルではそのまま返す。"""
    if not IS_PUBLIC or not isinstance(s, str):
        return s
    for _a, _b in _PUB_REPL:
        s = s.replace(_a, _b)
    return s.replace('  ', ' ')


_APP_TITLE = "🐎 Keiba Analysis -限定版" if IS_PUBLIC else "🐎 Keiba Analysis - Modified Ogura Index"
_PAGE_TITLE = "Keiba Analysis -限定版" if IS_PUBLIC else "Keiba Analysis - Modified Ogura Index"

st.set_page_config(page_title=_PAGE_TITLE, layout="wide")

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

    _MENU = [
        "🏠 Single Race Analysis",
        "🧠 MAGIシステム",
        "💰 BetSync（資金管理）",
        "🔍 Race Scanner (Batch)",
        "🧹 消去フィルター",
        "🤓 N氏の研究室",
        "🏇 騎手分析Pro",
        "💾 ロジック置き場",
        "📦 データ保管庫",
    ]
    # クリックで現在ページを切り替えず、新しいタブで開く（?nav=... を target=_blank で開き、
    # 新タブ側がこのクエリパラメータを読んで該当ページを表示する）
    import urllib.parse as _urlparse
    _qp_nav = st.query_params.get('nav')
    nav = _qp_nav if _qp_nav in _MENU else "🏠 Single Race Analysis"

    st.caption("クリックすると新しいタブで開きます（このタブの表示は変わりません）")
    _menu_html = '<div style="display:flex;flex-direction:column;gap:5px;">'
    for _m in _MENU:
        _u = '?nav=' + _urlparse.quote(_m)
        _active = (_m == nav)
        _bg = '#1f6feb' if _active else 'rgba(255,255,255,0.04)'
        _col = '#ffffff' if _active else '#9ecbff'
        _bd = '#1f6feb' if _active else 'rgba(255,255,255,0.12)'
        _mark = '▶ ' if _active else ''
        _menu_html += (
            f'<a href="{_u}" target="_blank" '
            f'style="text-decoration:none;color:{_col};background:{_bg};border:1px solid {_bd};'
            f'padding:7px 11px;border-radius:7px;font-weight:600;font-size:0.92em;display:block;">'
            f'{_mark}{_m}</a>'
        )
    _menu_html += '</div>'
    st.markdown(_menu_html, unsafe_allow_html=True)


st.title(_APP_TITLE)
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

        # ═════════════════════════════════════════
        # 🛡️ バンクロール・ガードレール（Task B：感情をルールで縛る）
        # ═════════════════════════════════════════
        from core import money

        st.divider()
        st.subheader("🛡️ バンクロール・ガードレール")
        st.caption("追い上げ系の「感情ベット」の上に、破産を数学的に止める防護柵を被せます。"
                   "1レース上限＝現在残高の数%（鉄則）／セッション損切り・利確で深追いを遮断。")

        g1, g2, g3 = st.columns(3)
        with g1:
            _ss.setdefault('bs_cap_pct', 2.0)
            _ss['bs_cap_pct'] = st.slider("1レース上限（残高の%）", 1.0, 5.0,
                                          float(_ss['bs_cap_pct']), 0.5, key="bs_gr_cap",
                                          help="鉄則: 1〜2%=保守 / 2〜3%=標準 / 5%=攻め")
        with g2:
            _ss.setdefault('bs_stop_pct', 25)
            _ss['bs_stop_pct'] = st.slider("セッション損切り（-%）", 10, 50,
                                           int(_ss['bs_stop_pct']), 5, key="bs_gr_stop",
                                           help="開始資金からこの%下落で撤退（推奨20〜30）")
        with g3:
            _ss.setdefault('bs_tp_pct', 30)
            _ss['bs_tp_pct'] = st.slider("セッション利確（+%）", 10, 100,
                                         int(_ss['bs_tp_pct']), 5, key="bs_gr_tp",
                                         help="開始資金からこの%上昇で利確（推奨30〜50）")

        # 上限チェック（進行系の次回ベット _nd_bet vs 残高%上限）
        _cap = money.cap_check(_nd_bet, final_balance, pct=_ss['bs_cap_pct'])
        _grd = money.session_guard(bankroll, final_balance,
                                   stop_loss_pct=_ss['bs_stop_pct'],
                                   take_profit_pct=_ss['bs_tp_pct'])

        gc1, gc2 = st.columns(2)
        with gc1:
            if _cap['ok']:
                st.success(f"✅ 次回ベット ¥{_nd_bet:,.0f} は上限内"
                           f"（上限 ¥{_cap['cap']:,.0f} ＝残高の{_cap['pct']:.1f}% / 実{_cap['bet_pct']:.1f}%）")
            else:
                st.error(f"🚨 次回ベット ¥{_nd_bet:,.0f} は上限超過（残高の{_cap['bet_pct']:.1f}%）。"
                         f"\n\n**鉄則上の推奨額 → ¥{_cap['recommended']:,.0f}**"
                         f"（上限 ¥{_cap['cap']:,.0f} ＝残高の{_cap['pct']:.1f}%／超過 ¥{_cap['over']:,.0f}）")
                st.caption("※ 追い上げ系が膨張しています。これがマーチンゲール破産の入口です。")
        with gc2:
            if _grd['status'] == '撤退(損切り)':
                st.error(f"🛑 **撤退ライン到達**（損益 {_grd['pnl']:+,.0f}円 / {_grd['pnl_pct']:+.1f}%）。"
                         f"\n\n今日はここで止める。明日の残高で再開。")
            elif _grd['status'] == '利確':
                st.success(f"🎉 **利確ライン到達**（損益 {_grd['pnl']:+,.0f}円 / {_grd['pnl_pct']:+.1f}%）。"
                           f"\n\n利益を確定して終了。欲を出さない。")
            else:
                st.info(f"🟢 継続中（損益 {_grd['pnl']:+,.0f}円 / {_grd['pnl_pct']:+.1f}%）\n\n"
                        f"撤退まで ¥{_grd['to_stop']:,.0f}（ライン¥{_grd['stop_line']:,.0f}）／"
                        f"利確まで ¥{_grd['to_tp']:,.0f}（ライン¥{_grd['tp_line']:,.0f}）")

        # ═════════════════════════════════════════
        # 🎯 EV配分・多肢ケリー（Task A：感情ではなく期待値で賭ける）
        # ═════════════════════════════════════════
        with st.expander("🎯 EV配分・多肢ケリー（妙味馬だけに合理配分）", expanded=False):
            st.caption("各馬の AI勝率 × 現在オッズ を入れると、EVプラス馬だけに残高の何%を"
                       "配分すべきかをケリー基準で算出します（追い上げの代わりに）。")
            # 🔗 Single Race Analysis の 🎰買い方最適化 が出した勝率×オッズを自動取込
            _feed = _ss.get('bs_ev_feed')
            if _feed and _feed.get('rows'):
                fl1, fl2 = st.columns([3, 1])
                with fl1:
                    st.success(f"🔗 予測モデル連携：レース **{_feed['race_id']}** の勝率×オッズを検出"
                               f"（{_feed['ts']} / α={_feed.get('alpha','-')}・{len(_feed['rows'])}頭）")
                with fl2:
                    if st.button("⬇️ 予測を取込", key="bs_kelly_load_feed", type="primary"):
                        _ss['bs_kelly_df'] = pd.DataFrame([
                            {'馬番': r['umaban'], '勝率%': round(r['p'] * 100, 1), 'オッズ': round(r['odds'], 1)}
                            for r in _feed['rows']])
                        st.rerun()
            _ss.setdefault('bs_kelly_df', pd.DataFrame(
                {'馬番': [1, 2, 3], '勝率%': [40.0, 20.0, 10.0], 'オッズ': [3.0, 6.0, 2.0]}))
            kc1, kc2 = st.columns([3, 1])
            with kc2:
                _kf = st.selectbox("ケリー率", [0.25, 0.5, 1.0],
                                   format_func=lambda x: f"1/4ケリー(推奨)" if x == 0.25
                                   else (f"1/2ケリー" if x == 0.5 else "フルケリー"),
                                   key="bs_kelly_frac")
            _edf = st.data_editor(_ss['bs_kelly_df'], num_rows="dynamic",
                                  key="bs_kelly_editor", width='stretch')
            _ss['bs_kelly_df'] = _edf
            try:
                _horses = [{'umaban': int(r['馬番']), 'p': float(r['勝率%']) / 100.0,
                            'odds': float(r['オッズ'])}
                           for _, r in _edf.iterrows()
                           if pd.notnull(r['馬番']) and pd.notnull(r['勝率%']) and pd.notnull(r['オッズ'])]
            except Exception:
                _horses = []
            if _horses:
                _km = money.kelly_multi(_horses, kelly_fraction=_kf)
                if any(b['frac'] > 0 for b in _km['bets']):
                    _rows = []
                    for b in _km['bets']:
                        if b['frac'] > 0:
                            _yen = int(final_balance * b['frac'] // 100) * 100
                            _rows.append({'馬番': b['umaban'], 'EV': b['ev'],
                                          '配分%': round(b['frac'] * 100, 2),
                                          '推奨額(円)': _yen})
                    st.dataframe(pd.DataFrame(_rows), width='stretch', hide_index=True)
                    _bet_yen = int(final_balance * _km['sum_bet'] // 100) * 100
                    st.info(f"EVプラス{len(_rows)}頭へ計 **¥{_bet_yen:,.0f}**（残高の{_km['sum_bet']*100:.1f}%）／"
                            f"現金留保 {_km['cash']*100:.1f}%　|　留保レートR={_km['reserve_rate']:.2f}　"
                            f"期待対数成長率 {_km['exp_log_growth']:+.4f}")
                    # 破産確率（最有力馬の繰り返し賭け）
                    _top = max(_km['bets'], key=lambda b: b['frac'])
                    _rp = money.ruin_probability(_top['p'], _top['odds'], kelly_fraction=_kf,
                                                 n_bets=500, ruin_level=0.5)
                    st.caption(f"💀 破産確率（{_top['umaban']}番を{_kf}ケリーで500戦繰り返した場合の資金半減確率）："
                               f"**{_rp.get('ruin_prob',0)*100:.1f}%**　中央値×{_rp.get('median_final','-')}")
                else:
                    st.warning("EVプラス（勝率×オッズ>1）の馬がありません。**賭けを見送るのが正解**。")

        # ═════════════════════════════════════════
        # 📈 回収率・残高推移（Task C：このセッションの記録）
        # ═════════════════════════════════════════
        if computed:
            st.divider()
            st.subheader("📈 回収率・残高推移")
            _cum_ret = 0
            _trend = []
            for _i, _c in enumerate(computed, 1):
                _cum_ret += _c['ret']
                _roi = (_cum_ret / _c['cum_bet'] * 100.0) if _c['cum_bet'] else 0.0
                _trend.append({'R': _i, '回収率%': round(_roi, 1), '残高': _c['balance']})
            _tdf = pd.DataFrame(_trend).set_index('R')
            tc1, tc2 = st.columns(2)
            with tc1:
                st.caption("累積回収率(%)　— 100%が損益分岐")
                st.line_chart(_tdf['回収率%'])
            with tc2:
                st.caption("残高推移(円)")
                st.line_chart(_tdf['残高'])

        # ═════════════════════════════════════════
        # 📒 収支台帳・Brier較正（Task C/D：予測→結果→反省ループ）
        # ═════════════════════════════════════════
        with st.expander("📒 収支台帳・Brier較正（予測勝率は当たっているか）", expanded=False):
            st.caption("単勝の予測勝率→結果を記録し、回収率の推移と Brier較正（予測確率の精度）を測ります。"
                       "AIの勝率予測が過大/過小評価していないかを数値で自己採点。")
            _lg = money.Ledger()
            try:
                # 🔗 予測モデル連携: feed の全頭をワンクリックで台帳へ（Brier較正データ化）
                _lfeed = _ss.get('bs_ev_feed')
                if _lfeed and _lfeed.get('rows'):
                    _lrid = _lfeed['race_id']
                    _exists = _lg.con.execute(
                        "SELECT COUNT(*) FROM bets WHERE race_id=?", (_lrid,)).fetchone()[0]
                    lf1, lf2 = st.columns([3, 1])
                    with lf1:
                        if _exists:
                            st.info(f"🔗 レース **{_lrid}** は記録済み（{_exists}件）。結果が出たら下の②で精算してください。")
                        else:
                            st.success(f"🔗 予測モデル連携：レース **{_lrid}** の {len(_lfeed['rows'])}頭の予測勝率を"
                                       f"台帳に一括記録できます（全頭記録＝較正用の正しいデータセット）。")
                    with lf2:
                        if st.button("📥 予測を一括記録", key="bs_led_ingest", disabled=bool(_exists)):
                            for _r in _lfeed['rows']:
                                _lg.record_prediction(_lrid, int(_r['umaban']), str(_r.get('bamei', '')),
                                                      float(_r['p']), float(_r['odds']), 100)
                            st.success(f"{len(_lfeed['rows'])}頭を記録しました。")
                            st.rerun()
                    st.markdown("---")

                _rep = _lg.report()
                if 'note' in _rep:
                    st.info("精算済みベットがまだありません。下のフォームで予測→結果を記録してください。")
                else:
                    lm1, lm2, lm3, lm4 = st.columns(4)
                    lm1.metric("記録数", f"{_rep['bets']}件")
                    lm2.metric("的中率", f"{_rep['hit_rate']}%")
                    lm3.metric("回収率", f"{_rep['roi']}%", f"{_rep['profit']:+,}円")
                    lm4.metric("Brier", f"{_rep['brier']}", help="0に近いほど予測確率が正確（≤0.25が目安）")
                    _srows = _lg.settled_rows()
                    if _srows:
                        _lc = 0; _lb = 0; _lt = []
                        for _idx, _r in enumerate(_srows, 1):
                            _lc += _r['payout']; _lb += _r['stake']
                            _lt.append({'n': _idx, '回収率%': round(_lc / _lb * 100.0, 1) if _lb else 0})
                        st.caption("台帳ベースの累積回収率(%)")
                        st.line_chart(pd.DataFrame(_lt).set_index('n')['回収率%'])
                    st.markdown("**🔍 反省会（予測 vs 実際の較正ズレ → 次回ルール）**")
                    for _rule in _lg.reflection():
                        st.markdown(f"- {_rule}")

                st.markdown("---")
                with st.form("bs_led_form", clear_on_submit=True):
                    st.markdown("**① 予測を記録**")
                    fc1, fc2, fc3, fc4, fc5 = st.columns(5)
                    _f_rid = fc1.text_input("レースID", key="bs_led_rid")
                    _f_uma = fc2.number_input("馬番", 1, 18, 1, key="bs_led_uma")
                    _f_p = fc3.number_input("予測勝率%", 0.0, 100.0, 20.0, key="bs_led_p")
                    _f_odds = fc4.number_input("オッズ", 1.0, 999.0, 5.0, key="bs_led_odds")
                    _f_stake = fc5.number_input("賭け金", 100, 1000000, 100, 100, key="bs_led_stake")
                    if st.form_submit_button("➕ 予測を台帳に記録"):
                        if _f_rid.strip():
                            _lg.record_prediction(_f_rid.strip(), int(_f_uma), '',
                                                  _f_p / 100.0, _f_odds, int(_f_stake))
                            st.success("記録しました。")
                            st.rerun()
                        else:
                            st.warning("レースIDを入力してください。")
                with st.form("bs_led_settle", clear_on_submit=True):
                    st.markdown("**② 結果を精算**")
                    sc1, sc2 = st.columns(2)
                    _s_rid = sc1.text_input("レースID", value=(_ss.get('bs_ev_feed') or {}).get('race_id', ''),
                                            key="bs_led_srid")
                    _s_win = sc2.number_input("1着馬番", 1, 18, 1, key="bs_led_swin")
                    _s_pay = st.number_input("単勝配当（100円あたり）", 0, 1000000, 0, 10, key="bs_led_spay")
                    if st.form_submit_button("✅ 結果を精算"):
                        if _s_rid.strip():
                            _lg.settle(_s_rid.strip(), int(_s_win), int(_s_pay))
                            st.success("精算しました。")
                            st.rerun()
                        else:
                            st.warning("レースIDを入力してください。")
                if st.button("🗑️ 台帳を全消去（デモデータ削除）", key="bs_led_reset"):
                    _lg.con.execute("DELETE FROM bets")
                    _lg.con.commit()
                    st.rerun()
            finally:
                _lg.close()

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

                    # 特別条件タグ（牝馬限定戦/ハンデ戦/新馬戦）を色付きで表示
                    _cond_tags = []
                    if meta.get('is_fillies'):
                        _cond_tags.append('<span style="color:#D81B60; font-weight:bold;">牝馬限定戦</span>')
                    if meta.get('is_handicap'):
                        _cond_tags.append('<span style="color:#E8590C; font-weight:bold;">ハンデ戦</span>')
                    if '新馬' in str(meta.get('class', '')):
                        _cond_tags.append('<span style="color:#1971C2; font-weight:bold;">新馬戦</span>')
                    _cond_html = (' <span style="color:#aaa;">|</span> ' + ' <span style="color:#aaa;">|</span> '.join(_cond_tags)) if _cond_tags else ''

                    st.markdown(f"""
                        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 10px; border-left: 10px solid {rank_color}; margin-bottom: 20px;">
                            <div style="display: flex; align-items: baseline; gap: 15px;">
                                <h1 style="margin: 0; font-size: 36px; color: #333;">Race Rating: {chaos_data['rank']}{_cond_html} <span style="color:#aaa;">|</span> {df['RaceName'].iloc[0] if not df.empty else ''}</h1>
                                <span style="font-size: 24px; color: {rank_color}; font-weight: bold;">(Score: {chaos_data.get('chaos_score', 0):.1f})</span>
                                <span style="margin-left: auto; font-size: 20px; font-weight: bold; background: #eee; padding: 4px 12px; border-radius: 20px;">📍 {display_cond}</span>
                            </div>
                            <p style="font-size: 18px; color: #555; margin-top: 10px; line-height: 1.6;"><b>判定理由:</b> {chaos_data['reason']}</p>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    # ── トラックバイアス強化（Phase1: 当日逆算/コース×馬場 ・ Phase2: クッション値/含水率）──
                    from core import track_bias as _tb
                    from core import pace_map as _tb_pm
                    _tb_venue = _tb_pm.venue_from_race_id(race_id_input)
                    _tb_surf = '芝'
                    try:
                        if 'CurrentSurface' in df.columns and not df.empty:
                            _tb_surf = 'ダ' if 'ダ' in str(df['CurrentSurface'].iloc[0]) else '芝'
                        elif 'ダ' in str(meta.get('surface', '')):
                            _tb_surf = 'ダ'
                    except Exception:
                        pass
                    # 🌧️ 重・不良馬場の検証済み注意(verified_heavy_track_bias)
                    _hb_cond = str(meta.get('condition', '') or '')
                    if _hb_cond in ('重', '不良', '稍重'):
                        if _tb_surf == '芝' and _hb_cond in ('重', '不良'):
                            st.warning(f"🌧️ 芝{_hb_cond}馬場：**1番人気の複勝率が大きく低下**"
                                       f"（検証: 芝重-5.6pp / 芝不良-9.2pp・オッズに未織込）。"
                                       f"1番人気の軸は割引き、人気薄の台頭・巻き返しに注意。", icon="🌧️")
                        elif _tb_surf == 'ダ' and _hb_cond == '不良':
                            st.warning("🌧️ ダート不良馬場：**1番人気がやや危険**（複勝-3.7pp）＋"
                                       "**外枠6-8が不利**の検証傾向。", icon="🌧️")
                        else:
                            st.info(f"🌧️ {_hb_cond}馬場：人気の信頼度低下は有意でなく概ね織込み済み"
                                    f"（馬場差は🔵補正タイムで較正済み）。")
                        st.caption("※馬場は締切直前に良→重へ変わることがあります。"
                                   "発走前に再取得して最新の馬場状態で判断してください。")
                    # 🌧️ 当日の時間別天気(会場・Open-Meteo) — 馬場悪化の予兆を確認
                    with st.expander("🌧️ 当日の時間別天気（会場・Open-Meteo）", expanded=False):
                        st.caption("締切直前に馬場が良→重へ変わる予兆を、会場の時間別降水量で確認します（押した時だけ取得）。")
                        _wd = str(meta.get('date_val', '') or '')[:8]
                        if not (len(_wd) == 8 and _wd.isdigit()):
                            st.caption("（このレースの開催日が取得できず天気照会できません）")
                        elif st.button("⛅ 時間別の天気を取得", key=f"wx_btn_{race_id_input}"):
                            from core import weather as _wx
                            with st.spinner("Open-Meteoから取得中..."):
                                _wr = _wx.fetch_hourly_precip(race_id_input, _wd)
                            if not _wr or '_error' in _wr:
                                st.warning(f"取得できませんでした: {(_wr or {}).get('_error', '不明')}")
                            else:
                                _sm = _wx.summarize(_wr)
                                if _sm:
                                    _wic = '🌧️' if _sm['rained'] else '☀️'
                                    st.info(f"{_wic} {_wr['venue']} {_wr['date']}：日中降水 **{_sm['total_mm']}mm** "
                                            f"/ ピーク {_sm['peak_hour']} / 傾向: **{_sm['trend']}**")
                                    if _sm['trend'].startswith('悪化'):
                                        st.warning("⚠️ 午後に雨が増える予報＝馬場悪化の可能性。後半レースは重/不良前提で"
                                                   "（芝の重・不良×1番人気は検証上 危険）。")
                                _whr = [{'時刻': hh, '降水mm': (p or 0)} for hh, p, _ in _wr.get('hours', [])
                                        if str(hh).split(':')[0].isdigit() and 6 <= int(str(hh).split(':')[0]) <= 20]
                                if _whr:
                                    st.bar_chart(pd.DataFrame(_whr).set_index('時刻'), height=170)
                    # 当日逆算バイアス: jravan.db に当該レースがあれば同日同場の既走Rから集計（無ければNone）
                    _tb_emp = None
                    _tb_rr = None  # jravan.db未配置(Streamlit Cloud等)でも後段で参照できるよう初期化
                    try:
                        import sqlite3 as _tb_sq
                        if os.path.exists('data/jravan.db'):
                            _tb_con = _tb_sq.connect('data/jravan.db')
                            _tb_rr = _tb_con.execute(
                                "SELECT year,monthday,jyo,surface,race_num FROM races WHERE race_id=?",
                                (race_id_input,)).fetchone()
                            _tb_con.close()
                            if _tb_rr:
                                _tb_emp = _tb.empirical_bias_from_db(*_tb_rr)
                    except Exception:
                        _tb_emp = None
                    st.session_state['_tb_emp_bias'] = _tb_emp  # Vエリアbaba自動化で参照

                    # track_cond テーブルからクッション値・含水率を自動供給（CSV取り込み済みデータ）
                    _tc_db = {'cushion': None, 'dirt_moisture': None}
                    _tc_shift = None
                    if _tb_rr:
                        _tc_db = _tb.lookup_track_cond(_tb_rr[0], _tb_rr[1], _tb_rr[2])
                        _tc_shift = _tb.cushion_day_shift(_tb_rr[0], _tb_rr[1], _tb_rr[2])

                    # コース特性: 距離・馬場を考慮した自動判定（従来の競馬場コード単独より精緻）
                    _tb_dist = meta.get('distance')
                    if not _tb_dist:
                        try:
                            import re as _tb_re2
                            if 'CurrentDistance' in df.columns and not df.empty:
                                _mm = _tb_re2.search(r'(\d{3,4})', str(df['CurrentDistance'].iloc[0]))
                                _tb_dist = int(_mm.group(1)) if _mm else None
                        except Exception:
                            _tb_dist = None
                    _course_profile_auto = _tb_pm.course_profile_label(_tb_venue, _tb_surf, _tb_dist)
                    st.session_state['_course_profile_auto'] = _course_profile_auto
                    # コース固有の経験的バイアス（jravan・静的・コースの性質）
                    _tb_cb = None
                    try:
                        _tb_cb = _tb.course_empirical_bias(str(race_id_input)[4:6], _tb_surf, _tb_dist)
                    except Exception:
                        _tb_cb = None

                    # Evidence Table
                    with st.expander("📊 判定根拠エビデンス表", expanded=True):
                        # クッション値・含水率（DB自動供給 + 手動上書き可）
                        _ck = f"tb_cushion_{race_id_input}"
                        _mk = f"tb_moist_{race_id_input}"
                        _mck = f"tb_moist_c4_{race_id_input}"
                        _tc_c = _tc_db.get('cushion') or 0.0
                        _tc_m = _tc_db.get('dirt_moisture') or 0.0
                        # 📌 24時間キャッシュ(開催日×場): 一度入れたら同日同場の他レースに自動引き継ぎ
                        from core import track_cond_cache as _tcache
                        _tcc = _tcache.load(race_id_input) or {}
                        _def_c = _tcc.get('cushion') or _tc_c
                        _def_m = _tcc.get('moist_goal') or (_tc_m if 'ダ' in _tb_surf else 0.0)
                        _def_mc = _tcc.get('moist_corner') or 0.0
                        st.session_state.setdefault(_ck, _def_c)
                        st.session_state.setdefault(_mk, _def_m)
                        st.session_state.setdefault(_mck, _def_mc)
                        if _tcc:
                            st.caption(f"📌 24時間キャッシュから自動入力（同じ開催日・場で共有／24h後に自動消去）"
                                       f"：クッション{_tcc.get('cushion') or '-'} / 含水ゴール前{_tcc.get('moist_goal') or '-'} / 4角{_tcc.get('moist_corner') or '-'}")
                        if _tc_c > 0 or _tc_m > 0:
                            _auto_parts = []
                            if _tc_c > 0:
                                _auto_parts.append(f"クッション{_tc_c:.1f}")
                            if _tc_m > 0:
                                _auto_parts.append(f"ダ含水{_tc_m:.1f}%")
                            st.caption(f"📡 DB自動供給: {' / '.join(_auto_parts)}（手動上書き可）")
                        _tb_paste = st.text_area(
                            _pub("📋 JRA-VANの馬場情報を貼り付け（任意・下のボタンで自動入力）"),
                            height=70, key=f"tb_paste_{race_id_input}",
                            placeholder="例: 芝クッション値(7時30分測定)：9.9　含水率：芝 ゴール前 11.4%、4コーナー 10.2%")
                        if st.button("📥 貼り付けから自動入力", key=f"tb_parse_{race_id_input}"):
                            _pp = _tb.parse_baba_announcement(_tb_paste)
                            if _pp.get('cushion') is not None:
                                st.session_state[_ck] = float(_pp['cushion'])
                            if _pp.get('moist_goal') is not None:
                                st.session_state[_mk] = float(_pp['moist_goal'])
                            if _pp.get('moist_corner') is not None:
                                st.session_state[_mck] = float(_pp['moist_corner'])
                            if any(_pp.get(k) is not None for k in ('cushion', 'moist_goal', 'moist_corner')):
                                st.success(f"自動入力: クッション{_pp.get('cushion')} / 含水ゴール前{_pp.get('moist_goal')} / 4角{_pp.get('moist_corner')}")
                                st.rerun()
                            else:
                                st.warning("数値を抽出できませんでした。手入力してください。")
                        _cm1, _cm2, _cm3 = st.columns(3)
                        with _cm1:
                            _tb_cushion = st.number_input(
                                "クッション値(芝)", min_value=0.0, max_value=15.0, step=0.1, key=_ck,
                                help=_pub("DB自動供給(2020-09〜)。手動上書き可。7以下=軟/12以上=硬。"))
                        with _cm2:
                            _tb_moist = st.number_input(
                                "含水率% ゴール前", min_value=0.0, max_value=30.0, step=0.1, key=_mk,
                                help="芝=高いほど時計遅／ダート=高いほど締まって速い（芝と逆）。")
                        with _cm3:
                            _tb_moist_c4 = st.number_input(
                                "含水率% 4コーナー", min_value=0.0, max_value=30.0, step=0.1, key=_mck,
                                help="ゴール前との差でコース内の部分的な荒れ・重さを判定（参考）。")
                        _cv = _tb_cushion if _tb_cushion > 0 else None
                        _mv = _tb_moist if _tb_moist > 0 else None
                        _mc = _tb_moist_c4 if _tb_moist_c4 > 0 else None
                        # 入力値を24hキャッシュへ保存(同日同場の他レースへ自動引き継ぎ・24h後自動消去)
                        if _cv or _mv or _mc:
                            try:
                                _tcache.save(race_id_input, cushion=_cv, moist_goal=_mv, moist_corner=_mc)
                            except Exception:
                                pass
                        st.session_state['_tb_cushion_style'] = _tb.cushion_style_bias(_tb_surf, _cv, _mv)

                        # エビデンス行を追記（Phase2: 馬場メトリクス / Phase1: 当日バイアス・コース×馬場）
                        evidence_list.extend(_tb.cushion_evidence(_tb_surf, _cv, _mv, moisture_corner=_mc))
                        if _tb_emp:
                            evidence_list.append({"項目": "当日逆算バイアス",
                                                  "値": f"{_tb_emp['pace_label']}/{_tb_emp['lane_label']}",
                                                  "ステータス": f"🔁 {_tb_emp['evidence']}"})
                        _tb_fast = None
                        if _cv is not None:
                            _tb_fast = _cv >= 10.0
                        elif _tb_emp:
                            _tb_fast = _tb_emp['front_rate'] >= 0.55
                        evidence_list.append({"項目": "コース×馬場傾向",
                                              "値": _tb_venue or '-',
                                              "ステータス": "🏟 " + _tb.course_bias_text(_tb_venue, _tb_fast)})
                        # コース特性プロファイル（距離・馬場考慮の自動判定）
                        evidence_list.append({"項目": "コース特性(自動判定)",
                                              "値": f"{_tb_venue}{_tb_surf}{_tb_dist or '?'}m",
                                              "ステータス": "✨ " + _course_profile_auto.replace('✨ ', '')})
                        # コース固有の経験的バイアス（jravan・過去実績）
                        if _tb_cb:
                            evidence_list.append({"項目": "コース実績バイアス",
                                                  "値": f"{_tb_cb['front_rate']*100:.0f}%先行",
                                                  "ステータス": "📚 " + _tb_cb['label']})
                        # 前日比クッション値シフト（絶対値より前日比が重要）
                        if _tc_shift:
                            _sh = _tc_shift
                            _sh_icon = {'+':"🔺硬化[+]",'△':"🔻軟化[△]",'±0':"➡️±0"}[_sh['shift']]
                            _sh_rel = "高信頼" if _sh['venue_reliable'] else ("⚠カオス場" if _sh['venue_chaos'] else "")
                            evidence_list.append({"項目": "前日比クッション値",
                                "値": f"{_sh['today']:.1f}（前日{_sh['prev']:.1f} / Δ{_sh['delta']:+.1f}）",
                                "ステータス": f"{_sh_icon} {_sh['turf_type']}(平均{_sh['turf_avg']}) {_sh_rel}"})
                        _ev_df = pd.DataFrame(evidence_list)

                        def _ev_row_style(_row):
                            _item = str(_row.get('項目', ''))
                            if _item == 'コース特性(自動判定)':
                                return ['background-color:#FFEFD5'] * len(_row)  # パパイヤホイップ
                            if _item == 'コース実績バイアス':
                                return ['background-color:#98FB98'] * len(_row)  # ペールグリーン
                            if _item == '先行馬密集度':
                                # ステータス列のみ赤文字
                                return ['color:#d00000;font-weight:bold' if _c == 'ステータス' else ''
                                        for _c in _row.index]
                            return [''] * len(_row)
                        try:
                            st.table(_ev_df.style.apply(_ev_row_style, axis=1))
                        except Exception:
                            st.table(_ev_df)
                        if _tb_emp is None:
                            st.caption("※当日逆算バイアスは未表示＝このレースの当日先行レース結果がJV-VAN（jravan.db）に未取り込み。"
                                       "未来のレースや体験版の当日反映前はVエリアのバイアスで手動指定してください。")
                        # 危険人気馬(逆張り消去・検証済): 外枠有利日に内枠を引いた1-3番人気
                        # ※順張り(合致馬を買う)は妙味ゼロ(priced-in)。逆張りのみ検証済エッジ。
                        if _tb_emp and _tb_emp.get('lane_label') == '外有利':
                            try:
                                _tosu_now = len(df)
                                _dpi_rows = []
                                for _, _drow in df.iterrows():
                                    _d_um = pd.to_numeric(_drow.get('Umaban'), errors='coerce')
                                    _d_pop = pd.to_numeric(_drow.get('Popularity'), errors='coerce')
                                    if pd.isnull(_d_um) or pd.isnull(_d_pop):
                                        continue
                                    _dpi = _tb.danger_popular_inner(_tb_emp, int(_d_um), _tosu_now, int(_d_pop))
                                    if _dpi:
                                        _d_nm = str(_drow.get('Name') or _drow.get('HorseName') or '?')
                                        _dpi_rows.append(f"- {int(_d_um)}番 {_d_nm}（{int(_d_pop)}番人気）: {_dpi['detail']}")
                                if _dpi_rows:
                                    st.warning("⚠ **危険人気馬（当日バイアス逆張り・検証済）**\n\n" + "\n".join(_dpi_rows)
                                               + "\n\n→ 軸からは外し、3連複の相手候補からも削ると点数効率が上がる目安。")
                            except Exception:
                                pass

                    # --- 血統適性サマリー（blood_dict.db） ---
                    with st.expander("🧬 血統適性（父×条件別 複勝率/回収率）", expanded=False):
                        try:
                            from core import bloodline as _bl2
                            _bl_rows = []
                            for _, _brow in df.iterrows():
                                _b_sire = str(_brow.get('sire') or '-')
                                _b_bms = str(_brow.get('broodmareSire') or '-')
                                _b_name = str(_brow.get('HorseName') or _brow.get('bamei') or '?')
                                _b_num = _brow.get('Umaban') or _brow.get('umaban') or '?'
                                _ss = _bl2.lookup_sire_stats(_b_sire, _tb_surf, _tb_dist)
                                _bs = _bl2.lookup_bms_stats(_b_bms, _tb_surf, _tb_dist)
                                _row = {'馬番': _b_num, '馬名': _b_name, '父': _b_sire, '母父': _b_bms}
                                if _ss:
                                    _row['父複勝率'] = f"{_ss['place_rate']:.1f}%"
                                    _row['父単回収'] = f"{_ss['win_roi']:.0f}%"
                                    _row['父走数'] = _ss['runs']
                                else:
                                    _row['父複勝率'] = '-'
                                    _row['父単回収'] = '-'
                                    _row['父走数'] = '-'
                                if _bs:
                                    _row['母父複勝率'] = f"{_bs['place_rate']:.1f}%"
                                    _row['母父単回収'] = f"{_bs['win_roi']:.0f}%"
                                else:
                                    _row['母父複勝率'] = '-'
                                    _row['母父単回収'] = '-'
                                # 馬場シフトフラグ
                                _sf = _tb.sire_cushion_flag(_b_sire, _tc_shift) if _tc_shift else None
                                _row['馬場シフト'] = _sf['flag'] if _sf else '-'
                                _bl_rows.append(_row)
                            if _bl_rows:
                                _bl_df = pd.DataFrame(_bl_rows)
                                st.dataframe(_bl_df, use_container_width=True, hide_index=True)
                                if _tc_shift and _tc_shift['shift'] != '±0':
                                    _shift_label = {'+':"硬化[+]→ディープ系・キズナ・レイデオロ活性",
                                                    '△':"軟化[△]→ND系・キタサンブラック活性"}
                                    st.caption(f"今日の前日比シフト: {_shift_label.get(_tc_shift['shift'], '')}")
                        except Exception as _bl_err:
                            st.caption(f"血統辞書エラー: {_bl_err}")

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

                            # ── 🧭 ペース総合判定（3指標を束ねて『どれを信じるか』を明示）──
                            def _pnorm(s):
                                s = str(s or '')
                                if 'ハイ' in s or '前傾' in s:
                                    return 'ハイ'
                                if 'スロー' in s or '後傾' in s:
                                    return 'スロー'
                                if s in ('標準', 'ミドル', 'イーブン'):
                                    return 'ミドル'
                                return None
                            _ten = st.session_state.get(f'_pace_int_{race_id_input}') or {}
                            _ten_lbl = _ten.get('label')
                            _ten_n = _pnorm(_ten_lbl)
                            _map_p = st.session_state.get(f'_pace_map_pace_{race_id_input}')
                            _map_n = _pnorm(_map_p)
                            _rpci_n = _pnorm(_pace_lbl_pci)
                            # 信頼順: テン速力(実時計・検証済) > 展開マップ(隊列の地図) > PCI(参考)
                            _verdict = _ten_n or _map_n or _rpci_n or 'ミドル'
                            _src = ('テン速力(検証済)' if _ten_n else ('展開マップ' if _map_n else 'PCI(参考)'))
                            _votes = [v for v in (_ten_n, _map_n, _rpci_n) if v]
                            _agree = _votes.count(_verdict)
                            _conf = ('3指標一致=信頼◎' if _agree >= 3 else
                                     ('2指標一致=多数決' if _agree == 2 else '食い違い=注意'))
                            _lean_txt = ('差し台頭で荒れ寄り → ②穴妙味狙い向き' if _verdict == 'ハイ'
                                         else ('前残りで堅め → 本線(人気2頭軸)向き' if _verdict == 'スロー'
                                               else '標準 → 力通り'))
                            _vc = {'ハイ': '#E63946', 'スロー': '#2A9D8F', 'ミドル': '#F4A261'}[_verdict]
                            st.markdown(f"""
                            <div style="background:#1a1a2e; color:#eee; padding:12px 16px; border-radius:10px;
                                        border-left:8px solid {_vc}; margin-bottom:10px;">
                                <div style="font-size:16px;">🧭 <b>ペース総合判定: <span style="color:{_vc};">{_verdict}</span></b>
                                &nbsp;<span style="font-size:12px;color:#ffd166;">（信じるのは {_src} ／ {_conf}）</span></div>
                                <div style="font-size:13px; color:#cfd6e4; margin-top:6px;">{_lean_txt}</div>
                                <div style="font-size:12px; color:#9aa3b2; margin-top:6px;">
                                内訳: テン速力z <b>{_ten_lbl or '—(展開マップ計算後に反映)'}</b> ｜
                                展開マップ <b>{_map_p or '—'}</b> ｜ PCI/RPCI <b>{_pace_lbl_pci}</b></div>
                                <div style="font-size:11px; color:#7a8290; margin-top:4px;">
                                信頼順位 ①テン速力(実時計・荒れ率と検証相関＝3連複🌀の根拠) ②展開マップ(隊列の地図)
                                ③PCI/RPCI(参考・乖離の妙味は検証で否定)。迷ったら①に従う。</div>
                            </div>
                            """, unsafe_allow_html=True)

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
                                # フィールド平均PCI: ±1.0以内=黄緑(#ADFF2F)、±2.0以内=薄黄(#FFF9C4)
                                def _highlight_near_avg(row):
                                    try:
                                        _d = abs(float(row['AvgPCI']) - avg_pci_val)
                                    except Exception:
                                        _d = None
                                    if _d is not None and _d <= 1.0:
                                        _bg = 'background-color:#ADFF2F'
                                    elif _d is not None and _d <= 2.0:
                                        _bg = 'background-color:#FFF9C4'
                                    else:
                                        _bg = ''
                                    return [_bg for _ in row]
                                st.dataframe(
                                    _mh_df.style
                                        .apply(_highlight_near_avg, axis=1)
                                        .apply(_highlight_match, subset=['適合度']),
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
                    # コース特性: 距離・馬場考慮の自動判定を優先（meta明示があればそれを尊重）
                    course_profile_main = meta.get('course_profile') or st.session_state.get('_course_profile_auto', '')
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

                    # --- 🐎 Stress Analyst（乗算デバフ・リーク無し検証版）---
                    with st.expander("🐎 Stress Analyst（危険人気馬あぶり出し・検証済デバフ）", expanded=False):
                        st.caption(
                            "基礎能力（戦闘力＋血統）に当日の環境ストレスを掛け算で小さく反映し、"
                            "人気のわりに走りにくい馬をあぶり出します。jravan(2023-25)で"
                            "『リーク無し（事前に分かるデータのみ）』に再検証した条件だけを採用："
                            "小柄馬×馬体減(-2.0pp)／芝×後方ぐせ(-1.5pp)／馬体増+8kg(-1.0pp)。"
                            "効果は±1〜2ppと小さく、軸を消すより相手の優先度を下げる用途です。"
                            "（旧版の逃げ+13pp等は結果脚質によるリークと判明し廃止）"
                        )
                        try:
                            _ss_results = []
                            for _, _ss_row in df.iterrows():
                                m = 1.0
                                reasons = []
                                w_text = str(_ss_row.get('WeightHistory', ''))
                                match_w = re.search(r'(\d+)\(([-+]?\d+)\)', w_text)
                                curr_w = int(match_w.group(1)) if match_w else 0
                                w_diff_val = int(match_w.group(2)) if match_w else 0
                                try:
                                    umaban = int(_ss_row.get('Umaban', 0))
                                except Exception:
                                    umaban = 0
                                try:
                                    waku = int(_ss_row.get('Waku', 1))
                                except Exception:
                                    waku = 1
                                avg_pos = float(_ss_row.get('AvgPosition', 9.9) or 9.9)
                                surface = str(_ss_row.get('CurrentSurface', ''))
                                is_back = avg_pos >= 7.5  # 習性後方（差し・追込）＝事前に分かる脚質
                                # ① 小柄馬×大幅馬体減：肉体ストレス(事前確定・複勝残差-2.0pp z=-3.0)
                                if 0 < curr_w < 440 and w_diff_val <= -6:
                                    m -= 0.04
                                    reasons.append("🟧小柄馬(440kg未満)×馬体減6kg超(検証-2.0pp)")
                                # ② 習性後方ぐせ×芝：揉まれ・展開待ち(複勝残差-1.5pp z=-3.0。ダートは非有意)
                                if "芝" in surface and is_back:
                                    m -= 0.03
                                    reasons.append("🟨芝×後方ぐせ(検証-1.5pp)")
                                # ③ 大幅馬体増：仕上がり/余分(事前確定・複勝残差-1.0pp z=-3.1・軽微)
                                if w_diff_val >= 8:
                                    m -= 0.02
                                    reasons.append("🟨馬体増+8kg超(軽微-1.0pp)")
                                multiplier = min(max(m, 0.85), 1.0)
                                base = float(_ss_row.get('BattleScore', 0) or 0)
                                blood = float(_ss_row.get('bonus', 0) or 0)
                                pre_score = base + blood
                                final_score = pre_score * multiplier
                                _ss_results.append({
                                    "枠番": waku,
                                    "馬番": umaban,
                                    "馬名": _ss_row.get('Name', ''),
                                    "脚質傾向": "差し/追込" if is_back else ("逃げ/前" if avg_pos <= 2.5 else "好位/中団"),
                                    "基礎評価": round(pre_score, 1),
                                    "ストレス係数": f"{multiplier:.2f}",
                                    "ストレス要因": " / ".join(reasons) if reasons else "標準 ✅",
                                    "最終予測": round(final_score, 1),
                                    "増減量": round(final_score - pre_score, 1),
                                })
                            if _ss_results:
                                _ss_df = pd.DataFrame(_ss_results).sort_values("最終予測", ascending=False)

                                def _style_stress(val):
                                    f_val = float(val)
                                    if f_val < 0.92:
                                        return 'background-color: #ffebee; color: #c62828; font-weight: bold;'
                                    if f_val < 1.0:
                                        return 'background-color: #fff8e1; color: #f57f17;'
                                    return 'color: #555;'

                                st.dataframe(
                                    _ss_df.style.map(_style_stress, subset=['ストレス係数']),
                                    column_config={
                                        "基礎評価": st.column_config.NumberColumn(format="%.1f"),
                                        "最終予測": st.column_config.NumberColumn(format="%.1f"),
                                        "増減量": st.column_config.NumberColumn(format="%+.1f"),
                                    },
                                    hide_index=True,
                                    use_container_width=True,
                                )
                                _trap = _ss_df[_ss_df['ストレス係数'].astype(float) < 0.92]
                                if not _trap.empty:
                                    st.warning(
                                        "⚠️ **過剰評価トラップ（危険人気の候補）**: 事前確定の検証済みストレスが該当。"
                                        "効果は小さい（±1〜2pp）ので、軸を消すより相手の優先度を下げる用途です。\n\n" +
                                        "\n".join([f"- {h['馬名']} (係数 {h['ストレス係数']})：{h['ストレス要因']}"
                                                   for _, h in _trap.iterrows()]))
                        except Exception as _ss_e:
                            st.caption(f"ストレス解析をスキップしました: {_ss_e}")

                    # --- 🗺️ コーナー別 想定展開マップ ---
                    with st.expander("🗺️ 展開マップ（コーナー別 想定位置取り）", expanded=False):
                        try:
                            from core import pace_map as _pmap
                            _pm_psm = _pace.get('position_score_map', {}) if '_pace' in dir() else {}
                            _pm_plm = _pace.get('positional_map', {}) if '_pace' in dir() else {}
                            _pm_horses = []
                            for _, _pm_r in df.iterrows():
                                try:
                                    _pm_u = int(_pm_r['Umaban'])
                                except Exception:
                                    continue
                                _pm_sc = _pm_psm.get(_pm_u)
                                if _pm_sc is None:
                                    _pm_sc = _pmap.score_from_pastruns(_pm_r.get('PastRuns', []))
                                _pm_horses.append({
                                    'umaban': _pm_u,
                                    'name': str(_pm_r.get('Name', '')),
                                    'score': float(_pm_sc),
                                    'style': _pm_plm.get(_pm_u) or _pmap.style_from_score(float(_pm_sc)),
                                })
                            # 距離: metadata → CurrentDistance 列の順でフォールバック
                            _pm_dist = meta.get('distance')
                            if not _pm_dist and 'CurrentDistance' in df.columns and not df.empty:
                                try:
                                    import re as _pm_re
                                    _pm_m = _pm_re.search(r'(\d{3,4})', str(df['CurrentDistance'].iloc[0]))
                                    _pm_dist = int(_pm_m.group(1)) if _pm_m else None
                                except Exception:
                                    _pm_dist = None
                            _pm_venue = _pmap.venue_from_race_id(race_id_input)
                            _pm_turn = _pmap.infer_turn(_pm_venue)
                            # コースレイアウト諸元（1角までの距離・直線長）による補正
                            _pm_surf = str(df['CurrentSurface'].iloc[0]) if 'CurrentSurface' in df.columns and not df.empty else '芝'
                            _pm_layout = _pmap.get_course_layout(_pm_venue, _pm_surf, _pm_dist)
                            # JRA-VAN実データをDBから取得（同馬場・距離近接の過去8走を条件・直近重みで集計。レース単位でキャッシュ）
                            _pm_prof_key = f"jv_pace_prof_{race_id_input}_{_pm_surf}_{_pm_dist}"
                            if _pm_prof_key not in st.session_state:
                                st.session_state[_pm_prof_key] = _pmap.fetch_jv_profiles(
                                    [h['name'] for h in _pm_horses], max_runs=8,
                                    surface=_pm_surf, distance=_pm_dist,
                                )
                            _pm_profiles = st.session_state[_pm_prof_key]

                            # 直線の風補正（任意・5m/s以上＆向かい/追い風で発火）。
                            # 自動取得=Open-Meteo（無料・APIキー不要）。風向°と各場の直線方位から
                            # 追い風/向かい風/横風を自動判定。手動入力にも対応。
                            _pm_wind = None
                            _pw_auto_key = f"pace_wind_auto_{race_id_input}"
                            _pw_method = st.radio(
                                "💨 直線の風（任意）",
                                ["補正なし", "自動取得（無料）", "手動入力"],
                                key="pace_wind_method", horizontal=True,
                                help="自動取得=Open-Meteo（無料・キー不要）で競馬場の現在の風を取得し、"
                                     "風向と各場の直線方位から追い風/向かい風/横風を自動判定。"
                                     "5m/s以上の向かい/追い風で展開補正が発火（風データはDBに無く"
                                     "精度未検証のため、控えめな補助補正です）。",
                            )
                            if _pw_method == "自動取得（無料）":
                                _pw_ca, _pw_cb = st.columns([1, 2])
                                with _pw_ca:
                                    if st.button("🌤 現在の風を取得", key="pace_wind_fetch"):
                                        st.session_state[_pw_auto_key] = _pmap.fetch_wind(_pm_venue)
                                _auto = st.session_state.get(_pw_auto_key)
                                if _auto and _auto.get('speed') is not None:
                                    _pm_wind = dict(_auto)
                                    _pm_wind['venue'] = _pm_venue
                                    _we_tmp = _pmap.wind_effect(_pm_wind)
                                    _kindjp = {'head': '向かい風', 'tail': '追い風',
                                               'none': '横風/微風（影響小）'}.get(
                                                   _we_tmp['kind'] if _we_tmp else 'none', '-')
                                    with _pw_cb:
                                        st.metric(
                                            f"{_pm_venue} の現在の風",
                                            f"{float(_auto.get('speed') or 0):.1f} m/s",
                                            f"{float(_auto.get('dir_deg') or 0):.0f}° → 直線{_kindjp}")
                                elif _auto is not None:
                                    st.warning("風データを取得できませんでした（オフライン等）。「手動入力」をご利用ください。")
                                else:
                                    st.caption("「🌤 現在の風を取得」を押すとOpen-Meteo（無料）から取得します。")
                            elif _pw_method == "手動入力":
                                _pw_c1, _pw_c2 = st.columns([1, 1])
                                with _pw_c1:
                                    _pw_mode = st.selectbox(
                                        "直線の風向き", ["追い風", "向かい風"], key="pace_wind_mode")
                                with _pw_c2:
                                    _pw_spd = st.number_input(
                                        "風速 (m/s)", min_value=0.0, max_value=25.0,
                                        value=0.0, step=1.0, key="pace_wind_spd")
                                if _pw_spd >= 5.0:
                                    _pm_wind = {'mode': 'tail' if _pw_mode == "追い風" else 'head',
                                                'speed': float(_pw_spd), 'venue': _pm_venue}

                            # 強適Ranking Table由来の決め手・適性・総合力を直線(到達=着順)位置へ反映
                            def _pm_num(v):
                                try:
                                    f = float(v)
                                    return f if f == f else None  # NaN除外
                                except (TypeError, ValueError):
                                    return None
                            _pm_extras = {}
                            for _, _er in df.iterrows():
                                try:
                                    _eu = int(_er['Umaban'])
                                except Exception:
                                    continue
                                _ex = {}
                                _av = _pm_num(_er.get('AvgAgari')) if 'AvgAgari' in df.columns else None
                                if _av is not None and _av > 0:
                                    _ex['kick'] = _av                # 上がり3F: 小さいほど速い=良い
                                _sv = _pm_num(_er.get('Suitability (Y)')) if 'Suitability (Y)' in df.columns else None
                                if _sv is not None:
                                    _ex['apt'] = -_sv                # 適性: 大きいほど良い→反転で0=最良
                                _bv = _pm_num(_er.get('BattleScore')) if 'BattleScore' in df.columns else None
                                if _bv is not None:
                                    _ex['power'] = -_bv              # 総合戦闘力: 大きいほど良い→反転
                                # 人気/単勝オッズ: 市場の総意（最強の単一指標）。小さいほど上位人気=良い
                                _pv = _pm_num(_er.get('Popularity')) if 'Popularity' in df.columns else None
                                if _pv is None or _pv >= 99:
                                    _ov = _pm_num(_er.get('Odds')) if 'Odds' in df.columns else None
                                    _pv = _ov if (_ov is not None and _ov > 0 and _ov < 999) else None
                                if _pv is not None:
                                    _ex['pop'] = _pv
                                if _ex:
                                    _pm_extras[_eu] = _ex

                            _pm_ctx = _pmap.build_pace_context(
                                _pm_horses, _pm_profiles, _pm_dist, _pm_surf,
                                _pm_layout, _pm_wind)
                            # 3連複エンジン等から参照するため展開コンテキストを保存
                            st.session_state[f'_pace_ctx_{race_id_input}'] = _pm_ctx
                            # 🧭 ペース総合判定(⚡PCI上部)から参照する展開マップのペース判定
                            st.session_state[f'_pace_map_pace_{race_id_input}'] = _pm_ctx.get('pace')
                            # 事前ペース強度（テン速力ベース・検証済み: ハイ想定→荒れ寄り）を保存
                            try:
                                st.session_state[f'_pace_int_{race_id_input}'] = \
                                    _pmap.predict_pace_intensity(_pm_profiles, _pm_dist, _pm_surf)
                            except Exception:
                                st.session_state[f'_pace_int_{race_id_input}'] = None
                            _pm_data = _pmap.estimate_pace_map(
                                _pm_horses, distance=_pm_dist, profiles=_pm_profiles,
                                layout=_pm_layout, surface=_pm_surf, wind=_pm_wind,
                                extras=_pm_extras,
                            )
                            if _pm_data:
                                _pm_title = f"{_pm_venue} {_pm_dist}m" if _pm_venue and _pm_dist else "想定展開マップ"
                                _pm_fig = _pmap.build_figure(_pm_data, turn=_pm_turn, title=_pm_title)
                                st.plotly_chart(_pm_fig, use_container_width=True, key="pace_map_fig")
                                # 最終直線で後方の馬を🧹消去クロステーブルへ橋渡し(ディスク保存)
                                try:
                                    from core import score_cache as _sc_rear
                                    _sc_rear.write_rear(race_id_input, _pmap.final_straight_rear(_pm_data))
                                except Exception:
                                    pass
                                _pm_n_jv = sum(1 for h in _pm_horses if h['name'] in _pm_profiles)
                                st.caption(_pub(
                                    f"📊 JRA-VAN実データ使用: {_pm_n_jv}/{len(_pm_horses)}頭"
                                    "（同馬場・近距離の過去8走を条件＆直近重みで集計。テン速力＝(走破タイム−上がり3F)/(距離−600)×600 を"
                                    "メンバー内z-score化し、コーナー履歴と合成して局面別ポジションを推定）｜ "
                                    "🔴逃げ 🟠先行 🔵差し 🟣追込 ｜ 下=内ラチ・右=前方。"
                                    "**【直線】は4角位置に強適Ranking Tableの〈決め手(上がり3F)・適性・総合戦闘力〉を合成した"
                                    "到達(着順)イメージ＝後方一気の差し馬も前方に描画**します。"
                                    "スライダーで局面を切替。想定であり実際の隊列を保証するものではありません。"
                                ))
                                # ペース文脈サマリ（ハナ・ペース判定・風）
                                _pm_lead_h = next((h for h in _pm_horses if h['umaban'] == _pm_ctx.get('leader')), None)
                                _pm_lead_txt = f"{_pm_lead_h['umaban']}番 {_pm_lead_h['name']}" if _pm_lead_h else "不明"
                                _pm_chips = [
                                    f"想定ペース: **{_pm_ctx.get('pace', '—')}**",
                                    f"ハナ予想: **{_pm_lead_txt}**",
                                    f"前向き率: **{_pm_ctx.get('front_ratio', 0)*100:.0f}%**",
                                ]
                                _pm_we = _pmap.wind_effect(_pm_wind) if _pm_wind else None
                                if _pm_we and _pm_we.get('kind') != 'none':
                                    _pm_chips.append(f"💨 {_pm_we['note']}")
                                st.info("　｜　".join(_pm_chips))
                                _pm_comment = _pmap.describe_pace(
                                    _pm_horses, profiles=_pm_profiles, layout=_pm_layout,
                                    pace_ctx=_pm_ctx,
                                )
                                if _pm_comment:
                                    st.markdown(
                                        f"<div style='background:#1a1a2e; color:#eee; padding:10px 14px; "
                                        f"border-radius:8px; border-left:6px solid #2A9D8F; font-size:13px;'>"
                                        f"💬 {_pm_comment}</div>",
                                        unsafe_allow_html=True,
                                    )

                                # ── 🔄 バイアス巻き返し（人気帯リフレーム版・検証反映） ──
                                # 検証(scripts/comeback_backtest.py・2023-25)で「巻き返し穴=次走妙味」は否定。
                                # 穴帯(6番人気〜)は複勝残差≈0〜負・単ROI66-68%で妙味ゼロ→非表示。
                                # 1-3番人気で発火のみ複勝残差+2.1pp(z=2.2)=軸の信頼度。4-5番人気は-3.8pp(z=-3.0)=危険人気の罠。
                                try:
                                    from core import track_bias as _cb_tb
                                    _cb_key = f"comeback_{race_id_input}"
                                    if _cb_key not in st.session_state:
                                        _cb = []
                                        for _h in _pm_horses:
                                            _f = _cb_tb.comeback_flag(_h['name'], before_key=None)
                                            if _f:
                                                _cb.append((_h['umaban'], _h['name'], _f['reason']))
                                        st.session_state[_cb_key] = _cb
                                    _cb_list = st.session_state[_cb_key]
                                    if _cb_list:
                                        _cb_ninki = {}
                                        if 'Popularity' in df.columns:
                                            for _, _cb_rr in df.iterrows():
                                                try:
                                                    _cb_ninki[int(_cb_rr['Umaban'])] = int(
                                                        pd.to_numeric(_cb_rr.get('Popularity'), errors='coerce'))
                                                except Exception:
                                                    pass
                                        _cb_axis, _cb_trap, _cb_hidden = [], [], 0
                                        for u, nm, r in _cb_list:
                                            p = _cb_ninki.get(u)
                                            if not p or p <= 0:
                                                _cb_hidden += 1            # 人気未取得=判定不可
                                            elif p <= 3:
                                                _cb_axis.append((u, nm, p, r))
                                            elif p <= 5:
                                                _cb_trap.append((u, nm, p, r))
                                            else:
                                                _cb_hidden += 1            # 6番人気以下=妙味ゼロ(検証)→非表示

                                        def _cb_rows(items):
                                            return "".join(
                                                f"<div style='background:rgba(0,0,0,0.18);border-radius:8px;"
                                                f"padding:7px 12px;margin:5px 0;'>"
                                                f"<b style='font-size:16px;color:#fff;'>{u}番 {nm} "
                                                f"<span style='font-size:12px;opacity:.85;'>({p}番人気)</span></b>"
                                                f"<span style='font-size:12px;color:#e9eef5;margin-left:10px;'>{r}</span></div>"
                                                for u, nm, p, r in items)
                                        # ✅ 1-3番人気で発火 → 軸の複勝信頼度UP（唯一の正のエッジ）
                                        if _cb_axis:
                                            st.markdown(
                                                "<div style='background:linear-gradient(135deg,#1b5e20,#2a9d8f);"
                                                "border:2px solid #8bf5b0;border-radius:12px;padding:14px 16px;margin:12px 0;'>"
                                                "<div style='font-size:18px;font-weight:900;color:#fff;'>"
                                                "🔄 巻き返し→軸の複勝信頼度UP（1〜3番人気）</div>"
                                                "<div style='font-size:12px;color:#e8fff0;margin:3px 0 8px;'>"
                                                "直近走で馬場バイアスに<b>逆らって好走</b>＋現在も人気上位。"
                                                "検証: この帯のみ複勝残差+2.1pp(z=2.2)＝<b>軸・相手の信頼度UP</b>"
                                                "（単勝妙味ではない＝ROIは控除内）。</div>"
                                                f"{_cb_rows(_cb_axis)}</div>",
                                                unsafe_allow_html=True)
                                        # ⚠ 4-5番人気で発火 → 危険人気の罠（過剰人気）
                                        if _cb_trap:
                                            st.markdown(
                                                "<div style='background:linear-gradient(135deg,#7f1d1d,#b45309);"
                                                "border:2px solid #fca5a5;border-radius:12px;padding:14px 16px;margin:12px 0;'>"
                                                "<div style='font-size:18px;font-weight:900;color:#fff;'>"
                                                "⚠ 巻き返し×4〜5番人気＝危険人気の罠</div>"
                                                "<div style='font-size:12px;color:#fff0f0;margin:3px 0 8px;'>"
                                                "巻き返し実績で人気を集めるが検証では複勝残差<b>-3.8pp(z=-3.0)</b>＝"
                                                "<b>過剰人気</b>。軸から外す/消去・相手厳選の検討材料。</div>"
                                                f"{_cb_rows(_cb_trap)}</div>",
                                                unsafe_allow_html=True)
                                        if not _cb_axis and not _cb_trap and _cb_hidden:
                                            st.caption(f"🔄 巻き返し該当 {_cb_hidden}頭は6番人気以下／人気未取得のため非表示"
                                                       "（検証で穴帯は妙味ゼロ=単ROI66-68%）。")
                                except Exception as _cb_e:
                                    st.caption(f"巻き返し判定: {_cb_e}")

                                # ── 🎯 差し切り限界ライン（1秒≒6馬身） ──
                                _sk_rows = _pmap.sashikiri_table(_pm_data, _pm_profiles)
                                if _sk_rows:
                                    st.markdown("**🎯 差し切り限界ライン**（1秒≒6馬身・1馬身≒0.17秒）")
                                    _sk_verdict_label = {
                                        'reach': '◎ 平均上がりで届く',
                                        'best_only': '△ 自己ベストなら届く',
                                        'no': '✕ ベストでも届かない',
                                    }
                                    _sk_disp = [{
                                        "馬番": _s['umaban'],
                                        "馬名": _s['name'],
                                        "4角想定": f"{_s['rank4']}番手",
                                        "先頭との差": f"約{_s['gap_len']}馬身",
                                        "平均上がり": f"{_s['my_agari']:.2f}",
                                        "自己ベスト": f"{_s['my_best']:.2f}",
                                        "必要上がり": f"{_s['need_agari']:.2f}",
                                        "判定": f"{_sk_verdict_label.get(_s['verdict'], '-')} ({_s['margin']:+.2f}秒)",
                                    } for _s in _sk_rows]
                                    st.dataframe(pd.DataFrame(_sk_disp), hide_index=True, use_container_width=True)
                                    st.caption(
                                        "4角想定隊列の先頭馬（の平均上がり3F）を物理的に差し切れるかの目安。"
                                        "馬身差は順位差×1.4馬身で推定。◎=平常運転で届く / △=自己ベスト必須（過信禁物） / "
                                        "✕=どれだけ脚を使っても物理的に届かない＝消し候補。"
                                    )

                                # ── 🧭 Vエリア・マトリクス（馬場 × 展開） ──
                                st.markdown("---")
                                st.markdown("**🧭 Vエリア・マトリクス**（馬場バイアス × 想定ペースで最も恵まれるポジションを可視化）")
                                # ペース初期値: 展開マップのペース文脈→展開分析の順で自動セット
                                _vm_pace_auto = _pm_ctx.get('pace') if _pm_ctx.get('pace') in _pmap.V_PACE_PATTERNS else 'ミドル'
                                if _vm_pace_auto == 'ミドル':
                                    try:
                                        _vm_pl = str(_pace.get('pace_label', '')) if '_pace' in dir() else ''
                                        if 'ハイ' in _vm_pl:
                                            _vm_pace_auto = 'ハイ'
                                        elif 'スロー' in _vm_pl:
                                            _vm_pace_auto = 'スロー'
                                    except Exception:
                                        pass
                                # 馬場バイアス初期値: ①当日逆算バイアス(実測・最優先) → ②開催日数/馬場(静的) の順で自動推定
                                _vm_baba_auto_idx = 0
                                _vm_baba_src = "開催日数/馬場"
                                _vm_emp = st.session_state.get('_tb_emp_bias')
                                if _vm_emp and _vm_emp.get('baba_for_v') in _pmap.V_BABA_PATTERNS:
                                    _vm_baba_auto_idx = _pmap.V_BABA_PATTERNS.index(_vm_emp['baba_for_v'])
                                    _vm_baba_src = f"当日逆算({_vm_emp['lane_label']})"
                                else:
                                    try:
                                        import re as _vm_re
                                        _vm_hd_m = _vm_re.search(r'\d+', str(meta.get('holding_days', '') or ''))
                                        _vm_hd_n = int(_vm_hd_m.group()) if _vm_hd_m else 0
                                        _vm_cond = str(meta.get('condition', '') or '')
                                        if _vm_cond in ('重', '不良') or _vm_hd_n >= 7:
                                            _vm_baba_auto_idx = 2   # 外有利
                                        elif _vm_hd_n >= 5:
                                            _vm_baba_auto_idx = 1   # 中有利
                                    except Exception:
                                        _vm_baba_auto_idx = 0
                                # 内有利/中有利/外有利 のラベルだけ赤字に(キャプションは通常色)
                                st.markdown(
                                    "<style>.st-key-vm_baba div[role='radiogroup'] label "
                                    "div[data-testid='stMarkdownContainer'] p{color:#e03131 !important;"
                                    "font-weight:700;}</style>", unsafe_allow_html=True)
                                _VM_BABA_DISP = {'フラット': '内有利', '内2頭目まで荒れ': '中有利',
                                                 '内4頭目まで荒れ': '外有利'}
                                _vm_c1, _vm_c2 = st.columns(2)
                                with _vm_c1:
                                    _vm_baba = st.radio(
                                        f"馬場バイアス（自動推定:{_vm_baba_src}・変更可）",
                                        _pmap.V_BABA_PATTERNS, horizontal=True, key="vm_baba",
                                        index=_vm_baba_auto_idx,
                                        format_func=lambda x: _VM_BABA_DISP.get(x, x),
                                        captions=[
                                            "芝が傷んでおらず最短距離の内枠・先行が恵まれる（開幕週・コース替り直後）",
                                            "内2頭ぶんが荒れて遅い→そこを避けた中を通る馬が浮上（開催中盤）",
                                            "内4頭ぶんまで荒れ→外を回す差し・外枠が台頭（開催後半・雨後）",
                                        ],
                                        help="初期値は①当日の前半レース結果からの逆算バイアス（あれば最優先）、"
                                             "②無ければ開催日数・馬場状態（1〜4日目=フラット/5〜6日目=内2/7日目以上 or 道悪=内4）。"
                                             "前レースの体感と違えば手動で変更。",
                                    )
                                with _vm_c2:
                                    _vm_pace = st.radio(
                                        "想定ペース（展開分析から自動判定済み・変更可）",
                                        _pmap.V_PACE_PATTERNS,
                                        index=_pmap.V_PACE_PATTERNS.index(_vm_pace_auto),
                                        horizontal=True, key="vm_pace",
                                    )
                                _vm_fig, _vm_list = _pmap.build_v_matrix(
                                    _pm_horses, profiles=_pm_profiles,
                                    pace=_vm_pace, baba=_vm_baba,
                                )
                                if _vm_fig is not None:
                                    st.plotly_chart(_vm_fig, use_container_width=True, key="v_matrix_fig")
                                    if _vm_list:
                                        _vm_names = "・".join(
                                            f"{v['umaban']}番{v['name']}({v['style']})" for v in _vm_list
                                        )
                                        st.success(f"🏆 Vエリア該当馬: {_vm_names}")
                                    else:
                                        st.info("Vエリア（赤枠）にすっぽり収まる馬は不在。半端なポジションの馬が多く波乱の余地あり。")
                                    st.caption(
                                        "⚠ Vエリア＝展開で恵まれる『有利ポジション』の可視化（予想の地図）であって"
                                        "『買い』シグナルではありません。検証(scripts/tenkai_bias_backtest.py / "
                                        "tenkai_alert_backtest.py)で、展開恩恵・有利な枠/位置は人気にほぼ織込み済み"
                                        "（合致馬を買っても複勝残差≈0・ROI控除割れ／Vエリア×人気薄もむしろ過剰人気）。"
                                        "妙味は下の🔍末脚妙味アラート（人気薄×末脚＝検証済ROI約111%）と、"
                                        "エビデンス表の⚠危険人気馬（外有利日×内枠人気馬の逆張り消去）で拾う。"
                                    )

                                    # ── 🔍 末脚妙味アラート（検証済みエッジに貼り替え）──
                                    # 旧『展開妙味（展開向く×人気薄）』は検証(scripts/tenkai_alert_backtest.py)で否定。
                                    # 展開恩恵は人気に織込み済みで、向く×人気薄はむしろ過剰人気(複勝率9〜13%/残差負)。
                                    # 人気薄で実際に効くのは展開でなく"末脚"(verified_spurt_index: 人気薄6+×習性末脚上位=単ROI≈111%)。
                                    # 選別基準を『人気薄(≥6番人気) × 習性上がり3F上位33%』に変更。
                                    try:
                                        _pop_map = {}
                                        for _, _pr in df.iterrows():
                                            try:
                                                _pop_map[int(_pr['Umaban'])] = _pm_num(_pr.get('Popularity'))
                                            except Exception:
                                                pass
                                        _spurt = []
                                        for _h in (_pm_horses or []):
                                            _u = _h.get('umaban')
                                            _nm = _h.get('name', '')
                                            _prof = (_pm_profiles or {}).get(_nm) or {}
                                            _ag = _prof.get('agari')   # 習性上がり相対順位 0=最速(過去走・事前確定)
                                            _pop = _pop_map.get(_u)
                                            if (_ag is not None and _ag <= 0.33
                                                    and _pop is not None and _pop >= 6):
                                                _spurt.append((_u, _nm, _h.get('style', ''), _ag, _pop))
                                        if _spurt:
                                            _chips = ""
                                            for _u, _nm, _sty, _ag, _pop in sorted(_spurt, key=lambda m: m[3]):
                                                _agtxt = f"末脚 上位{int(round(_ag * 100))}%"
                                                _chips += (
                                                    f"<div style='display:flex;align-items:center;gap:10px;"
                                                    f"background:rgba(0,0,0,0.22);border-radius:8px;"
                                                    f"padding:8px 12px;margin:6px 0;'>"
                                                    f"<span style='font-size:22px;font-weight:900;color:#fff;'>{_u}</span>"
                                                    f"<span style='font-size:17px;font-weight:800;color:#fff;'>{_nm}</span>"
                                                    f"<span style='font-size:13px;color:#ffe9a8;'>{_sty}</span>"
                                                    f"<span style='margin-left:auto;font-size:13px;color:#cdebff;'>"
                                                    f"{_agtxt} ｜ {int(_pop)}番人気</span></div>")
                                            st.markdown(
                                                "<div style='background:linear-gradient(135deg,#1d3557,#2a9d8f);"
                                                "border:3px solid #ffd700;border-radius:14px;padding:16px 18px;"
                                                "margin:14px 0;box-shadow:0 0 22px rgba(42,157,143,0.55);'>"
                                                "<div style='font-size:22px;font-weight:900;color:#fff;"
                                                "letter-spacing:1px;'>🔍 末脚妙味アラート</div>"
                                                "<div style='font-size:13px;color:#ffe;margin:4px 0 10px;'>"
                                                "<b>人気薄(6番人気以下)×習性の上がり3F上位</b>＝市場が過小評価しがちな差し脚。"
                                                "複勝・ワイド・3連複の押さえ向き。</div>"
                                                f"{_chips}"
                                                "<div style='font-size:11px;color:#ffd;margin-top:8px;'>"
                                                "※検証(2024-25)=人気薄6+×末脚上位33%で単回収率約111%(母集団71%超)。"
                                                "旧『展開が向く×人気薄』は検証で否定(過剰人気)のため末脚基準に変更済み。</div></div>",
                                                unsafe_allow_html=True,
                                            )
                                        else:
                                            st.caption("🔍 末脚妙味アラート: 該当なし（人気薄かつ習性の上がり3F上位の馬は不在）。")
                                    except Exception as _my_e:
                                        st.caption(f"末脚妙味判定: {_my_e}")
                                    st.caption(
                                        "縦=隊列位置（テンの位置取り実データ）、横=想定の通り（枠順＋脚質から推定）。"
                                        "金縁の馬がVエリア該当。スロー→前有利 / ハイ→後方有利、馬場が荒れるほど外有利。"
                                    )
                            else:
                                st.caption("出走馬データが不足しているため展開マップを描画できません。")
                        except Exception as _pm_e:
                            st.caption(f"展開マップ: {_pm_e}")

                    st.divider()

                    # --- ⏱️ 調教（追い切り）分析 ---
                    with st.expander("⏱️ 調教（追い切り）分析", expanded=False):
                        # 全頭の調教評価ランク＋短評を netkeiba(type=3)から1発取得しキャッシュ
                        _oik_key = f"oikiri_rev_{race_id_input}"
                        _oc1, _oc2 = st.columns([3, 1])
                        with _oc1:
                            st.caption("netkeiba 調教ページから全頭の評価ランク＋短評を取得（木・金更新）。"
                                       "時計（ラップ/コース/分所/脚色）はnetkeiba無料公開分の馬のみ表示されます。")
                        with _oc2:
                            if st.button("🔄 調教を取得", key=f"btn_oik_{race_id_input}"):
                                with st.spinner("調教（評価・短評・時計）を取得中..."):
                                    try:
                                        from core import oikiri as _oik
                                        st.session_state[_oik_key] = _oik.fetch_oikiri_reviews(race_id_input)
                                        st.session_state[_oik_key + '_det'] = _oik.fetch_oikiri_detail(race_id_input)
                                    except Exception as _e:
                                        st.session_state[_oik_key] = {}
                                        st.session_state[_oik_key + '_det'] = {}
                                        st.warning(f"取得失敗: {_e}")
                                st.rerun()
                        _rev_map = st.session_state.get(_oik_key, {}) or {}
                        _det_map = st.session_state.get(_oik_key + '_det', {}) or {}
                        _cy_sort = 'Projected Score' if 'Projected Score' in df.columns else 'BattleScore'
                        _has_train = (('TrainingScore' in df.columns and
                                       pd.to_numeric(df['TrainingScore'], errors='coerce').fillna(0).abs().sum() > 0)
                                      or ('TrainingEval' in df.columns and
                                          df['TrainingEval'].astype(str).str.strip().ne('').any()))
                        if not _has_train and not _rev_map:
                            st.info("調教データ未取得です。上の『🔄 全頭の短評を取得』を押すか、netkeiba の調教（追い切り）ページから取得します。"
                                    "調教は週後半（木・金）に更新されるため、発走が近づいてから取得すると評価が入ります。")
                        else:
                            st.caption("netkeiba の調教ページ（追い切り）より取得。評価A〜D＝netkeiba 調教評価。"
                                       "検証(下記)の結果、調教評価の予測ボーナスは既定で0（表示・参考用）にしています。")
                            _grade_from = {100.0: 'A', 70.0: 'B', 40.0: 'C', 10.0: 'D'}
                            _cy_rows = []
                            for _, _r in df.sort_values(_cy_sort, ascending=False).iterrows():
                                try:
                                    _u = int(_r['Umaban'])
                                except Exception:
                                    continue
                                _ts = pd.to_numeric(_r.get('TrainingScore'), errors='coerce')
                                _ev = str(_r.get('TrainingEval', '') or '').strip()
                                if not _ev and pd.notnull(_ts):
                                    _ev = _grade_from.get(float(_ts), '')
                                _rev = _rev_map.get(_u, {})
                                if (not _ev) and _rev.get('rank'):
                                    _ev = _rev['rank']
                                _row = {
                                    '馬番': _u, '馬名': str(_r.get('Name', '')),
                                    '人気': _r.get('Popularity', '-'),
                                    '調教評価': _ev or '-',
                                    '短評': _rev.get('critic', '') or '-',
                                }
                                _cy_rows.append(_row)
                            _cy_df = pd.DataFrame(_cy_rows)
                            # 全頭が空(未取得)の列は落としてスカスカ表示を防ぐ
                            for _c in list(_cy_df.columns):
                                if _c not in ('馬番', '馬名', '人気') and \
                                   _cy_df[_c].astype(str).str.strip().isin(['', '-']).all():
                                    _cy_df = _cy_df.drop(columns=[_c])

                            def _cy_color(v):
                                return ('background-color:#2b8a3e;color:white;font-weight:bold' if v == 'A'
                                        else 'background-color:#f4a261;font-weight:bold' if v == 'B'
                                        else 'color:#999' if v in ('C', 'D') else '')
                            try:
                                _sty = _cy_df.style
                                if '調教評価' in _cy_df.columns:
                                    _sty = _sty.applymap(_cy_color, subset=['調教評価'])
                                st.dataframe(_sty, hide_index=True, use_container_width=True)
                            except Exception:
                                st.dataframe(_cy_df, hide_index=True, use_container_width=True)
                            if '短評' not in _cy_df.columns and not _rev_map:
                                st.caption("↑『🔄 調教を取得』を押すと全頭の評価ランク＋短評が入ります。")
                            _cy_a = [r for r in _cy_rows if r['調教評価'] == 'A']
                            if _cy_a:
                                st.info("調教評価A(参考): "
                                        + " / ".join(f"{r['馬番']}{r['馬名']}" for r in _cy_a)
                                        + "　※Aは検証で有意な妙味なし・買い材料ではありません")
                            # 追い切り時計(netkeiba無料公開分=数頭のみ)を別表で表示
                            if _det_map:
                                _t_rows = []
                                for _, _r2 in df.sort_values(_cy_sort, ascending=False).iterrows():
                                    try:
                                        _u2 = int(_r2['Umaban'])
                                    except Exception:
                                        continue
                                    _d = _det_map.get(_u2)
                                    if not _d or not (_d.get('time_str') or _d.get('course')):
                                        continue
                                    _t_rows.append({
                                        '馬番': _u2, '馬名': str(_r2.get('Name', '')),
                                        '日付': _d.get('date', '') or '-',
                                        'コース': (str(_d.get('course', '') or '') + ' '
                                                  + str(_d.get('baba', '') or '')).strip() or '-',
                                        '乗り役': _d.get('rider', '') or '-',
                                        '時計(ラップ)': _d.get('time_str', '') or '-',
                                        '分所': _d.get('ichi', '') or '-',
                                        '脚色': _d.get('load', '') or '-',
                                    })
                                if _t_rows:
                                    st.markdown("**🕐 追い切り時計（netkeiba無料公開分のみ）**")
                                    st.dataframe(pd.DataFrame(_t_rows), hide_index=True, use_container_width=True)
                                    st.caption("netkeibaは無料では上位数頭の時計のみ公開（残りは非公開）。"
                                               "※調教時計は検証で『速い時計＝過剰人気』のため参考用です。")
                            st.caption("※検証(中央重賞2021–2025・9,092頭): 調教評価の3着内残差は A=+0.009(z+0.55, 有意でない)、"
                                       "B=−0.016(z−3.6), C=−0.023(z−3.3)＝B/Cは有意に過剰人気。よって調教評価の予測ボーナスは0に降格（表示・参考用）。")

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
                                   ("⏱️ 調教%(検証=予測力なし)", "Training", "trn"),
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
                        # 🔄 自動保存: 影響率を変更したら即ファイルへ書き込み（手動保存ボタン不要・次回起動時に自動復元）
                        try:
                            import json as _json_auto
                            _sw_sig = _json_auto.dumps(sw, sort_keys=True)
                            if st.session_state.get('_sw_saved_sig') != _sw_sig:
                                with open(_WEIGHTS_FILE, 'w', encoding='utf-8') as _wf:
                                    _json_auto.dump(sw, _wf, ensure_ascii=False, indent=2)
                                st.session_state['_sw_saved_sig'] = _sw_sig
                        except Exception:
                            pass
                        st.caption("💾 影響率は変更すると自動保存され、次回起動時に復元されます（血統7.00等もそのまま）。")
                        _sc1, _sc2 = st.columns([1, 1])
                        with _sc1:
                            if st.button("💾 影響率を保存（全レースに適用）", key="btn_save_weights_main_sp"):
                                import json as _json
                                try:
                                    with open(_WEIGHTS_FILE, 'w', encoding='utf-8') as _wf:
                                        _json.dump(sw, _wf, ensure_ascii=False, indent=2)
                                    st.session_state['_sw_saved_sig'] = _json.dumps(sw, sort_keys=True)
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

                        # ── 検証済みストレス（リーク無し・事前確定データのみ。🧪Stress Analystと同一基準）──
                        # 旧条件A(ダ内枠後方)/B(奇数枠逃げ)/D(長ダ内枠)は結果脚質リーク or 織込み済みで否定→撤去。
                        # ① 小柄馬×大幅馬体減：肉体ストレス(複勝残差-2.0pp z=-3.0・事前確定)
                        if 0 < curr_w < 440 and w_diff_val <= -6:
                            multiplier -= 0.04
                            reasons.append("小柄馬×馬体減6kg超(検証-2.0pp)")
                        # ② 習性後方ぐせ×芝：揉まれ・展開待ち(複勝残差-1.5pp z=-3.0。ダートは非有意)
                        if "芝" in surface and avg_pos >= 7.5:
                            multiplier -= 0.03
                            reasons.append("芝×後方ぐせ(検証-1.5pp)")
                        # ③ 大幅馬体増：仕上がり/余分(複勝残差-1.0pp z=-3.1・軽微)
                        if w_diff_val >= 8:
                            multiplier -= 0.02
                            reasons.append("馬体増+8kg超(軽微-1.0pp)")

                        multiplier = max(multiplier, 0.85)
                        
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
                    # 新タブ化で別セッションになった🧹消去フィルターから採点を読めるようディスクにも保存
                    try:
                        from core import score_cache as _sc
                        _sc.write_scores(race_id_input, df)
                    except Exception:
                        pass
                    try:
                        df.to_csv(os.path.join(os.path.dirname(__file__), "debug_app_bonus.csv"), encoding="utf-8-sig", index=False)
                    except:
                        pass
                            
                    st.divider()

                    # --- 強適 Ranking Table ---
                    st.subheader("📊 強適 Ranking Table")
                    display_icon_legend()

                    from core import bloodline as _bl
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

                    # Format Bloodline (Sire / BMS + Impact + ダート血統ボーナス + 馬場シフト適性)
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

                        # 馬場シフト×血統フラグ（前日比クッション値 or ダート含水率）
                        if sire != '-':
                            _sf = _tb.sire_cushion_flag(sire, _tc_shift) if _tc_shift else None
                            if _sf:
                                base += f" {_sf['flag']}"
                            _dm = _tc_db.get('dirt_moisture')
                            if _dm and 'ダ' in _tb_surf:
                                _df = _tb.dirt_moisture_bloodtype(sire, _dm)
                                if _df:
                                    base += f" {_df['flag']}"

                        # 血統辞書の複勝率/回収率は別列(BloodStats)へ分離(緑色表示するため)
                        return base

                    def fmt_blood_stats(row):
                        """父×条件の複勝率/回収率を別列に短縮表示（緑色用）。"""
                        def _clean(v):
                            s = str(v) if v is not None else '-'
                            return '-' if s in ('nan', 'NaN', 'None', '不明', '', '-') else s
                        sire = _clean(row.get('sire'))
                        if sire == '-':
                            return ''
                        _ss = _bl.lookup_sire_stats(sire, _tb_surf, _tb_dist)
                        if not _ss:
                            return ''
                        _roi_i = '🔥' if _ss['win_roi'] >= 100 else ('💰' if _ss['win_roi'] >= 85 else '')
                        return f"複{_ss['place_rate']:.0f}%/回{_ss['win_roi']:.0f}%{_roi_i}"

                    view_df['Bloodline'] = view_df.apply(fmt_blood, axis=1)
                    view_df['BloodStats'] = view_df.apply(fmt_blood_stats, axis=1)
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

                    # --- 厩舎: ランク(全体3年勝率)＋当コース3年勝率 を Trainer列に追記 ---
                    # 検証(scripts/trainer_backtest.py): 全体勝率は市場織込み済=妙味薄、
                    # 当コース(場×馬場)の高勝率(🔴≥20%/🟠≥14%)のみオッズ超の妙味あり。
                    _trc_key = f"trainer_course_{race_id_input}"
                    if _trc_key not in st.session_state:
                        _trc_map = {}
                        try:
                            from core import jockey_jv as _jjt
                            _trc_jyo = str(race_id_input)[4:6]
                            _trc_surf = '芝'
                            if 'CurrentSurface' in df.columns and not df.empty:
                                _trc_surf = str(df['CurrentSurface'].iloc[0])
                            try:
                                _min_year = str(int(str(race_id_input)[:4]) - 3)
                            except Exception:
                                _min_year = None
                            # 現走ブリンカー(出馬表B印) name->1/0
                            _bl_now = {}
                            if 'Blinker' in df.columns:
                                for _, _br in df.iterrows():
                                    try:
                                        if int(_br.get('Blinker', 0) or 0) == 1:
                                            _bl_now[str(_br.get('Name', ''))] = 1
                                    except Exception:
                                        pass
                            # 性別(SexAge) name->牝/牡/セ と 今回の月(RaceDate)
                            _sex_now = {}
                            if 'SexAge' in df.columns:
                                for _, _sr in df.iterrows():
                                    _sa = str(_sr.get('SexAge', '') or '')
                                    _sex_now[str(_sr.get('Name', ''))] = (
                                        '牝' if '牝' in _sa else '牡' if '牡' in _sa else 'セ')
                            _race_mo = 0
                            try:
                                _rd = re.sub(r'[^\d]', '', str(df['RaceDate'].iloc[0]))[:8] \
                                    if 'RaceDate' in df.columns and not df.empty else ''
                                if len(_rd) >= 6:
                                    _race_mo = int(_rd[4:6])
                            except Exception:
                                _race_mo = 0
                            for _nm in df['Name'].astype(str).unique():
                                _kt, _tc = _jjt.resolve_horse(_nm)
                                # 初ブリンカー: 現走B印かつ過去ブリンカー着用0回
                                _buri = False
                                if _bl_now.get(_nm) and _kt:
                                    _bh = _jjt.horse_blinker_history(_kt)
                                    if _bh and _bh.get('blinker_runs', 0) == 0:
                                        _buri = True
                                # 前走圧勝(着差≥1.0秒)＝軸選定の加点(verified_ohtani_trap)
                                _awm = None
                                if _kt:
                                    try:
                                        _awm = _jjt.horse_prev_win_margin(_kt)
                                    except Exception:
                                        _awm = None
                                # 季節フェード(検証: 牝×冬 z-4.6 / 牝×春 z-3.8 で有意に過剰人気)
                                _fade = ''
                                if _sex_now.get(_nm) == '牝':
                                    if _race_mo in (12, 1, 2):
                                        _fade = '♀冬'
                                    elif _race_mo in (3, 4, 5):
                                        _fade = '♀春'
                                if not _tc:
                                    _trc_map[_nm] = {'suffix': '', 'rank': '', 'buri': _buri,
                                                     'fade': _fade, 'awm': _awm}
                                    continue
                                _ov = _jjt.trainer_overall_winrate(_tc, min_year=_min_year)
                                _cs = _jjt.trainer_course_winrate(_tc, _trc_jyo, _trc_surf, min_year=_min_year)
                                _owr = _ov['win_rate'] if _ov and _ov.get('runs', 0) >= 30 else None
                                _rank = ('' if _owr is None else
                                         'A' if _owr >= 0.14 else 'B' if _owr >= 0.10
                                         else 'C' if _owr >= 0.07 else 'D')
                                if _cs and _cs.get('runs', 0) > 0:
                                    _cwr = _cs['win_rate']; _rn = _cs['runs']
                                    _mk = '🔴' if _cwr >= 0.20 else '🟠' if _cwr >= 0.14 else ''
                                    _cw_txt = f"{_cwr:.0%}{_mk}" + (f"({_rn})" if _rn >= 10 else f"({_rn}少)")
                                else:
                                    _cw_txt = '当ｺｰｽ-'
                                _suffix = f" {_rank or '?'}-{_cw_txt}"
                                _trc_map[_nm] = {'suffix': _suffix, 'rank': _rank,
                                                 'buri': _buri, 'fade': _fade, 'awm': _awm}
                        except Exception:
                            _trc_map = {}
                        st.session_state[_trc_key] = _trc_map
                    _tm = st.session_state.get(_trc_key, {})
                    if 'Trainer' in view_df.columns and _tm:
                        view_df['Trainer'] = view_df.apply(
                            lambda _r: str(_r.get('Trainer', '') or '')
                            + _tm.get(str(_r.get('Name', '')), {}).get('suffix', ''), axis=1)
                    # Alert列に注意フラグ追記(検証で過剰人気=妙味でなく注意材料)
                    #  ・初ブリ: 軽い過剰人気  ・牝×冬/春: 有意に過剰人気(フェード)
                    if 'Alert' in view_df.columns and _tm:
                        def _add_flags(_r):
                            _a = str(_r.get('Alert', '') or '')
                            _e = _tm.get(str(_r.get('Name', '')), {})
                            if _e.get('buri'):
                                _a = (_a + ' 🅑初ブリ').strip()
                            if _e.get('fade'):
                                _a = (_a + f" {_e['fade']}ﾌｪｰﾄﾞ").strip()
                            return _a
                        view_df['Alert'] = view_df.apply(_add_flags, axis=1)

                    # --- 🎯軸馬候補 ◎〇▲ (検証済み: 人気別複勝率 + 前走圧勝) ---
                    # 軸=3着内信頼度(複勝率)が高い人気馬。マークは最大3頭で迷わせない。
                    # core/axis_selector.py / 検証: verified_ohtani_trap, verified_legtype_axis
                    try:
                        from core import axis_selector as _axs
                        _ax_horses = []
                        for _, _dr in df.iterrows():
                            _nm = str(_dr.get('Name', '') or '')
                            _ax_horses.append({
                                'name': _nm, 'umaban': _dr.get('Umaban'),
                                'pop': _dr.get('Popularity'),
                                'odds': _dr.get('Odds'),
                                'prev_win_margin': _tm.get(_nm, {}).get('awm')})
                        _ax = _axs.axis_marks(_ax_horses)
                        _uma2mark = {}
                        for _h in _ax_horses:
                            _info = _ax.get(_h['name'], {})
                            _mk = _info.get('mark', '')
                            if not _mk:
                                continue
                            _conf = _info.get('conf')
                            _txt = _mk + (f" {_conf:.0f}%" if _conf is not None else '')
                            if _info.get('atsu'):
                                _txt += '🔨'  # 前走圧勝(着差≥1.0秒)＝過剰人気注意フラグ
                            try:
                                _uma2mark[int(_h['umaban'])] = _txt
                            except Exception:
                                pass
                        if _uma2mark and 'Umaban' in view_df.columns:
                            def _fmt_axis(_u):
                                try:
                                    return _uma2mark.get(int(_u), '')
                                except Exception:
                                    return ''
                            view_df['AxisMark'] = view_df['Umaban'].apply(_fmt_axis)
                    except Exception:
                        pass

                    # --- 🔵補正タイム列(過去走ベスト・フィールド内top3に🔵。検証:1-2番人気×top3で複勝+5.36pp=本命補強) ---
                    try:
                        from core import corrected_time as _cth
                        from core import jockey_jv as _jjh
                        _surf_h = str(df['CurrentSurface'].iloc[0]) if 'CurrentSurface' in df.columns and not df.empty else None
                        _ct_best = {}
                        for _, _rh in view_df.iterrows():
                            _uhn = pd.to_numeric(_rh.get('Umaban'), errors='coerce')
                            if pd.isnull(_uhn):
                                continue
                            _kth, _ = _jjh.resolve_horse(str(_rh.get('Name', '')))
                            _fg = _cth.get_figure(_kth, _surf_h) if _kth else None
                            _ct_best[int(_uhn)] = (_fg or {}).get('fig')
                        _ct_ranks = _cth.field_ranks(_ct_best)

                        def _ct_cell(_uu):
                            _b = _ct_best.get(_uu)
                            if _b is None:
                                return '-'
                            return ('🔵' if _ct_ranks.get(_uu, 99) <= 3 else '') + _cth.fmt_t100(_b)
                        view_df['CorrectedT'] = view_df['Umaban'].apply(
                            lambda u: _ct_cell(int(pd.to_numeric(u, errors='coerce')))
                            if pd.notnull(pd.to_numeric(u, errors='coerce')) else '-')
                    except Exception:
                        pass

                    # Merge previous screenshot columns with latest advanced columns
                    # --- v2.02: 展開データ列を追加 ---
                    cols = ['Rank', 'Umaban', 'Waku', 'Popularity', 'Odds', 'Name', 'AxisMark', 'Jockey', 'Signal',
                            'Projected Score', 'BattleScore', 'CorrectedT', 'AvgPosition',
                            'DeployScoreLabel', 'PCILabel', 'Pos600m', 'FrontCollapseEffect',
                            'DensityPenaltyLabel',
                            'OddsGap', 'Stress', 'SexAge', 'WeightHistory', 'WeightCarried',
                            'Trainer', 'Bloodline', 'BloodStats', 'JockeyChange',
                            'ボーナス詳細', 'AvgPCI', 'PCIType', 'DensityScore',
                            'NIndex', 'Strength (X)', 'Suitability (Y)',
                            'SpeedIndex', 'AvgAgari', 'Alert', 'RiskFlags']
                    view_df = view_df[[c for c in cols if c in view_df.columns]]

                    # --- Column order persistence (user_prefs.json) ---
                    # 注意: 保存先は必ずアプリ本体と同じフォルダに固定する。
                    # 以前は os.getcwd() を使っていたため、Streamlitを別ディレクトリから
                    # 起動すると保存ファイルを読めず「設定しても全列に戻る」不具合が出ていた。
                    import json as _json_sra
                    _prefs_path_sra = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), "user_prefs.json")
                    _saved_sra = []
                    _has_saved_sra = False  # キーが存在するか（空保存=全解除 と 未保存 を区別）
                    try:
                        with open(_prefs_path_sra, 'r', encoding='utf-8') as _f:
                            _prefs_loaded_sra = _json_sra.load(_f)
                        if 'single_race_col_order' in _prefs_loaded_sra:
                            _has_saved_sra = True
                            _saved_sra = _prefs_loaded_sra.get('single_race_col_order') or []
                    except Exception:
                        pass
                    
                    # 注: 以前はStress/Waku/Signal等の新列を保存済み順に強制再挿入していたが、
                    # 「外したはずの列が復活する＝保存されていない」と誤認される原因だったため廃止。
                    # 新列はデフォルト非表示とし、ユーザーが⚙列順設定で選んだものだけを尊重する。

                    _all_cols = list(view_df.columns)

                    _col_label_map = {
                        "Rank": "順位", "Umaban": "馬番", "Popularity": "人気",
                        "Odds": "単勝オッズ", "OddsGap": "オッズ断層",
                        "SexAge": "性別/年齢", "WeightHistory": "当日馬体重(増減)",
                        "WeightCarried": "斤量", "Trainer": "厩舎(ﾗﾝｸ-当ｺｰｽ勝率)",
                        "Bloodline": "血統(父/母父)", "BloodStats": "🧬血統実績(複/回)",
                        "Jockey": "騎手",
                        "JockeyChange": "乗替", "Name": "馬名",
                        "Signal": "🔬シグナル",
                        "AxisMark": "🎯軸馬候補",
                        "Projected Score": "⭐予測スコア", "CorrectedT": "🔵補正T", "ボーナス詳細": "ボーナス内訳", "NIndex": "N指数",
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

                    # アプリ本来の既定列順（「デフォルト」ボタンの戻し先）
                    _canonical_default = _all_cols[:]
                    # 初期表示に使う列順 = 保存があればそれを尊重（空保存=全解除も尊重）、
                    # 未保存(キー無し)のときだけアプリ既定（全列）。
                    if _has_saved_sra:
                        _default_cols = [c for c in _saved_sra if c in _all_cols]
                    else:
                        _default_cols = _canonical_default[:]

                    _display_to_col = {_col_label_map.get(c, c): c for c in _all_cols}
                    _col_to_display = {c: _col_label_map.get(c, c) for c in _all_cols}
                    _all_display = [_col_to_display[c] for c in _all_cols]
                    _default_display = [_col_to_display[c] for c in _default_cols]

                    # ── 展開フィルター（廃止）────────────────────────────── #
                    # 旧『好位妙味ゾーンで絞ると複勝+2.4pp』は大標本の再検証で否定された:
                    #   scripts/tenkai_alert_backtest.py(2024-25/360R)=展開恩恵は全帯で複勝残差≈0〜負
                    #   (好位中帯 n=1310 で-0.44pp/z=-0.39)。+2.4pp は小標本(n=466/z=1.25)のノイズだった。
                    # 展開恩恵は人気に織込み済みで妙味選別に使えないためフィルターを撤去。
                    # 人気薄の妙味は『展開マップ→🔍末脚妙味アラート』(検証済み末脚エッジ)を参照。
                    if '_pm_ctx' in dir() and _pm_ctx and _pm_ctx.get('pos4'):
                        st.caption("🚦 展開フィルターは廃止（展開恩恵での妙味絞りは検証で否定＝人気に織込み済み）。"
                                   "人気薄の妙味は展開マップの『🔍末脚妙味アラート』(検証済み末脚エッジ)を参照。")
                    # ─────────────────────────────────────────────────────── #

                    # ── 列順設定（チェック式）─────────────────────────── #
                    # チェックした列だけを表示。チェックした順に左から並べる。
                    # 永続化は「💾保存」「デフォルト」「全解除」を押した時だけ user_prefs.json へ書く。
                    # （毎回保存は一時的な空状態で設定を上書きしてしまうため廃止）
                    _order_key = 'sra_col_checked_order'
                    _ck = lambda _c: f"sra_ck_{_c}"

                    def _persist_sra_order(_order):
                        """列順を user_prefs.json に保存。成功でTrue。"""
                        try:
                            try:
                                with open(_prefs_path_sra, 'r', encoding='utf-8') as _f:
                                    _p = _json_sra.load(_f)
                            except Exception:
                                _p = {}
                            _p['single_race_col_order'] = list(_order)
                            with open(_prefs_path_sra, 'w', encoding='utf-8') as _f:
                                _json_sra.dump(_p, _f, ensure_ascii=False, indent=2)
                            return True
                        except Exception:
                            return False

                    # 初回のみ保存済み(=_default_cols)からチェック状態を初期化
                    if _order_key not in st.session_state:
                        _init_order = [c for c in _default_cols if c in _all_cols]
                        st.session_state[_order_key] = _init_order
                        for c in _all_cols:
                            st.session_state[_ck(c)] = (c in _init_order)
                    else:
                        # 後から登場した列のチェック状態を補完する。
                        # ・保存済み設定に含まれる列が後から現れた場合は復元してON（取りこぼし防止）。
                        # ・保存に無い純粋な新列は既定OFF（保存済み設定を壊さない）。
                        for c in _all_cols:
                            if _ck(c) not in st.session_state:
                                if _has_saved_sra and c in _saved_sra:
                                    # 保存順に沿って正しい位置へ挿入してON
                                    st.session_state[_ck(c)] = True
                                    _ord = st.session_state.get(_order_key, [])
                                    if c not in _ord:
                                        _pos = _saved_sra.index(c)
                                        _ins = len(_ord)
                                        for _j, _ec in enumerate(_ord):
                                            if _ec in _saved_sra and _saved_sra.index(_ec) > _pos:
                                                _ins = _j
                                                break
                                        _ord.insert(_ins, c)
                                        st.session_state[_order_key] = _ord
                                # BloodStatsは旧Bloodline内の表示を分離した列。Bloodlineが表示中なら
                                # 情報欠落を防ぐため自動でその隣に表示する。
                                elif c == 'BloodStats' and st.session_state.get(_ck('Bloodline')):
                                    st.session_state[_ck(c)] = True
                                    _ord = st.session_state.get(_order_key, [])
                                    if 'BloodStats' not in _ord:
                                        if 'Bloodline' in _ord:
                                            _ord.insert(_ord.index('Bloodline') + 1, 'BloodStats')
                                        else:
                                            _ord.append('BloodStats')
                                        st.session_state[_order_key] = _ord
                                else:
                                    st.session_state[_ck(c)] = False

                    _tl_col1, _tl_col2 = st.columns([1, 4])
                    with _tl_col1:
                        with st.popover("⚙ 列順設定"):
                            st.caption("チェックした列だけ表示。チェックした順に左から並びます。"
                                       "変更したら **💾保存** を押すとこの端末に記憶されます（次回も復元）。")
                            _btn_c = st.columns(2)
                            # ボタンはチェックボックス生成前に session_state を更新する
                            if _btn_c[0].button("全解除", key="sra_ck_clear"):
                                for c in _all_cols:
                                    st.session_state[_ck(c)] = False
                                st.session_state[_order_key] = []
                                _persist_sra_order([])
                                st.toast("全列を非表示にして保存しました", icon="🗑️")
                            if _btn_c[1].button("デフォルト", key="sra_ck_reset"):
                                _dc = [c for c in _canonical_default if c in _all_cols]
                                for c in _all_cols:
                                    st.session_state[_ck(c)] = (c in _dc)
                                st.session_state[_order_key] = _dc
                                _persist_sra_order(_dc)
                                st.toast("デフォルト列順に戻して保存しました", icon="↩️")
                            st.divider()
                            _grid = st.columns(2)
                            for _i, c in enumerate(_all_cols):
                                with _grid[_i % 2]:
                                    st.checkbox(_col_to_display.get(c, c), key=_ck(c))
                            st.divider()
                            if st.button("💾 この列順を保存", key="sra_ck_save",
                                         type="primary", use_container_width=True):
                                _prev = st.session_state.get(_order_key, [])
                                _sel = [c for c in _prev if st.session_state.get(_ck(c))]
                                for c in _all_cols:
                                    if st.session_state.get(_ck(c)) and c not in _sel:
                                        _sel.append(c)
                                st.session_state[_order_key] = _sel
                                if _persist_sra_order(_sel):
                                    st.toast(f"列順を保存しました（{len(_sel)}列）✅", icon="💾")
                                else:
                                    st.toast("保存に失敗しました", icon="⚠️")
                    with _tl_col2:
                        csv = view_df.to_csv(index=False).encode('utf-8-sig')
                        st.download_button(
                            label="📥 CSV出力",
                            data=csv,
                            file_name=f"ranking_table_{race_id_input}.csv",
                            mime="text/csv",
                            key="btn_download_ranking_csv"
                        )

                    # チェック順を再構成（表示用・このセッション内で即反映）。保存はボタン時のみ。
                    _prev_order = st.session_state.get(_order_key, [])
                    _col_sel = [c for c in _prev_order if st.session_state.get(_ck(c))]
                    for c in _all_cols:
                        if st.session_state.get(_ck(c)) and c not in _col_sel:
                            _col_sel.append(c)
                    st.session_state[_order_key] = _col_sel

                    if _col_sel:
                        view_df = view_df[[c for c in _col_sel if c in view_df.columns]]
                    else:
                        # チェック0列＝意図的な全解除。全列に戻さず明示メッセージのみ。
                        st.info("⚙ 列順設定で表示する列が選ばれていません。"
                                "「⚙ 列順設定」→「デフォルト」で全列に戻せます。")
                        view_df = view_df.iloc[:, 0:0]

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
                        "Trainer": st.column_config.TextColumn(
                            "厩舎(ﾗﾝｸ-当ｺｰｽ勝率)",
                            help="ﾗﾝｸ=全体3年勝率(A≥14%/B≥10%/C≥7%/D)。"
                                 "当ｺｰｽ=今回の競馬場×馬場の3年勝率。🔴≥20%/🟠≥14%は検証で妙味あり(全体勝率は市場織込み済)。"),
                        "Bloodline": st.column_config.TextColumn("血統(父/母父)", width="large"),
                        "BloodStats": st.column_config.TextColumn("🧬血統実績(複/回)", width="small",
                                 help="父×今回条件(馬場/距離)の複勝率/単勝回収率(blood_dict.db)。🔥=回収率≥100% 💰=≥85%"),
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
                        "Alert": st.column_config.TextColumn(
                            "Alert",
                            help="💣/💀=危険人気馬(軸外し推奨) ／ ◎=軸候補 ／ ⏱️=時計注意 ／ "
                                 "🅑初ブリ=初ブリンカーで軽い過剰人気 ／ "
                                 "♀冬ﾌｪｰﾄﾞ=牝馬×12〜2月、♀春ﾌｪｰﾄﾞ=牝馬×3〜5月。"
                                 "牝馬は冬春に実力以上の人気を集めやすく(検証:牝×冬z-4.6/牝×春z-3.8)、"
                                 "人気のわりに走らない＝買うと損になりやすい注意フラグ(妙味なし・軸非推奨)。"),
                        "RiskFlags": st.column_config.TextColumn("不安要素"),
                        "AxisMark": st.column_config.TextColumn(
                            "🎯軸馬候補",
                            help="3着内信頼度の高い人気馬を◎〇▲(最大3頭)。%=推定複勝率(単勝オッズ別の実績ベース。"
                                 "オッズは人気順位より細かい軸指標)。🔨=前走を着差1.0秒以上で圧勝＝"
                                 "オッズ統制では複勝率-5〜11ppの過剰人気注意フラグ(加点ではない)。"
                                 "脚質/前走僅差負けは人気に織込み済のため不採用。"
                        ),
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
                                elif "💀" in str(val): colors.append("background-color: #343a40; color: #ffd43b; font-weight: bold")
                                elif "◎" in str(val): colors.append("font-weight: bold; color: red")
                                elif "⏱️" in str(val): colors.append("font-weight: bold; color: gray")
                                elif "初ブリ" in str(val): colors.append("font-weight: bold; color: #e8590c")
                                elif "ﾌｪｰﾄﾞ" in str(val): colors.append("font-weight: bold; color: #1971c2")
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

                        def color_trainer(s):
                            """厩舎ランク(A-D)で文字色を変える。テキスト末尾の ' A-..' から判定。"""
                            _cmap = {
                                'A': "background-color:#e6f4ea; color:#1b5e20; font-weight:bold",
                                'B': "background-color:#fff8e1; color:#e65100; font-weight:bold",
                                'C': "color:#555",
                                'D': "color:#aaa",
                            }
                            out = []
                            for v in s:
                                m = re.search(r' ([A-D])-', str(v))
                                out.append(_cmap.get(m.group(1), '') if m else '')
                            return out
                        if 'Trainer' in view_df.columns:
                            styled_df = styled_df.apply(color_trainer, axis=0, subset=['Trainer'])

                        def color_bloodstats(s):
                            """血統実績(複/回)は緑文字で表示。空欄は無装飾。"""
                            return ["color:#2e7d32; font-weight:bold" if str(v).strip() else "" for v in s]
                        if 'BloodStats' in view_df.columns:
                            styled_df = styled_df.apply(color_bloodstats, axis=0, subset=['BloodStats'])
                        
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

                    # ── 🏇 騎手係数込み 総合スコア（J5・JRA-VAN検証ベース）──
                    try:
                        from core import jockey_jv as _j5
                        with st.expander("🏇 騎手係数込み 総合スコア（J5・黄金ライン/USMで補正）", expanded=False):
                            st.caption(_pub("強適スコア（馬の能力）に、JRA-VANで『人気以上に来る』と検証できた騎手要素"
                                       "（黄金ライン=騎手×調教師・USM=実力・場相性）を掛け合わせます。"
                                       "連敗・調子は予測力ゼロのため不使用。"))
                            _j5_w = st.slider("騎手影響率（0=馬のみ / 100=検証値どおり / 150=強調）",
                                              0, 150, 100, 10, key=f"j5_weight_{race_id_input}") / 100.0
                            # 期待値テーブル（USM較正用）をキャッシュ共有
                            if '_jj_expected' not in st.session_state:
                                st.session_state['_jj_expected'] = _j5.calibrate_odds_expectation()
                            _j5_exp = st.session_state['_jj_expected']
                            _j5_venue = _j5._venue_name(str(race_id_input)[4:6])
                            _j5_dist = meta.get('distance')
                            # 騎手係数(重み非依存)はレース単位でキャッシュ。スライダー操作を高速化。
                            _j5_key = f"_j5_mults_{race_id_input}"
                            if _j5_key not in st.session_state:
                                _mults = {}
                                for _, _r5 in df.iterrows():
                                    try:
                                        _u5 = int(_r5['Umaban'])
                                    except Exception:
                                        continue
                                    _fac = _j5.jockey_factor_by_name(
                                        str(_r5.get('Jockey', '')), str(_r5.get('Name', '')),
                                        venue=_j5_venue, distance=_j5_dist, expected=_j5_exp)
                                    _gold = _fac.get('gold')
                                    _gmk = ''
                                    if _gold:
                                        _gmk = "🥇🥇" if _gold['top2'] >= 0.40 else "🥇"
                                    _mults[_u5] = {'mult': _fac['mult'], 'note': _fac['note'], 'gold': _gmk}
                                st.session_state[_j5_key] = _mults
                            _mults = st.session_state[_j5_key]

                            _j5_rows = []
                            _base_rank = {}
                            _df_sorted = df.sort_values('Projected Score', ascending=False).reset_index(drop=True)
                            for _i, _rr in _df_sorted.iterrows():
                                _base_rank[int(_rr['Umaban'])] = _i + 1
                            for _, _rr in df.iterrows():
                                try:
                                    _u5 = int(_rr['Umaban'])
                                except Exception:
                                    continue
                                _ps = float(pd.to_numeric(_rr.get('Projected Score'), errors='coerce') or 0)
                                _mi = _mults.get(_u5, {'mult': 1.0, 'note': '-', 'gold': ''})
                                _adj = 1.0 + _j5_w * (_mi['mult'] - 1.0)
                                _j5_rows.append({
                                    '馬番': _u5, '馬名': str(_rr.get('Name', '')),
                                    '騎手': str(_rr.get('Jockey', '')),
                                    '強適スコア': round(_ps, 1),
                                    '騎手係数': round(_adj, 3),
                                    '黄金ライン': _mi['gold'] or '-',
                                    '騎手込みスコア': round(_ps * _adj, 1),
                                    '内訳': _mi['note'],
                                    '_base': _base_rank.get(_u5, 99),
                                })
                            _j5_df = pd.DataFrame(_j5_rows).sort_values('騎手込みスコア', ascending=False).reset_index(drop=True)
                            _j5_df.insert(0, '騎手込み順位', range(1, len(_j5_df) + 1))
                            _j5_df['順位変動'] = _j5_df.apply(
                                lambda r: ('↑' + str(int(r['_base'] - r['騎手込み順位'])))
                                if r['_base'] - r['騎手込み順位'] > 0
                                else ('↓' + str(int(r['騎手込み順位'] - r['_base'])))
                                if r['_base'] - r['騎手込み順位'] < 0 else '→', axis=1)
                            _j5_df = _j5_df.drop(columns=['_base'])
                            st.dataframe(_j5_df, hide_index=True, use_container_width=True)
                            st.caption("『順位変動』は強適スコア順位からの変化（↑＝騎手で評価UP）。"
                                       "黄金ライン🥇🥇(連対40%+)の馬が騎手込みで上がってきたら妙味。"
                                       "騎手係数は検証で測ったエッジ強度に合わせた保守的設定（影響率100%が既定）。")
                    except Exception as _j5e:
                        st.caption(f"騎手係数込みスコア: {_j5e}")

                    # （✨ Index Analysis Chart は削除済み。altは後続の強適シートで使用）
                    import altair as alt

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
                    
                    # 消し推奨表示用に下位5頭名を算出（Direct Match Network / Recent Match History は削除）
                    _bm_sort = 'BattleScore' if 'BattleScore' in df.columns else df.columns[0]
                    _bm_sorted = df.sort_values(by=_bm_sort, ascending=False)
                    top_5_names = _bm_sorted.head(5)['Name'].tolist()
                    bot_5_names = _bm_sorted.tail(5)['Name'].tolist()

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
                    # =========================================================
                    # 🎯 3連複おすすめエンジン（統合版）
                    #   旧: 推奨買い目 / 3連複スペシャル / 中穴10点 / 中穴スナイパー を1本化
                    # =========================================================
                    from core import trio_engine as _te
                    import importlib as _il_te; _il_te.reload(_te)  # サブモジュール編集を即反映(再起動不要)
                    st.subheader("🎯 3連複おすすめエンジン")
                    st.caption("2パターンで相互補完。"
                               "【本線】人気上位2頭を必ず軸に＝鉄板(37%)+①人気2穴1(46%)を同時カバー＝検証83%(堅め・的中重視)。"
                               "【②穴妙味】本線が取りこぼす荒れレース(人気上位≤1×穴2頭)を狙う高配当狙い。"
                               "ただし盲目的な人気1-穴2は検証で最悪(的中15%/ROI60%)だったため、"
                               "穴は🔥末脚救出・妙味シグナルが鳴った馬を厚く選別する。")

                    _te_sort = 'Projected Score' if 'Projected Score' in df.columns else 'BattleScore'
                    _te_sorted = df.sort_values(_te_sort, ascending=False).reset_index(drop=True)
                    _te_choices = [f"[{int(r['Umaban']):02d}] {r['Name']}"
                                   for _, r in _te_sorted.iterrows() if pd.notnull(r['Umaban'])]

                    # --- 🎯 馬券フィルター用 検証エッジ/危険馬/穴セット(レース単位キャッシュ・全券種共有) ---
                    _aim_key = f"_aimsets_{race_id_input}"
                    if _aim_key not in st.session_state:
                        try:
                            from core import corrected_time as _ctf2
                            from core import jockey_jv as _jjf2
                            _surf_te = str(df['CurrentSurface'].iloc[0]) if 'CurrentSurface' in df.columns and not df.empty else '芝'
                            _baba_te = str(meta.get('condition', '') or '')
                            _ctfig_te = {}; _spurt_te = {}; _ana_te = set(); _danger_te = set()
                            for _, _rt in df.iterrows():
                                _utn = pd.to_numeric(_rt.get('Umaban'), errors='coerce')
                                if pd.isnull(_utn):
                                    continue
                                _ut = int(_utn)
                                _popt = pd.to_numeric(_rt.get('Popularity'), errors='coerce')
                                if pd.notnull(_popt) and _popt >= 6:
                                    _ana_te.add(_ut)
                                if pd.notnull(_popt) and _popt == 1 and (
                                        ('芝' in _surf_te and _baba_te in ('重', '不良')) or
                                        ('ダ' in _surf_te and _baba_te == '不良')):
                                    _danger_te.add(_ut)
                                _ktt, _ = _jjf2.resolve_horse(str(_rt.get('Name', '')))
                                if _ktt:
                                    _fg = _ctf2.get_figure(_ktt, _surf_te)
                                    if _fg and _fg.get('fig') is not None:
                                        _ctfig_te[_ut] = _fg['fig']
                                    _cx = _jjf2.horse_recent_context(_ktt)
                                    _si = (_cx or {}).get('spurt_index'); _srn = (_cx or {}).get('spurt_runs', 0)
                                    if _si is not None and _srn >= 2:
                                        _spurt_te[_ut] = _si
                            _edge_te = {u for u, r in _ctf2.field_ranks(_ctfig_te).items() if r <= 3}
                            _edge_te |= {u for u, _ in sorted(_spurt_te.items(), key=lambda x: -x[1])[:3]}
                            st.session_state[_aim_key] = {'edge': _edge_te, 'danger': _danger_te, 'ana': _ana_te}
                        except Exception:
                            st.session_state[_aim_key] = {'edge': set(), 'danger': set(), 'ana': set()}
                    _aim = st.session_state[_aim_key]

                    _c1, _c2, _c3, _c4 = st.columns(4)
                    with _c1:
                        _axis_mode = st.radio("軸モード", ['軸なし(自動)', '1軸', '2軸'], key='te_axis_mode')
                    with _c2:
                        _pattern = st.radio("狙うパターン", ['本線(人気2頭軸＝鉄板+①)', '②穴妙味狙い(人気-穴-穴)'],
                                            key='te_pattern_v3',
                                            captions=['堅め・的中重視(鉄板+①を83%カバー)',
                                                      '荒れ・高配当(本線が取りこぼす穴レース／🔥末脚救出等の妙味穴を厚く)'])
                    with _c3:
                        _n_points = st.selectbox("提案数", [5, 8, 10, 12, 15, 18, 20, 30, 50], index=2, key='te_npoints',
                                                 help="②穴妙味狙いは後半(16番目以降)の組に的中が出やすい傾向。点数を増やすと拾える反面、合成オッズ低下＝トリガミに注意。")
                    with _c4:
                        _budget = st.number_input("予算(円・任意)", min_value=0, max_value=200000,
                                                  value=0, step=500, key='te_budget')

                    _axis_umaban = []
                    if _axis_mode != '軸なし(自動)':
                        _max_ax = 2 if _axis_mode == '2軸' else 1
                        _axis_sel = st.multiselect(f"軸馬を{_max_ax}頭選択（スコア順）", _te_choices,
                                                   default=_te_choices[:_max_ax],
                                                   max_selections=_max_ax, key='te_axis_sel')
                        for _s in _axis_sel:
                            try:
                                _axis_umaban.append(int(_s[1:3]))
                            except Exception:
                                pass

                    _odk = f"sanrenpuku_odds_{race_id_input}"
                    if st.button("🎯 3連複オッズ取得・更新", key='te_fetch'):
                        with st.spinner("3連複オッズ取得中..."):
                            st.session_state[_odk] = scraper.fetch_sanrenpuku_odds(race_id_input)
                            st.rerun()
                    _odds_list = st.session_state.get(_odk)
                    _odds_map = _te.build_odds_map(_odds_list) if _odds_list else None
                    if not _odds_list:
                        st.info("📡 3連複オッズ未取得。発売後に「取得・更新」を押すと狙い目価格帯フィルタが効きます（今はスコア・人気のみで暫定提案）。")
                    else:
                        st.caption(f"オッズ取得済み（{len(_odds_list)}組）。狙い目価格帯でフィルタ中。")

                    _te_horses = []
                    for _, _r in df.iterrows():
                        try:
                            _u = int(_r['Umaban'])
                        except Exception:
                            continue
                        _pv = pd.to_numeric(_r.get('Popularity'), errors='coerce')
                        _te_horses.append({
                            'umaban': _u, 'name': str(_r.get('Name', '')),
                            'score': float(pd.to_numeric(_r.get(_te_sort), errors='coerce') or 0),
                            'pop': int(_pv) if pd.notnull(_pv) and _pv < 99 else None,
                            'alert': str(_r.get('Alert', '') or ''),
                        })
                    # --- 🧹消去フィルターで残した馬を自動取込＋その場で編集(使う馬を絞る) ---
                    _all_te_um = [h['umaban'] for h in _te_horses]
                    _te_name_m = {h['umaban']: h['name'] for h in _te_horses}
                    _keep_default = _all_te_um
                    _kept_src = ''
                    try:
                        from core import score_cache as _sck_r
                        _kept = _sck_r.read_keep(race_id_input)
                        if _kept:
                            _inter = [u for u in _all_te_um if u in _kept]
                            if len(_inter) >= 3:
                                _keep_default = _inter
                                _kept_src = f"（🧹消去で残した{len(_inter)}頭を自動取込）"
                    except Exception:
                        pass
                    # 列順設定と同じチェック式(popover内のチェックボックス2列)で「使う馬」を選ぶ
                    _uck = lambda u: f"te_use_ck_{race_id_input}_{u}"
                    _use_init_key = f"te_use_init_{race_id_input}"
                    _use_sig = (str(race_id_input), tuple(_keep_default))
                    if st.session_state.get(_use_init_key) != _use_sig:
                        _kd = set(_keep_default)
                        for u in _all_te_um:
                            st.session_state[_uck(u)] = (u in _kd)
                        st.session_state[_use_init_key] = _use_sig
                    with st.popover(f"🐎 使う馬を選ぶ{_kept_src}"):
                        st.caption("チェックした馬だけで3連複を組みます。🧹消去の残し馬は自動でON（同レースを消去側で確定した場合）。")
                        _ub1, _ub2 = st.columns(2)
                        if _ub1.button("全選択", key=f"te_use_all_{race_id_input}"):
                            for u in _all_te_um:
                                st.session_state[_uck(u)] = True
                        if _ub2.button("消去残しに戻す", key=f"te_use_reset_{race_id_input}"):
                            _kd = set(_keep_default)
                            for u in _all_te_um:
                                st.session_state[_uck(u)] = (u in _kd)
                        st.divider()
                        _ugrid = st.columns(2)
                        for _i, u in enumerate(_all_te_um):
                            with _ugrid[_i % 2]:
                                st.checkbox(f"{u} {_te_name_m.get(u, '')}", key=_uck(u))
                    _use_um = [u for u in _all_te_um if st.session_state.get(_uck(u))]
                    st.caption((f"🐎 使う馬 {len(_use_um)}頭: " + " / ".join(f"{u}{_te_name_m.get(u, '')}" for u in _use_um))
                               if _use_um else "🐎 使う馬: 未選択（全馬で計算）")
                    if len(_use_um) >= 3:
                        _te_horses = [h for h in _te_horses if h['umaban'] in set(_use_um)]
                    else:
                        st.caption("⚠ 3頭未満のため全馬で計算します。")
                    # 展開マップ連携: 旧『好位妙味ボーナス』は検証で否定(deploy_bonus_from_ctxは加点ゼロ化済み)。
                    # 展開恩恵は妙味でないため3連複加点には使わない。pace_ctxはペース強度ヒント(下)でのみ利用。
                    _pace_ctx = st.session_state.get(f'_pace_ctx_{race_id_input}')
                    _deploy_map = None
                    # 事前ペース強度ヒント（検証済: ハイ想定→荒れ寄り＝②妙味向き / スロー想定→堅め＝本線向き）
                    _pint = st.session_state.get(f'_pace_int_{race_id_input}')
                    if _pint and _pint.get('label'):
                        _pl = _pint['label']
                        if _pl in ('ハイ想定', 'ややハイ'):
                            st.info(f"🌀 **ハイペース想定**（テン速力z={_pint['z']:+.1f}／前方TOP3={_pint['pred_pace']}秒）＝差し台頭で荒れ寄り → **②穴妙味狙い向き**。"
                                    "※検証=ハイ予想は1番人気オッズ層を固定しても荒れ率↑(中程度のエッジ)。穴選別は🔥末脚シグナルで。")
                        elif _pl == 'スロー想定':
                            st.info(f"🏁 **スローペース想定**（テン速力z={_pint['z']:+.1f}）＝前残りで堅め → **本線（人気2頭軸）向き**。")
                        else:
                            st.caption(f"想定ペース強度: 標準（テン速力z={_pint['z']:+.1f}）")
                    _pat_key = {'本線(人気2頭軸＝鉄板+①)': '本線',
                                '②穴妙味狙い(人気-穴-穴)': '②妙味'}[_pattern]
                    _mode_key = {'軸なし(自動)': 'auto', '1軸': '1軸', '2軸': '2軸'}[_axis_mode]
                    _te_res = _te.recommend_trio(_te_horses, odds_map=_odds_map,
                                                 axis_umaban=_axis_umaban, axis_mode=_mode_key,
                                                 pattern=_pat_key, n_points=_n_points,
                                                 deploy_map=_deploy_map)
                    if _te_res['warning']:
                        st.warning(_te_res['warning'])
                    if _te_res['bets']:
                        # --- 🎯 当てにいく馬券フィルター(ソフト=並べ替え＋印): 共有セットで注釈 ---
                        try:
                            from core import bet_filter as _bf
                            import importlib as _il_bf; _il_bf.reload(_bf)
                            _te_res['bets'] = _bf.annotate_bets(
                                _te_res['bets'], edge_horses=_aim['edge'],
                                danger_horses=_aim['danger'], ana_set=_aim['ana'])
                            st.caption("🎯当て度＝狙い目価格帯＋穴脚の検証エッジ(🔵補正T/末脚top)で上位化、⚠は危険馬(重不良×1番人気)を含む組。"
                                       "削らず並べ替え＝当たる根拠のある組を上に。")
                        except Exception as _bfe:
                            st.caption(f"（馬券フィルター適用スキップ: {_bfe}）")
                        _alloc_mode = '均等買い'
                        if _budget:
                            _alloc_mode = st.radio("予算配分モード", ['均等買い', '払戻均等'], horizontal=True,
                                                   key='te_alloc',
                                                   help="均等買い=全点同額。払戻均等=オッズ逆比配分でどれが当たっても回収額が近づく。")
                        _alloc = _te.allocate_budget(_te_res['bets'], _budget, mode=_alloc_mode)
                        _te_rows = []
                        for _b in _te_res['bets']:
                            _od = _b['odds']
                            _row = {
                                '買い目': '-'.join(str(x) for x in _b['combo']),
                                '馬名': ' / '.join(_b['names']),
                                '人気構成': f"人{_b['pop_ana'][0]}穴{_b['pop_ana'][1]}",
                                'オッズ': f"{_od:.1f}倍" if _od else '-',
                                '🎯当て度': _b.get('aim_tag', ''),
                                '根拠': _b.get('aim_reason', '-'),
                                '狙い目': '🎯' if _b['in_band'] else '',
                                'スコア': _b['score'],
                            }
                            if _budget:
                                _row['購入額'] = f"¥{_b.get('stake', 0):,}"
                                _row['的中時払戻'] = f"¥{_b['payout_if_hit']:,}" if _b.get('payout_if_hit') else '-'
                                _row['トリガミ'] = '⚠️' if _b.get('toriga') else ''
                            _te_rows.append(_row)
                        st.dataframe(pd.DataFrame(_te_rows), hide_index=True, use_container_width=True)
                        _syn = _te_res['meta'].get('synthetic_odds')
                        _te_msg = f"計 {len(_te_res['bets'])}点"
                        if _syn:
                            _te_msg += f" / 合成オッズ約{_syn}倍"
                        if _budget:
                            _te_msg += f" / 投資¥{_alloc['total']:,}（{_alloc_mode}）"
                            _ntg = sum(1 for _b in _te_res['bets'] if _b.get('toriga'))
                            if _ntg:
                                _te_msg += f" ⚠️トリガミ目{_ntg}点(的中しても投資割れ)"
                        st.success(_te_msg)

                    # =========================================================
                    # 🎯 馬連 / 馬単 おすすめエンジン（3連複の代替・高配当検知）
                    #   近年は人気馬が3頭目に絡むと3連複が伸びず、2頭勝負の
                    #   馬連/馬単のほうが高配当のことが多い。それを検知＆提案する。
                    # =========================================================
                    st.divider()
                    st.subheader("🎯 馬連 / 馬単 おすすめエンジン")
                    st.caption("人気馬が3頭目に絡むと3連複は配当が伸びない。そんな時は2頭勝負の"
                               "馬連/馬単のほうが高配当のことが多い。同じ軸で馬連/馬単の買い目を提案し、"
                               "3連複より高配当になる組をハイライトする。")
                    from core import odds_arbitrage as _oarb2

                    _qe_default = 0
                    if _axis_umaban:
                        for _i, _ch in enumerate(_te_choices):
                            try:
                                if int(_ch[1:3]) == _axis_umaban[0]:
                                    _qe_default = _i
                                    break
                            except Exception:
                                pass
                    _qa1, _qa2, _qa3 = st.columns([2, 1, 1])
                    with _qa1:
                        _qe_axis_sel = st.selectbox("軸馬（1頭・スコア順）", _te_choices,
                                                    index=min(_qe_default, max(0, len(_te_choices) - 1)),
                                                    key='qe_axis')
                        try:
                            _qe_axis = int(_qe_axis_sel[1:3])
                        except Exception:
                            _qe_axis = None
                    with _qa2:
                        _qe_nopp = st.selectbox("相手頭数", [3, 4, 5, 6, 7, 8], index=3, key='qe_nopp')
                    with _qa3:
                        _qe_both = st.checkbox("馬単の裏も", value=False, key='qe_both',
                                               help="馬単は1着→2着が基本。裏(相手→軸)も提案に含める。")

                    _qek = f"qe_allodds_{race_id_input}"
                    if st.button("🎯 馬連/馬単/3連複オッズ取得・更新", key='qe_fetch'):
                        with st.spinner("馬連・馬単・3連複オッズ取得中..."):
                            st.session_state[_qek] = _oarb2.fetch_all_odds(
                                race_id_input, kinds=('quinella', 'exacta', 'trio'))
                            st.rerun()
                    _allo = st.session_state.get(_qek)
                    if not _allo:
                        st.info("📡 馬連/馬単オッズ未取得。発売後に「取得・更新」を押すと買い目と高配当検知が出ます。")
                    else:
                        _qmap = {k: v['odds'] for k, v in (_allo.get('quinella') or {}).items() if v.get('odds')}
                        _emap = {k: v['odds'] for k, v in (_allo.get('exacta') or {}).items() if v.get('odds')}
                        _tmap = {frozenset(k): v['odds'] for k, v in (_allo.get('trio') or {}).items() if v.get('odds')}
                        st.caption(f"取得済み：馬連{len(_qmap)}組 / 馬単{len(_emap)}組 / 3連複{len(_tmap)}組")
                        _pop_by_um = {h['umaban']: h['pop'] for h in _te_horses if h.get('pop')}

                        _qe = _te.recommend_quinella_exacta(
                            _te_horses, q_odds=_qmap, e_odds=_emap,
                            axis_umaban=_qe_axis, n_opp=_qe_nopp, both_dir=_qe_both)
                        # 🎯 当てにいく馬券フィルター(馬連/馬単にも横断適用・同じ共有セット)
                        try:
                            from core import bet_filter as _bfqe
                            _qe['quinella'] = _bfqe.annotate_bets(
                                _qe.get('quinella', []), edge_horses=_aim['edge'],
                                danger_horses=_aim['danger'], ana_set=_aim['ana'])
                            _qe['exacta'] = _bfqe.annotate_bets(
                                _qe.get('exacta', []), edge_horses=_aim['edge'],
                                danger_horses=_aim['danger'], ana_set=_aim['ana'])
                        except Exception:
                            pass

                        # --- 高配当検知（3連複 vs 馬連/馬単）---
                        _trio_src = [b['combo'] for b in _te_res['bets']] if _te_res.get('bets') else list(_tmap.keys())
                        _cmp_raw = _te.trio_vs_pair(_trio_src, _tmap, _qmap, _emap, pop_by_um=_pop_by_um)
                        _better = [r for r in _cmp_raw if r['better']]
                        if _better:
                            st.warning(f"💡 **馬連/馬単のほうが3連複より高配当の組が {len(_better)}件**"
                                       "（人気馬が3頭目に絡み、3連複の配当が伸びていないケース）")
                            _cmp_disp = [{
                                '3連複': '-'.join(str(x) for x in r['trio']),
                                '3連複ｵｯｽﾞ': f"{r['trio_odds']:.1f}倍",
                                '2頭(人気薄)': '-'.join(str(x) for x in r['pair']),
                                '馬連': f"{r['q_odds']:.1f}倍" if r['q_odds'] else '-',
                                '馬単(高い方)': f"{r['e_best']:.1f}倍" if r['e_best'] else '-',
                                '高配当側': r['better'],
                                '倍率': f"×{r['ratio']}" if r['ratio'] else '-',
                            } for r in _better[:8]]
                            st.dataframe(pd.DataFrame(_cmp_disp), hide_index=True, use_container_width=True)
                        else:
                            st.caption("（現状は3連複が同等以上。馬連/馬単での取り逃しはなし）")

                        # --- 馬連おすすめ ---
                        st.markdown("**馬連おすすめ**（軸 × 相手）")
                        _qe_qrows = [{
                            '買い目': '-'.join(str(x) for x in r['combo']),
                            '馬名': ' / '.join(r['names']),
                            '構成': r['pop_ana'],
                            'オッズ': f"{r['odds']:.1f}倍" if r['odds'] else '-',
                            '🎯当て度': r.get('aim_tag', ''),
                            '根拠': r.get('aim_reason', '-'),
                            '狙い目': '🎯' if r['in_band'] else '',
                        } for r in _qe['quinella']]
                        if _qe_qrows:
                            st.dataframe(pd.DataFrame(_qe_qrows), hide_index=True, use_container_width=True)

                        # --- 馬単おすすめ ---
                        st.markdown("**馬単おすすめ**（1着 → 2着）")
                        _qe_erows = [{
                            '買い目': '→'.join(str(x) for x in r['combo']),
                            '馬名': ' → '.join(r['names']),
                            '構成': r['pop_ana'],
                            'オッズ': f"{r['odds']:.1f}倍" if r['odds'] else '-',
                            '🎯当て度': r.get('aim_tag', ''),
                            '根拠': r.get('aim_reason', '-'),
                            '狙い目': '🎯' if r['in_band'] else '',
                        } for r in _qe['exacta']]
                        if _qe_erows:
                            st.dataframe(pd.DataFrame(_qe_erows), hide_index=True, use_container_width=True)
                        st.caption("構成: 人=1〜5番人気 / 中=6〜9 / 穴=10番人気〜。"
                                   "狙い目帯=馬連10〜120倍・馬単20〜250倍。")

                    st.divider()
            except Exception as e:
                import traceback
                st.error(f"An error occurred: {e}")
                st.exception(e)
                logger.error(f"Analysis Failed: {traceback.format_exc()}")

    # ============================================================
    # 💱 オッズ歪みスキャナー & 資金配分最適化 (β)
    # ============================================================
    st.divider()
    st.subheader("💱 オッズ歪みスキャナー & 資金配分最適化（β）")
    st.caption("全券種オッズを直前に取得し、券種間の歪み（馬連 vs 3連複 等）・最適資金配分・タテ目の抑えを自動提案します。オッズは締切直前に大きく動くため、発走5〜10分前の再取得を推奨。")

    from core import odds_arbitrage as _oarb

    _arb_key = f"all_odds_{race_id_input}"
    _arb_c1, _arb_c2 = st.columns([1, 2])
    with _arb_c1:
        if st.button("📡 全券種オッズを取得", key="btn_arb_fetch"):
            with st.spinner("単勝・複勝・馬連・ワイド・馬単・3連複・3連単を取得中..."):
                st.session_state[_arb_key] = _oarb.fetch_all_odds(race_id_input)
                st.session_state[_arb_key + "_at"] = pd.Timestamp.now().strftime("%H:%M:%S")
    with _arb_c2:
        if _arb_key in st.session_state:
            _ao = st.session_state[_arb_key]
            _cnt_txt = " / ".join(
                f"{_oarb.KIND_LABELS[k]}:{len(v)}" for k, v in _ao.items()
            )
            st.caption(f"取得時刻 {st.session_state.get(_arb_key + '_at', '-')} ｜ {_cnt_txt}")

    if _arb_key in st.session_state and not any(st.session_state[_arb_key].values()):
        st.info("⏳ オッズが取得できませんでした。発売中レース・確定済み過去レースは取得可能です。**発売前のレース**は発売開始後に再取得してください。")

    if _arb_key in st.session_state and any(st.session_state[_arb_key].values()):
        _ao = st.session_state[_arb_key]

        # 馬番→馬名マップ（解析済みdfがあれば使う）
        _arb_names = {}
        _df_arb = st.session_state.get('df')
        if _df_arb is not None and 'Umaban' in _df_arb.columns and 'Name' in _df_arb.columns:
            for _, _r in _df_arb.iterrows():
                try:
                    _arb_names[int(_r['Umaban'])] = str(_r['Name'])
                except Exception:
                    continue

        def _arb_nm(u):
            return f"{u} {_arb_names.get(u, '')}".strip()

        def _arb_combo_str(combo):
            return "-".join(str(x) for x in combo)

        # 出走馬番リスト（単勝オッズから）
        _arb_umas = sorted(c[0] for c in _ao.get('win', {}).keys())
        if not _arb_umas and _arb_names:
            _arb_umas = sorted(_arb_names.keys())

        _win_probs = _oarb.estimate_win_probs(_ao)

        _tab_dist, _tab_alloc, _tab_cover = st.tabs(["🔍 歪み検知", "💰 資金配分", "🛡️ 抑え提案"])

        # ───────── 歪み検知 ─────────
        with _tab_dist:
            # 全自動スキャン: 人気上位馬の全ペア×全比較を一括実行し歪みランキング表示
            st.markdown("**🔎 全自動歪みスキャン**（人気上位8頭の全組み合わせを一括チェック）")
            if st.button("🔎 歪みランキングを生成", key="btn_arb_autoscan"):
                st.session_state['arb_scan_result'] = _oarb.scan_all_distortions(_ao, top_k=8, min_advantage=0.10)
            _scan_res = st.session_state.get('arb_scan_result')
            if _scan_res is not None:
                if _scan_res:
                    _sc_rows = [
                        {"順位": _i + 1, "種別": _f_['category'],
                         "内容": _f_['description'],
                         "優位度": f"{_f_['advantage']:.0%}"}
                        for _i, _f_ in enumerate(_scan_res[:15])
                    ]
                    st.dataframe(pd.DataFrame(_sc_rows), hide_index=True, use_container_width=True)
                    _top_f = _scan_res[0]
                    st.success(f"🏆 **最大の歪み**: [{_top_f['category']}] {_top_f['description']}")
                else:
                    st.caption("10%以上の優位がある歪みは検出されませんでした（市場が効率的な状態）。")
            st.divider()

            if len(_arb_umas) >= 2:
                # デフォルト軸 = 人気上位2頭
                _pop_sorted = sorted(
                    _arb_umas,
                    key=lambda u: _ao['win'].get((u,), {}).get('odds', 9999.0)
                )
                _ax_sel = st.multiselect(
                    "軸2頭を選択（馬連 vs 3連複2頭軸 比較）",
                    _arb_umas, default=_pop_sorted[:2],
                    format_func=_arb_nm, key="arb_axis_pair", max_selections=2,
                )
                if len(_ax_sel) == 2:
                    _cmp = _oarb.compare_quinella_vs_trio_axis(_ao, _ax_sel[0], _ax_sel[1])
                    _m1, _m2, _m3 = st.columns(3)
                    _m1.metric(f"馬連 {_arb_combo_str(_cmp['pair'])}", f"{_cmp['quinella_odds']:.1f}倍" if _cmp['quinella_odds'] else "-")
                    _m2.metric(f"3連複2頭軸 合成 ({_cmp['trio_count']}点)", f"{_cmp['trio_synthetic']:.1f}倍" if _cmp['trio_synthetic'] else "-")
                    _m3.metric("ワイド（参考）", f"{_cmp['wide_odds']:.1f}倍" if _cmp['wide_odds'] else "-")
                    if _cmp['verdict'] == 'quinella':
                        st.warning(
                            f"💡 **馬連の方が得**: 3連複2頭軸総流し（合成 {_cmp['trio_synthetic']:.1f}倍）より "
                            f"馬連 {_arb_combo_str(_cmp['pair'])}（{_cmp['quinella_odds']:.1f}倍）の方が高効率です。"
                            f"相手を絞らないなら馬連1点が優位。"
                        )
                    elif _cmp['verdict'] == 'trio':
                        st.success(
                            f"💡 **3連複が優位**: 馬連（{_cmp['quinella_odds']:.1f}倍）より 3連複2頭軸の合成オッズ"
                            f"（{_cmp['trio_synthetic']:.1f}倍）が上回っています。総流しでも3連複に妙味。"
                        )
                    if _cmp['trio_sub']:
                        with st.expander("3連複2頭軸の内訳（相手別オッズ）", expanded=False):
                            _t_rows = [
                                {"組合せ": _arb_combo_str(c), "オッズ": f"{o:.1f}",
                                 "相手": _arb_nm([x for x in c if x not in _cmp['pair']][0])}
                                for c, o in sorted(_cmp['trio_sub'].items(), key=lambda x: x[1])
                            ]
                            st.dataframe(pd.DataFrame(_t_rows), hide_index=True, use_container_width=True)

                st.divider()
                # 単勝 vs 馬単
                _ax1 = st.selectbox(
                    "1着固定の軸（単勝 vs 馬単1着固定総流し 比較）",
                    _arb_umas, format_func=_arb_nm, key="arb_axis_single",
                )
                if _ax1:
                    _cw = _oarb.compare_win_vs_exacta_first(_ao, _ax1)
                    _n1, _n2 = st.columns(2)
                    _n1.metric("単勝", f"{_cw['win_odds']:.1f}倍" if _cw['win_odds'] else "-")
                    _n2.metric(f"馬単1着固定 合成 ({_cw['exacta_count']}点)", f"{_cw['exacta_synthetic']:.1f}倍" if _cw['exacta_synthetic'] else "-")
                    if _cw['verdict'] == 'win':
                        st.warning(f"💡 **単勝の方が得**: 馬単総流し合成（{_cw['exacta_synthetic']:.1f}倍）＜ 単勝（{_cw['win_odds']:.1f}倍）。2着を絞れないなら単勝1点。")
                    elif _cw['verdict'] == 'exacta':
                        st.success(f"💡 **馬単に妙味**: 馬単1着固定の合成（{_cw['exacta_synthetic']:.1f}倍）が単勝（{_cw['win_odds']:.1f}倍）を上回っています。")

                st.divider()
                # ───── 3連複 vs 3連単マルチ ─────
                st.markdown("**🎯 3連複 vs 3連単マルチ**（同じ3頭・同じ的中条件で、最も効率の良い1つの形を推奨。点数は増やしません）")
                _t3_pop_sorted = sorted(
                    _arb_umas,
                    key=lambda u: _ao['win'].get((u,), {}).get('odds', 9999.0)
                )
                _t3_sel = st.multiselect(
                    "3頭を選択", _arb_umas, default=_t3_pop_sorted[:3],
                    format_func=_arb_nm, key="arb_trio3", max_selections=3,
                )
                _t3_budget = st.number_input(
                    "資金（円・任意）", min_value=0, max_value=1000000, value=0, step=500,
                    key="arb_trio3_budget",
                    help="未入力（0）でもオッズ比較は動きます。入力すると推奨形での具体的な配分額を表示。",
                )
                if len(_t3_sel) == 3:
                    # 強適テーブル由来のモデル勝率（あれば）。なければ市場確率
                    _t3_score_col = None
                    _t3_probs = _win_probs
                    _t3_prob_src_label = "市場オッズ"
                    if _df_arb is not None:
                        for _cand in ['Projected Score', 'BattleScore', 'OguraIndex']:
                            if _cand in _df_arb.columns:
                                _t3_score_col = _cand
                                break
                    if _t3_score_col:
                        _t3_sc_map = {}
                        for _, _r in _df_arb.iterrows():
                            try:
                                _t3_sc_map[int(_r['Umaban'])] = float(_r[_t3_score_col])
                            except Exception:
                                continue
                        _t3_model = _oarb.estimate_win_probs_from_scores(_t3_sc_map, gamma=2.0)
                        if _t3_model:
                            _t3_probs = _t3_model
                            _t3_prob_src_label = f"強適テーブル（{_t3_score_col}）"

                    # 強適コンテキスト表（判断材料）
                    if _df_arb is not None and not _df_arb.empty:
                        _ctx_rows = []
                        for _u in sorted(_t3_sel):
                            _hit = _df_arb[pd.to_numeric(_df_arb.get('Umaban'), errors='coerce') == _u]
                            if _hit.empty:
                                continue
                            _h = _hit.iloc[0]
                            _ctx_rows.append({
                                "馬番": _u, "馬名": str(_h.get('Name', '')),
                                "人気": _h.get('Popularity', '-'),
                                "単勝": _ao['win'].get((_u,), {}).get('odds', '-'),
                                "💪強さX": round(float(_h.get('Strength (X)', 0)), 1) if 'Strength (X)' in _df_arb.columns else '-',
                                "🎯適性Y": round(float(_h.get('Suitability (Y)', 0)), 1) if 'Suitability (Y)' in _df_arb.columns else '-',
                                "スコア": round(float(_h.get(_t3_score_col, 0)), 1) if _t3_score_col else '-',
                                "モデル勝率": f"{_t3_probs.get(_u, 0):.0%}",
                            })
                        if _ctx_rows:
                            _ctx_cap = ""
                            if 'CurrentSurface' in _df_arb.columns and 'CurrentDistance' in _df_arb.columns:
                                try:
                                    _ctx_cap = f"コース: {_df_arb['CurrentSurface'].iloc[0]}{int(_df_arb['CurrentDistance'].iloc[0])}m ｜ "
                                except Exception:
                                    pass
                            st.caption(f"{_ctx_cap}確率根拠: {_t3_prob_src_label}")
                            st.dataframe(pd.DataFrame(_ctx_rows), hide_index=True, use_container_width=True)

                    _t3 = _oarb.compare_trio_vs_trifecta_multi(_ao, _t3_sel[0], _t3_sel[1], _t3_sel[2], win_probs=_t3_probs)
                    _t3m1, _t3m2, _t3m3 = st.columns(3)
                    _t3m1.metric("3連複 1点", f"{_t3['trio_odds']:.1f}倍" if _t3['trio_odds'] else "-")
                    _t3m2.metric("3連単マルチ 6点 合成", f"{_t3['multi_synthetic']:.1f}倍" if _t3['multi_synthetic'] else "-")
                    _t3_fx = _t3.get('fixed_best')
                    _t3m3.metric(
                        f"1着固定 2点 合成" + (f"（{_t3_fx['first']}番頭）" if _t3_fx else ""),
                        f"{_t3_fx['synthetic']:.1f}倍" if _t3_fx else "-",
                        f"モデル確信度 {_t3_fx['prob_share']:.0%}" if _t3_fx else None,
                    )
                    if _t3['verdict'] == 'trio':
                        st.warning(f"💡 **3連複1点を推奨**: {_t3['reasons'][0]}")
                    elif _t3['verdict'] == 'multi':
                        st.success(f"💡 **3連単マルチに歪み**: {_t3['reasons'][0]}")
                    elif _t3['verdict'] == 'fixed':
                        st.success(f"💡 **1着固定2点に絞るのが最効率**: {_t3['reasons'][0]}")
                    for _rs in _t3['reasons'][1:]:
                        st.caption(f"｜{_rs}")

                    # 資金入力時: 推奨形での具体的配分
                    if _t3_budget > 0 and _t3['verdict']:
                        if _t3['verdict'] == 'trio':
                            _t3_alloc = {_t3['combo']: _t3['trio_odds']}
                            _t3_kind_lbl = '3連複'
                        elif _t3['verdict'] == 'multi':
                            _t3_alloc = _t3['multi_perms']
                            _t3_kind_lbl = '3連単'
                        else:
                            _t3_alloc = _t3_fx['perms']
                            _t3_kind_lbl = '3連単'
                        _t3_rows, _t3_summ = _oarb.allocate_equal_payout(_t3_alloc, int(_t3_budget))
                        if _t3_rows:
                            st.markdown(f"**推奨形（{_t3_kind_lbl}）への配分** — 払戻均等:")
                            _t3_disp = [
                                {"買い目": ("-" if _t3['verdict'] == 'trio' else "→").join(str(x) for x in _r['combo']),
                                 "オッズ": f"{_r['odds']:.1f}",
                                 "購入額": f"{_r['stake']:,}円",
                                 "払戻": f"{_r['payout']:,}円",
                                 "損益": f"{_r['profit']:+,}円"}
                                for _r in _t3_rows
                            ]
                            st.dataframe(pd.DataFrame(_t3_disp), hide_index=True, use_container_width=True)
                            if _t3_summ.get('min_profit', 0) < 0:
                                st.warning("⚠️ この予算だと的中してもマイナスの目があります。予算を増やすか3連複1点へ。")
                elif _t3_sel:
                    st.caption("3頭ちょうど選択してください。")

                st.divider()
                # ワイド/馬連 逆転スキャン
                st.markdown("**📡 ワイド≒馬連 接近ペア自動スキャン**（ワイドが過剰においしいペア）")
                _inv = _oarb.scan_quinella_wide_inversion(_ao, min_ratio=0.80)
                if _inv:
                    _inv_rows = [
                        {"ペア": f"{_arb_nm(p['pair'][0])} × {_arb_nm(p['pair'][1])}",
                         "馬連": f"{p['quinella_odds']:.1f}", "ワイド": f"{p['wide_odds']:.1f}",
                         "ワイド/馬連比": f"{p['ratio']:.2f}"}
                        for p in _inv[:10]
                    ]
                    st.dataframe(pd.DataFrame(_inv_rows), hide_index=True, use_container_width=True)
                    st.caption("比率0.8以上＝3着内2頭でOKのワイドが、1-2着限定の馬連並みの配当。ワイド優位の歪み。")
                else:
                    st.caption("接近ペアなし（比率0.8以上が存在しません）")
            else:
                st.info("単勝オッズが取得できていません。再取得してください。")

        # ───────── 資金配分 ─────────
        with _tab_alloc:
            _al_c1, _al_c2, _al_c3 = st.columns(3)
            with _al_c1:
                _al_kind = st.selectbox(
                    "券種", ['quinella', 'wide', 'exacta', 'trio', 'win', 'place'],
                    format_func=lambda k: _oarb.KIND_LABELS[k], key="arb_alloc_kind",
                )
            with _al_c2:
                _al_budget = st.number_input("予算（円）", min_value=500, max_value=1000000, value=5000, step=500, key="arb_alloc_budget")
            with _al_c3:
                _al_mode = st.radio("配分ロジック", ["払戻均等（ガミり防止）", "期待値傾斜（簡易ケリー）"], key="arb_alloc_mode")

            # 確率ソース: アプリのスコア列があればモデル確率を使える
            # （市場オッズ由来の確率だとEV≒払戻率で一定になり期待値傾斜が機能しないため）
            _score_col = None
            if _df_arb is not None:
                for _cand in ['Projected Score', 'BattleScore', 'OguraIndex']:
                    if _cand in _df_arb.columns:
                        _score_col = _cand
                        break
            _prob_src = "市場オッズ（Harville）"
            if _al_mode.startswith("期待値傾斜"):
                _ps_opts = ["市場オッズ（Harville）"]
                if _score_col:
                    _ps_opts.insert(0, f"アプリスコア（{_score_col}）★推奨")
                _prob_src = st.radio(
                    "確率の根拠", _ps_opts, key="arb_prob_src", horizontal=True,
                    help="市場オッズ由来の確率は期待値がほぼ一定（=払戻率）になるため歪み検出に不向き。自前スコア由来の確率なら「市場とモデルの乖離=妙味」を突けます。",
                )

            _al_horses = st.multiselect(
                "対象馬を選択（選択馬同士の全組み合わせを生成）",
                _arb_umas, default=[], format_func=_arb_nm, key="arb_alloc_horses",
            )
            _need_n = {'win': 1, 'place': 1, 'quinella': 2, 'wide': 2, 'exacta': 2, 'trio': 3}[_al_kind]
            if len(_al_horses) >= _need_n:
                from itertools import combinations as _icomb, permutations as _iperm
                _kind_odds = _ao.get(_al_kind, {})
                if _need_n == 1:
                    _combos = [(u,) for u in _al_horses]
                elif _al_kind == 'exacta':
                    _combos = [tuple(c) for c in _iperm(_al_horses, 2)]
                else:
                    _combos = [tuple(sorted(c)) for c in _icomb(_al_horses, _need_n)]
                _sel_odds = {c: _kind_odds[c]['odds'] for c in _combos if c in _kind_odds and _kind_odds[c]['odds'] > 0}
                if _sel_odds:
                    if _al_mode.startswith("払戻均等"):
                        _rows, _summ = _oarb.allocate_equal_payout(_sel_odds, int(_al_budget))
                    else:
                        # 確率ソースに応じてベース勝率を切替
                        _base_probs = _win_probs
                        if _prob_src.startswith("アプリスコア") and _score_col and _df_arb is not None:
                            _sc_map = {}
                            for _, _r in _df_arb.iterrows():
                                try:
                                    _sc_map[int(_r['Umaban'])] = float(_r[_score_col])
                                except Exception:
                                    continue
                            _model_probs = _oarb.estimate_win_probs_from_scores(_sc_map, gamma=2.0)
                            if _model_probs:
                                _base_probs = _model_probs
                                st.caption(f"📐 {_score_col} 由来のモデル勝率を使用中（市場と乖離した買い目ほどEVが立ちます）")
                        _probs = {c: _oarb.combo_prob(_base_probs, c, _al_kind) for c in _sel_odds}
                        _rows, _summ = _oarb.allocate_ev_weighted(_sel_odds, _probs, int(_al_budget))
                    if _rows:
                        # EV列: モデル確率があれば払戻均等モードでも計算して常時表示
                        # (combos → probs は concierge用に後で計算するが、ここでは _rev_probs はまだない。
                        #  代わりに _rev_src を先に確定させる)
                        _ev_probs_pre = {}
                        if _score_col and _df_arb is not None:
                            _pre_sc_map = {}
                            for _, _rv in _df_arb.iterrows():
                                try:
                                    _pre_sc_map[int(_rv['Umaban'])] = float(_rv[_score_col])
                                except Exception:
                                    continue
                            _pre_mp = _oarb.estimate_win_probs_from_scores(_pre_sc_map, gamma=2.0)
                            if _pre_mp:
                                _ev_probs_pre = {c: _oarb.combo_prob(_pre_mp, c, _al_kind) for c in _sel_odds}
                        elif _win_probs:
                            _ev_probs_pre = {c: _oarb.combo_prob(_win_probs, c, _al_kind) for c in _sel_odds}

                        _disp = []
                        for _r in _rows:
                            _ev_val = _r['ev'] if 'ev' in _r else (
                                _ev_probs_pre.get(_r['combo'], 0) * _r['odds']
                                if _ev_probs_pre else None
                            )
                            _row_d = {
                                "買い目": _arb_combo_str(_r['combo']),
                                "オッズ": f"{_r['odds']:.1f}",
                                "購入額": f"{_r['stake']:,}円",
                                "払戻": f"{_r['payout']:,}円",
                                "損益": f"{_r['profit']:+,}円",
                            }
                            if _ev_val is not None:
                                _ev_str = f"{_ev_val:.2f}"
                                _row_d["期待値"] = f"⚠️{_ev_str}" if _ev_val < 1.0 else f"✅{_ev_str}"
                            _disp.append(_row_d)
                        _disp_df = pd.DataFrame(_disp)
                        st.dataframe(_disp_df, hide_index=True, use_container_width=True)
                        if any("⚠️" in str(r.get("期待値", "")) for r in _disp):
                            st.caption("⚠️=期待値1.0未満（モデルスコア基準）。長期回収率を下げる買い目です。")
                        _s1, _s2, _s3 = st.columns(3)
                        _s1.metric("合計投資", f"{_summ.get('total', 0):,}円")
                        _s2.metric("合成オッズ", f"{_summ.get('synthetic', 0):.2f}倍")
                        if 'min_profit' in _summ:
                            _s3.metric("最低損益（的中時）", f"{_summ['min_profit']:+,}円")
                        if _summ.get('synthetic', 0) and _summ['synthetic'] < 1.0:
                            st.error("⚠️ 合成オッズが1.0倍未満＝全的中でもマイナス（トリガミ確定）。点数を絞ってください。")
                        elif _summ.get('min_profit', 0) < 0 and 'min_profit' in _summ:
                            st.warning("⚠️ 一部の買い目はガミります（的中しても損益マイナス）。")
                        # 買い目シート出力（投票メモ用）
                        _sheet_txt = _oarb.build_bet_sheet_text(_rows, _al_kind)
                        _dl1, _dl2 = st.columns(2)
                        with _dl1:
                            st.download_button(
                                "📝 買い目シート (テキスト)", _sheet_txt,
                                file_name=f"bets_{race_id_input}_{_al_kind}.txt",
                                mime="text/plain", key="arb_dl_txt",
                            )
                        with _dl2:
                            _csv_df = pd.DataFrame([
                                {"券種": _oarb.KIND_LABELS[_al_kind],
                                 "買い目": "-".join(str(x) for x in _r['combo']),
                                 "オッズ": _r['odds'], "購入額": _r['stake'],
                                 "想定払戻": _r['payout']}
                                for _r in _rows
                            ])
                            st.download_button(
                                "📊 買い目CSV", _csv_df.to_csv(index=False).encode('utf-8-sig'),
                                file_name=f"bets_{race_id_input}_{_al_kind}.csv",
                                mime="text/csv", key="arb_dl_csv",
                            )

                        # ───── 🎩 コンシェルジュ診断 ─────
                        st.markdown("---")
                        st.markdown("**🎩 コンシェルジュ診断**（成功者の型: 点数を絞る・期待値プラスのみ・資金管理・見送りも戦略）")
                        _bk_in = st.number_input(
                            "総資金（円・任意）", min_value=0, max_value=100000000, value=0, step=10000,
                            key="arb_bankroll",
                            help="入力すると「1レースに資金の何%を投じているか」の資金管理診断が有効になります。",
                        )
                        # 診断用確率: モデルスコアがあれば常にモデル確率で評価
                        _rev_src = _win_probs
                        if _score_col and _df_arb is not None:
                            _rev_sc_map = {}
                            for _, _r in _df_arb.iterrows():
                                try:
                                    _rev_sc_map[int(_r['Umaban'])] = float(_r[_score_col])
                                except Exception:
                                    continue
                            _rev_mp = _oarb.estimate_win_probs_from_scores(_rev_sc_map, gamma=2.0)
                            if _rev_mp:
                                _rev_src = _rev_mp
                        _rev_probs = {c: _oarb.combo_prob(_rev_src, c, _al_kind) for c in _sel_odds}
                        _rev = _oarb.concierge_review(
                            _rows, _al_kind, combo_probs=_rev_probs,
                            budget=int(_al_budget), bankroll=int(_bk_in) if _bk_in else None,
                        )
                        _gr_color = {'S': '#FFD700', 'A': '#4CAF50', 'B': '#FF9800', 'C': '#F44336'}.get(_rev['grade'], '#888')
                        _gr_label = _rev.get('label', _rev['grade'])
                        st.markdown(
                            f"<div style='display:inline-block;padding:4px 16px;border-radius:8px;"
                            f"background:{_gr_color}22;border:2px solid {_gr_color};"
                            f"font-size:1.4em;font-weight:bold;color:{_gr_color};'>判定: {_gr_label}</div>",
                            unsafe_allow_html=True,
                        )
                        for _ad in _rev['advice']:
                            if _ad['level'] == 'bad':
                                st.error(f"{_ad['icon']} {_ad['msg']}")
                            elif _ad['level'] == 'warn':
                                st.warning(f"{_ad['icon']} {_ad['msg']}")
                            else:
                                st.success(f"{_ad['icon']} {_ad['msg']}")
                    else:
                        st.warning("予算が少なすぎて配分できません。")
                else:
                    st.warning(f"選択された組み合わせの{_oarb.KIND_LABELS[_al_kind]}オッズが取得できていません。")
            else:
                st.caption(f"{_oarb.KIND_LABELS[_al_kind]}には最低{_need_n}頭の選択が必要です。")

        # ───────── 抑え提案 ─────────
        with _tab_cover:
            st.markdown("**本線=軸2頭** が崩れた時（軸の片方が4着以下→相手同士で決着）のタテ目を、**元返し**（本線投資の回収）最小コストで提案します。")
            _cv_c1, _cv_c2 = st.columns(2)
            with _cv_c1:
                _cv_axis = st.multiselect(
                    "本線の軸2頭", _arb_umas,
                    default=st.session_state.get("arb_axis_pair", [])[:2],
                    format_func=_arb_nm, key="arb_cover_axis", max_selections=2,
                )
            with _cv_c2:
                _cv_total = st.number_input("本線の投資総額（円）", min_value=100, max_value=1000000, value=3000, step=100, key="arb_cover_total")
            _cv_partners = st.multiselect(
                "相手馬（この中の2頭で決着するケースを抑える）",
                [u for u in _arb_umas if u not in _cv_axis],
                format_func=_arb_nm, key="arb_cover_partners",
            )
            if len(_cv_axis) == 2 and len(_cv_partners) >= 2:
                _cv_rows = _oarb.suggest_protection(_ao, int(_cv_total), _cv_axis[0], _cv_axis[1], _cv_partners)
                if _cv_rows:
                    _cv_disp = [
                        {"タテ目（馬連）": f"{_arb_nm(_r['pair'][0])} × {_arb_nm(_r['pair'][1])}",
                         "オッズ": f"{_r['odds']:.1f}",
                         "必要購入額": f"{_r['stake']:,}円",
                         "払戻": f"{_r['payout']:,}円",
                         "本線比コスト": f"{_r['cost_ratio']:.0%}"}
                        for _r in _cv_rows
                    ]
                    st.dataframe(pd.DataFrame(_cv_disp), hide_index=True, use_container_width=True)
                    _best = _cv_rows[0]
                    st.info(
                        f"🛡️ 最安の抑え: 馬連 **{_arb_combo_str(_best['pair'])}** に **{_best['stake']:,}円** "
                        f"→ 的中時 {_best['payout']:,}円 払戻で本線investment（{_cv_total:,}円＋抑え分）を回収。"
                    )
                    _tot_cover = sum(_r['stake'] for _r in _cv_rows)
                    st.caption(f"全タテ目を抑える場合の合計: {_tot_cover:,}円（本線の{_tot_cover / max(_cv_total, 1):.0%}）。コストが本線の50%を超えるなら、本線の自信度を再考するサインです。")
                else:
                    st.warning("相手馬同士の馬連オッズが取得できていません。")
            else:
                st.caption("軸2頭と相手2頭以上を選択してください。")

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
    if 'kf_fetched_id' not in st.session_state:
        st.session_state['kf_fetched_id'] = None
    if 'kf_race_data' not in st.session_state:
        st.session_state['kf_race_data'] = None
    if 'kf_selected_rules' not in st.session_state:
        st.session_state['kf_selected_rules'] = {}
        
    packs = load_filter_packs()
    
    # --- 上部: レース検索カード ---
    st.markdown("### 🔍 レースを検索")

    # 🏠 Single Race Analysis と同じく、netkeiba の URL を貼っても 12桁レースIDを自動抽出する。
    if 'kf_race_id_box' not in st.session_state:
        st.session_state['kf_race_id_box'] = st.session_state['kf_race_id']

    def _on_kf_race_id_change():
        val = str(st.session_state.get('kf_race_id_box', '') or '')
        match = re.search(r'race_id=(\d{12})', val)
        if not match:
            match = re.search(r'(\d{12})', val)
        if match:
            extracted = match.group(1)
            if extracted != val:
                st.session_state['kf_race_id_box'] = extracted
                st.session_state['kf_race_id_extracted'] = True

    race_id_input = st.text_input(
        "netkeibaのレースIDを入力して Enter（URL貼り付けでもOK・出馬表を自動取得）",
        placeholder="例: 202405020611 / Netkeiba の URL をそのまま貼り付け",
        key="kf_race_id_box",
        on_change=_on_kf_race_id_change,
    )
    if st.session_state.get('kf_race_id_extracted', False):
        st.success("🔗 URLからレースIDを自動抽出しました！", icon="🔗")
        st.session_state['kf_race_id_extracted'] = False

    # レースID→Enter（入力変更）だけで自動取得。前回取得IDと違う時のみfetch（再取得ループ防止）。
    if race_id_input and race_id_input != st.session_state['kf_fetched_id']:
        st.session_state['kf_fetched_id'] = race_id_input
        st.session_state['kf_race_id'] = race_id_input
        with st.spinner("出馬データを取得中..."):
            try:
                df = scraper.get_race_data(race_id_input)
                if df is not None and not df.empty:
                    st.session_state['kf_race_data'] = df
                    st.success(f"レースデータを取得しました！ ({len(df)}頭)")
                else:
                    st.session_state['kf_race_data'] = None
                    st.error("データの取得に失敗しました。レースIDが正しいか、またはネットワーク環境を確認してください。")
            except Exception as e:
                st.session_state['kf_race_data'] = None
                st.error(f"エラーが発生しました: {e}")
                    
    if st.session_state['kf_race_data'] is not None:
        df = st.session_state['kf_race_data']
        metadata = df.attrs.get('metadata', {})


        # ===== 🎯 強適消去エンジン（検証済み）=====
        st.markdown("### 🎯 強適消去エンジン（検証済み）")
        st.caption("市場順位±検証済みファクター（黄金ライン/厩舎当コース＝＋、牝冬春/大幅距離変更/初ダート/前走フロック＝−）"
                   "で強適消去スコアを算出→下位半分を消去。消した中から妙味の穴1頭を救出し、危険な人気馬も検知します。"
                   "※俗説条件(前走着順/年齢/ローテ/血統等)は検証で過剰人気=非採用。回顧時は下の📝消去理由で残し学習を蓄積できます。")
        _ekey = f"kf_elim_{race_id_input}"
        _elim_clicked = st.button("▶ 強適消去エンジンを実行", key="kf_elim_run", type="primary")
        if _elim_clicked:
            st.session_state.pop(_ekey, None)  # 再クリックで再計算
        # 実行ボタンを押した時だけ計算（押すまでは走らせない）。一度押せばキャッシュで表示継続。
        if _elim_clicked:
            with st.spinner("検証ファクターを照合中..."):
                try:
                    from core import jockey_jv as _jj
                    from core import elim_reasons as _er
                    from core import corrected_time as _ct
                    from core import bet_optimizer as _bo
                    from core import score_cache as _sc2
                    # --- 確率列(単勝EV/複勝率/連対率)用: 🏠採点のProjected Scoreをディスクから取得 ---
                    _scache = _sc2.read_scores(race_id_input)
                    _score_by_um = {}
                    _odds_by_um = {}
                    if _scache:
                        for _, _rp in df.iterrows():
                            try:
                                _u = int(pd.to_numeric(_rp.get('Umaban'), errors='coerce'))
                            except Exception:
                                continue
                            _pj = (_scache.get(_u) or {}).get('proj')
                            _od = pd.to_numeric(_rp.get('Odds'), errors='coerce')
                            if _pj is not None:
                                _score_by_um[_u] = float(_pj)
                            if pd.notnull(_od) and _od > 0:
                                _odds_by_um[_u] = float(_od)
                    _winp = _bo.blended_win_probs(_score_by_um, _odds_by_um) if _score_by_um else {}
                    _all_um = list(_winp.keys())

                    def _top2_prob(wp, a, allu):
                        s = wp.get(a, 0.0)
                        for b in allu:
                            if b != a:
                                s += _bo._p2(wp, b, a)
                        return s
                    _jyo = str(race_id_input)[4:6]
                    _surf = str(df['CurrentSurface'].iloc[0]) if 'CurrentSurface' in df.columns and not df.empty else '芝'
                    # 馬場状態(重/不良)= 検証済み危険人気馬バイアス用(verified_heavy_track_bias)
                    _baba = str(metadata.get('condition', '') or '')
                    try:
                        _dist = int(pd.to_numeric(df['CurrentDistance'].iloc[0], errors='coerce'))
                    except Exception:
                        _dist = None
                    _dv = str(metadata.get('date_val', '') or '')
                    _mo = int(_dv[4:6]) if len(_dv) >= 6 and _dv[4:6].isdigit() else 0
                    _miny = str(int(_dv[:4]) - 3) if _dv[:4].isdigit() else None
                    # 🔥末脚救出の検証定義(scripts/spurt_index_backtest.py): 末脚指数の
                    # 『レース内top3(順位)』×人気≥6 → 複勝13.4%/ROI77.7%(ベース9.4%/66.4%)。
                    # 旧版は絶対値0.8で実質発火せず(実測の末脚指数は概ね-0.7〜+0.6で0.8未到達)。
                    # → 事前にフィールド内で末脚指数を順位付けし top3 の馬番集合を作る。
                    _spurt_rank = []
                    for _, _r0 in df.iterrows():
                        _kt0, _ = _jj.resolve_horse(str(_r0.get('Name', '')))
                        _c0 = _jj.horse_recent_context(_kt0) if _kt0 else None
                        _si0 = (_c0 or {}).get('spurt_index')
                        _sr0 = (_c0 or {}).get('spurt_runs', 0)
                        if _si0 is not None and _sr0 >= 2:
                            try:
                                _spurt_rank.append((int(_r0.get('Umaban')), float(_si0)))
                            except Exception:
                                pass
                    _spurt_top3 = {u for u, _ in sorted(_spurt_rank, key=lambda x: -x[1])[:3]}
                    _erows = []
                    for _, _r in df.iterrows():
                        _nm = str(_r.get('Name', ''))
                        try:
                            _um = int(_r.get('Umaban'))
                        except Exception:
                            _um = 0
                        _pop = pd.to_numeric(_r.get('Popularity'), errors='coerce')
                        _odds = pd.to_numeric(_r.get('Odds'), errors='coerce')
                        _jky = str(_r.get('Jockey', '') or '')
                        _sa = str(_r.get('SexAge', '') or '')
                        _kt, _tc = _jj.resolve_horse(_nm)
                        _g = _jj.jockey_trainer_combo(_jky, _tc) if _tc else None
                        _gold = bool(_g and _g.get('rides', 0) >= 10 and _g.get('top2', 0) >= 0.40)
                        _cs = _jj.trainer_course_winrate(_tc, _jyo, _surf, min_year=_miny) if _tc else None
                        _tcok = bool(_cs and _cs.get('runs', 0) >= 10 and (_cs.get('win_rate') or 0) >= 0.20)
                        _ctx = _jj.horse_recent_context(_kt) if _kt else None
                        _fade = ('牝' in _sa) and _mo in (12, 1, 2, 3, 4, 5)
                        _distchg = bool(_ctx and _ctx.get('prev_dist') and _dist and abs(_dist - _ctx['prev_dist']) >= 400)
                        _hatsud = ('ダ' in _surf) and bool(_ctx) and _ctx.get('dirt_runs', 0) == 0
                        _fluke = bool(_ctx and _ctx.get('prev_ninki') and _ctx.get('prev_chaku')
                                      and _ctx['prev_ninki'] >= 6 and _ctx['prev_chaku'] <= 3)
                        # --- 追加検証済み危険シグナル(scripts/dangerfav_backtest.py) ---
                        def _njk(s):
                            return ''.join(str(s or '').split())

                        def _same_jk(a, b):
                            return bool(a and b and (a == b or (len(a) >= 2 and len(b) >= 2
                                       and (a.startswith(b) or b.startswith(a)))))
                        _curj = _njk(_r.get('Jockey', ''))
                        _pvj = (_ctx or {}).get('prev_jockey')
                        _topswap = bool(_ctx and _pvj and _jj.jockey_is_top(_pvj)
                                        and not _same_jk(_curj, _njk(_pvj)))
                        _kinratio = False
                        try:
                            _fk = float(_r.get('WeightCarried'))
                            _bwm = re.match(r'(\d+)', str(_r.get('Weight', '')))
                            if _bwm and int(_bwm.group(1)) > 0 and _fk / int(_bwm.group(1)) >= 0.126:
                                _kinratio = True
                        except Exception:
                            pass
                        _rest = False
                        _gap_days = None
                        try:
                            _pdt = (_ctx or {}).get('prev_date')
                            if _pdt and len(_dv) >= 8:
                                _gap = (datetime.strptime(_dv[:8], '%Y%m%d')
                                        - datetime.strptime(_pdt, '%Y%m%d')).days
                                _gap_days = _gap
                                if _gap >= 180:
                                    _rest = True
                        except Exception:
                            pass
                        # 馬体重増減(タグ用)
                        _zg_e = None
                        _mzg_e = re.search(r'\(([-+]?\d+)\)', str(_r.get('Weight', '') or ''))
                        if _mzg_e:
                            try:
                                _zg_e = int(_mzg_e.group(1))
                            except Exception:
                                _zg_e = None
                        _nige = bool(_ctx and _ctx.get('prev_kyaku') == '1')
                        # 🔥末脚救出(独立): レース内 末脚指数top3 × 人気≥6 × 2走以上
                        # (scripts/spurt_index_backtest.py 検証: 複勝13.4%/ROI77.7% ＞ ベース9.4%/66.4%)
                        _si = (_ctx or {}).get('spurt_index')
                        _sr = (_ctx or {}).get('spurt_runs', 0)
                        _spurt = bool(_um in _spurt_top3 and _sr >= 2
                                      and pd.notnull(_pop) and _pop >= 6)
                        # 🌧️ 重・不良馬場×1番人気=構造的に危険(verified_heavy_track_bias)
                        # 芝重/芝不良で複勝-5.6〜-9.2pp, ダ不良で-3.7pp(オッズ未織込・z有意)
                        _babafav = bool(
                            pd.notnull(_pop) and _pop == 1 and (
                                ('芝' in _surf and _baba in ('重', '不良')) or
                                ('ダ' in _surf and _baba == '不良')))
                        _posr = []
                        if _gold:
                            _posr.append(f"黄金ライン(連対{_g['top2']:.0%}/{_g['rides']})")
                        if _tcok:
                            _posr.append(f"厩舎当ｺｰｽ{_cs['win_rate']:.0%}")
                        if _spurt:
                            _posr.append(f"🔥末脚救出(指数{_si:.1f})")
                        _negr = []
                        if _fade:
                            _negr.append('牝' + ('冬' if _mo in (12, 1, 2) else '春') + 'ﾌｪｰﾄﾞ')
                        if _distchg:
                            _negr.append('大幅距離変更')
                        if _hatsud:
                            _negr.append('初ダート')
                        if _fluke:
                            _negr.append('前走フロック')
                        if _topswap:
                            _negr.append('トップ騎手乗替')
                        if _kinratio:
                            _negr.append('斤量比≥12.6%')
                        if _rest:
                            _negr.append('半年休み明け')
                        if _babafav:
                            _negr.append(f'🌧️{_baba}馬場×1番人気(複勝-5〜9pp検証)')
                        if _nige:
                            _negr.append('前走逃げ')
                        _pos = bool(_posr)
                        _neg = bool(_negr)
                        _score = -(float(_pop) if pd.notnull(_pop) else 18) + (1.5 if _pos else 0) - (1.5 if _neg else 0)
                        # 消去理由ラーニング用の構造タグ
                        _tags = sorted(_er.compute_tags(
                            ninki=(float(_pop) if pd.notnull(_pop) else None),
                            prev_dist=(_ctx or {}).get('prev_dist'), cur_dist=_dist,
                            layoff_days=_gap_days, spurt_index=_si, spurt_runs=_sr,
                            zogen=_zg_e, sex_age=_sa, prev_kyaku=(_ctx or {}).get('prev_kyaku'),
                            surface=_surf, dirt_runs=(_ctx or {}).get('dirt_runs'),
                            topswap=_topswap))
                        # 補正タイム(H7=直近7走×同一馬場の最高・負=速い／検証: 本命補強+穴の相手に有効)
                        _figd = _ct.get_figure(_kt, _surf) if _kt else None
                        _ctbest = (_figd or {}).get('fig')
                        # 確率列(Projected Scoreがある時だけ) EV=p*odds / 複勝=P(3着内) / 連対=P(2着内)
                        _p = _winp.get(_um)
                        _ev = _bo.ev(_p, _odds) if (_p and pd.notnull(_odds)) else None
                        _fuk = _bo.place_prob(_winp, _um, _all_um) if (_p and len(_all_um) >= 4) else None
                        _ren = _top2_prob(_winp, _um, _all_um) if (_p and len(_all_um) >= 3) else None
                        _erows.append({'馬番': _um, '馬名': _nm,
                                       '人気': int(_pop) if pd.notnull(_pop) else None,
                                       'オッズ': float(_odds) if pd.notnull(_odds) else None,
                                       'score': _score, 'pos': _pos, 'neg': _neg,
                                       '妙味材料': ' / '.join(_posr) or '-',
                                       '危険材料': ' / '.join(_negr) or '-',
                                       '_ctbest': _ctbest,
                                       '_ev': _ev, '_fuk': _fuk, '_ren': _ren,
                                       '_tags': _tags})
                    st.session_state[_ekey] = _erows
                except Exception as _e:
                    st.session_state[_ekey] = []
                    st.warning(f"エンジン実行エラー: {_e}")
        _erows = st.session_state.get(_ekey, [])
        if not _erows and _ekey not in st.session_state:
            st.info("👆「▶ 強適消去エンジンを実行」を押すと、検証ファクター照合と消去判定を行います。")
        if _erows:
            from core import elim_reasons as _er
            from core import corrected_time as _ct
            _edf = pd.DataFrame(_erows).sort_values('score', ascending=False).reset_index(drop=True)
            _n = len(_edf)
            _keep = (_n + 1) // 2
            # 🛟ボーダー残し(=半分カットのあとN頭だけ戻す): 消去ゾーン上位(score上位の消され馬)。
            # scripts/keepmore_backtest.py 検証(2023-25,9519R) 各戻し馬の3着内人気補正残差:
            #   +1頭目 +0.83pt(z=1.97) / +2頭目 +1.35pt(z=3.19・最強) / +3頭目 +0.78pt(z=1.84) /
            #   +4頭目 -0.36pt(z=-0.85=人気どおり以下=損)。→ 戻す価値は+3頭目まで、+4で打ち止め。
            #   累積3着内取りこぼし: 現行14.9% → +1:10.2% → +2:6.6% → +3:4.1%。
            # ※どれも単勝ROI70%台=相手(複勝/3連複の押さえ)専用、単勝軸(✅残し上位)には入れない。
            _cut_zone = _n - _keep   # 消去ゾーンの頭数
            _border_max = max(0, min(3, _cut_zone - 1)) if _n >= 6 else 0  # 最低1頭は消しを残す
            if _border_max > 0:
                _border_cnt = st.slider(
                    "🛟 ボーダー残し（半分カット後に戻す頭数）", 0, _border_max,
                    min(2, _border_max), key=f"kf_border_n_{race_id_input}",
                    help="消去ゾーン上位を相手(押さえ)に戻す。検証スイートスポット=2頭(z=3.19)。"
                         "+3まで過小評価、+4で人気どおり以下=損。単勝軸には入れない。")
            else:
                _border_cnt = 0

            def _verdict(i):
                if i < _keep:
                    return '✅残し'
                if _border_cnt and _keep <= i < _keep + _border_cnt:
                    return '🛟ボーダー残し'
                return '🧹消し'
            _edf['判定'] = [_verdict(i) for i in range(_n)]
            # --- 消去理由ラーニング: 学習済みタグに合致する消し馬を自動で残しに昇格 ---
            _ledger = _er.load_ledger()
            _learned = _er.learned_tags(_ledger)   # 3回以上たまったタグ
            _edf['学習残し'] = ''
            if _learned:
                for _ix, _rr in _edf.iterrows():
                    if _edf.at[_ix, '判定'] == '🧹消し':
                        _hit = sorted(set(_rr.get('_tags') or []) & _learned)
                        if _hit:
                            _edf.at[_ix, '判定'] = '✅残し'
                            _edf.at[_ix, '学習残し'] = '♻️' + '/'.join(_er.TAG_LABEL.get(k, k) for k in _hit)
            _cut = _edf[_edf['判定'] == '🧹消し']
            _ana = _cut[(_cut['pos']) & (_cut['人気'].fillna(99) >= 8)].sort_values('オッズ', ascending=False)
            _anauma = _ana.iloc[0] if not _ana.empty else None
            _dgr = _edf[(_edf['人気'].fillna(99) <= 3) & (_edf['neg'])]
            _has_learn = (_edf['学習残し'].astype(str).str.len() > 0).any()
            # --- 補正タイム列(フィールド内順位top3に🔵・負=基準より速い) ---
            _figs = {}
            for _, _rr in _edf.iterrows():
                try:
                    _figs[int(_rr['馬番'])] = _rr.get('_ctbest')
                except Exception:
                    pass
            _franks = _ct.field_ranks(_figs)

            def _ct_disp(rr):
                b = rr.get('_ctbest')
                if b is None:
                    return '-'
                try:
                    u = int(rr['馬番'])
                except Exception:
                    u = -1
                return ('🔵' if _franks.get(u, 99) <= 3 else '') + _ct.fmt_t100(b)
            _edf['補正T'] = [_ct_disp(_rr) for _, _rr in _edf.iterrows()]
            # --- 確率列(Projected Scoreがある時のみ。EV=p×odds, 複勝=P(3着内), 連対=P(2着内)) ---
            def _pct(v):
                return f"{v * 100:.0f}%" if v is not None else '-'
            _has_prob = any(_rr.get('_ev') is not None for _, _rr in _edf.iterrows())
            _edf['単勝EV'] = [(f"{_rr['_ev']:.2f}" if _rr.get('_ev') is not None else '-') for _, _rr in _edf.iterrows()]
            _edf['複勝率'] = [_pct(_rr.get('_fuk')) for _, _rr in _edf.iterrows()]
            _edf['連対率'] = [_pct(_rr.get('_ren')) for _, _rr in _edf.iterrows()]
            _show_cols = ['判定', '馬番', '馬名', '人気', 'オッズ']
            if _has_prob:
                _show_cols += ['単勝EV', '複勝率', '連対率']
            _show_cols += ['妙味材料', '危険材料']
            if _has_learn:
                _show_cols.append('学習残し')
            _show = _edf[_show_cols]

            def _row_color(s):
                _out = []
                for v in s:
                    if v == '🧹消し':
                        _out.append('background-color:#f1f3f5;color:#adb5bd')
                    elif v == '🛟ボーダー残し':
                        _out.append('background-color:#e3f0fb;color:#1565c0;font-weight:bold')
                    else:
                        _out.append('background-color:#e6f4ea;font-weight:bold')
                return _out
            _elim_colcfg = {'オッズ': st.column_config.NumberColumn('オッズ', format="%.1f")}
            try:
                st.dataframe(_show.style.apply(_row_color, subset=['判定']),
                             hide_index=True, use_container_width=True, column_config=_elim_colcfg)
            except Exception:
                st.dataframe(_show, hide_index=True, use_container_width=True, column_config=_elim_colcfg)
            _keep_n = int((_edf['判定'] == '✅残し').sum())
            _border_n = int((_edf['判定'] == '🛟ボーダー残し').sum())
            _cut_n = int((_edf['判定'] == '🧹消し').sum())
            _learn_n = int((_edf['学習残し'].astype(str).str.len() > 0).sum())
            # 🧹→🏠3連複エンジン連携: 残し(✅+🛟)をディスク保存(後でクロスの最終候補が上書き)
            try:
                from core import score_cache as _sck_w
                _sck_w.write_keep(race_id_input,
                                  [int(x) for x in _edf[_edf['判定'] != '🧹消し']['馬番'].tolist()])
            except Exception:
                pass
            st.caption(f"全{_n}頭 → ✅残し{_keep_n}頭"
                       + (f" / 🛟ボーダー残し{_border_n}頭" if _border_n else "")
                       + f" / 🧹消し{_cut_n}頭"
                       + (f"（うち♻️学習で自動残し{_learn_n}頭）" if _learn_n else "")
                       + "（🛟＝半分カット後に1頭戻す。3着内取りこぼし15→10%・複勝で僅かに過小評価＝相手専用/単勝軸非推奨）")
            if _has_prob:
                st.caption("単勝EV＝予測勝率×オッズ(1.0超で理論プラス)／複勝率＝P(3着内)／連対率＝P(2着内)。"
                           "**🏠の予測スコアから算出したモデル目安(未検証)**。人気薄の高EVは過信注意。"
                           "下の📊は別物=jravan.db実測のオッズ帯平均。")
            else:
                st.caption("ℹ️ 単勝EV/複勝率/連対率を出すには、先に🏠 Single Race Analysisで**同じレースを採点**してください"
                           "(予測スコアをディスク経由で取り込みます)。")

            # ===== 📊 残った馬の期待値・回収率・連対率（jravan.db実測ベース）=====
            st.markdown("#### 📊 残った馬の期待値・回収率・連対率")
            from core import jockey_jv as _jjv
            _RKEEP = _edf[_edf['判定'] != '🧹消し'].copy()
            # オッズ帯別の実測 勝率/連対率/複勝率(2022-25)を session にキャッシュ。
            # 期待値=回収率=勝率×オッズ(単勝は同義)。
            if '_odds_exp_fine' not in st.session_state:
                _ef = {}
                # ※ os.path.exists ガード必須: sqlite3.connect はファイルが無いと空DBを
                #   新規作成してしまい、以降 IS_PUBLIC 判定が壊れ engine が
                #   「no such table: results」で落ちる(公開版バグ)。read-only でも接続する。
                if os.path.exists(_jjv.JV_DB_PATH):
                    try:
                        import sqlite3 as _sq3
                        _edges = [1.5, 2.5, 4.0, 7.0, 15.0, 30.0, 60.0]

                        def _fband(o):
                            for _i, _e in enumerate(_edges):
                                if o <= _e:
                                    return _i
                            return len(_edges)
                        _con2 = _sq3.connect(f"file:{_jjv.JV_DB_PATH}?mode=ro", uri=True)
                        _rws = _con2.execute(
                            "SELECT win_odds, chakujun FROM results "
                            "WHERE year IN ('2022','2023','2024','2025') "
                            "AND chakujun>0 AND win_odds>0").fetchall()
                        _con2.close()
                        _bk = {}
                        for _o2, _c2 in _rws:
                            _b = _fband(_o2)
                            _d = _bk.setdefault(_b, [0, 0, 0, 0])
                            _d[0] += 1
                            _d[1] += 1 if _c2 == 1 else 0
                            _d[2] += 1 if _c2 <= 2 else 0
                            _d[3] += 1 if _c2 <= 3 else 0
                        _ef = {_b: {'win': _d[1] / _d[0], 'top2': _d[2] / _d[0],
                                    'top3': _d[3] / _d[0], 'n': _d[0]} for _b, _d in _bk.items()}
                        _ef['_edges'] = _edges
                    except Exception:
                        _ef = {}
                st.session_state['_odds_exp_fine'] = _ef
            _ef = st.session_state.get('_odds_exp_fine', {})
            if not _ef:
                st.info("期待値・回収率の実測較正には jravan.db が必要です（公開版では非表示）。")
            else:
                _vedges = _ef.get('_edges', [])

                def _fb2(o):
                    for _i, _e in enumerate(_vedges):
                        if o <= _e:
                            return _i
                    return len(_vedges)
                _vrows = []
                for _, _rr in _RKEEP.iterrows():
                    _o = _rr.get('オッズ')
                    _pop = _rr.get('人気')
                    if pd.isnull(_o) or _o <= 0:
                        continue
                    _e = _ef.get(_fb2(float(_o)))
                    if not _e:
                        continue
                    _roi = float(_o) * _e['win']   # 単勝期待値=回収率
                    _ana_fac = bool(_rr.get('pos')) and pd.notnull(_pop) and _pop >= 8
                    _myo = ('🔥+ファクター(人気薄・実測ROI108.8%帯)' if _ana_fac
                            else ('✨EV>1' if _roi >= 1.0 else '-'))
                    _vrows.append({'判定': _rr['判定'], '馬番': int(_rr['馬番']), '馬名': _rr['馬名'],
                                   '人気': (int(_pop) if pd.notnull(_pop) else None),
                                   'オッズ': float(_o), '補正T': _ct.fmt_t100(_rr.get('_ctbest')),
                                   '単勝回収率': _roi * 100,
                                   '連対率': _e['top2'] * 100, '複勝率': _e['top3'] * 100,
                                   '妙味': _myo})
                if _vrows:
                    _vdf = pd.DataFrame(_vrows)
                    # --- 残りから手動で外す(チェック→その行グレー化) ---
                    _excl_key = f"kf_keep_excl_{race_id_input}"
                    _opts_ex = [f"{int(r['馬番'])} {r['馬名']}" for r in _vrows]
                    _prev_ex = [o for o in st.session_state.get(_excl_key, []) if o in _opts_ex]
                    _exsel = st.multiselect(
                        "🚫 残りから外す馬（チェックするとその行がグレー＝買い目対象から除外）",
                        _opts_ex, default=_prev_ex,
                        key=f"kf_keep_excl_sel_{race_id_input}",
                        help="期待値・補正Tなどを見て『これは要らない』という馬をここで外せます。除外馬はグレー表示になります。")
                    st.session_state[_excl_key] = _exsel
                    _excl_ums = set()
                    for _s in _exsel:
                        try:
                            _excl_ums.add(int(str(_s).split()[0]))
                        except Exception:
                            pass
                    _vcfg = {
                        'オッズ': st.column_config.NumberColumn('オッズ', format="%.1f"),
                        '補正T': st.column_config.TextColumn(
                            '🔵補正T', help="補9風スコア(直近7走×同馬場の最高/100=勝ち負けレベル/高いほど速い・検証済H7図)"),
                        '単勝回収率': st.column_config.NumberColumn(
                            '単勝期待値(回収率)', format="%.0f%%",
                            help="勝率(オッズ帯実測)×オッズ。100%=損益分岐。控除率のため大半は75-85%で横並び。"),
                        '連対率': st.column_config.NumberColumn('連対率', format="%.0f%%",
                                                            help="そのオッズ帯の実測2着内率(2022-25)"),
                        '複勝率': st.column_config.NumberColumn('複勝率', format="%.0f%%",
                                                            help="そのオッズ帯の実測3着内率(2022-25)"),
                    }
                    def _gray_excl(_row):
                        try:
                            _ex = int(_row['馬番']) in _excl_ums
                        except Exception:
                            _ex = False
                        return (['background-color:#e9ecef;color:#adb5bd'] * len(_row)) if _ex else ([''] * len(_row))

                    # 補正T(高=速い)/単勝回収率(高=妙味)の上位6頭のセルに色付け
                    def _ct_num(v):
                        try:
                            return int(str(v))
                        except Exception:
                            return None
                    _top6_ct = {i for i, _ in sorted(
                        [(i, _ct_num(_vdf.at[i, '補正T'])) for i in _vdf.index if _ct_num(_vdf.at[i, '補正T']) is not None],
                        key=lambda t: -t[1])[:6]}
                    def _top6_by(col):
                        return {i for i, _ in sorted(
                            [(i, _vdf.at[i, col]) for i in _vdf.index if pd.notnull(_vdf.at[i, col])],
                            key=lambda t: -t[1])[:6]}
                    _top6_ev = _top6_by('単勝回収率')
                    _top6_ren = _top6_by('連対率')
                    _top6_fuk = _top6_by('複勝率')

                    def _hl_ct(s):
                        return ['background-color:#90ee90' if i in _top6_ct else '' for i in s.index]

                    def _hl_ev(s):
                        return ['background-color:#fffacd' if i in _top6_ev else '' for i in s.index]

                    def _hl_ren(s):
                        return ['background-color:#FFE4E1' if i in _top6_ren else '' for i in s.index]

                    def _hl_fuk(s):
                        return ['background-color:#B0E0E6' if i in _top6_fuk else '' for i in s.index]
                    try:
                        _vsty = (_vdf.style
                                 .apply(_hl_ct, subset=['補正T'])
                                 .apply(_hl_ev, subset=['単勝回収率'])
                                 .apply(_hl_ren, subset=['連対率'])
                                 .apply(_hl_fuk, subset=['複勝率'])
                                 .apply(_gray_excl, axis=1))
                        st.dataframe(_vsty, hide_index=True, use_container_width=True, column_config=_vcfg)
                    except Exception:
                        st.dataframe(_vdf, hide_index=True, use_container_width=True, column_config=_vcfg)
                    if _excl_ums:
                        _remain = [r for r in _vrows if int(r['馬番']) not in _excl_ums]
                        st.caption(f"🚫 除外{len(_excl_ums)}頭（{', '.join(str(u) for u in sorted(_excl_ums))}番）"
                                   f"→ 残り{len(_remain)}頭: "
                                   + " / ".join(f"{int(r['馬番'])}{r['馬名']}" for r in _remain))
                    st.caption("⚠️ 期待値＝回収率＝勝率×オッズ（単勝は同義の数字）。値はオッズ帯の母集団平均なので"
                               "大半が控除率ぶん(~75-85%)で横並び＝単純なオッズだけでは+妙味は出ない。"
                               "100%超の妙味は実測で平均を超える🔥+ファクター（人気薄×黄金/厩舎/末脚＝単勝ROI108.8%）持ちに限る。"
                               "連対率/複勝率もオッズ帯の実測値。最終判断は強適Ranking Tableと併用。")
                else:
                    st.info("残った馬にオッズ情報がありません。")

            # ===== 🧹 消去クロステーブル（来にくさフラグ重複）=====
            st.divider()
            st.markdown("### 🧹 消去クロステーブル（📊の残り → さらに6〜7頭へ絞る）")
            st.caption("📊で残した馬だけを対象に、来にくさフラグの重複を可視化（scripts/elim_cross_backtest.py検証）。"
                       "各フラグ単体は人気に織込み済(残差≈0)だが**重複数が増えるほど絶対複勝率は単調低下**"
                       "(0個31.5%→3個14.9%→7個10.3%)。🔴重複が多い＝来にくい馬を切って、**最終6〜7頭(軸含む)**に絞り込む段。")
            from core import elim_cross as _exc
            try:
                # --- 🏠 Single Race Analysis の採点テーブル(総合戦闘力/予測スコア)を取得し下位30%を判定 ---
                _score_df = st.session_state.get('current_bonus_df')
                if _score_df is None:
                    _score_df = st.session_state.get('df')
                # 左メニュー新タブ化で🧹は別セッション→session_stateに🏠の採点が無い。
                # ディスクキャッシュ(race_id一致・core/score_cache)から復元して連携を維持する。
                if _score_df is None or getattr(_score_df, 'empty', True):
                    try:
                        from core import score_cache as _scx
                        _cs = _scx.read_scores(race_id_input)
                        if _cs:
                            _score_df = pd.DataFrame([
                                {'Umaban': _u, 'BattleScore': (_v or {}).get('battle'),
                                 'Projected Score': (_v or {}).get('proj')}
                                for _u, _v in _cs.items()])
                    except Exception:
                        pass
                _battle_low = {}   # 馬番 -> True(総合戦闘力 下位30%)
                _proj_low = {}     # 馬番 -> True(予測スコア 下位30%)
                _score_match = 0   # この消去ページのレースと採点テーブルの馬番一致数
                _score_avail = False
                try:
                    if _score_df is not None and not _score_df.empty and 'Umaban' in _score_df.columns:
                        _sd = _score_df.copy()
                        _sd['_um'] = pd.to_numeric(_sd['Umaban'], errors='coerce')
                        _kf_ums = set(pd.to_numeric(df['Umaban'], errors='coerce').dropna().astype(int).tolist()) if 'Umaban' in df.columns else set()
                        _sd_ums = set(_sd['_um'].dropna().astype(int).tolist())
                        _score_match = len(_kf_ums & _sd_ums)
                        # 同一レース判定: 馬番集合が十分に重なる(別レースの採点を誤適用しない)
                        if _kf_ums and _score_match >= max(3, int(0.6 * len(_kf_ums))):
                            _score_avail = True
                            if 'BattleScore' in _sd.columns:
                                _bs = pd.to_numeric(_sd['BattleScore'], errors='coerce')
                                _bth = _bs.quantile(0.35)  # 総合戦闘力 下位35%(18頭なら下位6頭)
                                for _, _sr in _sd.iterrows():
                                    _u = _sr['_um']
                                    if pd.notnull(_u) and pd.notnull(_bs.loc[_sr.name]) and _bs.loc[_sr.name] <= _bth:
                                        _battle_low[int(_u)] = True
                            _pcol = 'Projected Score' if 'Projected Score' in _sd.columns else None
                            if _pcol:
                                _ps = pd.to_numeric(_sd[_pcol], errors='coerce')
                                _pth = _ps.quantile(0.30)
                                for _, _sr in _sd.iterrows():
                                    _u = _sr['_um']
                                    if pd.notnull(_u) and pd.notnull(_ps.loc[_sr.name]) and _ps.loc[_sr.name] <= _pth:
                                        _proj_low[int(_u)] = True
                except Exception:
                    _score_avail = False
                if _score_avail:
                    _use_score = st.checkbox(
                        "🏠 Single Race Analysisの『総合戦闘力 下位35%／予測スコア 下位30%』も加味する",
                        value=True, key=f"kf_excross_usescore_{race_id_input}",
                        help="🏠で採点済みのテーブルから、総合戦闘力が下位35%(18頭なら下位6頭)・予測スコアが下位30%の馬に弱点フラグを追加します。"
                             "※これらは人気/オッズを内包し検証(backtest)不可のため、推定複勝率(検証値)には算入せず『参考の重ね』として表示します。")
                else:
                    _use_score = False
                    st.markdown(
                        "<div style='color:#d32f2f;font-size:0.85em'>"
                        "ℹ️ 総合戦闘力／予測スコアを加味するには、先に🏠 Single Race Analysisで"
                        "<b>同じレースを採点</b>してください"
                        "（採点テーブルの馬番がこのレースと一致すると自動で取り込みます）。</div>",
                        unsafe_allow_html=True)
                _tg_default = []
                _all_names_ec = df['Name'].astype(str).tolist() if 'Name' in df.columns else []
                _tg_sel = st.multiselect(
                    "調教C以下の馬（任意・あなたの実観測を加算）", _all_names_ec, default=_tg_default,
                    key=f"kf_excross_train_{race_id_input}",
                    help="調教評価はjravan.dbに過去データが無く検証不可。実観測フラグとして重複数に+1加算します。")
                _exc_clicked = st.button("▶ 消去クロステーブルを作成", key="kf_excross_run")
                _xkey = f"kf_excross_{race_id_input}"
                if _exc_clicked:
                    with st.spinner("過去走サマリを照合中..."):
                        from core import jockey_jv as _jjx
                        from core import score_cache as _scx2
                        # 🏠展開MAPの最終直線『後方の馬』(ディスク橋渡し)→展開後方フラグ
                        # ※起動中Streamlitが旧モジュールをキャッシュしている場合に備えガード
                        try:
                            _pm_rear = _scx2.read_rear(race_id_input) or set()
                        except Exception:
                            _pm_rear = set()
                        _rdate = str(metadata.get('date_val', '') or '')
                        try:
                            _cdist = int(pd.to_numeric(df['CurrentDistance'].iloc[0], errors='coerce'))
                        except Exception:
                            _cdist = None
                        # --- 事前平均PCI(過去走ベース)とフィールド平均からの乖離(検証済 pcidev フラグ用) ---
                        _pci_map = {}   # 馬番 -> 事前平均PCI
                        try:
                            _calc_pci = race_analysis_tools.PCICalculator()
                            for _, _pr in df.iterrows():
                                try:
                                    _pu = int(pd.to_numeric(_pr.get('Umaban'), errors='coerce'))
                                except Exception:
                                    continue
                                _st = _calc_pci.analyze_horse_pci(_pr.get('PastRuns', []) or [])
                                if _st.get('pci_list'):  # 有効な過去走PCIがある馬のみ
                                    _pci_map[_pu] = float(_st['avg_pci'])
                            _field_pci = (sum(_pci_map.values()) / len(_pci_map)) if _pci_map else None
                        except Exception:
                            _field_pci = None
                        _xrows = []
                        for _, _r in df.iterrows():
                            _nm = str(_r.get('Name', ''))
                            try:
                                _um = int(pd.to_numeric(_r.get('Umaban'), errors='coerce'))
                            except Exception:
                                _um = 0
                            _pop = pd.to_numeric(_r.get('Popularity'), errors='coerce')
                            # age from SexAge('牡3')
                            _age = None
                            _mage = re.search(r'(\d+)', str(_r.get('SexAge', '') or ''))
                            if _mage:
                                _age = int(_mage.group(1))
                            # zogen from Weight('480(+4)')
                            _zg = None
                            _mzg = re.search(r'\(([-+]?\d+)\)', str(_r.get('Weight', '') or ''))
                            if _mzg:
                                _zg = int(_mzg.group(1))
                            _kt, _tc = _jjx.resolve_horse(_nm)
                            _ctx = _jjx.horse_recent_context(_kt) if _kt else None
                            _es = _jjx.horse_elim_stats(_kt) if _kt else None
                            _fl = _exc.compute_flags(
                                last5_top3=(_es or {}).get('last5_top3'),
                                spurt_index=(_ctx or {}).get('spurt_index'),
                                spurt_runs=(_ctx or {}).get('spurt_runs', 0),
                                avg_c4ratio=(_es or {}).get('avg_c4ratio'),
                                prev_date=(_ctx or {}).get('prev_date'),
                                race_date=_rdate,
                                prev_dist=(_ctx or {}).get('prev_dist'),
                                cur_dist=_cdist,
                                zogen=_zg, age=_age,
                                training_grade='C' if _nm in _tg_sel else None,
                                battle_low=bool(_use_score and _battle_low.get(_um)),
                                proj_low=bool(_use_score and _proj_low.get(_um)),
                                pm_back=bool(_um in _pm_rear),
                                pci_dev=((_pci_map[_um] - _field_pci)
                                         if (_field_pci is not None and _um in _pci_map) else None),
                            )
                            _cnt = len(_fl)                       # 総重複(検証+実観測/score)
                            _vcnt = _exc.verified_count(_fl)      # 検証済みのみ(推定複勝率の根拠)
                            _xrows.append({
                                '馬番': _um, '馬名': _nm,
                                '人気': int(_pop) if pd.notnull(_pop) else None,
                                'フラグ数': _cnt,
                                '検証数': _vcnt,
                                '推定複勝率': _exc.band_fukusho(_vcnt),
                                '_lit': [k for k in _exc.FLAG_DEFS_ORDER if k in _fl],  # 点灯フラグkey一覧(○マトリクス用)
                            })
                        st.session_state[_xkey] = _xrows
                _xrows = st.session_state.get(_xkey, [])
                # --- 📊で残った馬(✅/🛟残し − 📊で外した馬)のみを対象にする ---
                _surv = None
                try:
                    _kx_excl = set()
                    for _s in st.session_state.get(f"kf_keep_excl_{race_id_input}", []):
                        try:
                            _kx_excl.add(int(str(_s).split()[0]))
                        except Exception:
                            pass
                    _surv = set()
                    for _, _er2 in _edf.iterrows():
                        if _er2['判定'] != '🧹消し' and int(_er2['馬番']) not in _kx_excl:
                            _surv.add(int(_er2['馬番']))
                except Exception:
                    _surv = None
                if _surv is not None and _xrows:
                    _xrows = [r for r in _xrows if int(r.get('馬番', -1)) in _surv]
                if not _xrows and _xkey not in st.session_state:
                    st.info("👆「▶ 消去クロステーブルを作成」を押すと、📊で残った馬の来にくさフラグを集計します。")
                if _surv is not None and not _xrows and _xkey in st.session_state:
                    st.info("📊で残った馬がいません（先に上の📊で残す馬を確認してください）。")
                if _xrows:
                    _xrows = sorted(_xrows, key=lambda r: (-(r.get('フラグ数') or 0), -((r.get('人気') or 0))))
                    # --- stage2: ここからさらに外して6-7頭(軸含む)へ ---
                    _x2key = f"kf_cross_excl_{race_id_input}"
                    _x2opts = [f"{int(r['馬番'])} {r['馬名']}" for r in _xrows]
                    _x2prev = [o for o in st.session_state.get(_x2key, []) if o in _x2opts]
                    _x2sel = st.multiselect(
                        "🚫 ここからさらに外す（🔴重複が多い＝来にくい馬を切って6〜7頭へ）",
                        _x2opts, default=_x2prev, key=f"kf_cross_excl_sel_{race_id_input}",
                        help="📊の残りから、来にくさ重複が多い馬を切って最終6〜7頭(軸含む)に絞ります。外した馬はグレー表示。")
                    st.session_state[_x2key] = _x2sel
                    _x2ums = set()
                    for _s in _x2sel:
                        try:
                            _x2ums.add(int(str(_s).split()[0]))
                        except Exception:
                            pass
                    _final_rows = [r for r in _xrows if int(r['馬番']) not in _x2ums]
                    _nf = len(_final_rows)
                    _badge = ("✅ 目標達成" if 6 <= _nf <= 7 else ("⬇️ もう少し絞る" if _nf > 7 else "⚠️ 絞りすぎ"))
                    st.markdown(
                        f"**🎯 最終候補 {_nf}頭**（目標6〜7頭・軸含む） {_badge}　"
                        + " / ".join(f"{int(r['馬番'])}{r['馬名']}" for r in _final_rows))
                    # 🧹→🏠3連複エンジン連携: クロステーブルの最終候補を確定として保存(上書き)
                    try:
                        from core import score_cache as _sck_w2
                        _sck_w2.write_keep(race_id_input, [int(r['馬番']) for r in _final_rows])
                        st.caption("→ この最終候補は🏠 Single Race Analysisの🎯3連複おすすめエンジンに自動取込されます(同レースID)。")
                    except Exception:
                        pass
                    # 1頭以上で点灯したフラグだけを列にする(空列を出さない)。なければ全フラグ。
                    _active = [k for k in _exc.FLAG_DEFS_ORDER
                               if any(k in (r.get('_lit') or []) for r in _xrows)]
                    if not _active:
                        _active = _exc.FLAG_DEFS_ORDER[:]
                    # ○マトリクス: 各フラグ=列、点灯セルに○
                    _mat = []
                    for r in _xrows:
                        _lit = set(r.get('_lit') or [])
                        _row = {'馬番': r['馬番'], '馬名': r['馬名'], '人気': r['人気']}
                        for k in _active:
                            _row[_exc.FLAG_LABEL[k]] = '○' if k in _lit else ''
                        _row['重複'] = r['フラグ数']
                        _row['検証'] = r['検証数']
                        _row['推定複勝率'] = f"{r['推定複勝率']:.0f}%"
                        _mat.append(_row)
                    _xdf = pd.DataFrame(_mat)
                    _flag_cols = [_exc.FLAG_LABEL[k] for k in _active]
                    # 検証不可フラグ(調教/総合力/予測)の列ヘッダは△印で区別
                    _unv_cols = {_exc.FLAG_LABEL[k] for k in _active if k in _exc.UNVERIFIED}

                    def _dup_color(s):  # 重複数(赤系グラデ)
                        out = []
                        for v in s:
                            if v >= 4:
                                out.append('background-color:#f8d7da;color:#842029;font-weight:bold')  # 消去推奨
                            elif v >= 2:
                                out.append('background-color:#fff3cd')  # 注意
                            else:
                                out.append('')
                        return out

                    def _maru_color(s):  # ○セルを赤文字で目立たせる
                        return ['color:#c0392b;font-weight:bold;text-align:center' if v == '○' else '' for v in s]

                    def _gray_x2(_row):  # stage2で外した馬はグレー
                        try:
                            _ex = int(_row['馬番']) in _x2ums
                        except Exception:
                            _ex = False
                        return (['background-color:#e9ecef;color:#adb5bd'] * len(_row)) if _ex else ([''] * len(_row))

                    _disp_cols = ['馬番', '馬名'] + _flag_cols + ['重複']
                    _colcfg = {
                        '馬番': st.column_config.NumberColumn('馬番', width='small'),
                        '人気': st.column_config.NumberColumn('人気', width='small'),
                        '重複': st.column_config.NumberColumn('🔴重複', help="点灯した来にくさフラグの総数(○の数)。多いほど3着内率が下がる"),
                        '検証': st.column_config.NumberColumn('検証', width='small', help="うちjravan.dbで検証済みのフラグ数。推定複勝率はこの数だけで算定"),
                        '推定複勝率': st.column_config.TextColumn('推定複勝率', help="検証数→絶対複勝率(検証値)。人気と相関＝妙味判定ではない"),
                    }
                    for _fc in _flag_cols:
                        _lbl = ('△' + _fc) if _fc in _unv_cols else _fc
                        _colcfg[_fc] = st.column_config.TextColumn(_lbl, width='small')
                    try:
                        _sty = _xdf[_disp_cols].style.apply(_dup_color, subset=['重複'])
                        if _flag_cols:
                            _sty = _sty.apply(_maru_color, subset=_flag_cols)
                        if _x2ums:
                            _sty = _sty.apply(_gray_x2, axis=1)
                        st.dataframe(_sty, hide_index=True, use_container_width=True, column_config=_colcfg)
                    except Exception:
                        st.dataframe(_xdf[_disp_cols], hide_index=True, use_container_width=True, column_config=_colcfg)
                    st.caption("○＝その弱点が点灯。**🔴重複**＝○の総数(多いほど来にくい)。"
                               "△印の列(調教C以下/総合力下位/予測下位)は検証不可(人気内包)＝重複には乗るが推定複勝率には算入しない。")
                    _heavy = _xdf[_xdf['重複'] >= 4]
                    if not _heavy.empty:
                        st.error("🧹 消去候補（弱点重複4つ以上）: "
                                 + " / ".join(f"{int(r['馬番'])}{r['馬名']}(計{int(r['重複'])}個/検証{int(r['検証'])}個)" for _, r in _heavy.iterrows()))
                    _hpop = _xdf[(_xdf['人気'].fillna(99) <= 5) & (_xdf['検証'] >= 4)]
                    if not _hpop.empty:
                        st.warning("⚠️ 人気なのに検証弱点多数（過剰人気の兆候・検証残差-1.8〜): "
                                   + " / ".join(f"{int(r['馬番'])}{r['馬名']}({r['人気']}人気/検証{int(r['検証'])}個)" for _, r in _hpop.iterrows()))
                    st.caption("※各フラグは単体では人気に織込み済(妙味ではない)。重複数による絶対複勝率の低下を『相手絞り/軸の不安』として使う。"
                               "**推定複勝率は『検証数』のみで算定**。調教C以下・総合力下位・予測下位の3つは検証不可(人気/オッズ内包)のため"
                               "『重複数(参考の重ね)』には乗るが推定複勝率には算入しない。")
            except Exception as _xe:
                st.warning(f"消去クロステーブル エラー: {_xe}")
            st.divider()
            _ec1, _ec2 = st.columns(2)
            with _ec1:
                if _anauma is not None:
                    st.success(f"🎯 妙味の穴（消去ゾーンから救出）: **{int(_anauma['馬番'])} {_anauma['馬名']}** "
                               f"／ {_anauma['人気']}人気・{float(_anauma['オッズ']):.1f}倍\n\n材料: {_anauma['妙味材料']}"
                               if pd.notnull(_anauma['オッズ']) else
                               f"🎯 妙味の穴（消去ゾーンから救出）: **{int(_anauma['馬番'])} {_anauma['馬名']}** "
                               f"／ {_anauma['人気']}人気・-倍\n\n材料: {_anauma['妙味材料']}")
                    st.caption("検証: 人気薄(≥8番)×この＋ファクターは単勝回収率108.8%(無印63.7%)")
                else:
                    st.info("🎯 妙味の穴: 該当なし（消去ゾーンに＋ファクターの人気薄馬なし）")
            with _ec2:
                if not _dgr.empty:
                    st.error("⚠️ 危険な人気馬（人気≫実力の乖離）:\n"
                             + "\n".join(f"- {int(r['馬番'])} {r['馬名']}（{r['人気']}人気）: {r['危険材料']}"
                                         for _, r in _dgr.iterrows()))
                    st.caption("検証: −ファクター人気馬は他の人気馬より3着内 約-2.6pp(z有意)")
                else:
                    st.info("⚠️ 危険な人気馬: 該当なし")

            # ===== 📝 消去理由ラーニング（消し→残しの学習台帳）=====
            with st.expander("📝 消去理由を記録（消し→残しの学習）", expanded=False):
                st.caption("終了レースの回顧用。3着以内に来た馬が『🧹消し』に入っていたら、その馬を残しに変更し"
                           "理由（自由文・空欄可）と条件タグを記録します。同じタグが"
                           f"**{_er.PROMOTE_THRESHOLD}回**たまると、以後そのタグに合致する消し馬を自動で『✅残し』に昇格します。")
                st.caption("⚠️ これは検証済みエッジではなく個人の実観測台帳。人気薄/牝馬等の広いタグは多くの馬を残してしまう"
                           "ので、できるだけ具体的な状況タグを選んでください。")
                _cut_now = _edf[_edf['判定'] == '🧹消し']
                _nameof_e = {int(r['馬番']): str(r['馬名']) for _, r in _edf.iterrows()}
                _tagsof_e = {int(r['馬番']): list(r.get('_tags') or []) for _, r in _edf.iterrows()}
                if _cut_now.empty:
                    st.info("現在『🧹消し』の馬はいません（全頭残し）。")
                else:
                    _cut_ums = [int(x) for x in _cut_now['馬番'].tolist()]
                    _sel_um = st.selectbox(
                        "残しに変更する馬（消しの中から）", _cut_ums,
                        format_func=lambda u: f"{u} {_nameof_e.get(u, '')}", key=f"er_sel_{race_id_input}")
                    _auto = [k for k in _er.TAG_ORDER if k in set(_tagsof_e.get(_sel_um, []))]
                    _picked = st.multiselect(
                        "条件タグ（この馬を残す根拠。自動判定を初期選択。追加・削除可）",
                        _er.TAG_ORDER, default=_auto,
                        format_func=lambda k: _er.TAG_LABEL.get(k, k), key=f"er_tags_{race_id_input}_{_sel_um}")
                    _reason_txt = st.text_input(
                        "消去理由（自由文・空欄可）", placeholder="例: 雨で道悪替わり身／前走は不利",
                        key=f"er_reason_{race_id_input}_{_sel_um}")
                    if st.button("💾 残しに変更して学習に記録", key=f"er_save_{race_id_input}", type="primary"):
                        _row_e = _edf[_edf['馬番'] == _sel_um].iloc[0]
                        _ok = _er.add_entry(_er.make_entry(
                            race_id=race_id_input, umaban=_sel_um, name=_nameof_e.get(_sel_um, ''),
                            ninki=(int(_row_e['人気']) if pd.notnull(_row_e['人気']) else None),
                            odds=(float(_row_e['オッズ']) if pd.notnull(_row_e['オッズ']) else None),
                            reason=_reason_txt, tags=_picked))
                        if _ok:
                            st.toast(f"{_sel_um} {_nameof_e.get(_sel_um, '')} を学習台帳に記録しました", icon="📝")
                            st.rerun()
                        else:
                            st.toast("記録に失敗しました", icon="⚠️")
                # 学習状況の表示
                _counts = _er.tag_counts(_ledger)
                if _counts:
                    st.markdown("**📚 タグ学習状況**（台帳 {} 件）".format(len(_ledger)))
                    _crows = [{'条件タグ': _er.TAG_LABEL.get(k, k), '記録回数': n,
                               '状態': f'✅学習済み(自動残し)' if n >= _er.PROMOTE_THRESHOLD
                                       else f'あと{_er.PROMOTE_THRESHOLD - n}回で有効'}
                              for k, n in sorted(_counts.items(), key=lambda x: -x[1])]
                    st.dataframe(pd.DataFrame(_crows), hide_index=True, use_container_width=True)
                else:
                    st.caption("まだ記録がありません。")

            # ===== 🎯 フォーメーション（消去エンジン連携）=====
            st.markdown("#### 🎯 フォーメーション（消去エンジン連携）")
            _form_kind = st.radio("馬券種", ["3連複", "3連単"], horizontal=True, key="kf_form_kind")
            _is_tri = (_form_kind == "3連単")
            # 列ごとに選択pill(タグ)の色を変える: 1列目=既定(赤系)/2列目=#008080/3列目=#0000ff
            st.markdown(
                "<style>"
                ".st-key-kf_form_c2 span[data-baseweb=\"tag\"]{background-color:#008080 !important;}"
                ".st-key-kf_form_c3 span[data-baseweb=\"tag\"]{background-color:#0000ff !important;}"
                ".st-key-kf_form_c2 span[data-baseweb=\"tag\"] *,"
                ".st-key-kf_form_c3 span[data-baseweb=\"tag\"] *{color:#ffffff !important;}"
                "</style>",
                unsafe_allow_html=True)
            if _is_tri:
                st.caption("着順あり(1着-2着-3着)。✅残し上位を1着/2着、🎯穴・🛟ボーダー残しを3着候補に自動配置。"
                           "（着順固定の分だけ点数は増えます。検証済みの妙味は相手選びの方針と併用）")
            else:
                st.caption("✅残し上位を軸/対抗に、🎯穴・🛟ボーダー残しを押さえに自動配置。役割分担で無駄を省きます。"
                           "（買い目構造は予測エッジでなく点数最適化。検証済み①人気-人気-穴の方針と併用）")
            _keepdf = _edf[_edf['判定'] == '✅残し']
            _keep_um = [int(x) for x in _keepdf['馬番'].tolist()]
            _border_um = [int(x) for x in _edf[_edf['判定'] == '🛟ボーダー残し']['馬番'].tolist()]
            _ana_um = int(_anauma['馬番']) if _anauma is not None else None
            _name_of = {int(r['馬番']): str(r['馬名']) for _, r in _edf.iterrows()}

            def _lab(u):
                return f"{u} {_name_of.get(u, '')}"
            _tmpl = st.radio("フォーメーション型", ["2-4-7型(推奨)", "1-3-5型(少点)", "カスタム"],
                             horizontal=True, key="kf_form_tmpl")
            if _tmpl == "2-4-7型(推奨)":
                _na, _nb, _nc = 2, 4, 7
            elif _tmpl == "1-3-5型(少点)":
                _na, _nb, _nc = 1, 3, 5
            else:
                _na, _nb, _nc = 2, 4, 7
            # デフォルト配置: 軸=残し上位、対抗=その次、押さえ=残り残し+穴
            _def1 = _keep_um[:_na]
            _def2 = _keep_um[_na:_na + _nb]
            _def3 = _keep_um[_na + _nb:_na + _nb + _nc]
            if _ana_um is not None and _ana_um not in _def3:
                _def3 = (_def3 + [_ana_um])[:_nc + 1]
            # 🛟ボーダー残しは押さえ(相手)に追加（単勝軸=1列目には入れない）
            for _bu in _border_um:
                if _bu not in _def1 and _bu not in _def2 and _bu not in _def3:
                    _def3 = _def3 + [_bu]
            _all_um = [int(x) for x in _edf['馬番'].tolist()]
            # 型・ボーダー残し頭数・レースが変わったら3列を消去エンジンの初期配置に作り直す。
            # (multiselectのdefaultは初回描画しか効かないStreamlit仕様への対処。手動編集中は維持)
            _form_sig = (str(race_id_input), _tmpl, tuple(_def1), tuple(_def2), tuple(_def3))
            if st.session_state.get('kf_form_sig') != _form_sig:
                st.session_state['kf_form_c1'] = _def1
                st.session_state['kf_form_c2'] = _def2
                st.session_state['kf_form_c3'] = _def3
                st.session_state['kf_form_sig'] = _form_sig
            _lab_c1 = "1着" if _is_tri else "1列目 軸"
            _lab_c2 = "2着" if _is_tri else "2列目 対抗"
            _lab_c3 = "3着" if _is_tri else "3列目 押さえ(穴含む)"
            _fc1, _fc2, _fc3 = st.columns(3)
            with _fc1:
                _c1 = st.multiselect(_lab_c1, _all_um, default=_def1,
                                     format_func=_lab, key="kf_form_c1")
            with _fc2:
                _c2 = st.multiselect(_lab_c2, _all_um, default=_def2,
                                     format_func=_lab, key="kf_form_c2")
            with _fc3:
                _c3 = st.multiselect(_lab_c3, _all_um, default=_def3,
                                     format_func=_lab, key="kf_form_c3")
            try:
                from core import trio_engine as _te
                import importlib as _il_te2; _il_te2.reload(_te)
                _trios = (_te.build_trifecta_formation(_c1, _c2, _c3) if _is_tri
                          else _te.build_formation(_c1, _c2, _c3))
            except Exception as _fe:
                _trios = []
                st.warning(f"フォーメーション生成エラー: {_fe}")
            if _trios:
                _sep = '→' if _is_tri else '-'
                _nsep = ' → ' if _is_tri else ' '
                _umcol = '馬番(1→2→3着)' if _is_tri else '馬番'
                # ── オッズに応じた掛け金配分（人気組=低オッズに厚く） ──
                _alc_l, _alc_m, _alc_r = st.columns([1, 1.4, 1])
                with _alc_l:
                    _form_budget = st.number_input("予算(合計・円)", 100, 1000000, 3000, 100,
                                                   key="kf_form_budget")
                with _alc_m:
                    _form_amode = st.radio("掛け金の配り方",
                                           ["人気組に厚く(払戻均等)", "均等"],
                                           key="kf_form_amode", horizontal=True,
                                           help="人気組に厚く=低オッズ(人気)の組ほど多く賭け、どの組が当たっても"
                                                "払戻が近くなる配り方(オッズ逆比)。均等=全組同額。")
                with _alc_r:
                    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                    _fetch_form_odds = st.button("💴 オッズ取得＆配分", key="kf_form_fetch_odds",
                                                 use_container_width=True)
                _fodds_key = f"kf_form_odds_{race_id_input}_{'tri' if _is_tri else 'puk'}"
                if _fetch_form_odds:
                    with st.spinner("オッズ取得中（3連単/3連複のライブオッズ）..."):
                        try:
                            if _is_tri:
                                _omap = _te.build_trifecta_odds_map(
                                    scraper.fetch_sanrentan_odds(race_id_input))
                            else:
                                _omap = _te.build_odds_map(
                                    scraper.fetch_sanrenpuku_odds(race_id_input))
                        except Exception as _oe:
                            _omap = {}
                            st.warning(f"オッズ取得エラー: {_oe}")
                        st.session_state[_fodds_key] = _omap
                _omap = st.session_state.get(_fodds_key)
                if _omap:
                    _mode2 = '払戻均等' if _form_amode.startswith('人気組') else '均等買い'
                    _bets, _no_odds = [], 0
                    for t in _trios:
                        _o = _omap.get(t) if _is_tri else _omap.get(frozenset(t))
                        if _o:
                            _bets.append({'combo': t, 'odds': float(_o)})
                        else:
                            _no_odds += 1
                    if _bets:
                        _bets.sort(key=lambda b: b['odds'])  # 人気(低オッズ)順
                        _ares = _te.allocate_budget(_bets, int(_form_budget), mode=_mode2, unit=100)
                        _rows = [{
                            '馬番': _sep.join(str(u) for u in b['combo']),
                            '馬名': _nsep.join(f"({u}){_name_of.get(u, '')}" for u in b['combo']),
                            'オッズ': round(b['odds'], 1),
                            '推奨掛け金(円)': b.get('stake', 0),
                            '的中払戻(円)': b.get('payout_if_hit', 0),
                            'ﾄﾘｶﾞﾐ': '⚠' if b.get('toriga') else '',
                        } for b in _bets]
                        st.success(f"{_form_kind} {len(_bets)}点 / 合計 {_ares.get('total', 0):,}円"
                                   + (f"（{_no_odds}点はオッズ未取得で除外）" if _no_odds else "")
                                   + f" ・配分=「{_form_amode}」")
                        st.dataframe(pd.DataFrame(_rows), hide_index=True,
                                     use_container_width=True, height=340,
                                     column_config={
                                         '馬番': st.column_config.TextColumn(_umcol, width='small'),
                                         '馬名': st.column_config.TextColumn('馬名'),
                                         'オッズ': st.column_config.NumberColumn('オッズ', format="%.1f"),
                                         '推奨掛け金(円)': st.column_config.NumberColumn('推奨掛け金(円)', format="%d"),
                                         '的中払戻(円)': st.column_config.NumberColumn('的中払戻(円)', format="%d"),
                                     })
                        st.caption("💡『人気組に厚く(払戻均等)』はオッズの逆数で配分＝人気組ほど多く賭け、"
                                   "どの組が当たっても払戻が近くなります。ﾄﾘｶﾞﾐ⚠=その組が的中しても合計購入額を"
                                   "下回る（人気すぎ）。※配分は資金管理の型であって予測エッジ(妙味)ではありません。")
                    else:
                        st.warning("対象のライブオッズが取得できませんでした（発売前・終了レースは3連複/3連単の"
                                   "オッズが出ないことがあります）。下のフラット表示をご利用ください。")
                        _omap = None
                if not _omap:
                    _unit = st.number_input("1点あたり(円)", min_value=100, max_value=10000,
                                            value=100, step=100, key="kf_form_unit")
                    st.info(f"{_form_kind} 買い目 {len(_trios)}点 × {int(_unit)}円 = "
                            f"合計 {len(_trios) * int(_unit):,}円"
                            "（「💴 オッズ取得＆配分」を押すと、オッズに応じた推奨掛け金を表示します）")
                    _bl = pd.DataFrame([{
                        '馬番': _sep.join(str(u) for u in t),
                        '馬名': _nsep.join(f"({u}){_name_of.get(u, '')}" for u in t),
                    } for t in _trios])
                    st.dataframe(_bl, hide_index=True, use_container_width=True, height=240,
                                 column_config={
                                     '馬番': st.column_config.TextColumn(_umcol, width='small'),
                                     '馬名': st.column_config.TextColumn('馬名'),
                                 })
            else:
                st.info(f"各列に馬を選ぶと{_form_kind}の買い目が生成されます（3頭が相異なる組合せ）。")
            # 🎰 買い方最適化へ連携（軸=1列目/1着、相手1=2列目/2着、相手2=3列目/3着）
            if _c1:
                if st.button("🎰 この選択を買い方最適化へ送る（軸=1列目 / 相手1=2列目 / 相手2=3列目）",
                             key="kf_form_to_bo"):
                    _axis_link = [int(u) for u in _c1]
                    _mate1_link = [int(u) for u in _c2 if int(u) not in _axis_link]
                    _mate2_link = [int(u) for u in _c3
                                   if int(u) not in _axis_link and int(u) not in _mate1_link]
                    st.session_state['bo_axis'] = _axis_link
                    st.session_state['bo_mate1'] = _mate1_link
                    st.session_state['bo_mate2'] = _mate2_link
                    st.success("🎰 買い方最適化の軸・相手1・相手2に反映しました。"
                               "下の🎰パネルで「▶ ライブオッズ取得＆EV計算」を押してください。")

            # ===== 🎯 流し（軸固定 × 相手・絞った馬から選択）=====
            st.markdown("#### 🎯 流し（軸固定 × 相手）")
            st.caption("フォーメーションと別に、軸を固定して相手に流す買い方。馬・頭数は絞った馬(✅残し/🛟ボーダー残し/🎯穴)から自分で選びます。")
            _nag_pool = sorted(set(_keep_um + _border_um + ([_ana_um] if _ana_um is not None else [])))
            if not _nag_pool:
                st.info("先に「▶ 強適消去エンジンを実行」を押して残し馬を確定してください。")
            else:
                _ngc1, _ngc2 = st.columns([1.4, 1])
                with _ngc1:
                    _nag_kind = st.radio("券種", ["3連複", "馬連", "ワイド", "馬単", "3連単"],
                                         horizontal=True, key="kf_nag_kind")
                with _ngc2:
                    _ax_opts = ["1軸", "2軸"] if _nag_kind in ("3連複", "3連単") else ["1軸"]
                    _nag_axn = st.radio("軸数", _ax_opts, horizontal=True, key=f"kf_nag_axn_{_nag_kind}")
                _need_ax = 2 if _nag_axn == "2軸" else 1
                _nag_axis = st.multiselect(f"軸（{_need_ax}頭・絞った馬から）", _nag_pool,
                                           format_func=_lab, key="kf_nag_axis", max_selections=_need_ax)
                _ax = [int(u) for u in _nag_axis][:_need_ax]
                _mate_opts = [u for u in _nag_pool if u not in _ax]
                _nag_mate = st.multiselect("相手（絞った馬から）", _mate_opts, default=_mate_opts,
                                           format_func=_lab, key="kf_nag_mate")
                _mt = [int(u) for u in _nag_mate if int(u) not in _ax]
                from itertools import combinations as _comb_n, permutations as _perm_n
                _nc = []
                if len(_ax) >= _need_ax and _mt:
                    if _nag_kind == "3連複":
                        if _need_ax == 2:
                            _nc = [tuple(sorted((_ax[0], _ax[1], m))) for m in _mt]
                        else:
                            _nc = [tuple(sorted((_ax[0],) + pair)) for pair in _comb_n(_mt, 2)]
                    elif _nag_kind in ("馬連", "ワイド"):
                        _nc = [tuple(sorted((_ax[0], m))) for m in _mt]
                    elif _nag_kind == "馬単":      # 軸→相手(1着固定)
                        _nc = [(_ax[0], m) for m in _mt]
                    elif _nag_kind == "3連単":
                        if _need_ax == 2:          # 1-2着に軸2頭固定 → 3着相手
                            _nc = [(_ax[0], _ax[1], m) for m in _mt]
                        else:                      # 軸1着固定 → 相手から2着3着(順列)
                            _nc = [(_ax[0],) + p for p in _perm_n(_mt, 2)]
                if _nc:
                    _sep = "→" if _nag_kind in ("馬単", "3連単") else "-"
                    _nrows = [{'買い目': _sep.join(str(x) for x in c),
                               '馬名': (" " + _sep + " ").join(_name_of.get(x, '') for x in c)}
                              for c in _nc]
                    st.dataframe(pd.DataFrame(_nrows), hide_index=True, use_container_width=True)
                    st.success(f"{_nag_kind} {_nag_axn}流し ＝ **{len(_nc)}点**（軸{len(_ax)}頭 × 相手{len(_mt)}頭）")
                    if st.button("🎰 この流しを買い方最適化へ送る（軸 / 相手）", key="kf_nag_to_bo"):
                        st.session_state['bo_axis'] = _ax
                        st.session_state['bo_mate1'] = _mt
                        st.session_state['bo_mate2'] = []
                        st.success("🎰 買い方最適化の軸・相手1に反映しました。下の🎰パネルで「▶ ライブオッズ取得＆EV計算」を。")
                else:
                    st.info("軸と相手を選ぶと流し買い目（点数）が出ます。")

            # ===== 🎰 買い方最適化（券種EV比較・配分）=====
            st.markdown("#### 🎰 買い方最適化（券種EV比較・配分）")
            st.caption("Projected Scoreを市場本命の勝率に較正→Harvilleで連系的中率を推定→EV=的中率×オッズ。"
                       "EVは未検証モデル確率による『目安』(EV>1.0=モデルが市場より高評価=妙味)。配分はハーフケリー。")
            from core import bet_optimizer as _bo
            _bokey = f"bo_scores_{race_id_input}"
            if _bokey not in st.session_state:
                try:
                    _vc = str(race_id_input)[4:6]
                    _pi = 0 if _vc in ['04', '05', '07'] else (1 if _vc in ['01', '02', '03', '06', '10'] else 2)
                    _pt = ["✨ 直線が長い・差し有利 (東京/外回り 等)", "✨ 小回り・先行有利 (中山/小倉/札幌 等)", "✨ 標準 (バランス)"][_pi]
                    _sdf = calculator.calculate_battle_score(df.copy())
                    _sdf = calculator.calculate_n_index(_sdf)
                    _sdf = calculator.calculate_strength_suitability(_sdf, _pt)
                    _scol = 'Projected Score' if 'Projected Score' in _sdf.columns else 'BattleScore'
                    _sc = {}
                    for _, rr in _sdf.iterrows():
                        try:
                            _sc[int(pd.to_numeric(rr.get('Umaban'), errors='coerce'))] = float(pd.to_numeric(rr.get(_scol), errors='coerce'))
                        except Exception:
                            pass
                    st.session_state[_bokey] = _sc
                except Exception as _e:
                    st.session_state[_bokey] = {}
                    st.warning(f"スコア計算エラー: {_e}")
            _scores = {u: s for u, s in st.session_state.get(_bokey, {}).items() if s == s}
            if not _scores:
                st.info("買い方最適化にはモデルスコアが必要です（出馬表を取得し直してください）。")
            else:
                _ordered = sorted(_scores, key=lambda u: -_scores[u])
                _all_um_bo = [int(x) for x in _edf['馬番'].tolist()]
                _def_axis = _ordered[:2]
                _def_mate1 = [u for u in _ordered[2:5]]
                _def_mate2 = [u for u in _ordered[5:8]]
                if _anauma is not None:
                    _au = int(_anauma['馬番'])
                    if _au not in _def_mate1 and _au not in _def_mate2:
                        _def_mate2 = _def_mate2 + [_au]
                # 相手カードのpill色をフォーメーションと揃える(相手1=#008080 / 相手2=#0000ff)
                st.markdown(
                    "<style>"
                    ".st-key-bo_mate1 span[data-baseweb=\"tag\"]{background-color:#008080 !important;}"
                    ".st-key-bo_mate2 span[data-baseweb=\"tag\"]{background-color:#0000ff !important;}"
                    ".st-key-bo_mate1 span[data-baseweb=\"tag\"] *,"
                    ".st-key-bo_mate2 span[data-baseweb=\"tag\"] *{color:#ffffff !important;}"
                    "</style>",
                    unsafe_allow_html=True)
                # ── 入力カード(軸選択 | 計算設定) ──
                _top_l, _top_r = st.columns([1.3, 1])
                with _top_l:
                    with st.container(border=True):
                        st.markdown("**🎯 軸馬選択**")
                        _axis = st.multiselect("軸", _all_um_bo, default=_def_axis,
                                               format_func=_lab, key="bo_axis",
                                               label_visibility="collapsed",
                                               placeholder="馬を入力…")
                with _top_r:
                    with st.container(border=True):
                        st.markdown("**⚙️ 計算設定**")
                        _budget = st.number_input("予算(円)", 100, 1000000, 3000, 100, key="bo_budget")
                        _bankroll = st.number_input("総資金(ケリー基準用・円)", 1000, 100000000,
                                                    100000, 1000, key="bo_bank")
                        _amode = st.selectbox("配分方式", ["kelly", "払戻均等", "均等"], key="bo_mode")
                # ── 相手選択カード(相手1=2列目/2着・相手2=3列目/3着。横並びで詰める) ──
                _mid_l, _mid_r = st.columns(2)
                with _mid_l:
                    with st.container(border=True):
                        st.markdown("**🤝 相手馬選択1**（対抗 / 2着）")
                        _mate1 = st.multiselect("相手1", _all_um_bo, default=_def_mate1,
                                                format_func=_lab, key="bo_mate1",
                                                label_visibility="collapsed",
                                                placeholder="追加…")
                with _mid_r:
                    with st.container(border=True):
                        st.markdown("**🤝 相手馬選択2**（押さえ・穴 / 3着）")
                        _mate2 = st.multiselect("相手2", _all_um_bo, default=_def_mate2,
                                                format_func=_lab, key="bo_mate2",
                                                label_visibility="collapsed",
                                                placeholder="追加…")
                # EV計算用に相手1+相手2を統合(軸と重複は除く)
                _mate = [int(u) for u in (list(_mate1) + list(_mate2))
                         if int(u) not in [int(a) for a in _axis]]
                _mate = list(dict.fromkeys(_mate))
                # ── モデル寄与度 + 実行ボタン ──
                _sl_l, _sl_r = st.columns([2, 1])
                with _sl_l:
                    _alpha = st.slider("モデル寄与度 α（0=市場どおり / 1=モデル全振り）", 0.0, 1.0, 0.35, 0.05,
                                       key="bo_alpha",
                                       help="市場オッズを事前分布にしたモデル確率の混ぜ具合。"
                                            "小さいほど市場を尊重し外れ馬のEV暴発を抑制。既定0.35=市場寄り。")
                with _sl_r:
                    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                    _run_bo = st.button("▶ ライブオッズ取得＆EV計算", key="bo_run",
                                        use_container_width=True, type="primary")
                if _run_bo:
                    with st.spinner("ライブオッズ取得中（単複/馬連/ワイド/3連複）..."):
                        _ok = {}
                        try:
                            _ws = scraper.fetch_win_odds(race_id_input)
                            _ok['tan'] = {int(k): float(v) for k, v in (_ws.items() if _ws is not None else [])}
                        except Exception:
                            _ok['tan'] = {}
                        try:
                            _pl = scraper.fetch_place_odds_api(race_id_input) or {}
                            _ok['fuku'] = {u: d.get('Mid') for u, d in _pl.items() if d.get('Mid')}
                        except Exception:
                            _ok['fuku'] = {}
                        for _kk in ('umaren', 'wide'):
                            try:
                                _ok[_kk] = scraper.fetch_combo_odds(race_id_input, _kk)
                            except Exception:
                                _ok[_kk] = {}
                        try:
                            _tr = scraper.fetch_sanrenpuku_odds(race_id_input)
                            _ok['trio'] = {frozenset(it['Horses']): it['Odds'] for it in (_tr or [])
                                           if it.get('Horses') and len(it['Horses']) == 3 and it.get('Odds')}
                        except Exception:
                            _ok['trio'] = {}
                        st.session_state[f"bo_odds_{race_id_input}"] = _ok
                _ok = st.session_state.get(f"bo_odds_{race_id_input}")
                if not _ok:
                    st.info("「▶ ライブオッズ取得＆EV計算」を押すと、各券種のEVと推奨配分を表示します。")
                else:
                    _gotn = {k: len(v) for k, v in _ok.items() if v}
                    _wp = _bo.blended_win_probs(_scores, _ok.get('tan') or {}, alpha=_alpha)
                    _allu = list(_scores)
                    st.caption(f"モデル寄与度α={_alpha:.2f}（市場prior×モデル幾何ブレンド）／取得オッズ: "
                               + "・".join(f"{k}{n}" for k, n in _gotn.items()))
                    # 💰 BetSync 連携: 勝率×オッズを EV配分パネル/台帳へ供給
                    try:
                        _tan = _ok.get('tan') or {}
                        _name_map = {}
                        try:
                            for _, _rr in df.iterrows():
                                _name_map[int(pd.to_numeric(_rr.get('Umaban'), errors='coerce'))] = str(_rr.get('Name', ''))
                        except Exception:
                            pass
                        _ev_feed = []
                        for _u in sorted(_wp, key=lambda x: -_wp[x]):
                            _o = _tan.get(_u)
                            if _o and float(_o) > 1:
                                _ev_feed.append({'umaban': int(_u), 'bamei': _name_map.get(int(_u), ''),
                                                 'p': float(_wp[_u]), 'odds': float(_o)})
                        if _ev_feed:
                            st.session_state['bs_ev_feed'] = {
                                'race_id': str(race_id_input), 'rows': _ev_feed,
                                'alpha': _alpha, 'ts': datetime.now().strftime('%m/%d %H:%M'),
                            }
                    except Exception:
                        pass
                    _types = [('tan', '単勝'), ('fuku', '複勝'), ('umaren', '馬連'), ('wide', 'ワイド'), ('trio', '3連複')]
                    _summary, _all_bets = [], []
                    _missing = []
                    for _k, _lab2 in _types:
                        _om = _ok.get(_k) or {}
                        if not _om:
                            _missing.append(_lab2)
                            continue
                        _bets = _bo.enumerate_bets(_k, _axis, _mate, _wp, _om, _allu, max_points=10)
                        if not _bets:
                            _missing.append(_lab2)
                            continue
                        _b0 = _bets[0]
                        _summary.append({'券種': _lab2, '最良買い目': _b0['label'],
                                         'EV(目安)': round(_b0['ev'], 2),
                                         '的中率': f"{_b0['prob'] * 100:.1f}%", 'オッズ': _b0['odds']})
                        _all_bets.append((_lab2, _k, _bets))
                    if _missing:
                        st.info("📭 オッズ未取得で比較から除外: " + "・".join(_missing)
                                + "。馬連/ワイド/3連複の**ライブオッズは『発売中』のレースのみ**取得できます"
                                  "（発売前・終了レースは単勝/複勝の最終オッズしか出ないことがあります）。"
                                  "発売中のレースで「▶ ライブオッズ取得」を押すと全券種が並びます。")
                    if not _summary:
                        st.warning("買い目が生成できませんでした（軸/相手の選択かオッズ取得を確認）。")
                    else:
                        st.markdown("**券種別ベストEV比較**")
                        _sumdf = pd.DataFrame(_summary).sort_values('EV(目安)', ascending=False)

                        def _ev_color(s):
                            return ['color:#2e7d32;font-weight:bold' if v >= 1.0 else 'color:#b71c1c' for v in s]
                        _bo_colcfg = {'オッズ': st.column_config.NumberColumn('オッズ', format="%.1f"),
                                      'EV(目安)': st.column_config.NumberColumn('EV(目安)', format="%.2f")}
                        try:
                            st.dataframe(_sumdf.style.apply(_ev_color, subset=['EV(目安)']),
                                         hide_index=True, use_container_width=True, column_config=_bo_colcfg)
                        except Exception:
                            st.dataframe(_sumdf, hide_index=True, use_container_width=True, column_config=_bo_colcfg)
                        _pick = st.selectbox("配分する券種", [x[0] for x in _all_bets], key="bo_pick")
                        _sel = next((b for (lb, k, b) in _all_bets if lb == _pick), [])
                        _posev = [b for b in _sel if b['ev'] >= 1.0] or _sel[:3]
                        _alloc = _bo.allocate([b for b in _posev], _budget, mode=_amode, bankroll=_bankroll)
                        _bl = pd.DataFrame([{
                            '買い目': b['label'],
                            'EV(目安)': round(b['ev'], 2),
                            '的中率': f"{b['prob'] * 100:.1f}%",
                            'オッズ': b['odds'],
                            '購入額': b.get('stake', 0),
                            '的中払戻': b.get('payout_if_hit', 0),
                            'ﾄﾘｶﾞﾐ': '⚠' if b.get('toriga') else '',
                        } for b in _posev])
                        st.dataframe(_bl, hide_index=True, use_container_width=True,
                                     column_config={'オッズ': st.column_config.NumberColumn('オッズ', format="%.1f"),
                                                    'EV(目安)': st.column_config.NumberColumn('EV(目安)', format="%.2f")})
                        _syn = _alloc.get('synthetic_odds')
                        _res_l, _res_r = st.columns([3, 1])
                        with _res_l:
                            st.success(f"【{_pick}・{_amode}】合計 {_alloc['total']:,}円／合成オッズ "
                                       f"{(str(_syn)+'倍') if _syn else '-'}／期待回収 "
                                       f"{(str(int(_alloc['expected_value']*100))+'%') if _alloc.get('expected_value') else '-'}"
                                       f"／買い目 {len(_posev)}点")
                        with _res_r:
                            _csv = _bl.to_csv(index=False).encode('utf-8-sig')
                            st.download_button("💾 保存・エクスポート", _csv,
                                               file_name=f"buy_{race_id_input}_{_pick}_{_amode}.csv",
                                               mime="text/csv", key="bo_export",
                                               use_container_width=True)
                        st.caption("⚠ﾄﾘｶﾞﾐ=的中しても合計購入額を下回る点。EV/期待回収は未検証モデル確率(Projected Score)の目安。"
                                   "特に人気薄でEVが極端に高い馬はモデルの過大評価の可能性が高い。"
                                   "実証エッジは✨Scannerの妙味シグナル(単複乖離/断層/黄金ライン)側にある。"
                                   "この画面は券種比較と配分(合成オッズ/ﾄﾘｶﾞﾐ/ケリー)の構造づくりに使うのが安全。")

                # ── 📜 確定配当で回顧比較（終了レース向け）──
                st.markdown("##### 📜 確定配当で回顧比較（終了レース向け）")
                st.caption("終了後は全組合せのライブオッズが消えるため、全券種の『当選した確定配当』を表示します。"
                           "上で選んだ軸＋相手で当選をカバーできていたか(✅)も判定（回顧用・事前EVではありません）。")
                if st.button("📜 確定配当を取得", key="bo_payout_run"):
                    with st.spinner("結果ページから確定配当を取得中..."):
                        try:
                            st.session_state[f"bo_payout_{race_id_input}"] = scraper.fetch_race_payouts(race_id_input)
                        except Exception as _pe:
                            st.session_state[f"bo_payout_{race_id_input}"] = {}
                            st.warning(f"確定配当取得エラー: {_pe}")
                _pay = st.session_state.get(f"bo_payout_{race_id_input}")
                if _pay:
                    _pool = set(int(u) for u in _axis) | set(int(u) for u in _mate)
                    _knames = {'tan': '単勝', 'fuku': '複勝', 'wakuren': '枠連', 'umaren': '馬連',
                               'wide': 'ワイド', 'umatan': '馬単', 'trio': '3連複', 'trifecta': '3連単'}
                    _prows = []
                    for _kk in ['tan', 'fuku', 'wakuren', 'umaren', 'wide', 'umatan', 'trio', 'trifecta']:
                        for _it in _pay.get(_kk, []):
                            _cb = _it.get('combo', [])
                            _cov = '✅' if _cb and all(c in _pool for c in _cb) else '✗'
                            _prows.append({'券種': _knames.get(_kk, _kk),
                                           '当選': '-'.join(str(c) for c in _cb),
                                           '確定配当(倍)': _it.get('odds'),
                                           '人気': _it.get('pop'),
                                           '選択でカバー': _cov})
                    if _prows:
                        _pdf = pd.DataFrame(_prows)

                        def _cov_color(s):
                            return ['color:#2e7d32;font-weight:bold' if v == '✅'
                                    else 'color:#b71c1c' for v in s]
                        try:
                            st.dataframe(_pdf.style.apply(_cov_color, subset=['選択でカバー']),
                                         hide_index=True, use_container_width=True,
                                         column_config={'確定配当(倍)': st.column_config.NumberColumn(
                                             '確定配当(倍)', format="%.1f")})
                        except Exception:
                            st.dataframe(_pdf, hide_index=True, use_container_width=True)
                        _hit = [r for r in _prows if r['選択でカバー'] == '✅']
                        if _hit:
                            _best = max(_hit, key=lambda r: (r['確定配当(倍)'] or 0))
                            st.success(f"選択でカバーできた当選: {len(_hit)}件／最高配当 "
                                       f"{_best['券種']} {_best['当選']} = {_best['確定配当(倍)']}倍")
                        else:
                            st.info("今の軸＋相手では、どの券種の当選もカバーできていません（取りこぼし）。")
                        st.caption("✅=軸＋相手の選択に当選馬が全頭含まれていた（=その券種を手広く買っていれば的中圏）。"
                                   "✗=選択外。これは回顧で、実際の的中可否は買い目の点数構成に依存します。")
                    else:
                        st.caption("確定配当が取得できませんでした（未確定/古いレースの可能性）。")
                else:
                    st.caption("「📜 確定配当を取得」を押すと、終了レースの全券種の当選配当を表示します。")

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

    # 中央(JRA)競馬場コード [4:6] と場名。地方(NAR)はこれ以外＝スキャン対象外。
    _JRA_CODES = {'01', '02', '03', '04', '05', '06', '07', '08', '09', '10'}
    _JRA_VENUE = {'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
                  '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'}

    def _venue_label(rid):
        """race_id → '函館11R' のような 場名+レース番号。"""
        s = str(rid)
        v = _JRA_VENUE.get(s[4:6], s[4:6] if len(s) >= 6 else '?')
        try:
            return f"{v}{int(s[10:12])}R"
        except Exception:
            return v

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
        st.markdown("**🎯 妙味スキャン設定**")
        st.caption("👶 はじめての方は下の2つはそのままでOK。上位に出たレースから見てください。")

        # 妙味度＝レースの荒れ度。初心者向けに『どのくらい荒れそうか』を言葉で選ぶ
        _VAL_PRESETS = {
            "🟢 ぜんぶ表示（おまかせ）": 0,
            "🟡 やや荒れそうなレースを上に（おすすめ）": 25,
            "🟠 荒れ妙味レースだけ": 40,
            "🔴 大荒れ候補だけ": 55,
        }
        _val_choice = st.selectbox(
            "レースの荒れ度（中穴の出やすさ）",
            list(_VAL_PRESETS.keys()),
            index=1,
            key="scanner_min_value_sel",
            help="頭数・1番人気オッズ・上位拮抗・構造条件から自動算出する『荒れ度』。"
                 "荒れるほど中穴(人気薄)の妙味が出やすい。数字が分からなくても言葉で選べます。"
        )
        min_value_score = _VAL_PRESETS[_val_choice]

        # 妙味馬の頭数＝過小評価された馬が何頭いるレースを優先するか
        _VH_PRESETS = {
            "こだわらない": 0,
            "妙味馬が1頭以上いるレースを優先（おすすめ）": 1,
            "2頭以上いるレースを優先": 2,
            "3頭以上いるレースを優先": 3,
        }
        _vh_choice = st.selectbox(
            "過小評価された『妙味馬』の数",
            list(_VH_PRESETS.keys()),
            index=1,
            key="scanner_min_vhorses_sel",
            help="単複乖離(単勝は長いのに複勝は短い) or 黄金ライン/厩舎当コース🔴 を持つ"
                 "『人気以上に走れそうな馬』の頭数。多いレースほど買い目を組みやすい。"
        )
        min_value_horses = _VH_PRESETS[_vh_choice]
        trio_filter = st.radio(
            "🎯 3連複 決着タイプで絞り込み",
            ["すべて", "本線向き（人気2頭軸＝鉄板+①）", "②穴妙味向き（人気-穴-穴）"],
            key="scanner_trio_filter",
            help="検証済(scripts/condition_arare_backtest.py)。②向き=ハンデ戦/フルゲート/混戦/ハイ想定。"
                 "本線向き=少頭数8-10頭/鉄板1番人気/スロー想定。牝馬限定・ダートは織込み済みでスコア非加算。"
        )
        cond_filter = st.multiselect(
            "🏷 特別条件で絞り込み",
            ["牝馬限定戦", "ハンデ戦", "新馬戦", "ダート戦"],
            default=[],
            key="scanner_cond_filter",
            help="選んだ条件を含むレースのみ表示。ハンデ戦は荒れ独立エッジ(検証済)、"
                 "牝馬限定/ダートはオッズ織込み済み(検索用)。"
        )
        hide_skip = st.checkbox("見送りレースを隠す", value=False, key="scanner_hide_skip",
                                help="新馬/未勝利/2歳/障害/少頭数/単勝1倍台大本命を除外")
        do_factor = st.checkbox("妙味馬ファクター照合（やや重い）", value=True, key="scanner_do_factor",
                                help="各馬の黄金ライン/厩舎当コース/危険材料をDB照合。OFFなら単複乖離のみで高速。")
        do_place = st.checkbox("複勝オッズ取得（単複乖離判定）", value=True, key="scanner_do_place",
                               help="ライブ複勝オッズを取得し『単勝≥10×複勝≤3』の妙味馬を検知。")

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
                    _jra_list = [r for r in race_list if str(r['race_id'])[4:6] in _JRA_CODES]
                    _dropped = len(race_list) - len(_jra_list)
                    st.session_state['scanner_auto_ids'] = [r['race_id'] for r in _jra_list]
                    st.session_state['scanner_name_map'] = {r['race_id']: r['race_name'] for r in _jra_list}
                    if _dropped:
                        st.success(f"中央(JRA) {len(_jra_list)} 件を取得しました（地方競馬 {_dropped} 件は対象外として除外）。")
                    else:
                        st.success(f"{len(_jra_list)} 件のレースを取得しました。")
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
        _nar_dropped = [r for r in race_ids if str(r)[4:6] not in _JRA_CODES]
        race_ids = [r for r in race_ids if str(r)[4:6] in _JRA_CODES]
        if _nar_dropped:
            st.info(f"地方競馬(NAR) {len(_nar_dropped)} 件は対象外として除外しました（中央のみスキャン）。")

        if not race_ids:
            st.warning("有効なレースIDが見つかりませんでした。12桁の数字またはURLを入力してください（中央競馬のみ対応）。")
        else:
            from core import value_scanner as vs
            from core import jockey_jv as jj_scan
            progress_bar = st.progress(0)
            status_text = st.empty()
            results = []   # list of dicts

            for i, rid in enumerate(race_ids):
                status_text.text(f"スキャン中... {rid}  ({i+1}/{len(race_ids)})")
                try:
                    df_r = scraper.get_race_data(rid)
                    if df_r is None or df_r.empty:
                        raise ValueError("データなし")
                    meta = dict(getattr(df_r, 'attrs', {}).get('metadata', {}) or {})
                    jyo = str(rid)[4:6]
                    surf = str(df_r['CurrentSurface'].iloc[0]) if 'CurrentSurface' in df_r.columns and not df_r.empty else '芝'
                    try:
                        dist = int(pd.to_numeric(df_r['CurrentDistance'].iloc[0], errors='coerce'))
                    except Exception:
                        dist = None
                    dv = str(meta.get('date_val', '') or '')
                    month = int(dv[4:6]) if len(dv) >= 6 and dv[4:6].isdigit() else 0
                    miny = str(int(dv[:4]) - 3) if dv[:4].isdigit() else None

                    odds_list = [o for o in (pd.to_numeric(df_r['Odds'], errors='coerce').dropna().tolist()
                                             if 'Odds' in df_r.columns else []) if o > 0]
                    n_h = len(df_r)
                    min_win = min(odds_list) if odds_list else None

                    # race name
                    race_title = st.session_state.get('scanner_name_map', {}).get(rid, "")
                    if not race_title or race_title == rid:
                        race_title = str(meta.get('RaceName', '') or '')
                    if not race_title or race_title.lower() in ("unknown race", "nan"):
                        race_title = f"Race {rid[-4:]}"

                    # 事前ペース強度(テン速力ベース・検証済: ハイ想定→荒れ寄り)
                    _pint = None
                    try:
                        from core import pace_map as _pmap_scan
                        _scan_names = [str(x) for x in df_r['Name'].tolist()] if 'Name' in df_r.columns else []
                        _prof_ts = _pmap_scan.fetch_ten_speed_profiles(_scan_names, surface=surf, distance=dist)
                        if _prof_ts:
                            _pint = _pmap_scan.predict_pace_intensity(_prof_ts, dist, surf)
                    except Exception:
                        _pint = None
                    _pace_z = _pint.get('z') if _pint else None

                    rv = vs.race_value_score(odds_list, meta, jyo, surf, dist, n_h, pace_z=_pace_z)
                    skips = vs.race_skip_reasons(meta, n_h, surf, race_title, min_win)
                    # 3連複 決着タイプ傾向(本線⇔②穴妙味・検証済) と 特別条件
                    lean = vs.trio_lean(meta, n_h, rv['fav_odds'], _pace_z)
                    _conds = []
                    if meta.get('is_fillies'):
                        _conds.append('牝馬限定戦')
                    if meta.get('is_handicap') or meta.get('weight_rule') == 'ハンデ':
                        _conds.append('ハンデ戦')
                    if '新馬' in str(meta.get('class', '')) or any('新馬' in s for s in skips):
                        _conds.append('新馬戦')
                    if 'ダ' in str(surf):
                        _conds.append('ダート戦')

                    # live place odds (単複乖離用)
                    place_map = {}
                    if do_place:
                        try:
                            place_map = scraper.fetch_place_odds_api(rid) or {}
                        except Exception:
                            place_map = {}

                    # オッズ断層(強グループ末端の堅め妙味・90s検証+3.9pp)
                    odds_by_um = {}
                    if 'Umaban' in df_r.columns and 'Odds' in df_r.columns:
                        for _, _hr in df_r.iterrows():
                            try:
                                _u = int(pd.to_numeric(_hr.get('Umaban'), errors='coerce'))
                                _o = float(pd.to_numeric(_hr.get('Odds'), errors='coerce'))
                                if _u and _o > 0:
                                    odds_by_um[_u] = _o
                            except Exception:
                                pass
                    gap_anchors = vs.odds_gap_anchors(odds_by_um)

                    value_horses, danger_horses = [], []
                    for _, hr in df_r.iterrows():
                        try:
                            um = int(pd.to_numeric(hr.get('Umaban'), errors='coerce'))
                        except Exception:
                            um = 0
                        nm = str(hr.get('Name', '') or '')
                        pm = (place_map.get(um) or {}).get('Mid') if place_map else None
                        if do_factor:
                            f = vs.horse_value_factors(hr, jj_scan, jyo, surf, dist, month, miny,
                                                       place_mid=pm, date_val=dv,
                                                       gap_anchor=(um in gap_anchors))
                        else:
                            lvl, txt = vs.tanpuku_divergence(hr.get('Odds'), pm) if pm else (0, '')
                            _pop = pd.to_numeric(hr.get('Popularity'), errors='coerce')
                            _od = pd.to_numeric(hr.get('Odds'), errors='coerce')
                            _ga = um in gap_anchors
                            _pos = ([txt] if txt else []) + (['オッズ断層上位'] if _ga else [])
                            f = {'pos': _pos, 'neg': [], 'has_pos': bool(_pos),
                                 'has_neg': False, 'div_level': lvl, 'anchor': _ga,
                                 'pop': int(_pop) if pd.notnull(_pop) else None,
                                 'odds': float(_od) if pd.notnull(_od) else None}
                        pop = f['pop']
                        od = f['odds']
                        # オッズ未確定/出走取消(オッズ≤0・人気9999等の番兵)は判定対象外
                        valid = bool(od and od > 0 and pop and pop < 90)
                        if not valid:
                            continue
                        # 妙味馬: 単複乖離 or 断層上位(堅め) or (＋ファクター × 人気薄≥6)  ← 検証済の妙味定義
                        if f['div_level'] >= 1 or f.get('anchor') or (f['has_pos'] and pop >= 6):
                            value_horses.append({'um': um, 'name': nm, 'pop': pop,
                                                 'odds': od, 'why': ' / '.join(f['pos']) or '-',
                                                 'div': f['div_level'], 'anchor': bool(f.get('anchor'))})
                        # 危険な人気馬: −ファクター × 人気≤3
                        if f['has_neg'] and pop <= 3:
                            danger_horses.append({'um': um, 'name': nm, 'pop': pop,
                                                  'why': ' / '.join(f['neg'])})

                    # ランキング指標: 妙味馬数 と 妙味度
                    results.append({
                        "id": rid, "title": str(race_title), "error": None,
                        "vscore": rv['score'], "vlabel": rv['label'], "breakdown": rv['breakdown'],
                        "fav_odds": rv['fav_odds'], "skips": skips,
                        "value_horses": sorted(value_horses, key=lambda x: (-x['div'], -(x['odds'] or 0))),
                        "danger_horses": danger_horses, "n_h": n_h, "surf": surf, "dist": dist,
                        "pace_label": (_pint or {}).get('label'), "pace_z": _pace_z,
                        "lean": lean, "conds": _conds,
                    })
                except Exception as e:
                    import traceback
                    err_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
                    logger.error(f"Scanner error for {rid}: {err_msg}")
                    results.append({"id": rid, "title": rid, "error": str(e), "traceback": err_msg})

                progress_bar.progress((i + 1) / len(race_ids))

            status_text.text(f"✅ スキャン完了！ {len(race_ids)}件処理しました。")

            errors = [r for r in results if r.get('error')]
            valid = [r for r in results if not r.get('error')]
            if hide_skip:
                valid = [r for r in valid if not r['skips']]
            # 3連複 決着タイプ絞り込み(検証済 trio_lean)
            if trio_filter.startswith("本線"):
                valid = [r for r in valid if (r.get('lean') or {}).get('lean') == '本線向き']
            elif trio_filter.startswith("②"):
                valid = [r for r in valid if (r.get('lean') or {}).get('lean') == '②穴妙味向き']
            # 特別条件絞り込み(選択した全条件を含むレースのみ＝AND)
            if cond_filter:
                valid = [r for r in valid if all(c in (r.get('conds') or []) for c in cond_filter)]

            # 並び替え: ①見送りでない ②妙味馬がしきい値以上 ③妙味度しきい値以上 ④妙味馬数 ⑤妙味度
            def _rank_key(r):
                n_v = len(r['value_horses'])
                return (
                    0 if r['skips'] else 1,
                    1 if n_v >= min_value_horses and min_value_horses > 0 else 0,
                    1 if r['vscore'] >= min_value_score else 0,
                    n_v, r['vscore'],
                )
            valid.sort(key=_rank_key, reverse=True)

            if errors:
                with st.expander(f"✨ スキップ(取得エラー) {len(errors)}件", expanded=False):
                    for r in errors:
                        st.markdown(f"- `{r['id']}` : {r['error']}")
                        if 'traceback' in r:
                            st.code(r['traceback'], language="python")

            n_hot = sum(1 for r in valid if len(r['value_horses']) >= max(1, min_value_horses)
                        and r['vscore'] >= min_value_score and not r['skips'])
            st.markdown(f"### 💡 スキャン結果 {len(valid)} 件　／　🎯 妙味レース候補 {n_hot} 件")
            st.caption("妙味度＝頭数/1番人気オッズ/上位拮抗/構造条件の集約（荒れ＝中穴妙味）。"
                       "妙味馬＝単複乖離(単≥10×複≤3) or 黄金ライン/厩舎当コース🔴の過小評価馬。")

            if not valid:
                st.info("条件に合致するレースが見つかりませんでした。")
            else:
                _VL_COLOR = {'S': ('#FF4500', '#2D0000'), 'A': ('#7FFF00', '#0B1F00'),
                             'B': ('#FFD700', '#1A1400'), 'C': ('#00C8FF', '#001A2D'),
                             'D': ('#888', '#111')}
                for r in valid:
                    n_v = len(r['value_horses'])
                    _lk = r['vlabel'][0]
                    color, bg = _VL_COLOR.get(_lk, ('#888', '#111'))
                    # ホバー説明（HTML title属性・改行は &#10;）
                    _bk = ('&#10;内訳: ' + ' / '.join(r['breakdown'])) if r.get('breakdown') else ''
                    _tip_v = ('妙味度：頭数・1番人気オッズ・上位拮抗・構造条件を集約したレースの荒れ度。'
                              '&#10;S/A/Bほど荒れ＝中穴妙味が出やすい。' + _bk)
                    _tip_vh = ('妙味馬：単複乖離(単≥10×複≤3)で単勝が過小評価、'
                               'またはオッズ断層上位・黄金ライン・厩舎当コース🔴 の過小評価馬。'
                               '&#10;連系の軸／紐に妙味（検証：勝率2.5→7%）。')
                    _tip_dg = ('危険な人気馬：初ダート・大幅距離変更・トップ騎手乗替・前走フロック等の'
                               '−ファクターを持つ人気≤3の馬。&#10;他の人気馬より3着内 約-2.6pp(z有意)。')
                    _tip_sk = ('見送り：新馬・未勝利・2歳・障害・少頭数・単勝1倍台大本命など、'
                               '構造的に妙味が出にくいレース。')
                    badge = (f'<span title="{_tip_v}" style="background:{bg};color:{color};border:1px solid {color};'
                             f'border-radius:6px;padding:3px 10px;font-size:0.85em;font-weight:bold;cursor:help;">'
                             f'妙味度 {r["vscore"]:.0f}・{r["vlabel"]}</span>')
                    vh_badge = ''
                    if n_v:
                        vh_badge = (f'&nbsp;<span title="{_tip_vh}" style="background:#0B1F00;color:#7FFF00;border:1px solid #7FFF00;'
                                    f'border-radius:6px;padding:3px 8px;font-size:0.82em;font-weight:bold;cursor:help;">🎯妙味馬 {n_v}</span>')
                    dg_badge = ''
                    if r['danger_horses']:
                        dg_badge = (f'&nbsp;<span title="{_tip_dg}" style="background:#2D0000;color:#FF7777;border:1px solid #FF7777;'
                                    f'border-radius:6px;padding:3px 8px;font-size:0.82em;cursor:help;">⚠️危険人気 {len(r["danger_horses"])}</span>')
                    # 3連複 決着タイプ傾向バッジ(本線⇔②穴妙味・検証済 trio_lean=ペース/頭数/ハンデ/オッズ集約)
                    pace_badge = ''
                    _lean = r.get('lean') or {}
                    _ll = _lean.get('lean')
                    if _ll == '②穴妙味向き':
                        _reasons = ' / '.join(_lean.get('pos', [])) or '構造条件'
                        _tip_ln = ('3連複②穴妙味狙い(人気-穴-穴)向き。検証(condition_arare_backtest 2021-25)で'
                                   '1番人気オッズを統制しても②型決着が増える独立エッジ。'
                                   '&#10;根拠: ' + _reasons + '&#10;穴選別は🎯妙味馬/🔥末脚シグナルで。')
                        pace_badge = (f'&nbsp;<span title="{_tip_ln}" style="background:#2D1A00;color:#FFB347;'
                                      f'border:1px solid #FFB347;border-radius:6px;padding:3px 8px;font-size:0.82em;'
                                      f'font-weight:bold;cursor:help;">②穴妙味向き</span>')
                    elif _ll == '本線向き':
                        _reasons = ' / '.join(_lean.get('neg', [])) or '構造条件'
                        _tip_ln = ('3連複本線(人気2頭軸＝鉄板+①)向き。検証で堅い決着が多い'
                                   '(少頭数は本線+8.4pp/z8.3)。&#10;根拠: ' + _reasons)
                        pace_badge = (f'&nbsp;<span title="{_tip_ln}" style="background:#00131A;color:#7FE0FF;'
                                      f'border:1px solid #66ccdd;border-radius:6px;padding:3px 8px;font-size:0.82em;'
                                      f'font-weight:bold;cursor:help;">🏁本線向き</span>')
                    # 特別条件タグ(色分け・牝馬限定/ダートは織込み済みで中立タグ)
                    _COND_COLOR = {'牝馬限定戦': '#FF6FB0', 'ハンデ戦': '#FF9F45',
                                   '新馬戦': '#6FB3FF', 'ダート戦': '#C9A66B'}
                    cond_badge = ''
                    for _c in r.get('conds', []):
                        _cc = _COND_COLOR.get(_c, '#aaa')
                        cond_badge += (f'&nbsp;<span style="color:{_cc};border:1px solid {_cc};'
                                       f'border-radius:6px;padding:2px 7px;font-size:0.78em;font-weight:bold;">{_c}</span>')
                    skip_badge = ''
                    if r['skips']:
                        skip_badge = (f'&nbsp;<span title="{_tip_sk}" style="background:#222;color:#aaa;border:1px solid #555;'
                                      f'border-radius:6px;padding:3px 8px;font-size:0.8em;cursor:help;">🚫見送り: {"・".join(r["skips"])}</span>')
                    dim = 'opacity:0.5;' if r['skips'] else ''
                    rn = r["title"] if r["title"] != r["id"] else "(レース名不明)"
                    _vlab = _venue_label(r["id"])
                    _nk_url = f'https://race.netkeiba.com/race/shutuba.html?race_id={r["id"]}'
                    header_html = (
                        f'<a href="{_nk_url}" target="_blank" title="netkeiba.comでこのレースの出馬表を開く" '
                        f'style="text-decoration:none;color:#4FC3F7;font-weight:bold;font-size:1.05em;">🔗{_vlab}</a>'
                        f'&nbsp;<span style="font-size:1.12em;font-weight:bold;color:inherit;">{rn}</span>'
                        f'&nbsp;&nbsp;{badge}{vh_badge}{dg_badge}{pace_badge}{cond_badge}{skip_badge}&nbsp;'
                        f'<span style="color:#888;font-size:0.8em;">{r["id"]}</span>'
                    )
                    st.html(f'<div style="margin-top:14px;padding:10px 0 4px;border-top:1px solid #333;{dim}">{header_html}</div>')

                    with st.expander("🔍 詳細を見る", expanded=False):
                        if r['value_horses']:
                            st.markdown("**🎯 妙味馬（過小評価）**")
                            for h in r['value_horses']:
                                mark = '★★' if h['div'] >= 2 else ('★' if h['div'] == 1 else '')
                                if h.get('anchor'):
                                    mark = (mark + '🛡️').strip()
                                od = f"{h['odds']:.1f}倍" if h['odds'] else '-'
                                pp = f"{h['pop']}人気" if h['pop'] else '-'
                                st.markdown(f"- {mark} **{h['um']} {h['name']}**（{pp}・{od}）… {h['why']}")
                            st.caption("★単複乖離=単勝が長いのに複勝が短い→単勝過小評価(検証:勝率2.5→7%)。"
                                       "🛡️オッズ断層上位=強グループ末端の堅め妙味(90s検証:3着内+3.9pp/単勝回収81%)。"
                                       "＋ファクター×人気薄=単勝回収108.8%(無印63.7%)。連系の軸/紐に妙味。")
                        else:
                            st.caption("🎯 妙味馬: 該当なし")
                        if r['danger_horses']:
                            st.error("⚠️ 危険な人気馬:\n" + "\n".join(
                                f"- {h['um']} {h['name']}（{h['pop']}人気）: {h['why']}" for h in r['danger_horses']))
                        if r['breakdown']:
                            st.caption("妙味度内訳: " + " / ".join(r['breakdown']))
                        st.markdown(f"✨ [このレースをシングルタブで詳細分析する](/?race_id={r['id']})"
                                    f"　｜　🔗 [netkeiba.comで開く](https://race.netkeiba.com/race/shutuba.html?race_id={r['id']})")





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

            # JRA中央が0件＝平日/地方開催のみ → スキャンボタンが無効になる理由を明示
            if not venues:
                _nar_n = len(race_list)
                st.warning(
                    f"⚠️ **{st.session_state.get('rpps_date_input', '')} はJRA中央競馬の開催がありません**"
                    f"（取得した{_nar_n}レースは地方競馬のみ）。この馬番パターンスキャナはJRA中央(札幌〜小倉)専用のため、"
                    "スキャンを開始できません。**土日・祝日などJRA開催日の日付**を入力して「📅 開催場を取得」し直してください。")

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

    # ══════════════════════════════════════════════════════════════
    # 🧩 合議ゲート（妙味判定／見送り判定器） — 検証済みエッジの独立合議
    #   MELCHIOR=強適消去スコア / BALTHASAR=単複乖離・断層・黄金・厩舎 / CASPER=末脚救出・展開
    #   旧"予測器"(BattleScore相関の偽アンサンブル)を置換する本命機能。
    # ══════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown(
        "<div class='consensus-title'>🧩 CONSENSUS GATE ／ 合議ゲート（妙味判定・見送り判定）</div>"
        "<p style='font-size:11px;'>3機が<b>互いに独立した検証済みエッジ</b>を見て承認/否定。"
        "全会一致の人気薄＝🟢妙味、分裂＝⚪見送り。"
        "MELCHIOR=強適消去 / BALTHASAR=単複乖離・断層・黄金・厩舎 / CASPER=🔥末脚救出・展開。</p>",
        unsafe_allow_html=True)
    _mc_place = st.checkbox("🔌 事前複勝オッズを取得（単複乖離の精度UP・ネット接続）", value=False,
                            key="mc_fetch_place")
    if st.button("🧩 合議ゲート 起動", type="primary", use_container_width=True, key="mc_run"):
        from core import value_scanner as _vs_mc, jockey_jv as _jj_mc, magi_consensus as _mc
        import importlib as _il_mc
        _il_mc.reload(_vs_mc); _il_mc.reload(_mc)
        try:
            _rid_mc = str(race_id_for_magi)
            _jyo_mc = _rid_mc[4:6] if len(_rid_mc) >= 6 else ''
            _meta_mc = dict(getattr(df_magi, 'attrs', {}).get('metadata', {}) or {})
            _surf_mc = (str(df_magi['CurrentSurface'].iloc[0])
                        if 'CurrentSurface' in df_magi.columns and not df_magi.empty else '芝')
            try:
                _dist_mc = int(pd.to_numeric(df_magi['CurrentDistance'].iloc[0], errors='coerce'))
            except Exception:
                _dist_mc = None
            _dv_mc = str(_meta_mc.get('date_val', '') or race_metadata.get('date_val', '') or '')
            _month_mc = int(_dv_mc[4:6]) if len(_dv_mc) >= 6 and _dv_mc[4:6].isdigit() else 0
            _miny_mc = str(int(_dv_mc[:4]) - 3) if _dv_mc[:4].isdigit() else None

            # オッズ断層上位(純計算)
            _obu_mc = {}
            if 'Umaban' in df_magi.columns and 'Odds' in df_magi.columns:
                for _, _hh in df_magi.iterrows():
                    try:
                        _u = int(pd.to_numeric(_hh.get('Umaban'), errors='coerce'))
                        _o = float(pd.to_numeric(_hh.get('Odds'), errors='coerce'))
                        if _u and _o > 0:
                            _obu_mc[_u] = _o
                    except Exception:
                        pass
            _gap_mc = _vs_mc.odds_gap_anchors(_obu_mc)

            # 事前複勝オッズ(任意)
            _place_mc = {}
            if _mc_place and hasattr(scraper, 'fetch_place_odds_api'):
                try:
                    _place_mc = scraper.fetch_place_odds_api(_rid_mc) or {}
                except Exception:
                    _place_mc = {}

            # 旧『展開好位妙味ゾーン』はCASPER票への加点に使っていたが検証で否定(常に空)。
            # CASPERは実質 末脚救出(検証エッジ)のみで投票する。
            _pace_mc = set()

            _mc_res = _mc.evaluate_consensus(
                df_magi.to_dict('records'), _vs_mc, _jj_mc, _jyo_mc, _surf_mc,
                _dist_mc, _month_mc, _miny_mc, place_map=_place_mc,
                pace_pos=_pace_mc, date_val=_dv_mc, gap_anchors=_gap_mc)
            st.session_state['mc_result'] = _mc_res
            st.session_state['mc_race_id'] = _rid_mc
        except Exception as _e_mc:
            st.session_state['mc_result'] = None
            st.error(f"合議ゲートエラー: {_e_mc}")

    _mc_res = st.session_state.get('mc_result')
    if _mc_res:
        _cand = _mc_res.get('candidate')
        _uv = _mc_res.get('unit_votes', {})
        _verdict = _mc_res.get('verdict')
        # 焦点候補への3機の承認/否定（エヴァUI）
        if _cand:
            st.markdown(f"**焦点候補: `{_cand['um']}` {_cand['name']}** "
                        f"／ {_cand['pop']}人気・{_cand['odds']}倍")
            _cc = st.columns(3)
            for _ci, (_unit, _sub) in enumerate([
                    ('MELCHIOR-1', '実力／強適消去'),
                    ('BALTHASAR-2', '市場妙味／乖離・断層'),
                    ('CASPER-3', '展開／🔥末脚')]):
                _key = _unit.split('-')[0]
                _ok = _uv.get(_key, False)
                _verb = '承認' if _ok else '否定'
                _col = '#00ff44' if _ok else '#ff3333'
                with _cc[_ci]:
                    st.markdown(
                        f"<div style='border:2px solid {_col};background:#050510;"
                        f"padding:14px;text-align:center;font-family:monospace;'>"
                        f"<div style='color:#ff8844;font-size:10px;letter-spacing:2px;'>{_unit}</div>"
                        f"<div style='color:#888;font-size:9px;'>{_sub}</div>"
                        f"<div style='color:{_col};font-size:34px;font-weight:900;"
                        f"text-shadow:0 0 14px {_col};margin-top:6px;'>{_verb}</div></div>",
                        unsafe_allow_html=True)
        # 合議判定バナー
        _vcol = {'GO': '#00ff44', 'CONDITIONAL': '#ffaa00', 'SKIP': '#ff6600'}.get(_verdict, '#888')
        st.markdown(
            f"<div class='magi-consensus' style='border-color:{_vcol};margin-top:10px;'>"
            f"<div style='color:{_vcol};font-family:Orbitron,monospace;font-size:18px;"
            f"font-weight:900;letter-spacing:3px;text-shadow:0 0 16px {_vcol};text-align:center;'>"
            f"RESULT OF THE DELIBERATION<br>{_mc_res.get('verdict_label')}</div></div>",
            unsafe_allow_html=True)
        if _verdict == 'SKIP':
            st.caption("⚪ 控除率25%の競馬で最も効くのは『賭けないレースを選ぶこと』。シグナルが割れたら見送り。")

        # 合議妙味馬(人気薄×2票以上)
        _ana = _mc_res.get('consensus_anaUma', [])
        if _ana:
            import pandas as _pd_mc
            _adf = _pd_mc.DataFrame([{
                '馬番': h['um'], '馬名': h['name'], '人気': h['pop'], 'オッズ': h['odds'],
                '承認数': h['votes'],
                'MEL': '○' if h['mel'] else '×', 'BAL': '○' if h['bal'] else '×',
                'CAS': '○' if h['cas'] else '×',
                '妙味材料': ' / '.join(h['pos']) or '-',
            } for h in _ana])
            st.markdown("**🟢 合議妙味馬（人気薄 × 2機以上が承認）**")
            st.dataframe(_adf, hide_index=True, use_container_width=True)

        # 危険人気馬
        _dg = _mc_res.get('danger', [])
        if _dg:
            st.error("🔴 危険人気馬（軸外し推奨：人気≫実力＋市場妙味なし）:\n"
                     + "\n".join(f"- {d['um']} {d['name']}（{d['pop']}人気・{d['odds']}倍）: "
                                 f"{' / '.join(d['neg'])}" for d in _dg))

        # 回顧台帳キャリブレーション(自信度の実測値)
        with st.expander("🎓 回顧キャリブレーション（合議状態別の実測ヒット率）"):
            # ── バックテスト固定参考表(scripts/consensus_backtest.py, 2021-25・人気薄6番人気以下127,550点) ──
            st.markdown("**📊 合議バックテスト参考値（2021-25 / 人気薄6番人気以下 127,550点）**")
            import pandas as _pd_bt
            _bt_rows = [
                {'軸 / 合議状態': 'ベース（人気薄全体）', '複勝率': '9.4%', '単勝ROI': '66%', '点数': '127,550'},
                {'軸 / 合議状態': 'S1 末脚（実力軸）', '複勝率': '13.6%', '単勝ROI': '66%', '点数': '8,964'},
                {'軸 / 合議状態': 'S2 フォーム（実力軸）', '複勝率': '14.6%', '単勝ROI': '67%', '点数': '10,686'},
                {'軸 / 合議状態': 'S3 オッズ断層（市場軸）', '複勝率': '24.1%', '単勝ROI': '77%', '点数': '1,627'},
                {'軸 / 合議状態': 'votes=2（実力軸どうし）', '複勝率': '15.6%', '単勝ROI': '59〜69%', '点数': '—'},
                {'軸 / 合議状態': '🎯 votes=3（全軸一致）', '複勝率': '27.1%', '単勝ROI': '96%', '点数': '~230'},
                {'軸 / 合議状態': '🎯 末脚×断層（別軸AND）', '複勝率': '26.7%', '単勝ROI': '94%', '点数': '~370'},
            ]
            st.dataframe(_pd_bt.DataFrame(_bt_rows), hide_index=True, use_container_width=True)
            st.caption("📌 結論: 的中率は承認数に応じて単調に上がる(合議＝集中は本物)が、"
                       "**ROIを生むのは『市場軸(断層/単複乖離)の票』が混ざったときだけ**。"
                       "実力軸どうし(末脚+フォーム)を重ねても的中は上がるがROIはベース並み。"
                       "3軸全一致/末脚×断層は別格(複勝率~27%/単ROI~95%)だがフラット単勝で黒字化はせず＝**複勝/組合せ向き**。")
            st.markdown("---")
            st.markdown("**📒 実測台帳（あなたの記録）**")
            try:
                from core import magi_consensus as _mc2
                _cal = _mc2.calibration_summary()
                if _cal:
                    import pandas as _pd_c
                    _cdf = _pd_c.DataFrame([
                        {'合議状態': k, '記録数': v['n'], '勝率': f"{v['win_rate']}%",
                         '複勝率': f"{v['place_rate']}%", '単勝ROI': f"{v['win_roi']}%"}
                        for k, v in sorted(_cal.items(), reverse=True)])
                    st.dataframe(_cdf, hide_index=True, use_container_width=True)
                    st.caption("承認数が多いほど勝率/ROIが高ければ、合議は本物の自信度になっている。"
                               "記録は consensus_ledger.json に蓄積。")
                else:
                    st.info("まだ実績記録がありません。回顧学習ページで結果を記録すると、"
                            "合議状態別の実測ヒット率がここに蓄積されます。")
            except Exception as _e_cal:
                st.caption(f"集計不可: {_e_cal}")

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
# 🎓 MAGI 回顧学習（MAGIシステムタブの最下部に統合表示）
# ══════════════════════════════════════════════════════════════

if nav == "🧠 MAGIシステム":
    st.divider()
    # === MAGI おしゃべりルーム (EVANGELION風 左右2分割) ===
    import core.magi_chat as mc
    import random as _rand, html as _html

    st.markdown('''<style>
    .magi-bar{background:linear-gradient(90deg,#1a0e00,#2a1500);border:1px solid #e8590c;color:#ff8c42;font-family:monospace;letter-spacing:2px;padding:8px 14px;border-radius:6px;margin-bottom:10px;font-weight:700;}
    .magi-panel{background:#070707;border:1px solid #5a2d0a;border-radius:8px;padding:12px;margin-bottom:10px;}
    .magi-sub{color:#e8590c;font-family:monospace;font-size:0.72em;letter-spacing:1px;margin-bottom:8px;}
    .magi-status{display:flex;justify-content:space-between;font-family:monospace;color:#ff8c42;font-size:1.15em;font-weight:700;}
    .pcard{border-radius:6px;padding:8px 10px;margin-bottom:6px;background:#101418;border:1px solid #2a2f3a;}
    .pcard.active{border-color:#e8590c;box-shadow:0 0 8px rgba(232,89,12,0.45);}
    .pname{font-weight:700;font-size:0.9em;}
    .prole{color:#8a8f99;font-size:0.7em;}
    .pstate{float:right;font-family:monospace;font-size:0.72em;color:#e8590c;}
    .log-wrap{max-height:480px;overflow-y:auto;padding-right:6px;}
    .log-entry{border-left:3px solid #555;padding:6px 10px;margin-bottom:10px;background:rgba(255,255,255,0.02);border-radius:0 4px 4px 0;}
    .log-entry.user{border-left-color:#6f9bff;background:rgba(120,160,255,0.06);}
    .log-tag{color:#fff;font-size:0.7em;font-weight:700;padding:1px 8px;border-radius:3px;font-family:monospace;}
    .log-id{color:#666;font-family:monospace;font-size:0.66em;margin-left:6px;}
    .log-body{margin-top:5px;color:#dfe3ea;font-size:0.9em;line-height:1.55;}
    .proc{color:#e8590c;font-family:monospace;font-size:0.8em;margin-top:8px;}
    </style>''', unsafe_allow_html=True)

    if 'oshaberi' not in st.session_state:
        st.session_state.oshaberi = None
    osh = st.session_state.oshaberi

    def _logid():
        return ''.join(_rand.choices('0123456789abcdefghijklmnopqrstuvwxyz', k=5))

    st.markdown("<div class='magi-bar'>🗣️ MAGI SYSTEM — レース回顧おしゃべり</div>", unsafe_allow_html=True)

    _left, _right = st.columns([1, 1.5], gap="medium")

    with _left:
        if not osh:
            st.markdown("<div class='magi-sub'>⚠ INPUT QUERY</div>", unsafe_allow_html=True)
            with st.form("osh_start_form", clear_on_submit=False):
                _rid_in = st.text_input("レースID", placeholder="例: 202406050811", label_visibility="collapsed")
                _go = st.form_submit_button("▶ 審議開始", type="primary", use_container_width=True)
            if _go and _rid_in and _rid_in.strip():
                _rid = _rid_in.strip()
                with st.spinner("レース結果を読み込み中..."):
                    try:
                        _df_o = scraper.get_race_data(_rid, use_storage=False)
                        if not _df_o.empty:
                            _df_o = calculator.calculate_all(_df_o)
                    except Exception:
                        _df_o = pd.DataFrame()
                    try:
                        from core.magi_system import run_magi_deliberation
                        _mp = run_magi_deliberation(_df_o, course_profile="標準", chaos_rank="B") if not _df_o.empty else {}
                    except Exception:
                        _mp = {}
                    try:
                        _ar = scraper.fetch_comprehensive_result(_rid)
                    except Exception:
                        _ar = {}
                if not _ar or not _ar.get('horses'):
                    st.error("結果を取得できませんでした。確定済みのレースIDか確認してね。")
                else:
                    _ctx = mc.build_context(_df_o, _mp, _ar)
                    try:
                        _f = mc.magi_turn(_ctx, [], GEMINI_API_KEY)
                    except Exception:
                        _f = {'persona': 'balthasar', 'message': 'このレースで気になった馬はいた?', 'done': False}
                    st.session_state.oshaberi = {
                        'race_id': _rid, 'ctx': _ctx, 'result_line': mc.result_one_line(_ctx),
                        'chat': [{'role': 'magi', 'persona': _f['persona'], 'message': _f['message'], 'id': _logid()}],
                        'done': False, 'saved': False,
                    }
                    st.rerun()
            st.caption("👶 終わったレースのIDを入れて審議開始。3人格がやさしく質問します。")
        else:
            _status = "決議完了" if osh['done'] else "審議中"
            st.markdown(
                f"<div class='magi-panel'><div class='magi-status'><span>提訴</span><span>決議</span></div>"
                f"<div class='magi-sub' style='margin-top:6px'>CODE : {osh['race_id'][-4:]}　STATUS : {_status}</div></div>",
                unsafe_allow_html=True)
            _active = None
            for _m in reversed(osh['chat']):
                if _m['role'] == 'magi':
                    _active = _m['persona']
                    break
            for _k, _p in mc.PERSONAS.items():
                _cls = 'pcard active' if (_k == _active and not osh['done']) else 'pcard'
                _cnt = sum(1 for _m in osh['chat'] if _m.get('persona') == _k)
                _stt = '質問中' if (_k == _active and not osh['done']) else (f'{_cnt}問' if _cnt else '待機')
                st.markdown(
                    f"<div class='{_cls}' style='border-left:4px solid {_p['color']}'>"
                    f"<span class='pstate'>{_stt}</span>"
                    f"<div class='pname' style='color:{_p['color']}'>{_p['emoji']} {_p['jp']}</div>"
                    f"<div class='prole'>{_p['role']}</div></div>", unsafe_allow_html=True)

            if not osh['done']:
                st.markdown("<div class='magi-sub' style='margin-top:8px'>⚠ INPUT QUERY</div>", unsafe_allow_html=True)
                with st.form("osh_ans_form", clear_on_submit=True):
                    _ans = st.text_area("答え", placeholder="普通の言葉でOK（わからなければ「わからない」）",
                                        label_visibility="collapsed", height=90)
                    _send = st.form_submit_button("▶ 送信", type="primary", use_container_width=True)
                if _send and _ans and _ans.strip():
                    osh['chat'].append({'role': 'user', 'message': _ans.strip(), 'id': _logid()})
                    with st.spinner("MAGI 審議中..."):
                        try:
                            _nx = mc.magi_turn(osh['ctx'], osh['chat'], GEMINI_API_KEY)
                        except Exception:
                            _nx = {'persona': 'casper', 'message': 'なるほど。ほかに覚えていることは?', 'done': False}
                    osh['chat'].append({'role': 'magi', 'persona': _nx['persona'], 'message': _nx['message'], 'id': _logid()})
                    if _nx['done']:
                        osh['done'] = True
                    st.session_state.oshaberi = osh
                    st.rerun()
            else:
                if not osh.get('saved'):
                    if st.button("📒 審議を記録する", type="primary", use_container_width=True, key="osh_save"):
                        with st.spinner("学びをメモ中..."):
                            _lg = mc.extract_learning(osh['ctx'], osh['chat'], GEMINI_API_KEY)
                            _rec, _ts = mc.save_record(osh['race_id'], {}, osh['ctx'], osh['chat'], _lg)
                        osh['saved'] = True
                        osh['learning'] = _lg
                        osh['tagsum'] = _ts
                        st.session_state.oshaberi = osh
                        st.rerun()
                else:
                    st.success("記録しました")

            if st.button("■ ABORT / 別のレース", use_container_width=True, key="osh_reset"):
                st.session_state.oshaberi = None
                st.rerun()

    with _right:
        st.markdown("<div class='magi-sub'>📡 DELIBERATION LOG</div>", unsafe_allow_html=True)
        if not osh:
            st.markdown("<div class='magi-panel' style='color:#666;font-family:monospace'>&gt;&gt;&gt; AWAITING QUERY ...</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='magi-panel' style='font-size:0.9em'>🏁 {_html.escape(osh['result_line'])}</div>", unsafe_allow_html=True)
            _entries = []
            for _m in osh['chat']:
                _body = _html.escape(_m['message']).replace(chr(10), '<br>')
                if _m['role'] == 'user':
                    _entries.append(
                        f"<div class='log-entry user'><span class='log-tag' style='background:#6f9bff'>あなた</span>"
                        f"<span class='log-id'>LOG_ID: {_m.get('id','')}</span><div class='log-body'>{_body}</div></div>")
                else:
                    _p = mc.PERSONAS.get(_m['persona'], {})
                    _entries.append(
                        f"<div class='log-entry' style='border-left-color:{_p.get('color','#555')}'>"
                        f"<span class='log-tag' style='background:{_p.get('color','#555')}'>{_p.get('jp','MAGI')}</span>"
                        f"<span class='log-id'>LOG_ID: {_m.get('id','')}</span><div class='log-body'>{_body}</div></div>")
            if not osh['done']:
                _entries.append("<div class='proc'>&gt;&gt;&gt; PROCESSING ...</div>")
            st.markdown(f"<div class='log-wrap'>{''.join(_entries)}</div>", unsafe_allow_html=True)

            if osh.get('saved'):
                _lg = osh.get('learning', {})
                _tk = _lg.get('key_takeaways') or []
                _tags = osh.get('tagsum') or {}
                _sess = _lg.get('signal_tags') or []
                _parts = ["<div class='magi-panel'><div class='magi-sub'>🧠 学習レコード</div>"]
                if _tk:
                    _parts.append("<div style='color:#dfe3ea;font-size:0.88em'><b>今日の学び</b><ul style='margin:4px 0 8px 18px'>")
                    for _t in _tk:
                        _parts.append(f"<li>{_html.escape(str(_t))}</li>")
                    _parts.append("</ul></div>")
                if _sess:
                    _chips = []
                    for _t in _sess:
                        _info = _tags.get(_t, {'count': 1, 'quarantined': mc.is_quarantined(_t), 'ready': False})
                        _ts2 = _html.escape(str(_t))
                        if _info['quarantined']:
                            _chips.append(f"<span style='background:#5c1f1f;color:#ffb3b3;padding:2px 8px;border-radius:10px;font-size:0.78em'>⚠ {_ts2}（俗説・採用しない）</span>")
                        elif _info['ready']:
                            _chips.append(f"<span style='background:#1f5c2f;color:#b3ffc4;padding:2px 8px;border-radius:10px;font-size:0.78em'>✅ {_ts2}（{_info['count']}回目・要検証）</span>")
                        else:
                            _chips.append(f"<span style='background:#2a2f3a;color:#cfd6e4;padding:2px 8px;border-radius:10px;font-size:0.78em'>{_ts2}（{_info['count']}/3）</span>")
                    _parts.append("<div style='font-size:0.78em;color:#8a8f99;margin-bottom:4px'>気づきタグ（3回で検証候補）</div>")
                    _parts.append("<div style='line-height:2'>" + " ".join(_chips) + "</div>")
                _parts.append("</div>")
                st.markdown("".join(_parts), unsafe_allow_html=True)


# --- History & Review（MAGIシステムタブ最下部・MAGI回顧学習の下に統合表示）---
if nav == "🧠 MAGIシステム":
    st.divider()
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
                                elif "💀" in val: colors.append("background-color: #343a40; color: #ffd43b; font-weight: bold")
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
    jpro_tabJV, jpro_tab3, jpro_tab1, jpro_tab2, jpro_tab4 = st.tabs([
        _pub("🔥 JRA-VAN版 (調子・コンビ・黄金ライン)"),
        "✅ 最強予想ビュー (One-Push)",
        "🔍 詳細データ (コンビ/脚質)",
        "🚦 フラグ手動入力",
        "⚙️ 設定・データ管理",
    ])

    # =============================================
    # タブ(新): JRA-VAN実データ版 — J1〜J5＋調子/連敗
    # =============================================
    with jpro_tabJV:
        from core import jockey_jv as _jj
        import sqlite3 as _jjsq
        st.caption(_pub("netkeibaスクレイピング不使用。jravan.db（30年・283万走）から騎手の実力・相性・調子を直接集計。"))

        # オッズ期待値テーブル（USM較正用）はレース横断で共通。セッションにキャッシュ。
        if '_jj_expected' not in st.session_state:
            with st.spinner("オッズ期待値テーブルを較正中（初回のみ）..."):
                st.session_state['_jj_expected'] = _jj.calibrate_odds_expectation()
        _jj_exp = st.session_state['_jj_expected']

        # ── 📉 連敗中の騎手ピックアップ（オンカジ的パターン・正直ラベル付き）──
        with st.expander("📉 連敗中の騎手ピックアップ（現在の連敗・勝ち間隔パターン）", expanded=True):
            st.markdown(
                "<div style='background:#3a1c1c;border-left:6px solid #e63946;border-radius:8px;"
                "padding:10px 14px;font-size:12px;color:#ffd9d9;'>"
                "⚠️ <b>重要</b>：283万走のバックテストで、<b>連続して勝てない/3着以内に入れない長さは、次走で『勝つ・3着以内に来る』確率を上げも下げもしませんでした</b>"
                "（オッズ補正後の残差が連続0〜10+で平坦〜微マイナス＝『そろそろ来る』はギャンブラーの誤謬）。"
                "下表は<b>参考・話のタネ</b>で予測指標ではありません。騎手で本当に効くのは『コース相性・黄金ライン・実力(USM)』です。</div>",
                unsafe_allow_html=True)
            if st.button("🔄 連敗ランキングを更新", key="jj_streak_refresh") or '_jj_streaks' not in st.session_state:
                with st.spinner("直近騎乗騎手の連敗を集計中..."):
                    st.session_state['_jj_streaks'] = _jj.losing_streak_leaders(top=15)
            _streaks = st.session_state.get('_jj_streaks', [])
            if _streaks:
                _sdf = pd.DataFrame([{
                    "騎手": s['name'], "現在の連敗(未勝利)": s['lose_streak'],
                    "連続圏外(3着内なし)": s['no_top3'],
                    "最後の勝ちから": f"{s['cur_dry']}走",
                    "平均勝ち間隔": f"{s['win_gap_avg']}走に1勝",
                    "due比(>1=平均より長く未勝利)": s['due_ratio'],
                    "直近20複勝率": f"{s['recent_top3']*100:.0f}%",
                } for s in _streaks])
                st.dataframe(_sdf, hide_index=True, use_container_width=True)
                st.caption("「平均◯走に1勝」＝最近のパターン。due比が大きいほど『平均より長く勝っていない』"
                           "（が、それで次に勝ちやすくなる訳ではない点に注意）。")

        # ── レース単位の騎手指標（jravan.db に取り込み済みの過去レース）──
        st.markdown("---")
        _jj_rid = st.text_input("レースIDを入力（jravan.db取り込み済みの過去レース）",
                                value=str(st.session_state.get('_jj_last_rid', '')),
                                key="jj_race_id", placeholder="例: 202509030411")
        if _jj_rid:
            st.session_state['_jj_last_rid'] = _jj_rid
            try:
                # os.path.exists ガード必須: connect はファイルが無いと空DBを作り IS_PUBLIC 判定を壊す
                if not os.path.exists('data/jravan.db'):
                    raise FileNotFoundError('jravan.db')
                _jc = _jjsq.connect('file:data/jravan.db?mode=ro', uri=True)
                _jrow = _jc.execute(
                    "SELECT race_key, jyo, kyori, surface, race_name FROM races WHERE race_id=?",
                    (_jj_rid,)).fetchone()
                _jentries = []
                if _jrow:
                    _jentries = _jc.execute(
                        "SELECT umaban, jockey_name, bamei, trainer_code, ketto_num, ninki, chakujun "
                        "FROM results WHERE race_key=? ORDER BY umaban", (_jrow[0],)).fetchall()
                _jc.close()
            except Exception as _je:
                _jrow, _jentries = None, []
                st.caption(f"DB参照エラー: {_je}")

            if not _jrow:
                st.info("このレースIDは jravan.db に未取り込みです（未来のレースや体験版の反映前）。"
                        "過去のレースIDでお試しください。連敗ピックアップは上の表で確認できます。")
            elif _jentries:
                _rk, _jyo, _kyori, _surf, _rname = _jrow
                _venue = _jj._venue_name(_jyo)
                st.markdown(f"**{_rname or ''} {_venue}{_surf}{_kyori}m**（{len(_jentries)}頭）"
                            "　騎手指標はこのレース直前までの実績で算出（リーク無し）")
                _jrows = []
                for um, jk, bamei, tr, ketto, ninki, chaku in _jentries:
                    base = _jj.jockey_base_stats(jk, venue=_venue, distance=_kyori, before_key=_rk)
                    ov = base['overall']; vstat = base['venue'] or {}
                    tcombo = _jj.jockey_trainer_combo(jk, tr, before_key=_rk)
                    hcombo = _jj.jockey_horse_combo(jk, ketto, before_key=_rk)
                    mom = _jj.momentum(jk, before_key=_rk)
                    fac = _jj.jockey_factor(jk, venue=_venue, distance=_kyori,
                                            trainer_code=tr, expected=_jj_exp, before_key=_rk)
                    usm = _jj.jockey_usm(jk, _jj_exp, before_key=_rk)
                    # 🥇🥇=連対40%以上(検証で勝ち+2pp/連対+3pp の最強)・🥇=30-40%
                    _gmark = ("🥇🥇" if tcombo['rides'] >= 15 and tcombo['top2'] >= 0.40
                              else "🥇" if tcombo['rides'] >= 15 and tcombo['top2'] >= 0.30 else "")
                    _gold = f"{tcombo['top2']*100:.0f}%/{tcombo['rides']}走{_gmark}"
                    _combo = (f"{hcombo['top3']*100:.0f}%/{hcombo['rides']}走" if hcombo['rides'] > 0 else "初")
                    _jrows.append({
                        "馬番": um, "騎手": jk, "馬": bamei, "人気": ninki,
                        "全体勝率": f"{ov['win']*100:.0f}%", "全体複勝": f"{ov['top3']*100:.0f}%",
                        f"{_venue}連対": f"{vstat.get('top2',0)*100:.0f}%/{vstat.get('rides',0)}走",
                        "黄金ライン(対調教師)": _gold,
                        "コンビ(この馬)": _combo,
                        "USM複勝(100=平均)": usm['top3_usm'] if usm['top3_usm'] else "-",
                        "騎手係数": fac['mult'],
                        "調子(連敗/hot)": f"連{mom.get('lose_streak','-')}/{mom.get('hot',0):+.2f}",
                        "_sort": fac['mult'],
                    })
                _jdf = pd.DataFrame(_jrows).sort_values('_sort', ascending=False).drop(columns=['_sort'])
                st.dataframe(_jdf, hide_index=True, use_container_width=True)
                st.caption("USM=人気(オッズ期待値)に対し実際の複勝率が何%か（100超=人気以上に走らせる＝騎手の実力）。"
                           "🥇🥇=黄金ライン最強(対調教師15走以上・連対40%以上＝検証で勝ち+2pp/連対+3pp人気以上)・🥇=30-40%。"
                           "騎手係数=検証で『人気以上に来る』と確認できたUSM・場相性・黄金ラインのみで構成"
                           "（連敗/調子は予測力ゼロのため不採用）。")

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
            "フラグボーナス": 50.0,
            "騎乗数": 0.0
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
                ("📈 調子Pウェイト", "調子P", "調子ポイント(好不調)の乗数ウェイト。", 0.0, 100.0, 0.01),
                ("💰 単回収%ウェイト", "単回収%", "コース単勝回収率(割合換算)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("👥 人気ウェイト", "人気", "人気値(1〜18、1人気ほど高得点化)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("オッズウェイト", "オッズ", "オッズ値(1.0〜150.0)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🥋 PW指数ウェイト", "PW指数", "PW指数(0〜150程度、/10)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🎯 単勝USMウェイト", "単勝USM", "単勝USM(割合換算)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🥈 連対USMウェイト", "連対USM", "連対USM(割合換算)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🥉 複勝USMウェイト", "複勝USM", "複勝USM(割合換算)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🏇 騎乗数ウェイト", "騎乗数", "騎乗数の乗数ウェイト。", 0.0, 10.0, 0.01),
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

                    # 9) 騎乗数
                    _rides_val = float(vs.get('rides', 0))
                    score += _rides_val * weights.get('騎乗数', 0.0)

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



