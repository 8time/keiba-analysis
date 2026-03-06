import requests

url = "https://race.netkeiba.com/race/shutuba_past.html?race_id=202409020601"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

print(f"Fetching {url}")
response = requests.get(url, headers=headers)
content = response.content

print(f"Content Length: {len(content)}")
print("First 200 bytes (hex):")
print(content[:200].hex())

# Try decoding specific known string if position known?
# Let's just try to find "良" (EUC-JP: A4 C2) or "芝" (EUC-JP: BC C7)
# Scan for A4C2
if b'\xa4\xc2' in content:
    print("Found '良' (EUC-JP)")
if b'\xbc\xc7' in content:
    print("Found '芝' (EUC-JP)")
    
# Check UTF-8 for "良" (E8 89 AF)
if b'\xe8\x89\xaf' in content:
    print("Found '良' (UTF-8)")
    
# Check Shift-JIS for "良" (97 C良)
if b'\x97\xcc' in content:
    print("Found '良' (Shift-JIS)")
