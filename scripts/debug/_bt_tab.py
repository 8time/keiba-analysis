import ast, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
root = Path(__file__).resolve().parents[2]
cats = {
    'elim': '消去/フィルター',
    'folklore': '俗説',
    'trio': '3連複/券種',
    'trifecta': '3連単',
    'formation': 'フォーメーション',
    'jrdb': 'JRDB',
    'nar': '地方/NAR',
    'jockey': '騎手',
    'pace': 'ペース/展開',
    'arare': '荒れ',
    'vh': '穴馬/ValueHunter',
    'pci': 'PCI',
    'blood': '血統',
    'training': '調教',
    'spurt': '末脚',
    'axis': '軸馬',
    'hunter': 'ハンター',
    'other': 'その他',
}
for p in sorted(root.glob('scripts/**/*backtest*.py')):
    t = p.read_text(encoding='utf-8', errors='replace')
    try:
        doc = (ast.get_docstring(ast.parse(t)) or '').strip().replace('\n', ' ')[:140]
    except Exception:
        doc = ''
    cat = 'other'
    n = p.stem
    for k in cats:
        if k in n:
            cat = k
            break
    src = 'jravan.db' if 'jravan' in t else ('export CSV' if 'export/' in t or 'horse_races' in t else ('scrape' if 'fetch_robust' in t or 'scraper' in t else '?'))
    met = []
    for m in ['ROI', '回収', '的中', 'recall', 'capture', '複勝', '残差']:
        if m in t:
            met.append(m)
    out = 'CSV' if 'to_csv' in t else 'stdout'
    print(f"{p.name}\t{cat}\t{src}\t{','.join(met) or '-'}\t{out}\t{doc}")
