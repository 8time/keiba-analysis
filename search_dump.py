def search_dump():
    with open("shutuba_dump.html", "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    for i, line in enumerate(lines):
        if "指数" in line or "timeindex" in line:
            print(f"Line {i}: {line.strip()}")

if __name__ == "__main__":
    search_dump()
