# 实验协议：先开发诊断，再独立确认

## 1. 比较对象

主任务是普通无向无权、仅拓扑的全图重叠社区检测。每张完整图只规范节点编号、去原输入重复无向边和自环；所有处理、孤立点、metadata范围记录。不得随机删点取得有利速度而仍称原图任务。

两种信息面板：
- `graph_only_native_K`：BigCLAM原生K搜索、Highway、Ego-splitting、SLPA，均不接收真K。
- `oracle_K`：NOCD-G和BigCLAM固定同一真实K，诊断已知模型大小时的归属学习。两者都能获知这个标量；真实成员列表不能传入。它不代表无监督自动选择K。

CPU与GPU、Python与C++的结果分别注明。新法如果改自某基线，必须同时提供同语言/后端版本的控制，不能只用工程实现差异论证新的算法复杂度。Highway纯Python和作者C++不混同；Ego公开第三方实现不等于作者的大规模平台。

## 2. 数据与阶段

`configs/protocol.json`提出24图development网格。LFR作者仓库的unweighted_undirected包显式支持-on/-om。使用time_seed.dat，生成器会自行递增seed，必须为每个case建立独立cwd并保存生成前/后文件。每个生成失败留记录；不通过不断换seed得到一个更容易的图。

LFR可能为满足约束调整群大小。保存statistics.dat和全部警告，报告真实n,m,degree,overlap及群大小。代码另报告“没有共同真群的边比例”，它不保证与原生mu统计定义完全一致，不能互相替代。

开发图是形成假设和修改算法的材料。它不是独立确认集。确认集使用211/212等预先指定新种子，只有算法和参数政策冻结后才运行。确认失败不得重新调参后仍称这批独立测试。

加入另一种生成机制/真实图之前，分别冻结其定义；它们不能作为一个LFR控制变量的额外重复。真实图的代理标签通常不完整：strict evaluator只适用于明确完整的标签；partial metadata不可将未列成员当负例。top5000社区是预筛集合，不是随机总体。不能利用完整真实标签选择参数、种子、threshold或停止点。

## 3. 完整标签的评价定义

设真实群T_a和预测群P_b，矩阵s_ab=2|T_a∩P_b|/(|T_a|+|P_b|)。用一对一Hungarian匹配最大化Σs_ab。未匹配群贡献0。

- matched macro precision = Σmatched s_ab / #predicted groups。
- matched macro recall = Σmatched s_ab / #true groups。
- matched macro F1 = 2Σmatched s_ab/(#predicted+#true)。
- membership micro：复用该匹配，TP=Σmatched|intersection|，分母是两边总membership数；不是另行优化micro的matching。
- overlap node：预测/真实membership数是否≥2，计算PR/F1。
- 至少两项正确归属召回：对真实重叠节点，matched正确归属数是否≥2。
- extra membership：正确匹配数r_i贡献max(r_i−1,0)，对应真实/预测归属数量扣除第一项后的总数。没有“天然第一/第二社团”的语义。
- 小群：真实群大小≤该图群大小25%分位值，报告平均matched F1，切点及组数同时报告。

预测重复群不去重：它们可骗取precision，故保留并让未匹配者受罚。群内重复节点按set处理并记账；空群不算社区，记录数量。缺失节点保持未覆盖，不补singleton或真标签。空真值不是合法恢复任务。无真实重叠时，额外归属召回记NA而不是人为赋1。

对于多重最优matching，固定输入顺序和库版本；macro最优值不变，但次级membership分解可能随匹配选择而异。重要诊断应检查tie敏感性，不能把任意一种匹配当唯一语义对应。

ONMI是额外指标。机器应加入一个明确版本的overlapping NMI实现并以perfect/permuted/complement/empty例子复核；不能用sklearn的非重叠NMI替代。本包目前返回明确的not implemented，而不是伪造0。

## 4. 时间与状态

主pipeline计时从新进程启动到最后cover写出，包含import/load、预处理、fit、decode、模型选择、checkpoint写出与失败尝试。下载/编译作为一次性setup另报。评价真标签的时间不算算法推断时间，但必须保留。图算法的重复安装不算每次推断。

`stage_seconds`可能嵌套：anchor时间通常包含在fit内，不能再加一次。GPU内部分阶段计时需要synchronize，外层process-wall自然包含退出前工作。RSS是0.2秒采样的process-tree RSS之和，共享页可能重复计；短瞬时峰值可能漏测。显存需额外测量。不能称该值为精确峰值。

COMPLETED表示返回了一个有效输出，不等于global optimum或已收敛。TIMEOUT/MEMORY_LIMIT/ERROR等独立记录。若有合法partial checkpoint，可以报告其预算内质量，但不能把它变成completed time。没有任何checkpoint就质量未知，不在成功条件均值中填0或填最优。

time-to-quality只使用实际saved checkpoints。观测到t时第一次过线是离散checkpoint crossing；不能线性插值、把超时预算当成功到达时间。真标签只能在offline评估crossing；不能因此让算法选最佳标签分数checkpoint作为输出。

`tools/summarize.py`给初始全结果/状态表和完成任务散点图；它不是宣称所有不同图的点构成一个统一Pareto前沿。正式分析必须按相同case、信息面板、硬件比较。完整状态分母与共同完成条件时间都报告，不给相关case套IID置信区间。

## 5. Development迭代纪律

最多两个单机制候选，每个最多四个配置。先写具体错误/开销trace、预测和失效条件，再改代码。简单控制必须包括与改动相关的“只是多算一点/保留更多seed/增加r/改数值精度/已有ego处理”。

不得：候选用更大K却不收费；新方法C++对旧方法Python后宣称算法复杂度优势；用不同decoder阈值但把收益全归给传播；偷看真overlap后改变每个图配置；把强对手安装失败判成算法失败。

若修复的是第三方库bug，须给所有相关arm同样的bugfix控制，算法身份注明。若新方法仅是已有方法的组合和常规实现优化，保留真实收益但不宣称新原理。

## 6. 阶段trace

不改变逻辑的低开销trace可记录：anchor IDs/数量、backbone边数、每轮membership候选/保留数、训练目标与数值状态、解码前后membership矩阵路径、各阶段wall time。真实标签映射在运行后做。

一次完整profile单独运行，防止instrumentation不同造成速度假象。追踪的目标是定位信息最早丢失的位置，而非证明全领域都存在该缺陷。无法获得某方法内部trace，不得臆测其内部病因。

## 7. 研究结论尺度

发现阶段的一个正例是线索；确认阶段的整体改善才可支持方法范围内结论。没有任何要求“某个天数内必须赢”。固定budget是执行管理，不是统计定理或发表阈值。

理论与实际改动匹配：等价缓存证明更新不变、近似传播给误差界、结构初始化给适用图类与反例。不强制每个算法都证明minimax，不把已知恒等式当新定理。
