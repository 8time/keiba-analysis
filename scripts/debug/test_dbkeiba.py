# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"C:/Users/kimnhaty/.gemini/antigravity/scratch/keiba_analysis")

import logging
logging.basicConfig(level=logging.WARNING)
import requests

url = "https://db-keiba.com/jockey/01167/"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://db-keiba.com/",
}

with open("dbkeiba_raw.txt", "w", encoding="utf-8") as f:
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        f.write(f"status: {resp.status_code}\n")
        f.write(f"Content-Encoding: {resp.headers.get('Content-Encoding','なし')}\n")
        f.write(f"Content-Type: {resp.headers.get('Content-Type','なし')}\n")
        f.write(f"resp.encoding: {resp.encoding}\n")
        f.write(f"content bytes先頭20: {resp.content[:20]}\n")
        f.write(f"content長さ: {len(resp.content)} bytes\n\n")

        for enc in ('utf-8', 'utf-8-sig', 'cp932', 'shift_jis', 'euc-jp'):
            try:
                decoded = resp.content.decode(enc)
                has_jp = any(k in decoded for k in ('騎手','回収','勝率','川田','傾向'))
                f.write(f"[{enc}] OK {len(decoded)}文字 日本語={has_jp} 先頭80={decoded[:80]}\n")
                if has_jp:
                    f.write(f"  -> {enc} が正解！\n")
                    for kw in ["回収率100", "回収率90", "100%以上", "90%以上", "傾向まとめ", "回収率"]:
                        idx = decoded.find(kw)
                        if idx >= 0:
                            f.write(f"  '{kw}' @ {idx}:\n{decoded[max(0,idx-50):idx+300]}\n\n")
                    break
            except Exception as e:
                f.write(f"[{enc}] 失敗: {e}\n")

    except Exception as e:
        f.write(f"requests失敗: {e}\n")

print("完了: dbkeiba_raw.txt に書き込みました")
