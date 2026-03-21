import pandas as pd
import numpy as np

def is_non_empty_pandas(obj) -> bool:
    """
    obj が None なら False
    pandas Series / DataFrame なら not obj.empty
    それ以外は False
    """
    if obj is None:
        return False
    if isinstance(obj, (pd.Series, pd.DataFrame)):
        return not obj.empty
    return False

def is_non_empty_collection(obj) -> bool:
    """
    obj が None なら False
    list/tuple/set/dict/string なら len(obj) > 0
    それ以外は False
    """
    if obj is None:
        return False
    if isinstance(obj, (list, tuple, set, dict, str)):
        return len(obj) > 0
    return False

def is_truthy_scalar(obj) -> bool:
    """
    scalar 値だけを安全に bool 判定する
    pandas / numpy 配列系は False を返すか例外にする
    """
    if obj is None:
        return False
    if isinstance(obj, (pd.Series, pd.DataFrame, np.ndarray)):
        # raise ValueError(f"Expected scalar, got {type(obj)}")
        return False
    return bool(obj)

def describe_runtime_type(obj) -> str:
    """
    デバッグ用に型名を返す
    pandas Series / DataFrame / ndarray / scalar を区別できるようにする
    """
    if obj is None:
        return "NoneType"
    if isinstance(obj, pd.Series):
        return f"pandas.Series(length={len(obj)})"
    if isinstance(obj, pd.DataFrame):
        return f"pandas.DataFrame(shape={obj.shape})"
    if isinstance(obj, np.ndarray):
        return f"numpy.ndarray(shape={obj.shape})"
    if isinstance(obj, (list, tuple, set, dict, str)):
        return f"{type(obj).__name__}(length={len(obj)})"
    return f"scalar({type(obj).__name__})"
