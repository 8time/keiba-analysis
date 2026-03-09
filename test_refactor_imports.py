import sys
import os

# Set output encoding to UTF-8
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_imports():
    print("Testing imports for refactored project...")
    try:
        from core import scraper
        print("[OK] core.scraper imported")
        from core import calculator
        print("[OK] core.calculator imported")
        from core import history_manager
        print("[OK] core.history_manager imported")
        from core import theory_rmhs
        print("[OK] core.theory_rmhs imported")
        
        # Test scraper's ability to find helpers
        h_path = os.path.join(os.path.dirname(scraper.__file__), "..", "utils", "fetch_helper.py")
        if os.path.exists(h_path):
            print(f"[OK] scraper can find fetch_helper at {h_path}")
        else:
            print(f"[ERR] scraper CANNOT find fetch_helper at {h_path}")
            
        adv_h_path = os.path.join(os.path.dirname(scraper.__file__), "..", "utils", "adv_fetch_helper.py")
        if os.path.exists(adv_h_path):
            print(f"[OK] scraper can find adv_fetch_helper at {adv_h_path}")
        else:
            print(f"[ERR] scraper CANNOT find adv_fetch_helper at {adv_h_path}")
            
        print("\nAll internal imports and path references verified!")
    except Exception as e:
        print(f"[ERR] Import failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    test_imports()
