# -*- coding: utf-8 -*-
"""検証済みエッジの健全性チェック(再検証ループ) — scripts/health_check.py

使い方:
    python scripts/health_check.py            # 全期間 + 直近1年 を並べて健全性表示
    python scripts/health_check.py --years 3  # 直近列の窓を3年に

目的: 採用済みの検証エッジが、新しいレースが増えても『まだ生きているか／符号が
      反転(ドリフト)していないか』を一括確認する。パラメータは一切変えない＝過学習しない
      安全な"健康診断"。週末のデータ取込後に週1〜月1で回すのが想定。

読み方:
  - 全期間z … 記録済みの検証値とほぼ一致するはず(土台の確認)。
  - 直近z  … 直近1年だけの同じ指標。データが少ないので|z|は小さくなりがち＝弱くても異常でない。
  - 状態   … ✅生存(期待方向で全期間|z|≥2) / ⚠️弱(方向は合うが弱い・要観察) /
             ❌反転(期待と逆方向に|z|≥2=ドリフト。要再検証)。
  ※末脚偏差/補正タイム/厩舎当コース等の重い指標は個別スクリプト(spurt_index_backtest.py 等)で確認。
"""
import os
import sys
import argparse
import sqlite3
import math
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core import track_bias as tb
from core import value_scanner as vs

DB = jj.JV_DB_PATH
ap = argparse.ArgumentParser()
ap.add_argument('--years', type=int, default=1, help='直近列の窓(年)')
args = ap.parse_args()

exp = jj.calibrate_odds_expectation(db_path=DB)
def e3(o):
    e = exp.get(jj._odds_band(o)); return e['top3'] if e else 0.22


def zres(rows):
    """rows=[(chaku, win_odds, in_recent)] → 全期間/直近の複勝残差pp・z を返す。"""
    out = {}
    for tag, sel in (('full', lambda r: True), ('recent', lambda r: r[2])):
        sub = [r for r in rows if sel(r)]
        n = len(sub)
        if n == 0:
            out[tag] = (0, 0.0, 0.0); continue
        res = sum((1 if r[0] <= 3 else 0) - e3(r[1]) for r in sub)
        var = sum(e3(r[1]) * (1 - e3(r[1])) for r in sub)
        z = res / math.sqrt(var) if var > 0 else 0
        out[tag] = (n, res / n * 100, z)
    return out


def status(full_z, expect_sign):
    """期待方向expect_sign(+1/-1)に対する状態。"""
    if expect_sign * full_z >= 2:
        return '✅生存'
    if expect_sign * full_z <= -2:
        return '❌反転'
    return '⚠️弱'


con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
sire_of = {str(k): s for k, s in con.execute("SELECT ketto_num, sire FROM horses").fetchall()}
rows = con.execute(
    """SELECT r.chakujun, r.ninki, r.win_odds, r.ketto_num, ra.surface,
              ra.baba_shiba, ra.baba_dirt, ra.year, ra.monthday, ra.juryo,
              ra.shusso_tosu, ra.race_key
       FROM results r JOIN races ra ON ra.race_key=r.race_key
       WHERE r.chakujun>0 AND r.win_odds>0 AND r.ninki>0
         AND ra.surface IN ('芝','ダート') AND ra.shubetsu IN ('11','12','13','14')
         AND ra.year>='2021'""").fetchall()
con.close()

# 直近窓のカットオフ(最新日 - years年)
dates = [int(r[7] + r[8]) for r in rows if r[7] and r[8]]
maxd = max(dates) if dates else 20260101
cutoff = maxd - args.years * 10000


def is_recent(y, md):
    try:
        return int(y + md) >= cutoff
    except Exception:
        return False


def fade(s): return s and any(k in s for k in tb._FADE_WET_SIRES)
def wetp(s): return s and any(k in s for k in tb._WETPOWER_SIRES)

# ── 馬レベル(複勝残差・オッズ統制) ──
E = defaultdict(list)
for (chaku, ninki, wo, ket, surf, bsh, bdt, y, md, juryo, tosu, rk) in rows:
    rec = is_recent(y, md)
    bcode = str((bsh if surf == '芝' else bdt) or '')
    wet = bcode in ('3', '4')
    sire = sire_of.get(str(ket))
    item = (chaku, wo, rec)
    if surf == '芝' and wet and ninki == 1:
        E['芝重不良×1番人気(危険)'].append(item)
    if surf == 'ダート' and bcode == '4' and ninki == 1:
        E['ダ不良×1番人気(危険)'].append(item)
    if wet and 1 <= ninki <= 3 and fade(sire):
        E['道悪×1-3人気×FADE血統'].append(item)
    if surf == 'ダート' and wet and 1 <= ninki <= 3 and wetp(sire):
        E['ダ道悪×1-3人気×WETPOWER血統'].append(item)

# 期待方向: 危険=負(-1) / FADE=負(-1) / WETPOWER=正(+1)
EXPECT = {'芝重不良×1番人気(危険)': -1, 'ダ不良×1番人気(危険)': -1,
          '道悪×1-3人気×FADE血統': -1, 'ダ道悪×1-3人気×WETPOWER血統': +1}

print("=" * 90)
print(f"検証済みエッジ 健康診断  (全期間=2021〜 / 直近={args.years}年・カットオフ{cutoff})")
print("=" * 90)
print("【馬レベル: 複勝残差pp(オッズ統制)】 期待方向に全期間|z|≥2なら✅")
print(f"{'エッジ':<30}{'全n':>7}{'全残差':>8}{'全z':>7}{'直近n':>7}{'直近z':>7}  状態")
print("-" * 90)
for name, sgn in EXPECT.items():
    o = zres(E[name])
    st = status(o['full'][2], sgn)
    print(f"{name:<30}{o['full'][0]:>7}{o['full'][1]:>+8.2f}{o['full'][2]:>+7.2f}"
          f"{o['recent'][0]:>7}{o['recent'][2]:>+7.2f}  {st}")

# ── レースレベル(本線/②型・1番人気オッズ帯統制) ──
_EDGES = [1.5, 2, 2.5, 3, 4, 5, 7, 10, 1e9]
def oband(o):
    o = o or 1e9
    for i, e in enumerate(_EDGES):
        if o <= e: return i
    return len(_EDGES) - 1

races = {}
for (chaku, ninki, wo, ket, surf, bsh, bdt, y, md, juryo, tosu, rk) in rows:
    d = races.setdefault(rk, {'tosu': tosu, 'juryo': juryo or '', 'surf': surf,
                              'baba': str((bsh if surf == '芝' else bdt) or ''),
                              'recent': is_recent(y, md), 'horses': []})
    d['horses'].append({'chaku': chaku, 'ninki': ninki, 'wo': wo})

R = []
for rk, d in races.items():
    odds = [h['wo'] for h in d['horses'] if h['wo'] > 0]
    if len(odds) < 3 or d['tosu'] < 8:
        continue
    top3 = [h for h in d['horses'] if h['chaku'] <= 3]
    hon = 1 if (any(h['ninki'] == 1 and h['chaku'] <= 3 for h in d['horses'])
                and any(h['ninki'] == 2 and h['chaku'] <= 3 for h in d['horses'])) else 0
    ana = 1 if sum(1 for h in top3 if h['ninki'] >= 5) >= 2 else 0
    R.append({'band': oband(min(odds)), 'hon': hon, 'ana': ana, 'tosu': d['tosu'],
              'handi': d['juryo'] == '1', 'recent': d['recent']})

bt = defaultdict(int); bh = defaultdict(int); ba = defaultdict(int)
for r in R:
    bt[r['band']] += 1; bh[r['band']] += r['hon']; ba[r['band']] += r['ana']
eh = {b: bh[b]/bt[b] for b in bt}; ea = {b: ba[b]/bt[b] for b in bt}

def zrace(sub, key, expb):
    n = len(sub)
    if n == 0: return (0, 0.0)
    act = sum(r[key] for r in sub); e = sum(expb[r['band']] for r in sub)
    var = sum(expb[r['band']] * (1 - expb[r['band']]) for r in sub)
    z = (act - e) / math.sqrt(var) if var > 0 else 0
    return (n, z)

print("\n【レースレベル: 決着タイプ(1番人気オッズ帯統制)】")
print(f"{'条件':<26}{'n':>7}{'②型z':>8}{'本線z':>8}  状態(期待)")
print("-" * 90)
race_checks = [
    ('ハンデ戦→②型↑', lambda r: r['handi'], 'ana', +1),
    ('フルゲート16+→②型↑', lambda r: r['tosu'] >= 16, 'ana', +1),
    ('少頭数8-10→本線↑', lambda r: 8 <= r['tosu'] <= 10, 'hon', +1),
]
for name, fn, key, sgn in race_checks:
    sub = [r for r in R if fn(r)]
    na, za = zrace(sub, 'ana', ea)
    nh, zh = zrace(sub, 'hon', eh)
    chk = za if key == 'ana' else zh
    st = '✅生存' if sgn * chk >= 2 else ('❌反転' if sgn * chk <= -2 else '⚠️弱')
    print(f"{name:<26}{na:>7}{za:>+8.2f}{zh:>+8.2f}  {st}")

# trio_lean 分離(本線向き vs ②穴妙味向きの実決着率)
lean_b = defaultdict(lambda: {'n': 0, 'hon': 0, 'ana': 0})
for rk, d in races.items():
    odds = [h['wo'] for h in d['horses'] if h['wo'] > 0]
    if len(odds) < 3 or d['tosu'] < 8:
        continue
    hon = 1 if (any(h['ninki'] == 1 and h['chaku'] <= 3 for h in d['horses'])
                and any(h['ninki'] == 2 and h['chaku'] <= 3 for h in d['horses'])) else 0
    ana = 1 if sum(1 for h in d['horses'] if h['chaku'] <= 3 and h['ninki'] >= 5) >= 2 else 0
    _BABA = {'3': '重', '4': '不良'}
    lean = vs.trio_lean(meta={'is_handicap': d['juryo'] == '1'}, n_horses=d['tosu'],
                        fav_odds=min(odds), baba=_BABA.get(d['baba']), odds_list=odds)['lean']
    b = lean_b[lean]; b['n'] += 1; b['hon'] += hon; b['ana'] += ana

print("\n【trio_lean 決着タイプ分離(本線向きで本線↑・②穴妙味向きで②型↑なら✅)】")
print(f"{'lean判定':<16}{'n':>7}{'本線%':>8}{'②型%':>8}")
for lean in ('本線向き', '中立', '②穴妙味向き'):
    b = lean_b[lean]
    if b['n']:
        print(f"{lean:<16}{b['n']:>7}{b['hon']/b['n']*100:>8.1f}{b['ana']/b['n']*100:>8.1f}")
sep_ok = (lean_b['本線向き']['n'] and lean_b['②穴妙味向き']['n']
          and lean_b['本線向き']['hon']/max(lean_b['本線向き']['n'],1)
              > lean_b['②穴妙味向き']['hon']/max(lean_b['②穴妙味向き']['n'],1)
          and lean_b['②穴妙味向き']['ana']/max(lean_b['②穴妙味向き']['n'],1)
              > lean_b['本線向き']['ana']/max(lean_b['本線向き']['n'],1))
print(f"  分離: {'✅生存' if sep_ok else '⚠️要確認'}")

print("\n" + "=" * 90)
print("❌反転が出たら要再検証(該当の*_backtest.pyを回す)。⚠️弱は通常は様子見でOK。")
print("重い個別指標(末脚=spurt_index_backtest / 補正T=corrected_time_backtest / "
      "厩舎=trainer / 騎手=jockey) は別途。")
