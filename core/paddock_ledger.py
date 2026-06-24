# -*- coding: utf-8 -*-
"""
パドック観察タグ台帳 — 自分のパドック観察(タグ)×結果のROIを蓄積して、
「どの観察が回収率に効くか」を自分のデータで実証するための個人検証装置。

【設計思想・正直な前提】
  パドックの主観cue(歩様/発汗/気配 等)は歴史的な正解ラベルが存在せず、
  既存のバックテストでは検証できない(verified_paddock_weight)。だから予測ロジックには
  できない。代わりに本台帳で「自分が付けたタグ × そのレース結果」を貯め、タグ別の
  複勝率・ROIを実測する。検証で効くと分かったタグだけを以後信頼する(elim_reasonsと同思想)。

  タグの極性(fade/buy)は表示用の仮説に過ぎず、効くかどうかは台帳の実測で判定する。
  「白い泡=危険」等は俗説。本台帳はそれを鵜呑みにせず数字で確かめるためにある。

  定量(馬体重/増減)は既に検証済(fade側のみ・買い妙味ゼロ=verified_paddock_weight)なので
  ここでは扱わない。本台帳は『主観cueを個人検証する』ことに専念する。

【使い方(想定)】
  1) レース前: パドックを見て、気づいた観察をタグで記録(+自由メモ)。source='manual'。
     将来 phase B で Ollama/Gemma の自動抽出タグ(source='gemma')も同じ台帳に入れて
     人の眼 vs Gemma のどちらが効くか比較する。
  2) レース後: 着順(と分かれば単勝オッズ)を入れて精算(settle)。
  3) tag_stats でタグ別の複勝率/単ROI/平均人気を見る。十分なnが貯まったら効くタグを採用。
"""
import json
import os
from collections import defaultdict
from datetime import datetime

LEDGER_PATH = os.path.join(os.getcwd(), "paddock_ledger.json")
MIN_SAMPLE = 20   # この件数(精算済)に満たないタグは「サンプル不足」と明示する

SCENES = ('paddock', 'training')
SCENE_LABEL = {'paddock': 'パドック', 'training': '調教'}

# 観察タグ: (key, 表示ラベル, グループ, scene)。group は表示用の仮説(fade=減点候補/
# buy=加点候補/ctx=文脈)。scene=paddock/training。極性が正しいかは台帳の実測で判定する。
TAG_DEFS = [
    # ===== パドック =====
    # --- fade候補(走らないサイン仮説) ---
    ('sweat_foam',  '白い泡の発汗(首/股)',       'fade', 'paddock'),
    ('sweat_cold',  '季節外れ/大量の発汗',       'fade', 'paddock'),
    ('chaka',       'チャカつき/イレ込み',       'fade', 'paddock'),
    ('diarrhea',    '下痢(尻汚れ)',              'fade', 'paddock'),
    ('umake',       '馬っ気(牡の興奮)',          'fade', 'paddock'),
    ('gait_stiff',  '歩様が硬い/ぎこちない',     'fade', 'paddock'),
    ('head_high',   '頭が高い/力んでいる',       'fade', 'paddock'),
    ('donadona',    'ドナドナ(引かれて歩く/内回り)', 'fade', 'paddock'),
    ('two_handler', '2人引きで必死に抑え',       'fade', 'paddock'),
    ('tomo_loose',  'トモが緩い/張り無し',       'fade', 'paddock'),
    ('over_weight', '太め残り(背割れ/腹ボテ)',   'fade', 'paddock'),
    ('too_thin',    '細すぎ/巻き上がり',         'fade', 'paddock'),
    ('dull_coat',   '毛づや悪い/覇気無し',       'fade', 'paddock'),
    ('eye_red',     '目の充血',                  'fade', 'paddock'),
    # --- buy候補(激走サイン仮説・予測は織込み済みなのでROIで判定) ---
    ('zenigata',    '銭形(代謝良)',              'buy', 'paddock'),
    ('tomo_tight',  'トモがパンと張る',          'buy', 'paddock'),
    ('coat_shine',  '毛艶◎/発光感',             'buy', 'paddock'),
    ('vein',        '血管の浮き(究極仕上げ)',    'buy', 'paddock'),
    ('deep_step',   '踏み込みが深い',            'buy', 'paddock'),
    ('rhythm_out',  'リズム良く外側を大回り',    'buy', 'paddock'),
    ('calm_focus',  '落ち着き/集中',            'buy', 'paddock'),
    ('first_blink', '初ブリンカー等×集中(変わり身)', 'buy', 'paddock'),
    ('kani_ok',     '返し馬でカニ走り→折り合いOK', 'buy', 'paddock'),
    # --- 文脈(過去比較) ---
    ('worse_usual', 'いつもより悪い(過去比較で異常)', 'ctx', 'paddock'),
    ('better_usual','いつもより良い(過去比較)',  'ctx', 'paddock'),
    # ===== 調教 =====
    # --- fade候補 ---
    ('t_bate',         'ゴール後バテてヘロヘロ(即消し)', 'fade', 'training'),
    ('t_decel_lap',    '減速ラップ(前半飛ばし最後タレ)', 'fade', 'training'),
    ('t_dull',         '反応一息/終い失速',         'fade', 'training'),
    ('t_yoroke',       '左右によろける/真っ直ぐ走れない', 'fade', 'training'),
    ('t_pull',         'かかる/折り合い欠く',       'fade', 'training'),
    ('t_course_switch','調教コース急変(脚部不安疑い)', 'fade', 'training'),
    ('t_heavy',        '帰厩後 重い/太い感じ',      'fade', 'training'),
    ('t_form_bad',     'フォーム乱れ/ぎこちない',   'fade', 'training'),
    ('t_reluctant',    '行きたがらない/促し通し',   'fade', 'training'),
    # --- buy候補 ---
    ('t_after_goal', 'ゴール後も余力(追って更に加速)', 'buy', 'training'),
    ('t_accel_lap',  '加速ラップ/ラスト1F 12秒台のキレ', 'buy', 'training'),
    ('t_awase_strong','併せ馬で格上に好反応/再加速', 'buy', 'training'),
    ('t_kickback',   'キックバック大(力強い踏み込み)', 'buy', 'training'),
    ('t_strong',     '終いしっかり伸びる',        'buy', 'training'),
    ('t_easy_fast',  '馬なりで好時計(余力)',      'buy', 'training'),
    ('t_sharp',      '反応良くスムーズ',          'buy', 'training'),
    ('t_form_good',  '坂路フォーム良/ストライド大', 'buy', 'training'),
    ('t_comeback',   '帰厩後の変わり身/状態上昇', 'buy', 'training'),
    # --- 文脈 ---
    ('t_harder',    'いつもより強い負荷/本数多い', 'ctx', 'training'),
    ('t_lighter',   'いつもより軽い調整',        'ctx', 'training'),
]
TAG_ORDER = [k for k, _, _, _ in TAG_DEFS]
TAG_LABEL = {k: lbl for k, lbl, _, _ in TAG_DEFS}
TAG_GROUP = {k: g for k, _, g, _ in TAG_DEFS}
TAG_SCENE = {k: sc for k, _, _, sc in TAG_DEFS}
GROUP_LABEL = {'fade': '減点候補', 'buy': '加点候補', 'ctx': '文脈'}


def scene_tags(scene):
    """指定sceneのタグキーをTAG_ORDER順で返す。"""
    return [k for k in TAG_ORDER if TAG_SCENE.get(k) == scene]

# 各タグが「どういう状況か」の説明(資料の減点法/3本柱より)。UIのツールチップ/凡例用。
TAG_HELP = {
    'sweat_foam':  '首回り/股の間に石鹸のような白い泡。暑さの透明な汗と違い、極度の緊張でエネルギーを空回りさせているサイン(即消しレベル)。',
    'sweat_cold':  '涼しい日・冬場なのに大量に汗をかいている。精神的な不安定のサイン。',
    'chaka':       '小走り・首の激しい上下・キョロキョロ・尻っぱね。集中を欠きレース前に体力を消耗。',
    'diarrhea':    '尻/後肢の汚れ＝下痢。体調不良や極度のストレス(即消しレベル)。',
    'umake':       '牡馬がシンボルを出す興奮状態(馬っ気)。レースに集中できていない。',
    'gait_stiff':  '足取りがカチカチ・ぎこちない歩き。状態不十分。',
    'head_high':   '頭を高く上げ首に力が入る=過度の緊張(逆に終始下げ続けは元気不足)。',
    'donadona':    '厩務員に引っ張られてようやく歩く/歩幅が狭く内側を回る。活気なし。',
    'two_handler': '2人がかりで必死に抑える=気性難。※ガッチリ落ち着かせているなら逆にプラス評価もある(例外)。',
    'tomo_loose':  '後肢/尻の筋肉に張りがなく緩い。仕上がり不足(未勝利戦のような幼さ)。',
    'over_weight': '腹がボテッ/背中の肉が左右に割れる「背割れ」=太め残り。',
    'too_thin':    '腹が極端に巻き上がりガリガリ=痩せすぎ・栄養不足。',
    'dull_coat':   '毛がボサッと光沢なし・覇気を感じない。体調不良の危険信号。',
    'eye_red':     '目が血走る/口から泡。かなりの興奮状態(イレ込み)。',
    'zenigata':    'トモ周辺に浮く斑点模様(銭形)。代謝良好=絶好調のサイン。※冬毛/芦毛は見えにくいので注意。',
    'tomo_tight':  '後肢/尻がムキムキに盛り上がり皮膚が弾けそうな張り。最高出力の証。',
    'coat_shine':  '内側から発光するような光沢。栄養吸収良好で終盤の二の脚に直結。※ワックスの人工テカリと区別。',
    'vein':        '下腹部/四肢の付け根に血管が浮き出る。無駄肉のない究極の仕上がり。',
    'deep_step':   '後肢が前肢の跡を超えて深く踏み込む。可動域が広くストライドが伸びる。',
    'rhythm_out':  '引っ張られず自発的に外側を大回り・一定のリズム。やる気と集中力の証。',
    'calm_focus':  '周囲を気にせず落ち着き、騎手が乗るとピリッと気合が入る。理想の状態。',
    'first_blink': '前走未装着のブリンカー/シャドーロール等を初装着し集中している=「一変」の激走予兆。',
    'kani_ok':     '本馬場入場後に斜めに行進(カニ走り)させて落ち着く=折り合いがついた。パドックでイレ込んでいても再評価の余地。',
    'worse_usual': '普段大人しい馬がチャカつく等、その馬の平常運転と比べて異常(過去比較)。',
    'better_usual':'過去の凡走時より明らかに状態が良い(過去比較)。',
    # 調教
    't_bate':       '終点を過ぎるとバテてヘロヘロ/追っても反応なし。資料の最重要消し材料(即消し)。',
    't_decel_lap':  '前半飛ばして最後タレる減速ラップ(例 12.0→13.0)。全体時計が速くても危険・新馬戦で人気して飛ぶ典型。',
    't_dull':       '追われても反応が一息/終いが伸びず失速。動きに余裕がない。',
    't_yoroke':     '左右にヨレる/真っ直ぐ走れない。直進性を欠く=大きな減点。',
    't_pull':       'かかって行きたがり折り合いを欠く。レースで脚を溜められない懸念。',
    't_course_switch':'普段ウッドで追う馬が急に坂路の馬なりに変更等=コースで追えない脚部不安のサインの可能性大(マイナス)。',
    't_heavy':      '帰厩後/久々で体が重そう・太い感じ。仕上がり途上。',
    't_form_bad':   '走法フォームが乱れる/ぎこちない・四肢の連動が悪い。',
    't_reluctant':  '行きたがらず終始促し通し。気合い乗り不足。',
    't_after_goal': '終点を過ぎても騎手に追われ続け、それに反応して更に加速している。資料の最重要プラスポイント。',
    't_accel_lap':  '徐々に加速しラスト1Fを12秒台で切る加速ラップ。実戦でのキレと余力を保証。脚質問わず高期待値。',
    't_awase_strong':'併せ馬で格上(オープン/重賞)相手に楽な手応えで追走/抜かれそうで自ら顔を向け再加速する勝負根性。先着の有無より反応の質を重視。',
    't_kickback':   '蹴り上げた土(ウッドチップ)が高く跳ねるほど踏み込みが力強い証拠。',
    't_strong':     '終いまでしっかり伸びる/止まらない。スタミナと気合い十分。',
    't_easy_fast':  '馬なり(抑えたまま)で好時計。余力を持って速い=高評価。',
    't_sharp':      '指示への反応が良くスムーズに加速できる。',
    't_form_good':  '坂路等でフォームが良くストライドが大きい/トモの踏み込み深い。',
    't_comeback':   '帰厩後/前走比で明らかに動きが上昇=変わり身の予兆。',
    't_harder':     'いつもより強い負荷/本数が多い=勝負気配 or 仕上げ遅れの両義(過去比較)。',
    't_lighter':    'いつもより軽めの調整(過去比較)。',
}

# 添付メディア(画像/動画)の保存先。lib不要・標準のファイル保存のみ。
MEDIA_DIR = os.path.join(os.getcwd(), 'data', 'paddock_media')
MEDIA_EXT_OK = ('.jpg', '.jpeg', '.png', '.webp', '.gif',
                '.mp4', '.mov', '.webm', '.m4v', '.avi')


def load_ledger(path=LEDGER_PATH):
    """台帳(エントリのlist)を読み込む。無ければ空list。"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_ledger(led, path=LEDGER_PATH):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(led, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def make_entry(*, race_id, umaban, name, ninki=None, odds=None, tags=None,
               note='', source='manual', media=None, scene='paddock'):
    """観察1件。chaku/win_odds は精算時に settle_entry で埋める。
    scene=paddock/training。media=添付画像/動画の相対パスlist(phase BのGemma評価用の正解データ)。"""
    return {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'scene': (scene if scene in SCENES else 'paddock'),
        'race_id': str(race_id),
        'umaban': (int(umaban) if umaban not in (None, '') else None),
        'name': str(name or ''),
        'ninki': (int(ninki) if ninki not in (None, '') else None),
        'odds': (float(odds) if odds not in (None, '') else None),
        'tags': [t for t in (tags or []) if t in TAG_LABEL],
        'note': str(note or ''),
        'source': ('gemma' if source == 'gemma' else 'manual'),
        'media': list(media or []),   # 画像/動画の相対パス
        'chaku': None,         # 精算後の着順
        'win_odds': None,      # 精算時点の確定単勝オッズ(あれば)
        'settled': False,
    }


def save_media(data, filename, *, race_id='', umaban='', media_dir=MEDIA_DIR):
    """アップロードされた画像/動画(bytes)を MEDIA_DIR に保存し、相対パスを返す。
    拡張子が許可外なら None。lib不要(標準のファイル書き込みのみ)。"""
    ext = os.path.splitext(str(filename))[1].lower()
    if ext not in MEDIA_EXT_OK:
        return None
    os.makedirs(media_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe = f"{race_id}_{umaban}_{stamp}{ext}".lstrip('_')
    path = os.path.join(media_dir, safe)
    # 同名衝突を避ける
    n = 1
    base, e = os.path.splitext(path)
    while os.path.exists(path):
        path = f"{base}_{n}{e}"
        n += 1
    with open(path, 'wb') as f:
        f.write(data)
    return os.path.relpath(path, os.getcwd())


def add_entry(entry, path=LEDGER_PATH):
    """1件追記。成功でTrue。"""
    led = load_ledger(path)
    led.append(entry)
    return save_ledger(led, path)


def _key(race_id, umaban):
    return (str(race_id), (int(umaban) if umaban not in (None, '') else None))


def settle_entry(race_id, umaban, chaku, win_odds=None, path=LEDGER_PATH):
    """同 race_id × umaban の未精算エントリに着順(と単勝オッズ)を記録。
    更新件数を返す(0=該当なし)。"""
    led = load_ledger(path)
    tgt = _key(race_id, umaban)
    n = 0
    for e in led:
        if _key(e.get('race_id'), e.get('umaban')) == tgt:
            try:
                e['chaku'] = int(chaku)
            except (TypeError, ValueError):
                continue
            if win_odds not in (None, ''):
                try:
                    e['win_odds'] = float(win_odds)
                except (TypeError, ValueError):
                    pass
            e['settled'] = True
            n += 1
    if n:
        save_ledger(led, path)
    return n


def _agg():
    return {'n': 0, 'settled': 0, 't3': 0, 'win': 0,
            'pay1': 0.0, 'pay1_n': 0, 'ninki_sum': 0, 'ninki_n': 0}


def _add(d, e):
    d['n'] += 1
    if e.get('ninki') is not None:
        d['ninki_sum'] += e['ninki']
        d['ninki_n'] += 1
    if not e.get('settled'):
        return
    chaku = e.get('chaku')
    if chaku is None:
        return
    d['settled'] += 1
    d['t3'] += 1 if chaku <= 3 else 0
    d['win'] += 1 if chaku == 1 else 0
    # 単ROI: 精算時の単勝オッズが記録されている分だけで計算(無い分は母数から除外)
    o = e.get('win_odds') or e.get('odds')
    if o:
        d['pay1_n'] += 1
        d['pay1'] += (o if chaku == 1 else 0.0)


def _scene_of(e):
    return e.get('scene') or 'paddock'


def baseline(ledger, scene=None):
    """(指定sceneの)精算済ベース複勝率/単勝率/平均人気。タグ判定の比較基準。"""
    d = _agg()
    for e in ledger:
        if scene and _scene_of(e) != scene:
            continue
        _add(d, e)
    return _summary('全体ベース', d)


def _summary(label, d):
    st = max(d['settled'], 1)
    return {
        'label': label,
        'n': d['n'],
        'settled': d['settled'],
        't3_rate': d['t3'] / st,
        'win_rate': d['win'] / st,
        'roi1': (d['pay1'] / d['pay1_n']) if d['pay1_n'] else None,
        'roi1_n': d['pay1_n'],
        'avg_ninki': (d['ninki_sum'] / d['ninki_n']) if d['ninki_n'] else None,
    }


def tag_stats(ledger, scene=None):
    """(指定sceneの)タグ別の集計list(精算済件数の多い順)。各要素に group/仮説極性も含む。
    複勝率はベースとの差分(delta_t3)で見る。平均人気で『ただの人気薄か』を判別する。"""
    by = defaultdict(_agg)
    for e in ledger:
        if scene and _scene_of(e) != scene:
            continue
        for k in (e.get('tags') or []):
            if k in TAG_LABEL and (not scene or TAG_SCENE.get(k) == scene):
                _add(by[k], e)
    base = baseline(ledger, scene=scene)
    out = []
    for k, d in by.items():
        s = _summary(TAG_LABEL[k], d)
        s['key'] = k
        s['group'] = TAG_GROUP.get(k, 'ctx')
        s['delta_t3'] = (s['t3_rate'] - base['t3_rate']) if d['settled'] else 0.0
        s['enough'] = d['settled'] >= MIN_SAMPLE
        out.append(s)
    out.sort(key=lambda s: (-s['settled'], -s['n']))
    return out, base


def verdict(s, base):
    """1タグの実測判定(表示用の短文)。仮説極性ではなく実測で言う。"""
    if not s['enough']:
        return f"サンプル不足(精算{s['settled']}/{MIN_SAMPLE}件)"
    grp = s['group']
    d = s['delta_t3']
    roi = s['roi1']
    if grp == 'fade':
        # 減点候補: ベースより複勝率が十分低ければ「消し材料として機能」
        if d <= -0.05:
            return f"消しに機能(複勝率ベース比{d*100:+.1f}pt)"
        if d >= 0.03:
            return f"逆効果の疑い(複勝率ベース比{d*100:+.1f}pt・消すと取りこぼす)"
        return f"効果薄/織込み済み(複勝率ベース比{d*100:+.1f}pt)"
    if grp == 'buy':
        # 加点候補: 予測は織込み済みなので複勝率高でなくROIで判定
        if roi is not None and roi >= 1.0:
            return f"買い妙味あり(単ROI{roi*100:.0f}%)"
        if roi is not None:
            return f"買い妙味なし(単ROI{roi*100:.0f}%・織込み済み)"
        return f"オッズ未記録でROI不明(複勝率{s['t3_rate']*100:.0f}%)"
    return f"複勝率{s['t3_rate']*100:.0f}%(ベース比{d*100:+.1f}pt)"
