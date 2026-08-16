# -*- coding: utf-8 -*-
"""「この1番人気は買えるか」を1画面で答える判定器。

検証を積み重ねた結果、このアプリで実際に効くのは
**中心の並び順**ではなく**本命の信頼度を測ること**だった。
その部品は既に揃っているが 43列のテーブルや各所のバッジに散らばっていて
一目で答えが出ない。ここでは既存の検証済み部品だけを組み合わせて集約する。
**新しい主張は一切足していない**（各項目に出典と実測値を持たせている）。

使う部品（すべて検証済み・実装済み）:
  danger_gate.danger_veto      危険材料。10.8万頭で再監査し効果ゼロの2項目は削除済
  value_scanner.glass_favorite_fade  ガラス人気馬。複勝率残差 z-8.5（3窓一貫）
  axis_selector.axis_confidence  前走1着-2pp / 位置比率<0.28の先行-1.6〜1.9pp を織込んだ信頼度
  axis_selector.fuku_rate        オッズから引く素の複勝率
  axis_selector.race_axis_confidence  補正T×人気の重複（1番人気複勝率 55%→74%）
  jockey_jv.is_golden_line       騎手×厩舎連対率35-40%（+2.44/+2.48pp・77.5万騎乗）

⚠「来ない予言」ではない。[[verified_danger_fav_audit]]の実測では
  危険材料0個で複勝率54.3% / 1個51.4% / **2個でも47.7%**。
  材料が付いても**半分は来る**。あくまで「オッズに見合うか」の印。
"""

# 危険材料の数 → 実測の複勝率（10.8万頭・オッズ統制後）
DANGER_FUKU = {0: 54.3, 1: 51.4, 2: 47.7}


def _safe(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception:
        return None


def check(fav, horses=None, race=None):
    """1頭（通常は1番人気）を判定する。

    fav: {'umaban','name','ninki','win_odds','place_mid','surface','baba',
          'sire','sex_age','umaban','tosu','layoff_days','prev_chaku',
          'prev_kyaku','pos_ratio','prev_win_margin','stress_flags',
          'jockey','trainer','month','emp_bias','top_jockey_swap',
          'fillies_race'}
    horses: レース全体 [{'umaban','ninki','ct_fig'},...]（補正T重複の判定に使う）
    race:   {'is_nar':bool}

    戻り値:
      {'verdict':'buy'|'caution'|'avoid', 'emoji':str, 'headline':str,
       'fuku':float|None, 'items':[{'ok':bool,'label':str,'detail':str}],
       'note':str}
    """
    from core import danger_gate, axis_selector
    from core import value_scanner as vs

    is_nar = bool((race or {}).get('is_nar'))
    ninki = fav.get('ninki')
    odds = fav.get('win_odds')
    items = []

    # ── ① 危険材料（danger_gate） ──────────────────
    dv = _safe(danger_gate.danger_veto,
               ninki=ninki, surface=fav.get('surface', ''),
               baba=fav.get('baba', ''), sire=fav.get('sire', ''),
               sex_age=fav.get('sex_age', ''), month=fav.get('month'),
               emp_bias=fav.get('emp_bias'), umaban=fav.get('umaban'),
               tosu=fav.get('tosu'),
               top_jockey_swap=bool(fav.get('top_jockey_swap')),
               layoff_days=fav.get('layoff_days'),
               prev_kyaku=fav.get('prev_kyaku'),
               prev_chaku=fav.get('prev_chaku'),
               stress_flags=fav.get('stress_flags'),
               win_odds=odds, place_mid=fav.get('place_mid'),
               fillies_race=bool(fav.get('fillies_race')),
               tozai=fav.get('tozai'), jyo=fav.get('jyo')) or {}
    # ⚠ガラス人気馬は②で個別に出すので、ここでは数えない（二重カウント防止）
    _reasons = [r for r in (dv.get('reasons') or []) if 'ガラス' not in str(r)]
    n_danger = len(_reasons)
    exp_fuku = DANGER_FUKU.get(min(n_danger, 2), 47.7)
    if n_danger == 0:
        items.append({'ok': True, 'label': '危険材料なし',
                      'detail': f'検証済みの危険材料に1つも当たりません'
                                f'（この状態の複勝率は実測{DANGER_FUKU[0]}%）'})
    else:
        items.append({'ok': False, 'w': 2 if n_danger >= 2 else 1,
                      'label': f'危険材料 {n_danger}個',
                      'detail': '／'.join(_reasons)
                                + f'（材料{min(n_danger,2)}個の複勝率は実測{exp_fuku}%。'
                                  f'材料なしの{DANGER_FUKU[0]}%より低いだけで、'
                                  f'半分近くは3着以内に来ます）'})

    # ── ② ガラス人気馬（複勝が売れていない上位人気） ──────
    gl, ratio = (_safe(vs.glass_favorite_fade, odds, fav.get('place_mid'), ninki)
                 or (False, None))
    if fav.get('place_mid') in (None, '') or not odds:
        items.append({'ok': True, 'label': 'ガラス判定：複勝オッズ未取得',
                      'detail': '複勝オッズが取れていないため判定していません'
                                '（地方競馬は複勝オッズの供給がありません）'})
    elif gl:
        items.append({'ok': False, 'w': 2,   # 残差z-8.5＝最強クラス
                      'label': 'ガラスの人気馬',
                      'detail': f'単勝は売れているのに複勝が売れていません'
                                f'（帯の中央値の{ratio}倍）。'
                                f'複勝率が実測で下がる形です（残差z-8.5・3窓一貫）'})
    else:
        items.append({'ok': True, 'label': 'ガラスではない',
                      'detail': '単勝と複勝の売れ方が釣り合っています'})

    # ── ③ 前走1着 / 本物の先行（軸としての過剰人気） ──────
    pc = fav.get('prev_chaku')
    pr = fav.get('pos_ratio')
    bad_axis = []
    if pc == 1:
        bad_axis.append('前走1着（勝ち上がり直後）')
    if pr is not None and pr < 0.28:
        bad_axis.append('本物の先行（位置比率0.28未満）')
    if bad_axis:
        items.append({'ok': False, 'w': 2 if len(bad_axis) >= 2 else 1,
                      'label': '軸としては過剰人気',
                      'detail': '／'.join(bad_axis)
                                + '。生の複勝率は高いのですが、'
                                  'オッズがそれ以上に高くなります'
                                  '（前走1着-2pp／先行-1.6〜1.9pp・両窓で有意）。'
                                  '両方持つ馬が最悪（-4.6pp）です'})
    else:
        items.append({'ok': True, 'label': '軸に向く形',
                      'detail': '前走1着でも本物の先行でもありません'
                                '（この組み合わせが最良の軸：+0.8〜1.0pp）'})

    # ── ③-2 アプリの実力Rankが人気より大きく低い ──────────
    # [[verified_rank_fav_disagree]]: 人気1-3をRank下位に落とした馬は
    # オッズ統制の複勝率残差が **Rank7-9位で-1.86pp(z-4.16) /
    # Rank10位以下で-4.21pp(z-7.45)** と完全に単調。
    # LTRの学習は2023年までで、**学習期間外(2024-26)が-6.25pp(z-5.29)と最も強い**
    # ＝リークではない。買い側(人気薄の昇格)は+0.27pp/z1.19で無力という非対称。
    _rk = fav.get('app_rank')
    try:
        _rk = int(_rk) if _rk is not None else None
    except (TypeError, ValueError):
        _rk = None
    if _rk is not None and ninki and int(ninki) <= 3:
        if _rk >= 10:
            items.append({'ok': False, 'w': 2,   # -4.21pp / z-7.45
                          'label': f'実力Rankが{_rk}位まで落ちている',
                          'detail': f'人気{ninki}番なのにアプリの実力順では{_rk}位です。'
                                    'この形はオッズが示す以上に走りません'
                                    '（複勝率残差 -4.21pp・z-7.45）。'
                                    '1番人気なら実測の複勝率が63.5%→52.7%に落ちます。'
                                    '学習期間外でも同じ向きなので偶然ではありません'})
        elif _rk >= 7:
            items.append({'ok': False, 'w': 1,   # -1.86pp / z-4.16
                          'label': f'実力Rankが{_rk}位とやや低い',
                          'detail': f'人気{ninki}番に対してアプリの実力順は{_rk}位。'
                                    '軽い割引が要ります（残差-1.86pp・z-4.16）'})
        else:
            items.append({'ok': True, 'label': f'実力Rankも{_rk}位で一致',
                          'detail': '市場の評価とアプリの実力評価が揃っています'
                                    '（この形は残差+1.83pp・z+8.63）'})

    # ── ④ 黄金ライン（騎手×厩舎） ─────────────────
    gold = None
    if fav.get('jockey') and fav.get('trainer'):
        try:
            from core import jockey_jv
            gold = jockey_jv.is_golden_line(fav['jockey'], fav['trainer'])
        except Exception:
            gold = None
    if gold is True:
        items.append({'ok': True, 'label': '黄金ライン該当',
                      'detail': 'この騎手×厩舎の連対率は35%以上です'
                                '（両窓で+2.44/+2.48pp・77.5万騎乗で検証）'})
    elif gold is False:
        items.append({'ok': True, 'label': '黄金ラインではない',
                      'detail': '該当しないだけで、減点材料ではありません'})

    # ── ⑤ レース全体：補正T×人気の重複 ─────────────
    # ⚠これは**レースの性質**であって馬の落ち度ではない。
    #   総合判定(ng)には数えず、文脈として別枠(race_ctx)で返す。
    rc = _safe(axis_selector.race_axis_confidence, horses) if horses else None
    race_ctx = None
    if rc:
        race_ctx = {
            'label': rc['label'], 'overlap': rc['overlap'],
            'fav_top3': rc['fav_top3'],
            'detail': (f'補正タイム上位3頭と人気上位3頭が{rc["overlap"]}頭重なります。'
                       f'この状態の1番人気の複勝率は実測{rc["fav_top3"]}%です'
                       '（重複0で55%／3で74%まで動きます）')}

    # ── 推定複勝率 ────────────────────────────
    fuku = _safe(axis_selector.fuku_rate, ninki, odds, is_nar)

    # ── 総合判定 ─────────────────────────────
    # 効果量で重み付けする。強い材料(w=2)は単独でも警戒レベルを上げる。
    #   w=2: ガラス(z-8.5) / Rank10位以下(-4.21pp) / 危険材料2個(-6.6pp) /
    #        前走1着と先行の両方(-4.6pp)
    #   w=1: 危険材料1個(-2.9pp) / Rank7-9位(-1.86pp) / 前走1着のみ(-2pp)
    ng = sum(int(x.get('w', 1)) for x in items if not x['ok'])
    if ng == 0:
        verdict, emoji, head = 'buy', '🟢', '軸にできます'
    elif ng <= 2:
        verdict, emoji, head = 'caution', '🟡', '軸にはできますが割引が要ります'
    else:
        verdict, emoji, head = 'avoid', '🔴', '軸から外すことを勧めます'

    note = ('この判定は「来る／来ない」ではなく「**オッズに見合うか**」を見ています。'
            f'危険材料が2個ついた馬でも実測の複勝率は{DANGER_FUKU[2]}%で、'
            '半分近くは3着以内に来ます。'
            '「危ないから消す」ではなく「その人気で買うほどではない」と読んでください。')
    return {'verdict': verdict, 'emoji': emoji, 'headline': head,
            'fuku': fuku, 'items': items, 'note': note,
            'race_ctx': race_ctx,
            'n_danger': n_danger, 'danger_fuku': exp_fuku}
