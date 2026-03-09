
import pandas as pd
import kagglehub
import os
import logging
import json
import re
from datetime import datetime
import google.genai as genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)

class KaggleChatClient:
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(KaggleChatClient, cls).__new__(cls)
        return cls._instance

    def __init__(self, api_key: str = None):
        if api_key and not hasattr(self, 'client'):
            self.client = genai.Client(api_key=api_key)
        elif api_key and hasattr(self, 'client'):
            # Allow updating key if provided
             self.client = genai.Client(api_key=api_key)
            
        if hasattr(self, 'initialized') and self.initialized:
            return
            
        self.dataset_id = "noriyukifurufuru/japan-horse-racing-2010-2025"
        self.data_path = None
        self.dfs = {}
        self.client = genai.Client(api_key=api_key) if api_key else None
        self.interactions_file = os.path.join("data", "kaggle_interactions.json")
        self.initialized = True
        
        # Ensure data directory exists
        os.makedirs("data", exist_ok=True)
        if not os.path.exists(self.interactions_file):
            with open(self.interactions_file, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def load_data(self):
        """Kaggle からデータをロードしてメモリに保持する"""
        if self.dfs:
            return True
            
        try:
            logger.info("Downloading/Loading Kaggle dataset...")
            self.data_path = kagglehub.dataset_download(self.dataset_id)
            
            files = {
                "races": "keiba_races.csv",
                "results": "keiba_results.csv",
                "payouts": "keiba_payouts.csv"
            }
            
            for key, filename in files.items():
                full_path = os.path.join(self.data_path, filename)
                logger.info(f"Loading {filename}...")
                self.dfs[key] = pd.read_csv(
                    full_path, 
                    encoding='utf-8', 
                    on_bad_lines='skip', 
                    engine='python'
                )
                # 基本的な前処理
                if key == 'races':
                    self.dfs[key]['date'] = pd.to_datetime(self.dfs[key]['date'], errors='coerce')
            
            logger.info("Kaggle data loaded successfully.")
            return True
        except Exception as e:
            logger.error(f"Error loading Kaggle data: {e}")
            return False

    def ask(self, query: str):
        """自然言語の質問を解析して実行し、結果を返す"""
        if not self.client:
            return "API Key が設定されていません。", None
            
        if not self.dfs:
            if not self.load_data():
                return "データの読み込みに失敗しました。", None

        try:
            prompt = f"""
            あなたは競馬データ分析の専門家です。
            以下の pandas DataFrame を使用して、ユーザーの質問に答える Python コードを生成してください。
            
            DataFrame構成:
            - df_races: レース情報 (race_id, date, venue, race_name, distance, course_type, race_class)
            - df_results: 走破結果 (race_id, rank, number, horse_id, horse_name, odds, popularity)
            - df_payouts: 払戻 (race_id, bet_type, horse_num, payout)
            
            重要事項:
            - df_payouts['bet_type'] の値には '単勝', '複勝', '馬連', 'ワイド', '三連複', '三連単', '馬単', '枠連', '枠単' が含まれます。
            - 数値の「3」ではなく漢字の「三」を使用していることに注意してください（例: '三連複', '三連単'）。
            - `df_payouts['payout']` は数値変換してから計算してください。
            - 日付フィルタは `df_races['date']` (datetime型) を使用してください。
            - ERROR AVOIDANCE: 
              - 日付 (`date`) が `NaT` の場合があるため、`.strftime()` を呼ぶ前に `pd.notnull()` でチェックするか `fillna` してください。
              - フィルタの結果が空の可能性があるため、`.iloc[0]` を使う前に `.empty` をチェックしてください。
            
            ユーザーの質問: {query}
            
            出力ルール:
            - 変数名 `result_df` または `result_text` に最終的な回答を格納してください。
            - `result_text` には分析の構成や、平均配当・合計などの要約を日本語で入れてください。
            - レースIDを表示する際は、必ず netkeiba のリンク形式にしてください。
              - 形式: `[レースID](https://db.netkeiba.com/race/レースID/)` (バックティックで囲まないこと)
            - コードのみを出力し、解説は含めないでください。
            - インポート文(import pandas as pd等)は含めないでください。
            """

            response = self.client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[prompt],
                config=genai_types.GenerateContentConfig(
                    temperature=0.1
                )
            )

            code = self._extract_code(response.text)
            if not code:
                return "解析に必要なコードを生成できませんでした。", None

            # 2. 生成されたコードの実行環境を構築
            namespace = {
                'pd': pd,
                'df_races': self.dfs['races'],
                'df_results': self.dfs['results'],
                'df_payouts': self.dfs['payouts'],
                'result_df': None,
                'result_text': ""
            }
            
            try:
                exec(code, namespace)
            except Exception as e:
                logger.error(f"Code execution failed: {e}")
                return f"コードの実行中にエラーが発生しました: {e}\n\n生成されたコード:\n```python\n{code}\n```", None
            
            res_df = namespace.get('result_df')
            res_text = namespace.get('result_text')
            
            return res_text, res_df
            
        except Exception as e:
            logger.error(f"Kaggle Chat Error: {e}")
            return f"エラーが発生しました: {e}", None

    def _extract_code(self, text):
        """Markdown から Python コードブロックを抽出"""
        m = re.search(r'```(?:python)?\n(.*?)\n```', text, re.DOTALL)
        if m:
            return m.group(1)
        return text.strip().replace('```python', '').replace('```', '')

    def save_interaction(self, query, response_text, response_df=None):
        """やりとりを保存する"""
        try:
            with open(self.interactions_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
            
            df_json = None
            if response_df is not None:
                df_json = response_df.to_json(orient='split')
                
            entry = {
                'id': datetime.now().strftime('%Y%m%d_%H%M%S'),
                'timestamp': datetime.now().isoformat(),
                'query': query,
                'response_text': response_text,
                'response_df_json': df_json
            }
            
            history.append(entry)
            with open(self.interactions_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving interaction: {e}")
            return False

    def delete_interaction(self, interaction_id):
        """やりとりを削除する"""
        try:
            with open(self.interactions_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
            
            new_history = [item for item in history if item['id'] != interaction_id]
            
            with open(self.interactions_file, 'w', encoding='utf-8') as f:
                json.dump(new_history, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error deleting interaction: {e}")
            return False

    def get_saved_interactions(self):
        """保存されたやりとりを取得"""
        try:
            with open(self.interactions_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
