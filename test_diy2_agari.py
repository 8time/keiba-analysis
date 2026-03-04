import pandas as pd
import numpy as np
import calculator
import sys

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

# Mock DataFrame
data = [
    {
        'Umaban': 1, 'Name': 'Speedy Finisher', 
        'PastRuns': [
            {'Agari': 33.5},
            {'Agari': 34.0}
        ]
    },
    {
        'Umaban': 2, 'Name': 'Slow Finisher', 
        'PastRuns': [
            {'Agari': 36.5}
        ]
    },
    {
        'Umaban': 3, 'Name': 'Average Finisher', 
        'PastRuns': [
            {'Agari': 35.0}
        ]
    },
    {
         'Umaban': 4, 'Name': 'No Data Horse', 
        'PastRuns': []
    }
]

df = pd.DataFrame(data)
df = calculator.calculate_diy2_index(df)

print("DIY2 (Agari) Calculation Results:")
print(df[['Umaban', 'Name', 'DIY2_Index']])

# Speedy: avg 33.75
# Slow: avg 36.5
# Avg: avg 35.0
# Field Mean for valid: (33.75 + 36.5 + 35.0) / 3 = 105.25 / 3 = 35.083
# Field Std: approx 1.12
# Speedy Score should be > 50 (approx 50 + 10 * 1.33 / 1.12 = 61.8)
