import sys
from bs4 import BeautifulSoup

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

with open("l_dump.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f, "html.parser")

table = soup.find("table", class_="yokobashiraTable")
if not table:
    th = soup.find("th", class_="THShisu")
    if th:
        table = th.find_parent("table")

if table:
    print(f"Table found. Classes: {table.get('class')}")
    tbody = table.find("tbody")
    rows = tbody.find_all("tr")
    print(f"Total rows in tbody: {len(rows)}")
    
    count = 0
    for row in rows:
        cells = row.find_all("td")
        if len(cells) > 1:
            umaban_text = cells[1].get_text(strip=True)
            if umaban_text.isdigit():
                count += 1
                if count <= 2: # Just show first two horses
                    print(f"--- Horse {count} (Umaban: {umaban_text}) ---")
                    for i, cell in enumerate(cells):
                        print(f"Col {i}: {cell.get_text(strip=True)[:50]} (Class: {cell.get('class')})")
    print(f"Horse rows found: {count}")
else:
    print("Table not found.")
