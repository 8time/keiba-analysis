import textwrap
import re

with open('app.py', encoding='utf-8') as f:
    text = f.read()

# I will find the marker '# --- ✨ Strategy Advisor ---' up to '# --- ✨ Race Pattern Strategy Advisor ---'
# And indent it 4 spaces.
parts = text.split('# --- ✨ Strategy Advisor ---', 1)
if len(parts) == 2:
    part1, rest = parts
    strat_block, pattern_block = rest.split('# --- ✨ Race Pattern Strategy Advisor ---', 1)
    pattern_block_text, rest_ai = pattern_block.split('# --- ✨ AI Assistant ---', 1)

    # Modify strat_block to fit under col_r1
    # Adding a tab (4 spaces) to everything.
    strat_block_indented = textwrap.indent('# --- ✨ Strategy Advisor ---\n' + strat_block, '    ')
    
    # Modify pattern_block_text to fit under col_r2
    pattern_block_indented = textwrap.indent('# --- ✨ Race Pattern Strategy Advisor ---\n' + pattern_block_text, '    ')

    target_old = '''                    with col_r1:
                        st.markdown(f"## Race Rating: {rating_icon} {rating}")
                        st.progress(min(score, 100) / 100.0)
                        if reasons:
                            st.caption(f"Reason: {', '.join(reasons)}")'''

    col_r2_str = '''
                    with col_r2:
                        if fav_vuln_msg:
                            st.info(fav_vuln_msg)
                        if dark_horse_msgs:
                            st.warning("🎯 **【注目の適性ダークホース】**\\n\\n" + "\\n\\n".join(dark_horse_msgs))
'''
    
    # Text without the blocks appended at the end
    text_without_them = part1 + '# --- ✨ AI Assistant ---\n' + rest_ai
    
    # Replace the existing col_r2 definition at the end (the non-indented one)
    text_without_them = text_without_them.replace(col_r2_str, '')

    replacement = target_old + '\n' + strat_block_indented + col_r2_str + pattern_block_indented

    new_app = text_without_them.replace(target_old, replacement)

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(new_app)
    print("Indented")
else:
    print("Already indented or not found")
