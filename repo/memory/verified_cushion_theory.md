---
name: verified-cushion-theory
description: クッション値理論(資料PDF)の検証 — 前残り/遷移は否定、種牡馬×9.5水準は4頭のみ本物
metadata: 
  node_type: memory
  type: project
  originSessionId: ae626662-ddf7-4948-bcf9-cdf9f6a2e414
  modified: 2026-07-21T13:48:47.300Z
---

ユーザー提供のクッション値理論資料(2026-07)を芝13.7万頭(2020-09〜2026-06)・人気統制残差・train/holdout両窓で検証(scripts/cushion_theory_backtest.py)。

**結果**:
- ①「高クッション=前残り(先行有利)」→ **否定**。先行習性(pos_ratio3≤0.28)は硬い馬場でも残差≈0〜負(trainやや硬-1.9pp)。[[verified-front-runner-overbet]]と整合(先行人気馬は過剰人気)。holdout硬11+の+6.4ppはn=134の小標本。
- ②「種牡馬×コース×9.5閾値」→ 名指し16頭中**12頭崩落**(コース別閾値=多重検定の過学習)。pooled両窓一致は4頭のみ: **ダイワメジャー(硬〇+2.7/+8.0pp)・ハービンジャー(軟〇)・リアルスティール(軟〇)・サトノダイヤモンド(軟〇=資料の京都硬〇説と逆)**。→ track_bias._SIRE_CUSHION_LEVEL + sire_cushion_level_flag()に配線(SRA血統列+血統SPテーブル「ク値適性」・芝のみ)。シフト版_SIRE_CUSHION_AFFINITY(前日比・2025重賞小標本)とは別軸で併設。
- ③「前走標準→今走硬め×前走末脚上位=激走」→ **遷移の独自エッジ無し**。対照実験で正体は既知の末脚top3×1-6人気の一般効果(+2.4〜+3.8pp z6.8-11.7)。今走やや硬での増幅はholdoutのみ(train ns)=採用ゲート未達。逆遷移(やや硬→標準)はholdout崩落。

**Why**: コース別×閾値の高ROI表(単回915%等)は5走前理論[[verified-5run-theory-debunk]]と同型の小標本幻影。水準×種牡馬をpooled+両窓で見るのが正しい検証形。

**How to apply**: クッション系の新提案はまずこのスクリプトの枠(band×人気統制残差×両窓)で検証。4頭以外の種牡馬追加はデータが変わらない限り禁止。JRA公式PDF取り込み(scripts/update_track_cond_from_jra.py)で芝含水率も取得可能になった([[project-jra-baba-scraper]]相当・track_cond拡張済み)。
