import sys

def refactor_app_py():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Change the tabs declaration
    old_tabs = """    # --- メインUI: 4タブ構成 ---
    jpro_tab1, jpro_tab2, jpro_tab3, jpro_tab4 = st.tabs([
        "🔍 コンビネーション分析",
        "🚦 スクリーニング",
        "📋 出馬表ビュー",
        "⚙️ 設定・データ管理",
    ])"""
    
    new_tabs = """    # --- メインUI: 1ページ完結体験（出馬表ビューを先頭に） ---
    jpro_tab3, jpro_tab1, jpro_tab2, jpro_tab4 = st.tabs([
        "✅ 最強予想ビュー (One-Push)",
        "🔍 詳細データ (コンビ/脚質)",
        "🚦 フラグ手動入力",
        "⚙️ 設定・データ管理",
    ])"""

    if old_tabs in content:
        content = content.replace(old_tabs, new_tabs)
        print("Replaced tabs successfully.")
    else:
        print("Failed to replace tabs.")

    # 2. Extract the "Race ID Analyzer" from jpro_tab1 (around 8535)
    # We will find the block starting at "        # --- レースID分析（既存機能を保持） ---"
    # and ending right before "    # =============================================" (Tab 2 start)
    
    start_tag = "        # --- レースID分析（既存機能を保持） ---"
    end_tag = "    # =============================================\n    # タブ2: スクリーニング"
    
    start_idx = content.find(start_tag)
    end_idx = content.find(end_tag)
    
    if start_idx != -1 and end_idx != -1:
        race_analyzer_block = content[start_idx:end_idx]
        
        # Modify the input inside the block to pre-fill from main_race_id_input
        race_analyzer_block = race_analyzer_block.replace(
            'key="jp_race_input",',
            'value=st.session_state.get("main_race_id_input", ""),\n                key="jp_race_input",'
        )
        # Also remove the "st.divider()" at the beginning if we put it at the very top of Tab 3
        race_analyzer_block = race_analyzer_block.replace("st.divider()\n        st.markdown", "st.markdown")
        
        # Remove it from jpro_tab1
        content = content[:start_idx] + "\n" + content[end_idx:]
        
        # Insert it into jpro_tab3
        tab3_tag = "    with jpro_tab3:\n        st.subheader(\"📋 騎手強適 Ranking Table\")\n"
        tab3_idx = content.find(tab3_tag)
        
        if tab3_idx != -1:
            insertion_point = tab3_idx + len(tab3_tag)
            
            # Hide the Ranking Table subheader if we replace it with a cooler UI
            new_tab3_tag = """    with jpro_tab3:
        st.markdown("### 🏇 騎手分析Pro - Final Push")
        st.caption("「単一レース分析」のレースIDを自動引継ぎ。一押しで強力な騎手・コース適性を判定します。")
"""
            content = content.replace(tab3_tag, new_tab3_tag)
            tab3_idx = content.find(new_tab3_tag)
            insertion_point = tab3_idx + len(new_tab3_tag)
            
            content = content[:insertion_point] + race_analyzer_block + "\n" + content[insertion_point:]
            print("Moved Race Analyzer block to Tab 3 successfully.")
        else:
            print("Could not find jpro_tab3 body.")
    else:
        print("Could not find Race Analyzer block.")

    with open('app_modified.py', 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == '__main__':
    refactor_app_py()
