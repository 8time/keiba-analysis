"""騎手俗説の参考表示。スコアには接続しない。"""
import pandas as pd
import streamlit as st

from core import jockey_checklist as jc


def render(df):
    with st.expander('🧾 画像の騎手チェック表（参考・スコア非連動）', expanded=False):
        st.caption(jc.SOURCE)
        st.caption(jc.NOTICE)
        st.dataframe(pd.DataFrame(jc.race_rows(df.to_dict('records'))),
                     hide_index=True, use_container_width=True)
        st.caption('条件別の実測値は 🏇騎手分析Pro → レースID一発分析 → '
                   '各騎手の「📈条件別PRB・複勝率」で、勝率・複勝率・騎乗数を確認できます。'
                   '外部サイトのDB条件は集計期間外の検証で優位性未確認です。')
        with st.expander('元画像の35項目・本人確認待ちを含む', expanded=False):
            st.dataframe(pd.DataFrame(jc.catalogue()), hide_index=True,
                         use_container_width=True)
            st.caption('「強い馬」「穴馬」「斤量有利」は画像内に数値定義がありません。'
                       '判読・本人特定が不確かな表記は勝手に補完していません。')
