# -*- coding: utf-8 -*-
"""前走着差(0.6秒境界・0.8秒スイートスポット)仮説の検証。
資料(The_0.6s_Alpha)の主張:
  (A) 前走0.6秒以上負け = 巻き返し困難 → 切り捨て
  (B) 前走0.8秒差負け = 過小評価で単勝回収155%(スイートスポット)
  (C) 前走0.6秒以上勝ち(2着に大差) = 昇級でも強い・絶対能力の証明
  (D) 前走6着×着差<1.0×ダ1700m+×4番人気以下 = 単勝回収135%
測るもの: 前走着差で層別した【今走】の 勝率/複勝率/単複ROI と、
          人気(オッズ)補正後の残差(=オッズを超える妙味か)。残差≈0/負なら織込み済み。
着差はjravan.dbに無いので time から自前計算(自馬time − 勝ち馬time)。
test=2016-2025・JRA平地(芝/ダ)。win_odds欠損が多くROIは方向性のみ(memory: 欠損37%でROI群間比較は不可)。"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

DB = jj.JV_DB_PATH
exp = jj.calibrate_odds_expectation(db_path=DB)


def e3(o):
    e = exp.get(jj._odds_band(o)); return e['top3'] if e else 0.22


def e1(o):
    e = exp.get(jj._odds_band(o)); return e['win'] if e else 0.08


def to_sec(t):
    if not t or len(t) != 4 or not t.isdigit() or t == '0000':
        return None
    return int(t[0]) * 60 + int(t[1:3]) + int(t[3]) / 10.0


con = sqlite3.connect(DB)
cur = con.cursor()

print('Loading results...', file=sys.stderr)
rows = cur.execute(
    """SELECT r.ketto_num, r.race_key, ra.year, ra.monthday, ra.race_num,
              r.chakujun, r.ninki, r.win_odds, r.time, r.ato3f,
              ra.surface, ra.kyori, ra.grade, ra.shubetsu
       FROM results r JOIN races ra ON ra.race_key=r.race_key
       WHERE r.chakujun>0 AND ra.surface IN ('芝','ダート')
         AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10
         AND CAST(ra.year AS INTEGER) >= 2016
       ORDER BY r.ketto_num, ra.year, ra.monthday, ra.race_num""").fetchall()
con.close()
print(f'  {len(rows):,} rows', file=sys.stderr)

# winner / 2nd time per race_key (for margin calc)
race_times = defaultdict(list)
for kt, rkey, yr, md, rnum, chaku, ninki, odds, time, a3f, surf, kyori, grade, shubetsu in rows:
    s = to_sec(time)
    if s is not None:
        race_times[rkey].append((chaku, s))
win_sec, second_sec = {}, {}
for rkey, lst in race_times.items():
    lst.sort(key=lambda x: x[1])
    win_sec[rkey] = lst[0][1]
    if len(lst) >= 2:
        second_sec[rkey] = lst[1][1]

# build per-horse time-ordered runs
by_horse = defaultdict(list)
for kt, rkey, yr, md, rnum, chaku, ninki, odds, time, a3f, surf, kyori, grade, shubetsu in rows:
    by_horse[kt].append({
        'rkey': rkey, 'chaku': chaku, 'ninki': ninki or 0, 'odds': odds or 0,
        'sec': to_sec(time), 'a3f': a3f or 0, 'surf': surf, 'kyori': kyori or 0,
        'grade': (grade or '').strip(), 'shubetsu': (shubetsu or '').strip(),
    })


class Bucket:
    __slots__ = ('n', 'win', 'top3', 'rw', 'rt', 'ret1', 'bet1')

    def __init__(self):
        self.n = self.win = self.top3 = 0
        self.rw = self.rt = 0.0
        self.ret1 = self.bet1 = 0

    def add(self, chaku, odds):
        self.n += 1
        w = 1 if chaku == 1 else 0
        t = 1 if chaku <= 3 else 0
        self.win += w; self.top3 += t
        if odds and odds > 0:
            self.rw += w - e1(odds)
            self.rt += t - e3(odds)
            self.bet1 += 1
            self.ret1 += (odds * 100 if w else 0)

    def line(self, label):
        if self.n == 0:
            return f'{label:28s} n=0'
        wr = self.win / self.n * 100
        tr = self.top3 / self.n * 100
        rwa = self.rw / self.bet1 if self.bet1 else 0
        rta = self.rt / self.bet1 if self.bet1 else 0
        roi = self.ret1 / (self.bet1 * 100) * 100 if self.bet1 else 0
        return (f'{label:28s} n={self.n:6d}  勝{wr:5.1f}%  複{tr:5.1f}%  '
                f'単残{rwa:+.4f}  複残{rta:+.4f}  単ROI{roi:5.0f}% (n_odds={self.bet1})')


def margin_band(m):
    if m is None:
        return None
    if m <= 0.05:
        return '0.0(勝/同着)'
    if m <= 0.15:
        return '0.1'
    if m <= 0.35:
        return '0.2-0.3'
    if m <= 0.55:
        return '0.4-0.5'
    if m <= 0.95:
        return '0.6-0.9'
    return '1.0+'


def fine_band(m):
    """0.8秒スイートスポット仮説をピンポイント検証する細分割。"""
    if m is None:
        return None
    if m <= 0.55:
        return None
    if m <= 0.65:
        return '0.6'
    if m <= 0.75:
        return '0.7'
    if m <= 0.85:
        return '0.8'
    if m <= 0.95:
        return '0.9'
    if m <= 1.15:
        return '1.0-1.1'
    return None


# ============ (A)(B) 前走着差(負け側)で今走を層別 ============
mb = defaultdict(Bucket)
mb_dirt_long = defaultdict(Bucket)   # ダ1700m+
mb_turf_short = defaultdict(Bucket)  # 芝1600m以下
# (D) 前走6着×着差<1.0×ダ1700+×4番人気以下
combo_d = Bucket()
# (C) 前走「2着に0.6秒+差」で勝利 → 今走
win_big = defaultdict(Bucket)
# (B') 0.8秒スイートスポットのピンポイント検証(全体 + 前走2着限定 = 資料の母集団)
fb = defaultdict(Bucket)
fb_prev2 = defaultdict(Bucket)

for kt, runs in by_horse.items():
    for i in range(1, len(runs)):
        cur_run = runs[i]
        prev = runs[i - 1]
        o = cur_run['odds']
        # 前走着差(勝ち馬との差)
        if prev['sec'] is not None and prev['rkey'] in win_sec:
            m = prev['sec'] - win_sec[prev['rkey']]
            band = margin_band(m)
            if band:
                mb[band].add(cur_run['chaku'], o)
                if cur_run['surf'] == 'ダート' and cur_run['kyori'] >= 1700:
                    mb_dirt_long[band].add(cur_run['chaku'], o)
                if cur_run['surf'] == '芝' and cur_run['kyori'] <= 1600:
                    mb_turf_short[band].add(cur_run['chaku'], o)
            fbn = fine_band(m)
            if fbn:
                fb[fbn].add(cur_run['chaku'], o)
                if prev['chaku'] == 2:   # 資料の母集団=前走2着馬の着差
                    fb_prev2[fbn].add(cur_run['chaku'], o)
            # (D) combo
            if (prev['chaku'] == 6 and m < 1.0
                    and cur_run['surf'] == 'ダート' and cur_run['kyori'] >= 1700
                    and cur_run['ninki'] >= 4):
                combo_d.add(cur_run['chaku'], o)
        # (C) 前走で2着に0.6秒+の差をつけて勝利
        if prev['chaku'] == 1 and prev['rkey'] in second_sec and prev['sec'] is not None:
            wm = second_sec[prev['rkey']] - win_sec[prev['rkey']]
            key = '圧勝(2着に0.6s+)' if wm >= 0.6 else '勝利(0.6s未満)'
            win_big[key].add(cur_run['chaku'], o)

print('\n===== (A)(B) 前走着差(勝ち馬との差) → 今走成績 全体 =====')
print('  (資料主張: 0.6+は切り捨て・0.8前後は回収155%のスイートスポット)')
for b in ['0.0(勝/同着)', '0.1', '0.2-0.3', '0.4-0.5', '0.6-0.9', '1.0+']:
    print('  ' + mb[b].line(b))

print('\n===== ダート1700m+ に限定 (資料: 着差が開きやすく価値が高い) =====')
for b in ['0.0(勝/同着)', '0.1', '0.2-0.3', '0.4-0.5', '0.6-0.9', '1.0+']:
    print('  ' + mb_dirt_long[b].line(b))

print('\n===== 芝1600m以下 に限定 (資料: 1秒差は致命的) =====')
for b in ['0.0(勝/同着)', '0.1', '0.2-0.3', '0.4-0.5', '0.6-0.9', '1.0+']:
    print('  ' + mb_turf_short[b].line(b))

print('\n===== (C) 前走「2着に0.6秒+の差」で勝利 → 今走 =====')
for k in ['圧勝(2着に0.6s+)', '勝利(0.6s未満)']:
    print('  ' + win_big[k].line(k))

print('\n===== (B-ピンポイント) 0.8秒スイートスポット検証 全体 =====')
for b in ['0.6', '0.7', '0.8', '0.9', '1.0-1.1']:
    print('  ' + fb[b].line(b))
print('\n===== (B-ピンポイント) 資料の母集団=前走2着馬に限定 =====')
for b in ['0.6', '0.7', '0.8', '0.9', '1.0-1.1']:
    print('  ' + fb_prev2[b].line(b))

print('\n===== (D) 前走6着×着差<1.0×ダ1700+×今走4番人気以下 (資料: 単勝135%) =====')
print('  ' + combo_d.line('combo_D'))

print('\n注: 残差(残)=実測−オッズ期待。+なら市場を超える妙味/−なら過剰人気(織込み済)。')
print('    単ROIはwin_odds欠損の影響で水準は不正確・群間の方向性のみ参考。')
