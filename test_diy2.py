import pandas as pd
import numpy as np
import calculator
import sys

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

# Mock DataFrame
data = [
    {
        'Umaban': 1, 'Name': 'Fast Horse', 
        'CurrentSurface': '芝', 'CurrentDistance': 1600,
        'PastRuns': [
            {'Surface': '芝', 'Distance': 1600, 'Time': 93.0},
            {'Surface': '芝', 'Distance': 1400, 'Time': 81.0}
        ]
    },
    {
        'Umaban': 2, 'Name': 'Slow Horse', 
        'CurrentSurface': '芝', 'CurrentDistance': 1600,
        'PastRuns': [
            {'Surface': '芝', 'Distance': 1600, 'Time': 96.0}
        ]
    },
    {
        'Umaban': 3, 'Name': 'Average Horse', 
        'CurrentSurface': '芝', 'CurrentDistance': 1600,
        'PastRuns': [
            {'Surface': '芝', 'Distance': 1600, 'Time': 94.5}
        ]
    },
    {
         'Umaban': 4, 'Name': 'Different Surf', 
        'CurrentSurface': '芝', 'CurrentDistance': 1600,
        'PastRuns': [
            {'Surface': 'ダ', 'Distance': 1600, 'Time': 100.0}
        ]
    }
]

df = pd.DataFrame(data)
df = calculator.calculate_diy2_index(df)

print("DIY2 Calculation Results:")
print(df[['Umaban', 'Name', 'DIY2_Index']])

# Verify Logic: 
# Fast (93.0), Slow (96.0), Avg (94.5)
# Mean = 94.5, Std = sqrt((1.5**2 + 1.5**2 + 0)/3) = sqrt(1.5) approx 1.22
# Fast T-Score = 50 + 10 * (94.5 - 93.0) / 1.22 approx 50 + 12.29 = 62.3
# Different Surf should get 50.0
