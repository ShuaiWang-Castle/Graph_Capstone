# 最终报告：完整负面结果与局部开发加速

**最终状态：NO_REPRODUCIBLE_GAIN。** 准确范围：本轮未获得通过事前冻结的全网格或有限范围准入规则的可重复质量—成本改进。NOCD sampled-CSR在n5000开发图上有三个算法种子一致的17.1480%–18.4766%配对中位加速，但n1000变慢且一个质量层未通过，未获准进入独立确认。不能把主状态理解成“没有任何局部正向观察”，也不能把局部信号提升为确认结果。

## 实际完成了什么

在普通无向无权、只用拓扑的全图重叠社区检测任务中，已执行启动脚本、隔离依赖安装、源/许可证核验与提交锁定、作者LFR/SNAP BigCLAM/Highway原生编译、实际适配器smoke、24张LFR开发图、全部正式任务和独立诊断。以下数量仅计正式比较，setup/smoke、六项基线profile及六项候选profile另存。

| 正式任务 | 计划 | 完成并评分 | 超时且无cover |
|---|---:|---:|---:|
| 九个初轮arm×24图，算法seed73 | 216 | 204 | 12 |
| 两个已有Ego强配置×24图 | 48 | 48 | 0 |
| C1四arm×24图×算法73/74/75 | 288 | 288 | 0 |
| 原作者NOCD seed73身份/费用重查 | 24 | 24 | 0 |
| **合计** | **576** | **564** | **12** |

图种子11/12，n1000/5000，指定重叠比例0/.2/.4、mu .2/.5、平均度20、max度50、群大小20–100；实际生成统计、警告、递增seed前后、图和完整truth哈希全部保留。不是用换图种子挑容易样本。真标签只用于离线评价和事后开发诊断，算法接口没有truth文件。oracle-K只传群数标量，不能混入native-K面板。

本轮真实墙钟起点2026-09-30T05:02:08.976173+00:00，唯一deadline 2026-10-01T05:02:08.976173+00:00；续接从未重置。资源在开发质量前冻结：测量串行、CPU线程设置1、采样RSS守卫1500MiB，n1000/n5000分别120/300秒。宿主Mac ARM64、16GB，无GPU实验；无付费服务、全局环境/驱动修改或远端push。时间、依赖与实际硬件细节留在metadata。

未执行独立确认LFR211/212、算法173/174/175、另一生成机制的正式图、degree-only正式负例、真实图、GPU或第二机制。确认集没有生成或参与调参。另一生成器只有预登记定义、小规模功能测试和未运行清单，不能当额外泛化结果。C1被冻结准入否决后，本轮在预算内完成负面交付，不无限运行到赢。

## 基线给出的事实

详细表见 `BASELINE_REPORT_ZH.md`。初轮BigCLAM auto-K在n5000的12项全部于300秒预算内CV超时，没有合法cover/checkpoint，质量未知；完成小图CV舍入CPU占原生总CPU中位94.51%。其K搜索信息预算不能由免费已知K替代。

Ego第三方通用自环检查使一个实际trace中每点只有一个persona，400真实重叠点预测重叠0，信息容量最早在邻域分量前丢失。去自环是已有修复；原min0碎片版本质量低，新增48项保留上游现成CC/Louvain/min5和PC/Leiden/min5配置，后者n5000 macro中位.7658、pipeline4.4347秒。这些是已有强控制，不是新机制。

已知K面板中，n5000的12/12同图，原生C++ BigCLAM都比历史原NOCD PyTorch更快且macro/micro更高；中位分别约9.8811秒/.8770/.8920与25.6049秒/.3514/.4333。不同实现栈是实用对照，不隔离证明算法复杂度。Highway作者C++、CDlib Python、第三方Ego与固定SLPA分别保留身份与完整成本，没有把文献成绩当本轮结果。

NOCD保存点诊断表明训练full loss和归属恢复有差距，9/24图的事后最佳macro saved point比实际返回点高≥.03；标签不能回选输出或停止。代理loss与modularity没有替代核心matched macro/membership micro指标。

## 唯一候选及准入失败

C1只改作者NOCD采样pair-dot的计算原语，比较原elementwise、现成BMM、现成sampled-CSR，以及原elementwise cap1000。全部CSR准备成本计入。GCN、初始化、sampling、Adam、正则、full-loss选点、patience、K、threshold0.5不改；入场函数/梯度、无RNG或输入突变及harness身份检查通过。已知双线性恒等式与常规原语调用没有被包装为新原理。

质量、状态与速度门槛在首个候选质量前冻结：每个n×算法seed的12个配对macro/micro平均差≥−.01，无新增不完整；相应范围各seed配对中位节时≥10%。大图限定范围也要求两种规模先通过质量。不能按图规模、case_id、真实overlap或标签路由后端。精确规则与SHA在 `configs/candidate_gate_v1.json`。

| 对elementwise500 | n1000，算法73/74/75 | n5000，算法73/74/75 | 决定 |
|---|---|---|---|
| BMM配对中位节时 | −3.5048% / −3.1835% / −2.1727% | −3.7270% / −4.4977% / −4.2055% | 平均质量合格，速度不合格 |
| CSR配对中位节时 | −7.9448% / −7.4585% / −7.3164% | +18.4766% / +17.1480% / +17.4531% | 局部加速，整体质量准入失败 |

CSR n1000/seed75 macro平均差 **−0.0108144000793**，低于冻结−.01，即使接近边界也不放宽。n5000各seed平均macro/micro在容差内，相对BMM亦快20.5499%–22.0266%；这些局部开发事实保留。CSR和BMM对elementwise分别有5、4项材料macro/micro退化；大图至少两正确归属召回仍有下降，对BMM亦有一项macro下降−.036739。完整退化索引与逐案差见 `CANDIDATE_DECISION_ZH.md` 及其引用路径，不声称逐例支配或严格同质量。

`selected_global_backend=BMM` 是质量合格项的排序结果；实际 `selected_claim_scope=none`、`confirmation_gate_open=false`。确认未运行。此实用gate不是统计非劣效定理；24相关图×三算法seed不当作72张IID图。

## 改善来自什么，瓶颈在哪里

全部72个case/seed的四arm初始embedding字节一致。大图36对CSR与elementwise实际更新数均相同，每更新forward/loss/backward成本中位降低20.4745%–21.6936%，支持真实训练计算收益，不能只用提前停止解释。相同更新次数仍不保证浮点轨迹一致。

六项候选独立profile全部完成，cover、initial/best embedding、检查epoch与full-loss数值均与原任务一致；elapsed/阶段计时和完整JSON分别保留。五个早期窗口中，pair整理小/大图10次约9.745/10.709ms，而elementwise大图gather/scatter self约34.629/21.557ms，CSR约0.176/0.159ms；已有BMM仍保留这类endpoint开销。小图CSR反而慢，准备/框架成本与数值轨迹质量漂移是具体阻碍。五步窗口、嵌套时钟及带instrumentation的wrapper计时不当作完整速度证明，也不据此宣布所有质量退化的因果机制。

cap500→1000的64/72对确实增加更新，8对没有；大图时间约1.80–1.89倍，macro平均差−.003090/+.003085/+.000315，micro +.006078/+.007118/+.005580。多算不能解释成等墙钟更好，也未解决原NOCD大图归属恢复弱的事实。

本轮只得到某后端、信息面板、机器与开发图上的工程观察；没有新增社区建模原理、数学新定理、独立新图确认或SOTA证据。除已有恒等式和功能等价核验外，理论/先例核查不足以支持新方法论文结论，因此不声称投稿就绪或顶会认可。

## 产物核验与复现边界

综合 `analysis/results.csv/json` 保存576个完整计划行，12超时不填造质量或完成时间。四个组目录保存逐任务评价/ONMI、匹配、完整结果、config/source/input hashes、实际命令与时间/RSS；各正式run目录保存预测、错误/超时日志、native输出、所有实际训练模型、embedding和saved cover/checkpoint。没有为无checkpoint方法捏造文件。

新增312项独立终态审计19,875 PASS、312 UNKNOWN、0 FAIL，7,379个保存评估cover一致；UNKNOWN仅为未从state重新运行GCN生成embedding/full loss，不能说完成即收敛或可以精确恢复训练RNG。另24图历史/镜像/新作者adapter模型与输出身份精确一致。

实际异地迁移3017个索引依赖文件，564项核心评分全部按固定Hungarian匹配在1e−12绝对容差内重算一致，12超时仍QUALITY_UNKNOWN。使用另一目录且禁止打开原位置indexed输入；guard是评分诊断钩子，不是安全sandbox。ONMI原值和来源hash核验，未在迁移工具重算；原隔离数值依赖仍被使用。这证明离线评价迁移，不证明全部方法重新训练或换平台性能。

实际源码tar恢复到另一个新目录，1,853文件内容/大小/权限校验通过；第三方论文PDF不入交付，URL/获取时间/hash记录保留，许可证和原提交锁定保留。`SOURCE_LOCK.json`中的早期NOT_MEASURED是冻结时历史状态，实际完成以正式raw result及最终报告为准。

`pipeline_seconds` 包含启动、导入、训练、等待native子程序、选点、checkpoint/cover写盘和退出；不含runner启动前的输入/source哈希核验及退出后合法性检查、结果保存、离线评价；adapter内部源码/binary核验仍在child pipeline内计费。进程树RSS约.2秒采样且共享页可能重复，瞬间峰值会漏测；短Highway值尤其不足以比较内存优胜。线程1是环境/实现设置，没有OS亲和性与线程数遥测。

`REPRODUCE.sh`提供新隔离工作区的精确锁依赖、归档恢复、强制原生重建、smoke与全开发重跑入口；仅语法审查及当前轮原生smoke成功，不宣称完整fresh环境脚本已再运行成功。复现步骤和实际验证路径见 `docs/REPRODUCIBILITY_ZH.md`。

## 实际交付

规范报告：本文件、`BASELINE_REPORT_ZH.md`、`FAILURE_MAP_ZH.md`、`CANDIDATE_DECISION_ZH.md`。规范总表：`analysis/results.csv/json`；分组per_job和所有质量—成本图、阶段profile、具体错误trace保留。源码版本/许可证/兼容补丁、原生实际binary、可重跑代码、关键日志、完整正式产物与两项实际迁移/恢复核验随 **DELIVERY.zip** 交付。ZIP逐文件SHA/CRC及嵌入replay/source绑定另行实测检查，SHA-256在 `DELIVERY.sha256.json`；最终独立范围/交付审阅与 `provenance/final_closeout.json` 保留。早期STAGE1/DIAGNOSTIC snapshot仅是历史快照，不能当本轮最终包。

本轮没有自动push，也没有修改打开的LaTeX论文。失败交付与局部正向观察均按原始证据保留。
