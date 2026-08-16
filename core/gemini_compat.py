# -*- coding: utf-8 -*-
"""Gemini のモデル世代差を吸収する薄い互換レイヤ — core/gemini_compat.py

【なぜ必要か】
Gemini 3.5/3.6 で思考制御のパラメータが `thinking_budget`(整数) から
`thinking_level`(文字列) に置き換わった。この2つは**排他**で、
片方しか受け付けないモデルに他方を渡すと 400 INVALID_ARGUMENT で落ちる。

実測(2026-07-23・実機で全モデルを叩いて確認):
    モデル                          thinking_budget=0   thinking_level='MINIMAL'
    gemini-2.5-flash                     OK                  400
    gemini-2.5-flash-lite                OK                  400
    gemini-3.1-flash-lite-preview        OK                  OK
    gemini-3.5-flash-lite                400                 OK
    gemini-3.6-flash                     400                 OK

このアプリは MAGI が 2.5系と3.1系を**混在させ、さらに相互フォールバック**するため、
「置換」では直せない(2.5系に thinking_level を渡した瞬間に死ぬ)。よってモデル名から
世代を判定して振り分ける。**未知の新モデルは thinking_level 側に倒す**
(Googleの移行方向がそちらで、今後のモデルは全てそちら側のため)。

参考: temperature / top_p / top_k は3.5以降で「無視される」だけでエラーにはならない
(実測確認済み)。よって緊急の削除は不要だが、将来世代では400になると公式に予告されている。
"""
import re

# この版以降は thinking_level を使う(それ未満は thinking_budget)
_LEVEL_FROM = (3, 5)


def _version(model_name):
    """モデル名から (major, minor) を取り出す。判定できなければ None。"""
    m = re.match(r'gemini-(\d+)\.(\d+)', str(model_name or ''))
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def uses_thinking_level(model_name):
    """このモデルは thinking_level 方式か。未知の名前は新方式(True)に倒す。"""
    v = _version(model_name)
    return True if v is None else v >= _LEVEL_FROM


def supports_sampling(model_name):
    """temperature / top_p / top_k が実際に効くモデルか。

    3.5以降では**無視される**(実測でエラーにはならない)が、公式に
    「将来のモデル世代では400を返す」と予告されている。よって
    『効く世代にだけ渡す』のが正しい扱いで、一律削除でも一律送信でもない。

    ⚠ 一律削除してはいけない: 2.5系では今も有効で、MAGIのCASPERは
      temperature=0.85(直感・創造性)が人格の源泉の一つになっている。
    """
    return not uses_thinking_level(model_name)


def sampling_kwargs(model_name, temperature=None, top_p=None, top_k=None):
    """効く世代のときだけサンプリング系引数を dict で返す(効かない世代は空dict)。

    使い方: GenerateContentConfig(**base, **sampling_kwargs(model, temperature=0.4))
    """
    if not supports_sampling(model_name):
        return {}
    out = {}
    if temperature is not None:
        out['temperature'] = temperature
    if top_p is not None:
        out['top_p'] = top_p
    if top_k is not None:
        out['top_k'] = top_k
    return out


def apply_thinking(cfg, types_mod, model_name, level='MINIMAL'):
    """cfg にモデル世代に合った思考設定を適用して返す。

    cfg:        GenerateContentConfig インスタンス
    types_mod:  google.genai.types モジュール
    model_name: これから呼ぶモデル名(**必ずモデルごとに呼び直すこと**)
    level:      3.5以降で使う思考レベル。'MINIMAL'/'LOW'/'MEDIUM'/'HIGH'
                JSONだけ欲しい用途は 'MINIMAL'、表を読んで判断させるなら 'LOW' 以上。

    ⚠ 思考トークンは max_output_tokens を消費する。'LOW' 以上にするなら出力枠に
      余裕を持たせること(実測で700では JSON が途中で切れた)。
    例外は握りつぶす(思考設定に非対応のモデルでも本体の呼び出しは通すため)。
    """
    try:
        if uses_thinking_level(model_name):
            cfg.thinking_config = types_mod.ThinkingConfig(thinking_level=level)
        else:
            cfg.thinking_config = types_mod.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass
    return cfg
