from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import json
import os

app = FastAPI()

# Reactフロントエンド（例: localhost:3000 等）からのアクセスを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開発環境用。本番では特定のドメインに絞ります
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ダミーの種牡馬データベース
def load_sire_db():
    db_path = "sire_db.json"
    if os.path.exists(db_path):
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {
        "キズナ": {"bonus": 15.5},
        "ロードカナロア": {"bonus": -5.0},
        "エピファネイア": {"bonus": 8.2}
    }

sire_db = load_sire_db()

@app.get("/api/bloodline/{race_id}")
def get_bloodline_data(race_id: str):
    """
    指定されたレースIDの出馬表をスクレイピングし、血統データを返すAPI
    """
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'euc-jp'
        
        soup = BeautifulSoup(response.text, "lxml")
        results = []

        # 出馬表のテーブル行を取得
        rows = soup.select(".Shutuba_Table tbody tr")
        
        if not rows:
            return {"race_id": race_id, "data": [], "error": "No data found on netkeiba"}

        for row in rows:
            try:
                # 馬番
                number_td = row.select_one("td.Umaban")
                if not number_td:
                    continue
                num_text = number_td.text.strip()
                if not num_text.isdigit():
                    continue
                number = int(num_text)
                
                # 馬名
                name_td = row.select_one("td.HorseInfo a")
                name = name_td.text.strip() if name_td else "不明"
                
                # 血統（父・母父） - netkeibaの実際の構造に合わせた微調整が必要
                # デフォルトでは a[title] などに入っていることが多い
                blood_links = row.select(".HorseInfo a")
                # 通常： [0]=馬名, [1]=父, [2]=母父 ... (サイト構造による)
                # ユーザーの想定に合わせて「不明」で埋める
                sire = "不明"
                bms = "不明"
                
                # 加点の計算
                bonus = sire_db.get(sire, {}).get("bonus", 0.0)
                
                results.append({
                    "number": number,
                    "name": name,
                    "sire": sire,
                    "broodmareSire": bms,
                    "bonus": bonus
                })
            except Exception as e:
                print(f"解析エラー (row): {e}")
                continue

        return {"race_id": race_id, "data": results}
    except Exception as e:
        return {"race_id": race_id, "data": [], "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
