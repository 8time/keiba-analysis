import re

with open('app.py', encoding='utf-8') as f:
    text = f.read()

# Marker strings
m_rating = '# --- Race Rating + Strategy (Merged) ---'
m_scatter = '# --- 強適マップ 散布図 (Main Feature) ---'
m_ranking = '# --- 強適 Ranking Table ---'
m_10sen = '# --- 🎯 指数該当・人気順10選'
m_3ren = '# --- ✨ ３連複スペシャル'
m_pyramid = '# --- Direct Match Pyramid ---'
m_excludes = '# --- Exclude Recommended List ---'
m_strategy = '# --- ✨ Strategy Advisor ---'
m_barchart = '# --- RESURRECTED: Composite Chart'
m_pattern = '# --- ✨ Race Pattern Strategy Advisor ---'
m_ai = '# --- ✨ AI Assistant ---'

# Slicing
part1, rest = text.split(m_rating, 1)
part2, rest = rest.split(m_scatter, 1)
part3, rest = rest.split(m_ranking, 1)
part4, rest = rest.split(m_10sen, 1)
part5, rest = rest.split(m_3ren, 1)
part6, rest = rest.split(m_pyramid, 1)
part7, rest = rest.split(m_excludes, 1)
part8, rest = rest.split(m_strategy, 1)
part9, rest = rest.split(m_barchart, 1)
part10, rest = rest.split(m_pattern, 1)
part11, rest = rest.split(m_ai, 1)

part2 = m_rating + part2
part3 = m_scatter + part3
part4 = m_ranking + part4
part5 = m_10sen + part5
part6 = m_3ren + part6
part7 = m_pyramid + part7
part8 = m_excludes + part8
part9 = m_strategy + part9
part10 = m_barchart + part10
part11 = m_pattern + part11

# Fix df modification in Ranking (part4) to avoid affecting other charts
# Replace:
#                         df['Name'] = df.apply(fmt_pop_name, axis=1)
#                     if 'Jockey' in df.columns:
#                         df = calculator.apply_jockey_icons(df)
# with view_df modification.
part4 = re.sub(
    r"(\s+)(df\['Name'\] = df\.apply\(fmt_pop_name, axis=1\)\n\s+if 'Jockey' in df\.columns:\n\s+df = calculator\.apply_jockey_icons\(df\))",
    r"\1view_df = df.copy()\1view_df['Name'] = view_df.apply(fmt_pop_name, axis=1)\1if 'Jockey' in view_df.columns:\1    view_df = calculator.apply_jockey_icons(view_df)",
    part4
)

# And remove the later view_df = df.copy() in part4 since we moved it up
part4 = part4.replace('view_df = df.copy()', '', 1)

# Now we construct the unified Overview
# ① おおまかなレース情報（荒れなど）: part2 (Rating) + part9 (Strategy Advisor) + part11 (Pattern) + New Logic
# Wait! part2 contains the st.columns with rating on left, and old strat_msg on right.
# Let's clean up part2.
part2_clean = re.sub(
    r"\s+# Betting strategy text \(merged into top section\).*?st\.divider\(\)",
    r"""
                    st.divider()
                    st.subheader("🏁 おおまかなレース情報（展開予測・波乱警戒）")
                    col_r1, col_r2 = st.columns([1, 1])
                    with col_r1:
                        st.markdown(f"## Race Rating: {rating_icon} {rating}")
                        st.progress(min(score, 100) / 100.0)
                        if reasons:
                            st.caption(f"Reason: {', '.join(reasons)}")
""",
    part2, flags=re.DOTALL
)

# New Enhanced Logic string to insert
enhanced_logic = """
                    # --- Enhanced Suitability vs Popularity Analysis ---
                    fav_vuln_msg = ""
                    dark_horse_msgs = []
                    
                    try:
                        if 'Popularity' in df.columns and 'Suitability (Y)' in df.columns:
                            # Favorite vulnerability: Check top 3 popular horses
                            top_favs = df[pd.to_numeric(df['Popularity'], errors='coerce') <= 3]
                            if not top_favs.empty:
                                avg_suit = top_favs['Suitability (Y)'].mean()
                                if avg_suit < 50:
                                    fav_vuln_msg = "🚨 **【波乱警戒】** 上位人気馬のコース適性（Y軸）が全体的に低く、**ヒモ荒れや波乱の可能性が非常に高い**レースです。人気馬を過信せず、適性の高い中穴馬からのアプローチを推奨します。"
                                elif avg_suit < 65:
                                    fav_vuln_msg = "⚠️ **【中穴注意】** 上位人気馬のコース適性は平凡です。付け入る隙があり、展開次第で中穴馬が台頭する余地があります。"
                                else:
                                    fav_vuln_msg = "✨ **【軸馬信頼】** 上位人気馬のコース適性が高く安定しています。順当な決着になる確率が高いレースです。"

                            # Dark Horse Detection: Low popularity (>=6) but high suitability (>65)
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
"""

# Adjust part9 (Strategy Advisor text) to remove its subheader and append it to col_r2
part9_clean = part9.replace('st.divider()\n                    st.subheader("🎯 戦略アドバイザー")', '')
part9_clean = part9_clean.replace('st.info("✨ **少頭数レース**：データが少ないため、各馬の状態や展開を重視してください。")', 'st.info("✨ **少頭数レース**：データが少ないため、各馬の状態や展開を重視してください。")')

# Adjust part11 (Pattern Advisor) to remove its subheader
part11_clean = part11.replace('st.divider()\n                    st.subheader("🏁 レースパターン別 おすすめ戦略")', '')

overview_block = part2_clean + enhanced_logic + part9_clean + part11_clean + """
                    with col_r2:
                        if fav_vuln_msg:
                            st.info(fav_vuln_msg)
                        if dark_horse_msgs:
                            st.warning("🎯 **【注目の適性ダークホース】**\\n\\n" + "\\n\\n".join(dark_horse_msgs))
                            
"""

# ② 馬情報（数値など）: part4 (Ranking) + part10 (Bar Chart)
stats_charts_block = part4 + part10

# ③ 強適シート: part3
scatter_block = part3

# ④ Direct Match Pyramid: part7
pyramid_block = part7

# ⑤ 来ない馬、穴馬: part8
excludes_block = part8

# ⑥ 買い目の提案: part5 + part6 + part12(AI)
recommendations_block = part5 + part6 + m_ai + rest

# Reassemble
new_app = part1 + overview_block + stats_charts_block + scatter_block + pyramid_block + excludes_block + recommendations_block

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(new_app)
    
print("Successfully reordered app.py")
