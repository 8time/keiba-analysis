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
        Returns: (data_list, error_msg)
        """
        try:
            # Prepare image
            image = PIL.Image.open(io.BytesIO(image_bytes))
            
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

            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[prompt, image],
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.1
                )
            )

            # JSON パース
            if not response or not response.text:
                return None, "AI から空のレスポンスが返されました。", []
                
            clean_text = response.text.strip()
            # Remove possible markdown fences
            if clean_text.startswith("```"):
                lines = clean_text.splitlines()
                if lines[0].startswith("```"): lines = lines[1:]
                if lines[-1].startswith("```"): lines = lines[:-1]
                clean_text = "\n".join(lines).strip()

            data = json.loads(clean_text)
            logger.info(f"AI extracted {len(data)} horses from image.")
            return data, None, []
            
        except Exception as e:
            err_msg = str(e)
            logger.error(f"Image analysis failed: {err_msg}")
            # return traceback too? maybe unnecessary for user
            return None, f"解析中にエラーが発生しました: {err_msg}", []

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
