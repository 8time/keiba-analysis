"""
Debug script: dump the HTML structure of a netkeiba shutuba page
to identify correct CSS selectors for odds and popularity columns.
"""
import sys
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

import requests
from bs4 import BeautifulSoup

URL = "https://race.netkeiba.com/race/shutuba.html?race_id=202506030811"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}

print(f"Fetching: {URL}")
resp = requests.get(URL, headers=HEADERS, timeout=15)
resp.encoding = 'utf-8'
print(f"Status: {resp.status_code}, Length: {len(resp.text)}")

soup = BeautifulSoup(resp.text, "html.parser")

# Try multiple table selectors
table = soup.select_one("#shutuba_table") or soup.select_one("table.Shutuba_Table") or soup.select_one("table.RaceTable01")
if not table:
    print("ERROR: Could not find shutuba table. Trying all tables...")
    for t in soup.find_all("table"):
        classes = t.get("class", [])
        tid = t.get("id", "")
        print(f"  table id={tid!r} class={classes}")
    # Also dump part of raw HTML to find the table
    text = resp.text
    for keyword in ["Shutuba", "HorseList", "shutuba_table", "RaceTable"]:
        idx = text.find(keyword)
        if idx >= 0:
            print(f"\n--- Found '{keyword}' at position {idx} ---")
            print(text[max(0, idx-200):idx+300])
    sys.exit(1)

print(f"\nFound table: id={table.get('id', '')!r}, class={table.get('class', [])}")

# Print header row if available
thead = table.select_one("thead tr, tr.Header")
if thead:
    print("\n=== HEADER ROW ===")
    for i, th in enumerate(thead.find_all(["th", "td"])):
        cls = th.get("class", [])
        print(f"  [{i}] tag={th.name} class={cls} text={th.get_text(strip=True)!r}")

# Find first HorseList row
rows = table.select("tr.HorseList")
if not rows:
    rows = table.select("tr[id]")  # fallback
if not rows:
    print("ERROR: No HorseList rows found. All tr classes:")
    for tr in table.find_all("tr"):
        print(f"  tr class={tr.get('class', [])}")
    sys.exit(1)

print(f"\nFound {len(rows)} HorseList rows")

# Dump first row in detail
row = rows[0]
print(f"\n=== FIRST ROW: class={row.get('class', [])} id={row.get('id', '')} ===")
print("\n--- All TD elements ---")
for i, td in enumerate(row.find_all("td")):
    cls = td.get("class", [])
    text = td.get_text(strip=True)
    # Also check for nested spans/divs
    children = []
    for child in td.children:
        if hasattr(child, 'name') and child.name:
            children.append(f"{child.name}.{child.get('class', [])}")
    children_str = f" children=[{', '.join(children)}]" if children else ""
    print(f"  [{i:2d}] class={cls!r:<40s} text={text!r:<30s}{children_str}")

print("\n--- Raw HTML of first row ---")
print(row.prettify()[:3000])

# Also check second row for comparison
if len(rows) > 1:
    row2 = rows[1]
    print(f"\n=== SECOND ROW (for comparison) ===")
    for i, td in enumerate(row2.find_all("td")):
        cls = td.get("class", [])
        text = td.get_text(strip=True)
        print(f"  [{i:2d}] class={cls!r:<40s} text={text!r}")
