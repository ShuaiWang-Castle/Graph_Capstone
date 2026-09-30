# 原生基线报告：初轮216项及48补充已有强配置已终态

最终汇总更新：2026-09-30T09:35:34.120090+00:00。全部24张预定LFR有效；216项初轮任务已结束，204 COMPLETED且SCORED、12 TIMEOUT且无prediction，未删失败。

全部任务为普通无向无权全图，无属性输入；oracle-K面板额外提供群数标量，成员标签只用于离线评价/诊断；CPU线程设置1、串行，采样RSS守卫1500MiB/job；n1000/n5000分别120/300秒。Apple Silicon macOS，未使用CUDA/MPS/GPU，C++原生编译无OpenMP。

| 方法 / 信息面板 / n | 完成/计划 | 超时 | 完成条件pipeline中位秒 | 完成条件macro F1中位 | 完成条件micro F1中位 |
|---|---:|---:|---:|---:|---:|
| bigclam_native / graph_only_native_K / 1000 | 12/12 | 0 | 15.1774 | 0.8339 | 0.8335 |
| bigclam_native / graph_only_native_K / 5000 | 0/12 | 12 | NA | NA | NA |
| ego_karateclub / graph_only_native_K / 1000 | 12/12 | 0 | 0.2423 | 0.7913 | 0.8286 |
| ego_karateclub / graph_only_native_K / 5000 | 12/12 | 0 | 0.7376 | 0.3751 | 0.4992 |
| ego_karateclub_loopless_fix / graph_only_native_K / 1000 | 12/12 | 0 | 0.4361 | 0.0102 | 0.2215 |
| ego_karateclub_loopless_fix / graph_only_native_K / 5000 | 12/12 | 0 | 2.2320 | 0.0076 | 0.1634 |
| ego_sknetwork_fixed / graph_only_native_K / 1000 | 12/12 | 0 | 2.7078 | 0.0108 | 0.2322 |
| ego_sknetwork_fixed / graph_only_native_K / 5000 | 12/12 | 0 | 2.9872 | 0.0075 | 0.1641 |
| highway_native / graph_only_native_K / 1000 | 12/12 | 0 | 0.1314 | 0.5128 | 0.3589 |
| highway_native / graph_only_native_K / 5000 | 12/12 | 0 | 0.1967 | 0.1654 | 0.1720 |
| highway_python / graph_only_native_K / 1000 | 12/12 | 0 | 0.2692 | 0.4968 | 0.4489 |
| highway_python / graph_only_native_K / 5000 | 12/12 | 0 | 0.8406 | 0.0988 | 0.1745 |
| slpa_cdlib / graph_only_native_K / 1000 | 12/12 | 0 | 0.5236 | 0.5037 | 0.7533 |
| slpa_cdlib / graph_only_native_K / 5000 | 12/12 | 0 | 2.2306 | 0.5805 | 0.8561 |
| bigclam_oracleK / oracle_K / 1000 | 12/12 | 0 | 0.7149 | 0.8569 | 0.8561 |
| bigclam_oracleK / oracle_K / 5000 | 12/12 | 0 | 9.8811 | 0.8770 | 0.8920 |
| nocd_graph_oracleK / oracle_K / 1000 | 12/12 | 0 | 5.9667 | 0.9206 | 0.9418 |
| nocd_graph_oracleK / oracle_K / 5000 | 12/12 | 0 | 25.6049 | 0.3514 | 0.4333 |

上述中位数是完成条件下的描述性汇总，不能当24图整体赢家；尤其原生BigCLAM的5000节点质量未知。没有为相关图套IID置信区间。

规范逐case质量—成本表为 `analysis/baseline73_v2/results.csv/json`；匹配、补充ONMI、阶段数据在同目录。`paired/`保留528条同图、信息/CPU/线程/请求seed的配对行；非共同完成不计算完成时间比例，也不补质量。绘图按native-K与oracle-K分开，不把不同图的点当统一前沿。

SNAP author C++ BigCLAM autoK、作者PyTorch NOCD-G仅A/oracle-K、作者Highway C++与CDlib Python分别记录、Karate Club第三方CC/Python-Louvain原生及loopless控制、修复后的egosplit-sknetwork CC/Louvain/min0、固定CDlib SLPA均实际运行。精确源提交、许可证、依赖、源码/binary哈希、编译命令在provenance和work/setup。第三方Ego不冒充作者分布式平台；NOCD PyTorch不冒充论文TensorFlow成绩。

BigCLAM主面板只由n设置maxK=ceil(n/10)，min5/10 trials，实际11点每点3次CV；内部seed固定10。换请求seed是重复计时，不是独立算法随机重复。oracle-K只注入群数标量，两模型同K，不传成员列表。Highway确定性重复同样只用于计时。

修复的早期0.2秒计时地板在开发质量揭晓前完成，旧attempt保存。Ego自环、权重/CSR顺序/isolate已知修复独立登记；不计新机制或新原理。NOCD保持作者sampler、训练loss选点和停止比较，全部500个保存cover现已离线评分；24项返回cover与训练loss选点一致。完整模型状态只支持推断恢复，不含完整RNG训练续跑保障。

ONMI为固定NOCD来源McDaid NMI_max，经perfect/permuted/complement/empty及2000随机cover等价核验；补充稀疏评价只是工程修复，非OCD收益。空/零熵仍明确未知，不用partition NMI替代。

独立诊断6/6完成，6个输出cover与对应原baseline完全一致；两个NOCD initial/best embedding也字节相同。阶段profile费用只计研发，不覆盖原baseline时间。真实CV、Highway阶段数组、PyTorch内核和Ego trace见 `work/diagnostic_v2/`。

新增已有强配置已登记于 `configs/ego_existing_controls_v1.json`：同样bugfix下的原包PC/Leiden/min5默认，以及CC/Louvain/min5单独控制。原CC/Louvain/min0结果不变；新增48项全部COMPLETED且SCORED，质量—成本详见 `analysis/ego_controls73_v1/`。未计作新候选，未根据标签调过滤值。

本轮实际执行了源码/依赖安装、三项原生构建、功能smoke、24开发图、216初轮基线、6独立trace/profile及离线评价；48补充强配置已完成；C1四arm×三算法seed共288项完成，原作者seed73身份/费用重查24项完成。冻结准入失败，确认图未生成、未参与调参。

当前观察只支持CV搜索开销、Ego实现缺陷及NOCD采样loss中的张量复制/梯度开销；不宣称已改善质量—成本前沿。任何工程加速须同后端和强原语对照，不包装新原理。

## 已有Ego强配置补充结果

24图×2配置均完成；与旧min0/loopless结果分列，不能把改变现成过滤值归为新算法。

| 已有配置 / n | 完成/计划 | pipeline中位秒 | macro F1中位 | micro F1中位 |
|---|---:|---:|---:|---:|
| ego_sknetwork_CC_Louvain_min5 / 1000 | 12/12 | 2.5826 | 0.6569 | 0.7303 |
| ego_sknetwork_CC_Louvain_min5 / 5000 | 12/12 | 2.8856 | 0.5706 | 0.5972 |
| ego_sknetwork_defaults_fixed / 1000 | 12/12 | 2.8802 | 0.7372 | 0.7539 |
| ego_sknetwork_defaults_fixed / 5000 | 12/12 | 4.4347 | 0.7658 | 0.7867 |


## 已知K面板中的同图强基线边界

`analysis/baseline73_v2/paired/bigclam_vs_nocd_size_diagnosis.json` 逐图核对：n5000的12/12共同完成case上，原生C++ BigCLAM/oracle-K都严格更快，并且matched macro与micro F1都高于原始PyTorch NOCD；n1000仅2/12满足这三个条件。两个方法都只拿同一K标量、不拿成员列表。该事实来自本轮同图测量，属于不同实现栈的实用成本对照，不能据此隔离推断算法复杂度；内部BigCLAM seed10与NOCD请求seed73不是相同随机轨迹。

因此C1即使通过相对原NOCD的工程加速门槛，也不能直接声称改善整个方法集合的实用质量—成本前沿。必须保留这些强基线、具体图与信息面板边界。


## 成本与资源字段的实际含义

`pipeline_seconds` 从 runner 完成输入/source hash核验后、打开日志和创建适配器进程前计时，至适配器进程退出的专用wait线程记录止；包括进程导入、训练、等待原生子程序、模型选择、checkpoint/cover写入和退出。它不含runner启动前的输入/source哈希核验、退出后的cover合法性/hash与result保存，也不含离线标签评价；适配器内部的源码/binary核验属于child pipeline计费；整轮deadline仍按真实墙钟连续计。

`peak_tree_rss_bytes` 是约0.2秒间隔采样的进程树RSS最大观察值；1500MiB是采样守卫阈值，非OS硬内存限制，瞬间峰值可能漏测。24项初轮Highway C++中19项小于0.2秒，15项仅记录245760B，不能据此宣称真实峰值或内存优胜。原数值保留，不补造高峰。CPU 1线程是环境变量和实际实现设置；没有OS线程/亲和性遥测，不声称OS证实始终只有一个线程。完整源码审计见 `work/setup/measurement_semantics_audit/`。


## 全轮正式结果与候选原语控制

四组完整计划合计576项，564 COMPLETED且SCORED，12 TIMEOUT且质量未知；超时全是初轮BigCLAM auto-K/n5000。另有独立诊断、smoke和功能边界测试，不混入正式576项分母。综合 `analysis/results.csv/json` 保留每一个计划任务、原测量及评价字段、来源和失败；各组逐任务详细评分仍保留在对应 `analysis/<group>/per_job/`。

| 正式组 | 计划 | 完成且评分 | 超时无cover |
|---|---:|---:|---:|
| 初轮九arm/seed73 | 216 | 204 | 12 |
| 已有Ego强配置两arm/seed73 | 48 | 48 | 0 |
| C1四arm/算法73、74、75 | 288 | 288 | 0 |
| 原作者NOCD seed73身份/费用重查 | 24 | 24 | 0 |
| 合计 | 576 | 564 | 12 |

下表是C1三seed合并36项/规模的完成条件中位，不能用两个中位数的比代替逐图配对节时，也不能用中位质量代替冻结gate的逐层平均差。信息均为graph-only输入加oracle-K标量、CPU线程设置1、Python/PyTorch实现。

| 原语/cap | n | 完成/计划 | pipeline中位秒 | macro中位 | micro中位 |
|---|---:|---:|---:|---:|---:|
| nocd_pairdot_bmm500 | 1000 | 36/36 | 6.0145 | 0.9124 | 0.9355 |
| nocd_pairdot_bmm500 | 5000 | 36/36 | 26.8587 | 0.3564 | 0.4319 |
| nocd_pairdot_csr500 | 1000 | 36/36 | 6.2466 | 0.9108 | 0.9305 |
| nocd_pairdot_csr500 | 5000 | 36/36 | 21.4851 | 0.3487 | 0.4243 |
| nocd_pairdot_elementwise1000 | 1000 | 36/36 | 7.3648 | 0.9211 | 0.9350 |
| nocd_pairdot_elementwise1000 | 5000 | 36/36 | 47.7339 | 0.3475 | 0.4352 |
| nocd_pairdot_elementwise500 | 1000 | 36/36 | 5.8349 | 0.9211 | 0.9347 |
| nocd_pairdot_elementwise500 | 5000 | 36/36 | 25.8832 | 0.3539 | 0.4286 |

C1只改 sampled pair-dot；原语、full-loss选点和质量退化分列。CSR大图相对elementwise的逐图中位节时17.1480%–18.4766%，小图反而慢7.3164%–7.9448%。n1000/seed75的macro平均差−0.0108144000793未达事前≥−0.01门槛；BMM平均质量合格但六层均慢，独立确认未获准。完整决定与逐层表见 `CANDIDATE_DECISION_ZH.md`，不是整体同质量或独立确认结论。

在不同根目录已实际重算564合法cover的核心评价，全部在1e−12绝对容差内一致；12超时仍UNKNOWN。原源位置的indexed输入访问被诊断guard拒绝，ONMI仅检查原值/源码hash，没有重算。当前轮原生安装/构建/smoke已实际成功；这不等于完整新平台依赖安装和全轮再训练已经复现。证据分别在 `verification/portable_replay_full_v1/`、`verification/source_restore_v2/` 与 `docs/REPRODUCIBILITY_ZH.md`。
