# -*- coding: utf-8 -*-
"""decision_chain の表示文レビュー用"""
import sys

sys.path.insert(0, r"C:\Users\kimnhaty\.gemini\antigravity\scratch\keiba_analysis")
from core import bettype_selector as b

for z, n, src in [("D", 1, "computed"), ("C", 2, "computed"), ("C", 3, "computed"),
                  ("C", 0, "unavailable"), ("BA", 4, "computed")]:
    d = b.decision_chain(z, n, cross_n_source=src)
    print(f"--- zone={z} cross_n={n} ({src}) ---")
    for i, s in enumerate(d["steps"], 1):
        print(f"  {i}. {s}")
    print("  => plain=", d["plain"], "/ skip=", d["skip"])
