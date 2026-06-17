import os

def update():
    with open('app.py', 'r', encoding='utf-8') as f:
        text = f.read()

    start_marker = '    if retro_btn and retro_race_id:'
    end_marker = '# ──────────────────────────────────────────────\n# --- Footer ---'

    start_idx = text.find(start_marker)
    
    # We want the LAST '# ──────────────────────────────────────────────' right before # --- Footer ---
    # So we can search for the Footer first
    end_idx = text.find(end_marker, start_idx)

    if start_idx != -1 and end_idx != -1:
        with open('/tmp/replacement.txt', 'r', encoding='utf-8') as f2:
            replacement = f2.read()
            
        new_text = text[:start_idx] + replacement + '\n\n' + text[end_idx:]
        
        with open('app.py', 'w', encoding='utf-8') as f3:
            f3.write(new_text)
        print("Success! Chat UI Applied.")
    else:
        print(f"Markers missing. start_idx: {start_idx}, end_idx: {end_idx}")

if __name__ == '__main__':
    update()
