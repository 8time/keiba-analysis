
import sys
import os
import pandas as pd

# Add current dir to path to import core modules
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

import pandas as pd
from core.local_vision_analyzer import LocalVisionOddsAnalyzer

def test_parsing():
    # Use dummy languages to avoid reader init if we only test _parse_ocr_results
    analyzer = LocalVisionOddsAnalyzer()
    
    # Mock OCR results (bbox, text, confidence)
    # Netkeiba layout: [Umaban] [Ninki] [Win Odds] [Place Odds Min] [Place Odds Max]
    # Represented as: (bbox, text, conf)
    # bbox format: [[x0,y0], [x1,y1], [x2,y2], [x3,y3]]
    mock_results = [
        # Horse 1
        ([[10, 100], [30, 100], [30, 120], [10, 120]], "1", 0.99),
        ([[50, 100], [70, 100], [70, 120], [50, 120]], "5", 0.99),
        ([[100, 100], [150, 100], [150, 120], [100, 120]], "15.3", 0.99),
        # Horse 2 (Mixed order in results, simulating OCR detection order)
        ([[100, 150], [150, 150], [150, 170], [100, 170]], "55.5", 0.99),
        ([[10, 150], [30, 150], [30, 170], [10, 170]], "2", 0.99),
        ([[50, 150], [70, 150], [70, 170], [50, 170]], "10", 0.99),
    ]
    
    print("Testing new OCR parsing logic...")
    data, debug = analyzer._parse_ocr_results(mock_results)
    
    print("\n--- Parsed Data ---")
    for d in data:
        print(d)
    
    print("\n--- Debug Info ---")
    for line in debug:
        print(line)

    # Verification
    assert len(data) == 2
    assert data[0]['umaban'] == 1
    assert data[0]['popularity'] == 5
    assert data[0]['win_odds'] == 15.3
    
    assert data[1]['umaban'] == 2
    assert data[1]['popularity'] == 10
    assert data[1]['win_odds'] == 55.5
    
    print("\nResult: SUCCESS! Coordinates handled correctly.")

if __name__ == "__main__":
    test_parsing()
