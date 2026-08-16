---
name: verified_pci_pricedin
description: PCI乖離は人気織込み済みで消去妙味なし。想定RPCI乖離は逆効果。is_pci_fatal否定。PCI×コース形状の交互作用もz0.20で否定。弱因子stacking(combo層別)も否定=PCI完全終了
metadata:
  node_type: memory
  type: project
  originSessionId: c3fa42fa-de5c-41c4-9911-b6156b6e7b9d
---

⚡PCI(ペースチェンジ指数)乖離を消去フィルターに使えるかの検証(2026-06-17・ユーザー要望)。scripts/pci_elim_backtest.py, jravan.db 2021-25, 事前AvgPCI=過去5走平均(今走除外・hindsight漏れ防止), n=162,353。jravan time'1369'=96.9秒の専用パース要。

- **①フィールド平均PCIからの乖離**: 絶対複勝率は単調低下(0-1乖離22.9%→6以上20.0%)だが**人気補正残差は最大-0.47pp**(人気薄限定でも-0.75pp)。= 人気織込み済=妙味ではない([[verified_legtype_axis]]脚質priced-inと同型)。
- **②想定RPCIからの乖離→逆効果**: 乖離大ほど複勝率が上がる(20.9→29.1%)。RPCI(逃げ=前傾代理)から離れる=後傾/瞬発型=人気馬寄り。消去に使うと勝ち馬を消す。**不採用**。
- **③is_pci_fatal(core/race_analysis_tools.py 致命的ペース不一致)は検証で否定**: 該当馬の複勝率24.15%>非該当21.35%(残差+0.14pp)。⚡PCI分析の『致命的』表示を消去根拠にするのは過信注意。

- **④PCI傾向×コース形状の交互作用も否定=PCI完全終了**(2026-07-02・カード6・scripts/pci_course_shape_backtest.py): 動画の「O字(トップスピード維持)↔低PCI持続型 / U字(再加速)↔高PCI瞬発型 のマッチで穴」を6人気以下・純粋交互作用コントラスト(主効果打消し)で検証→**holdout2025 C=+0.30pp/z=+0.20**(train z0.65・2026 z1.65)でゲートz2.0未達。単体PCI(①②③)に続き交互作用も否定。→**PCIは軸/相手/消去いずれもエッジ無し。再提案打ち切り**(FEATURE_STATUS.md「検証済み却下」に恒久記録)。

- **⑤『弱因子は重なれば効くのでは(comboと同発想)』も否定**(2026-07-19・ユーザー仮説・scripts/pci_combo_interaction_backtest.py): 事前平均PCI(過去5走・leak-free)×combo層別。train凍結PCI中央値52.7/ninkiベース。「combo=2+(複数シグナル重なり)の中でPCI高低が効くか」→**holdout D=+0.006/z+0.41・2025 D=-0.019/z-1.64で符号逆転=効かない**。皮肉にもPCIが唯一残差を見せるのは**combo=0×人気馬帯(holdout z+3.44/2025 z+2.49)**だが、(a)仮説の真逆(重なりでなく単独時)(b)6人気以下では消滅(z+0.27/+0.77)=穴ROIにならず単勝効率的。→「重ねても効かない=priced-inは層別でも不変」を確認。**教訓**: comboが効くのは検証済みエッジを積むから。ゼロ因子を多数組合せて『効く組合せ』を探すのは多重検定の過学習(in-sample光ってoos死)=combo=0で光り2+で死んだのが実例。弱因子stackingの再提案は打ち切り。

**結論/How to apply**: PCI乖離は単独の消去シグナル非採用。妙味は[[verified_spurt_index]]/[[project_value_scanner]]/[[project_elimination_engine]]に集約。唯一の使い道=「フィールド平均から6pp以上乖離」は絶対複勝率22.4→20.0%で[[project_elimination_engine]]消去クロスの既存弱フラグ(単体priced-in)と同格の"来にくさ"。重複数→絶対複勝率の可視化用途で9個目検証フラグ(pcidev)として足すなら筋は通る(妙味ではない)。**実装済(2026-06-17)**: core/elim_cross.py に pcidev(PCI_DEV_BIG=6.0, 検証フラグ扱いでUNVERIFIED外=band算入)追加。app.py 消去クロスで各馬の事前平均PCI(PCICalculator.analyze_horse_pci(PastRuns))→フィールド平均乖離を compute_flags(pci_dev=)へ。
