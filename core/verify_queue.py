# -*- coding: utf-8 -*-
"""検証候補キュー ―― MAGI回顧の非俗説タグをロジック置き場に【検証候補NNNNN】で永続化。

目的(ユーザー要望): MAGI回顧で複数回出たタグは"自動実装"されない(絶対)。3回以上たまった
非俗説タグを、番号付きの『検証候補』としてロジック置き場(saved_logic_notes.json)に登録し、
人間が時間のある時に見返して→Claudeに渡し→holdout検証してから採否を決める運用の入口。

重要: ここは登録(見える化)だけ。実装/デプロイはしない。採否は必ずholdoutゲートが決める。
"""
import os
import re
import json
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGIC_FILE = os.path.join(_ROOT, 'saved_logic_notes.json')
_KEY_RE = re.compile(r'【検証候補(\d+)】')


def _load(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def next_number(data):
    """既存の【検証候補NNNNN】の最大+1。無ければ1。"""
    nums = [int(m.group(1)) for k in data for m in [_KEY_RE.search(str(k))] if m]
    return (max(nums) + 1) if nums else 1


def registered_tags(data):
    """既に検証候補として登録済みのタグ集合(重複登録防止)。"""
    out = set()
    for k, v in data.items():
        if _KEY_RE.search(str(k)):
            t = (v or {}).get('tag')
            if t:
                out.add(str(t))
    return out


def register(candidates, path=LOGIC_FILE):
    """candidates(hypothesis_export()['exported']の各dict: name/role/band/note)を
    未登録のものだけ【検証候補NNNNN】で登録。戻り値: [(番号, タグ), ...] 新規分。
    ⚠登録=見える化のみ。実装はしない(採否はholdout)。"""
    data = _load(path)
    already = registered_tags(data)
    num = next_number(data)
    added = []
    for c in candidates or []:
        tag = str(c.get('name', '')).strip()
        if not tag or tag in already:
            continue
        key = f'【検証候補{num:05d}】{tag}'
        data[key] = {
            'memo': (
                f'MAGI回顧で3回以上出現した検証候補（自動実装ではない）。\n\n'
                f'タグ: {tag}\n'
                f'役割: {c.get("role", "相手")} / 対象人気帯: {c.get("band", "6+")}\n'
                f'状態: 未検証\n\n'
                f'{c.get("note", "")}\n\n'
                f'検証コマンド案:\n  python scripts/signal_tag_backtest.py "{tag}"\n\n'
                f'※これは俗説隔離を通った非俗説タグ。人間がレビュー→Claudeに渡し→'
                f'jravan.db holdoutで複勝残差z/recall@7を検証してから採否を決める。'
            ),
            'ag_prompt': '',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': '未検証',
            'tag': tag,
            'role': c.get('role', '相手'),
            'band': c.get('band', '6+'),
        }
        added.append((num, tag))
        already.add(tag)
        num += 1
    if added:
        _save(path, data)
    return added


def list_candidates(path=LOGIC_FILE):
    """登録済み検証候補の一覧(番号順)。戻り値: [{'num','tag','status','date'}...]。"""
    data = _load(path)
    out = []
    for k, v in data.items():
        m = _KEY_RE.search(str(k))
        if m:
            out.append({'num': int(m.group(1)), 'tag': (v or {}).get('tag', ''),
                        'status': (v or {}).get('status', '未検証'),
                        'date': (v or {}).get('date', '')})
    return sorted(out, key=lambda x: x['num'])


if __name__ == '__main__':
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    for c in list_candidates():
        print(f"【検証候補{c['num']:05d}】{c['tag']}  [{c['status']}]  {c['date']}")
