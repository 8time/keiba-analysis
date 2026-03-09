import traceback
import sys

try:
    import core.scraper
    print("Import successful")
except Exception as e:
    print(f"Import failed: {e}")
    traceback.print_exc()
    sys.exit(1)
except SyntaxError as e:
    print(f"Syntax error: {e}")
    traceback.print_exc()
    sys.exit(1)
