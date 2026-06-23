# -*- coding: utf-8 -*-
"""#5 危険人気馬 severity校正バックテスト。
core/danger_gate.danger_veto の severity(危険理由数)が、人気上位(1-3番)の複勝残差を
どれだけ単調に押し下げるかを検証し、「完全消し(相手からも外す)まで踏み込むか」を判断する。

severity は cheap-field(オッズ統制で事前確定)のみで算定:
  重不良×1番 / 道悪×瞬発系FADE / 牝×冬春fade  (emp_bias/topswap等の文脈依存因子は本BT対象外)
測定: 1番人気オッズ帯ではなく各馬のwin_oddsバンド期待(複勝)に対する残差＋z(baba_blood等と同様)。
2021-25 平地(芝/ダ)・人気1-3番。reason別の分解も出す。"""
import os
import sys
import math
import sqlite3
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core import danger_gate as dg
from core import value_scanner as vs

DB = jj.JV_DB_PATH
exp = jj.calibrate_odds_expectation(db_path=DB)
def e3(o):
    e = exp.get(jj._odds_band(o)); return e['top3'] if e else 0.22

_SEX = {'1': '牡', '2': '牝', '3': 'セ'}


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
    sire_of = {str(k): s for k, s in con.execute("SELECT ketto_num, sire FROM horses").fetchall()}
    rows = con.execute(
        """SELECT r.chakujun, r.ninki, r.win_odds, r.ketto_num, r.sex, r.age,
                  ra.surface, ra.baba_shiba, ra.baba_dirt, ra.monthday
           FROM results r JOIN races ra ON ra.race_key=r.race_key
           WHERE r.chakujun>0 AND r.win_odds>0 AND r.ninki BETWEEN 1 AND 3
             AND ra.surface IN ('芝','ダート') AND ra.year>='2021'
             AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10""").fetchall()
    con.close()

    by_sev = defaultdict(lambda: {'n': 0, 't3': 0, 'res': 0.0, 'var': 0.0})
    by_reason = defaultdict(lambda: {'n': 0, 't3': 0, 'res': 0.0, 'var': 0.0})

    def add(d, chaku, o):
        d['n'] += 1
        d['t3'] += 1 if chaku <= 3 else 0
        d['res'] += (1 if chaku <= 3 else 0) - e3(o)
        d['var'] += e3(o) * (1 - e3(o))

    for (chaku, ninki, wo, ket, sex, age, surf, bsh, bdt, md) in rows:
        baba = vs.baba_code_to_label(bsh if surf == '芝' else bdt)
        sire = sire_of.get(str(ket))
        sex_age = _SEX.get(str(sex), '') + str(age or '')
        month = int(str(md)[:2]) if md and str(md)[:2].isdigit() else None
        vr = dg.danger_veto(ninki=ninki, surface=surf, baba=baba, sire=sire,
                            sex_age=sex_age, month=month)
        sev = vr['severity']
        key = '3+' if sev >= 3 else str(sev)
        add(by_sev[key], chaku, wo)
        for rs in vr['reasons']:
            add(by_reason[rs], chaku, wo)

    def line(name, d):
        n = max(d['n'], 1)
        z = (d['res']) / math.sqrt(d['var']) if d['var'] > 0 else 0
        print(f"  {name:<20} n={d['n']:6d}  複勝率{d['t3']/n:6.2%}  複勝残差{d['res']/n:+.4f}(z={z:+.2f})")

    print("=== #5 danger severity 校正 (人気1-3番・2021-25・複勝残差) ===")
    print("severity=危険理由数(cheap-field)。残差が単調に負へ下がるかを見る。\n")
    print("【severity別】")
    for k in ('0', '1', '2', '3+'):
        if by_sev[k]['n']:
            line(f"severity={k}", by_sev[k])
    print("\n【危険理由カテゴリ別(単独寄与)】")
    for rs, d in sorted(by_reason.items(), key=lambda kv: -kv[1]['n']):
        if d['n'] >= 30:
            line(rs, d)
    print("\n→ severity≥2 で残差が明確に負(z<-2)なら『軸不可』は妥当。"
          "≥3で更に深い負なら相手からも外す(完全消し)余地。理由別で効く因子を確認。")


if __name__ == '__main__':
    main()
