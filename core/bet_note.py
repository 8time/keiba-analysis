# -*- coding: utf-8 -*-
"""📝 買い目ノート — 手書きの買い目を読み取って診断する(API不使用・決定的ルール)。

思想: 予想を当てにいくのではなく、検証済み台帳に照らして
      「その買い方は長期的に損をしないか」だけを機械的に指摘する。
      LLMは使わない。全ての指摘に検証根拠を添える。

入力例(自由記述・1行1点):
    1R 馬連 3-7 500
    東京5R 単勝 8 1000円
    9R 3連複 2-4-8 300
    11R ワイド 5-9,12 200      ← 流し(5軸→9,12)
    12R 3連複 1,4,7,9 BOX 100

使い方:
    bets, bad = parse_note(text)
    findings  = diagnose(bets, bankroll=30000, race_ctx={...})
"""
import re
from itertools import combinations

# ── 券種の正規化 ───────────────────────────────────────────
_KIND_ALIASES = {
    'tansho': ['単勝', '単', 'タンショウ', 'tan', 'win'],
    'fukusho': ['複勝', '複', 'フクショウ', 'fuku', 'place'],
    'wakuren': ['枠連'],
    'umaren': ['馬連', '馬れん', 'ウマレン', 'umaren', 'quinella'],
    'umatan': ['馬単', 'ウマタン', 'exacta'],
    'wide': ['ワイド', 'wide', 'ワイド馬券'],
    'sanrenpuku': ['3連複', '三連複', '３連複', 'サンレンプク', 'trio'],
    'sanrentan': ['3連単', '三連単', '３連単', 'サンレンタン', 'trifecta'],
}
KIND_LABEL = {'tansho': '単勝', 'fukusho': '複勝', 'wakuren': '枠連',
              'umaren': '馬連', 'umatan': '馬単', 'wide': 'ワイド',
              'sanrenpuku': '3連複', 'sanrentan': '3連単'}
# 何頭選ぶ券種か(組合せ点数の計算用)
KIND_PICK = {'tansho': 1, 'fukusho': 1, 'wakuren': 2, 'umaren': 2,
             'umatan': 2, 'wide': 2, 'sanrenpuku': 3, 'sanrentan': 3}
# 順序が意味を持つ(順列)券種
KIND_ORDERED = {'umatan', 'sanrentan'}

_KIND_LOOKUP = {}
for _k, _vs in _KIND_ALIASES.items():
    for _v in _vs:
        _KIND_LOOKUP[_v] = _k


def _norm(s):
    """全角英数・記号を半角に寄せる。"""
    out = []
    for ch in str(s or ''):
        o = ord(ch)
        if 0xFF10 <= o <= 0xFF19 or 0xFF21 <= o <= 0xFF3A or 0xFF41 <= o <= 0xFF5A:
            out.append(chr(o - 0xFEE0))
        elif ch in '－ー−―':
            out.append('-')
        elif ch == '＝':
            out.append('=')
        elif ch == '，':
            out.append(',')
        elif ch == '　':
            out.append(' ')
        else:
            out.append(ch)
    return ''.join(out)


def parse_line(line, default_race_no=None, default_race_id=None):
    """1行を1件の買い目に変換。

    戻り値 (bet, error)。ただし『11R』『京都11R』のようにレースだけ書かれた
    見出し行は (('header', race_no, race_id), None) を返す。
    default_race_no/id はその見出しの引き継ぎ値。
    """
    raw = line
    s = _norm(line).strip()
    if not s or s.startswith('#') or s.startswith('//'):
        return None, None                      # 空行/コメントは無視(エラー扱いしない)

    # レース: '5R' / '東京5R' / 12桁race_id
    race_no, race_id = None, None
    m_rid = re.search(r'\b(\d{12})\b', s)
    if m_rid:
        race_id = m_rid.group(1)
        s = s.replace(m_rid.group(0), ' ')
    m_r = re.search(r'(\d{1,2})\s*[rR]\b', s)
    if m_r:
        race_no = int(m_r.group(1))
        s = s[:m_r.start()] + ' ' + s[m_r.end():]
    if race_no is None and race_id:
        try:
            race_no = int(str(race_id)[-2:])
        except ValueError:
            pass

    # 券種
    kind = None
    for alias in sorted(_KIND_LOOKUP, key=len, reverse=True):
        if alias in s:
            kind = _KIND_LOOKUP[alias]
            s = s.replace(alias, ' ', 1)
            break
    if not kind:
        # 『11R』『京都11R』だけの行＝以降の買い目が属するレースの見出し。
        # 人は普通こう書くので、券種が無くてもエラーにせず引き継ぎ情報として扱う。
        if (race_no or race_id) and not re.search(r'\d', s.replace(' ', '')):
            return ('header', race_no, race_id), None
        return None, f'券種が読めません（単勝/馬連/ワイド/3連複…）: {raw.strip()}'

    # 行にレース指定が無ければ直前の見出しを引き継ぐ
    if race_no is None:
        race_no = default_race_no
    if race_id is None:
        race_id = default_race_id

    # 金額: '500円' / '@500' / 末尾の数値。馬番と誤認しないよう円/@/×を優先
    amount = None
    m_amt = re.search(r'(?:@|×|x)?\s*(\d{2,7})\s*円', s)
    if m_amt:
        amount = int(m_amt.group(1))
        s = s[:m_amt.start()] + ' ' + s[m_amt.end():]
    else:
        m_amt = re.search(r'(?:@|×|x)\s*(\d{2,7})\b', s)
        if m_amt:
            amount = int(m_amt.group(1))
            s = s[:m_amt.start()] + ' ' + s[m_amt.end():]

    is_box = bool(re.search(r'\b(box|BOX|ボックス)\b', s, re.I))
    s = re.sub(r'\b(box|BOX|ボックス)\b', ' ', s, flags=re.I)

    # 馬番: '3-7' / '3=7' / '3,7' / 流し '5-9,12'
    # 先頭グループ(軸)と後続グループ(相手)を '-' か '=' で分ける
    body = s.strip(' 　.、。')
    groups = [g for g in re.split(r'[-=>→]', body) if g.strip()]
    parsed = []
    for g in groups:
        nums = [int(x) for x in re.findall(r'\d{1,2}', g)]
        nums = [n for n in nums if 1 <= n <= 18]
        if nums:
            parsed.append(nums)
    if not parsed:
        return None, f'馬番が読めません: {raw.strip()}'

    # 金額が未確定なら、最後のグループの末尾に3桁以上の数値が紛れていないか見る
    if amount is None:
        m_tail = re.search(r'\b(\d{3,7})\s*$', body)
        if m_tail and int(m_tail.group(1)) >= 100:
            amount = int(m_tail.group(1))
            # その数値は馬番リストから除く
            v = int(m_tail.group(1))
            parsed = [[n for n in grp if n != v] or grp for grp in parsed]

    flat = sorted({n for g in parsed for n in g})
    pick = KIND_PICK.get(kind, 1)

    # 点数を決める
    if is_box:
        combos = _box_combos(flat, pick, kind)
    elif len(parsed) >= 2 and pick >= 2:
        combos = _nagashi_combos(parsed, pick, kind)
    else:
        combos = _box_combos(flat, pick, kind) if len(flat) > pick else [tuple(flat)]

    return {'race_no': race_no, 'race_id': race_id, 'kind': kind,
            'kind_label': KIND_LABEL.get(kind, kind), 'groups': parsed,
            'horses': flat, 'is_box': is_box, 'combos': combos,
            'points': len(combos), 'amount': amount,
            'total': (amount or 0) * len(combos), 'raw': raw.strip()}, None


def _box_combos(nums, pick, kind):
    if len(nums) < pick:
        return [tuple(nums)] if nums else []
    if pick == 1:
        return [(n,) for n in nums]
    base = list(combinations(sorted(nums), pick))
    if kind in KIND_ORDERED:
        # 順序ありは順列(BOXなら全順序)
        from itertools import permutations
        return list(permutations(sorted(nums), pick))
    return base


def _nagashi_combos(groups, pick, kind):
    """軸(先頭グループ)→相手(残り)の流し。"""
    axis = groups[0]
    rest = sorted({n for g in groups[1:] for n in g})
    rest = [n for n in rest if n not in axis]
    out = []
    need = pick - len(axis)
    if need <= 0:
        return _box_combos(axis, pick, kind)
    if len(rest) < need:
        return []
    for c in combinations(rest, need):
        combo = tuple(sorted(list(axis) + list(c)))
        out.append(combo)
    if kind in KIND_ORDERED:
        # 1着固定の流しとして扱う(軸→相手の順)
        out = [tuple(list(axis) + list(c)) for c in combinations(rest, need)]
    return out


def parse_note(text):
    """複数行をまとめて解釈。(買い目リスト, 読めなかった行のリスト)。

    『11R』のようなレース見出し行は、それ以降の買い目行に引き継がれる。
    """
    bets, bad = [], []
    cur_no, cur_id = None, None
    for line in str(text or '').splitlines():
        b, err = parse_line(line, cur_no, cur_id)
        if isinstance(b, tuple) and b and b[0] == 'header':
            cur_no, cur_id = b[1], (b[2] or cur_id)
            continue
        if b:
            bets.append(b)
            # 行内でレースを指定していたら、以降の行もそのレース扱いにする。
            # 『9R 馬連 3-7』の次に『ワイド 1-2』と書いたら9R扱いが自然。
            _n = _norm(line)
            if re.search(r'\d{1,2}\s*[rR]\b', _n) or re.search(r'\b\d{12}\b', _n):
                cur_no = b.get('race_no') or cur_no
                cur_id = b.get('race_id') or cur_id
        elif err:
            bad.append(err)
    return bets, bad


# ── 診断 ───────────────────────────────────────────────────

def _f(sev, title, detail, basis=''):
    return {'sev': sev, 'title': title, 'detail': detail, 'basis': basis}


def diagnose(bets, bankroll=None, race_ctx=None, cap_pct=5.0):
    """買い目リストを検証済み台帳に照らして診断する。

    race_ctx: {race_no(int): {...}} 任意。使えるキーは
      'skips'(見送り理由list) / 'arare_prob'(float) / 'danger'(set 馬番) /
      'keshi'(set 馬番) / 'narrow_n'(int) / 'odds'({馬番:単勝オッズ}) / 'label'(str)
    戻り: {'findings':[...], 'summary':{...}}
    """
    race_ctx = race_ctx or {}
    findings = []
    total = sum(b['total'] for b in bets)
    total_points = sum(b['points'] for b in bets)
    by_race = {}
    for b in bets:
        by_race.setdefault(b['race_no'], []).append(b)

    if not bets:
        return {'findings': [], 'summary': {}}

    # ① 金額未記入
    no_amt = [b for b in bets if not b['amount']]
    if no_amt:
        findings.append(_f('info', '金額が読めなかった買い目があります',
                           f"{len(no_amt)}件。『500円』『@500』の形式だと確実に読めます。"
                           "金額なしは資金診断の対象外になります。"))

    # ② 資金に対する張りすぎ
    if bankroll and total > 0:
        pct = total / bankroll * 100
        if pct > 100:
            findings.append(_f('danger', '資金を超えています',
                               f"合計 {total:,}円 / 資金 {bankroll:,}円（{pct:.0f}%）。"))
        elif pct > 20:
            findings.append(_f('danger', '1日の投入が多すぎます',
                               f"合計 {total:,}円＝資金の{pct:.0f}%。"
                               "1日で資金の2割を超えると、連敗時の回復が難しくなります。",
                               'ケリー基準＋破産確率(core/money.py)'))
        for rno, bs in by_race.items():
            rt = sum(b['total'] for b in bs)
            rp = rt / bankroll * 100
            if rp > cap_pct:
                _rl = ((race_ctx.get(rno) or {}).get('label')
                       or (f'{rno}R' if rno else '(レース未指定)'))
                findings.append(_f('warn', f'{_rl}への集中',
                                   f"{rt:,}円＝資金の{rp:.1f}%。"
                                   f"1レースの上限は{cap_pct:.0f}%が鉄則です。",
                                   'bankroll_cap(1〜5%)'))

    # ③ 単勝は市場効率的
    tan = [b for b in bets if b['kind'] == 'tansho']
    if tan:
        amt = sum(b['total'] for b in tan)
        findings.append(_f('warn', '単勝が含まれています',
                           f"{len(tan)}件 / {amt:,}円。単勝は全オッズ帯・全条件で"
                           "プラス回収のポケットが見つかっていません。"
                           "同じ狙いなら複勝・ワイド・馬連の方が分散が小さく残ります。",
                           '単勝ROI検証(全条件で+ROIなし)'))

    # ④ 3連単の難度
    tan3 = [b for b in bets if b['kind'] == 'sanrentan']
    if tan3:
        pts = sum(b['points'] for b in tan3)
        findings.append(_f('info', '3連単があります',
                           f"{len(tan3)}件 / {pts}点。的中率が大きく下がるので、"
                           "同じ資金なら3連複に回した方が期待値のブレは小さくなります。"))

    # ⑤ レース単位の診断
    for rno, bs in sorted(by_race.items(), key=lambda x: (x[0] is None, x[0])):
        ctx = race_ctx.get(rno) or {}
        rt = sum(b['total'] for b in bs)
        pts = sum(b['points'] for b in bs)
        used = sorted({n for b in bs for n in b['horses']})
        lbl = ctx.get('label') or (f'{rno}R' if rno else '(レース不明)')

        if ctx.get('skips'):
            findings.append(_f('danger', f'{lbl}は見送り推奨',
                               '理由: ' + '・'.join(ctx['skips'][:3]) +
                               f"（{rt:,}円を投入予定）",
                               'race_skip_reasons(検証済み)'))

        dang = set(ctx.get('danger') or [])
        hit_d = [n for n in used if n in dang]
        if hit_d:
            findings.append(_f('warn', f'{lbl} 危険人気馬を買っています',
                               f"馬番 {', '.join(map(str, hit_d))}。"
                               "ただし材料が付いても約半分は3着内に来ます（0個54.3%/2個47.7%）。"
                               "切るのではなく**軸から外して相手に回す**のが検証上は正解です。",
                               '危険人気馬10.8万頭の再検証'))

        keshi = set(ctx.get('keshi') or [])
        hit_k = [n for n in used if n in keshi]
        if hit_k:
            findings.append(_f('warn', f'{lbl} 消去対象の馬が入っています',
                               f"馬番 {', '.join(map(str, hit_k))}（弱点重複が多い馬）。",
                               '消去クロス(重複数で複勝率31.5→10.3%)'))

        nn = ctx.get('narrow_n')
        if nn and used:
            if len(used) > nn + 2:
                findings.append(_f('info', f'{lbl} 手を広げすぎかもしれません',
                                   f"{len(used)}頭を使用（推奨{nn}頭）。"
                                   "推奨を大きく超えると点数のわりに的中が伸びません。",
                                   '推奨絞り頭数(holdout検証済)'))
            elif len(used) < nn - 2:
                findings.append(_f('info', f'{lbl} 絞りすぎかもしれません',
                                   f"{len(used)}頭のみ（推奨{nn}頭）。"
                                   "このタイプのレースは取りこぼしが増えます。",
                                   '推奨絞り頭数(holdout検証済)'))

        # トリガミ判定: 最も安い組合せが当たっても元が取れるか
        odds = ctx.get('odds') or {}
        if odds and rt > 0:
            worst = _min_payout_estimate(bs, odds)
            if worst is not None and worst < rt:
                findings.append(_f('warn', f'{lbl} トリガミの可能性',
                                   f"最も人気の組合せが的中しても概算 {worst:,.0f}円 "
                                   f"< 投入 {rt:,}円。点数を減らすか、"
                                   "本命が絡む組合せの金額を厚くしてください。"))

        # 100倍超の構造的不利帯
        ls = [n for n in used if odds.get(n) and odds[n] > 100]
        if ls:
            findings.append(_f('info', f'{lbl} 100倍超の馬が入っています',
                               f"馬番 {', '.join(map(str, ls))}。"
                               "この帯は回収率が44.5%に急落します（141,519頭で検証）。",
                               '構造的不利帯'))

        if pts >= 20:
            findings.append(_f('info', f'{lbl} 点数が多めです',
                               f"{pts}点 / {rt:,}円。点数を増やすほど"
                               "1点あたりの期待値は薄まります。"))

        # 3連系は連敗が深いので、その帯の実測連敗と必要資金を添える
        _ap_r = ctx.get('arare_prob')
        for _k, _kl in (('trio', '3連複'), ('trifecta', '3連単')):
            _mine = [b for b in bs if b['kind'] == ('sanrenpuku' if _k == 'trio'
                                                    else 'sanrentan')]
            if not _mine:
                continue
            try:
                from core import formation_stats as _fsn
                _st = _fsn.get(_ap_r * 100 if _ap_r is not None else None, _k)
            except Exception:
                _st = None
            if not _st:
                continue
            _u = max((b['amount'] or 0) for b in _mine) or 100
            _need = _fsn.required_bankroll(
                _ap_r * 100 if _ap_r is not None else None, _k, unit=_u)
            _msg = (f"この帯（{_fsn.ZONE_SHORT.get(_st['zone'], _st['zone'])}）の{_kl}は"
                    f"実測で**最大{_st['max_streak']}連敗**・回収率{_st['roi']:.0f}%です。")
            if bankroll and _need and _need > bankroll:
                findings.append(_f('warn', f'{lbl} {_kl}は資金に対して重いかもしれません',
                                   _msg + f" 連敗に耐えるには目安{_need:,}円要りますが"
                                   f"資金は{bankroll:,}円です。点数を減らすか"
                                   "3連複に落とすと軽くなります。",
                                   '実配当34,212Rの分布統計'))
            else:
                findings.append(_f('info', f'{lbl} {_kl}の連敗リスク',
                                   _msg + "（当たらない期間が長く続く前提で資金を置いてください）",
                                   '実配当34,212Rの分布統計'))

    if not findings:
        findings.append(_f('ok', '大きな問題は見つかりませんでした',
                           '資金配分・券種・レース選択のいずれも警告条件に触れていません。'))

    return {'findings': findings,
            'summary': {'n_bets': len(bets), 'points': total_points, 'total': total,
                        'races': len([r for r in by_race if r is not None]),
                        'pct': (total / bankroll * 100) if bankroll else None}}


def _min_payout_estimate(bets, odds):
    """そのレースで最も人気（=最も安い）組合せが当たった時の概算払戻。

    単複は単勝オッズをそのまま、連系は各馬の単勝オッズから素朴に近似する
    （馬連≒o1*o2/2.4 等）。あくまで桁感の目安でトリガミ検知にのみ使う。
    """
    best = None
    for b in bets:
        if not b['amount']:
            continue
        for c in b['combos']:
            os_ = [odds.get(n) for n in c]
            if any(o is None or o <= 0 for o in os_):
                continue
            k = b['kind']
            if k in ('tansho',):
                pay = os_[0]
            elif k == 'fukusho':
                pay = max(1.0, os_[0] * 0.28)
            elif k == 'wide':
                pay = max(1.0, (os_[0] * os_[1]) / 6.0)
            elif k in ('umaren', 'wakuren'):
                pay = max(1.0, (os_[0] * os_[1]) / 2.4)
            elif k == 'umatan':
                pay = max(1.0, (os_[0] * os_[1]) / 1.2)
            elif k == 'sanrenpuku':
                pay = max(1.0, (os_[0] * os_[1] * os_[2]) / 7.0)
            else:  # sanrentan
                pay = max(1.0, (os_[0] * os_[1] * os_[2]) / 1.5)
            v = pay * b['amount']
            if best is None or v < best:
                best = v
    return best
