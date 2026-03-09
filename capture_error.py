import traceback
import sys

try:
    import app
    print("Import successful")
except SyntaxError as e:
    with open("error_log.txt", "w", encoding="utf-8") as f:
        f.write(f"SyntaxError: {e}\n")
        f.write(f"File: {e.filename}\n")
        f.write(f"Line: {e.lineno}\n")
        f.write(f"Offset: {e.offset}\n")
        f.write(f"Text: {e.text}\n")
except Exception as e:
    with open("error_log.txt", "w", encoding="utf-8") as f:
        f.write(f"Unexpected error: {type(e).__name__}: {e}\n")
        f.write(traceback.format_exc())
