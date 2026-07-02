# -*- coding: utf-8 -*-
"""netkeiba「AI展開予測」の4コーナー隊列位置スクレイパー(表示専用)。

netkeibaの出馬表ページ(nar/race.netkeiba.com/race/shutuba.html)には
「AI展開予測」という隊列可視化があり、スタート後/3コーナー/4コーナーの各時点で
各馬アイコン(#Horse{馬番})を CSS の left%(0%=先頭 / 100%=最後方)で配置する。
この位置は動的描画に見えるが、実体は updateHorsePosition() 内の静的JSに
コーナー別に埋め込まれている(要ログイン/課金なし)。

用途: 当アプリの展開MAP(直線=到達位置の帯)と netkeiba AI の4コーナー帯を
照合し、両AIが「同じ帯」と判定した馬に🏆(有利位置一致)/💀(危険位置一致)を出す。
**表示のみ・エッジ主張なし**(展開恩恵はpriced-in [[verified_tenkai_priced_in]])。

方向較正(2026-07-03 大井実査): 先行馬=低left%(#6先行=0%)、追込馬=高left%(#3追込=100%)。
→ left%が小さいほど前・大きいほど後方。
"""
import re
import logging

logger = logging.getLogger(__name__)

# CornerスイッチID → 意味
_CORNER_KEYS = {"Corner01": "start", "Corner02": "corner3", "Corner03": "corner4"}


def _strip_js_line_comments(block: str) -> str:
    """JSブロックから行コメント(// …)を除去する。

    netkeibaのupdateHorsePosition()は「// $(...)」でコメントアウトした
    テンプレ行と実行行が混在するため、コメント行の座標を拾わないよう除去する。
    (このブロックにURLは無いため素朴な // 切りで安全)
    """
    out = []
    for line in block.split("\n"):
        idx = line.find("//")
        out.append(line if idx < 0 else line[:idx])
    return "\n".join(out)


def parse_tenkai_positions(html: str):
    """出馬表HTMLから、AI展開予測のコーナー別 馬番→left% を抽出する。

    戻り値: dict {umaban:int → {'start':float,'corner3':float,'corner4':float}}
    left%は 0=先頭 / 100=最後方。テンプレの余分な馬番は実描画アイコンで濾す。
    データが無ければ空dict。
    """
    if not html:
        return {}

    # 実際に描画されている馬アイコンの馬番のみ採用(テンプレの余剰スロットを除外)
    real = set(int(m) for m in re.findall(r'class="HorseIcon[^"]*"\s+id="Horse(\d+)"', html))
    if not real:
        return {}

    i = html.find("function updateHorsePosition")
    if i < 0:
        return {}
    # 最初のswitch(チェックなし=基本配置)のみを対象にする
    j = html.find("出遅れ率チェック", i)
    block = html[i:(j if j > i else i + 12000)]
    block = _strip_js_line_comments(block)

    result = {u: {} for u in real}
    for corner_id, key in _CORNER_KEYS.items():
        m = re.search(r"case '" + corner_id + r"':(.*?)(?:break;|case ')", block, re.S)
        if not m:
            continue
        seg = m.group(1)
        for mm in re.finditer(r'#Horse(\d+)"\)\.css\(\{[^}]*left\'?\s*:\s*\'?([\d.]+)%', seg):
            u = int(mm.group(1))
            if u in real:
                result[u][key] = float(mm.group(2))
    # 位置が1つも取れなかった馬は落とす
    return {u: v for u, v in result.items() if v}


def band_by_left(left_map, front_frac=0.40, back_frac=0.35):
    """馬番→left%(小=前/大=後) を 前/中/後 の帯に分類する。

    front_frac: 前帯に入れる下位(=先頭寄り)割合。back_frac: 後帯に入れる上位割合。
    ユーザー指定=前40%/後35%。戻り値: {umaban: '前'|'中'|'後'}
    """
    items = [(u, x) for u, x in left_map.items() if x is not None]
    n = len(items)
    if n == 0:
        return {}
    items.sort(key=lambda t: t[1])  # left%昇順=前→後
    n_front = max(1, round(n * front_frac))
    n_back = max(1, round(n * back_frac))
    bands = {}
    for rank, (u, _) in enumerate(items):
        if rank < n_front:
            bands[u] = "前"
        elif rank >= n - n_back:
            bands[u] = "後"
        else:
            bands[u] = "中"
    return bands


def agreement_icons(nk_band_map, app_band_map):
    """netkeiba4コーナー帯とアプリ直線帯が「同帯」の馬に🏆/💀を付す。

    両者とも前=🏆(両AIが有利位置で一致) / 両者とも後=💀(両AIが後方=危険で一致)。
    それ以外(不一致 or 中)は空文字。戻り値: {umaban: '🏆'|'💀'|''}
    """
    icons = {}
    for u, nb in nk_band_map.items():
        ab = app_band_map.get(u)
        if nb == "前" and ab == "前":
            icons[u] = "🏆"
        elif nb == "後" and ab == "後":
            icons[u] = "💀"
        else:
            icons[u] = ""
    return icons


def fetch_tenkai_positions(race_id, html=None):
    """race_idから出馬表HTMLを取得してparse_tenkai_positionsを返す(htmlを渡せば再取得しない)。"""
    if html is None:
        try:
            from core.scraper import fetch_robust_html, _is_nar
            dom = "nar.netkeiba.com" if _is_nar(race_id) else "race.netkeiba.com"
            html = fetch_robust_html(f"https://{dom}/race/shutuba.html?race_id={race_id}")
        except Exception as e:
            logger.warning(f"[ai_tenkai] HTML取得失敗: {race_id} → {e}")
            return {}
    return parse_tenkai_positions(html)


def corner4_bands(race_id, html=None, front_frac=0.40, back_frac=0.35):
    """race_id(またはhtml)から netkeiba AIの4コーナー帯 {umaban:'前'/'中'/'後'} を返す簡便関数。"""
    pos = fetch_tenkai_positions(race_id, html=html)
    c4 = {u: v.get("corner4") for u, v in pos.items() if v.get("corner4") is not None}
    return band_by_left(c4, front_frac=front_frac, back_frac=back_frac)
