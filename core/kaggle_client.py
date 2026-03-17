
import pandas as pd
import kagglehub
import os
import logging
import json
import re
import pickle
from datetime import datetime
import google.genai as genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)

CACHE_PATH = "/tmp/keiba_kaggle_cache.pkl"

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
        self._loaded = False
        self.client = genai.Client(api_key=api_key) if api_key else None
        self.interactions_file = os.path.join("data", "kaggle_interactions.json")
        self.initialized = True
        
        # Ensure data directory exists
        os.makedirs("data", exist_ok=True)
        if not os.path.exists(self.interactions_file):
            with open(self.interactions_file, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def is_loaded(self) -> bool:
        """データがメモリにロード済みかどうかを返す"""
        return self._loaded and bool(self.dfs)

    def load_data(self):
        """Kaggle からデータをロードしてメモリに保持する（/tmp pickle キャッシュ対応）"""
        if self._loaded and self.dfs:
            return True

        # /tmp pickle キャッシュを試みる
        try:
            if os.path.exists(CACHE_PATH):
                logger.info(f"Loading Kaggle data from cache: {CACHE_PATH}")
                with open(CACHE_PATH, 'rb') as f:
                    self.dfs = pickle.load(f)
                self._loaded = True
                logger.info("Kaggle data loaded from cache.")
                return True
        except Exception as e:
            logger.warning(f"Cache load failed, will re-download: {e}")
            self.dfs = {}

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

            # /tmp にキャッシュ保存
            try:
                with open(CACHE_PATH, 'wb') as f:
                    pickle.dump(self.dfs, f)
                logger.info(f"Kaggle data cached to {CACHE_PATH}")
            except Exception as ce:
                logger.warning(f"Cache save failed (non-fatal): {ce}")

            self._loaded = True
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

        import time
        
        prompt = f"""
        あなたは競馬データ分析の専門家です。
        以下の pandas DataFrame を使用して、ユーザーの質問に答える Python コードを生成してください。
        
        DataFrame構成:
        - df_races: レース情報 (race_id, date, venue, race_name, distance, course_type, race_class)
        - df_results: 走破結果 (race_id, rank, number, horse_id, horse_name, odds, popularity)
        - df_payouts: 払戻 (race_id, bet_type, horse_num, payout)
        
        重要事項:
        - df_payouts['bet_type'] の値には '単勝', '複勝', '馬連', 'ワイド', '三連複', '三連単', '馬単', '枠連', '枠単' が含まれます。
        - 三連複・三連単などの「三」は漢数字を使用してください。
        - `df_payouts['payout']` は数値変換してから計算してください。
        - 日付フィルタは `df_races['date']` (datetime型) を使用してください。
        - フィルタ結果が空の可能性があるため、`.iloc[0]` を使う前に `.empty` をチェックしてください。
        
        ユーザーの質問: {query}
        
        出力ルール:
        - 変数名 `result_df` または `result_text` に回答を格納してください。
        - レースIDを表示する際は `[レースID](https://db.netkeiba.com/race/レースID/)` 形式にしてください。
        - コードのみを出力し、解説は含めないでください。
        """

        models_to_try = ["gemini-3.1-flash-lite-preview"]
        last_error = ""

        for model_id in models_to_try:
            retries = 3
            wait_sec = 2
            
            while retries > 0:
                try:
                    response = self.client.models.generate_content(
                        model=model_id,
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
                    err_msg = str(e)
                    last_error = err_msg
                    
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        logger.warning(f"Quota exceeded for {model_id}. Retrying in {wait_sec}s... ({retries-1} left)")
                        time.sleep(wait_sec)
                        retries -= 1
                        wait_sec *= 2
                    else:
                        # 他のエラー（認証エラー等）は即座に終了
                        logger.error(f"Gemini API Error ({model_id}): {err_msg}")
                        break # Try next model or fail
            
            logger.info(f"Model {model_id} failed or exhausted. Trying next fallback...")

        # 全ての試行が失敗した場合
        if "429" in last_error or "RESOURCE_EXHAUSTED" in last_error:
            return "⚠️ AIの利用制限（リミット）に達しました。無料枠の上限のため、30秒〜1分ほど待ってから再試行してください。もしくは API Key の有効期限や制限設定を確認してください。", None
        
        return f"エラーが発生しました: {last_error}", None

    def generate_content(self, contents, temperature=0.2):
        """
        AI呼び出しにリトライとモデルフォールバックを適用する汎用メソッド。
        contents: 文字列のリスト（システムプロンプト等を含む）
        """
        if not self.client:
            return "API Key が設定されていないため、AI機能を利用できません。"

        import time
        models_to_try = ["gemini-3.1-flash-lite-preview"]
        last_error = ""

        for model_id in models_to_try:
            retries = 3
            wait_sec = 2
            while retries > 0:
                try:
                    response = self.client.models.generate_content(
                        model=model_id,
                        contents=contents,
                        config=genai_types.GenerateContentConfig(temperature=temperature)
                    )
                    if response and response.text:
                        return response.text
                    return "AIからの応答が空でした。"
                except Exception as e:
                    err_msg = str(e)
                    last_error = err_msg
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        logger.warning(f"Quota exceeded for {model_id}. Retrying in {wait_sec}s...")
                        time.sleep(wait_sec)
                        retries -= 1
                        wait_sec *= 2
                    else:
                        logger.error(f"AI Generate Error ({model_id}): {err_msg}")
                        break # 他のエラーは現在のモデルを諦める
            logger.info(f"Model {model_id} exhausted or failed. Falling back...")

        if "429" in last_error or "RESOURCE_EXHAUSTED" in last_error:
            return "⚠️ AI利用制限（429）に達しました。30秒ほど待ってから再試行してください。"
        return f"AI解析中にエラーが発生しました: {last_error}"

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
