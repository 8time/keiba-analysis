import sys
import io

# Test 1: Verify stdout encoding
try:
    sys.stdout.reconfigure(encoding='utf-8')
    print("✅ Stdout reconfigured to utf-8")
except Exception as e:
    print(f"❌ Stdout reconfiguration failed: {e}")

# Test 2: Import modules to check for immediate errors
try:
    import scraper
    print("✅ scraper module imported")
except Exception as e:
    print(f"❌ scraper import failed: {e}")

try:
    import app
    print("✅ app module imported")
except Exception as e:
    print(f"❌ app import failed: {e}")

try:
    import history_manager
    print("✅ history_manager module imported")
except Exception as e:
    print(f"❌ history_manager import failed: {e}")

try:
    import dump_html
    print("✅ dump_html module imported")
except Exception as e:
    print(f"❌ dump_html import failed: {e}")

print("✨ All checks passed (if no ❌ seen).")
