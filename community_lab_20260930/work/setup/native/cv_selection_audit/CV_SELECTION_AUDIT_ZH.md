# n1000 BigCLAM 原生 CV 选择与停止语义审计

UTC 2026-09-30T06:42:10.672012+00:00 快照；仅审 12 项已 COMPLETED 的 n1000 graph-only native-K BigCLAM。主实验仍在执行，本报告不代表24项主面板已完成。未读活跃输出、真标签或评价质量，不改冻结代码/配置、不跑测量、不登记候选。

## 实际完成证据

| 检查 | 满足/已审项 |
|---|---:|
| grid_exactly_expected | 12/12 |
| all_11_k_have_3_complete_mle | 12/12 |
| all_cv_returned_at_10000_attempts | 12/12 |
| final_mle_completed | 12/12 |
| native_exit_banner_seen | 12/12 |
| scores_finite_and_negative | 12/12 |
| stdout_tab_argmax_equal | 12/12 |
| winner_unambiguous_at_print_precision | 12/12 |
| tab_grid_exactly_expected | 12/12 |
| cover_count_consistent_with_selected_k | 12/12 |

原生接受CLI均为 c=-1/mc=5/xc=100/nc=10/nt=1；stdout和TAB均包含完整网格 `[5,6,8,10,13,17,22,29,39,52,100]`。每个K确有3次CV MLE completion，而后单独最终fit、native exit banner与有效cover。没有用“planned配置”代替实际执行证据。

| case | 选K | stdout第1/2名分差 | CV calls | final attempts | 输出群数 | omitted |
|---|---:|---:|---:|---:|---:|---:|
| lfr_n1000_o00_m20_s11 | 22 | 689.671004 | 33 | 39000 | 22 | 0 |
| lfr_n1000_o00_m20_s12 | 22 | 443.718001 | 33 | 41000 | 22 | 0 |
| lfr_n1000_o00_m50_s11 | 17 | 606.339618 | 33 | 53000 | 17 | 0 |
| lfr_n1000_o00_m50_s12 | 17 | 141.509906 | 33 | 47000 | 17 | 0 |
| lfr_n1000_o20_m20_s11 | 29 | 176.146631 | 33 | 45000 | 29 | 0 |
| lfr_n1000_o20_m20_s12 | 29 | 94.968281 | 33 | 55000 | 29 | 0 |
| lfr_n1000_o20_m50_s11 | 29 | 345.172512 | 33 | 89000 | 29 | 0 |
| lfr_n1000_o20_m50_s12 | 5 | 45.073893 | 33 | 47000 | 5 | 0 |
| lfr_n1000_o40_m20_s11 | 29 | 115.701189 | 33 | 49000 | 29 | 0 |
| lfr_n1000_o40_m20_s12 | 29 | 772.974334 | 33 | 47000 | 29 | 0 |
| lfr_n1000_o40_m50_s11 | 5 | 452.654325 | 33 | 45000 | 5 | 0 |
| lfr_n1000_o40_m50_s12 | 5 | 406.681500 | 33 | 39000 | 5 | 0 |

## 数值与原生选择规则

- 原生 FindComsByCV 选择 HOLV 最大值；初值 EstComs=2/MaxL=TFlt::Mn，按grid顺序严格 `MaxL < HOLV[c]` 更新，所以相等时保留首个。stdout每K score为 `%f` 六位小数，TAB为 `%g` 通常六位有效数字；真正选择发生在输出之前，使用内存double，不读取TAB。
- 本次所有已审score均finite/negative，非TFlt::Mn sentinel；stdout argmax与TAB argmax一致，头两名分差远大于打印舍入。称选K是由实际stdout和源码规则核验的结果，不声称TAB保存double全精度。完整所有K分数与原文件hash在JSON。
- m>50分支分数为3次holdout likelihood之和。holdout集合双向保存，因此LikelihoodHoldOut逐u遍历会双向计pair；不能将该值当最终全图训练loss、归属恢复指标或跨不同图归一分数。源码将非负HOL替换TFlt::Mn，本审计未见该sentinel。
- 每个K仅初始化一次；三fold MLE连续更新同一F，非三次独立重启。候选结束后选择K、RandomInit，再由main重新NeighborComInit最终fit。本报告记录原生语义，没有另加修复。

## 停止条件可事实确认的范围

- n1000的33次CV MLE每次恰为10000 vertex-update attempts。源码CV MaxIter=10*n=10000，而MLE的相对目标早停检查额外要求 iter>10000，所以此规模CV在到达MaxIter前无法触发容差早停。这是源码/日志共同支持的停止语义，不是新算法候选。
- 最终fit MaxIter=1000*n=1000000。已审final attempts均低于上限；按未改源码仅有的while内部break，可以推断因相对目标变化条件退出。该条件是 `CurL-PrevL <= .0001*abs(PrevL)`，目标下降也会满足；日志本身没有停止原因/精确最后差值，不能声称已证明收敛或最优。
- iterations包含每个节点尝试及跳过，非有效梯度更新次数；最终解码阈值sqrt(2m/n²)、MinSz3可能使输出群数小于选K，stdout明确记录omitted。不要把输出群数反推选K，更不把选K视为真实群数恢复。

## 文件、绘图依赖与时间单位

- native_.CV.likelihood.tab只有每K汇总likelihood；.plt是指向该表的gnuplot绘图脚本。两者均不是模型/affiliation/checkpoint，无节点cover可转换。native_cmtyvv.txt在最终fit后写，graph.gexf是后续图导出。
- 本快照 12/12 项stderr提示Cannot find GnuPlot，0项生成PNG；TAB/PLT仍已写，native继续返回成功且cover有效。这属于可选绘图环境限制，不算算法失败；本审计没有在计量期间安装依赖或改代码。
- TExeTm以clock()/CLOCKS_PER_SEC计CPU时间；native MLE completion、conductance、run time不是pipeline wall。进度[N sec]是time(NULL)整秒、每次MLE重置。不得从本审计补任何墙钟阶段时长；完整pipeline以runner保存值为准，原生绘图调用和导出成本已计入，不能事后免费移除。离线真标签评价按协议单列，不属于算法推断时间。

## 公平比较边界

- 本规模原生CV无容差早停的事实可以作为后续研发profile的依据，但改检查间隔/早停仍会改变训练政策，必须单独冻结、与简单少迭代/少K/增加预算控制比较，而不能作为免费兼容修复。这里未登记任何候选。
- 固定K oracle结果属于已知K面板，不是graph-only的免费primary arm；native规模网格也不是新机制。更快实现/缓存只有语义等价且同输出预算对照才可归为工程收益。
- 本审计只证实已完成n1000搜索路径；n5000超时CV不能称完整模型选择或评价未知cover，原失败保留。

逐项证据：cv-selection-audit.csv/json。可执行 `python3 work/setup/native/cv_selection_audit/audit_cv_selection.py` 更新同一派生报告，原始结果不修改。
