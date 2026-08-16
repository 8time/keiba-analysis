---
name: project-trackbias
description: トラックバイアス強化のアプリ統合計画。計画書は repo の trackbias_integration_plan.md。JV-VAN無料体験中に強化したい
metadata:
  node_type: memory
  type: project
  originSessionId: 5e89769b-3184-403b-8fde-01496f4cfa45
---

トラックバイアスをアプリ（特に📊判定根拠エビデンス表）に強化統合する計画。詳細は repo ルートの **trackbias_integration_plan.md**（2026-06-14作成）。NotebookLMリサーチ済み。

**データ制約（調査済み・重要）**:
- JV-Dataフィード自体には **クッション値・含水率・砂厚・ABCコース区分は無い**が、**クッション値・含水率は外部CSV取り込みで jravan.db `track_cond`(2,273日×場・2021〜) に収録済み**(下記Phase2参照)。races は tenko/baba_shiba/baba_dirt/mae3f/ato3f/track_code/kyori/surface/hasso_time のみ。
- **荒れ予測には無効(検証済2026-06-17)**: クッション値/含水率で層別しても荒れ率(勝ち馬ninki≥6)はフラット(やわ18.9/標準16.8/かた18.8%=単調性なし)。詳細は[[pace-map-rebuild]]。トラックバイアスは「どの脚質/枠が有利か」のナッジには使えるが「荒れるか否か」の予測子にはならない。
- **track_code は東京芝で全'11'＝A/B/Cコース(仮柵移動)を区別できない**。
- クッション値(2020〜)・含水率はJV-Dataにあるはず→どのrecordか要特定して取り込み。
- 整備車両画像解析・騎手コメントNLP・砂付着検知は🔴データ源なしで非現実的。

**実装フェーズ（推奨順）**:
- Phase1(取り込み不要・即効): 当日前半レースのresults集計で逆算バイアス(4角通過順・好走枠偏り・上がり3F差)＋3視点枠評価(馬番/逆馬番/外枠率) → エビデンス表&Vエリアbaba自動化。
- Phase2: クッション値・含水率取り込み→芝/ダ分岐(含水は芝=時計遅/ダ=時計速で逆)→エビデンス表。
- Phase3: バイアス恩恵分離(恵まれ勝ち=危険人気/逆らい好走=穴)・不利巻き返し抽出→予測スコア/[[catch-underrated-winners]]・妙味フラグへ。
- Phase4(将来): ML相互作用特徴量・Target Encoding(現アプリは非ML)。

各ルールは jravan.db でバックテストしてから採用（[[pace-map-rebuild]]の「測ってから最適化」踏襲）。
既存接続先: エビデンス表(app.py evidence_list ~1494)、Vエリア(build_v_matrix・baba自動)、finish(predict_finish)、妙味フラグ。

**実装状況（2026-06-14）— core/track_bias.py 新設**:
- **検証済**: 同日同場同馬場で前半の前残り傾向は後半も持続（前残り率高い日=後半61% vs 低い日50% / 内枠32.5%vs26.3%）。効果は中程度＝ナッジ扱い。
- **Phase1 実装済**: `empirical_bias_from_db`(当日逆算バイアス)・`frame_eval`(3視点枠)・`course_bias_text`(大箱小回り×高速タフ)。エビデンス表に「当日逆算バイアス」「コース×馬場傾向」行を追加。Vエリアbaba初期値を①当日逆算(最優先)②開催日数/馬場 の順で自動。
- **Phase2 実装済(DB自動供給+前日比シフト+血統照合)**: クッション値・含水率はJV-Dataに無い（確定）。外部CSV購入(TARGET外部指数18桁形式)で解決。`scripts/ingest_track_cond.py`→jravan.db `track_cond`(2,273日×場)。**前日比クッション値シフト**(NotebookLMリサーチ反映): `cushion_day_shift()`で同場前日比Δ算出→[+]硬化/[△]軟化/[±0]。場の信頼度(東京・小倉=高相関/中山・阪神・京都・福島=カオス)・芝種別平均も表示。**種牡馬×シフト適性**: `sire_cushion_flag()`でディープ系=[+]活性、ND系・キタサン=[△]活性、モーリス=[△]⚠危険を自動判定→強適Ranking Table血統列にフラグ表示。**ダート含水率×血統型**: `dirt_moisture_bloodtype()`で乾燥=欧州型🟢/湿潤=米国型🟢。エビデンス表に「前日比クッション値」行追加。**重要**: 絶対値での場間比較は禁物(京都の10≠東京の10)。前日比がキー。
- **Phase3 実装済**: `comeback_flag`＝直近走で当日バイアスに逆らって好走した馬を「🔄バイアス巻き返し候補」として展開マップ内に表示。
- **Phase4 ML: 未実装（意図的に保留）**。現アプリは非ML(強適スコア方式)。LightGBM+相互作用特徴量+Target Encodingは学習パイプライン構築が要る別プロジェクト。やるなら段階的に。
- 当日逆算は jravan.db に当日の先行レースが取り込まれている必要あり。未来レース/体験版当日反映前は None→手動Vエリアにフォールバック。

**コース特性プロファイル改善（2026-06-14）**: 上部「✨コース特性プロファイル」は従来★競馬場コード単独の3択★で距離/芝ダ/内外を無視＝京都/阪神外回りが「標準」、東京ダ短距離が「差し有利」等の誤分類だった。
- `pace_map.course_profile_label(venue,surface,distance)`追加＝get_course_layoutの実測直線長で3ラベル(直線>=400m=差し有利/<=335m=小回り先行/他=標準)。京都芝1400外→差し有利・京都芝2000内→小回り・阪神芝1800外→差し有利と正しく区別。calculate_strength_suitabilityは「直線が長い/小回り」の語で判定するのでラベル文字列維持。
- app.py: スコア計算を `meta.get('course_profile') or session['_course_profile_auto']` に変更。エビデンス表に「コース特性(自動判定)」「コース実績バイアス」行追加。
- `track_bias.course_empirical_bias(jyo,surface,distance)`追加＝jravanで当該コース過去10年の逃げ先行決着率/内枠勝率(静的・コース固有で信頼可)。例:中山ダ1200=逃げ先行65%(先行有利)。
- **重要DB事実**: races.surface はダートが **'ダート'** で保存(='ダ'ではない)。完全一致クエリ`surface='ダ'`は外れる→ `surface LIKE 'ダ%'` を使う(芝は'芝')。get_course_layout/fetch_jv_profilesは`'ダ' in surface`部分一致なので無問題。
