from bs4 import BeautifulSoup
import sys

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

with open("u_8_1_dump.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f, "html.parser")

rows = soup.find_all("tr", class_=["odd-row", "even-row"])
print(f"Total rows found: {len(rows)}")

for i, row in enumerate(rows[:5]):
    cells = row.find_all("td", recursive=False)
    index = i + 1
    print(f"--- Row {index} ---")
    for j, cell in enumerate(cells):
        text = cell.get_text(strip=True)
        print(f"  Col {j}: {text[:50]} (Class: {cell.get('class')})")
