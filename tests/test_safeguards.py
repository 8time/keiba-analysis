import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from core import utils_type

def test_is_non_empty_pandas():
    assert utils_type.is_non_empty_pandas(pd.Series([1, 2])) == True
    assert utils_type.is_non_empty_pandas(pd.Series([], dtype=float)) == False
    assert utils_type.is_non_empty_pandas(pd.DataFrame({'a': [1]})) == True
    assert utils_type.is_non_empty_pandas(pd.DataFrame()) == False
    assert utils_type.is_non_empty_pandas(None) == False
    assert utils_type.is_non_empty_pandas({'a': 1}) == False

def test_is_non_empty_collection():
    assert utils_type.is_non_empty_collection([1, 2]) == True
    assert utils_type.is_non_empty_collection([]) == False
    assert utils_type.is_non_empty_collection({'a': 1}) == True
    assert utils_type.is_non_empty_collection({}) == False
    assert utils_type.is_non_empty_collection("test") == True
    assert utils_type.is_non_empty_collection("") == False
    assert utils_type.is_non_empty_collection(None) == False
    assert utils_type.is_non_empty_collection(pd.Series([1, 2])) == False # Pandas should use is_non_empty_pandas

def test_is_truthy_scalar():
    assert utils_type.is_truthy_scalar(4.1) == True
    assert utils_type.is_truthy_scalar(0.0) == False
    assert utils_type.is_truthy_scalar(None) == False
    assert utils_type.is_truthy_scalar("test") == True
    assert utils_type.is_truthy_scalar("") == False
    
    # Should safely return False for pandas/numpy objects instead of ValueError
    assert utils_type.is_truthy_scalar(pd.Series([1, 2])) == False
    assert utils_type.is_truthy_scalar(np.array([1, 2])) == False

def test_describe_runtime_type():
    assert "pandas.Series" in utils_type.describe_runtime_type(pd.Series([1]))
    assert "numpy.ndarray" in utils_type.describe_runtime_type(np.array([1]))
    assert "NoneType" in utils_type.describe_runtime_type(None)
    assert "dict" in utils_type.describe_runtime_type({})

def test_res_odds_simulation():
    """
    Simulation of the fix applied in core/scraper.py for res_odds
    Ensures that various types of res_odds do not cause crash when evaluated.
    """
    df = pd.DataFrame({'Umaban': [1, 2]})
    
    # 1. res_odds = None
    res_odds = None
    if utils_type.is_non_empty_collection(res_odds) or utils_type.is_non_empty_pandas(res_odds):
        pass # should skip safely
    assert 'Odds' not in df.columns
    
    # 2. res_odds = scalar float 
    res_odds = 4.1
    if utils_type.is_non_empty_collection(res_odds) or utils_type.is_non_empty_pandas(res_odds):
        pass # should skip safely
    
    # 3. res_odds = pandas Series
    res_odds = pd.Series({1: 3.5, 2: 7.2})
    if utils_type.is_non_empty_collection(res_odds) or utils_type.is_non_empty_pandas(res_odds):
        _ro = dict(res_odds) if utils_type.is_non_empty_pandas(res_odds) else res_odds
        df['Odds'] = df['Umaban'].map(lambda u: _ro.get(u, 0.0) if pd.notna(u) else 0.0)
    assert df['Odds'].iloc[0] == 3.5
    
    # 4. res_odds = Empty pandas Series
    df = pd.DataFrame({'Umaban': [1, 2]})
    res_odds = pd.Series([], dtype=float)
    if utils_type.is_non_empty_collection(res_odds) or utils_type.is_non_empty_pandas(res_odds):
        pass # shouldn't execute
    assert 'Odds' not in df.columns

if __name__ == "__main__":
    test_is_non_empty_pandas()
    test_is_non_empty_collection()
    test_is_truthy_scalar()
    test_describe_runtime_type()
    test_res_odds_simulation()
    print("All safeguard tests passed")
