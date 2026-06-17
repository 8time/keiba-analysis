"""
Hyper-MAGI Sandbox (DGM-H: Darwin Gödel Machine - Hyperagents for Keiba)
このスクリプトは論文 "Hyperagents" の手法を完全実装し、AI自身が自律的にソースコードを改修する進化ループを実行します。

機能一覧:
1. アーカイブ構築（Stepping Stones）: 成功したコードはすべて保持し、系統樹として管理。
2. 探索 vs 搾取（Exploration vs Exploitation）:
   - ROIが高いエージェントを優先的に親として選出（Exploitation）。
   - しかし同じ親から何度も子を生成しすぎると（fertility過多）、優先度を下げて別系統を探索（Exploration）。
3. メタ認知自己改修 & 反省日記（Diary）: 失敗要因を自らRoot Cause Analysisし、IMPROVEMENTS.md に書き残して次に活かす。
4. Iteration-based Guidance: 残り世代数に応じた戦略的アドバイスの動的注入。
"""
import os
import sys
import re
import json
import shutil
import random
from datetime import datetime
import google.genai as genai
from google.genai import types

# --- パス設定 ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from core.magi_trainer import load_kaggle_data, load_weights

SANDBOX_DIR = os.path.join(BASE_DIR, "sandbox", "hyperagents")
ARCHIVES_DIR = os.path.join(SANDBOX_DIR, "stepping_stones")
METRICS_DB = os.path.join(SANDBOX_DIR, "archive_db.json")
DIARY_FILE = os.path.join(SANDBOX_DIR, "IMPROVEMENTS.md")
ORIGINAL_SYSTEM_PATH = os.path.join(BASE_DIR, "core", "magi_system.py")

os.makedirs(ARCHIVES_DIR, exist_ok=True)

class HyperArchive:
    def __init__(self):
        self.nodes = {}  # id -> {id, parent_id, path, roi, hit_rate, fertility, generation}
        self.load()

    def load(self):
        if os.path.exists(METRICS_DB):
            with open(METRICS_DB, "r", encoding="utf-8") as f:
                self.nodes = json.load(f)

    def save(self):
        with open(METRICS_DB, "w", encoding="utf-8") as f:
            json.dump(self.nodes, f, ensure_ascii=False, indent=2)

    def add_node(self, node_id, parent_id, path, roi, hit_rate, generation):
        self.nodes[node_id] = {
            "id": node_id,
            "parent_id": parent_id,
            "path": path,
            "roi": roi,
            "hit_rate": hit_rate,
            "fertility": 0, # 何個の子の親として選ばれ、コードがコンパイル成功したか
            "generation": generation
        }
        self.save()

    def select_parent(self) -> dict:
        """論文に基づく: 成績(ROI)が高いものを優遇(Exploitation)しつつ、多産(Fertility)な親はペナルティ(Exploration)"""
        if not self.nodes:
            return None
        
        candidates = list(self.nodes.values())
        if len(candidates) == 1:
            return candidates[0]

        best_roi = max(c['roi'] for c in candidates)
        min_roi = min(c['roi'] for c in candidates)
        range_roi = max(0.01, best_roi - min_roi)

        scores = []
        for c in candidates:
            # ROI正規化 (0.0 - 1.0)
            norm_roi = (c['roi'] - min_roi) / range_roi
            # Fertilityペナルティ (沢山子を作ったらスコアダウン)
            fertility_penalty = 1.0 / (1.0 + c['fertility'] * 0.5) 
            
            # Selection Score = normalized_score + exploration_weight
            # 論文式に近い確率選択を行う
            selection_score = norm_roi * 0.7 + fertility_penalty * 0.3
            scores.append(max(0.01, selection_score))

        total_score = sum(scores)
        probs = [s / total_score for s in scores]
        selected = random.choices(candidates, weights=probs, k=1)[0]
        return selected

    def increase_fertility(self, node_id):
        if node_id in self.nodes:
            self.nodes[node_id]['fertility'] += 1
            self.save()

    def get_best_roi(self):
        if not self.nodes: return -999.0
        return max(c['roi'] for c in self.nodes.values())

def run_evaluation(script_path: str, n_samples: int = 50) -> dict:
    import importlib.util
    module_name = f"sandbox_magi_eval_{int(datetime.now().timestamp())}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        return {"error": f"Syntax/Compile Error: {e}"}

    import core.magi_trainer as trainer
    dfs = load_kaggle_data()
    if not dfs:
        return {"error": "Kaggleデータがありません"}
        
    weights = load_weights()
    res = trainer.backtest(dfs, weights, n_samples=n_samples)
    return res

def meta_agent_generate(parent_code: str, diary_history: str, metrics: dict, iterations_left: int, api_key: str) -> dict:
    """Hyperagent (Meta) として、反省日記と新コードを出力する"""
    client = genai.Client(api_key=api_key)
    
    # イテレーションの残り回数に応じたダイナミックガイダンス（論文踏襲）
    if iterations_left > 15:
        guidance = "You have many iterations remaining. Consider making fundamental improvements and introducing new metrics from the available columns."
    elif iterations_left > 5:
        guidance = "You have moderate iterations remaining. Focus on refining existing mechanisms and finding complex non-linear combinations (pattern discovery)."
    else:
        guidance = "Focus on stability, final polishing, and removing any logic that overfits."

    roi = metrics.get('roi', 0.0)
    
    prompt = f"""
あなたは競馬AI「MAGIシステム」の自己進化を司るHyperagent（Meta Agent）です。
DGM-Hの原則に従い、自身のタスクエージェント（Pythonコード）を再設計し、回収率(ROI)を進化させてください。

[システム状態]
- 現在の親のROI(回収率): {roi}%
- 残り世代数: {iterations_left}
- 戦略ガイダンス: {guidance}

[直近の反省日記 (IMPROVEMENTS.md)]
{diary_history[-1000:] if diary_history else "まだ日記はありません。"}

[指示]
1. `melchior_analyze`, `balthasar_analyze`, または `casper_analyze` の判定ロジックを直接改修してください。
2. 既に付与されている `MakuriPower`, `MatchScore`, `HiddenGem`, `AvgPosition` などの指標を活用し、「危険な上位人気を削る」か「6位以下の大穴を引き上げる」機構を強化してください。
3. 以下の2点を出力してください。
   (A) 新しい反省と戦略（Root Cause Analysis / Action Plan）
   (B) 完全なPythonコード（`magi_system.py`の全文）
   
出力フォーマット:
<DIARY>
Problem Identified: ...
Root Cause Analysis: ...
Action Plan: ...
</DIARY>

```python
[ここに変更を加えた完全なソースコードを記述。省略不可]
```
"""
    
    print("🧠 Meta Agent is thinking... (gemini-3.1-flash-lite)")
    import time
    time.sleep(10) # API制限回避のための待機時間
    
    response = client.models.generate_content(
        model='gemini-3.1-flash-lite',
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.7)
    )
    
    diary_match = re.search(r'<DIARY>(.*?)</DIARY>', response.text, re.DOTALL)
    code_match = re.search(r'```python\n(.*?)\n```', response.text, re.DOTALL)
    
    return {
        "diary": diary_match.group(1).strip() if diary_match else "分析なし",
        "code": code_match.group(1) if code_match else response.text
    }

def main(total_iterations: int = 50, n_samples: int = 30):
    api_key = os.environ.get("GEMINI_API_KEY")
    
    # .streamlit/secrets.toml から直接パース
    if not api_key:
        try:
            secrets_path = os.path.join(BASE_DIR, ".streamlit", "secrets.toml")
            if os.path.exists(secrets_path):
                with open(secrets_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if "GEMINI_API_KEY" in line and "=" in line:
                            api_key = line.split("=")[1].strip().strip('"').strip("'")
                            break
        except Exception:
            pass
            
    if not api_key:
        print("GEMINI_API_KEY が環境変数または .streamlit/secrets.toml に見つかりません。")
        return
        
    archive = HyperArchive()
    
    # 初代(Node 0)の準備
    if not archive.nodes:
        print("🌱 Initializing Generation 0 (Node 0) from original system...")
        base_id = "node_0"
        base_path = os.path.join(ARCHIVES_DIR, f"{base_id}.py")
        shutil.copy(ORIGINAL_SYSTEM_PATH, base_path)
        
        metrics = run_evaluation(base_path, n_samples)
        if "error" in metrics:
            print("初期ファイルエラー:", metrics["error"])
            return
            
        roi = metrics.get('roi', 0.0)
        archive.add_node(base_id, "root", base_path, roi, metrics.get('casper_hit_rate', 0.0), 0)
        print(f"Node 0 ROI: {roi}%")

    print(f"\n🚀 DGM-H Evolution Loop 起動 (全{total_iterations}回) 🚀")
    
    for gen in range(1, total_iterations + 1):
        print(f"\n[{gen}/{total_iterations}] Selecting Parent...")
        parent = archive.select_parent()
        print(f"-> Parent Selected: {parent['id']} (ROI: {parent['roi']}%, Fertility: {parent['fertility']})")
        
        # 日記を読み込み
        diary_hist = ""
        if os.path.exists(DIARY_FILE):
            with open(DIARY_FILE, "r", encoding="utf-8") as f:
                diary_hist = f.read()

        with open(parent["path"], "r", encoding="utf-8") as f:
            p_code = f.read()
            
        print("🧠 Meta Agent is thinking and rewriting code...")
        output = meta_agent_generate(
            parent_code=p_code, 
            diary_history=diary_hist,
            metrics={"roi": parent["roi"]},
            iterations_left=(total_iterations - gen),
            api_key=api_key
        )
        
        child_id = f"node_{int(datetime.now().timestamp())}"
        child_path = os.path.join(ARCHIVES_DIR, f"{child_id}.py")
        
        with open(child_path, "w", encoding="utf-8") as f:
            f.write(output["code"])
            
        print(f"⚙️ Evaluating Child {child_id}...")
        c_metrics = run_evaluation(child_path, n_samples)
        
        if "error" in c_metrics:
            print(f"❌ Syntax or Compile Error in Child. Discarding: {c_metrics['error'][:80]}")
            os.remove(child_path)
            continue
            
        archive.increase_fertility(parent["id"])  # 親としての役割を果たした
            
        c_roi = c_metrics.get('roi', 0.0)
        print(f"-> Child ROI: {c_roi}%")
        
        # 論文通り、アーカイブには常に保存して多様性を維持 (あまりに酷いものは捨てる)
        if c_roi > -50.0:  
            archive.add_node(child_id, parent["id"], child_path, c_roi, c_metrics.get('casper_hit_rate', 0.0), gen)
            
            # 日記へ記録
            with open(DIARY_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n\n## Generation {gen} (Parent: {parent['id']} -> Child: {child_id})\n")
                f.write(f"**Parent ROI**: {parent['roi']}% -> **Child ROI**: {c_roi}%\n")
                f.write(f"**Meta Agent Diary**:\n{output['diary']}\n")
                
            if c_roi > archive.get_best_roi():
                print("🏆 NEW GLOBAL BEST ROI!")

if __name__ == "__main__":
    # デフォルトで50回イテレーションを回す
    main(total_iterations=50, n_samples=30)
