# Goal mode：用真实质量—成本结果驱动社区发现算法研发

你是负责执行的研究工程Agent，而不是只写建议的顾问。请解压本包到一个独立工作区，按本任务书持续完成安装、运行、诊断、有限修改和验证。最终给实际结果和可复现文件，不要用另一份proposal代替实验。

## 0. 唯一目标与 authority

**目标：在图结构单输入的全图重叠社区检测中，找到一个可重放的质量—费用改进；若没有，给出完整负面结果和准确瓶颈。**

同预算更好，或同质量更快。不能只追求更低训练loss、更高modularity或更多输出社区。不得以“先证明一个顶会级新定理”为执行前置条件；也不得在只有普通工程优化时宣称发明了新原理。

当前最高authority是本文件、`docs/EXPERIMENT_PROTOCOL_ZH.md`和经宿主冻结的配置。`context`中的旧执行限制只是历史背景。本轮允许在既有授权机器的独立目录中下载安装公开代码/数据、编译、CPU运行及使用一块确实空闲的GPU、修改自己的候选实现并做必要小型证明检查。不要租算力、付费API、全局安装、改驱动、终止别人的作业、上传秘密/原始研究数据或自动push仓库。不要改原固定研究43×5数据、目标与结论。

不继续名额/CB/PL、BCSU、安全收缩、crossed-affiliation理论或residual fission。主线A为全图重叠检测；不自动切换为谱聚类、局部seed检索或新的观测模型。

## 1. 把问题固定，不预设新组件

强基线：BigCLAM（SNAP native）、NOCD-G（作者PyTorch图输入）、Ego-splitting（标明实现来源）、Highway（原生后端与CDlib Python区分）、SLPA（轻量控制）。

你的第一项科学产物是：哪些方法同预算更好、时间花在哪里、成员信息在哪一步丢掉。只有真实trace支持后，才选择一个修改。不要预先规定必须修anchor，不要把共享中心toy包装为新方法；已有ego-component方法解决该toy。

## 2. 自主执行与预算

从开始记录`work/state.json`，含started_at、deadline、phase、spent、下一条可运行命令。默认本轮总墙钟24小时，用户新指令优先。超过预算就保存并交付，不能无限运行“直到赢”。

先探测OS、编译器、Python、CPU、内存、GPU及活动进程。默认测量任务串行、1线程；单任务RAM不超过min(8GiB,可用RAM的35%)。图1000节点120秒、5000节点300秒。资源不足则在看质量结果之前统一下调并记录。GPU仅当用户机器确实授权且当前空闲时启用独立面板，最多1块、避免挤占其他任务；无GPU照常做CPU部分。

安装/source audit预算最多2小时；单依赖问题修复两次仍失败就保留BLOCKED，推进其他方法。不要因为一项下载失败放弃全部实验；不得用自写弱算法悄悄替代原生方法。若少于三个实质不同的OCD基线可用，保留可运行结果但不进入“击败领域强方法”的主张。

小错误、依赖补丁、格式问题、首次无收益无需反复询问用户。只有付费/权限、无法解析的原始数据授权、需要改变任务/数据/评价时才询问。中断或上下文切换前先写文件，不得仅报告内存中的结果或不可见内部路径。

## 3. 阶段一：让实验设施和基线真实跑起来

阅读README、source map及协议。执行：

```
bash START_HERE.sh
python tools/fetch_sources.py --only snap lfr nocd cdlib_highway karateclub
```

先检查LICENSE、ReadMe、实际CLI/API，再安装到隔离环境并构建。源码必须锁定commit和文件hash；对运行所需的兼容补丁保存diff，区分兼容性修复和算法改动。

特别核验：
- LFR必须来自支持重叠的作者包，-on/-om有效；time_seed.dat确定seed；不是NetworkX非重叠LFR。
- BigCLAM源码默认值与ReadMe并不完全一致；显式传入参数。当前源码固定内部seed，不存在随意杜撰的--seed；重复同一随机实现不能当多个独立seed。
- NOCD-G输入仅为A，禁止读节点属性或真实归属；真正的K只在oracle-K面板显式提供。作者PyTorch版与论文TensorFlow版要说明。
- Highway Python质量/trace测试不等于论文C++的时间；Ego第三方实现也不冒充原生分布式后端。
- 所有节点ID统一0..n-1，保留孤立点；upstream无法返回某些节点就报告coverage，不私自补真标签。

薄适配器尚未经过原生依赖运行，需要你做smoke核验。运行`tests`只证明基础设施，不代表原论文已复现。

## 4. 阶段二：冻结并运行24张开发图

完成smoke后，按`configs/protocol.json`冻结：
- n∈{1000,5000}，平均degree20，maxdegree50；
- overlap比例∈{0,0.2,0.4}，重叠节点2个归属；
- μ∈{0.2,0.5}，graph seeds∈{11,12}；
- degree exponent2、community exponent1、community size20..100。

保留24项生成任务，失败不换seed求一个成功图。生成器若改变community-size分布，保存其警告和实际统计。候选无效可全局重定协议，但必须在任何基线质量结果揭晓前，旧失败保留。

执行generate_lfr、prepare_plan、run_jobs、summarize，输出所有planned rows，不是只保存成功的行。初轮algorithm seed73；随机方法后续用74/75核验，固定seed原生程序只作重复计时。

主表graph-only/native-K：BigCLAM autoK、Ego、Highway、SLPA。补充oracle-K：NOCD-G和BigCLAM固定同一真K。不得跨信息/硬件面板给一个综合赢家。可在oracle-K面板再加入忽略K的算法，但必须同样披露。

真标签存`evaluation_only`，不传给训练adapter。K也只能由单独oracle面板注入。已知归属可用于事后开发trace，不可写进算法的case-specific选择规则。

主指标：一对一matched cover macro F1、固定匹配下的membership micro F1、overlap节点PR、正确恢复至少两个归属的召回、小群匹配F1；完整ONMI需另接已验证版本，不用普通partition NMI假装ONMI。

每个job记录输入哈希、source/配置、设备/线程、全部耗时、返回状态、cover与checkpoint；不能把超时当完成时间。训练loss仅供同目标优化诊断。

## 5. 阶段三：从真实trace选择一个瓶颈

先写`reports/BASELINE_REPORT_ZH.md`、`reports/FAILURE_MAP_ZH.md`，回答：
A. 第二归属是初始化就没有、稀疏化删掉、传播top-r剪掉，还是最终阈值丢掉？
B. 时间集中在邻居交集、seed选择、SpMM/更新、优化迭代、还是rounding/model-order search？
C. 简单增加预算、用原生优化实现、增加已有seed数、原有ego处理是否已经解决？

对每个有希望的现象写一个可复放trace，包含具体图、节点/群体、阶段数组和对应代码位置；如果没有稳定规律，报告没有找到，不编insight。

阶段数组的标签对照只在进程退出后做。完整timing可用低开销事件；详细profile单独复跑并计入研发开销，不能把profile开销只加在旧方法上。

## 6. 阶段四：最多两个单机制候选，不无限调参

每次只选择一个由结果支持的改动，例如某个信息丢失步骤或重复运算。先登记：
- 一句话观察；
- 为什么旧步骤会造成当前错误/开销；
- 修改哪一行或哪一原语；
- 预测哪些case改善、哪些不变、哪些可能退化；
- 相同参数/表示容量/重启次数/预算的简单控制。

最多探索两个不同机制，每个最多四个配置。不得把anchor+传播+loss一起改，不能按case_id、真群数、真overlap或测试标签分支。速度修复若是普通向量化/缓存，应当保留但如实标作工程改进；原理查重是正面结果后的必要检查，不是停止运行的借口。

候选在所有24个开发case保留原结果与失败，再检查74/75种子稳定性。不承诺候选必须赢。若没有任何一致方向，就以NO_REPRODUCIBLE_GAIN收束，保存诊断。

## 7. 阶段五：有可重复开发改善，才冻结确认实验

冻结一个候选、最强相关旧方法、简单控制、全部参数/模型选择/threshold/预算。新LFR graph seeds用211/212，algorithm seeds173/174/175；本包种子只是预指定，尚未运行。确认集任何反馈不再调方法；修改后该批即转为开发，不能二次称独立确认。

在预算内补一种不同生成机制与无社团/degree-only负例。其生成方式、规模和参数必须在读取候选得分前写明并锁定，不能事后只保留parity/共享中心等有利toy。

真实图的metadata下载/完整图运行只有在预算和许可证允许时执行。Amazon/DBLP的top5000是预筛代理标签，不能按完整ground truth计precision、把未标注成员当负例。现成strict evaluator会拒绝部分标签；须先定义正例检索/分组评价政策再评分。不能为了速度提取标签诱导子图而仍称原始全图任务。

## 8. 必须给用户的实物

- `reports/BASELINE_REPORT_ZH.md`：全部方法、版本、信息与硬件面板、全结果和失败；
- `reports/FAILURE_MAP_ZH.md`：一条或多条阶段trace与耗时证据；
- `reports/CANDIDATE_DECISION_ZH.md`：单点修改、简单对照、哪部分是已有工具；
- `reports/FINAL_REPORT_ZH.md`：是否改善质量—成本前沿及其边界；
- 结果CSV/JSON、cover/checkpoints、图哈希、冻结配置、源版本及补丁、raw logs；
- 一张按同信息/同硬件分面板的质量—时间图；有anytime checkpoint才画时间到质量，不插值杜撰；
- `DELIVERY.zip`与manifest，以及一条从环境到结果的重跑命令；
- `RESUME.md`：如预算或环境受阻，写准确下一条命令、已完成/未完成，不承诺不可见后台工作。

停止状态只能如实选择：IMPROVEMENT_CONFIRMED、DEV_SIGNAL_ONLY、NO_REPRODUCIBLE_GAIN、BLOCKED_ENV、BUDGET_EXHAUSTED。这些是本轮执行结论，不是论文录用判断。

**现在开始执行，不要只回答“计划如下”。目标不是强行得到一个赢家，而是让机器真正产出可核验的结果、算法trace和有边界的改进。**
