import PIL.Image
import google.genai as genai
from google.genai import types as genai_types
import json
import logging
import os
import re
import io
import pandas as pd

logger = logging.getLogger(__name__)

class VisionOddsAnalyzer:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.model_id = "gemini-1.5-flash"

    def analyze_odds_image(self, image_bytes: bytes):
        """
        Gemini API を使用してオッズ画像を解析し、構造化データを抽出する。
        Returns: (data_list, error_msg, dummy_list)
        """
        # Prepare image
        try:
            image = PIL.Image.open(io.BytesIO(image_bytes))
        except Exception as e:
            return None, f"画像の読み込みに失敗しました: {e}", []
            
        prompt = """
        あなたは競馬のプロフェッショナルです。
        添付された画像のオッズ表（netkeiba等の形式）から、全ての馬のデータを抽出してください。
        
        表の見出し（馬番、人気、単勝、複勝など）を正確に読み取り、以下の項目を抽出してください：
        - 馬番 (umaban)
        - 人気 (popularity)
        - 単勝オッズ (win_odds)
        - 複勝オッズ[下限] (place_min)
        - 複勝オッズ[上限] (place_max)

        画像内に表示されている全頭分のデータを抽出してください。
        数値が読み取れない場合は省略せず null を設定してください。
        """

        # schema definition for structured output
        schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "umaban": {"type": "INTEGER"},
                    "popularity": {"type": "INTEGER"},
                    "win_odds": {"type": "NUMBER"},
                    "place_min": {"type": "NUMBER"},
                    "place_max": {"type": "NUMBER"},
                },
                "required": ["umaban"]
            }
        }

        import time
        models_to_try = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-3.1-flash-lite-preview"]
        last_error = ""

        for model_id in models_to_try:
            retries = 2
            wait_sec = 2
            while retries > 0:
                try:
                    response = self.client.models.generate_content(
                        model=model_id,
                        contents=[prompt, image],
                        config=genai_types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=schema,
                            temperature=0.1
                        )
                    )

                    if not response or not response.text:
                        continue
                        
                    clean_text = response.text.strip()
                    if clean_text.startswith("```"):
                        lines = clean_text.splitlines()
                        if lines[0].startswith("```"): lines = lines[1:]
                        if lines[-1].startswith("```"): lines = lines[:-1]
                        clean_text = "\n".join(lines).strip()

                    data = json.loads(clean_text)
                    logger.info(f"AI extracted {len(data)} horses from image using {model_id}.")
                    return data, None, []

                except Exception as e:
                    err_msg = str(e)
                    last_error = err_msg
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        logger.warning(f"Quota exceeded for {model_id} (Vision). Retrying in {wait_sec}s...")
                        time.sleep(wait_sec)
                        retries -= 1
                        wait_sec *= 2
                    else:
                        break
            logger.info(f"Vision model {model_id} exhausted. Trying next...")

        if "429" in last_error or "RESOURCE_EXHAUSTED" in last_error:
            return None, "⚠️ AIの利用制限に達しました。1分ほど待ってから再試行してください。", []
        return None, f"解析中にエラーが発生しました: {last_error}", []

    def merge_vision_data(self, df, vision_data):
        """
        解析されたデータを既存の DataFrame にマージする。
        馬番をキーにして、単勝・人気・複勝データを更新。
        """
        if not vision_data or df.empty:
            return df
            
        v_df = pd.DataFrame(vision_data)
        # カラム名の変換
        v_df = v_df.rename(columns={
            "umaban": "Umaban",
            "popularity": "Popularity",
            "win_odds": "Odds",
            "place_min": "Show Odds (Min)",
            "place_max": "Show Odds (Max)"
        })
        
        # 型の統一
        df['Umaban'] = df['Umaban'].astype(int)
        v_df['Umaban'] = v_df['Umaban'].astype(int)
        
        # マージ ( vision_data がある馬だけ上書き)
        for _, row in v_df.iterrows():
            idx = df[df['Umaban'] == row['Umaban']].index
            if not idx.empty:
                i = idx[0]
                if pd.notna(row['Odds']): df.at[i, 'Odds'] = row['Odds']
                if pd.notna(row['Popularity']): df.at[i, 'Popularity'] = row['Popularity']
                if pd.notna(row['Show Odds (Min)']): df.at[i, 'Show Odds (Min)'] = row['Show Odds (Min)']
                if pd.notna(row['Show Odds (Max)']): df.at[i, 'Show Odds (Max)'] = row['Show Odds (Max)']
                
        return df
