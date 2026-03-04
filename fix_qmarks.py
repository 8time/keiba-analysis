import re

with open('app.py', encoding='utf-8') as f:
    text = f.read()

replacements = {
    '**??◎ (二重丸)': '**◎ (二重丸)',
    '1?3番人気': '1～3番人気',
    'BetSync ? 資金管理': 'BetSync 📊 資金管理',
    '= Step 1 ?示': '= Step 1 表示',
    'if total_races else "?"': 'if total_races else "-"',
    '? 次回のベット：': '▶ 次回のベット：',
    'options=["? 負", "? 勝"]': 'options=["❌ 負", "✅ 勝"]',
    '== "? 勝"': '== "✅ 勝"',
    '"?✨ 削除"': '"🗑️ 削除"',
    '"? 勝"   if': '"✅ 勝"   if',
    'else "? 負"': 'else "❌ 負"',
    '>?プラス<': '>📈プラス<',
    '>??ガミ<': '>⚠️ガミ<',
    '>?ハズレ<': '>📉ハズレ<',
    'st.success("? プラス（このレースで利益）", icon=None)': 'st.success("✅ プラス（このレースで利益）", icon="✅")',
    'st.caption("? ハズレ ? 払い戻しなし")': 'st.caption("❌ ハズレ → 払い戻しなし")',
    '_add_label = "? 次のレースを追加"': '_add_label = "➕ 次のレースを追加"',
    '（?・?）': '（✅・❌）',
    'st.success("? URLからレースIDを自動抽出しました！", icon="?")': 'st.success("🔗 URLからレースIDを自動抽出しました！", icon="🔗")',
    'button("?✨ Analyze Race': 'button("🚀 Analyze Race',
    'rating_icon = "??"': 'rating_icon = "➖"',
    '"S" in rating: rating_icon = "????"': '"S" in rating: rating_icon = "🌟"',
    '"A" in rating: rating_icon = "??"': '"A" in rating: rating_icon = "🟢"',
    '"B" in rating: rating_icon = "??"': '"B" in rating: rating_icon = "🟡"',
    '["??✨ S", "✨ A"]': '["🌟 S", "🟢 A"]',
    'st.subheader("?✨ 強適シート': 'st.subheader("📊 強適シート',
    '1?5位': '1～5位',
    '2?6位': '2～6位',
    '3?5位': '3～5位',
    '3?6位': '3～6位',
    '3?4点': '3～4点',
    '5?6点': '5～6点',
    '10?20倍': '10～20倍',
    '30?80倍': '30～80倍',
    '2?7位': '2～7位',
    '15?40倍': '15～40倍',
    '50?200倍': '50～200倍',
    '6?9位': '6～9位',
    '4?8位': '4～8位',
    '5?8位': '5～8位',
    '8?10点': '8～10点',
    '4?7位': '4～7位',
    '40?100倍': '40～100倍',
    '100?500倍': '100～500倍',
    '6?7頭': '6～7頭',
    '500倍?万馬券': '500倍～万馬券',
    '10?20秒': '10～20秒',
    '"■ 相手（2?5位 + 2-3位クロス）"': '"■ 相手（2～5位 + 2-3位クロス）"',
    'f"? スキャン完了！': 'f"✅ スキャン完了！',
    'expander("? 詳細を見る"': 'expander("🔍 詳細を見る"',
    'st.success(f"? レース結果取得済み': 'st.success(f"✅ レース結果取得済み',
}

for k, v in replacements.items():
    text = text.replace(k, v)

# Remaining 3-renpuku special formatting
text = text.replace('{hn(0, "??")}', '{hn(0, "◎")}')
text = text.replace('{hn(1, "??")}', '{hn(1, "○")}')

text = text.replace('? 基本姿勢：', '▶ 基本姿勢：')
text = text.replace('? どうしても買いたい場合：', '▶ どうしても買いたい場合：')
text = text.replace('? 次の「荒れレース」に向けて', '▶ 次の「荒れレース」に向けて')
text = text.replace('<strong>? 上位2頭が', '<strong>▶ 上位2頭が')
text = text.replace('消し（??マーク）', '消し（💀マーク）')

text = text.replace('lbl("? 軸馬', 'lbl("🎯 軸馬')
text = text.replace('lbl("? 相手', 'lbl("🧩 相手')

text = re.sub(r'if \"\?\?\" in str\(val\): colors\.append\(\"background-color: #444444(.*?)\n', r'if "💣" in str(val): colors.append("background-color: #444444\g<1>\n', text)
text = re.sub(r'elif \"\?\?\" in str\(val\): colors\.append\(\"font-weight: bold; color: yellow\"\)', 'elif "💀" in str(val): colors.append("font-weight: bold; color: yellow")', text)
text = re.sub(r'elif \"\?\?\" in str\(val\): colors\.append\(\"font-weight: bold; color: red\"\)', 'elif "◎" in str(val): colors.append("font-weight: bold; color: red")', text)
text = re.sub(r'elif \"\?\?\" in str\(val\): colors\.append\(\"font-weight: bold; color: gray\"\)', 'elif "⏱️" in str(val): colors.append("font-weight: bold; color: gray")', text)

text = text.replace("if '??' in str(row.get('Alert', '')) or '??' in str(row.get('Alert', '')):", "if '💣' in str(row.get('Alert', '')) or '💀' in str(row.get('Alert', '')):")

# second config
text = re.sub(r'if \"\?\?\" in val: colors\.append\(\"background-color: #444444(.*?)\n', r'if "💣" in val: colors.append("background-color: #444444\1\n', text)
text = re.sub(r'elif \"\?\?\" in val: colors\.append\(\"font-weight: bold; color: yellow\"\)', 'elif "💀" in val: colors.append("font-weight: bold; color: yellow")', text)
text = re.sub(r'elif \"\?\?\" in val: colors\.append\(\"font-weight: bold; color: red\"\)', 'elif "◎" in val: colors.append("font-weight: bold; color: red")', text)
text = re.sub(r'elif \"\?\?\" in val: colors\.append\(\"font-weight: bold; color: gray\"\)', 'elif "⏱️" in val: colors.append("font-weight: bold; color: gray")', text)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(text)

