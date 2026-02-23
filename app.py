import sys, io
import os
import google.generativeai as genai
from dotenv import load_dotenv

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
tab1, tab2, tab_today, tab3 = st.tabs(["Single Race Analysis", "Race Scanner (Batch)", "📅 Today's Picks", "📊 History & Review"])

# --- Tab 2: Today's Picks (Scanner ONLY) ---
with tab_today:
    st.header("📅 本日の厳選お宝レース (Today's Picks)")
    
    # Date Picker
    # Default to 2026/02/15 for verification as requested by user
    default_date = datetime(2026, 2, 15).date()
    selected_date = st.date_input("Select Date", default_date)
    date_str = selected_date.strftime('%Y%m%d')
    
    if st.button("🚀 Scan Races", type="primary"):
        status_container = st.container()
        results_container = st.container()
        
        hot_races = []     # S or A
        rocket_races = []  # Rocket Horse exists
        treasure_races = [] # EV >= 300 exists
        waiting_races = [] # Data not ready
        
        with status_container:
            st.write(f"🔍 Fetching race list for **{date_str}**...")
            try:
                # Show URL for debug
                target_url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}"
                st.caption(f"Target URL: {target_url}")
                
                today_races = scraper.get_race_ids_for_date(date_str)
                st.write(f"✅ Found {len(today_races)} races.")
                
                if not today_races:
                    st.error("No races found. This could be due to:")
                    st.markdown("- **Incorrect Date**: Please check if races are held on this date.")
                    st.markdown("- **Netkeiba Access Block**: The site might be blocking the request.")
                    st.markdown("- **URL Change**: The race list URL structure might have changed.")
                    st.caption(f"Tried fetching from: {target_url}")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    for i, rid in enumerate(today_races):
                        status_text.text(f"Analyzing Race {i+1}/{len(today_races)} (ID: {rid})...")
                        progress_bar.progress((i + 1) / len(today_races))
                        
                        try:
                            # 1. Fetch
                            df = scraper.get_race_data(rid)
                            if df.empty:
                                continue
                                
                            # 2. Analyze
                            df = calculator.calculate_ogura_index(df)
                            df = calculator.calculate_speed_index(df) # NEW
                            df = calculator.apply_delete_logic(df)    # NEW
                            df = calculator.calculate_n_index(df)     # NEW
                            
                            # Check Valid Data
                            valid_data = df[df['Status'] != 'No Data']
                            if valid_data.empty:
                                waiting_races.append(rid)
                                continue
                            
                            # 3. Categorize
                            top_score = df['OguraIndex'].max()
                            rating = "C"
                            if top_score >= 75: rating = "S"
                            elif top_score >= 70: rating = "A"
                            elif top_score >= 65: rating = "B"
                            
                            race_title = df['RaceTitle'].iloc[0] if 'RaceTitle' in df.columns else f"Race {rid}"
                            
                            item = {
                                "id": rid,
                                "title": race_title,
                                "rating": rating,
                                "score": top_score
                            }
                            
                            # Hot (S/A)
                            if rating in ['S', 'A']:
                                hot_races.append(item)
                            
                            # Rocket (Contains 🚀)
                            if 'Alert' in df.columns and df['Alert'].str.contains("🚀").any():
                                rocket_races.append(item)
                                
                            # Treasure (EV >= 300)
                            if 'ExpectedValue' in df.columns and (df['ExpectedValue'] >= 200).any():
                                treasure_races.append(item)

                        except Exception as e:
                            # print(f"Error analyzing {rid}: {e}")
                            pass
                            
                    progress_bar.empty()
                    status_text.text("Scan Complete!")
                    
                    with results_container:
                        c1, c2, c3 = st.columns(3)
                        
                        with c1:
                            st.subheader("🔥 激熱 (Hot)")
                            if hot_races:
                                for r in hot_races:
                                    st.markdown(f"**[{r['title']} (ID: {r['id']})](/?race_id={r['id']})** - **Rating {r['rating']}**")
                            else:
                                st.caption("None.")
                                
                        with c2:
                            st.subheader("🚀 穴馬 (Rocket)")
                            if rocket_races:
                                for r in rocket_races:
                                    st.markdown(f"**[{r['title']} (ID: {r['id']})](/?race_id={r['id']})**")
                            else:
                                st.caption("None.")
                                
                        with c3:
                            st.subheader("💎 お宝 (Treasure)")
                            if treasure_races:
                                for r in treasure_races:
                                    st.markdown(f"**[{r['title']} (ID: {r['id']})](/?race_id={r['id']})**")
                            else:
                                st.caption("None.")
                                
                        # Waiting
                        if waiting_races:
                            with st.expander(f"Waiting / Error ({len(waiting_races)})"):
                                st.write(waiting_races)

            except Exception as e:
                st.error(f"An error occurred during scan: {e}")

# --- Tab 1: Single Race Analysis (Main View) ---
with tab1:
    # Handle Query Params for Race ID
    query_params = st.query_params
    default_id = "202608020211"
    
    if "race_id" in query_params:
        default_id = query_params["race_id"]
        
    # Input
    col1, col2 = st.columns([1, 2])
    with col1:
        race_id_input = st.text_input("Race ID (Netkeiba)", value=default_id)
        st.caption("Example: 202608020211")
        
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
                    
                    # --- 🤖 AI Assistant ---
                    st.divider()
                    st.subheader("🤖 AI最終予想アシスタント（検索連携）")
                    if st.button("🤖 AIに最終予想を依頼する（Web検索連携）"):
                        
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
                                    genai.configure(api_key=genai_api_key)
                                    
                                    # Use gemini-2.5-flash and enable search grounding
                                    model = genai.GenerativeModel('gemini-2.5-flash', tools='google_search_retrieval')
                                    
                                    df_str = df.to_markdown(index=False)
                                    prompt = f"""
以下のデータは、私が独自に算出した本日の競馬のレースデータです。このデータを『最も重要な評価基準』としてメインに使用してください。

【出走馬データ】
{df_str}

さらに、Web検索機能を利用して、本日の対象競馬場の『天気』『馬場状態（良・稍重など）』『トラックバイアス』などのリアルタイム情報を取得してください。
独自データと検索結果を総合的に判断し、本気で推奨する『勝ち馬』と『おすすめの買い目（3連複など）』、その論理的な推論プロセスを出力してください。
"""
                                    response = model.generate_content(prompt)
                                    
                                    st.success("予想が完了しました！")
                                    st.markdown(response.text)
                            except Exception as e:
                                st.error(f"AI処理中にエラーが発生しました: {e}")
                    # -----------------------

            except Exception as e:
                st.error(f"An error occurred: {e}")

with tab2:
    st.header("🔍 Race Scanner (Batch Analysis)")
    st.markdown("Enter multiple Race IDs (one per line or comma separated) to scan.")
    
    input_text = st.text_area("Race IDs Input", height=150, placeholder="202608020211\n202608020212")
    scan_btn = st.button("Start Scan", type="primary")
    
    if scan_btn and input_text:
        # Parse IDs
        raw_ids = input_text.replace(",", "\n").split("\n")
        race_ids = [rid.strip() for rid in raw_ids if rid.strip()]
        
        if not race_ids:
            st.warning("Please enter valid Race IDs.")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            summary_data = []
            from datetime import datetime
            
            for i, rid in enumerate(race_ids):
                status_text.text(f"Scanning {rid} ({i+1}/{len(race_ids)})...")
                try:
                    df = scraper.get_race_data(rid)
                    if not df.empty:
                        df = calculator.calculate_ogura_index(df)
                        score, rating, reasons = calculator.calculate_confidence(df)
                        
                        ss_horses = df[df['Status'] == 'SS']['Name'].tolist()
                        top_horse = ss_horses[0] if ss_horses else (df.iloc[0]['Name'] if not df.empty else "-")
                        
                        # Extract Race Info (Title)
                        race_info = df.iloc[0]['RaceTitle'] if 'RaceTitle' in df.columns else rid
                        
                        summary_data.append({
                            "Date": datetime.now().strftime("%Y/%m/%d"),
                            "Race Info": race_info,
                            "Race ID": rid,
                            "Rating": rating,
                            "Score": score,
                            "Top Horse": top_horse,
                            "Note": ", ".join(reasons)
                        })
                        
                        # Auto-Save to History (New Feature)
                        import history_manager
                        history_manager.save_race_data(df, rid)
                        
                except Exception as e:
                    print(f"Error {rid}: {e}")
                    
                progress_bar.progress((i + 1) / len(race_ids))
                
            status_text.text("Scan Complete!")
            
            if summary_data:
                res_df = pd.DataFrame(summary_data)
                res_df = res_df.sort_values(by='Score', ascending=False)
                
                # Reorder columns: [Date, Race Info, Rating, Score, Top Horse, Note, (Race ID)]
                cols = ['Date', 'Race Info', 'Rating', 'Score', 'Top Horse', 'Note', 'Race ID']
                # Ensure vars exist
                existing_cols = [c for c in cols if c in res_df.columns]
                res_df = res_df[existing_cols]
                
                def highlight_scanner_row(row):
                    # Highlight '🔥🔥' (S) or '🔥' (A)
                    if 'Rating' in row and "🔥🔥" in str(row['Rating']):
                        return ['background-color: #ffcccc; color: black; font-weight: bold'] * len(row)
                    elif 'Rating' in row and "🔥" in str(row['Rating']):
                        return ['background-color: #ffe0b2; color: black'] * len(row)
                    return [''] * len(row)

                st.subheader("📊 Scan Results")
                
                st.dataframe(
                    res_df.style.apply(highlight_scanner_row, axis=1),
                    use_container_width=True
                )
                
                # Auto-Save Logic? Or Manual?
                # User: "When Analyze button is pressed... append to csv"
                # For scanner, we have multiple races. Let's save them all.
                if st.button("Save Scan Results to History"):
                    import history_manager
                    count = 0
                    for item in summary_data:
                        # We need the full DF for each race to save detailed horse data.
                        # `summary_data` only has summary.
                        # We need to re-fetch or pass the dfs.
                        # Re-fetching is slow.
                        # Let's simple support Single Race Save primarily, 
                        # or just save the top-level scan result?
                        # User request: "Save calculated index and horse data".
                        # So detailed data is needed.
                        # For Scanner, it's heavy to save all horses for all races if we didn't keep them.
                        pass
                    st.warning("For detailed history, please analyze individual races or use Single Race Mode.")

            else:
                st.error("No valid data found.")

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
    
    display_race_id = st.text_input("Race ID を入力 (Display)", placeholder="202605010811", key="history_display_race_id")
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

