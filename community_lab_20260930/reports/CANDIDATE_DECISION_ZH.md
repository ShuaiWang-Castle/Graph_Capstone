# 候选决定：C1 完成，冻结准入失败

本轮主状态为 **NO_REPRODUCIBLE_GAIN**：未获得通过事先冻结的全网格或有限范围准入规则的质量—成本改进。CSR 在 n5000 开发图上有三个算法种子一致的局部加速，但不能绕过小图质量条件；独立确认门保持关闭。此状态不等于所有局部观察都没有收益。

## 机制、注册与原样控制

初始216项结束后的实际profile定位 NOCD 训练批损失的 endpoint gather、逐元素乘法与反向 scatter。C1 仅替换作者 `BerpoDecoder.loss_batch` 的 ordered pair-dot primitive：已有 CPU `torch.sparse.sampled_addmm` 用 CSR 唯一有向 pair 计算，再按 inverse 恢复重复、顺序及 multiplicity。全部 unique、排序、CSR 和 inverse 准备计入 pipeline。GCN、初始化、sampler、Adam、正则、full-training-loss 选点、patience、K 和解码阈值0.5均保持原规则。

数学依据是已知双线性恒等式，不是新定理或社区检测原理。有限精度计算顺序可能改变轨迹，函数/梯度近似相等不能保证训练输出逐字节相同。真实归属质量必须独立评价。

登记文件 `configs/candidate_registry_v1.json`；四个 arm 在 `configs/nocd_pairdot_controls_v1.json`。24开发图×算法73/74/75×elementwise500、BMM500、CSR500、elementwise1000，共288项全部完成并评分，全部属于oracle-K面板，尚无native-K结论。1000只增加最大epoch，patience原样，是cap敏感性控制，不是等墙钟预算质量对照。另24项新跑原作者adapter/seed73，和历史基线、elementwise镜像逐项核对，24/24输入、initial/best embedding、model/optimizer值、检查epoch与full-loss数值、停止/选点及cover精确一致；elapsed/阶段计时、完整JSON序列化和实际时间单独保留。

入场功能检查包含30组primitive、4组作者loss和3组gradcheck；另有12组pair-ID准备等价检查、18次无RNG/输入突变检查和原作者/三后端smoke。入场证据在 `work/setup/candidate_integration_audit/`，仅证明功能契约，不能代替开发结果。

## 冻结标准与实际逐层结果

`configs/candidate_gate_v1.json` 于2026-09-30T07:16:08.912145+00:00冻结，SHA-256 `2cde3f5429ea10b76e37b338ea512efe8e28ab1c2b0de9f1dc7c33df139527b1`，早于首个候选质量读取。每个 n×算法seed层保留12个计划配对；macro与micro平均差均须≥−0.01，不新增失败；节时中位须≥10%。预先允许 n5000 有限范围速度信号，但两种规模、每个seed均须先通过质量/状态。只能选一个全局后端，不能按case、真overlap或标签路由。CSR归因还要与现成BMM直接比较。阈值是事先约定的实用准入，不是统计非劣效证明。

节时为每个同图配对的 `1−T_arm/T_elementwise500` 再取中位；质量为同图差的均值。所有层12/12完整，新增 incomplete=0。

| 后端 | n | 算法seed | 配对中位节时 | 平均macro差 | 平均micro差 | 质量准入 |
|---|---:|---:|---:|---:|---:|---|
| BMM | 1000 | 73 | −3.5048% | +0.012468 | +0.010377 | 通过 |
| BMM | 1000 | 74 | −3.1835% | −0.006897 | −0.004839 | 通过 |
| BMM | 1000 | 75 | −2.1727% | −0.008885 | −0.007138 | 通过 |
| BMM | 5000 | 73 | −3.7270% | −0.003227 | −0.001374 | 通过 |
| BMM | 5000 | 74 | −4.4977% | +0.004548 | +0.005038 | 通过 |
| BMM | 5000 | 75 | −4.2055% | +0.001726 | +0.001117 | 通过 |
| CSR | 1000 | 73 | −7.9448% | +0.006846 | +0.004826 | 通过 |
| CSR | 1000 | 74 | −7.4585% | −0.000832 | −0.000770 | 通过 |
| CSR | 1000 | 75 | −7.3164% | **−0.0108144000793** | −0.009705 | **失败** |
| CSR | 5000 | 73 | +18.4766% | −0.002899 | −0.000623 | 通过 |
| CSR | 5000 | 74 | +17.1480% | −0.001380 | −0.000695 | 通过 |
| CSR | 5000 | 75 | +17.4531% | −0.004172 | −0.002454 | 通过 |

CSR 小图seed75越界约0.0008144仍失败，不事后放宽−0.01。BMM六层平均质量合格却全部变慢；gate中的 `selected_global_backend=BMM` 只是质量合格项的排序结果，`selected_claim_scope=none`，不是赢家或确认算法。CSR大图相对BMM节时22.0266%/21.4058%/20.5499%，小图却慢约4.81%–7.25%；局部速度优势不能替代质量准入。

全部实际配对、精确小数、更新数、失败分母、计算工具和输入hash在 `analysis/nocd_pairdot_gate_v1/`。72配对来自相关开发网格和三种算法随机数，不能视作72张独立抽样图，不给IID置信区间或p值。

## 不能被平均值掩盖的退化

相对elementwise，BMM有4项、CSR有5项 macro或micro下降≥0.03，均在n1000。例如CSR在 `lfr_n1000_o20_m50_s11 / seed75` 宏差−0.066839、微差−0.060191、至少两正确归属召回差−0.125。n5000相对elementwise虽没有达到该macro/micro材料阈值的退化，至少两正确归属召回仍分别有8/3/4项下降；不能写逐例无退化。

大图对BMM也有材料退化：`lfr_n5000_o00_m20_s12 / seed74` CSR−BMM宏差−0.036739、微差−0.024836。主列表 `regressions.csv` 只收BMM/CSR对elementwise的53条材料退化或两归属召回下降；独立审阅目录 `work/setup/candidate_final_artifact_audit/scientific_scope_review/ALL_EXISTING_PAIR_REGRESSIONS.csv` 补全全部既有比较的87条索引（53主对照、27 CSR对BMM、7 cap控制）。它复制原pairs的既有flags，没有重评分或改阈值；完整288配对始终保留。

## 成本诊断、增加cap与强实现

全部72个case/seed的四arm initial embedding字节一致。CSR66/72对与elementwise更新次数相同，BMM65/72相同；不同次数全部在n1000。相同次数不保证轨迹相同。n5000全部36对CSR更新次数相同，forward/loss/backward每更新成本中位降低21.6936%/20.4745%/20.7453%；大图局部收益不是仅靠提前停止获得。n1000相同次数子集的该阶段反而慢约9.37%–12.13%，只作探索诊断，不替换headline分母。

六项独立候选profile均实际完成，cover、initial/best embedding、检查epoch与full-loss数值均与对应无profile任务一致；elapsed/阶段计时和完整JSON分别保留。五步早期窗口中，CSR小图pair准备10次约9.745ms，大图约10.709ms；大图elementwise gather/scatter self约34.629/21.557ms，CSR约0.176/0.159ms。已有BMM仍做gather/scatter。嵌套计时不可相加，五步窗口和带instrumentation的准备计时不能当完整pipeline收益。源、trace及汇总在 `work/setup/candidate_profile_tools/` 和 `analysis/candidate_profile_summary.json`。

cap500→1000的72对中64对确定增加更新、8对没有。n5000三seed完整时间比例1.8046/1.8926/1.8817；macro平均差−0.003090/+0.003085/+0.000315，micro +0.006078/+0.007118/+0.005580。多算带来有限且指标不一致的变化，不能声称解决大图归属学习或同预算更好。

已有Ego PC/Leiden/min5和CC/Louvain/min5控制48项完成，不算第二机制。原生C++ BigCLAM/oracle-K在n5000的12/12同图上比历史原NOCD更快且macro/micro都高；CSR相对一个原NOCD后端的加速不能升级为整个方法集合前沿或SOTA。不同实现栈不能单独证明算法复杂度优势。

## 终止本轮的具体决定

仅测试C1一个机制；最多两个是上限，不是必须填满。现有另一些瓶颈属于已有实现修复、native K信息预算差异或训练loss与归属目标不一致，尚无在原任务纪律下由trace支持的第二个单机制改动及清晰控制，故本轮不为制造赢家添加C2。

保持冻结门关闭；LFR211/212、算法173/174/175、另生成器与degree-only正式图均未生成/运行，确认集未参与调参。另生成器仅有预登记定义和小规模功能测试，不是泛化证据。本轮交付完整负面结果及局部开发信号，不继续运行直到赢、不改题、不自动push。独立范围审阅见 `work/setup/candidate_final_artifact_audit/scientific_scope_review/`；无新颖性、录用或投稿就绪判决。
