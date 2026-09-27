"""Extract backtest script summaries."""
import ast
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
scripts = sorted(root.glob("scripts/**/*backtest*.py"))
if not scripts:
    scripts = sorted(root.glob("scripts/*backtest*.py"))

for p in scripts:
    text = p.read_text(encoding="utf-8", errors="replace")
    doc = ast.get_docstring(ast.parse(text)) or ""
    doc1 = doc.strip().split("\n")[0][:120] if doc else ""
    inputs = []
    for pat in [
        r"jravan\.db",
        r"race_history",
        r"keiba_results",
        r"fetch_robust",
        r"scraper",
        r"payouts",
        r"\.csv",
        r"\.json",
        r"\.db",
    ]:
        if re.search(pat, text, re.I):
            inputs.append(pat)
    metrics = []
    for m in ["ROI", "回収", "的中", "複勝", "勝率", "recall", "capture", "Brier", "z-score", "残差"]:
        if m.lower() in text.lower() or m in text:
            metrics.append(m)
    out = "stdout"
    if "to_csv" in text or ".csv" in text.split("if __name__")[-1]:
        out = "csv+stdout"
    print(f"FILE|{p.name}")
    print(f"DESC|{doc1}")
    print(f"INPUT|{','.join(sorted(set(inputs))[:6]) or 'unknown'}")
    print(f"METRIC|{','.join(sorted(set(metrics))[:8]) or 'unknown'}")
    print(f"OUT|{out}")
    print("---")
