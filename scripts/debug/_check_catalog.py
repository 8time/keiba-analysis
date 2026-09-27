# -*- coding: utf-8 -*-
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.folklore_lib import CATALOG

c = Counter(e['verdict'] for e in CATALOG)
print('verdict counts:', dict(c), 'total', len(CATALOG))
for e in CATALOG:
    if e['verdict'] == 'effective':
        print('E:', e['id'])
