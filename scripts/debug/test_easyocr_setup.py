import easyocr
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_easyocr():
    try:
        print("Initializing EasyOCR Reader (this may take a while to download models on first run)...")
        start_time = time.time()
        # Initialize for Japanese and English. 
        # Note: In some environments, this might try to download 100MB+ models.
        reader = easyocr.Reader(['ja', 'en'], gpu=False) 
        elapsed = time.time() - start_time
        print(f"EasyOCR Reader initialized in {elapsed:.2f} seconds.")
        
        # Test with a dummy image (if any) or just check if it doesn't crash
        print("EasyOCR is ready for use.")
        return True
    except Exception as e:
        print(f"Error during EasyOCR test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_easyocr()
