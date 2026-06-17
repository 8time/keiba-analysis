# -*- coding: utf-8 -*-
"""
消去クロス — 『来にくさ』フラグの重複数を可視化する消去支援エンジン。
─────────────────────────────────────────────────────────
ユーザー観測(調教C以下は3着内に来にくい)を起点に、jravan.dbで各「下位フラグ」を
検証(scripts/elim_cross_backtest.py / test 2021-25, n=330,818)。

【重要な検証結果 — 正直な前提】
  ・各フラグ単体の複勝率は人気にほぼ織込み済(人気補正残差 -0.1〜-1.5pp)。
    つまり『妙味(市場の歪み)発見』ではなく、人気と相関する『来にくさ』の素直な指標。
  ・ただしフラグ重複数 → 絶対複勝率は強い単調低下:
       0個31.5% / 1個27.1% / 2個19.1% / 3個14.9% / 4個13.7% / 5個13.6% /
       6個13.1% / 7個10.3%。
  ・人気1-5番でも 6個以上重なると残差 -1.8〜-5.5pp(小n)＝過剰人気の兆候。
  → 用途: 3連複フォーメーションの『相手から外す』点数削減 と 軸の不安可視化。
     人気とほぼ相関するため、これ単独で穴の妙味は出ない(妙味は別エンジン)。

※調教評価(C以下)は jravan.db に過去データが無く検証不可。ユーザー実観測が強いため
  『検証不可だが採用』フラグとして任意で1つ加算できる(train)。
"""

# フラグ定義: key -> (表示ラベル, 説明)。検証はすべて単体では priced-in。
FLAG_DEFS = [
    ('form3',   '近3走着外',   '直近3走すべて4着以下(3着内なし)'),
    ('nofuku5', '5走複勝0',    '直近5走(3走以上)で一度も3着内なし'),
    ('slow3f',  '末脚下位',    '末脚指数が低い(上がり3Fが相対的に遅い)'),
    ('back',    '後方脚質',    '直近3走平均の4角位置が後方(出走頭数比≥0.78)'),
    ('layoff',  '半年休み',    '前走から180日以上の長期休養明け'),
    ('distbig', '距離大変更',  '前走から距離が±400m以上変わる'),
    ('zogen',   '体重±16k',    '当日馬体重の増減が±16kg以上'),
    ('age8',    '8歳上',       '8歳以上の高齢'),
    ('pcidev',  'PCI乖離',     '事前平均PCIがフィールド平均から±6以上乖離(検証済・人気内包の弱フラグ)'),
    ('train',   '調教C以下',   '調教評価がC以下(検証不可・実観測フラグ)'),
    ('battle',  '総合力下位',  '🏠Single Race Analysisの総合戦闘力が下位30%(検証不可・人気内包)'),
    ('proj',    '予測下位',    '🏠Single Race Analysisの予測スコアが下位30%(検証不可・人気内包)'),
]
FLAG_DEFS_ORDER = [k for k, _, _ in FLAG_DEFS]
FLAG_LABEL = {k: lbl for k, lbl, _ in FLAG_DEFS}
FLAG_HELP = {k: hlp for k, _, hlp in FLAG_DEFS}
# 検証DBに無い=歴史的バックテスト不可のフラグ。これらは推定複勝率(BAND)の算定から除外する。
#  ・train: 調教評価(過去データがDBに無い)
#  ・battle/proj: ライブ生成スコアで再構築不可、かつ人気/オッズを内包し他フラグと相関
UNVERIFIED = {'train', 'battle', 'proj'}
# BAND(推定複勝率)の根拠となる検証済みフラグのみ
VERIFIED_ORDER = [k for k in FLAG_DEFS_ORDER if k not in UNVERIFIED]


def verified_count(flag_set):
    """検証済みフラグの点灯数(BANDの入力)。実観測/score系は数えない。"""
    return len([k for k in flag_set if k not in UNVERIFIED])

SLOW3F_TH = 0.30        # spurt_index(0-1, 高=好末脚)がこれ以下=末脚下位
SLOW3F_MIN_RUNS = 2
BACK_RATIO_TH = 0.78    # 4角位置比率(0先頭〜1最後方)
LAYOFF_DAYS = 180
DIST_BIG = 400          # m
ZOGEN_BIG = 16          # kg
AGE_OLD = 8
PCI_DEV_BIG = 6.0       # 事前平均PCI − フィールド平均PCI の絶対乖離(検証: 6pp以上で複勝率22.4→20.0%)

# 重複数 → 推定複勝率(%)。scripts/elim_cross_backtest.py の絶対複勝率(全フラグ)。
BAND = {0: 31.5, 1: 27.1, 2: 19.1, 3: 14.9, 4: 13.7, 5: 13.6, 6: 13.1, 7: 10.3}


def band_fukusho(count):
    """フラグ重複数 → 推定複勝率(%)。範囲外は端でクランプ。"""
    if count <= 0:
        return BAND[0]
    if count >= max(BAND):
        return BAND[max(BAND)]
    return BAND.get(count, BAND[min(BAND, key=lambda k: abs(k - count))])


def _daygap(prev_date, race_date):
    """'YYYYMMDD' 文字列同士の日数差(概算)。失敗時 None。"""
    from datetime import datetime
    try:
        a = datetime.strptime(str(prev_date)[:8], '%Y%m%d')
        b = datetime.strptime(str(race_date)[:8], '%Y%m%d')
        return (b - a).days
    except Exception:
        return None


def compute_flags(*, last5_top3=None, spurt_index=None, spurt_runs=0,
                  avg_c4ratio=None, prev_date=None, race_date=None,
                  prev_dist=None, cur_dist=None, zogen=None, age=None,
                  training_grade=None, include_train=True,
                  battle_low=False, proj_low=False, pci_dev=None):
    """1頭の点灯フラグ集合(set of key)を返す。すべて pre-race 情報のみ。
    引数は app 側で ctx/horse_elim_stats/出馬表から渡す。"""
    f = set()
    l5 = list(last5_top3 or [])
    if len(l5) >= 3 and sum(l5[:3]) == 0:
        f.add('form3')
    if len(l5) >= 3 and sum(l5) == 0:
        f.add('nofuku5')
    if spurt_index is not None and spurt_runs >= SLOW3F_MIN_RUNS and spurt_index <= SLOW3F_TH:
        f.add('slow3f')
    if avg_c4ratio is not None and avg_c4ratio >= BACK_RATIO_TH:
        f.add('back')
    gap = _daygap(prev_date, race_date) if (prev_date and race_date) else None
    if gap is not None and gap >= LAYOFF_DAYS:
        f.add('layoff')
    if prev_dist and cur_dist and abs(int(cur_dist) - int(prev_dist)) >= DIST_BIG:
        f.add('distbig')
    try:
        if zogen is not None and abs(int(zogen)) >= ZOGEN_BIG:
            f.add('zogen')
    except (TypeError, ValueError):
        pass
    try:
        if age is not None and int(age) >= AGE_OLD:
            f.add('age8')
    except (TypeError, ValueError):
        pass
    # PCI乖離(検証済の弱フラグ): 事前平均PCIがフィールド平均から±PCI_DEV_BIG以上
    try:
        if pci_dev is not None and abs(float(pci_dev)) >= PCI_DEV_BIG:
            f.add('pcidev')
    except (TypeError, ValueError):
        pass
    if include_train and training_grade:
        g = str(training_grade).strip().upper()[:1]
        if g in ('C', 'D', 'E', 'F'):
            f.add('train')
    # 🏠 Single Race Analysis の総合戦闘力/予測スコア下位(検証不可・任意加味)
    if battle_low:
        f.add('battle')
    if proj_low:
        f.add('proj')
    return f
